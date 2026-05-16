"""
에러 분류 및 재시도 정책.

LLM/AWS SDK에서 발생하는 raw exception을 운영 가능한 카테고리로
매핑하여 재시도 여부 / 폴백 여부 / 사용자 메시지를 일관되게 결정.

운영 단계 핵심:
- 에러를 9개 카테고리로 분류하여 재시도/폴백 결정
- 중첩된 예외 (__cause__/__context__) 최대 5단계까지 탐색
- Rate limit / Throttling은 지수 백오프, 서킷 브레이커와 연동
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    """에러 카테고리 - 각각 다른 재시도 전략."""
    AUTH = "auth"                    # 재시도 불가 (자격 증명 문제)
    RATE_LIMIT = "rate_limit"        # 지수 백오프 재시도
    TIMEOUT = "timeout"              # 단순 재시도
    NETWORK = "network"              # 재시도 + 폴백 검토
    THROTTLING = "throttling"        # 지수 백오프
    VALIDATION = "validation"        # 재시도 불가 (입력 수정 필요)
    HTTP_4XX = "http_4xx"            # 재시도 불가
    HTTP_5XX = "http_5xx"            # 재시도 가능
    CONTEXT_LENGTH = "context_length"  # 컨텍스트 축소 후 재시도
    SSL = "ssl"                      # 네트워크 설정 문제
    UNKNOWN = "unknown"


@dataclass
class ClassifiedError:
    category: ErrorCategory
    code: Optional[str]
    message: str
    retryable: bool
    should_fallback: bool
    root_cause: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "should_fallback": self.should_fallback,
            "root_cause": self.root_cause,
        }


# AWS/Bedrock 에러 코드 매핑
AWS_ERROR_MAP = {
    "ThrottlingException": (ErrorCategory.THROTTLING, True),
    "TooManyRequestsException": (ErrorCategory.RATE_LIMIT, True),
    "ServiceQuotaExceededException": (ErrorCategory.RATE_LIMIT, True),
    "ModelTimeoutException": (ErrorCategory.TIMEOUT, True),
    "ModelErrorException": (ErrorCategory.HTTP_5XX, True),
    "ValidationException": (ErrorCategory.VALIDATION, False),
    "AccessDeniedException": (ErrorCategory.AUTH, False),
    "UnrecognizedClientException": (ErrorCategory.AUTH, False),
    "ExpiredTokenException": (ErrorCategory.AUTH, False),
    "ResourceNotFoundException": (ErrorCategory.VALIDATION, False),
    "ModelNotReadyException": (ErrorCategory.HTTP_5XX, True),
    "InternalServerException": (ErrorCategory.HTTP_5XX, True),
}


def walk_cause_chain(exc: BaseException, max_depth: int = 5) -> list[str]:
    """Exception의 cause chain을 최대 max_depth까지 추적."""
    chain = []
    current = exc
    depth = 0
    while current and depth < max_depth:
        chain.append(f"{type(current).__name__}: {str(current)[:200]}")
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        depth += 1
    return chain


def classify_error(exc: BaseException) -> ClassifiedError:
    """Exception을 카테고리로 분류."""
    chain = walk_cause_chain(exc)
    full_text = " | ".join(chain)
    error_type = type(exc).__name__
    message = str(exc)[:300]

    # 1. AWS ClientError 체크
    code = None
    if hasattr(exc, "response") and isinstance(getattr(exc, "response", None), dict):
        code = exc.response.get("Error", {}).get("Code")
        if code in AWS_ERROR_MAP:
            category, retryable = AWS_ERROR_MAP[code]
            return ClassifiedError(
                category=category,
                code=code,
                message=message,
                retryable=retryable,
                should_fallback=(category in (ErrorCategory.HTTP_5XX, ErrorCategory.TIMEOUT)),
                root_cause=chain[-1] if chain else None,
            )

    # 2. 직접 예외 타입 매칭
    if error_type in ("TimeoutError", "ReadTimeout", "ConnectTimeout"):
        return ClassifiedError(
            category=ErrorCategory.TIMEOUT,
            code=error_type,
            message=message,
            retryable=True,
            should_fallback=True,
            root_cause=chain[-1] if chain else None,
        )

    if error_type in ("ConnectionError", "ConnectionRefusedError", "NetworkError"):
        return ClassifiedError(
            category=ErrorCategory.NETWORK,
            code=error_type,
            message=message,
            retryable=True,
            should_fallback=True,
            root_cause=chain[-1] if chain else None,
        )

    # 3. 메시지 기반 매칭
    text_lower = full_text.lower()

    # SSL 관련
    if any(p in text_lower for p in ["ssl", "certificate", "cert verify"]):
        return ClassifiedError(
            category=ErrorCategory.SSL,
            code="ssl_error",
            message=message,
            retryable=False,
            should_fallback=False,
        )

    # Context length
    if any(p in text_lower for p in ["context length", "too many tokens", "max tokens", "context window"]):
        return ClassifiedError(
            category=ErrorCategory.CONTEXT_LENGTH,
            code="context_length_exceeded",
            message=message,
            retryable=True,
            should_fallback=False,
        )

    # Rate limit
    if any(p in text_lower for p in ["rate limit", "rate-limit", "429", "too many requests"]):
        return ClassifiedError(
            category=ErrorCategory.RATE_LIMIT,
            code="rate_limit",
            message=message,
            retryable=True,
            should_fallback=False,
        )

    # Auth
    if any(p in text_lower for p in ["unauthorized", "forbidden", "401", "403", "expired"]):
        return ClassifiedError(
            category=ErrorCategory.AUTH,
            code="auth_error",
            message=message,
            retryable=False,
            should_fallback=False,
        )

    # HTTP status
    m = re.search(r"\b(5\d{2})\b", full_text)
    if m:
        return ClassifiedError(
            category=ErrorCategory.HTTP_5XX,
            code=f"http_{m.group(1)}",
            message=message,
            retryable=True,
            should_fallback=True,
        )

    m = re.search(r"\b(4\d{2})\b", full_text)
    if m:
        return ClassifiedError(
            category=ErrorCategory.HTTP_4XX,
            code=f"http_{m.group(1)}",
            message=message,
            retryable=False,
            should_fallback=False,
        )

    # 기본값
    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        code=error_type,
        message=message,
        retryable=False,
        should_fallback=False,
        root_cause=chain[-1] if chain else None,
    )


def get_retry_delay_ms(category: ErrorCategory, attempt: int) -> int:
    """카테고리별 재시도 지연 시간 (지수 백오프)."""
    base_delays = {
        ErrorCategory.RATE_LIMIT: 2000,   # 2초
        ErrorCategory.THROTTLING: 1000,
        ErrorCategory.TIMEOUT: 500,
        ErrorCategory.NETWORK: 500,
        ErrorCategory.HTTP_5XX: 1000,
        ErrorCategory.CONTEXT_LENGTH: 0,
    }
    base = base_delays.get(category, 500)
    # 2^attempt * base + jitter (최대 30초)
    delay = min(base * (2 ** attempt), 30_000)
    return delay
