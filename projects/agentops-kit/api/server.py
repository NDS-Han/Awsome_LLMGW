"""
FastAPI 백엔드 서버 (프로덕션 검증 패턴 통합).
운영 단계 검증을 위한 모듈:
- guardrails: 출력 검증 (PII, 수치 근거, 환각)
- cost_tracker: 토큰/비용 추적, 예산 관리
- errors: 에러 분류 + 재시도 정책
- session: 서킷 브레이커 + 세션 상태
- analytics: 이벤트 큐 + sink (PII 레덕션)

Usage:
    uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import time
import uuid
import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# .env 자동 로드 — 다른 api.* 모듈이 env를 읽기 전에 로드되어야 함
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
except ImportError:
    pass

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import boto3
from api.agentcore_runtime import invoke_runtime
from api.cloudwatch import cw_helper, AGENT_ID
from api.cloudwatch import cw_helper as _cw_ref  # noqa: ensure module loads
from api.genai_metrics import record_invocation as record_genai_metrics, record_error as record_genai_error, init_metrics as init_genai_metrics
from api.persistence import get_persistence


# 프롬프트 버전 상태는 이제 FastAPI 측에서만 관리 (Runtime 호출 시 payload로 전달)
_current_prompt_version = os.getenv("PROMPT_VERSION", "v1")
_RUNTIME_NAME = os.getenv("AGENTCORE_RUNTIME_NAME", "ecommerce_analytics")
_GATEWAY_NAME = os.getenv("AGENTCORE_GATEWAY_NAME", "agentops-ecommerce-gateway")
_GATEWAY_TARGET_NAME = os.getenv("GATEWAY_TARGET_NAME", "EcommerceAnalyticsTools")
_AGENT_RUNTIME_NAMES = os.getenv("AGENT_RUNTIME_NAMES", "ecommerce_analytics,reviews_specialist,logistics_specialist").split(",")
_MAIN_RUNTIME = _AGENT_RUNTIME_NAMES[0] if _AGENT_RUNTIME_NAMES else "ecommerce_analytics"
_ALARM_PREFIX = os.getenv("ALARM_PREFIX", "agentops-anomaly")


def get_current_prompt_version() -> str:
    return _current_prompt_version


def set_prompt_version(version: str) -> bool:
    global _current_prompt_version
    from agent.system_prompt import PROMPT_VERSIONS
    if version in PROMPT_VERSIONS:
        _current_prompt_version = version
        return True
    return False
from api.guardrails import validate_response, redact_pii, GuardrailResult
from api.cost_tracker import get_tracker, TokenUsage
from api.errors import classify_error, get_retry_delay_ms
from api.session import get_session_store, CircuitState
from api.analytics import get_queue, get_memory_sink, Events, emit, _ensure_cw_sink
from api.users import (
    UserCtx, UsageRecord, get_user_ctx, record_usage, enforce_budget,
    get_budget_state, set_budget, list_users, list_teams, get_directory_entry,
    get_user_usage, get_team_usage, top_users, top_teams,
)
from api.telemetry import publish_span_event, subscribe_span_events, unsubscribe_span_events
from fastapi import Depends

app = FastAPI(
    title="AgentOps E-commerce Analytics API",
    version="2.0.0",
    # 운영에서는 OpenAPI 노출 여부를 제어
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "true").lower() == "true" else None,
    redoc_url=None,
)


@app.on_event("startup")
def _startup_otel():
    try:
        from api.otel_setup import init_otel
        init_otel()
        init_genai_metrics()
    except Exception:
        pass
    _ensure_cw_sink()

    from api.langfuse_tracing import init_langfuse
    init_langfuse()


@app.on_event("shutdown")
def _shutdown_langfuse():
    from api.langfuse_tracing import flush
    flush()


@app.on_event("startup")
def _restore_persisted_state():
    """Restore in-memory state from DynamoDB on server start."""
    global _chat_history
    global _llm_gateway_acc, _optimization_state

    persistence = get_persistence()

    try:
        _chat_history = persistence.load_chat_history(limit=100)
        print(f"[restore] chat_history: {len(_chat_history)} entries")
    except Exception as e:
        print(f"[restore] chat_history failed: {e}")

    # Evaluation state is now managed by AgentCore Online Evaluation Config
    # (no in-memory eval state to restore)

    try:
        sessions = persistence.load_sessions()
        if sessions:
            get_session_store()._sessions = sessions
            print(f"[restore] sessions: {len(sessions)} entries")
    except Exception as e:
        print(f"[restore] sessions failed: {e}")

    try:
        restored_gw = persistence.load_llm_gateway()
        if restored_gw:
            _llm_gateway_acc.update(restored_gw)
            print("[restore] llm_gateway_acc restored")
    except Exception as e:
        print(f"[restore] llm_gateway failed: {e}")

    try:
        restored_opt = persistence.load_optimization_state()
        if restored_opt:
            _optimization_state.update(restored_opt)
            print(f"[restore] optimization_state: stage={restored_opt.get('stage')}")
    except Exception as e:
        print(f"[restore] optimization failed: {e}")

    try:
        cost_sessions, global_cost = persistence.load_cost_state()
        if cost_sessions:
            tracker = get_tracker()
            tracker._sessions = cost_sessions
            tracker._global_cost = global_cost
            print(f"[restore] cost_tracker: {len(cost_sessions)} sessions, ${global_cost:.4f}")
    except Exception as e:
        print(f"[restore] cost failed: {e}")

# 전역 예외 핸들러 — 내부 스택 트레이스가 응답으로 새지 않도록
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    print(f"[error] {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "path": str(request.url.path), "detail": str(exc)},
    )

# CORS origins는 환경변수로 제어. 기본은 로컬 개발 포트만 허용.
_cors_origins = [
    o.strip() for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization", "traceparent", "tracestate"],
)

# Model configuration
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")


# --- Request/Response Models ---


_SESSION_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, pattern=_SESSION_ID_PATTERN)
    prompt_version: Optional[str] = Field(default=None, pattern=r"^v[123]$")
    enable_guardrails: bool = True
    budget_usd: Optional[float] = Field(default=None, ge=0.0, le=100.0)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    trace_id: str
    turn_id: str
    prompt_version: str
    latency_ms: float
    tools_used: list[str]
    token_usage: dict
    cost: dict
    guardrails: Optional[dict] = None
    circuit_state: str
    redacted: bool = False


class EvalRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, pattern=_SESSION_ID_PATTERN)
    trace_id: Optional[str] = None
    lookback_days: int = Field(default=7, ge=1, le=90)
    evaluators: list[str] = Field(
        default=[
            "Builtin.Helpfulness",
            "Builtin.Correctness",
            "Builtin.GoalSuccessRate",
            "Builtin.Faithfulness",
            "Builtin.ToolSelectionAccuracy",
            "Builtin.Conciseness",
        ],
        max_length=10,
    )


class PromptUpdateRequest(BaseModel):
    version: str = Field(pattern=r"^v[123]$")


class BudgetRequest(BaseModel):
    session_id: str = Field(pattern=_SESSION_ID_PATTERN)
    budget_usd: float = Field(ge=0.0, le=1000.0)


# --- Storage ---
_chat_history: list[dict] = []

# LLM Gateway 누적 캐시 — runtime 컨테이너가 idle로 내려가면 in-process store가
# 리셋되기 때문에, BFF에서 /chat/stream의 final event에 실린 snapshot을 턴마다
# 병합해 유지. /gateways/llm 폴링에서 이 캐시를 fallback 데이터와 merge해 반환.
_llm_gateway_acc: dict = {
    "routing_policy": "quality",
    "models": {},         # name -> {calls, input_tokens, output_tokens, cost_usd, avg_latency_ms, id, tier}
    "recent_calls": [],
    "guardrails": {"input_scrubs": 0, "output_scrubs": 0, "detected_tags": {}},
    "total_calls": 0,
    "last_model_used": "",
    "last_routing_reason": "",
}


def _merge_llm_gateway_snapshot(snap: dict) -> None:
    """Runtime의 turn snapshot을 BFF의 누적 캐시에 병합."""
    if not isinstance(snap, dict):
        return
    policy = snap.get("routing_policy")
    if policy:
        _llm_gateway_acc["routing_policy"] = policy
    for m in snap.get("models") or []:
        name = m.get("name")
        if not name:
            continue
        acc = _llm_gateway_acc["models"].setdefault(name, {
            "name": name, "id": m.get("id", ""), "tier": m.get("tier", ""),
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "avg_latency_ms": 0.0, "_lat_sum_ms": 0.0,
        })
        acc["id"] = m.get("id") or acc["id"]
        acc["tier"] = m.get("tier") or acc["tier"]
        calls_delta = int(m.get("calls") or 0)
        input_delta = int(m.get("input_tokens") or 0)
        output_delta = int(m.get("output_tokens") or 0)
        cost_delta = float(m.get("cost_usd") or 0)
        lat_this = float(m.get("avg_latency_ms") or 0) * max(1, calls_delta)
        acc["calls"] += calls_delta
        acc["input_tokens"] += input_delta
        acc["output_tokens"] += output_delta
        acc["cost_usd"] += cost_delta
        acc["_lat_sum_ms"] += lat_this
        acc["avg_latency_ms"] = (acc["_lat_sum_ms"] / acc["calls"]) if acc["calls"] else 0.0
    # recent_calls — 최근 50개 유지
    new_calls = snap.get("recent_calls") or []
    _llm_gateway_acc["recent_calls"] = (new_calls + _llm_gateway_acc["recent_calls"])[:50]
    # guardrails — 단순 합산
    g = snap.get("guardrails") or {}
    _llm_gateway_acc["guardrails"]["input_scrubs"] += int(g.get("input_scrubs") or 0)
    _llm_gateway_acc["guardrails"]["output_scrubs"] += int(g.get("output_scrubs") or 0)
    for k, v in (g.get("detected_tags") or {}).items():
        _llm_gateway_acc["guardrails"]["detected_tags"][k] = (
            _llm_gateway_acc["guardrails"]["detected_tags"].get(k, 0) + int(v)
        )
    _llm_gateway_acc["total_calls"] += int(snap.get("total_calls") or 0)
    if snap.get("last_model_used"):
        _llm_gateway_acc["last_model_used"] = snap["last_model_used"]
    if snap.get("last_routing_reason"):
        _llm_gateway_acc["last_routing_reason"] = snap["last_routing_reason"]
# 가장 최근 /chat 턴의 Gateway 요약 — Journey Strip과 /gateways/* 의 last_* 필드 전용.
_last_turn_summary: Optional[dict] = None


def _infer_specialist(prompt: str, tools_used: list[str]) -> str:
    """delegate_to_specialist 호출이 어느 전문가로 갔는지 프롬프트 키워드로 추정."""
    p = (prompt or "").lower()
    if any(k in p for k in ["리뷰", "만족", "후기", "review", "sentiment", "satisfact"]):
        return "reviews"
    if any(k in p for k in ["배송", "물류", "셀러", "delivery", "shipping", "seller"]):
        return "logistics"
    return "specialist"
_optimization_state: dict = {
    "stage": "idle",
    "active_recommendation": None,
    "active_test": None,
}


# --- Endpoints ---


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "prompt_version": get_current_prompt_version(),
        "model": MODEL_ID,
        "analytics_stats": get_queue().get_stats(),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, ctx: UserCtx = Depends(get_user_ctx)):
    """
    에이전트 호출 (프로덕션 검증 파이프라인 통합):
    1. 세션/서킷 브레이커 확인
    2. 턴 시작 + 텔레메트리 span 생성
    3. 에이전트 호출
    4. 가드레일 검증
    5. 비용 추적
    6. 분석 이벤트 emit
    """
    session_id = req.session_id or str(uuid.uuid4())
    session = get_session_store().get_or_create(session_id)

    # 0. User 예산 enforcement (1000+ 유저 환경에서 abuse 방지)
    enforce_budget(ctx)

    # 1. 서킷 브레이커 확인
    can_proceed, reason = session.circuit_breaker.can_proceed()
    if not can_proceed:
        emit(Events.CIRCUIT_OPEN, session_id=session_id, reason=reason)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "circuit_breaker_open",
                "reason": reason,
                "circuit_state": session.circuit_breaker.state.value,
                "retry_after_seconds": session.circuit_breaker.recovery_timeout_seconds,
            },
        )

    # 예산 설정
    if req.budget_usd is not None:
        get_tracker().set_budget(session_id, req.budget_usd)

    # 2. 턴 시작
    turn_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    # ADOT 자동 계측이 만든 현재 span의 trace_id (CloudWatch에 저장되는 ID)
    from api.telemetry import get_current_otel_trace_id
    otel_trace_id = get_current_otel_trace_id()
    session.start_turn(turn_id)

    emit(
        Events.CHAT_START,
        session_id=session_id,
        turn_id=turn_id,
        prompt_length=len(req.prompt),
        _SENSITIVE_prompt=req.prompt,
    )

    start_time = time.time()
    tools_used: list[str] = []
    tool_outputs: list[str] = []
    token_usage = TokenUsage()

    try:
        # 3. AgentCore Runtime 호출 (컨테이너에서 Strands + Gateway 실행)
        runtime_result = invoke_runtime(
            prompt=req.prompt,
            session_id=session_id if len(session_id) >= 33 else None,
            prompt_version=req.prompt_version or get_current_prompt_version(),
        )

        response_text = runtime_result.get("response", "")
        tools_used = runtime_result.get("tools_used", [])
        tool_calls = runtime_result.get("tool_calls", [])
        runtime_session_id = runtime_result.get("runtime_session_id", "")
        runtime_trace_id = runtime_result.get("runtime_trace_id", "")
        runtime_otel_trace_id = runtime_result.get("otel_trace_id", "")
        print(f"[runtime] otel_trace={runtime_otel_trace_id!r}, session={runtime_session_id!r}")
        if runtime_otel_trace_id:
            otel_trace_id = runtime_otel_trace_id
        usage = runtime_result.get("usage", {}) or {}
        token_usage.input_tokens = int(usage.get("input_tokens", 0))
        token_usage.output_tokens = int(usage.get("output_tokens", 0))

        # Gateway 도구 이름은 "Target___toolName" 형식 → prefix 제거
        tools_used = [t.split("___", 1)[-1] for t in tools_used]

        latency_ms = round((time.time() - start_time) * 1000, 1)

        # 4. 가드레일 검증
        guardrail_result: Optional[GuardrailResult] = None
        redacted = False
        if req.enable_guardrails:
            guardrail_result = validate_response(response_text, tool_outputs=tool_outputs)

            if any(v.severity == "critical" for v in guardrail_result.violations):
                response_text = redact_pii(response_text)
                redacted = True

            if guardrail_result.passed:
                emit(Events.GUARDRAIL_PASS, session_id=session_id, turn_id=turn_id,
                     violations=len(guardrail_result.violations))
            else:
                emit(Events.GUARDRAIL_FAIL, session_id=session_id, turn_id=turn_id,
                     critical_count=guardrail_result.critical_count)

            for v in guardrail_result.violations:
                emit(Events.GUARDRAIL_VIOLATION, session_id=session_id, turn_id=turn_id,
                     rule_id=v.rule_id, severity=v.severity.value)

        # 5. 비용 추적
        cost_info = get_tracker().record(session_id, MODEL_ID, token_usage)

        budget_status = cost_info["budget"].get("status")
        if budget_status in ("warning", "critical"):
            emit(Events.BUDGET_WARNING, session_id=session_id, ratio=cost_info["budget"]["used_ratio"])
        elif budget_status == "exceeded":
            emit(Events.BUDGET_EXCEEDED, session_id=session_id)

        # 6. 세션 업데이트
        session.end_turn()
        session.add_message("user", req.prompt)
        session.add_message("assistant", response_text, metadata={
            "tools_used": tools_used,
            "latency_ms": latency_ms,
        })
        session.context_tokens_used += token_usage.billable_tokens
        session.circuit_breaker.record_success()
        get_session_store().persist(session_id)

        # GenAI 메트릭 기록 (ADOT meter → CloudWatch)
        guardrail_viol_count = len(guardrail_result.violations) if guardrail_result else 0
        record_genai_metrics(
            latency_ms=latency_ms,
            input_tokens=token_usage.input_tokens,
            output_tokens=token_usage.output_tokens,
            model=MODEL_ID,
            tools_used=tools_used,
            cost_usd=cost_info["cost"]["total_cost"],
            prompt_version=get_current_prompt_version(),
            guardrail_violations=guardrail_viol_count,
        )

        emit(
            Events.CHAT_COMPLETE,
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            tools_count=len(tools_used),
            token_total=token_usage.total_tokens,
            cost_usd=cost_info["cost"]["total_cost"],
            prompt_version=get_current_prompt_version(),
        )

        # User/Team 사용량 기록 (비동기 DynamoDB write)
        # Runtime이 토큰을 반환하지 않으면 텍스트 길이로 추정
        _rec_input = token_usage.input_tokens or max(len(req.prompt) // 4, 1)
        _rec_output = token_usage.output_tokens or max(len(response_text) // 4, 1)
        record_usage(UsageRecord(
            user_id=ctx.user_id,
            team_id=ctx.team_id,
            timestamp=datetime.utcnow().isoformat(),
            input_tokens=_rec_input,
            output_tokens=_rec_output,
            total_tokens=_rec_input + _rec_output,
            cost_usd=cost_info["cost"]["total_cost"],
            model=MODEL_ID,
            tools_used=tools_used,
            prompt_version=get_current_prompt_version(),
            session_id=session_id,
            trace_id=trace_id,
            latency_ms=int(latency_ms),
        ))

        _chat_history.append({
            "session_id": session_id,
            "trace_id": trace_id,
            "otel_trace_id": otel_trace_id,
            "turn_id": turn_id,
            "prompt": req.prompt,
            "response": response_text,
            "tools_used": tools_used,
            "timestamp": datetime.utcnow().isoformat(),
        })
        get_persistence().persist_chat(_chat_history[-1])

        # Gateway 5분 데모용: 최근 턴 요약 캐시
        global _last_turn_summary
        has_handoff = "delegate_to_specialist" in tools_used
        _last_turn_summary = {
            "turn_id": turn_id,
            "session_id": session_id,
            "trace_id": otel_trace_id or trace_id,
            "model": MODEL_ID,
            "tools_used": tools_used,
            "has_handoff": has_handoff,
            "handoff_target": _infer_specialist(req.prompt, tools_used) if has_handoff else None,
            "cost_usd": cost_info["cost"]["total_cost"],
            "total_tokens": token_usage.total_tokens,
            "duration_ms": latency_ms,
            "prompt_snippet": redact_pii(req.prompt[:120]),
            "timestamp": datetime.utcnow().isoformat(),
        }


        # Langfuse trace 기록
        from api.langfuse_tracing import trace_chat, is_enabled as langfuse_enabled
        if langfuse_enabled():
            trace_chat(
                trace_id=trace_id,
                session_id=session_id,
                user_id=ctx.user_id,
                prompt=req.prompt,
                response=response_text,
                model=MODEL_ID,
                input_tokens=token_usage.input_tokens,
                output_tokens=token_usage.output_tokens,
                latency_ms=latency_ms,
                tools_used=tools_used,
                cost_usd=cost_info["cost"]["total_cost"],
                prompt_version=get_current_prompt_version(),
            )

        return ChatResponse(
            response=response_text,
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            prompt_version=get_current_prompt_version(),
            latency_ms=latency_ms,
            tools_used=tools_used,
            token_usage=token_usage.to_dict(),
            cost=cost_info["cost"],
            guardrails=guardrail_result.to_dict() if guardrail_result else None,
            circuit_state=session.circuit_breaker.state.value,
            redacted=redacted,
        )

    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 1)

        classified = classify_error(e)
        session.circuit_breaker.record_failure()

        record_genai_error(MODEL_ID, get_current_prompt_version(), classified.code)

        if session.circuit_breaker.state == CircuitState.OPEN:
            emit(Events.CIRCUIT_OPEN, session_id=session_id,
                 consecutive_failures=session.circuit_breaker.consecutive_failures)

        session.end_turn()

        emit(
            Events.CHAT_ERROR,
            session_id=session_id,
            turn_id=turn_id,
            error_category=classified.category.value,
            error_code=classified.code,
            retryable=classified.retryable,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "error": classified.to_dict(),
                "retry_delay_ms": get_retry_delay_ms(classified.category, 0) if classified.retryable else None,
                "trace_id": trace_id,
                "turn_id": turn_id,
            },
        )


def _chat_history_by_trace() -> dict[str, dict]:
    """trace_id / otel_trace_id / matched_otel_trace_id → chat_history entry 매핑."""
    result = {}
    for h in _chat_history:
        if h.get("trace_id"):
            result[h["trace_id"]] = h
        if h.get("otel_trace_id"):
            result[h["otel_trace_id"]] = h
        if h.get("matched_otel_trace_id"):
            result[h["matched_otel_trace_id"]] = h
    return result


def _chat_history_by_session() -> dict[str, list[dict]]:
    """session_id → chat_history entries (시간순) 매핑."""
    result: dict[str, list[dict]] = {}
    for h in _chat_history:
        sid = h.get("session_id", "")
        if sid:
            result.setdefault(sid, []).append(h)
    return result


def _match_chat_for_trace(trace: dict) -> dict | None:
    """trace_id / otel_trace_id 직접 매칭 또는 session_id 기반 매칭."""
    trace_tid = trace.get("trace_id", "")

    # 1차: trace_id / otel_trace_id / matched_otel_trace_id 직접 매칭
    chat = _chat_history_by_trace().get(trace_tid)
    if chat:
        return chat

    # 2차: session_id 기반 매칭 (세션에 턴이 하나뿐이면 확정)
    sid = trace.get("session_id", "")
    if sid:
        session_chats = _chat_history_by_session().get(sid, [])
        if len(session_chats) == 1:
            matched = session_chats[0]
            if trace_tid:
                matched["matched_otel_trace_id"] = trace_tid
            return matched

    return None


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, ctx: UserCtx = Depends(get_user_ctx)):
    """Streaming 변형 /chat — AgentCore Runtime의 async generator 응답을 SSE로 프록시.

    프런트엔드는 EventSource 또는 fetch ReadableStream으로 다음 이벤트를 받음:
      data: {"type":"session","session_id":"...","turn_id":"..."}
      data: {"type":"text_delta","delta":"..."}   (토큰 단위 반복)
      data: {"type":"tool_use","name":"..."}
      data: {"type":"final", response, tools_used, usage, latency_ms, ...}
      data: {"type":"complete", cost, guardrails, redacted}
    """
    session_id = req.session_id or str(uuid.uuid4())
    session = get_session_store().get_or_create(session_id)

    # 1) 예산·서킷브레이커 확인 (동기 pre-check)
    enforce_budget(ctx)
    can_proceed, reason = session.circuit_breaker.can_proceed()
    if not can_proceed:
        raise HTTPException(
            status_code=503,
            detail={"error": "circuit_breaker_open", "reason": reason,
                    "circuit_state": session.circuit_breaker.state.value},
        )
    if req.budget_usd is not None:
        get_tracker().set_budget(session_id, req.budget_usd)

    turn_id = str(uuid.uuid4())
    session.start_turn(turn_id)
    emit(Events.CHAT_START, session_id=session_id, turn_id=turn_id,
         prompt_length=len(req.prompt), _SENSITIVE_prompt=req.prompt)

    prompt = req.prompt
    prompt_version = req.prompt_version or get_current_prompt_version()
    enable_guardrails = req.enable_guardrails

    def event_generator():
        from api.agentcore_runtime import _get_client, _get_runtime_arn
        try:
            from api.telemetry import inject_traceparent
            tp = inject_traceparent()
        except Exception:
            tp = None

        # 초기 세션 정보 emit
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id, 'turn_id': turn_id})}\n\n"

        payload = {"prompt": prompt, "session_id": session_id,
                   "prompt_version": prompt_version}
        if tp:
            payload["traceparent"] = tp

        kwargs = {
            "agentRuntimeArn": _get_runtime_arn(),
            "qualifier": "DEFAULT",
            "payload": json.dumps(payload).encode("utf-8"),
        }
        if len(session_id) >= 33:
            kwargs["runtimeSessionId"] = session_id

        started_at = time.time()
        final_event: Optional[dict] = None

        # Publish trace_start event
        trace_id = turn_id
        publish_span_event("trace_start", {
            "trace_id": trace_id,
            "prompt": prompt[:120],
            "model": MODEL_ID or "",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        try:
            resp = _get_client().invoke_agent_runtime(**kwargs)
        except Exception as e:
            err = classify_error(e)
            session.circuit_breaker.record_failure()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:200], 'category': err.category.value})}\n\n"
            return

        body_stream = resp.get("response")
        buffer = b""
        saw_sse_frames = False
        try:
            iterator = body_stream if hasattr(body_stream, "__iter__") else iter([body_stream.read()])
            for chunk in iterator:
                if not chunk:
                    continue
                b = chunk if isinstance(chunk, (bytes, bytearray)) else str(chunk).encode("utf-8")
                buffer += b
                while b"\n\n" in buffer:
                    saw_sse_frames = True
                    frame, buffer = buffer.split(b"\n\n", 1)
                    frame_str = frame.decode("utf-8", errors="replace").strip()
                    if not frame_str:
                        continue
                    data_line = frame_str
                    if frame_str.startswith("data:"):
                        data_line = frame_str[len("data:"):].strip()
                    try:
                        event = json.loads(data_line)
                    except Exception:
                        event = None
                    if isinstance(event, dict) and event.get("type") == "final":
                        final_event = event
                    yield f"data: {data_line}\n\n"

            # 남은 buffer 처리
            rest_bytes = buffer.strip()
            if rest_bytes:
                rest_str = rest_bytes.decode("utf-8", errors="replace")
                if rest_str.startswith("data:"):
                    rest_str = rest_str[len("data:"):].strip()

                # Fallback: Runtime이 SSE 프레임을 보내지 않았다면 (구 동기 entrypoint)
                # 단일 JSON을 전체 응답으로 간주하고 스트리밍 이벤트로 합성.
                if not saw_sse_frames:
                    try:
                        raw = json.loads(rest_str)
                    except Exception:
                        raw = None
                    if isinstance(raw, dict) and "response" in raw:
                        full_text = raw.get("response", "") or ""
                        tool_list = [
                            (t.split("___", 1)[-1] if isinstance(t, str) and "___" in t else t)
                            for t in (raw.get("tools_used") or [])
                        ]
                        for tname in tool_list:
                            yield f"data: {json.dumps({'type': 'tool_use', 'name': tname})}\n\n"
                        if full_text:
                            # 구 runtime은 스트리밍이 없으므로 전체 텍스트를 한 번에.
                            yield f"data: {json.dumps({'type': 'text_delta', 'delta': full_text})}\n\n"
                        final_event = {
                            "type": "final",
                            "response": full_text,
                            "tools_used": tool_list,
                            "usage": raw.get("usage", {}),
                            "latency_ms": raw.get("latency_ms", 0),
                            "otel_trace_id": raw.get("otel_trace_id", ""),
                            "prompt_version": raw.get("prompt_version", prompt_version),
                            "llm_gateway_snapshot": raw.get("llm_gateway_snapshot", {}),
                        }
                        yield f"data: {json.dumps(final_event)}\n\n"
                    else:
                        yield f"data: {rest_str}\n\n"
                else:
                    # 정상 SSE 말미의 마지막 프레임
                    try:
                        event = json.loads(rest_str)
                        if isinstance(event, dict) and event.get("type") == "final":
                            final_event = event
                    except Exception:
                        pass
                    yield f"data: {rest_str}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)[:200]})}\n\n"

        # Post-processing (guardrails · cost · history)
        response_text = (final_event or {}).get("response", "") if final_event else ""
        tools_used = (final_event or {}).get("tools_used", []) if final_event else []
        tools_used = [t.split("___", 1)[-1] for t in tools_used]
        usage_d = (final_event or {}).get("usage", {}) if final_event else {}
        latency_ms = (final_event or {}).get("latency_ms") if final_event else None
        if latency_ms is None:
            latency_ms = round((time.time() - started_at) * 1000, 1)

        guardrail_passed = True
        guardrail_violations: list = []
        guardrail_checks_run: list = []
        guardrail_critical = 0
        guardrail_warn = 0
        guardrail_info = 0
        redacted = False
        if enable_guardrails and response_text:
            try:
                g = validate_response(response_text)
                guardrail_passed = g.passed
                guardrail_checks_run = g.checks_run
                guardrail_critical = g.critical_count
                guardrail_warn = g.warn_count
                guardrail_info = sum(1 for v in g.violations if v.severity.value == "info")
                guardrail_violations = [{"rule_id": v.rule_id, "severity": v.severity.value,
                                         "message": v.message,
                                         "matched_text": v.matched_text[:80] if v.matched_text else None,
                                         "suggestion": v.suggestion} for v in g.violations]
                if any(v.severity.value == "critical" for v in g.violations):
                    redacted = True
            except Exception:
                pass

        cost_info = {}
        try:
            tu = TokenUsage(
                input_tokens=int(usage_d.get("input_tokens", 0)),
                output_tokens=int(usage_d.get("output_tokens", 0)),
            )
            cost_info = get_tracker().record(session_id, MODEL_ID, tu)
        except Exception:
            pass

        # LLM Gateway 캐시 누적
        try:
            snap = (final_event or {}).get("llm_gateway_snapshot")
            if snap:
                _merge_llm_gateway_snapshot(snap)
                get_persistence().persist_llm_gateway(_llm_gateway_acc)
        except Exception:
            pass

        # record to history for /traces & /chat/history
        try:
            _chat_history.append({
                "session_id": session_id,
                "turn_id": turn_id,
                "trace_id": (final_event or {}).get("otel_trace_id") or turn_id,
                "prompt": prompt,
                "response": response_text,
                "tools_used": tools_used,
                "tokens": usage_d,
                "cost": cost_info.get("cost", {}) if cost_info else {},
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow().isoformat(),
                "prompt_version": prompt_version,
                "guardrails_passed": guardrail_passed,
            })
            get_persistence().persist_chat(_chat_history[-1])
        except Exception:
            pass

        # User/Team 사용량 기록 (스트리밍 경로)
        try:
            input_tok = int(usage_d.get("input_tokens", 0))
            output_tok = int(usage_d.get("output_tokens", 0))
            # Runtime이 토큰을 반환하지 않으면 텍스트 길이로 추정
            if input_tok == 0 and prompt:
                input_tok = max(len(prompt) // 4, 1)
            if output_tok == 0 and response_text:
                output_tok = max(len(response_text) // 4, 1)
            record_usage(UsageRecord(
                user_id=ctx.user_id,
                team_id=ctx.team_id,
                timestamp=datetime.utcnow().isoformat(),
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=input_tok + output_tok,
                cost_usd=cost_info.get("cost", {}).get("total_cost", 0) if cost_info else 0,
                model=MODEL_ID,
                tools_used=tools_used,
                prompt_version=prompt_version,
                session_id=session_id,
                trace_id=(final_event or {}).get("otel_trace_id") or turn_id,
                latency_ms=int(latency_ms),
            ))
        except Exception:
            pass

        session.circuit_breaker.record_success()
        session.end_turn()
        get_session_store().persist(session_id)

        # Publish trace_end event
        publish_span_event("trace_end", {
            "trace_id": trace_id,
            "total_duration_ms": round(latency_ms),
            "final_status": "ok",
        })

        # Final enriched event
        complete = {
            "type": "complete",
            "session_id": session_id,
            "turn_id": turn_id,
            "trace_id": (final_event or {}).get("otel_trace_id") or turn_id,
            "latency_ms": latency_ms,
            "cost": cost_info.get("cost", {}) if cost_info else {},
            "guardrails": {
                "passed": guardrail_passed,
                "critical_count": guardrail_critical,
                "warn_count": guardrail_warn,
                "info_count": guardrail_info,
                "checks_run": guardrail_checks_run,
                "violations": guardrail_violations,
            },
            "redacted": redacted,
            "circuit_state": session.circuit_breaker.state.value,
        }
        yield f"data: {json.dumps(complete)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
            "X-Turn-Id": turn_id,
        },
    )


@app.get("/traces")
def list_traces(
    limit: int = Query(20, ge=1, le=200),
    hours: int = Query(6, ge=1, le=168),
):
    """최근 트레이스 (턴) 목록. OTEL + chat_history 병합."""
    traces = cw_helper.get_recent_traces(limit, hours=hours)
    for t in traces:
        chat = _match_chat_for_trace(t)
        if chat:
            if not t.get("prompt"):
                t["prompt"] = chat.get("prompt", "")[:120]
            if not t.get("turn_id"):
                t["turn_id"] = chat.get("turn_id", "")
            if not t.get("session_id"):
                t["session_id"] = chat.get("session_id", "")
    return {"traces": traces, "count": len(traces)}


@app.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    """트레이스 상세. OTEL spans + chat_history 병합."""
    detail = cw_helper.get_trace_detail(trace_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Trace not found")
    chat = _match_chat_for_trace(detail)
    if chat:
        if not detail.get("prompt"):
            detail["prompt"] = chat.get("prompt", "")
        if not detail.get("response"):
            detail["response"] = chat.get("response", "")
        if not detail.get("turn_id"):
            detail["turn_id"] = chat.get("turn_id", "")
        if not detail.get("session_id"):
            detail["session_id"] = chat.get("session_id", "")
    return detail


@app.get("/traces/stream")
async def stream_traces():
    """SSE endpoint for real-time trace/span events."""
    queue = subscribe_span_events()

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_span_events(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/agents")
def list_agents():
    """사용 가능한 AgentCore Runtime 에이전트 목록."""
    agents = cw_helper.list_agents()
    return {"agents": agents, "count": len(agents)}


@app.get("/metrics")
def get_metrics(
    hours: int = Query(1, ge=1, le=168),
    agent_id: str = Query(None, description="Agent ID to filter metrics"),
    user_id: str = Query(None, description="User ID to filter metrics (DynamoDB-based)"),
):
    """집계 메트릭. user_id 지정 시 해당 유저의 DynamoDB 사용 기록에서 집계."""
    if user_id:
        return _get_user_metrics(user_id, hours)

    base = cw_helper.get_aggregated_metrics(hours, agent_id=agent_id)
    global_cost = get_tracker().get_global_state()
    analytics_stats = get_queue().get_stats()
    event_counts = get_memory_sink().get_event_counts()

    return {
        **base,
        "cost_global": global_cost,
        "analytics": analytics_stats,
        "event_counts": event_counts,
    }


def _get_user_metrics(user_id: str, hours: int) -> dict:
    """DynamoDB USAGE_TABLE에서 유저별 메트릭을 MetricsData 포맷으로 집계."""
    from datetime import timedelta
    from boto3.dynamodb.conditions import Key as DdbKey

    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    table = get_persistence()._usage_table()

    try:
        resp = table.query(
            KeyConditionExpression=DdbKey("user_id").eq(user_id) & DdbKey("sort_key").gte(f"ts#{cutoff}"),
            Limit=500,
        )
        items = resp.get("Items", [])
    except Exception as e:
        return {"error": str(e)[:200], "source": "dynamodb"}

    if not items:
        return {
            "invocation_count": 0,
            "latency": {"avg": 0, "p50": 0, "p99": 0, "values": []},
            "tokens": {"total": 0, "input": 0, "output": 0, "avg_per_call": 0, "values": []},
            "cost": {"total_usd": 0, "values": []},
            "tool_calls": {},
            "tool_durations": {},
            "source": "dynamodb",
            "user_id": user_id,
        }

    latencies = []
    total_input = 0
    total_output = 0
    total_cost = 0.0
    tool_counts: dict[str, int] = {}
    latency_ts: list[dict] = []
    token_ts: list[dict] = []
    cost_ts: list[dict] = []

    for item in items:
        lat = int(item.get("latency_ms", 0) or 0)
        inp = int(item.get("input_tokens", 0) or 0)
        out = int(item.get("output_tokens", 0) or 0)
        cost = float(item.get("cost_usd", 0) or 0)
        ts = item.get("sort_key", "")[3:30] if item.get("sort_key", "").startswith("ts#") else ""

        latencies.append(lat)
        total_input += inp
        total_output += out
        total_cost += cost

        tools = item.get("tools_used", set())
        if isinstance(tools, set):
            tools = list(tools)
        for t in tools:
            if t and t != "none":
                tool_counts[t] = tool_counts.get(t, 0) + 1

        if ts:
            latency_ts.append({"timestamp": ts, "value": lat})
            token_ts.append({"timestamp": ts, "value": inp + out})
            cost_ts.append({"timestamp": ts, "value": cost})

    n = len(items)
    sorted_lat = sorted(latencies)
    avg_lat = sum(latencies) / n if n else 0
    p50 = sorted_lat[n // 2] if n else 0
    p99 = sorted_lat[int(n * 0.99)] if n else 0
    total_tokens = total_input + total_output

    return {
        "invocation_count": n,
        "latency": {
            "avg": round(avg_lat, 1),
            "p50": round(p50, 1),
            "p99": round(p99, 1),
            "values": latency_ts[-20:],
        },
        "tokens": {
            "total": total_tokens,
            "input": total_input,
            "output": total_output,
            "avg_per_call": round(total_tokens / n) if n else 0,
            "values": token_ts[-20:],
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "values": cost_ts[-20:],
        },
        "tool_calls": tool_counts,
        "tool_durations": {},
        "source": "dynamodb",
        "user_id": user_id,
    }


@app.get("/evaluations/evaluators")
def get_evaluators():
    """사용 가능한 AgentCore 평가기 목록."""
    import api.agentcore_evaluation as ac_eval
    return {"evaluators": ac_eval.list_evaluators()}


@app.get("/evaluations/online/configs")
def get_online_configs():
    """Online Evaluation Config 목록."""
    import api.agentcore_evaluation as ac_eval
    return {"configs": ac_eval.list_online_configs()}


@app.get("/evaluations/online/config/{config_id}")
def get_online_config_detail(config_id: str):
    """Online Evaluation Config 상세."""
    import api.agentcore_evaluation as ac_eval
    return ac_eval.get_online_config(config_id)


@app.post("/evaluations/online/config")
def create_online_config(req: dict):
    """Online Evaluation Config 생성."""
    import api.agentcore_evaluation as ac_eval
    name = req.get("name", "eval_config")
    evaluator_ids = req.get("evaluator_ids", ["Builtin.Helpfulness", "Builtin.Correctness", "Builtin.GoalSuccessRate"])
    sampling_rate = req.get("sampling_rate", 100.0)
    description = req.get("description", "")
    return ac_eval.create_online_config(name, evaluator_ids, sampling_rate, description)


@app.put("/evaluations/online/config/{config_id}")
def update_online_config(config_id: str, req: dict):
    """Online Evaluation Config 수정."""
    import api.agentcore_evaluation as ac_eval
    return ac_eval.update_online_config(
        config_id,
        sampling_rate=req.get("sampling_rate"),
        evaluator_ids=req.get("evaluator_ids"),
        enabled=req.get("enabled"),
    )


@app.delete("/evaluations/online/config/{config_id}")
def delete_online_config(config_id: str):
    """Online Evaluation Config 삭제."""
    import api.agentcore_evaluation as ac_eval
    return ac_eval.delete_online_config(config_id)


@app.get("/evaluations/online/results/{config_id}")
def get_online_results(config_id: str, hours: int = Query(24, ge=1, le=720)):
    """Online Evaluation 결과 조회 (CloudWatch Logs)."""
    import api.agentcore_evaluation as ac_eval
    return ac_eval.get_online_results(config_id, hours=hours)


@app.post("/evaluations/run")
def run_evaluation(req: EvalRequest):
    """On-demand 평가 실행 (단일 세션/트레이스)."""
    import api.agentcore_evaluation as ac_eval

    session_id = req.session_id
    trace_id = req.trace_id

    if not session_id and _chat_history:
        last = _chat_history[-1]
        session_id = last.get("session_id", "")
        if not trace_id:
            trace_id = last.get("otel_trace_id") or last.get("trace_id", "")

    if not session_id:
        traces = cw_helper.get_recent_traces(1)
        if traces:
            session_id = traces[0].get("session_id", "")
            if not trace_id:
                trace_id = traces[0].get("trace_id", "")

    if not session_id:
        raise HTTPException(status_code=400, detail="No session available. Send a chat message first or provide session_id.")

    results = ac_eval.run_on_demand(
        evaluator_ids=req.evaluators,
        session_id=session_id,
        trace_id=trace_id,
        look_back_hours=req.lookback_days * 24,
    )

    return {
        "eval_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "trace_id": trace_id or "",
        "results": results,
    }


@app.post("/evaluations/batch")
def start_batch_evaluation(req: dict):
    """Batch evaluation 시작."""
    import api.agentcore_evaluation as ac_eval
    name = req.get("name", f"batch_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
    evaluator_ids = req.get("evaluator_ids", ["Builtin.Helpfulness", "Builtin.Correctness", "Builtin.GoalSuccessRate"])
    return ac_eval.start_batch(name, evaluator_ids)


@app.get("/evaluations/batch")
def list_batch_evaluations():
    """Batch evaluation 목록."""
    import api.agentcore_evaluation as ac_eval
    return {"batches": ac_eval.list_batches()}


@app.get("/evaluations/batch/{batch_id}")
def get_batch_evaluation(batch_id: str):
    """Batch evaluation 상세 + 결과."""
    import api.agentcore_evaluation as ac_eval
    detail = ac_eval.get_batch(batch_id)
    if detail.get("status") == "COMPLETED" and not detail.get("results"):
        results = ac_eval.get_batch_results(batch_id)
        detail["results"] = results.get("results", [])
        detail["results_summary"] = results.get("summary", {})
    return detail


# --- Optimization Endpoints (AgentCore Optimization API) ---


@app.get("/optimization/status")
def get_optimization_status():
    """전체 optimization 파이프라인 상태 — history는 AgentCore API에서 조회."""
    from api.agentcore_optimization import list_recommendations, list_bundles, list_bundle_versions

    history = []
    try:
        recs = list_recommendations()
        for r in recs:
            history.append({
                "type": "recommendation",
                "id": r.get("recommendation_id", ""),
                "name": r.get("name", ""),
                "status": r.get("status", ""),
                "timestamp": r.get("created_at", ""),
            })

        bundles = list_bundles()
        active_bundle_id = _optimization_state.get("active_bundle_id")
        if active_bundle_id:
            try:
                versions = list_bundle_versions(active_bundle_id)
                for v in versions:
                    history.append({
                        "type": "bundle_version",
                        "bundle_id": active_bundle_id,
                        "version_id": v.get("version_id", ""),
                        "commit_message": v.get("commit_message", ""),
                        "timestamp": v.get("created_at", ""),
                    })
            except Exception:
                pass

        history = [h for h in history if h.get("timestamp")]
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception as e:
        history = [{"type": "error", "message": str(e)}]

    return {**_optimization_state, "history": history}


@app.post("/optimization/recommendations")
def create_recommendation_endpoint(req: dict = Body(...)):
    """추천 생성 — trace 분석 시작."""
    from api.agentcore_optimization import start_recommendation
    from agent.system_prompt import get_prompt

    evaluator_id = req.get("evaluator_id", "Builtin.GoalSuccessRate")
    lookback_days = req.get("lookback_days", 7)
    current_prompt = get_prompt(get_current_prompt_version())

    name = f"rec-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    result = start_recommendation(
        name=name,
        evaluator_id=evaluator_id,
        current_prompt=current_prompt,
        lookback_days=lookback_days,
    )

    _optimization_state["stage"] = "recommending"
    _optimization_state["active_recommendation"] = result
    get_persistence().persist_optimization_state(_optimization_state)

    return result


@app.get("/optimization/recommendations")
def list_recommendations_endpoint():
    """추천 목록 조회."""
    from api.agentcore_optimization import list_recommendations
    return {"recommendations": list_recommendations()}


@app.get("/optimization/recommendations/{recommendation_id}")
def get_recommendation_endpoint(recommendation_id: str):
    """특정 추천 상세 조회."""
    from api.agentcore_optimization import get_recommendation

    result = get_recommendation(recommendation_id)

    if _optimization_state.get("stage") == "recommending":
        if result.get("status") == "COMPLETED":
            _optimization_state["stage"] = "recommended"
            _optimization_state["active_recommendation"] = result
            get_persistence().persist_optimization_state(_optimization_state)
        elif result.get("status") == "FAILED":
            _optimization_state["stage"] = "idle"
            _optimization_state["active_recommendation"] = result
            get_persistence().persist_optimization_state(_optimization_state)

    return result


@app.post("/optimization/bundles")
def create_bundle_endpoint(req: dict = Body(...)):
    """Configuration Bundle 생성."""
    from api.agentcore_optimization import create_bundle

    bundle_name = req.get("bundle_name", "")
    system_prompt = req.get("system_prompt", "")
    description = req.get("description", "")

    if not bundle_name or not system_prompt:
        raise HTTPException(status_code=400, detail="bundle_name and system_prompt required")

    return create_bundle(bundle_name, system_prompt, description)


@app.get("/optimization/bundles")
def list_bundles_endpoint():
    """Configuration Bundle 목록."""
    from api.agentcore_optimization import list_bundles
    return {"bundles": list_bundles()}


@app.get("/optimization/bundles/{bundle_id}")
def get_bundle_endpoint(bundle_id: str, version_id: Optional[str] = None):
    """Configuration Bundle 상세."""
    from api.agentcore_optimization import get_bundle
    return get_bundle(bundle_id, version_id)


@app.get("/optimization/bundles/{bundle_id}/versions")
def list_bundle_versions_endpoint(bundle_id: str):
    """Configuration Bundle 버전 목록."""
    from api.agentcore_optimization import list_bundle_versions
    return {"versions": list_bundle_versions(bundle_id)}


_ab_test_state: Optional[dict] = None


@app.post("/optimization/ab-tests")
def create_ab_test_endpoint(req: dict = Body(...)):
    """A/B 테스트 생성 — Gateway traffic split via Configuration Bundle variants."""
    global _ab_test_state
    from agent.system_prompt import get_prompt

    control_weight = req.get("control_weight", 80)
    treatment_weight = req.get("treatment_weight", 20)
    treatment_prompt = req.get("treatment_prompt", "")
    control_version = req.get("control_version", get_current_prompt_version())

    if not treatment_prompt:
        rec = _optimization_state.get("active_recommendation") or {}
        treatment_prompt = rec.get("recommended_prompt", "")
    if not treatment_prompt:
        raise HTTPException(status_code=400, detail="treatment_prompt required or run recommendation first")

    test_id = f"ab-{uuid.uuid4().hex[:8]}"
    _ab_test_state = {
        "rule_id": test_id,
        "status": "RUNNING",
        "control": {"version": control_version, "prompt": get_prompt(control_version), "weight": control_weight},
        "treatment": {"version": "recommended", "prompt": treatment_prompt, "weight": treatment_weight},
        "stats": {"control_count": 0, "treatment_count": 0},
        "created_at": datetime.utcnow().isoformat(),
    }

    _optimization_state["stage"] = "testing"
    _optimization_state["active_test"] = {
        "rule_id": test_id,
        "status": "RUNNING",
        "control_weight": control_weight,
        "treatment_weight": treatment_weight,
        "created_at": _ab_test_state["created_at"],
    }
    get_persistence().persist_optimization_state(_optimization_state)

    return _optimization_state["active_test"]


@app.post("/optimization/ab-tests/{rule_id}/complete")
def complete_ab_test_endpoint(rule_id: str, req: dict = Body(...)):
    """A/B 테스트 종료 + winner 배포."""
    global _ab_test_state
    from agent.system_prompt import PROMPT_VERSIONS

    winner = req.get("winner", "treatment")

    if winner == "treatment" and _ab_test_state:
        treatment_prompt = _ab_test_state["treatment"]["prompt"]
        version_key = f"v{len(PROMPT_VERSIONS) + 1}"
        PROMPT_VERSIONS[version_key] = treatment_prompt
        set_prompt_version(version_key)
        emit(Events.PROMPT_VERSION_CHANGE, new_version=version_key)

    _ab_test_state = None
    _optimization_state["stage"] = "complete"
    _optimization_state["active_test"] = None
    get_persistence().persist_optimization_state(_optimization_state)

    return {"status": "completed", "winner": winner, "rule_id": rule_id}


@app.post("/optimization/apply")
def apply_recommendation_endpoint(req: dict = Body(...)):
    """추천 프롬프트를 Configuration Bundle로 저장하고 에이전트에 적용."""
    from api.agentcore_optimization import create_bundle, update_bundle
    from agent.system_prompt import PROMPT_VERSIONS

    recommended_prompt = req.get("system_prompt", "")
    recommendation_id = req.get("recommendation_id", "")
    if not recommended_prompt:
        raise HTTPException(status_code=400, detail="system_prompt required")

    active_bundle_id = _optimization_state.get("active_bundle_id")
    if active_bundle_id:
        result = update_bundle(
            bundle_id=active_bundle_id,
            system_prompt=recommended_prompt,
            commit_message=f"Applied recommendation {recommendation_id}",
        )
    else:
        result = create_bundle(
            bundle_name="agent_prompt_" + _RUNTIME_NAME.replace("-", "_"),
            system_prompt=recommended_prompt,
            description=f"Auto-created from recommendation {recommendation_id}",
        )
        _optimization_state["active_bundle_id"] = result.get("bundle_id", "")

    prev_version = get_current_prompt_version()
    version_key = f"v{len(PROMPT_VERSIONS) + 1}"
    PROMPT_VERSIONS[version_key] = recommended_prompt
    set_prompt_version(version_key)
    emit(Events.PROMPT_VERSION_CHANGE, new_version=version_key)

    _optimization_state["stage"] = "applied"
    _optimization_state["active_recommendation"] = {
        **(_optimization_state.get("active_recommendation") or {}),
        "bundle_id": result.get("bundle_id", _optimization_state.get("active_bundle_id", "")),
        "bundle_arn": result.get("bundle_arn", ""),
        "bundle_version": result.get("version_id", ""),
        "applied_version": version_key,
    }
    get_persistence().persist_optimization_state(_optimization_state)

    return {
        "status": "applied",
        "version": version_key,
        "version_from": prev_version,
        "bundle_id": result.get("bundle_id", ""),
        "bundle_arn": result.get("bundle_arn", ""),
        "bundle_version": result.get("version_id", ""),
    }


@app.post("/optimization/deploy")
def deploy_winner_endpoint(req: dict = Body(...)):
    """Winner 프롬프트를 active로 배포 (직접 배포 또는 A/B 테스트 후 배포)."""
    new_prompt = req.get("system_prompt", "")
    version_label = req.get("version_label", "")

    if not new_prompt:
        raise HTTPException(status_code=400, detail="system_prompt required")

    from api.agentcore_optimization import create_bundle, update_bundle
    from agent.system_prompt import PROMPT_VERSIONS

    active_bundle_id = _optimization_state.get("active_bundle_id")
    if active_bundle_id:
        update_bundle(
            bundle_id=active_bundle_id,
            system_prompt=new_prompt,
            commit_message=f"Deploy winner: {version_label or 'direct'}",
        )
    else:
        result = create_bundle(
            bundle_name="agent_prompt_" + _RUNTIME_NAME.replace("-", "_"),
            system_prompt=new_prompt,
            description="Deployed via optimization pipeline",
        )
        _optimization_state["active_bundle_id"] = result.get("bundle_id", "")

    version_key = version_label or f"v{len(PROMPT_VERSIONS) + 1}"
    PROMPT_VERSIONS[version_key] = new_prompt
    set_prompt_version(version_key)
    emit(Events.PROMPT_VERSION_CHANGE, new_version=version_key)

    _optimization_state["stage"] = "idle"
    get_persistence().persist_optimization_state(_optimization_state)
    return {"status": "deployed", "version": version_key}


@app.post("/optimization/reset")
def reset_optimization():
    """Optimization 파이프라인 초기화."""
    global _ab_test_state
    _ab_test_state = None
    _optimization_state.update({
        "stage": "idle",
        "active_recommendation": None,
        "active_test": None,
    })
    get_persistence().persist_optimization_state(_optimization_state)
    return {"status": "idle"}


# --- Evaluation Analysis Endpoints ---




@app.put("/system-prompt")
def update_system_prompt(req: PromptUpdateRequest):
    if set_prompt_version(req.version):
        emit(Events.PROMPT_VERSION_CHANGE, new_version=req.version)
        return {
            "status": "updated",
            "version": req.version,
            "message": f"Prompt switched to {req.version}",
        }
    raise HTTPException(status_code=400, detail=f"Invalid version: {req.version}")


@app.get("/system-prompt")
def get_system_prompt():
    from agent.system_prompt import get_prompt
    version = get_current_prompt_version()
    return {"version": version, "prompt": get_prompt(version)}


@app.get("/system-prompt/versions")
def list_prompt_versions():
    from agent.system_prompt import PROMPT_VERSIONS
    return {
        "current": get_current_prompt_version(),
        "versions": sorted(PROMPT_VERSIONS.keys()),
    }


@app.get("/system-prompt/{version}")
def get_prompt_by_version(version: str):
    from agent.system_prompt import PROMPT_VERSIONS, get_prompt
    if version not in PROMPT_VERSIONS:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return {"version": version, "prompt": get_prompt(version)}


# --- 새로운 프로덕션 검증 엔드포인트 ---


@app.get("/session/{session_id}")
def get_session_detail(session_id: str):
    """세션 상태 + 서킷 브레이커 상태."""
    session = get_session_store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    cost_state = get_tracker().get_session_state(session_id)
    return {
        **session.to_dict(),
        "cost_state": cost_state,
    }


@app.get("/sessions")
def list_sessions(limit: int = Query(20, ge=1, le=200)):
    sessions = get_session_store().list_sessions(limit)
    return {
        "sessions": [s.to_dict() for s in sessions],
        "count": len(sessions),
    }


@app.post("/budget")
def set_session_budget(req: BudgetRequest):
    """세션 예산 설정 (legacy in-memory)."""
    get_tracker().set_budget(req.session_id, req.budget_usd)
    state = get_tracker().get_session_state(req.session_id)
    return {"status": "ok", "session_cost": state}


@app.get("/cost")
def get_cost_overview():
    """전역 비용 현황."""
    return get_tracker().get_global_state()


@app.get("/cost/{session_id}")
def get_session_cost(session_id: str):
    """세션별 비용 상세."""
    state = get_tracker().get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not tracked")
    return state


@app.get("/analytics/events")
def get_analytics_events(
    event_name: Optional[str] = Query(None, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$"),
    limit: int = Query(100, ge=1, le=1000),
):
    """분석 이벤트 조회."""
    events = get_memory_sink().get_events(filter_name=event_name, limit=limit)
    return {"events": events, "count": len(events)}


@app.get("/analytics/summary")
def get_analytics_summary():
    """이벤트 카운트 요약."""
    return {
        "event_counts": get_memory_sink().get_event_counts(),
        "queue_stats": get_queue().get_stats(),
    }


class GuardrailTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    tool_outputs: list[str] = Field(default_factory=list, max_length=20)


@app.post("/guardrails/test")
def test_guardrails(payload: GuardrailTestRequest):
    """가드레일 단독 테스트 엔드포인트."""
    result = validate_response(payload.text, tool_outputs=payload.tool_outputs)
    return result.to_dict()


@app.get("/circuit/{session_id}")
def get_circuit_state(session_id: str):
    """서킷 브레이커 상태 조회."""
    session = get_session_store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.circuit_breaker.to_dict()


@app.post("/circuit/{session_id}/reset")
def reset_circuit(session_id: str):
    """서킷 브레이커 수동 리셋."""
    session = get_session_store().get_or_create(session_id)
    session.circuit_breaker.consecutive_failures = 0
    session.circuit_breaker.state = CircuitState.CLOSED
    emit(Events.CIRCUIT_CLOSED, session_id=session_id, reason="manual_reset")
    return {"status": "reset", "circuit_breaker": session.circuit_breaker.to_dict()}


# --- Gateway 페이지용 엔드포인트 ---


@app.get("/gateways/llm")
def get_llm_gateway():
    """LLM Gateway 현황 — 모델 카탈로그, 최근 호출, 가드레일 통계.

    우선순위:
      1) BFF 누적 캐시(_llm_gateway_acc) — 실제 chat 호출로 쌓인 정확한 데이터
      2) Runtime op=llm_gateway_stats — 단일 컨테이너 세션의 snapshot
      3) Fallback 7-model empty snapshot
    """
    # 1) 캐시에 실제 호출 데이터가 있으면 그걸 우선 반환 (누적 통계)
    if _llm_gateway_acc["models"]:
        # 전체 7-model 템플릿과 병합 — 호출 없는 모델도 목록에 보이도록
        _all_models = [
            ("opus-4-7",     "global.anthropic.claude-opus-4-7",     "premium"),
            ("sonnet-4-6",   "global.anthropic.claude-sonnet-4-6",   "quality"),
            ("haiku-4-5",    "global.anthropic.claude-haiku-4-5",    "cost"),
            ("nova-pro",     "us.amazon.nova-pro-v1:0",              "quality"),
            ("nova-2-lite",  "global.amazon.nova-2-lite-v1:0",       "cost"),
            ("gpt-oss-120b", "openai.gpt-oss-120b-1:0",              "cost"),
            ("gpt-oss-20b",  "openai.gpt-oss-20b-1:0",               "cost"),
        ]
        merged = []
        for name, mid, tier in _all_models:
            if name in _llm_gateway_acc["models"]:
                m = _llm_gateway_acc["models"][name]
                merged.append({
                    "name": m["name"], "id": m.get("id") or mid,
                    "tier": m.get("tier") or tier,
                    "calls": m["calls"], "input_tokens": m["input_tokens"],
                    "output_tokens": m["output_tokens"],
                    "avg_latency_ms": round(m.get("avg_latency_ms") or 0, 1),
                    "cost_usd": round(m.get("cost_usd") or 0, 6),
                })
            else:
                merged.append({
                    "name": name, "id": mid, "tier": tier,
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "avg_latency_ms": 0, "cost_usd": 0.0,
                })
        return {
            "routing_policy": _llm_gateway_acc["routing_policy"],
            "models": merged,
            "recent_calls": _llm_gateway_acc["recent_calls"],
            "guardrails": _llm_gateway_acc["guardrails"],
            "total_calls": _llm_gateway_acc["total_calls"],
            "last_model_used": _llm_gateway_acc["last_model_used"],
            "last_routing_reason": _llm_gateway_acc["last_routing_reason"],
        }

    # 2) 아직 호출이 없었다면 runtime에 물어본다 (cold-path)
    try:
        from api.agentcore_runtime import _get_client, _get_runtime_arn
        resp = _get_client().invoke_agent_runtime(
            agentRuntimeArn=_get_runtime_arn(),
            qualifier="DEFAULT",
            payload=json.dumps({"op": "llm_gateway_stats"}).encode("utf-8"),
        )
        body = resp.get("response")
        raw = body.read() if hasattr(body, "read") else b"".join(body)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        # Runtime이 아직 stats를 보낸 적 없거나 실패 시 — agent/llm_gateway.py의
        # MODEL_CATALOG 전체를 미러링한 빈 스냅샷 반환.
        _EMPTY_STATS = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                        "avg_latency_ms": 0, "cost_usd": 0}
        return {
            "routing_policy": os.getenv("LLM_GATEWAY_ROUTING", "quality"),
            "models": [
                {"name": "opus-4-7",     "id": "global.anthropic.claude-opus-4-7",
                 "tier": "premium", **_EMPTY_STATS},
                {"name": "sonnet-4-6",   "id": "global.anthropic.claude-sonnet-4-6",
                 "tier": "quality", **_EMPTY_STATS},
                {"name": "haiku-4-5",    "id": "global.anthropic.claude-haiku-4-5",
                 "tier": "cost",    **_EMPTY_STATS},
                {"name": "nova-pro",     "id": "us.amazon.nova-pro-v1:0",
                 "tier": "quality", **_EMPTY_STATS},
                {"name": "nova-2-lite",  "id": "global.amazon.nova-2-lite-v1:0",
                 "tier": "cost",    **_EMPTY_STATS},
                {"name": "gpt-oss-120b", "id": "openai.gpt-oss-120b-1:0",
                 "tier": "cost",    **_EMPTY_STATS},
                {"name": "gpt-oss-20b",  "id": "openai.gpt-oss-20b-1:0",
                 "tier": "cost",    **_EMPTY_STATS},
            ],
            "recent_calls": [],
            "guardrails": {"input_scrubs": 0, "output_scrubs": 0, "detected_tags": {}},
            "total_calls": 0,
            "last_model_used": "",
            "last_routing_reason": "",
            "error": str(e)[:200],
        }


def _local_tool_call_counts() -> dict[str, int]:
    """현재 서버 세션의 _chat_history로부터 도구 호출 빈도를 즉시 집계."""
    counts: dict[str, int] = {}
    for h in _chat_history:
        for tname in h.get("tools_used", []) or []:
            base = tname.split("___", 1)[-1] if "___" in tname else tname
            counts[base] = counts.get(base, 0) + 1
    return counts


def _last_tool_used_display() -> Optional[str]:
    """Journey Strip/Tool Gateway 펄스용 — delegate_to_specialist는 제외하고 직전 턴의 마지막 MCP 도구."""
    if not _last_turn_summary:
        return None
    tools = _last_turn_summary.get("tools_used") or []
    filtered = [t for t in tools if t != "delegate_to_specialist"]
    if filtered:
        return filtered[-1]
    return tools[-1] if tools else None


@app.get("/gateways/tool")
def get_tool_gateway():
    """AgentCore Gateway 현황 — 등록된 MCP 도구 목록 + 호출 빈도."""
    local_counts = _local_tool_call_counts()
    last_tool_used = _last_tool_used_display()
    try:
        import boto3
        cp = boto3.client("bedrock-agentcore-control", region_name=os.getenv("AWS_REGION", "us-east-1"))
        gateways = cp.list_gateways().get("items", [])
        gw = next((g for g in gateways if g["name"] == _GATEWAY_NAME), None)
        if not gw:
            return {
                "error": "gateway_not_found",
                "tools": [],
                "call_counts": local_counts,
                "last_tool_used": last_tool_used,
            }
        gid = gw["gatewayId"]
        targets = cp.list_gateway_targets(gatewayIdentifier=gid).get("items", [])
        target = next((t for t in targets if t["name"] == _GATEWAY_TARGET_NAME), None)

        # 도구 스키마는 target config에서 가져옴
        tools_info = []
        if target:
            detail = cp.get_gateway_target(gatewayIdentifier=gid, targetId=target["targetId"])
            schema = detail.get("targetConfiguration", {}).get("mcp", {}).get("lambda", {}).get("toolSchema", {})
            for t in schema.get("inlinePayload", []):
                tools_info.append({
                    "name": t.get("name"),
                    "description": t.get("description"),
                    "schema": t.get("inputSchema", {}),
                })
        # CloudWatch + 로컬 히스토리 호출 빈도 병합 (라이브 데모에서 즉시 반영되도록)
        cw_counts: dict[str, int] = {}
        try:
            for t in cw_helper.get_recent_traces(100):
                for tool_name in t.get("tools_used", []):
                    base = tool_name.split("___", 1)[-1] if "___" in tool_name else tool_name
                    cw_counts[base] = cw_counts.get(base, 0) + 1
        except Exception:
            cw_counts = {}
        call_counts = {
            k: max(local_counts.get(k, 0), cw_counts.get(k, 0))
            for k in set(local_counts) | set(cw_counts)
        }
        return {
            "gateway_id": gid,
            "gateway_name": gw["name"],
            "gateway_url": gw.get("gatewayUrl"),
            "semantic_search_enabled": True,
            "authorizer": "cognito_oauth",
            "tool_count": len(tools_info),
            "tools": tools_info,
            "call_counts": call_counts,
            "last_tool_used": last_tool_used,
        }
    except Exception as e:
        return {
            "error": str(e)[:200],
            "tools": [],
            "call_counts": local_counts,
            "last_tool_used": last_tool_used,
        }


# --- User/Team 사용량 추적 엔드포인트 (Work B) ---


class BudgetUpdateRequest(BaseModel):
    entity_type: str = Field(pattern=r"^(user|team)$")
    entity_id: str = Field(min_length=1, max_length=64)
    budget_usd: float = Field(ge=0.0, le=10000.0)


@app.get("/users")
def get_users(team_id: Optional[str] = Query(None, max_length=64), top: bool = False, days: int = Query(7, ge=1, le=90)):
    """사용자 목록 — top=true면 상위 사용자 랭킹."""
    if top:
        return {"users": top_users(days=days, limit=20), "window_days": days, "ranking": True}
    return {"users": list_users(team_id=team_id), "team_filter": team_id}


@app.get("/users/{user_id}")
def get_user_detail(user_id: str, days: int = Query(30, ge=1, le=90)):
    entry = get_directory_entry("user", user_id)
    usage = get_user_usage(user_id, days=days)
    budget = get_budget_state("user", user_id)
    if not entry:
        team_id = ""
        if usage.get("recent_calls"):
            team_id = usage["recent_calls"][-1].get("team_id", "")
        entry = {
            "entity_id": user_id,
            "entity_type": "user",
            "name": user_id,
            "team_id": team_id,
            "role": "",
            "email": "",
            "created_at": "",
        }
    return {"directory": entry, "usage": usage, "budget": budget}


@app.get("/teams")
def get_teams(top: bool = False, days: int = Query(7, ge=1, le=90)):
    if top:
        return {"teams": top_teams(days=days, limit=10), "window_days": days, "ranking": True}
    return {"teams": list_teams()}


@app.get("/teams/{team_id}")
def get_team_detail(team_id: str, days: int = Query(30, ge=1, le=90)):
    entry = get_directory_entry("team", team_id)
    usage = get_team_usage(team_id, days=days)
    budget = get_budget_state("team", team_id)
    return {"directory": entry, "usage": usage, "budget": budget}


@app.post("/budgets")
def update_budget(req: BudgetUpdateRequest):
    set_budget(req.entity_type, req.entity_id, req.budget_usd)
    return get_budget_state(req.entity_type, req.entity_id)


@app.get("/budgets/{entity_type}/{entity_id}")
def get_budget_detail(entity_type: str, entity_id: str):
    if entity_type not in ("user", "team"):
        raise HTTPException(status_code=400, detail="entity_type must be 'user' or 'team'")
    return get_budget_state(entity_type, entity_id)


@app.get("/registry")
def get_registry():
    """AgentCore Registry 현황 — 등록된 에이전트/MCP 서버 목록."""
    try:
        import boto3
        region = os.getenv("REGISTRY_REGION", "us-east-1")
        registry_id = os.getenv("REGISTRY_ID")
        if not registry_id:
            return {"error": "registry_not_configured", "records": []}

        c = boto3.client("bedrock-agentcore-control", region_name=region)
        resp = c.list_registry_records(registryId=registry_id, maxResults=50)
        records_raw = resp.get("registryRecords", resp.get("items", []))

        status_map = {"PENDING_APPROVAL": "SUBMITTED"}
        a2a_agents = _get_a2a_names()
        records = []
        for r in records_raw:
            raw_status = r.get("status", "")
            name = r.get("name", "")
            dtype = r.get("descriptorType", "")
            if dtype == "CUSTOM" and name in a2a_agents:
                dtype = "A2A"
            records.append({
                "record_id": r.get("recordId"),
                "name": name,
                "description": r.get("description"),
                "descriptor_type": dtype,
                "status": status_map.get(raw_status, raw_status),
                "created_at": r.get("createdAt").isoformat() if r.get("createdAt") else None,
                "updated_at": r.get("updatedAt").isoformat() if r.get("updatedAt") else None,
            })

        # 레지스트리 메타 조회
        reg_meta = c.list_registries(maxResults=50)
        reg = next(
            (x for x in reg_meta.get("registries", []) if x.get("registryId") == registry_id),
            {},
        )

        return {
            "registry_id": registry_id,
            "registry_name": reg.get("name"),
            "authorizer_type": reg.get("authorizerType"),
            "status": reg.get("status"),
            "record_count": len(records),
            "records": records,
            "by_type": {
                t: sum(1 for r in records if r["descriptor_type"] == t)
                for t in {r["descriptor_type"] for r in records}
            },
            "by_status": {
                s: sum(1 for r in records if r["status"] == s)
                for s in {r["status"] for r in records}
            },
        }
    except Exception as e:
        return {"error": str(e)[:300], "records": []}


class RegistryPublishRequest(BaseModel):
    name: str
    description: str
    descriptor_type: str = Field(description="MCP | A2A | CUSTOM | AGENT_SKILLS")
    descriptor_url: Optional[str] = None


@app.post("/registry/records")
def publish_registry_record(req: RegistryPublishRequest):
    """레지스트리에 새 레코드 생성 + 자동 제출."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        raise HTTPException(status_code=400, detail="REGISTRY_ID not configured")

    c = boto3.client("bedrock-agentcore-control", region_name=region)

    server_content = json.dumps({
        "name": f"agentops/{req.name}",
        "description": req.description,
        "version": "1.0.0",
    })

    actual_type = req.descriptor_type if req.descriptor_type == "MCP" else "CUSTOM"
    create_params: dict = {
        "registryId": registry_id,
        "name": req.name,
        "description": req.description,
        "descriptorType": actual_type,
        "recordVersion": "1.0",
    }
    if req.descriptor_type == "MCP":
        create_params["descriptors"] = {
            "mcp": {"server": {"inlineContent": server_content}}
        }
    else:
        create_params["descriptors"] = {
            "custom": {"inlineContent": server_content}
        }

    resp = c.create_registry_record(**create_params)
    record_id = resp.get("recordId") or resp.get("recordArn", "").split("/")[-1]

    # 레코드가 CREATING → DRAFT 전환 후 submit 가능. 최대 10초 대기.
    import time as _time
    for _ in range(5):
        _time.sleep(2)
        try:
            c.submit_registry_record_for_approval(registryId=registry_id, recordId=record_id)
            return {"record_id": record_id, "status": "SUBMITTED", "name": req.name}
        except c.exceptions.ConflictException:
            continue
        except Exception:
            break

    return {"record_id": record_id, "status": "DRAFT", "name": req.name}


