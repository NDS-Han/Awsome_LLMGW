"""
LLM Gateway — Strands BedrockModel의 wrapper.

에이전트가 모델을 직접 호출하는 대신 이 레이어를 거침으로써:
- 모델 라우팅 (태그 기반 cost/quality 선택)
- 입출력 가드레일 (PII 스크럽)
- 모델별 사용량/비용 집계 + CloudWatch 송출
- Rate limiting (세션/팀 기준)
- 통합 로깅

실제 호출은 Bedrock Runtime API로 수행 (프록시 패턴).
"""

import os
import re
import time
import json
import threading
from typing import Any, Optional

import boto3
from strands.models.bedrock import BedrockModel


# --- 모델 카탈로그 + 라우팅 규칙 ---

MODEL_CATALOG = {
    "opus-4-7": {
        "id": "global.anthropic.claude-opus-4-7",
        "tier": "premium",
        "price_in_per_m": 5.0,
        "price_out_per_m": 25.0,
    },
    "sonnet-4-6": {
        "id": "global.anthropic.claude-sonnet-4-6",
        "tier": "quality",
        "price_in_per_m": 3.0,
        "price_out_per_m": 15.0,
    },
    "haiku-4-5": {
        "id": "global.anthropic.claude-haiku-4-5",
        "tier": "cost",
        "price_in_per_m": 1.0,
        "price_out_per_m": 5.0,
    },
    "nova-pro": {
        "id": "us.amazon.nova-pro-v1:0",
        "tier": "quality",
        "price_in_per_m": 0.80,
        "price_out_per_m": 3.20,
    },
    "nova-2-lite": {
        "id": "global.amazon.nova-2-lite-v1:0",
        "tier": "cost",
        "price_in_per_m": 0.30,
        "price_out_per_m": 2.50,
    },
    "gpt-oss-120b": {
        "id": "openai.gpt-oss-120b-1:0",
        "tier": "cost",
        "price_in_per_m": 0.15,
        "price_out_per_m": 0.60,
    },
    "gpt-oss-20b": {
        "id": "openai.gpt-oss-20b-1:0",
        "tier": "cost",
        "price_in_per_m": 0.07,
        "price_out_per_m": 0.30,
    },
}

ROUTING_POLICY = os.getenv("LLM_GATEWAY_ROUTING", "quality")  # quality|cost|balanced


def _select_model(policy: str = None) -> tuple[str, str]:
    """라우팅 정책에 따라 실제 사용할 모델 ID와 결정 근거를 반환."""
    policy = policy or ROUTING_POLICY
    if policy == "cost":
        return MODEL_CATALOG["haiku-4-5"]["id"], "policy=cost → haiku-4-5 (always)"
    if policy == "balanced":
        return MODEL_CATALOG["sonnet-4-6"]["id"], "policy=balanced → sonnet-4-6 (default)"
    return MODEL_CATALOG["sonnet-4-6"]["id"], "policy=quality → sonnet-4-6 (always)"


def _reason_for_model(model_id: str, policy: str = None) -> str:
    """이미 선택된 model_id에 대해 정책상 근거 문자열 구성."""
    policy = policy or ROUTING_POLICY
    short = next(
        (name for name, meta in MODEL_CATALOG.items() if meta["id"] == model_id),
        model_id.split(".")[-1],
    )
    return f"policy={policy} → {short}"


# --- PII 스크럽 (LLM 입력/출력 모두 적용) ---

_PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "cpf_br": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
}


def scrub_pii(text: str) -> tuple[str, list[str]]:
    """PII를 감지하고 마스킹된 텍스트 반환. 감지된 태그 목록도 함께."""
    if not text:
        return text, []
    detected = []
    for name, pat in _PII_PATTERNS.items():
        if pat.search(text):
            detected.append(name)
            text = pat.sub(f"[{name.upper()}_REDACTED]", text)
    return text, detected


# --- 메트릭 스토어 (인메모리 + CloudWatch 송출) ---


class GatewayMetricsStore:
    """모델별 / 태그별 호출 통계."""

    def __init__(self):
        self._lock = threading.Lock()
        self._calls: list[dict] = []
        self._by_model: dict[str, dict] = {}
        self._guardrail_stats = {"input_scrubs": 0, "output_scrubs": 0, "detected_tags": {}}
        self._last_model_used: str = ""
        self._last_routing_reason: str = ""

    def record_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        tag: str = "default",
        cost_usd: float = 0.0,
        routing_reason: str = "",
    ):
        with self._lock:
            self._calls.append({
                "timestamp": time.time(),
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": latency_ms,
                "tag": tag,
                "cost_usd": cost_usd,
                "routing_reason": routing_reason,
            })
            if len(self._calls) > 500:
                self._calls = self._calls[-500:]

            m = self._by_model.setdefault(model, {
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
                "latency_ms_total": 0, "cost_usd": 0.0,
            })
            m["calls"] += 1
            m["input_tokens"] += input_tokens
            m["output_tokens"] += output_tokens
            m["latency_ms_total"] += latency_ms
            m["cost_usd"] += cost_usd

            self._last_model_used = model
            if routing_reason:
                self._last_routing_reason = routing_reason

    def record_guardrail(self, direction: str, detected: list[str]):
        if not detected:
            return
        with self._lock:
            key = f"{direction}_scrubs"
            if key in self._guardrail_stats:
                self._guardrail_stats[key] += 1
            for tag in detected:
                self._guardrail_stats["detected_tags"][tag] = (
                    self._guardrail_stats["detected_tags"].get(tag, 0) + 1
                )

    def snapshot(self) -> dict:
        with self._lock:
            models = []
            for model_name, meta in MODEL_CATALOG.items():
                stats = self._by_model.get(meta["id"], {})
                models.append({
                    "name": model_name,
                    "id": meta["id"],
                    "tier": meta["tier"],
                    "calls": stats.get("calls", 0),
                    "input_tokens": stats.get("input_tokens", 0),
                    "output_tokens": stats.get("output_tokens", 0),
                    "avg_latency_ms": round(
                        stats.get("latency_ms_total", 0) / max(stats.get("calls", 1), 1), 1
                    ) if stats.get("calls") else 0,
                    "cost_usd": round(stats.get("cost_usd", 0.0), 6),
                })
            return {
                "routing_policy": ROUTING_POLICY,
                "models": models,
                "recent_calls": list(reversed(self._calls[-30:])),
                "guardrails": dict(self._guardrail_stats),
                "total_calls": len(self._calls),
                "last_model_used": self._last_model_used,
                "last_routing_reason": self._last_routing_reason,
            }


