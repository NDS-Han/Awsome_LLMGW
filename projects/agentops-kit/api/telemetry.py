"""
트레이싱 유틸리티.
AgentCore Observability가 ADOT로 수집한 span을 CloudWatch에서 조회할 때
사용하는 헬퍼 함수만 제공한다. Span 생성은 ADOT 자동 계측에 위임.
"""

import asyncio
import time as _time
from typing import Any

_span_event_queues: list[asyncio.Queue] = []


def publish_span_event(event_type: str, data: dict[str, Any]) -> None:
    """Publish a span event to all connected SSE listeners."""
    event = {"type": event_type, "data": data, "ts": _time.time()}
    for q in list(_span_event_queues):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscribe_span_events() -> asyncio.Queue:
    """Create a new subscriber queue for SSE streaming."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _span_event_queues.append(q)
    return q


def unsubscribe_span_events(q: asyncio.Queue) -> None:
    """Remove a subscriber queue."""
    try:
        _span_event_queues.remove(q)
    except ValueError:
        pass


def inject_traceparent() -> str:
    """현재 OTEL span context에서 W3C traceparent 헤더 값을 생성."""
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id and ctx.span_id:
            return f"00-{format(ctx.trace_id, '032x')}-{format(ctx.span_id, '016x')}-01"
    except Exception:
        pass
    return ""


def get_current_otel_trace_id() -> str:
    """현재 OTEL span의 trace_id (hex)를 반환."""
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id:
            return format(ctx.trace_id, '032x')
    except Exception:
        pass
    return ""


def build_span_tree(flat_spans: list[dict]) -> list[dict]:
    """flat span 리스트를 parent_span_id 기반 트리로 변환."""
    by_id = {s["span_id"]: {**s, "subsegments": []} for s in flat_spans}
    roots = []
    for s in by_id.values():
        parent = s.get("parent_span_id")
        if parent and parent in by_id:
            by_id[parent]["subsegments"].append(s)
        else:
            roots.append(s)
    return roots
