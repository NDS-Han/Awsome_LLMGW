"""
AgentCore Runtime 호출 클라이언트.
FastAPI가 로컬에서 Strands Agent를 돌리는 대신 이 모듈을 통해 AgentCore Runtime을 invoke한다.
"""

import os
import json
import functools
from typing import Optional

import boto3


@functools.lru_cache(maxsize=1)
def _get_client():
    return boto3.client("bedrock-agentcore", region_name=os.getenv("AGENTCORE_REGION", os.getenv("AWS_REGION", "us-east-1")))


def _get_runtime_arn() -> str:
    arn = os.getenv("AGENTCORE_RUNTIME_ARN")
    if not arn:
        raise RuntimeError("AGENTCORE_RUNTIME_ARN is not configured.")
    return arn


def invoke_runtime(
    prompt: str,
    session_id: Optional[str] = None,
    prompt_version: Optional[str] = None,
    qualifier: str = "DEFAULT",
) -> dict:
    """AgentCore Runtime 호출. 반환: {response, tools_used, usage, latency_ms, prompt_version}."""
    payload = {"prompt": prompt}
    if prompt_version:
        payload["prompt_version"] = prompt_version
    if session_id:
        payload["session_id"] = session_id

    try:
        from api.telemetry import inject_traceparent
        tp = inject_traceparent()
        if tp:
            payload["traceparent"] = tp
    except Exception:
        pass

    kwargs = {
        "agentRuntimeArn": _get_runtime_arn(),
        "qualifier": qualifier,
        "payload": json.dumps(payload).encode("utf-8"),
    }
    # AgentCore는 session_id가 33글자 이상이어야 함
    if session_id and len(session_id) >= 33:
        kwargs["runtimeSessionId"] = session_id

    resp = _get_client().invoke_agent_runtime(**kwargs)

    runtime_session_id = resp.get("runtimeSessionId", "")
    runtime_trace_id = resp.get("traceId", "")

    # 응답은 stream 형태. 전체를 읽어 JSON 파싱.
    body_stream = resp.get("response")
    if hasattr(body_stream, "read"):
        raw = body_stream.read()
    else:
        # iterator
        raw = b"".join(chunk for chunk in body_stream)

    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"response": text, "tools_used": [], "usage": {}, "latency_ms": 0}

    if runtime_session_id:
        result["runtime_session_id"] = runtime_session_id
    if runtime_trace_id:
        result["runtime_trace_id"] = runtime_trace_id
    return result