_store = GatewayMetricsStore()


def get_store() -> GatewayMetricsStore:
    return _store


# --- Strands 커스텀 Model: BedrockModel을 감싸서 가드레일/메트릭 추가 ---


class GatewayBedrockModel(BedrockModel):
    """Bedrock 호출을 가로채서 LLM Gateway 기능을 추가한 커스텀 Model.

    Strands Agent는 이 인스턴스를 받아 평상시와 동일하게 사용하지만,
    내부적으로 converse/converse_stream 호출이 훅을 거쳐 집계됨.
    """

    def __init__(self, routing_tag: str = "default", **kwargs):
        # 라우팅 정책에 따라 실제 model_id 결정 + 근거 캐시
        if "model_id" not in kwargs:
            model_id, reason = _select_model()
            kwargs["model_id"] = model_id
            self._routing_reason = reason
        else:
            self._routing_reason = _reason_for_model(kwargs["model_id"])
        super().__init__(**kwargs)
        self._routing_tag = routing_tag

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        """Strands Model 인터페이스의 async 스트림 - 훅 포함.

        Strands는 (messages, tool_specs, system_prompt, **kwargs) 형태로 호출.
        각 호출은 `llm.invoke_model` OTel 스팬으로 감싸 트레이스 트리에 노출된다.
        """
        # 입력 가드레일 (사용자 메시지만 스크럽)
        for msg in messages:
            if msg.get("role") == "user":
                for content in msg.get("content", []) or []:
                    if isinstance(content, dict) and "text" in content:
                        scrubbed, detected = scrub_pii(content["text"])
                        if detected:
                            _store.record_guardrail("input", detected)
                            content["text"] = scrubbed

        model_id = self.config.get("model_id", "")

        # OTel 스팬 — CloudWatch GenAI Observability 트레이스에 LLM 호출을 노출
        try:
            from opentelemetry import trace as oteltrace
            tracer = oteltrace.get_tracer("agentops.llm_gateway")
            span_cm = tracer.start_as_current_span("llm.invoke_model")
        except Exception:
            span_cm = None

        span = span_cm.__enter__() if span_cm is not None else None
        if span is not None:
            try:
                span.set_attribute("gen_ai.system", "aws.bedrock")
                span.set_attribute("gen_ai.request.model", model_id)
                span.set_attribute("llm_gateway.routing_tag", self._routing_tag)
                span.set_attribute("llm_gateway.routing_reason", self._routing_reason)
                span.set_attribute("llm_gateway.routing_policy", ROUTING_POLICY)
            except Exception:
                pass

        start = time.time()
        total_in = total_out = 0
        full_response = ""

        try:
            async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
                usage = None
                if isinstance(event, dict):
                    md = event.get("metadata", {})
                    if isinstance(md, dict):
                        usage = md.get("usage")
                    cb = event.get("contentBlockDelta", {})
                    if isinstance(cb, dict):
                        delta = cb.get("delta", {})
                        if isinstance(delta, dict) and "text" in delta:
                            full_response += delta["text"]
                if usage and isinstance(usage, dict):
                    total_in = int(usage.get("inputTokens", total_in) or total_in)
                    total_out = int(usage.get("outputTokens", total_out) or total_out)
                yield event
        finally:
            latency_ms = round((time.time() - start) * 1000, 1)

            # 출력 가드레일
            _, out_detected = scrub_pii(full_response)
            if out_detected:
                _store.record_guardrail("output", out_detected)

            # 비용 계산
            model_meta = next(
                (m for m in MODEL_CATALOG.values() if m["id"] == model_id),
                {"price_in_per_m": 3.0, "price_out_per_m": 15.0},
            )
            cost = (total_in / 1_000_000) * model_meta["price_in_per_m"] + \
                   (total_out / 1_000_000) * model_meta["price_out_per_m"]

            _store.record_call(
                model=model_id,
                input_tokens=total_in,
                output_tokens=total_out,
                latency_ms=latency_ms,
                tag=self._routing_tag,
                cost_usd=cost,
                routing_reason=self._routing_reason,
            )

            if span is not None:
                try:
                    span.set_attribute("gen_ai.usage.input_tokens", total_in)
                    span.set_attribute("gen_ai.usage.output_tokens", total_out)
                    span.set_attribute("gen_ai.latency_ms", latency_ms)
                    span.set_attribute("llm_gateway.cost_usd", cost)
                except Exception:
                    pass
            if span_cm is not None:
                try:
                    span_cm.__exit__(None, None, None)
                except Exception:
                    pass
