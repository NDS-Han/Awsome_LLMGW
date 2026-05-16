"""
이커머스 분석 에이전트 (AgentCore Runtime 배포용).

도구는 AgentCore Gateway (MCP)를 통해 Lambda에서 실행된다.
이 파일 자체가 AgentCore Runtime의 컨테이너 안에서 실행됨.
"""

import os
import time
from pathlib import Path
from typing import Optional

# .env 자동 로드 (로컬 개발 편의, 배포 환경에선 env가 이미 주입됨)
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client

from agent.system_prompt import get_prompt
from agent.llm_gateway import GatewayBedrockModel, get_store as get_llm_gateway_store


# --- Role-based configuration (Agent Gateway: main/reviews/logistics) ---

AGENT_ROLE = os.getenv("AGENT_ROLE", "main")

_ROLE_SYSTEM_PROMPTS = {
    "reviews": (
        "You are a customer reviews specialist for Brazilian e-commerce. "
        "You focus exclusively on review scores, sentiment, satisfaction trends, and category-level feedback. "
        "Use ONLY the analyze_reviews tool. Always include specific numerical data and example reviews."
    ),
    "logistics": (
        "You are a logistics and seller performance specialist for Brazilian e-commerce. "
        "You focus on delivery times, on-time rates, state-level shipping performance, and seller metrics. "
        "Use check_delivery_performance and get_seller_metrics tools only. Always include state-level breakdowns."
    ),
}

# role별 허용 도구.
# main은 도메인 전용 도구(analyze_reviews · check_delivery_performance · get_seller_metrics)를
# 갖지 않는다 — 이 도메인 질문은 반드시 delegate_to_specialist로 위임하도록 구조적으로 강제.
# 이렇게 해야 Agent Gateway A2A 흐름이 데모에서도 안정적으로 재현된다.
_ROLE_ALLOWED_TOOLS = {
    "reviews": {"analyze_reviews"},
    "logistics": {"check_delivery_performance", "get_seller_metrics"},
    "main": {
        "query_sales_data",          # 매출 집계 — Main 직접 수행
        "text2sql_query",             # 범용 SQL — Main 직접 수행
        "delegate_to_specialist",     # 리뷰·물류·셀러 → 전문가에게 위임 강제
    },
}

app = BedrockAgentCoreApp()

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
REGION = os.getenv("AWS_REGION", "us-east-1")
GATEWAY_URL = os.environ["GATEWAY_URL"]
COGNITO_CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]
COGNITO_CLIENT_SECRET = os.environ["COGNITO_CLIENT_SECRET"]
COGNITO_TOKEN_ENDPOINT = os.environ["COGNITO_TOKEN_ENDPOINT"]
COGNITO_SCOPE = os.environ.get("COGNITO_SCOPE", "")


# --- OAuth 토큰 관리 (캐시 + 갱신) ---

