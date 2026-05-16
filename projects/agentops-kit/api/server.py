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
        load_dotenv(_env)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import boto3
from api.agentcore_runtime import invoke_runtime
from api.cloudwatch import cw_helper, AGENT_ID
from api.cloudwatch import cw_helper as _cw_ref  # noqa: ensure module loads
from api.genai_metrics import record_invocation as record_genai_metrics, record_error as record_genai_error, init_metrics as init_genai_metrics


# 프롬프트 버전 상태는 이제 FastAPI 측에서만 관리 (Runtime 호출 시 payload로 전달)
_current_prompt_version = os.getenv("PROMPT_VERSION", "v1")


def get_current_prompt_version() -> str:
    return _current_prompt_version


def set_prompt_version(version: str) -> bool:
    global _current_prompt_version
    if version in ("v1", "v2", "v3"):
        _current_prompt_version = version
        return True
    return False
from api.guardrails import validate_response, redact_pii, GuardrailResult
from api.cost_tracker import get_tracker, TokenUsage
from api.errors import classify_error, get_retry_delay_ms
from api.session import get_session_store, CircuitState
from api.analytics import get_queue, get_memory_sink, Events, emit
from api.users import (
    UserCtx, UsageRecord, get_user_ctx, record_usage, enforce_budget,
    get_budget_state, set_budget, list_users, list_teams, get_directory_entry,
    get_user_usage, get_team_usage, top_users, top_teams,
)
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

# 전역 예외 핸들러 — 내부 스택 트레이스가 응답으로 새지 않도록
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "path": str(request.url.path)},
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
_eval_history: list[dict] = []
_turn_evals: dict[str, dict] = {}
_turn_eval_order: list[str] = []
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
_improvement_state: dict = {
    "status": "idle",
    "trigger_score": None,
    "suggestion": None,
    "before_score": None,
    "after_score": None,
}
_custom_evaluator_id: Optional[str] = None


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
        record_usage(UsageRecord(
            user_id=ctx.user_id,
            team_id=ctx.team_id,
            timestamp=datetime.utcnow().isoformat(),
            input_tokens=token_usage.input_tokens,
            output_tokens=token_usage.output_tokens,
            total_tokens=token_usage.total_tokens,
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

        # 비동기 자동 평가 트리거 (논블로킹)
        eval_session = runtime_session_id or session_id
        eval_trace = otel_trace_id or runtime_trace_id or trace_id
        asyncio.create_task(_auto_evaluate_turn(
            turn_id, eval_trace, req.prompt, response_text,
            tools_used=tools_used, session_id=eval_session,
        ))

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
        redacted = False
        if enable_guardrails and response_text:
            try:
                g = validate_response(response_text)
                guardrail_passed = g.passed
                guardrail_violations = [{"rule_id": v.rule_id, "severity": v.severity.value,
                                         "message": v.message} for v in g.violations]
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
        except Exception:
            pass

        session.circuit_breaker.record_success()
        session.end_turn()

        # Final enriched event
        complete = {
            "type": "complete",
            "session_id": session_id,
            "turn_id": turn_id,
            "trace_id": (final_event or {}).get("otel_trace_id") or turn_id,
            "latency_ms": latency_ms,
            "cost": cost_info.get("cost", {}) if cost_info else {},
            "guardrails": {"passed": guardrail_passed, "violations": guardrail_violations},
            "redacted": redacted,
            "circuit_state": session.circuit_breaker.state.value,
        }
        yield f"data: {json.dumps(complete)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if fronted
            "X-Session-Id": session_id,
            "X-Turn-Id": turn_id,
        },
    )


@app.get("/traces")
def list_traces(limit: int = Query(20, ge=1, le=200)):
    """최근 트레이스 (턴) 목록. OTEL + chat_history 병합."""
    traces = cw_helper.get_recent_traces(limit)
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


@app.get("/agents")
def list_agents():
    """사용 가능한 AgentCore Runtime 에이전트 목록."""
    agents = cw_helper.list_agents()
    return {"agents": agents, "count": len(agents)}


@app.get("/metrics")
def get_metrics(
    hours: int = Query(1, ge=1, le=168),
    agent_id: str = Query(None, description="Agent ID to filter metrics"),
):
    """집계 메트릭."""
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