@app.put("/registry/records/{record_id}/approve")
def approve_registry_record(record_id: str):
    """큐레이터가 레코드 승인."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        raise HTTPException(status_code=400, detail="REGISTRY_ID not configured")

    c = boto3.client("bedrock-agentcore-control", region_name=region)
    c.update_registry_record_status(registryId=registry_id, recordId=record_id, status="APPROVED", statusReason="Curator approved")
    return {"record_id": record_id, "status": "APPROVED"}


@app.put("/registry/records/{record_id}/reject")
def reject_registry_record(record_id: str):
    """큐레이터가 레코드 거부."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        raise HTTPException(status_code=400, detail="REGISTRY_ID not configured")

    c = boto3.client("bedrock-agentcore-control", region_name=region)
    c.update_registry_record_status(registryId=registry_id, recordId=record_id, status="REJECTED", statusReason="Curator rejected")
    return {"record_id": record_id, "status": "REJECTED"}


@app.put("/registry/records/{record_id}/deprecate")
def deprecate_registry_record(record_id: str):
    """레코드 폐기 — 더 이상 검색 불가."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        raise HTTPException(status_code=400, detail="REGISTRY_ID not configured")

    c = boto3.client("bedrock-agentcore-control", region_name=region)
    c.update_registry_record_status(registryId=registry_id, recordId=record_id, status="DEPRECATED", statusReason="Deprecated by curator")
    return {"record_id": record_id, "status": "DEPRECATED"}


class RegistrySearchRequest(BaseModel):
    query: str
    max_results: int = 10


@app.post("/registry/search")
def search_registry(req: RegistrySearchRequest):
    """시맨틱+키워드 하이브리드 검색."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        raise HTTPException(status_code=400, detail="REGISTRY_ID not configured")

    c = boto3.client("bedrock-agentcore", region_name=region)
    resp = c.search_registry_records(
        registryIds=[registry_id],
        searchQuery=req.query,
        maxResults=req.max_results,
    )
    records_raw = resp.get("registryRecords", resp.get("items", []))

    a2a_agents = _get_a2a_names()
    records = []
    for r in records_raw:
        name = r.get("name", "")
        dtype = r.get("descriptorType", "")
        if dtype == "CUSTOM" and name in a2a_agents:
            dtype = "A2A"
        records.append({
            "record_id": r.get("recordId"),
            "name": name,
            "description": r.get("description"),
            "descriptor_type": dtype,
            "status": r.get("status"),
            "descriptor_url": r.get("descriptorUrl"),
            "search_score": r.get("score"),
            "created_at": r.get("createdAt").isoformat() if r.get("createdAt") else None,
            "updated_at": r.get("updatedAt").isoformat() if r.get("updatedAt") else None,
        })

    return {"records": records, "query": req.query, "total": len(records)}


