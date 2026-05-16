"""
OpenTelemetry 초기화 — ADOT(aws-opentelemetry-distro) 자동 계측 감지.

`opentelemetry-instrument`로 실행하면 ADOT가 TracerProvider, MeterProvider,
FastAPI 계측, propagator를 모두 설정한다. 이 모듈은 ADOT가 활성인지
감지하고, 활성이면 참조만 가져온다. 비활성(로컬 개발)이면 no-op으로
LocalSpan 폴백이 동작하도록 한다.
"""

import logging

logger = logging.getLogger(__name__)

_ENABLED: bool = False
_tracer = None
_meter = None


def is_enabled() -> bool:
    return _ENABLED


def get_tracer():
    return _tracer


def get_meter():
    return _meter


def _is_sdk_configured() -> bool:
    """ADOT(또는 수동 SDK)가 TracerProvider를 설정했는지 확인."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
        provider = trace.get_tracer_provider()
        # ProxyTracerProvider는 SDK 미설정 상태, SdkTracerProvider가 있으면 ADOT 활성
        return isinstance(provider, SdkTracerProvider)
    except ImportError:
        return False


def init_otel():
    """ADOT 자동 계측 감지 후 tracer/meter 참조 획득."""
    global _ENABLED, _tracer, _meter

    try:
        from opentelemetry import trace, metrics

        if not _is_sdk_configured():
            logger.info("ADOT not active — local fallback mode")
            return

        _tracer = trace.get_tracer("agentops-api", "2.0.0")
        _meter = metrics.get_meter("agentops-api", "2.0.0")
        _ENABLED = True

        provider_type = type(trace.get_tracer_provider()).__name__
        logger.info("ADOT detected (%s) — OTEL enabled", provider_type)

    except ImportError:
        logger.info("OpenTelemetry SDK not installed — local fallback mode")
    except Exception as e:
        logger.warning("OTEL init failed: %s", e)
