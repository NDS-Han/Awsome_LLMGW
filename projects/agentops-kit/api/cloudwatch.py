"""
CloudWatch 트레이스/메트릭 조회 헬퍼.
AgentCore Observability에서 수집된 OpenTelemetry 데이터를 CloudWatch에서 조회한다.
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional

import boto3
from botocore.exceptions import ClientError

OBSERVABILITY_REGION = os.getenv("OBSERVABILITY_REGION") or os.getenv(
    "AGENTCORE_REGION", os.getenv("AWS_REGION", "us-east-1")
)
AGENT_ID = os.getenv("AGENTCORE_AGENT_ID", "")
OTEL_SPANS_LOG_GROUP = os.getenv("OTEL_SPANS_LOG_GROUP", "aws/spans")
RUNTIME_LOG_GROUP = os.getenv(
    "RUNTIME_LOG_GROUP",
    f"/aws/bedrock-agentcore/runtimes/{AGENT_ID}-DEFAULT" if AGENT_ID else "",
)
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

RUNTIME_NS = "AWS/Bedrock-AgentCore"
OTEL_NS = "bedrock-agentcore"


def _to_otel_hex(trace_id: str) -> str:
    """Any trace ID format → OTEL 32-hex."""
    if trace_id.startswith("1-"):
        parts = trace_id.split("-", 2)
        if len(parts) == 3:
            return parts[1] + parts[2]
    return trace_id.replace("-", "")


class CloudWatchHelper:
    """CloudWatch/OTEL에서 에이전트 트레이스와 메트릭을 조회."""

    _BATCH_CACHE_TTL_S = 30

    def __init__(self):
        self.cw_client = boto3.client("cloudwatch", region_name=OBSERVABILITY_REGION)
        self.logs_client = boto3.client("logs", region_name=OBSERVABILITY_REGION)
        self._otel_batch_cache: dict[str, list[dict]] = {}
        self._otel_trace_meta_cache: dict[str, dict] = {}
        self._otel_batch_ts: float = 0

    # ------------------------------------------------------------------
    # Public: trace list
    # ------------------------------------------------------------------

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """최근 트레이스 목록 (OTEL spans)."""
        otel_batch = self.get_otel_spans_batch()

        traces = []
        for otel_tid, spans in otel_batch.items():
            meta = self._otel_trace_meta_cache.get(otel_tid, {})
            total_dur = max(
                (s["start_ms"] + s["duration_ms"] for s in spans), default=0
            )
            has_error = any(s["status"] == "error" for s in spans)
            traces.append({
                "trace_id": otel_tid,
                "timestamp": meta.get("timestamp", ""),
                "duration_ms": round(total_dur, 1),
                "latency_ms": round(total_dur, 1),
                "status": "error" if has_error else "ok",
                "tools_used": meta.get("tools_used", []),
                "token_usage": meta.get("token_usage"),
                "model": meta.get("model", ""),
                "prompt_version": meta.get("prompt_version", ""),
                "session_id": meta.get("session_id", ""),
                "span_source": "otel",
            })

        traces.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
        return traces[:limit]

    # ------------------------------------------------------------------
    # Public: trace detail
    # ------------------------------------------------------------------

    def get_trace_detail(self, trace_id: str) -> Optional[dict]:
        """특정 트레이스의 스팬 트리 + 메타데이터 반환."""
        from api.telemetry import build_span_tree

        otel_hex = _to_otel_hex(trace_id)

        otel_spans = self.get_otel_spans(otel_hex)
        if not otel_spans:
            return None

        meta = self._extract_trace_metadata(otel_spans)
        cached_meta = self._otel_trace_meta_cache.get(otel_hex, {})
        timestamp = cached_meta.get("timestamp", "")
        span_tree = build_span_tree(otel_spans)
        self._link_tool_events(span_tree)
        return {
            "trace_id": trace_id,
            "timestamp": timestamp,
            "span_source": "otel",
            "spans": span_tree,
            **meta,
        }

    # ------------------------------------------------------------------
    # Public: aggregated metrics
    # ------------------------------------------------------------------

    def list_agents(self) -> list[dict]:
        """CloudWatch에서 사용 가능한 AgentCore Runtime 에이전트 목록 조회."""
        try:
            paginator = self.cw_client.get_paginator("list_metrics")
            agents: dict[str, dict] = {}
            for page in paginator.paginate(
                Namespace=RUNTIME_NS, MetricName="Invocations",
                Dimensions=[{"Name": "Operation", "Value": "InvokeAgentRuntime"}],
            ):
                for m in page.get("Metrics", []):
                    dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                    resource = dims.get("Resource", "")
                    name = dims.get("Name", "")
                    if resource and name and ":runtime/" in resource:
                        agent_id = resource.split(":runtime/")[-1]
                        if agent_id not in agents:
                            agents[agent_id] = {
                                "agent_id": agent_id,
                                "name": name.replace("::DEFAULT", ""),
                                "resource_arn": resource,
                            }
            result = list(agents.values())
            result.sort(key=lambda a: a["name"])
            return result
        except (ClientError, Exception):
            return []

    def get_aggregated_metrics(self, hours: int = 1, agent_id: Optional[str] = None) -> dict:
        """CloudWatch에서 집계 메트릭 조회."""
        try:
            return self._get_cw_metrics(hours, agent_id=agent_id)
        except (ClientError, Exception):
            return {
                "invocation_count": 0,
                "latency": {"avg": 0, "p50": 0, "p99": 0, "values": []},
                "tokens": {"total": 0, "avg_per_call": 0, "values": []},
                "cost": {"total_usd": 0, "values": []},
                "tool_calls": {},
                "source": "cloudwatch",
            }

    # ------------------------------------------------------------------
    # OTEL spans
    # ------------------------------------------------------------------

    def _query_log_group(self, log_group: str, query: str, hours: int = 6) -> list[dict]:
        """로그 그룹에서 CloudWatch Insights 쿼리 실행 → parsed records."""
        try:
            start_resp = self.logs_client.start_query(
                logGroupName=log_group,
                startTime=int((datetime.utcnow() - timedelta(hours=hours)).timestamp()),
                endTime=int(datetime.utcnow().timestamp()),
                queryString=query,
            )
            query_id = start_resp["queryId"]
            result = {}
            for _ in range(15):
                result = self.logs_client.get_query_results(queryId=query_id)
                if result["status"] in ("Complete", "Failed", "Cancelled"):
                    break
                time.sleep(0.5)
            if result.get("status") != "Complete":
                return []
            records = []
            for row in result.get("results", []):
                msg = next((f["value"] for f in row if f["field"] == "@message"), None)
                if not msg:
                    continue
                try:
                    parsed = json.loads(msg)
                    if isinstance(parsed, dict):
                        records.append(parsed)
                    elif isinstance(parsed, list):
                        records.extend(parsed)
                except (json.JSONDecodeError, TypeError):
                    continue
            return records
        except (ClientError, Exception):
            return []

    def get_otel_spans(self, trace_id: str) -> list[dict]:
        """aws/spans + runtime 로그에서 traceId로 OTEL spans + event logs 조회."""
        otel_hex = _to_otel_hex(trace_id)

        if self._otel_batch_cache and (
            time.time() - self._otel_batch_ts
        ) < self._BATCH_CACHE_TTL_S:
            cached = self._otel_batch_cache.get(otel_hex)
            if cached:
                return cached
        try:
            query = f"fields @message | filter @message like /{otel_hex}/ | limit 100"
            raw_spans = self._query_log_group(OTEL_SPANS_LOG_GROUP, query)

            if RUNTIME_LOG_GROUP:
                event_query = f"fields @message | filter @message like /{otel_hex}/ and @message like /gen_ai.system/ | limit 100"
                event_logs = self._query_log_group(RUNTIME_LOG_GROUP, event_query)
                raw_spans.extend(event_logs)

            if not raw_spans:
                return []

            earliest_nano = min(
                (int(s.get("startTimeUnixNano", 0)) for s in raw_spans if s.get("startTimeUnixNano")),
                default=0,
            )
            if earliest_nano:
                self._otel_trace_meta_cache.setdefault(otel_hex, {})["timestamp"] = (
                    datetime.utcfromtimestamp(earliest_nano / 1_000_000_000).isoformat()
                )

            return self._normalize_otel_spans(raw_spans)
        except (ClientError, Exception):
            return []

    def get_otel_spans_batch(self, hours: int = 6) -> dict[str, list[dict]]:
        """aws/spans에서 최근 스팬을 일괄 조회하여 traceId별로 그룹. TTL 캐시."""
        now = time.time()
        if self._otel_batch_cache and (
            now - self._otel_batch_ts
        ) < self._BATCH_CACHE_TTL_S:
            return self._otel_batch_cache

        try:
            query = (
                "fields @message"
                " | filter @message like /strands.telemetry/"
                " or @message like /botocore.bedrock/"
                " or @message like /invoke_agent/"
                " or @message like /execute_tool/"
                " or @message like /execute_event_loop/"
                " or @message like /gen_ai.system/"
                " | limit 500"
            )
            start_resp = self.logs_client.start_query(
                logGroupName=OTEL_SPANS_LOG_GROUP,
                startTime=int(
                    (datetime.utcnow() - timedelta(hours=hours)).timestamp()
                ),
                endTime=int(datetime.utcnow().timestamp()),
                queryString=query,
            )
            query_id = start_resp["queryId"]

            result = {}
            for _ in range(15):
                result = self.logs_client.get_query_results(queryId=query_id)
                if result["status"] in ("Complete", "Failed", "Cancelled"):
                    break
                time.sleep(0.5)

            if result.get("status") != "Complete":
                return {}

            raw_by_trace: dict[str, list[dict]] = {}
            for row in result.get("results", []):
                msg = next(
                    (f["value"] for f in row if f["field"] == "@message"), None
                )
                if not msg:
                    continue
                try:
                    parsed = json.loads(msg)
                    items = parsed if isinstance(parsed, list) else [parsed]
                except (json.JSONDecodeError, TypeError):
                    continue
                for span in items:
                    if not isinstance(span, dict):
                        continue
                    tid = span.get("traceId", "")
                    if tid:
                        raw_by_trace.setdefault(tid, []).append(span)

            grouped: dict[str, list[dict]] = {}
            trace_meta: dict[str, dict] = {}

            for tid, raw_spans in raw_by_trace.items():
                earliest_nano = min(
                    (
                        int(s.get("startTimeUnixNano", 0))
                        for s in raw_spans
                        if s.get("startTimeUnixNano")
                    ),
                    default=0,
                )
                normalized = self._normalize_otel_spans(raw_spans)
                grouped[tid] = normalized

                meta = self._extract_trace_metadata(normalized)
                if earliest_nano:
                    meta["timestamp"] = datetime.utcfromtimestamp(
                        earliest_nano / 1_000_000_000
                    ).isoformat()
                trace_meta[tid] = meta

            self._otel_batch_cache = grouped
            self._otel_trace_meta_cache = trace_meta
            self._otel_batch_ts = now
            return grouped
        except (ClientError, Exception):
            return {}

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def _extract_trace_metadata(self, spans: list[dict]) -> dict:
        """OTEL 스팬에서 trace-level 메타데이터 추출."""
        tools: list[str] = []
        input_tokens = 0
        output_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
        model = ""
        prompt_version = ""
        session_id = ""

        for s in spans:
            attrs = s.get("attributes", {})
            if not session_id:
                session_id = str(attrs.get("session.id", "") or "")

            if s["type"] == "tool":
                name = attrs.get(
                    "gen_ai.tool.name",
                    attrs.get("tool.name", s.get("name", "")),
                )
                if "execute_tool." in name:
                    name = name.split("execute_tool.", 1)[-1]
                if "___" in name:
                    name = name.split("___", 1)[-1]
                if name:
                    tools.append(name)

            if s["type"] == "llm":
                input_tokens += int(
                    attrs.get("gen_ai.usage.input_tokens", 0) or 0
                )
                output_tokens += int(
                    attrs.get("gen_ai.usage.output_tokens", 0) or 0
                )
                cache_creation_tokens += int(
                    attrs.get("gen_ai.usage.cache_creation_tokens", 0) or 0
                )
                cache_read_tokens += int(
                    attrs.get("gen_ai.usage.cache_read_tokens", 0) or 0
                )
                if not model:
                    model = str(
                        attrs.get("gen_ai.request.model", "") or ""
                    )
                if not prompt_version:
                    prompt_version = str(
                        attrs.get("gen_ai.prompt_version", "") or ""
                    )

        token_usage = None
        if input_tokens or output_tokens:
            token_usage = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
            }

        return {
            "tools_used": tools,
            "token_usage": token_usage,
            "model": model,
            "prompt_version": prompt_version,
            "session_id": session_id,
        }

    # ------------------------------------------------------------------
    # OTEL span normalization
    # ------------------------------------------------------------------

    def _normalize_otel_spans(self, raw_records: list[dict]) -> list[dict]:
        """OTEL 스팬 + event log records를 표준 span 형식으로 변환."""
        span_records = []
        event_log_records: list[dict] = []

        for r in raw_records:
            if r.get("startTimeUnixNano"):
                span_records.append(r)
            elif r.get("severityNumber") is not None and r.get("spanId"):
                event_log_records.append(r)

        all_starts = []
        for s in span_records:
            start_nano = s.get("startTimeUnixNano")
            if start_nano:
                all_starts.append(int(start_nano))
        trace_start_nano = min(all_starts) if all_starts else 0

        events_by_span: dict[str, list[dict]] = {}
        for ev in event_log_records:
            sid = ev.get("spanId", "")
            if not sid:
                continue
            ts_nano = int(ev.get("observedTimeUnixNano", 0))
            ts_ms = round((ts_nano - trace_start_nano) / 1_000_000, 1) if trace_start_nano else 0

            body = ev.get("body", {})
            if isinstance(body, dict):
                content = body.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            parts.append(item.get("text", json.dumps(item, ensure_ascii=False)))
                        else:
                            parts.append(str(item))
                    body_text = "\n".join(parts)
                elif content:
                    body_text = str(content)
                else:
                    tool_calls = body.get("tool_calls", [])
                    tool_result = body.get("toolResult", {})
                    if tool_calls:
                        body_text = json.dumps(tool_calls, ensure_ascii=False)[:2000]
                    elif tool_result:
                        body_text = json.dumps(tool_result, ensure_ascii=False)[:2000]
                    else:
                        body_text = json.dumps(body, ensure_ascii=False)[:2000] if body else ""
            else:
                body_text = str(body)[:2000] if body else ""

            ev_attrs = ev.get("attributes", {})
            scope = ev.get("scope", {})
            scope_name = scope.get("name", "") if isinstance(scope, dict) else ""
            event_name = "gen_ai.message"
            if "bedrock-runtime" in scope_name and isinstance(body, dict):
                if body.get("toolResult"):
                    event_name = "gen_ai.tool.message"
                elif "message" in body and ("index" in body or "finish_reason" in body):
                    finish = body.get("finish_reason", "")
                    msg_content = body.get("message", {})
                    if isinstance(msg_content, dict):
                        msg_content = msg_content.get("content", [])
                    if finish == "tool_use" or (
                        isinstance(msg_content, list)
                        and self._content_has_key(msg_content, "toolUse")
                    ):
                        event_name = "gen_ai.tool_call"
                    else:
                        event_name = "gen_ai.choice"
                elif body.get("content") and isinstance(body["content"], list):
                    if self._content_has_key(body["content"], "toolResult"):
                        event_name = "gen_ai.tool.message"
                    elif self._content_has_key(body["content"], "toolUse"):
                        event_name = "gen_ai.tool_call"
                    else:
                        event_name = "gen_ai.input.message"

            events_by_span.setdefault(sid, []).append({
                "name": event_name,
                "timestamp_ms": ts_ms,
                "attributes": ev_attrs if isinstance(ev_attrs, dict) else {},
                "body": body_text[:4000],
            })

        spans = []
        for s in span_records:
            start_nano = int(s.get("startTimeUnixNano", 0))
            duration_nano = int(s.get("durationNano", 0))
            name = s.get("name", "unknown")
            attrs_raw = s.get("attributes", {})

            if isinstance(attrs_raw, list):
                attrs = {}
                for a in attrs_raw:
                    k = a.get("key", "")
                    v = a.get("value", {})
                    if isinstance(v, dict):
                        attrs[k] = (
                            v.get("stringValue")
                            or v.get("intValue")
                            or v.get("doubleValue")
                            or v.get("boolValue", "")
                        )
                    else:
                        attrs[k] = v
            else:
                attrs = dict(attrs_raw)

            scope_name = (
                s.get("scope", {}).get("name", "")
                if isinstance(s.get("scope"), dict)
                else str(s.get("scope", ""))
            )
            if not self._is_agent_span(name, attrs, scope_name):
                continue
            span_type = self._classify_otel_span(name, attrs, scope_name)

            status_obj = s.get("status", {})
            status_code = (
                status_obj.get("code", "OK")
                if isinstance(status_obj, dict)
                else "OK"
            )

            inline_events = self._parse_otel_events(
                s.get("events", []), trace_start_nano
            )
            log_events = events_by_span.get(s.get("spanId", ""), [])
            all_events = inline_events + log_events

            spans.append(
                {
                    "span_id": s.get("spanId", ""),
                    "parent_span_id": s.get("parentSpanId"),
                    "name": name,
                    "type": span_type,
                    "start_ms": round(
                        (start_nano - trace_start_nano) / 1_000_000, 1
                    ),
                    "duration_ms": round(duration_nano / 1_000_000, 1),
                    "status": "error" if status_code == "ERROR" else "ok",
                    "attributes": attrs,
                    "events": all_events,
                    "error": None,
                }
            )

        return spans

    @staticmethod
    def _collect_all_spans(tree: list[dict]) -> list[dict]:
        """트리에서 모든 span을 flat하게 수집 (참조 유지)."""
        result = []
        for s in tree:
            result.append(s)
            result.extend(CloudWatchHelper._collect_all_spans(s.get("subsegments", [])))
        return result

    @staticmethod
    def _link_tool_events(tree: list[dict]) -> None:
        """LLM span의 tool_call/tool.message 이벤트를 매칭되는 tool span에 복사."""
        all_spans = CloudWatchHelper._collect_all_spans(tree)

        tool_call_events: dict[str, dict] = {}
        tool_result_events: dict[str, dict] = {}

        for s in all_spans:
            for ev in s.get("events", []):
                body = ev.get("body", "")
                if ev["name"] == "gen_ai.tool_call" and "toolUse" in body:
                    try:
                        idx = body.index("{\"toolUse\"")
                        parsed = json.loads(body[idx:])
                        tool_use_id = parsed.get("toolUse", {}).get("toolUseId", "")
                        if tool_use_id:
                            tool_call_events[tool_use_id] = ev
                    except (json.JSONDecodeError, ValueError):
                        pass
                elif ev["name"] == "gen_ai.tool.message" and "toolResult" in body:
                    try:
                        parsed = json.loads(body)
                        tool_use_id = parsed.get("toolResult", {}).get("toolUseId", "")
                        if tool_use_id:
                            tool_result_events[tool_use_id] = ev
                    except (json.JSONDecodeError, ValueError):
                        pass

        if not tool_call_events and not tool_result_events:
            return

        for s in all_spans:
            if s["type"] != "tool":
                continue
            call_id = s.get("attributes", {}).get("gen_ai.tool.call.id", "")
            if not call_id:
                continue
            matched = []
            if call_id in tool_call_events:
                matched.append(tool_call_events[call_id])
            if call_id in tool_result_events:
                matched.append(tool_result_events[call_id])
            if matched:
                s["events"] = list(s.get("events", [])) + matched

    @staticmethod
    def _extract_otel_attr_value(v):
        if isinstance(v, dict):
            return (
                v.get("stringValue")
                or v.get("intValue")
                or v.get("doubleValue")
                or v.get("boolValue", "")
            )
        return v

    @staticmethod
    def _parse_otel_events(raw_events: list, trace_start_nano: int) -> list[dict]:
        """OTEL span events를 파싱. gen_ai.content.prompt/completion 포함."""
        if not raw_events:
            return []
        events = []
        for ev in raw_events:
            if not isinstance(ev, dict):
                continue
            name = ev.get("name", "")
            ts_nano = int(ev.get("timeUnixNano", 0))
            ts_ms = round((ts_nano - trace_start_nano) / 1_000_000, 1) if trace_start_nano else 0

            ev_attrs_raw = ev.get("attributes", [])
            ev_attrs = {}
            if isinstance(ev_attrs_raw, list):
                for a in ev_attrs_raw:
                    k = a.get("key", "")
                    ev_attrs[k] = CloudWatchHelper._extract_otel_attr_value(a.get("value", ""))
            elif isinstance(ev_attrs_raw, dict):
                ev_attrs = ev_attrs_raw

            raw_body = ev.get("body")
            if isinstance(raw_body, dict):
                content = raw_body.get("content", "")
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            parts.append(item.get("text", str(item)))
                        else:
                            parts.append(str(item))
                    body = "\n".join(parts)
                else:
                    body = str(content)
            elif raw_body:
                body = str(raw_body)
            else:
                body = ev_attrs.get("gen_ai.content", "") or ev_attrs.get("body", "")

            events.append({
                "name": name,
                "timestamp_ms": ts_ms,
                "attributes": ev_attrs,
                "body": str(body)[:4000],
            })
        return events

    @staticmethod
    def _content_has_key(content_list: list, key: str) -> bool:
        """content 리스트 안의 text JSON에서 특정 키 존재 여부 확인."""
        for item in content_list:
            if isinstance(item, dict):
                if key in item:
                    return True
                text = item.get("text", "")
                if isinstance(text, str) and f'"{key}"' in text:
                    return True
        return False

    _AGENT_SCOPES = {
        "strands.telemetry.tracer",
        "opentelemetry.instrumentation.botocore.bedrock-runtime",
    }

    @staticmethod
    def _is_agent_span(name: str, attrs: dict, scope_name: str) -> bool:
        """AgentCore 관련 스팬인지 판별 (allowlist)."""
        if scope_name in CloudWatchHelper._AGENT_SCOPES:
            return True
        if attrs.get("gen_ai.operation.name"):
            return True
        if scope_name == "" and ("invoke_agent" in name or "execute_" in name):
            return True
        return False

    @staticmethod
    def _classify_otel_span(name: str, attrs: dict, scope_name: str = "") -> str:
        """OTEL 스팬 타입 분류."""
        op_name = attrs.get("gen_ai.operation.name", "")
        if name.startswith("execute_tool") or op_name == "execute_tool":
            return "tool"
        if name.startswith("invoke_agent") or op_name == "invoke_agent":
            return "interaction"
        if op_name == "execute_event_loop_cycle":
            return "interaction"
        if "bedrock-runtime" in scope_name or op_name == "chat":
            return "llm"
        return "other"

    # ------------------------------------------------------------------
    # CloudWatch metrics
    # ------------------------------------------------------------------

    def _get_cw_metrics(self, hours: int, agent_id: Optional[str] = None) -> dict:
        """CloudWatch에서 AgentCore 메트릭 조회.

        두 네임스페이스를 사용:
        - AWS/Bedrock-AgentCore: Runtime 메트릭 (Invocations, Latency)
        - bedrock-agentcore: OTEL 메트릭 (token usage, tool calls, LLM duration)
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        period = 300

        effective_agent_id = agent_id or AGENT_ID
        runtime_arn = f"arn:aws:bedrock-agentcore:{OBSERVABILITY_REGION}:{self._get_account_id()}:runtime/{effective_agent_id}"
        runtime_name = effective_agent_id.rsplit("-", 1)[0] + "::DEFAULT" if "-" in effective_agent_id else effective_agent_id + "::DEFAULT"

        runtime_dims = [
            {"Name": "Resource", "Value": runtime_arn},
            {"Name": "Operation", "Value": "InvokeAgentRuntime"},
            {"Name": "Name", "Value": runtime_name},
        ]

        model_id = BEDROCK_MODEL_ID
        token_dims_base = [
            {"Name": "server.address", "Value": f"bedrock-runtime.{OBSERVABILITY_REGION}.amazonaws.com"},
            {"Name": "gen_ai.operation.name", "Value": "chat"},
            {"Name": "server.port", "Value": "443"},
            {"Name": "gen_ai.request.model", "Value": model_id},
            {"Name": "gen_ai.system", "Value": "aws.bedrock"},
        ]
        token_input_dims = token_dims_base + [{"Name": "gen_ai.token.type", "Value": "input"}]
        token_output_dims = token_dims_base + [{"Name": "gen_ai.token.type", "Value": "output"}]
        llm_duration_dims = token_dims_base

        runtime_service_dims = [
            {"Name": "Resource", "Value": runtime_arn},
            {"Name": "Service", "Value": "AgentCore.Runtime"},
            {"Name": "Name", "Value": runtime_name},
        ]

        queries = [
            {
                "Id": "invocations",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Invocations", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "latency_avg",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Latency", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Average",
                },
            },
            {
                "Id": "latency_p50",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Latency", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "p50",
                },
            },
            {
                "Id": "latency_p99",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Latency", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "p99",
                },
            },
            {
                "Id": "errors",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Errors", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "user_errors",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "UserErrors", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "system_errors",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "SystemErrors", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "throttles",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Throttles", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "duration_avg",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "Duration", "Dimensions": runtime_dims},
                    "Period": period, "Stat": "Average",
                },
            },
            {
                "Id": "cpu_hours",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "CPUUsed-vCPUHours", "Dimensions": runtime_service_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "memory_hours",
                "MetricStat": {
                    "Metric": {"Namespace": RUNTIME_NS, "MetricName": "MemoryUsed-GBHours", "Dimensions": runtime_service_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "token_input",
                "MetricStat": {
                    "Metric": {"Namespace": OTEL_NS, "MetricName": "gen_ai.client.token.usage", "Dimensions": token_input_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "token_output",
                "MetricStat": {
                    "Metric": {"Namespace": OTEL_NS, "MetricName": "gen_ai.client.token.usage", "Dimensions": token_output_dims},
                    "Period": period, "Stat": "Sum",
                },
            },
            {
                "Id": "llm_duration",
                "MetricStat": {
                    "Metric": {"Namespace": OTEL_NS, "MetricName": "gen_ai.client.operation.duration", "Dimensions": llm_duration_dims},
                    "Period": period, "Stat": "Average",
                },
            },
        ]

        response = self.cw_client.get_metric_data(
            MetricDataQueries=queries,
            StartTime=start_time,
            EndTime=end_time,
        )

        results_map: dict[str, list[dict]] = {}
        for r in response.get("MetricDataResults", []):
            rid = r.get("Id", "")
            points = []
            for ts, val in zip(r.get("Timestamps", []), r.get("Values", [])):
                points.append({"timestamp": ts.isoformat(), "value": val})
            points.sort(key=lambda p: p["timestamp"])
            results_map[rid] = points

        def _last_or(key, default=0):
            pts = results_map.get(key, [])
            return pts[-1]["value"] if pts else default

        def _sum_of(key):
            return sum(p["value"] for p in results_map.get(key, []))

        invocation_count = int(_sum_of("invocations"))
        total_input = int(_sum_of("token_input"))
        total_output = int(_sum_of("token_output"))

        tool_calls = self._get_tool_call_metrics(start_time, end_time, period)
        tool_durations = self._get_tool_duration_metrics(start_time, end_time, period)
        event_loop = self._get_event_loop_metrics(start_time, end_time, period)

        cost_usd = self._estimate_cost(total_input, total_output)
        cost_values = []
        input_pts = results_map.get("token_input", [])
        output_pts = results_map.get("token_output", [])
        out_by_ts = {p["timestamp"]: p["value"] for p in output_pts}
        for p in input_pts:
            ts = p["timestamp"]
            inp = p["value"]
            out = out_by_ts.get(ts, 0)
            cost_values.append({"timestamp": ts, "value": self._estimate_cost(int(inp), int(out))})

        total_errors = int(_sum_of("errors"))
        error_rate = round(total_errors / max(invocation_count, 1) * 100, 1)

        avg_llm_duration = round(_last_or("llm_duration"), 1)
        avg_total_latency = round(_last_or("latency_avg"), 1)
        llm_ratio = round(avg_llm_duration / max(avg_total_latency, 1) * 100, 1) if avg_total_latency > 0 else 0

        return {
            "invocation_count": invocation_count,
            "latency": {
                "avg": avg_total_latency,
                "p50": round(_last_or("latency_p50"), 1),
                "p99": round(_last_or("latency_p99"), 1),
                "values": results_map.get("latency_avg", [])[-20:],
            },
            "tokens": {
                "total": total_input + total_output,
                "input": total_input,
                "output": total_output,
                "avg_per_call": round(
                    (total_input + total_output) / max(invocation_count, 1)
                ),
                "values": results_map.get("token_input", [])[-20:],
            },
            "cost": {
                "total_usd": round(cost_usd, 6),
                "values": cost_values[-20:],
            },
            "errors": {
                "total": total_errors,
                "user_errors": int(_sum_of("user_errors")),
                "system_errors": int(_sum_of("system_errors")),
                "throttles": int(_sum_of("throttles")),
                "error_rate": error_rate,
                "values": results_map.get("errors", [])[-20:],
            },
            "duration": {
                "avg_total_ms": avg_total_latency,
                "avg_llm_ms": avg_llm_duration,
                "llm_ratio_pct": llm_ratio,
                "avg_duration_ms": round(_last_or("duration_avg"), 1),
                "values": results_map.get("duration_avg", [])[-20:],
            },
            "compute": {
                "cpu_vcpu_hours": round(_sum_of("cpu_hours"), 6),
                "memory_gb_hours": round(_sum_of("memory_hours"), 6),
            },
            "event_loop": event_loop,
            "tool_calls": tool_calls,
            "tool_durations": tool_durations,
            "source": "cloudwatch",
        }

    def _get_account_id(self) -> str:
        if not hasattr(self, "_account_id"):
            sts = boto3.client("sts", region_name=OBSERVABILITY_REGION)
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    def _get_tool_call_metrics(
        self, start_time: datetime, end_time: datetime, period: int
    ) -> dict[str, int]:
        """bedrock-agentcore에서 strands.tool.call_count를 tool_name별로 집계."""
        try:
            paginator = self.cw_client.get_paginator("list_metrics")
            tool_dims_list = []
            for page in paginator.paginate(
                Namespace=OTEL_NS, MetricName="strands.tool.call_count"
            ):
                for m in page.get("Metrics", []):
                    dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                    if "tool_name" in dims:
                        tool_dims_list.append(m["Dimensions"])

            if not tool_dims_list:
                return {}

            seen_tools: set[str] = set()
            unique_dims = []
            for dims in tool_dims_list:
                tool_name = next(d["Value"] for d in dims if d["Name"] == "tool_name")
                if tool_name not in seen_tools:
                    seen_tools.add(tool_name)
                    unique_dims.append(dims)

            queries = []
            tool_id_map: dict[str, str] = {}
            for i, dims in enumerate(unique_dims):
                tool_name = next(d["Value"] for d in dims if d["Name"] == "tool_name")
                qid = f"tool_{i}"
                tool_id_map[qid] = tool_name.split("___")[-1] if "___" in tool_name else tool_name
                queries.append({
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {"Namespace": OTEL_NS, "MetricName": "strands.tool.call_count", "Dimensions": dims},
                        "Period": period, "Stat": "Sum",
                    },
                })

            result: dict[str, int] = {}
            for batch_start in range(0, len(queries), 10):
                batch = queries[batch_start:batch_start + 10]
                resp = self.cw_client.get_metric_data(
                    MetricDataQueries=batch,
                    StartTime=start_time,
                    EndTime=end_time,
                )
                for r in resp.get("MetricDataResults", []):
                    rid = r.get("Id", "")
                    total = sum(r.get("Values", []))
                    if total > 0 and rid in tool_id_map:
                        name = tool_id_map[rid]
                        result[name] = result.get(name, 0) + int(total)

            return result
        except (ClientError, Exception):
            return {}

    def _get_tool_duration_metrics(
        self, start_time: datetime, end_time: datetime, period: int
    ) -> dict[str, float]:
        """bedrock-agentcore에서 strands.tool.duration을 tool_name별로 집계 (평균 ms)."""
        try:
            paginator = self.cw_client.get_paginator("list_metrics")
            seen_tools: set[str] = set()
            unique_dims = []
            for page in paginator.paginate(
                Namespace=OTEL_NS, MetricName="strands.tool.duration"
            ):
                for m in page.get("Metrics", []):
                    dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
                    tool_name = dims.get("tool_name", "")
                    if tool_name and tool_name not in seen_tools:
                        seen_tools.add(tool_name)
                        unique_dims.append(m["Dimensions"])

            if not unique_dims:
                return {}

            queries = []
            tool_id_map: dict[str, str] = {}
            for i, dims in enumerate(unique_dims):
                tool_name = next(d["Value"] for d in dims if d["Name"] == "tool_name")
                qid = f"td_{i}"
                tool_id_map[qid] = tool_name.split("___")[-1] if "___" in tool_name else tool_name
                queries.append({
                    "Id": qid,
                    "MetricStat": {
                        "Metric": {"Namespace": OTEL_NS, "MetricName": "strands.tool.duration", "Dimensions": dims},
                        "Period": period, "Stat": "Average",
                    },
                })

            result: dict[str, list[float]] = {}
            for batch_start in range(0, len(queries), 10):
                batch = queries[batch_start:batch_start + 10]
                resp = self.cw_client.get_metric_data(
                    MetricDataQueries=batch,
                    StartTime=start_time,
                    EndTime=end_time,
                )
                for r in resp.get("MetricDataResults", []):
                    rid = r.get("Id", "")
                    vals = r.get("Values", [])
                    if vals and rid in tool_id_map:
                        name = tool_id_map[rid]
                        result.setdefault(name, []).extend(vals)

            return {name: round(sum(vals) / len(vals), 1) for name, vals in result.items() if vals}
        except (ClientError, Exception):
            return {}

    def _get_event_loop_metrics(
        self, start_time: datetime, end_time: datetime, period: int
    ) -> dict:
        """bedrock-agentcore에서 strands.event_loop 메트릭 집계."""
        try:
            cycle_count_dims = []
            cycle_duration_dims = []
            paginator = self.cw_client.get_paginator("list_metrics")
            for page in paginator.paginate(Namespace=OTEL_NS, MetricName="strands.event_loop.cycle_count"):
                for m in page.get("Metrics", []):
                    cycle_count_dims.append(m["Dimensions"])
            for page in paginator.paginate(Namespace=OTEL_NS, MetricName="strands.event_loop.cycle_duration"):
                for m in page.get("Metrics", []):
                    cycle_duration_dims.append(m["Dimensions"])

            total_cycles = 0
            total_duration_vals: list[float] = []
            num_invocations = max(len(cycle_count_dims), 1)

            if cycle_count_dims:
                queries = []
                for i, dims in enumerate(cycle_count_dims[:20]):
                    queries.append({
                        "Id": f"cc_{i}",
                        "MetricStat": {
                            "Metric": {"Namespace": OTEL_NS, "MetricName": "strands.event_loop.cycle_count", "Dimensions": dims},
                            "Period": period, "Stat": "Sum",
                        },
                    })
                for batch_start in range(0, len(queries), 10):
                    batch = queries[batch_start:batch_start + 10]
                    resp = self.cw_client.get_metric_data(
                        MetricDataQueries=batch, StartTime=start_time, EndTime=end_time,
                    )
                    for r in resp.get("MetricDataResults", []):
                        total_cycles += int(sum(r.get("Values", [])))

            if cycle_duration_dims:
                queries = []
                for i, dims in enumerate(cycle_duration_dims[:20]):
                    queries.append({
                        "Id": f"cd_{i}",
                        "MetricStat": {
                            "Metric": {"Namespace": OTEL_NS, "MetricName": "strands.event_loop.cycle_duration", "Dimensions": dims},
                            "Period": period, "Stat": "Average",
                        },
                    })
                for batch_start in range(0, len(queries), 10):
                    batch = queries[batch_start:batch_start + 10]
                    resp = self.cw_client.get_metric_data(
                        MetricDataQueries=batch, StartTime=start_time, EndTime=end_time,
                    )
                    for r in resp.get("MetricDataResults", []):
                        total_duration_vals.extend(r.get("Values", []))

            avg_cycles_per_invocation = round(total_cycles / num_invocations, 1) if total_cycles else 0
            avg_cycle_duration = round(sum(total_duration_vals) / len(total_duration_vals), 1) if total_duration_vals else 0

            return {
                "total_cycles": total_cycles,
                "avg_cycles_per_invocation": avg_cycles_per_invocation,
                "avg_cycle_duration_ms": avg_cycle_duration,
            }
        except (ClientError, Exception):
            return {"total_cycles": 0, "avg_cycles_per_invocation": 0, "avg_cycle_duration_ms": 0}

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
        """토큰 수에서 비용 추정 (Sonnet 4 기준, USD per 1M tokens)."""
        return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000


cw_helper = CloudWatchHelper()
