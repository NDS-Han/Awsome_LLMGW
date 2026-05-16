"""
토큰 및 비용 추적.

FinOps 관점의 에이전트 비용 가시성 확보 모듈. LLM 호출 단위로
실제 billable 토큰을 계산하고 세션/전역 누적값을 관리.

핵심:
- 모델별 가격표 (Bedrock on-demand pricing, 2026-04 기준)
- 입력/출력/캐시 토큰 분리 계산 (cache read는 할인율 적용)
- 자연어 예산 파싱 ("$5", "100k tokens", "1M")
- 세션별 누적 비용 + 임계치 알림 (80%, 95%, 100%)
"""

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Bedrock 가격표 (USD per 1M tokens, 2026-04)
# 참고: https://aws.amazon.com/bedrock/pricing/
# Claude 캐시: write = 1.25x input (5-min TTL), read = 0.1x input
# Nova 캐시:   write ≈ 1.25x input,             read ≈ 0.25x input
# gpt-oss:     프롬프트 캐싱 미지원 → cache_* 항목은 input과 동일하게 두어 혹시 캐시 토큰이 집계돼도 실가격과 일치
MODEL_PRICING = {
    # Claude models
    "claude-opus-4-7": {"input": 5.0, "output": 25.0, "cache_write": 6.25, "cache_read": 0.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.10},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
    "claude-3-haiku": {"input": 0.25, "output": 1.25, "cache_write": 0.30, "cache_read": 0.03},
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    # Amazon Nova
    "nova-pro": {"input": 0.80, "output": 3.20, "cache_write": 1.0, "cache_read": 0.20},
    "nova-2-lite": {"input": 0.30, "output": 2.50, "cache_write": 0.375, "cache_read": 0.075},
    "nova-lite": {"input": 0.06, "output": 0.24, "cache_write": 0.08, "cache_read": 0.015},
    "nova-micro": {"input": 0.035, "output": 0.14, "cache_write": 0.044, "cache_read": 0.009},
    # OpenAI open-weight (gpt-oss) — 프롬프트 캐싱 미지원
    "gpt-oss-120b": {"input": 0.15, "output": 0.60, "cache_write": 0.15, "cache_read": 0.15},
    "gpt-oss-20b": {"input": 0.07, "output": 0.30, "cache_write": 0.07, "cache_read": 0.07},
    # Default fallback
    "default": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens + self.cache_read_tokens

    @property
    def billable_tokens(self) -> int:
        """캐시 히트는 할인되므로 billable 기준 토큰."""
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens

    def add(self, other: "TokenUsage"):
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_tokens += other.cache_creation_tokens
        self.cache_read_tokens += other.cache_read_tokens

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "total_tokens": self.total_tokens,
            "billable_tokens": self.billable_tokens,
        }


@dataclass
class CostBreakdown:
    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_write_cost: float = 0.0
    cache_read_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost + self.cache_write_cost + self.cache_read_cost

    def to_dict(self) -> dict:
        return {
            "input_cost": round(self.input_cost, 6),
            "output_cost": round(self.output_cost, 6),
            "cache_write_cost": round(self.cache_write_cost, 6),
            "cache_read_cost": round(self.cache_read_cost, 6),
            "total_cost": round(self.total_cost, 6),
        }