@app.get("/registry/mcp-endpoint")
def get_registry_mcp_endpoint():
    """Registry MCP 엔드포인트 연결 상태."""
    import urllib.request
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    registry_id = os.getenv("REGISTRY_ID")
    if not registry_id:
        return {"error": "REGISTRY_ID not configured"}

    c = boto3.client("bedrock-agentcore-control", region_name=region)
    try:
        reg = c.get_registry(registryId=registry_id)
    except Exception as e:
        return {"error": str(e)[:200]}

    mcp_url = reg.get("mcpEndpoint", reg.get("mcpEndpointUrl", ""))
    auth_type = reg.get("authorizerType", "IAM")

    status = "disconnected"
    if mcp_url:
        try:
            req = urllib.request.Request(mcp_url, method="HEAD")
            urllib.request.urlopen(req, timeout=5)
            status = "connected"
        except Exception:
            status = "disconnected"

    return {
        "url": mcp_url or "",
        "auth_type": auth_type,
        "status": status,
        "last_checked": datetime.utcnow().isoformat(),
    }


_publishable_cache: dict = {"resources": [], "a2a_names": set(), "ts": 0}


def _get_a2a_names() -> set[str]:
    """캐시된 A2A 리소스 이름 세트 반환 (60초 TTL)."""
    import time as _t
    if _t.time() - _publishable_cache["ts"] > 60:
        _, names = _discover_publishable_resources()
        _publishable_cache["a2a_names"] = names
        _publishable_cache["ts"] = _t.time()
    return _publishable_cache["a2a_names"]


