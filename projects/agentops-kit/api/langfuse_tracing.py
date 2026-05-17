"""
Langfuse 연동 모듈.
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST 환경변수로 활성화.
설정이 없으면 no-op.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_langfuse = None
_enabled = False


def init_langfuse():
    global _langfuse, _enabled

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.info("Langfuse not configured — skipping")
        return

    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        _enabled = True
        logger.info("Langfuse initialized (host=%s)", host)
    except ImportError:
        logger.warning("langfuse package not installed")
    except Exception as e:
        logger.warning("Langfuse init failed: %s", e)


def is_enabled() -> bool:
    return _enabled


def trace_chat(
    *,
    trace_id: str,
    session_id: str,
    user_id: str,
    prompt: str,
    response: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: float,
    tools_used: list[str],
    cost_usd: float,
    prompt_version: str,
    metadata: Optional[dict] = None,
):
    """BFF /chat 턴 하나를 Langfuse trace로 기록."""
    if not _enabled or not _langfuse:
        return

    try:
        trace = _langfuse.trace(
            id=trace_id,
            session_id=session_id,
            user_id=user_id,
            input=prompt,
            output=response,
            metadata={
                "prompt_version": prompt_version,
                "tools_used": tools_used,
                **(metadata or {}),
            },
        )

        trace.generation(
            name="agent-invoke",
            model=model,
            input=prompt,
            output=response,
            usage={
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            metadata={
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
                "tools_used": tools_used,
            },
        )
    except Exception as e:
        logger.warning("Langfuse trace_chat failed: %s", e)


def flush():
    """Shutdown 시 버퍼 플러시."""
    if _langfuse:
        try:
            _langfuse.flush()
        except Exception:
            pass