_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def _get_gateway_token() -> str:
    """Cognito client_credentials 플로우로 access token 획득 (만료 전 캐싱)."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    data = {
        "grant_type": "client_credentials",
        "client_id": COGNITO_CLIENT_ID,
        "client_secret": COGNITO_CLIENT_SECRET,
    }
    if COGNITO_SCOPE:
        data["scope"] = COGNITO_SCOPE

    resp = httpx.post(
        COGNITO_TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    _token_cache["access_token"] = body["access_token"]
    _token_cache["expires_at"] = now + int(body.get("expires_in", 3600))
    return _token_cache["access_token"]


def _mcp_transport():
    """MCPClient에 전달할 transport factory. 호출 시점마다 최신 토큰 사용."""
    token = _get_gateway_token()
    return streamablehttp_client(GATEWAY_URL, headers={"Authorization": f"Bearer {token}"})


# --- Agent 생성 ---

_current_prompt_version = os.getenv("PROMPT_VERSION", "v1")

# 에이전트는 Bedrock을 직접 호출하지 않고 LLM Gateway를 경유.
# GatewayBedrockModel은 Bedrock wrapper로 라우팅/가드레일/메트릭을 추가.
_model = GatewayBedrockModel(
    model_id=MODEL_ID,
    region_name=REGION,
    routing_tag="main_agent",
)


def create_agent(prompt_version: Optional[str] = None) -> tuple[Agent, MCPClient]:
    """Gateway MCP 클라이언트와 함께 Strands Agent 생성.

    AGENT_ROLE에 따라 system prompt, 허용 도구가 달라진다:
      - main: 전체 도구 + delegate_to_specialist
      - reviews: analyze_reviews만
      - logistics: check_delivery_performance, get_seller_metrics만
    """
    mcp_client = MCPClient(_mcp_transport)
    mcp_client.start()
    try:
        all_tools = mcp_client.list_tools_sync()
    except Exception:
        mcp_client.stop(None, None, None)
        raise

    # role-based tool filtering
    if AGENT_ROLE in _ROLE_ALLOWED_TOOLS:
        allowed = _ROLE_ALLOWED_TOOLS[AGENT_ROLE]
        tools = [t for t in all_tools if _tool_name_base(t) in allowed]
    else:
        tools = all_tools  # main은 전체

    # system prompt
    if AGENT_ROLE in _ROLE_SYSTEM_PROMPTS:
        system_prompt = _ROLE_SYSTEM_PROMPTS[AGENT_ROLE]
    else:
        version = prompt_version or _current_prompt_version
        system_prompt = get_prompt(version)

    agent = Agent(
        model=_model,
        tools=tools,
        system_prompt=system_prompt,
    )
    return agent, mcp_client


def _tool_name_base(tool) -> str:
    """MCP 도구 이름에서 Target prefix 제거. 'Target___name' -> 'name'."""
    name = getattr(tool, "tool_name", None) or getattr(tool, "name", "")
    return name.split("___", 1)[-1] if "___" in name else name


def set_prompt_version(version: str) -> bool:
    global _current_prompt_version
    if version in ("v1", "v2"):
        _current_prompt_version = version
        return True
    return False


def get_current_prompt_version() -> str:
    return _current_prompt_version


@app.entrypoint
async def invoke(payload, context=None):
    """AgentCore Runtime 진입점.

    payload:
      {"prompt": str, "session_id": str, "prompt_version": "v1"|"v2"}
        → async generator 반환 (SSE 스트리밍: text_delta / tool_use / final)
      {"op": "llm_gateway_stats"}
        → dict 반환 (비스트리밍, LLM Gateway 메트릭 스냅샷)
    """
    if payload.get("op") == "llm_gateway_stats":
        return get_llm_gateway_store().snapshot()

    prompt = payload.get("prompt", "")
    prompt_version = payload.get("prompt_version")
    # async generator를 반환 — AgentCore가 자동으로 text/event-stream 으로 감쌈
    return _chat_stream(prompt, prompt_version)


async def _chat_stream(prompt: str, prompt_version):
    """Strands Agent의 async stream을 AgentCore SSE 이벤트로 변환.

    Yields:
      {"type":"text_delta","delta":"..."}   — 토큰 단위 응답 텍스트
      {"type":"tool_use","name":"..."}       — 도구 호출 시 한 번
      {"type":"final", ...전체 메타데이터}   — 완료 시 1회
    """
    agent, mcp_client = create_agent(prompt_version)
    full_text = ""
    tools_used: list[str] = []
    final_usage: dict = {}
    final_metrics: dict = {}
    started_at = time.time()

    try:
        async for event in agent.stream_async(prompt):
            # Strands는 다양한 event 타입을 dict로 방출
            if isinstance(event, dict):
                # 텍스트 델타: {"data": "chunk"}
                data = event.get("data")
                if isinstance(data, str) and data:
                    full_text += data
                    yield {"type": "text_delta", "delta": data}
                    continue
                # 도구 사용: {"current_tool_use": {"name": ..., "input": ...}}
                tu = event.get("current_tool_use")
                if isinstance(tu, dict):
                    name = tu.get("name") or ""
                    base = name.split("___", 1)[-1] if "___" in name else name
                    if base and base not in tools_used:
                        tools_used.append(base)
                        yield {"type": "tool_use", "name": base}
                    continue
                # 최종 result: {"result": AgentResult}
                result = event.get("result")
                if result is not None:
                    metrics_obj = getattr(result, "metrics", None)
                    if metrics_obj is not None:
                        final_usage = getattr(metrics_obj, "accumulated_usage", {}) or final_usage
                        final_metrics = getattr(metrics_obj, "accumulated_metrics", {}) or final_metrics

        otel_trace_id = ""
        try:
            from opentelemetry import trace as oteltrace
            ctx = oteltrace.get_current_span().get_span_context()
            if ctx.trace_id:
                otel_trace_id = format(ctx.trace_id, '032x')
        except Exception:
            pass

        yield {
            "type": "final",
            "response": full_text,
            "prompt_version": get_current_prompt_version(),
            "tools_used": tools_used,
            "otel_trace_id": otel_trace_id,
            "usage": {
                "input_tokens": int(final_usage.get("inputTokens", 0)),
                "output_tokens": int(final_usage.get("outputTokens", 0)),
                "total_tokens": int(final_usage.get("totalTokens", 0)),
            },
            "latency_ms": (int(final_metrics.get("latencyMs", 0))
                           or int((time.time() - started_at) * 1000)),
            "llm_gateway_snapshot": get_llm_gateway_store().snapshot(),
        }
    finally:
        try:
            mcp_client.stop(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    app.run()