def _discover_publishable_resources() -> tuple[list[dict], set[str]]:
    """배포된 Agent Runtime + Gateway Target에서 등록 가능한 리소스를 동적으로 조회."""
    region = os.getenv("REGISTRY_REGION", "us-east-1")
    gateway_id = os.getenv("AGENTCORE_GATEWAY_ID", os.getenv("GATEWAY_ID", ""))
    gateway_url = os.getenv("GATEWAY_URL", "")
    resources: list[dict] = []
    a2a_names: set[str] = set()

    try:
        c = boto3.client("bedrock-agentcore-control", region_name=region)

        # Agent Runtimes → A2A
        rt_resp = c.list_agent_runtimes(maxResults=20)
        runtimes = rt_resp.get("agentRuntimes", rt_resp.get("agentRuntimeSummaries", []))
        for r in runtimes:
            name = r.get("agentRuntimeName", "")
            if not name:
                continue
            resources.append({
                "name": name,
                "description": r.get("description") or f"AgentCore Runtime: {name}",
                "type": "A2A",
                "descriptor_url": None,
            })
            a2a_names.add(name)

        # Gateway Targets → MCP tools
        if gateway_id:
            targets = c.list_gateway_targets(gatewayIdentifier=gateway_id, maxResults=20)
            for t in targets.get("targets", targets.get("items", [])):
                tid = t.get("targetId", "")
                detail = c.get_gateway_target(gatewayIdentifier=gateway_id, targetId=tid)
                tc = detail.get("targetConfiguration", {})
                tools = tc.get("mcp", {}).get("lambda", {}).get("toolSchema", {}).get("inlinePayload", [])
                for tool in tools:
                    resources.append({
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "type": "MCP",
                        "descriptor_url": gateway_url,
                    })
    except Exception:
        pass

    return resources, a2a_names