@app.post("/evaluations")
def run_evaluation(req: EvalRequest):
    """평가 실행 (EvaluationClient — CloudWatch 스팬 기반)."""
    session_id = req.session_id
    trace_id = req.trace_id

    if not session_id and _chat_history:
        last = _chat_history[-1]
        session_id = last.get("session_id", "")
        if not trace_id:
            trace_id = last.get("otel_trace_id") or last.get("trace_id", "")

    if not session_id:
        raise HTTPException(status_code=400, detail="No session available for evaluation. Send a chat message first or provide session_id.")

    eval_results = _run_agentcore_evaluation(req.evaluators, session_id, trace_id)

    eval_entry = {
        "eval_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "prompt_version": get_current_prompt_version(),
        "evaluators": req.evaluators,
        "results": eval_results,
        "session_id": session_id,
        "trace_id": trace_id or "",
    }
    _eval_history.append(eval_entry)

    emit(Events.EVAL_RUN, evaluators=req.evaluators,
         prompt_version=get_current_prompt_version(),
         avg_score=round(sum(r["score"] for r in eval_results) / max(len(eval_results), 1), 3))

    return eval_entry


@app.get("/evaluations/history")
def get_eval_history():
    return {"history": _eval_history, "count": len(_eval_history)}


@app.get("/evaluations/turn/{turn_id}")
def get_turn_eval(turn_id: str):
    """특정 턴의 자동 평가 결과."""
    result = _turn_evals.get(turn_id)
    if not result:
        raise HTTPException(status_code=404, detail="No evaluation for this turn")
    return result


@app.get("/evaluations/turns")
def get_all_turn_evals():
    """전체 턴별 평가 결과 + 트렌드."""
    trend = []
    for tid in _turn_eval_order:
        ev = _turn_evals.get(tid)
        if ev:
            trend.append({
                "turn_id": tid,
                "avg_score": ev["avg_score"],
                "prompt_version": ev["prompt_version"],
                "timestamp": ev["timestamp"],
                "eval_source": ev.get("eval_source", "agentcore"),
            })
    return {"turn_evals": _turn_evals, "trend": trend, "count": len(trend)}


@app.get("/improvement")
def get_improvement_state():
    """개선 파이프라인 상태."""
    return _improvement_state


@app.post("/improvement/apply")
def apply_improvement():
    """제안된 개선 적용."""
    if _improvement_state["status"] != "ready":
        raise HTTPException(status_code=400, detail="No improvement suggestion ready")

    suggestion = _improvement_state["suggestion"]
    new_version = suggestion["suggested_version"]

    if not set_prompt_version(new_version):
        raise HTTPException(status_code=400, detail=f"Cannot switch to {new_version}")

    _improvement_state["status"] = "applied"
    _improvement_state["before_score"] = _improvement_state.get("trigger_score")

    emit(Events.PROMPT_VERSION_CHANGE, new_version=new_version)

    return {
        "status": "applied",
        "previous_version": suggestion["current_version"],
        "new_version": new_version,
        "before_score": _improvement_state["before_score"],
    }


@app.post("/improvement/reset")
def reset_improvement():
    """개선 파이프라인 초기화."""
    _improvement_state.update({
        "status": "idle",
        "trigger_score": None,
        "suggestion": None,
        "before_score": None,
        "after_score": None,
    })
    return {"status": "idle"}


# --- Evaluation Analysis Endpoints ---


