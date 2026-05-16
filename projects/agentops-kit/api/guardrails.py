"""
출력 검증 가드레일.

LLM 응답을 프로덕션 공개 전 검증하는 규칙 기반 레이어. 모든 체크는
독립 실행되어 하나가 실패해도 다른 체크는 계속 수행됨 (fail-safe).

운영 단계 검증 체크:
1. PII 감지 (email, 전화번호, 주민번호 등)
2. 수치 근거 검증 (LLM 응답에 도구 출력에 없는 숫자가 있는지)
3. 카테고리 환각 감지 (존재하지 않는 상품 카테고리 언급)
4. 안전하지 않은 패턴 (SQL injection 시도, 내부 경로 노출)
5. 응답 길이/품질 체크
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class GuardrailViolation:
    rule_id: str
    severity: Severity
    message: str
    matched_text: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class GuardrailResult:
    passed: bool
    violations: list[GuardrailViolation] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.CRITICAL)

    @property
    def warn_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARN)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "critical_count": self.critical_count,
            "warn_count": self.warn_count,
            "info_count": sum(1 for v in self.violations if v.severity == Severity.INFO),
            "checks_run": self.checks_run,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "matched_text": v.matched_text[:80] if v.matched_text else None,
                    "suggestion": v.suggestion,
                }
                for v in self.violations
            ],
        }


# --- PII Patterns ---

PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "phone_kr": re.compile(r"\b01[016789][-. ]?\d{3,4}[-. ]?\d{4}\b"),
    "ssn_kr": re.compile(r"\b\d{6}[-]\d{7}\b"),
    "cpf_br": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # 브라질 주민번호
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}

# 내부 경로/secrets
UNSAFE_PATTERNS = {
    "filesystem_path": re.compile(r"/(?:Users|home|root|var|etc)/[^\s]+"),
    "stack_trace": re.compile(r'File "[^"]+", line \d+'),
    "api_error": re.compile(r"(?i)traceback|exception.*line \d+"),
    "sql_injection": re.compile(r"(?i)(drop\s+table|union\s+select|--\s*$|;\s*delete)"),
}


# --- 유효한 카테고리 목록 (Olist 데이터셋 기반) ---
VALID_CATEGORIES = {
    "health_beauty", "watches_gifts", "bed_bath_table", "sports_leisure",
    "computers_accessories", "furniture_decor", "housewares", "auto",
    "toys", "garden_tools", "cool_stuff", "perfumery", "baby", "electronics",
    "stationery", "telephony", "fashion_bags_accessories", "office_furniture",
    "pet_shop", "consoles_games", "luggage_accessories", "construction_tools_construction",
    "home_appliances", "books_general_interest", "musical_instruments", "industry_commerce_and_business",
    "fashion_shoes", "market_place", "food_drink", "drinks", "small_appliances",
    "air_conditioning", "kitchen_dining_laundry_garden_furniture", "fashion_male_clothing",
    "fashion_female_clothing", "construction_tools_lights", "fashion_underwear_beach",
    "audio", "books_imported", "food", "costruction_tools_garden",
    "tablets_printing_image", "cine_photo", "diapers_and_hygiene", "home_confort",
    "arts_and_craftmanship", "security_and_services",
}


# --- Brazilian state codes ---
VALID_BR_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


# --- Individual Check Functions ---


def check_pii(text: str) -> list[GuardrailViolation]:
    """PII 패턴 감지."""
    violations = []
    for name, pattern in PII_PATTERNS.items():
        for match in pattern.findall(text)[:3]:  # 최대 3개까지만
            matched = match if isinstance(match, str) else match[0]
            violations.append(GuardrailViolation(
                rule_id=f"pii.{name}",
                severity=Severity.CRITICAL if name in ("credit_card", "ssn_kr", "aws_key") else Severity.WARN,
                message=f"Possible {name} detected in response",
                matched_text=matched,
                suggestion=f"Mask or remove {name} before showing to user",
            ))
    return violations


def check_unsafe_patterns(text: str) -> list[GuardrailViolation]:
    """내부 시스템 정보 노출 감지."""
    violations = []
    for name, pattern in UNSAFE_PATTERNS.items():
        match = pattern.search(text)
        if match:
            violations.append(GuardrailViolation(
                rule_id=f"unsafe.{name}",
                severity=Severity.CRITICAL if name == "sql_injection" else Severity.WARN,
                message=f"Unsafe pattern detected: {name}",
                matched_text=match.group()[:80],
                suggestion="Review response for sensitive information leakage",
            ))
    return violations


def check_category_grounding(text: str) -> list[GuardrailViolation]:
    """응답에 존재하지 않는 카테고리가 언급되었는지 확인 (환각 감지)."""
    violations = []
    # 카테고리 패턴: 소문자+언더스코어
    candidates = re.findall(r"\b([a-z]+_[a-z_]+)\b", text.lower())
    # 알려진 false positive 제거
    filtered = [c for c in candidates if c not in {
        "order_id", "customer_id", "seller_id", "product_id",
        "on_time", "avg_delivery", "total_revenue", "review_score",
    } and "_" in c]

    seen = set()
    for cand in filtered[:10]:
        if cand in seen or len(cand) < 5:
            continue
        seen.add(cand)
        # 카테고리처럼 보이지만 유효하지 않은 경우
        if cand not in VALID_CATEGORIES and _looks_like_category(cand):
            violations.append(GuardrailViolation(
                rule_id="hallucination.category",
                severity=Severity.WARN,
                message=f"Category '{cand}' is not in the Olist dataset",
                matched_text=cand,
                suggestion=f"Verify category name against valid list",
            ))
    return violations


def _looks_like_category(text: str) -> bool:
    """카테고리 스타일인지 판단 (snake_case, 2-3단어)."""
    parts = text.split("_")
    return 2 <= len(parts) <= 4 and all(2 <= len(p) <= 20 for p in parts)


def check_numeric_grounding(response: str, tool_outputs: list[str]) -> list[GuardrailViolation]:
    """
    응답에 나온 숫자가 도구 출력에 근거가 있는지 확인.
    (환각 숫자 감지 - "2017년 매출 500억" 같은 근거 없는 수치)
    """
    violations = []

    # 응답에서 숫자 추출 (소수점/쉼표 포함)
    response_numbers = set(re.findall(r"\b\d[\d,.]*\b", response))

    # 도구 출력에서 숫자 추출
    tool_numbers = set()
    for output in tool_outputs:
        tool_numbers.update(re.findall(r"\b\d[\d,.]*\b", output))

    # 응답에만 있고 도구 출력에 없는 큰 숫자
    suspicious = []
    for num in response_numbers:
        # 단순 숫자(0-100)나 연도는 제외
        clean = num.replace(",", "").replace(".", "")
        if not clean.isdigit():
            continue
        val = int(clean)
        if val <= 100 or 1900 <= val <= 2100:  # 연도는 허용
            continue
        # 도구 출력에 없는 숫자
        if num not in tool_numbers and clean not in "".join(tool_numbers):
            suspicious.append(num)

    if len(suspicious) > 2:  # 2개 이상 의심스러운 숫자
        violations.append(GuardrailViolation(
            rule_id="hallucination.numeric",
            severity=Severity.WARN,
            message=f"Response contains {len(suspicious)} numbers not found in tool outputs",
            matched_text=", ".join(suspicious[:5]),
            suggestion="Verify numerical claims against actual data",
        ))

    return violations


def check_state_validity(text: str) -> list[GuardrailViolation]:
    """브라질 주 코드 유효성 검증."""
    violations = []
    # 2글자 대문자 패턴 (잠재적 주 코드)
    candidates = re.findall(r"\b([A-Z]{2})\b", text)
    seen = set()
    for state in candidates:
        if state in seen:
            continue
        seen.add(state)
        # 유효하지 않은 2글자 코드 (단, 일반 영어 약어 제외)
        if state not in VALID_BR_STATES and state not in {
            "AI", "ML", "AM", "PM", "US", "UK", "EU", "UN", "ID", "OK", "NO",
            "IT", "IS", "BE", "TO", "ON", "IN", "IF", "DO", "OR", "AS", "AT", "BY",
            "GO", "UP", "ME", "MY", "HE", "SO", "WE", "AN", "BR",
        }:
            violations.append(GuardrailViolation(
                rule_id="validation.br_state",
                severity=Severity.INFO,
                message=f"'{state}' looks like a state code but is not a valid Brazilian state",
                matched_text=state,
            ))
    return violations[:3]


def check_response_quality(text: str) -> list[GuardrailViolation]:
    """응답 품질 체크."""
    violations = []

    if len(text) < 20:
        violations.append(GuardrailViolation(
            rule_id="quality.too_short",
            severity=Severity.WARN,
            message=f"Response is very short ({len(text)} chars)",
        ))

    if len(text) > 5000:
        violations.append(GuardrailViolation(
            rule_id="quality.too_long",
            severity=Severity.INFO,
            message=f"Response is very long ({len(text)} chars), may exceed user attention span",
        ))

    # 숫자가 하나도 없으면 경고 (데이터 분석 응답이므로)
    if not re.search(r"\d", text) and len(text) > 100:
        violations.append(GuardrailViolation(
            rule_id="quality.no_numbers",
            severity=Severity.WARN,
            message="Analytics response contains no numerical data",
            suggestion="Data analysis responses should include specific numbers",
        ))

    # 불확실성 표현 과다 사용
    uncertain_phrases = [
        "i'm not sure", "i don't know", "i cannot", "unable to",
        "might be", "could be", "perhaps", "maybe",
    ]
    uncertain_count = sum(text.lower().count(p) for p in uncertain_phrases)
    if uncertain_count >= 3:
        violations.append(GuardrailViolation(
            rule_id="quality.uncertain",
            severity=Severity.INFO,
            message=f"Response has {uncertain_count} uncertainty markers",
            suggestion="High uncertainty may indicate incomplete analysis",
        ))

    return violations


# --- Main Orchestrator ---


def validate_response(
    response: str,
    tool_outputs: Optional[list[str]] = None,
    enable_checks: Optional[list[str]] = None,
) -> GuardrailResult:
    """
    응답에 모든 가드레일 체크 실행.

    Args:
        response: 에이전트 응답 텍스트
        tool_outputs: 도구 실행 결과 리스트 (수치 근거 검증용)
        enable_checks: 실행할 체크 목록. None이면 모두 실행.
    """
    import time
    start = time.time()

    all_checks = {
        "pii": check_pii,
        "unsafe": check_unsafe_patterns,
        "category_grounding": check_category_grounding,
        "state_validity": check_state_validity,
        "quality": check_response_quality,
    }

    checks_to_run = enable_checks or list(all_checks.keys())
    violations = []
    checks_run = []

    for check_name in checks_to_run:
        if check_name in all_checks:
            try:
                check_violations = all_checks[check_name](response)
                violations.extend(check_violations)
                checks_run.append(check_name)
            except Exception as e:
                violations.append(GuardrailViolation(
                    rule_id=f"check_error.{check_name}",
                    severity=Severity.INFO,
                    message=f"Check {check_name} failed: {e}",
                ))

    # 수치 근거 체크는 별도 (tool_outputs 필요)
    if tool_outputs and "numeric_grounding" not in checks_to_run or "numeric_grounding" in checks_to_run:
        if tool_outputs:
            num_violations = check_numeric_grounding(response, tool_outputs)
            violations.extend(num_violations)
            checks_run.append("numeric_grounding")

    duration_ms = round((time.time() - start) * 1000, 2)

    # CRITICAL 있으면 fail
    passed = not any(v.severity == Severity.CRITICAL for v in violations)

    return GuardrailResult(
        passed=passed,
        violations=violations,
        checks_run=checks_run,
        duration_ms=duration_ms,
    )


def redact_pii(text: str) -> str:
    """PII를 마스킹된 형태로 치환."""
    redacted = text
    redacted = PII_PATTERNS["email"].sub("[EMAIL_REDACTED]", redacted)
    redacted = PII_PATTERNS["credit_card"].sub("[CARD_REDACTED]", redacted)
    redacted = PII_PATTERNS["phone_kr"].sub("[PHONE_REDACTED]", redacted)
    redacted = PII_PATTERNS["ssn_kr"].sub("[SSN_REDACTED]", redacted)
    redacted = PII_PATTERNS["cpf_br"].sub("[CPF_REDACTED]", redacted)
    redacted = PII_PATTERNS["aws_key"].sub("[AWS_KEY_REDACTED]", redacted)
    return redacted