@app.get("/registry/publishable")
def get_publishable_resources():
    """등록 가능한 기존 에이전트/MCP 도구 목록."""
    resources, _ = _discover_publishable_resources()
    return {"resources": resources}


@app.get("/gateways/agent")
def get_agent_gateway():
    """Agent Gateway 현황 — 등록된 에이전트 목록 + A2A 호출 이력."""
    try:
        import boto3
        client = boto3.client("bedrock-agentcore-control", region_name=os.getenv("AWS_REGION", "us-east-1"))
        runtimes = client.list_agent_runtimes().get("agentRuntimes", [])

        agents = []
        for rt in runtimes:
            name = rt.get("agentRuntimeName", "")
            if name in _AGENT_RUNTIME_NAMES:
                agents.append({
                    "name": name,
                    "arn": rt.get("agentRuntimeArn"),
                    "status": rt.get("status"),
                    "role": "main" if name == _MAIN_RUNTIME else name.replace("_specialist", ""),
                    "description": {
                        "main": "Orchestrator — routes complex queries to specialists",
                        "reviews": "Customer satisfaction / sentiment / review analysis",
                        "logistics": "Delivery performance / seller metrics / shipping analysis",
                    }.get(name.replace("_specialist", "") if name.endswith("_specialist") else "main"),
                })

        # A2A 호출 이력 — 로컬 히스토리에서 즉시, CloudWatch에서 과거 턴 병합
        handoffs: list[dict] = []
        seen_turn_ids: set[str] = set()

        # 1) 로컬 _chat_history (라이브 데모 즉시 반영)
        for h in reversed(_chat_history):
            tools = h.get("tools_used", []) or []
            if "delegate_to_specialist" not in tools:
                continue
            tid = h.get("turn_id", "")
            if tid in seen_turn_ids:
                continue
            seen_turn_ids.add(tid)
            handoffs.append({
                "turn_id": tid,
                "timestamp": h.get("timestamp", ""),
                "from": "main",
                "to": _infer_specialist(h.get("prompt", ""), tools),
                "prompt": redact_pii((h.get("prompt", "") or "")[:120]),
            })
            if len(handoffs) >= 20:
                break

        # 2) CloudWatch 트레이스에서 누락된 과거 이력 보강
        if len(handoffs) < 20:
            try:
                for t in cw_helper.get_recent_traces(50):
                    used = [name.split("___", 1)[-1] for name in t.get("tools_used", [])]
                    if "delegate_to_specialist" not in used:
                        continue
                    tid = t.get("turn_id", "")
                    if tid and tid in seen_turn_ids:
                        continue
                    seen_turn_ids.add(tid)
                    handoffs.append({
                        "turn_id": tid,
                        "timestamp": t.get("timestamp", ""),
                        "from": "main",
                        "to": _infer_specialist(t.get("prompt", ""), used),
                        "prompt": redact_pii((t.get("prompt", "") or "")[:120]),
                    })
                    if len(handoffs) >= 20:
                        break
            except Exception:
                pass

        last_handoff = None
        if _last_turn_summary and _last_turn_summary.get("has_handoff"):
            last_handoff = {
                "turn_id": _last_turn_summary.get("turn_id", ""),
                "from": "main",
                "to": _last_turn_summary.get("handoff_target") or "specialist",
                "timestamp": _last_turn_summary.get("timestamp", ""),
            }

        return {
            "protocol": "AgentCore Runtime invoke (A2A)",
            "agent_count": len(agents),
            "agents": agents,
            "handoffs": handoffs,
            "handoff_count": len(handoffs),
            "last_handoff": last_handoff,
        }
    except Exception as e:
        return {"error": str(e)[:200], "agents": [], "last_handoff": None}