@app.get("/evaluations/analysis")
def get_eval_analysis(threshold: float = Query(0.65, ge=0.0, le=1.0)):
    """통합 평가 분석 — 카테고리별, 평가자별, 시간 트렌드, 도구 상관관계, 저점수 분석."""
    by_category: dict[str, dict] = {}
    by_evaluator: dict[str, dict] = {}
    time_trend: list[dict] = []
    tool_scores: dict[str, list[float]] = {}
    tool_counts: dict[str, int] = {}
    low_score_turns: list[dict] = []

    for tid in _turn_eval_order:
        ev = _turn_evals.get(tid)
        if not ev:
            continue

        cat = ev.get("category", "general")
        if cat not in by_category:
            by_category[cat] = {"count": 0, "total_score": 0.0, "evaluator_totals": {}, "evaluator_counts": {}}
        bc = by_category[cat]
        bc["count"] += 1
        bc["total_score"] += ev["avg_score"]
        for s in ev["scores"]:
            name = s["evaluator"]
            bc["evaluator_totals"][name] = bc["evaluator_totals"].get(name, 0.0) + s["score"]
            bc["evaluator_counts"][name] = bc["evaluator_counts"].get(name, 0) + 1

        for s in ev["scores"]:
            name = s["evaluator"]
            if name not in by_evaluator:
                by_evaluator[name] = {"total": 0.0, "count": 0, "trend": [], "lowest_score": 1.0, "lowest_turn": None}
            be = by_evaluator[name]
            be["total"] += s["score"]
            be["count"] += 1
            be["trend"].append(round(s["score"], 3))
            if s["score"] < be["lowest_score"]:
                be["lowest_score"] = s["score"]
                be["lowest_turn"] = {
                    "turn_id": tid,
                    "score": s["score"],
                    "prompt": ev.get("prompt", "")[:200],
                    "response": ev.get("response", "")[:300],
                }

        time_trend.append({
            "turn_id": tid,
            "timestamp": ev["timestamp"],
            "avg_score": ev["avg_score"],
            "prompt_version": ev["prompt_version"],
            "category": cat,
        })

        for tool in ev.get("tools_used", []):
            tool_scores.setdefault(tool, []).append(ev["avg_score"])
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

        if ev["avg_score"] < threshold:
            weakest = min(ev["scores"], key=lambda s: s["score"]) if ev["scores"] else None
            low_score_turns.append({
                "turn_id": tid,
                "avg_score": ev["avg_score"],
                "prompt": ev.get("prompt", "")[:200],
                "response": ev.get("response", "")[:500],
                "category": cat,
                "tools_used": ev.get("tools_used", []),
                "scores": ev["scores"],
                "weakest_evaluator": weakest["evaluator"] if weakest else None,
                "prompt_version": ev["prompt_version"],
                "timestamp": ev["timestamp"],
            })

    categories_out = {}
    for cat, data in by_category.items():
        evaluator_scores = {}
        for name, total in data["evaluator_totals"].items():
            evaluator_scores[name] = round(total / max(data["evaluator_counts"][name], 1), 3)
        categories_out[cat] = {
            "count": data["count"],
            "avg_score": round(data["total_score"] / max(data["count"], 1), 3),
            "evaluator_scores": evaluator_scores,
        }

    evaluators_out = {}
    for name, data in by_evaluator.items():
        evaluators_out[name] = {
            "avg_score": round(data["total"] / max(data["count"], 1), 3),
            "count": data["count"],
            "trend": data["trend"][-20:],
            "lowest": data["lowest_turn"],
        }

    tool_correlation = {}
    for tool, scores_list in tool_scores.items():
        tool_correlation[tool] = {
            "avg_score_when_used": round(sum(scores_list) / max(len(scores_list), 1), 3),
            "call_count": tool_counts[tool],
        }

    trend_scores = [t["avg_score"] for t in time_trend]
    improving = False
    delta = 0.0
    if len(trend_scores) >= 3:
        first_half = sum(trend_scores[:len(trend_scores)//2]) / max(len(trend_scores)//2, 1)
        second_half = sum(trend_scores[len(trend_scores)//2:]) / max(len(trend_scores) - len(trend_scores)//2, 1)
        delta = round(second_half - first_half, 3)
        improving = delta > 0.02

    # Why-low heuristic analysis for each low-score turn
    for lt in low_score_turns:
        lt["analysis"] = _analyze_low_scores(lt["scores"])

    return {
        "by_category": categories_out,
        "by_evaluator": evaluators_out,
        "time_trend": time_trend,
        "tool_correlation": tool_correlation,
        "low_score_turns": sorted(low_score_turns, key=lambda x: x["avg_score"])[:10],
        "summary": {"improving": improving, "delta": delta, "total_turns": len(time_trend)},
        "custom_evaluator": {
            "registered": _custom_evaluator_id is not None,
            "evaluator_id": _custom_evaluator_id,
        },
    }


_WHY_LOW_RULES: dict[str, dict[str, str]] = {
    "Builtin.Correctness": {
        "analysis": "Response may lack specific numerical data or contain inaccurate figures.",
        "recommendation": "Add structured guidelines for numerical data format (BRL values, percentages, counts).",
    },
    "Builtin.Faithfulness": {
        "analysis": "Response may not be grounded in tool results or includes fabricated data.",
        "recommendation": "Ensure the prompt instructs the agent to only cite data returned by tools.",
    },
    "Builtin.ToolSelectionAccuracy": {
        "analysis": "Wrong tools may have been selected for this query type.",
        "recommendation": "Add explicit tool-selection guidance in the system prompt for each query category.",
    },
    "Builtin.Helpfulness": {
        "analysis": "Response may be too generic or miss the user's specific question.",
        "recommendation": "Add few-shot examples showing ideal responses for each question category.",
    },
    "Builtin.Conciseness": {
        "analysis": "Response is overly verbose or includes unnecessary preamble.",
        "recommendation": "Add output format constraints: lead with the answer, then provide supporting data.",
    },
    "Builtin.GoalSuccessRate": {
        "analysis": "The agent may not have fully addressed the user's intent.",
        "recommendation": "Add explicit goal-checking step: verify the response answers the original question.",
    },
}


def _analyze_low_scores(scores: list[dict]) -> dict:
    """낮은 점수에 대한 휴리스틱 분석."""
    if not scores:
        return {"summary": "No scores available.", "details": [], "recommendations": []}

    low_scores = sorted(scores, key=lambda s: s["score"])
    details = []
    recommendations = []
    for s in low_scores:
        if s["score"] < 0.65:
            rule = _WHY_LOW_RULES.get(s["evaluator"], {})
            details.append({
                "evaluator": s["evaluator"],
                "score": s["score"],
                "analysis": rule.get("analysis", "Score below threshold."),
            })
            rec = rule.get("recommendation")
            if rec and rec not in recommendations:
                recommendations.append(rec)

    weakest = low_scores[0]
    summary = f"Weakest: {weakest['evaluator'].replace('Builtin.', '')} ({weakest['score']:.0%}). "
    if len(details) > 1:
        summary += f"{len(details)} evaluators below threshold."
    return {"summary": summary, "details": details, "recommendations": recommendations}


# --- Custom Evaluator Registration ---


def _register_custom_evaluator() -> Optional[str]:
    """custom_evaluator.json을 AgentCore에 등록."""
    global _custom_evaluator_id
    config_path = Path(__file__).resolve().parent.parent / "evaluation" / "custom_evaluator.json"
    if not config_path.exists():
        print("[custom-eval] custom_evaluator.json not found, skipping registration")
        return None

    try:
        config = json.loads(config_path.read_text())
        client = boto3.client("bedrock-agentcore", region_name=os.getenv("AGENTCORE_REGION", "us-east-1"))
        resp = client.create_evaluator(
            evaluatorName="ecommerce-analytics-quality",
            description="E-commerce analytics response quality evaluator (LLM-as-a-Judge)",
            evaluatorConfig=config,
        )
        _custom_evaluator_id = resp.get("evaluatorId")
        print(f"[custom-eval] registered: {_custom_evaluator_id}")
        return _custom_evaluator_id
    except client.exceptions.ConflictException:
        print("[custom-eval] already registered, fetching existing")
        try:
            resp = client.get_evaluator(evaluatorName="ecommerce-analytics-quality")
            _custom_evaluator_id = resp.get("evaluatorId")
            return _custom_evaluator_id
        except Exception as e:
            print(f"[custom-eval] fetch failed: {e}")
            return None
    except Exception as e:
        print(f"[custom-eval] registration failed (non-critical): {e}")
        return None


@app.post("/evaluations/custom/register")
def register_custom_evaluator():
    """커스텀 평가자 수동 등록."""
    eid = _register_custom_evaluator()
    config_path = Path(__file__).resolve().parent.parent / "evaluation" / "custom_evaluator.json"
    config_summary = {}
    if config_path.exists():
        config = json.loads(config_path.read_text())
        scale = config.get("llmAsAJudge", {}).get("ratingScale", {}).get("numerical", [])
        config_summary = {
            "model": config.get("llmAsAJudge", {}).get("modelConfig", {}).get("bedrockEvaluatorModelConfig", {}).get("modelId"),
            "scale_points": len(scale),
        }
    return {"registered": eid is not None, "evaluator_id": eid, "config": config_summary}


@app.get("/evaluations/custom/status")
def get_custom_evaluator_status():
    """커스텀 평가자 등록 상태."""
    return {"registered": _custom_evaluator_id is not None, "evaluator_id": _custom_evaluator_id}


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
        gw = next((g for g in gateways if g["name"] == "agentops-ecommerce-gateway"), None)
        if not gw:
            return {
                "error": "gateway_not_found",
                "tools": [],
                "call_counts": local_counts,
                "last_tool_used": last_tool_used,
            }
        gid = gw["gatewayId"]
        targets = cp.list_gateway_targets(gatewayIdentifier=gid).get("items", [])
        target = next((t for t in targets if t["name"] == "EcommerceAnalyticsTools"), None)

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
        region = os.getenv("AWS_REGION", "us-east-1")
        registry_id = os.getenv("REGISTRY_ID")
        if not registry_id:
            return {"error": "registry_not_configured", "records": []}

        c = boto3.client("bedrock-agentcore-control", region_name=region)
        resp = c.list_registry_records(registryId=registry_id, maxResults=50)
        records_raw = resp.get("registryRecords", resp.get("items", []))

        records = []
        for r in records_raw:
            records.append({
                "record_id": r.get("recordId"),
                "name": r.get("name"),
                "description": r.get("description"),
                "descriptor_type": r.get("descriptorType"),
                "status": r.get("status"),
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
            if name in ("ecommerce_analytics", "reviews_specialist", "logistics_specialist"):
                agents.append({
                    "name": name,
                    "arn": rt.get("agentRuntimeArn"),
                    "status": rt.get("status"),
                    "role": "main" if name == "ecommerce_analytics" else name.replace("_specialist", ""),
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
        eval_data = _turn_evals.get(turn_id)
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
            "eval": {
                "avg_score": eval_data["avg_score"],
                "scores": eval_data.get("scores", []),
            } if eval_data else None,
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


def _run_agentcore_evaluation(evaluators: list[str], session_id: str, trace_id: str = "") -> list[dict]:
    """AgentCore Evaluation API 호출 (EvaluationClient — CloudWatch 스팬 기반)."""
    from datetime import timedelta
    from bedrock_agentcore.evaluation.client import EvaluationClient

    region = os.getenv("AGENTCORE_REGION", "us-east-1")
    agent_id = os.getenv("AGENTCORE_AGENT_ID", "")

    eval_client = EvaluationClient(region_name=region)
    raw_results = eval_client.run(
        evaluator_ids=evaluators,
        session_id=session_id,
        agent_id=agent_id if agent_id else None,
        trace_id=trace_id.replace("-", "") if trace_id else None,
        look_back_time=timedelta(minutes=15),
    )

    results = []
    for r in raw_results:
        score_val = r.get("value", 0.0)
        if score_val is None:
            continue
        results.append({
            "evaluator": r.get("evaluatorId", ""),
            "score": score_val,
            "label": _score_label(score_val),
            "explanation": r.get("explanation", ""),
            "eval_source": "agentcore",
        })
    return results


def _score_label(score: float) -> str:
    if score >= 0.85:
        return "Excellent"
    if score >= 0.7:
        return "Very Good"
    if score >= 0.5:
        return "Good"
    if score >= 0.3:
        return "Fair"
    return "Poor"


# --- Auto-Evaluation (Online) ---

_DEFAULT_EVALUATORS = [
    "Builtin.Helpfulness",
    "Builtin.Correctness",
    "Builtin.GoalSuccessRate",
    "Builtin.Faithfulness",
    "Builtin.ToolSelectionAccuracy",
    "Builtin.Conciseness",
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "sales": ["revenue", "sales", "order", "purchase", "transaction", "category", "product", "aov", "average order"],
    "reviews": ["review", "rating", "satisfaction", "complaint", "star", "feedback", "score"],
    "delivery": ["delivery", "shipping", "late", "on-time", "logistics", "carrier", "freight"],
    "sellers": ["seller", "vendor", "merchant", "supplier", "ranking"],
}


def _infer_category(prompt: str) -> str:
    lower = prompt.lower()
    scores = {cat: sum(1 for kw in kws if kw in lower) for cat, kws in _CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"

_IMPROVEMENT_SUGGESTIONS = {
    "v1": {
        "current_version": "v1",
        "suggested_version": "v2",
        "changes": [
            {"aspect": "Numerical Specificity", "before": "No guidance on data format", "after": "Always include BRL values, percentages, counts"},
            {"aspect": "Data Breakdown", "before": "Generic responses", "after": "State-level, time-based breakdown required"},
            {"aspect": "Business Insights", "before": "Not required", "after": "End with 1-2 actionable insights"},
        ],
        "expected_delta": "+27%",
        "reason": "Low Correctness — agent responses lack grounded numerical data and structured breakdowns",
    },
    "v2": {
        "current_version": "v2",
        "suggested_version": "v3",
        "changes": [
            {"aspect": "Response Format", "before": "Free-form text", "after": "Markdown tables for rankings, bullets for breakdowns"},
            {"aspect": "Few-Shot Guidance", "before": "No examples", "after": "One ideal Q&A pair as reference"},
            {"aspect": "Edge Case Handling", "before": "No guidance", "after": "Explicit instructions for missing data periods"},
        ],
        "expected_delta": "+6%",
        "reason": "Good but inconsistent formatting — structured output template and examples will improve consistency",
    },
}


async def _auto_evaluate_turn(
    turn_id: str, trace_id: str, prompt: str, response: str,
    tools_used: Optional[list[str]] = None, session_id: str = "",
):
    """채팅 턴 후 비동기 자동 평가 (EvaluationClient — CloudWatch 스팬 기반)."""
    await asyncio.sleep(30)

    prompt_version = get_current_prompt_version()
    category = _infer_category(prompt)

    evaluator_ids = list(_DEFAULT_EVALUATORS)
    if _custom_evaluator_id:
        evaluator_ids.append(_custom_evaluator_id)

    agent_id = os.getenv("AGENTCORE_AGENT_ID", "")
    region = os.getenv("AGENTCORE_REGION", "us-east-1")

    scores = []
    from datetime import timedelta
    from bedrock_agentcore.evaluation.client import EvaluationClient

    max_attempts = 3
    retry_delays = [0, 30, 60]
    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"[eval] retry {attempt}/{max_attempts-1} for {turn_id} after {retry_delays[attempt]}s")
            await asyncio.sleep(retry_delays[attempt])
        try:
            eval_client = EvaluationClient(region_name=region)
            print(f"[eval] attempt {attempt+1}/{max_attempts} for turn={turn_id}, session={session_id}, trace={trace_id}")
            results = eval_client.run(
                evaluator_ids=evaluator_ids,
                session_id=session_id,
                agent_id=agent_id if agent_id else None,
                trace_id=trace_id.replace("-", "") if trace_id else None,
                look_back_time=timedelta(minutes=15),
            )
            print(f"[eval] got {len(results)} results for {turn_id}")
            for r in results:
                is_custom = r.get("evaluatorId", "") not in _DEFAULT_EVALUATORS
                score_val = r.get("value", 0.0)
                if score_val is None:
                    continue
                scores.append({
                    "evaluator": r.get("evaluatorId", ""),
                    "score": score_val,
                    "label": _score_label(score_val),
                    "eval_source": "custom" if is_custom else "agentcore",
                    "explanation": r.get("explanation", ""),
                })
            if scores:
                break
        except Exception as e:
            err_msg = str(e)
            print(f"[eval] attempt {attempt+1} failed for {turn_id}: {err_msg}")
            if "no spans with supported scope" in err_msg and attempt < max_attempts - 1:
                continue
            break

    if not scores:
        print(f"[eval] no scores for {turn_id}")
        return

    builtin_scores = [s for s in scores if s.get("eval_source") != "custom"]
    avg_score = round(sum(s["score"] for s in builtin_scores) / max(len(builtin_scores), 1), 3)

    turn_eval = {
        "turn_id": turn_id,
        "trace_id": trace_id,
        "scores": scores,
        "avg_score": avg_score,
        "prompt_version": prompt_version,
        "timestamp": datetime.utcnow().isoformat(),
        "eval_source": "agentcore",
        "prompt": prompt,
        "response": response[:1000],
        "tools_used": tools_used or [],
        "category": category,
    }
    _turn_evals[turn_id] = turn_eval
    _turn_eval_order.append(turn_id)

    # 개선 후 첫 평가면 after_score 기록
    if _improvement_state["status"] == "applied" and _improvement_state["after_score"] is None:
        _improvement_state["after_score"] = avg_score

    emit(Events.EVAL_RUN, evaluators=_DEFAULT_EVALUATORS,
         prompt_version=prompt_version, avg_score=avg_score)

    # 점수 낮으면 개선 파이프라인 트리거
    if avg_score < 0.65 and _improvement_state["status"] == "idle":
        await _trigger_improvement(avg_score, prompt_version)


async def _trigger_improvement(trigger_score: float, current_version: str):
    """낮은 평가 점수에 대한 개선 제안 생성."""
    suggestion = _IMPROVEMENT_SUGGESTIONS.get(current_version)
    if not suggestion:
        return

    _improvement_state["status"] = "analyzing"
    _improvement_state["trigger_score"] = trigger_score

    await asyncio.sleep(2.0)

    _improvement_state["status"] = "ready"
    _improvement_state["suggestion"] = suggestion
    _improvement_state["before_score"] = trigger_score
    _improvement_state["after_score"] = None


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
            AlarmNamePrefix="agentops-anomaly",
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