def normalize_model_id(model_id: str) -> str:
    """Bedrock model ID에서 간략 이름 추출."""
    # global.anthropic.claude-sonnet-4-6 -> claude-sonnet-4-6
    model_id = model_id.lower()

    # 주의: 더 구체적인 패턴(claude-opus-4-7)이 일반 패턴(claude-opus-4)보다 먼저 와야 함
    patterns = [
        (r"claude-sonnet-4-6", "claude-sonnet-4-6"),
        (r"claude-sonnet-4-5", "claude-sonnet-4-5"),
        (r"claude-sonnet-4", "claude-sonnet-4"),
        (r"claude-3-7-sonnet", "claude-3-7-sonnet"),
        (r"claude-3-5-sonnet", "claude-3-5-sonnet"),
        (r"claude-haiku-4-5", "claude-haiku-4-5"),
        (r"claude-3-5-haiku", "claude-3-5-haiku"),
        (r"claude-3-haiku", "claude-3-haiku"),
        (r"claude-opus-4-7", "claude-opus-4-7"),
        (r"claude-opus-4", "claude-opus-4"),
        (r"nova-pro", "nova-pro"),
        (r"nova-2-lite", "nova-2-lite"),
        (r"nova-lite", "nova-lite"),
        (r"nova-micro", "nova-micro"),
        (r"gpt-oss-120b", "gpt-oss-120b"),
        (r"gpt-oss-20b", "gpt-oss-20b"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, model_id):
            return name
    return "default"


def calculate_cost(usage: TokenUsage, model_id: str) -> CostBreakdown:
    """토큰 사용량으로 비용 계산."""
    model = normalize_model_id(model_id)
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

    return CostBreakdown(
        input_cost=(usage.input_tokens / 1_000_000) * pricing["input"],
        output_cost=(usage.output_tokens / 1_000_000) * pricing["output"],
        cache_write_cost=(usage.cache_creation_tokens / 1_000_000) * pricing["cache_write"],
        cache_read_cost=(usage.cache_read_tokens / 1_000_000) * pricing["cache_read"],
    )


# --- Session Cost Tracking ---


@dataclass
class SessionCostState:
    session_id: str
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    total_cost: float = 0.0
    call_count: int = 0
    budget_usd: Optional[float] = None
    model_breakdown: dict[str, dict] = field(default_factory=dict)
    first_call_at: Optional[datetime] = None
    last_call_at: Optional[datetime] = None


class CostTracker:
    """세션별 비용 추적 + 예산 관리."""

    def __init__(self, default_budget_usd: float = 1.0):
        self._sessions: dict[str, SessionCostState] = {}
        self._global_usage = TokenUsage()
        self._global_cost = 0.0
        self._default_budget = default_budget_usd
        self._lock = threading.Lock()

    def record(
        self,
        session_id: str,
        model_id: str,
        usage: TokenUsage,
    ) -> dict:
        """LLM 호출 기록. 비용 계산 + 예산 확인."""
        with self._lock:
            cost = calculate_cost(usage, model_id)
            model = normalize_model_id(model_id)

            session = self._sessions.setdefault(
                session_id,
                SessionCostState(session_id=session_id, budget_usd=self._default_budget),
            )

            now = datetime.utcnow()
            if session.first_call_at is None:
                session.first_call_at = now
            session.last_call_at = now

            session.total_usage.add(usage)
            session.total_cost += cost.total_cost
            session.call_count += 1

            # 모델별 breakdown
            mb = session.model_breakdown.setdefault(model, {
                "calls": 0, "cost": 0.0, "tokens": 0,
            })
            mb["calls"] += 1
            mb["cost"] += cost.total_cost
            mb["tokens"] += usage.billable_tokens

            # 전역 누적
            self._global_usage.add(usage)
            self._global_cost += cost.total_cost

            # 예산 확인
            budget_warning = self._check_budget(session)

            return {
                "usage": usage.to_dict(),
                "cost": cost.to_dict(),
                "session_total_cost": round(session.total_cost, 6),
                "session_total_tokens": session.total_usage.billable_tokens,
                "budget": budget_warning,
                "model": model,
            }

    def _check_budget(self, session: SessionCostState) -> dict:
        """예산 사용률 체크."""
        if not session.budget_usd:
            return {"status": "unlimited"}

        ratio = session.total_cost / session.budget_usd
        status = "ok"
        if ratio >= 1.0:
            status = "exceeded"
        elif ratio >= 0.95:
            status = "critical"
        elif ratio >= 0.80:
            status = "warning"

        return {
            "status": status,
            "used_usd": round(session.total_cost, 6),
            "budget_usd": session.budget_usd,
            "used_ratio": round(ratio, 3),
            "remaining_usd": round(max(session.budget_usd - session.total_cost, 0), 6),
        }

    def get_session_state(self, session_id: str) -> Optional[dict]:
        with self._lock:
            s = self._sessions.get(session_id)
            if not s:
                return None
            return {
                "session_id": s.session_id,
                "total_usage": s.total_usage.to_dict(),
                "total_cost": round(s.total_cost, 6),
                "call_count": s.call_count,
                "budget": self._check_budget(s),
                "model_breakdown": s.model_breakdown,
                "duration_seconds": (
                    (s.last_call_at - s.first_call_at).total_seconds()
                    if s.first_call_at and s.last_call_at else 0
                ),
            }

    def get_global_state(self) -> dict:
        with self._lock:
            return {
                "total_usage": self._global_usage.to_dict(),
                "total_cost": round(self._global_cost, 6),
                "active_sessions": len(self._sessions),
                "top_sessions": sorted(
                    [
                        {"session_id": s.session_id, "cost": round(s.total_cost, 6), "calls": s.call_count}
                        for s in self._sessions.values()
                    ],
                    key=lambda x: x["cost"],
                    reverse=True,
                )[:5],
            }

    def set_budget(self, session_id: str, budget_usd: float):
        with self._lock:
            session = self._sessions.setdefault(
                session_id, SessionCostState(session_id=session_id),
            )
            session.budget_usd = budget_usd


# 싱글톤
_tracker = CostTracker(default_budget_usd=1.0)


def get_tracker() -> CostTracker:
    return _tracker


