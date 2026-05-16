"""
GenAI 메트릭 수집.
ADOT 활성 시 OTEL Meter 기반 instrument 사용, 비활성 시 no-op.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_NAMESPACE = "bedrock-agentcore"

_latency_histogram = None
_token_input_counter = None
_token_output_counter = None
_invocation_counter = None
_cost_counter = None
_tool_call_counter = None
_error_counter = None
_guardrail_violation_counter = None

_initialized = False


def init_metrics():
    """OTEL meter에서 instrument 생성. ADOT 비활성 시 no-op."""
    global _latency_histogram, _token_input_counter, _token_output_counter
    global _invocation_counter, _cost_counter, _tool_call_counter
    global _error_counter, _guardrail_violation_counter, _initialized

    if _initialized:
        return

    from api.otel_setup import is_enabled, get_meter

    if is_enabled():
        meter = get_meter()
        if meter:
            _latency_histogram = meter.create_histogram(
                "genai.invocation.latency",
                unit="ms",
                description="Agent invocation latency",
            )
            _token_input_counter = meter.create_counter(
                "genai.token.input",
                unit="tokens",
                description="Input tokens consumed",
            )
            _token_output_counter = meter.create_counter(
                "genai.token.output",
                unit="tokens",
                description="Output tokens generated",
            )
            _invocation_counter = meter.create_counter(
                "genai.invocation.count",
                description="Total agent invocations",
            )
            _cost_counter = meter.create_counter(
                "genai.cost.usd",
                unit="USD",
                description="Estimated cost in USD",
            )
            _tool_call_counter = meter.create_counter(
                "genai.tool.calls",
                description="Tool invocations",
            )
            _error_counter = meter.create_counter(
                "genai.error.count",
                description="Agent invocation errors",
            )
            _guardrail_violation_counter = meter.create_counter(
                "genai.guardrail.violations",
                description="Guardrail violations detected",
            )
            logger.info("GenAI OTEL metrics instruments created")

    _initialized = True


def record_invocation(
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    model: str,
    tools_used: list[str],
    cost_usd: float,
    prompt_version: str,
    guardrail_violations: int = 0,
    error: bool = False,
):
    """메트릭 기록. ADOT 활성 시 OTEL instrument, 비활성 시 no-op."""
    if not _initialized:
        init_metrics()

    if not _latency_histogram:
        return

    attrs = {
        "gen_ai.system": "aws.bedrock",
        "gen_ai.request.model": model,
        "gen_ai.prompt_version": prompt_version,
    }

    _latency_histogram.record(latency_ms, attributes=attrs)
    _token_input_counter.add(input_tokens, attributes=attrs)
    _token_output_counter.add(output_tokens, attributes=attrs)
    _invocation_counter.add(1, attributes=attrs)
    _cost_counter.add(cost_usd, attributes=attrs)
    for tool in tools_used:
        _tool_call_counter.add(1, attributes={**attrs, "tool.name": tool})
    if guardrail_violations > 0:
        _guardrail_violation_counter.add(guardrail_violations, attributes=attrs)
    if error:
        _error_counter.add(1, attributes=attrs)


def record_error(model: str, prompt_version: str, error_code: Optional[str] = None):
    """에러 메트릭만 기록."""
    if not _initialized:
        init_metrics()

    if not _error_counter:
        return

    attrs = {
        "gen_ai.system": "aws.bedrock",
        "gen_ai.request.model": model,
        "gen_ai.prompt_version": prompt_version,
    }
    if error_code:
        attrs["error.code"] = error_code

    _error_counter.add(1, attributes=attrs)