@app.get("/gateways/journey")
def get_gateway_journey():
    """최근 1턴의 Gateway 통과 요약 — Chat 탭 상단 Journey Strip 전용."""
    if not _last_turn_summary:
        return {
            "active": False,
            "turn_id": "",
            "llm": {"model": "", "reason": ""},
            "tool": {"last": None, "used": []},
            "agent": {"handoff": False, "target": None},
            "summary": {"cost_usd": 0.0, "total_tokens": 0, "duration_ms": 0},
        }

    tools = _last_turn_summary.get("tools_used", []) or []
    mcp_tools = [t for t in tools if t != "delegate_to_specialist"]
    last_mcp_tool = mcp_tools[-1] if mcp_tools else (tools[-1] if tools else None)

    return {
        "active": True,
        "turn_id": _last_turn_summary.get("turn_id", ""),
        "trace_id": _last_turn_summary.get("trace_id", ""),
        "timestamp": _last_turn_summary.get("timestamp", ""),
        "prompt_snippet": _last_turn_summary.get("prompt_snippet", ""),
        "llm": {
            "model": _last_turn_summary.get("model", ""),
            "reason": "",  # LLM Gateway 엔드포인트의 last_routing_reason과 프런트에서 합성
        },
        "tool": {
            "last": last_mcp_tool,
            "used": mcp_tools,
        },
        "agent": {
            "handoff": bool(_last_turn_summary.get("has_handoff")),
            "target": _last_turn_summary.get("handoff_target"),
        },
        "summary": {
            "cost_usd": _last_turn_summary.get("cost_usd", 0.0),
            "total_tokens": _last_turn_summary.get("total_tokens", 0),
            "duration_ms": _last_turn_summary.get("duration_ms", 0),
        },
    }


