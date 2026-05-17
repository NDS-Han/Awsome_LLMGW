"""Write-through persistence layer for in-memory state migration to DynamoDB."""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key


REGION = os.getenv("AWS_REGION", "us-east-1")
CHAT_HISTORY_TABLE = os.getenv("CHAT_HISTORY_TABLE", "")
EVALUATIONS_TABLE = os.getenv("EVALUATIONS_TABLE", "")
SESSIONS_TABLE = os.getenv("SESSIONS_TABLE", "")
BUDGET_STATE_TABLE = os.getenv("BUDGET_STATE_TABLE", "")
USAGE_TABLE = os.getenv("USAGE_TABLE", "")

_TTL_CHAT_DAYS = 7
_TTL_EVAL_DAYS = 30
_TTL_SESSION_HOURS = 2


def _ttl_epoch(days: int = 0, hours: int = 0) -> int:
    delta = timedelta(days=days, hours=hours)
    return int((datetime.now(timezone.utc) + delta).timestamp())


def _date_bucket(ts: str) -> str:
    return ts[:10] if ts else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _serialize(obj) -> str:
    return json.dumps(obj, default=str)


def _to_dynamodb(obj):
    """Recursively convert floats to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dynamodb(i) for i in obj]
    return obj


def _deserialize_item(item: dict) -> dict:
    out = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = float(v) if v % 1 else int(v)
        elif isinstance(v, set):
            out[k] = list(v)
        elif isinstance(v, dict):
            out[k] = _deserialize_item(v)
        elif isinstance(v, list):
            out[k] = [
                _deserialize_item(i) if isinstance(i, dict)
                else (float(i) if isinstance(i, Decimal) else i)
                for i in v
            ]
        else:
            out[k] = v
    return out


class PersistenceLayer:
    """Write-through persistence for in-memory state."""

    def __init__(self):
        self._writer = ThreadPoolExecutor(max_workers=4, thread_name_prefix="persist")
        self._ddb = boto3.resource("dynamodb", region_name=REGION)

    def _chat_table(self):
        return self._ddb.Table(CHAT_HISTORY_TABLE)

    def _eval_table(self):
        return self._ddb.Table(EVALUATIONS_TABLE)

    def _session_table(self):
        return self._ddb.Table(SESSIONS_TABLE)

    def _state_table(self):
        return self._ddb.Table(BUDGET_STATE_TABLE)

    def _usage_table(self):
        return self._ddb.Table(USAGE_TABLE)

    # ------------------------------------------------------------------
    # Chat History
    # ------------------------------------------------------------------

    def persist_chat(self, entry: dict) -> None:
        self._writer.submit(self.persist_chat_sync, entry)

    def persist_chat_sync(self, entry: dict) -> None:
        try:
            ts = entry.get("timestamp", datetime.now(timezone.utc).isoformat())
            turn_id = entry.get("turn_id", "")
            item = {
                "session_id": entry.get("session_id", ""),
                "sort_key": f"turn#{ts}#{turn_id}",
                "turn_id": turn_id,
                "trace_id": entry.get("trace_id", ""),
                "otel_trace_id": entry.get("otel_trace_id", ""),
                "prompt": (entry.get("prompt", "") or "")[:4000],
                "response": (entry.get("response", "") or "")[:4000],
                "tools_used": entry.get("tools_used", []),
                "tokens": entry.get("tokens", {}),
                "cost": entry.get("cost", {}),
                "latency_ms": Decimal(str(entry.get("latency_ms", 0))),
                "prompt_version": entry.get("prompt_version", ""),
                "guardrails_passed": entry.get("guardrails_passed", True),
                "timestamp": ts,
                "date_bucket": _date_bucket(ts),
                "ttl": _ttl_epoch(days=_TTL_CHAT_DAYS),
            }
            self._chat_table().put_item(Item=_to_dynamodb(item))
        except Exception as e:
            print(f"[persistence] chat write failed: {e}")

    def load_chat_history(self, limit: int = 100) -> list[dict]:
        try:
            results = []
            for days_ago in range(7):
                bucket = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                resp = self._chat_table().query(
                    IndexName="gsi-timestamp",
                    KeyConditionExpression=Key("date_bucket").eq(bucket),
                    ScanIndexForward=False,
                    Limit=limit - len(results),
                )
                for item in resp.get("Items", []):
                    results.append(_deserialize_item(item))
                if len(results) >= limit:
                    break
            results.sort(key=lambda x: x.get("timestamp", ""))
            return results[-limit:]
        except Exception as e:
            print(f"[persistence] chat load failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Evaluations
    # ------------------------------------------------------------------

    def persist_eval(self, turn_eval: dict) -> None:
        self._writer.submit(self.persist_eval_sync, turn_eval)

    def persist_eval_sync(self, turn_eval: dict) -> None:
        try:
            ts = turn_eval.get("timestamp", datetime.now(timezone.utc).isoformat())
            turn_id = turn_eval.get("turn_id", "")
            item = {
                "turn_id": turn_id,
                "sort_key": f"eval#{ts}",
                "trace_id": turn_eval.get("trace_id", ""),
                "scores": turn_eval.get("scores", []),
                "avg_score": Decimal(str(round(turn_eval.get("avg_score", 0), 4))),
                "prompt_version": turn_eval.get("prompt_version", ""),
                "category": turn_eval.get("category", "general"),
                "prompt": (turn_eval.get("prompt", "") or "")[:2000],
                "response": (turn_eval.get("response", "") or "")[:2000],
                "tools_used": turn_eval.get("tools_used", []),
                "eval_source": turn_eval.get("eval_source", "agentcore"),
                "timestamp": ts,
                "date_bucket": _date_bucket(ts),
                "ttl": _ttl_epoch(days=_TTL_EVAL_DAYS),
            }
            self._eval_table().put_item(Item=item)
        except Exception as e:
            print(f"[persistence] eval write failed: {e}")

    def load_evaluations(self, limit: int = 50) -> tuple[list[dict], dict]:
        try:
            results = []
            for days_ago in range(30):
                bucket = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                resp = self._eval_table().query(
                    IndexName="gsi-timestamp",
                    KeyConditionExpression=Key("date_bucket").eq(bucket),
                    ScanIndexForward=False,
                    Limit=limit - len(results),
                )
                for item in resp.get("Items", []):
                    results.append(_deserialize_item(item))
                if len(results) >= limit:
                    break
            results.sort(key=lambda x: x.get("timestamp", ""))
            results = results[-limit:]

            turn_evals = {r["turn_id"]: r for r in results if r.get("turn_id")}
            return results, turn_evals
        except Exception as e:
            print(f"[persistence] eval load failed: {e}")
            return [], {}

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def persist_session(self, session) -> None:
        self._writer.submit(self.persist_session_sync, session)

    def persist_session_sync(self, session) -> None:
        try:
            cb = session.circuit_breaker
            item = {
                "session_id": session.session_id,
                "created_at": session.created_at.isoformat() if isinstance(session.created_at, datetime) else str(session.created_at),
                "last_activity": session.last_activity.isoformat() if isinstance(session.last_activity, datetime) else str(session.last_activity),
                "turn_counter": session.turn_counter,
                "context_tokens_used": session.context_tokens_used,
                "circuit_breaker": {
                    "state": cb.state.value,
                    "consecutive_failures": cb.consecutive_failures,
                    "total_failures": cb.total_failures,
                    "total_successes": cb.total_successes,
                    "failure_threshold": cb.failure_threshold,
                    "recovery_timeout_seconds": cb.recovery_timeout_seconds,
                },
                "recent_messages": session.recent_messages[-10:],
                "ttl": _ttl_epoch(hours=_TTL_SESSION_HOURS),
            }
            self._session_table().put_item(Item=_to_dynamodb(item))
        except Exception as e:
            print(f"[persistence] session write failed: {e}")

    def load_sessions(self) -> dict:
        try:
            from api.session import SessionState, CircuitBreaker, CircuitState
            resp = self._session_table().scan(Limit=200)
            items = resp.get("Items", [])
            sessions = {}
            for item in items:
                item = _deserialize_item(item)
                sid = item.get("session_id", "")
                if not sid:
                    continue
                session = SessionState(session_id=sid)
                session.turn_counter = int(item.get("turn_counter", 0))
                session.context_tokens_used = int(item.get("context_tokens_used", 0))
                session.recent_messages = item.get("recent_messages", [])

                created = item.get("created_at", "")
                if created:
                    try:
                        session.created_at = datetime.fromisoformat(created)
                    except (ValueError, TypeError):
                        pass
                last_act = item.get("last_activity", "")
                if last_act:
                    try:
                        session.last_activity = datetime.fromisoformat(last_act)
                    except (ValueError, TypeError):
                        pass

                cb_data = item.get("circuit_breaker", {})
                if cb_data:
                    session.circuit_breaker.state = CircuitState(cb_data.get("state", "closed"))
                    session.circuit_breaker.consecutive_failures = int(cb_data.get("consecutive_failures", 0))
                    session.circuit_breaker.total_failures = int(cb_data.get("total_failures", 0))
                    session.circuit_breaker.total_successes = int(cb_data.get("total_successes", 0))

                sessions[sid] = session
            return sessions
        except Exception as e:
            print(f"[persistence] sessions load failed: {e}")
            return {}

    # ------------------------------------------------------------------
    # LLM Gateway Snapshot
    # ------------------------------------------------------------------

    def persist_llm_gateway(self, snapshot: dict) -> None:
        self._writer.submit(self.persist_llm_gateway_sync, snapshot)

    def persist_llm_gateway_sync(self, snapshot: dict) -> None:
        try:
            item = {
                "entity_id": "state#llm_gateway",
                "period": "current",
                "data": _serialize(snapshot),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            self._state_table().put_item(Item=item)
        except Exception as e:
            print(f"[persistence] llm_gateway write failed: {e}")

    def load_llm_gateway(self) -> Optional[dict]:
        try:
            resp = self._state_table().get_item(
                Key={"entity_id": "state#llm_gateway", "period": "current"}
            )
            item = resp.get("Item")
            if not item:
                return None
            data_str = item.get("data", "{}")
            return json.loads(data_str)
        except Exception as e:
            print(f"[persistence] llm_gateway load failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Optimization State
    # ------------------------------------------------------------------

    def persist_optimization_state(self, state: dict) -> None:
        self._writer.submit(self.persist_optimization_state_sync, state)

    def persist_optimization_state_sync(self, state: dict) -> None:
        try:
            item = {
                "entity_id": "state#optimization",
                "period": "current",
                "data": _serialize(state),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            self._state_table().put_item(Item=item)
        except Exception as e:
            print(f"[persistence] optimization write failed: {e}")

    def load_optimization_state(self) -> Optional[dict]:
        try:
            resp = self._state_table().get_item(
                Key={"entity_id": "state#optimization", "period": "current"}
            )
            item = resp.get("Item")
            if not item:
                return None
            data_str = item.get("data", "{}")
            return json.loads(data_str)
        except Exception as e:
            print(f"[persistence] optimization load failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Cost State (derived from usage table)
    # ------------------------------------------------------------------

    def load_cost_state(self) -> tuple[dict, float]:
        try:
            from api.cost_tracker import SessionCostState, TokenUsage
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            resp = self._usage_table().query(
                IndexName="gsi-date-cost",
                KeyConditionExpression=Key("date_bucket").eq(today),
                ScanIndexForward=False,
                Limit=500,
            )
            items = resp.get("Items", [])

            sessions: dict = {}
            global_cost = 0.0
            for item in items:
                item = _deserialize_item(item)
                sid = item.get("session_id", "")
                cost = float(item.get("cost_usd", 0))
                global_cost += cost
                if sid:
                    if sid not in sessions:
                        sessions[sid] = SessionCostState(session_id=sid)
                    s = sessions[sid]
                    s.total_cost += cost
                    s.call_count += 1
                    s.total_usage.input_tokens += int(item.get("input_tokens", 0))
                    s.total_usage.output_tokens += int(item.get("output_tokens", 0))
            return sessions, global_cost
        except Exception as e:
            print(f"[persistence] cost load failed: {e}")
            return {}, 0.0


_instance: Optional[PersistenceLayer] = None


def get_persistence() -> PersistenceLayer:
    global _instance
    if _instance is None:
        _instance = PersistenceLayer()
    return _instance