@app.get("/chat/history")
def get_chat_history(
    session_id: Optional[str] = Query(None, pattern=_SESSION_ID_PATTERN),
    limit: int = Query(50, ge=1, le=500),
):
    history = _chat_history
    if session_id:
        history = [h for h in history if h["session_id"] == session_id]
    return {"history": history[-limit:], "count": len(history)}


@app.get("/sessions/{session_id}/turns")
def get_session_turns(session_id: str, limit: int = Query(50, ge=1, le=200)):
    """세션의 턴별 상세 — prompt/response + 인라인 메트릭 (Session Explorer용)."""
    traces = [t for t in _chat_history if t.get("session_id") == session_id]
    traces.sort(key=lambda t: t.get("timestamp", ""))
    traces = traces[-limit:]

    turns = []
    for t in traces:
        turn_id = t.get("turn_id", "")
        turns.append({
            "turn_id": turn_id,
            "trace_id": t.get("trace_id", ""),
            "timestamp": t.get("timestamp", ""),
            "prompt": t.get("prompt_full", t.get("prompt", "")),
            "response": t.get("response_full", t.get("response", "")),
            "latency_ms": t.get("duration_ms", 0),
            "tools_used": t.get("tools_used", []),
            "token_usage": t.get("token_usage"),
            "cost": t.get("cost"),
            "prompt_version": t.get("prompt_version", ""),
            "status": t.get("status", "ok"),
            "eval": None,
        })

    session = get_session_store().get(session_id)
    return {
        "session_id": session_id,
        "turn_count": len(turns),
        "turns": turns,
        "session_start": session.created_at if session else None,
        "total_duration_s": session.session_duration_seconds if session else 0,
    }


# --- Helper Functions ---




# --- Observability Endpoints ---


@app.get("/observability/agent-timeline")
def get_agent_timeline(limit: int = Query(20, ge=1, le=100)):
    """에이전트 턴별 타임라인 — LLM 호출 → 도구 선택 → 실행 → 응답 단계를 시각화."""
    recent_traces = cw_helper.get_recent_traces(limit)
    timelines = []

    # OTEL 스팬을 시간 범위로 일괄 조회 (캐시됨)
    otel_cache = {}
    try:
        if AGENT_ID:
            otel_cache = cw_helper.get_otel_spans_batch()
    except Exception:
        pass

    for t in recent_traces:
        trace_id = t.get("trace_id", "")
        turn_id = t.get("turn_id", "")
        total_ms = t.get("latency_ms", t.get("duration_ms", 0))
        tools = t.get("tools_used", [])

        spans = otel_cache.get(trace_id, [])

        steps = []
        if spans:
            for i, span in enumerate(spans):
                step_type = "llm_call"
                stype = span.get("type", "other")
                if stype == "llm":
                    step_type = "llm_call"
                elif stype == "tool":
                    step_type = "tool_execution"
                elif stype == "guardrail":
                    step_type = "guardrail"
                elif stype == "cost":
                    step_type = "response"
                else:
                    step_type = "llm_call" if i == 0 else "response"

                steps.append({
                    "step_index": i,
                    "type": step_type,
                    "name": span.get("name", "unknown"),
                    "duration_ms": round(span.get("duration_ms", 0), 1),
                    "start_ms": round(span.get("start_ms", 0), 1),
                    "details": span.get("attributes", {}),
                })
        else:
            # span 없으면 트레이스 메타에서 추론
            cursor_ms = 0.0
            # 1. LLM reasoning
            llm_ms = total_ms * 0.4 if tools else total_ms * 0.8
            steps.append({
                "step_index": 0, "type": "llm_call", "name": "LLM Reasoning",
                "duration_ms": round(llm_ms, 1), "start_ms": 0,
                "details": {"model": MODEL_ID},
            })
            cursor_ms += llm_ms

            # 2. Tool selection + execution
            if tools:
                sel_ms = total_ms * 0.05
                steps.append({
                    "step_index": 1, "type": "tool_selection", "name": "Tool Selection",
                    "duration_ms": round(sel_ms, 1), "start_ms": round(cursor_ms, 1),
                    "details": {"selected_tools": tools},
                })
                cursor_ms += sel_ms

                tool_ms_each = (total_ms * 0.35) / max(len(tools), 1)
                for i, tool_name in enumerate(tools):
                    is_handoff = tool_name == "delegate_to_specialist"
                    steps.append({
                        "step_index": 2 + i,
                        "type": "a2a_handoff" if is_handoff else "tool_execution",
                        "name": f"{'A2A → Specialist' if is_handoff else tool_name}",
                        "duration_ms": round(tool_ms_each, 1),
                        "start_ms": round(cursor_ms, 1),
                        "details": {"tool": tool_name},
                    })
                    cursor_ms += tool_ms_each

            # 3. Guardrail
            gr_ms = total_ms * 0.05
            steps.append({
                "step_index": len(steps), "type": "guardrail", "name": "Guardrail Check",
                "duration_ms": round(gr_ms, 1), "start_ms": round(cursor_ms, 1),
                "details": {},
            })
            cursor_ms += gr_ms

            # 4. Response generation
            resp_ms = total_ms - cursor_ms
            steps.append({
                "step_index": len(steps), "type": "response", "name": "Response Generation",
                "duration_ms": round(max(resp_ms, 0), 1), "start_ms": round(cursor_ms, 1),
                "details": {},
            })

        timelines.append({
            "turn_id": turn_id,
            "trace_id": trace_id,
            "timestamp": t.get("timestamp", ""),
            "total_duration_ms": round(total_ms, 1),
            "steps": steps,
            "tools_used": tools,
            "prompt_version": t.get("prompt_version", ""),
        })

    return {"timelines": timelines, "count": len(timelines)}


@app.get("/observability/tool-analytics")
def get_tool_analytics(hours: int = Query(24, ge=1, le=168)):
    """도구별 사용 패턴 분석 — 호출 빈도, 성공률, latency, 선택 패턴."""
    recent_traces = cw_helper.get_recent_traces(200)

    # OTEL 스팬 일괄 조회 — 실측 latency 사용
    otel_cache: dict[str, list[dict]] = {}
    try:
        if AGENT_ID:
            otel_cache = cw_helper.get_otel_spans_batch()
    except Exception:
        pass

    tool_data: dict[str, dict] = {}
    selection_pairs: dict[str, int] = {}

    for t in recent_traces:
        tools = t.get("tools_used", [])
        tc_list = t.get("tool_calls", [])
        total_ms = t.get("latency_ms", t.get("duration_ms", 0))
        is_error = t.get("status") == "error"
        timestamp = t.get("timestamp", "")
        turn_id = t.get("turn_id", "")
        trace_id = t.get("trace_id", "")

        # OTEL execute_tool 스팬에서 실측 duration 추출
        otel_tool_spans = []
        for s in otel_cache.get(trace_id, []):
            if s.get("type") == "tool":
                otel_tool_spans.append(s)

        # OTEL 스팬이 있으면 실측, 없으면 추정
        has_otel = bool(otel_tool_spans)
        tool_ms_each = (total_ms * 0.35) / max(len(tools), 1) if tools else 0

        # tool_calls가 있으면 개별 도구의 실제 status 사용
        tc_by_index = {i: tc for i, tc in enumerate(tc_list)} if tc_list else {}

        for i, tool_name in enumerate(tools):
            if tool_name not in tool_data:
                tool_data[tool_name] = {
                    "total_calls": 0, "success_count": 0, "error_count": 0,
                    "latencies": [], "last_called": "", "calls_by_turn": [],
                }
            td = tool_data[tool_name]
            td["total_calls"] += 1
            tc_info = tc_by_index.get(i, {})
            tool_error = tc_info.get("status") == "error" if tc_info else is_error

            # OTEL 스팬에서 해당 도구의 실측 latency 매칭
            otel_ms = None
            latency_estimated = True
            if has_otel:
                for os_span in otel_tool_spans:
                    otel_name = os_span.get("attributes", {}).get("gen_ai.tool.name", "")
                    short_name = otel_name.split("___", 1)[-1] if "___" in otel_name else otel_name
                    if short_name == tool_name:
                        otel_ms = os_span.get("duration_ms", 0)
                        otel_status = os_span.get("attributes", {}).get("gen_ai.tool.status", "")
                        if otel_status == "error":
                            tool_error = True
                        latency_estimated = False
                        otel_tool_spans.remove(os_span)
                        break

            actual_ms = otel_ms if otel_ms is not None else tool_ms_each

            if tool_error:
                td["error_count"] += 1
            else:
                td["success_count"] += 1
            td["latencies"].append(actual_ms)
            td["last_called"] = timestamp
            td["calls_by_turn"].append({
                "turn_id": turn_id, "timestamp": timestamp,
                "latency_ms": round(actual_ms, 1), "success": not tool_error,
                "latency_estimated": latency_estimated,
            })

            # 도구 선택 순서 패턴
            if i > 0:
                pair = f"{tools[i-1]}→{tool_name}"
                selection_pairs[pair] = selection_pairs.get(pair, 0) + 1

    tools_list = []
    for name, td in tool_data.items():
        lats = sorted(td["latencies"])
        total = td["total_calls"]
        tools_list.append({
            "tool_name": name,
            "total_calls": total,
            "success_count": td["success_count"],
            "error_count": td["error_count"],
            "success_rate": round(td["success_count"] / max(total, 1), 3),
            "avg_latency_ms": round(sum(lats) / max(len(lats), 1), 1),
            "p50_latency_ms": round(lats[len(lats) // 2], 1) if lats else 0,
            "p99_latency_ms": round(lats[int(len(lats) * 0.99)], 1) if lats else 0,
            "last_called": td["last_called"],
            "calls_by_turn": td["calls_by_turn"][-20:],
        })

    tools_list.sort(key=lambda x: x["total_calls"], reverse=True)

    patterns = [
        {"from_tool": pair.split("→")[0], "to_tool": pair.split("→")[1], "count": count}
        for pair, count in sorted(selection_pairs.items(), key=lambda x: -x[1])[:20]
    ]

    total_calls = sum(t["total_calls"] for t in tools_list)

    return {
        "tools": tools_list,
        "total_calls": total_calls,
        "most_used": tools_list[0]["tool_name"] if tools_list else "",
        "slowest": max(tools_list, key=lambda x: x["avg_latency_ms"])["tool_name"] if tools_list else "",
        "selection_patterns": patterns,
    }


@app.get("/observability/anomalies")
def get_anomalies():
    """CloudWatch Anomaly Detection 알람 상태 조회."""
    try:
        cw = boto3.client("cloudwatch", region_name=os.getenv("AWS_REGION", "us-east-1"))

        # 실제 알람 조회
        response = cw.describe_alarms(
            AlarmNamePrefix=_ALARM_PREFIX,
            AlarmTypes=["MetricAlarm"],
        )
        raw_alarms = response.get("MetricAlarms", [])

        if not raw_alarms:
            raise ValueError("no_alarms_configured")

        # Anomaly detector에서 expected band 조회
        detectors = {}
        try:
            det_resp = cw.describe_anomaly_detectors(Namespace="AgentCore/GenAI")
            for det in det_resp.get("AnomalyDetectors", []):
                mn = det.get("SingleMetricAnomalyDetector", {}).get("MetricName", "")
                if mn:
                    detectors[mn] = det
        except Exception:
            pass

        # 최근 datapoint 조회로 current_value 보강
        namespace = "AgentCore/GenAI"
        agent_id = os.getenv("AGENTCORE_AGENT_ID", "agentops-demo")
        end_time = datetime.utcnow()
        start_time = end_time - __import__("datetime").timedelta(minutes=10)

        alarms = []
        for alarm in raw_alarms:
            metric_name = alarm.get("MetricName", "")
            alarm_name = alarm.get("AlarmName", "")

            # 최근 값 가져오기
            current_value = 0
            try:
                data_resp = cw.get_metric_data(
                    MetricDataQueries=[{
                        "Id": "current",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": namespace,
                                "MetricName": metric_name,
                                "Dimensions": [{"Name": "AgentId", "Value": agent_id}],
                            },
                            "Period": 60,
                            "Stat": "Average",
                        },
                    }],
                    StartTime=start_time,
                    EndTime=end_time,
                )
                values = data_resp.get("MetricDataResults", [{}])[0].get("Values", [])
                if values:
                    current_value = values[0]
            except Exception:
                pass

            # Anomaly band 범위
            expected_low, expected_high = 0, 0
            det = detectors.get(metric_name)
            if det:
                config = det.get("Configuration", {})
                expected_low = config.get("MetricTimezone", 0)
                expected_high = config.get("ExcludedTimeRanges", 0)

            state_val = alarm.get("StateValue", "INSUFFICIENT_DATA")
            ts = alarm.get("StateUpdatedTimestamp")
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")

            alarms.append({
                "metric_name": metric_name,
                "display_name": alarm.get("AlarmDescription") or alarm_name,
                "state": state_val,
                "current_value": round(current_value, 1),
                "expected_low": round(expected_low, 1),
                "expected_high": round(expected_high, 1),
                "unit": alarm.get("Unit", ""),
                "timestamp": ts_str,
            })
        return {"alarms": alarms, "source": "cloudwatch"}

    except Exception:
        # Fallback: 최근 traces에서 시뮬레이션
        recent_traces = cw_helper.get_recent_traces(50)
        latencies = [t.get("latency_ms", t.get("duration_ms", 0)) for t in recent_traces]
        avg_lat = sum(latencies) / max(len(latencies), 1)
        std_lat = (sum((x - avg_lat) ** 2 for x in latencies) / max(len(latencies), 1)) ** 0.5 if latencies else 2000
        token_totals = [
            (t.get("token_usage") or {}).get("total_tokens", 0)
            for t in recent_traces if t.get("token_usage")
        ]
        avg_tokens = sum(token_totals) / max(len(token_totals), 1)
        std_tokens = (sum((x - avg_tokens) ** 2 for x in token_totals) / max(len(token_totals), 1)) ** 0.5 if token_totals else 1000

        error_traces = sum(1 for t in recent_traces if t.get("status") == "error")
        error_rate = round(error_traces / max(len(recent_traces), 1) * 60, 1)

        return {
            "alarms": [
                {
                    "metric_name": "genai.invocation.latency",
                    "display_name": "Invocation Latency",
                    "state": "ALARM" if avg_lat > avg_lat + 2 * std_lat and avg_lat > 0 else "OK",
                    "current_value": round(avg_lat, 1),
                    "expected_low": round(max(avg_lat - 2 * std_lat, 0), 1) if latencies else 500,
                    "expected_high": round(avg_lat + 2 * std_lat, 1) if latencies else 8000,
                    "unit": "ms",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                {
                    "metric_name": "genai.token.usage",
                    "display_name": "Token Usage per Call",
                    "state": "OK",
                    "current_value": round(avg_tokens, 0),
                    "expected_low": round(max(avg_tokens - 2 * std_tokens, 0), 0) if token_totals else 100,
                    "expected_high": round(avg_tokens + 2 * std_tokens, 0) if token_totals else 5000,
                    "unit": "tokens",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                {
                    "metric_name": "genai.error.count",
                    "display_name": "Error Rate",
                    "state": "ALARM" if error_rate > 5 else "OK",
                    "current_value": error_rate,
                    "expected_low": 0,
                    "expected_high": 3,
                    "unit": "errors/min",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            ],
            "source": "local",
        }
