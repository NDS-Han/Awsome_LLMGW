"""
세션 상태 관리 + 서킷 브레이커.

세션은 사용자 대화 단위 컨테이너. 턴 카운터, 컨텍스트 사용량,
실패 누적치를 추적하여 불안정한 세션을 자동으로 차단.

운영 단계 핵심:
- 세션당 turn_counter, consecutive_failures 추적
- 서킷 브레이커 3상태: CLOSED → OPEN (N회 실패) → HALF_OPEN (복구 시도) → CLOSED
- 최근 N개 메시지 유지 + 초과 시 자동 compaction
- 컨텍스트 윈도우 사용률 모니터링
"""

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"      # 정상 동작
    OPEN = "open"          # 차단됨 (모든 호출 거부)
    HALF_OPEN = "half_open"  # 복구 시도 (1회만 허용)


@dataclass
class CircuitBreaker:
    """
    클래식 서킷 브레이커 구현.
    N회 연속 실패 시 OPEN 상태로 전환하여 장애 확산 방지.
    recovery_timeout 경과 후 HALF_OPEN으로 자동 복구 시도.
    """
    failure_threshold: int = 3
    recovery_timeout_seconds: int = 30
    consecutive_failures: int = 0
    state: CircuitState = CircuitState.CLOSED
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    total_failures: int = 0
    total_successes: int = 0

    def record_success(self):
        self.consecutive_failures = 0
        self.total_successes += 1
        self.last_success_time = datetime.utcnow()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED

    def record_failure(self):
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_failure_time = datetime.utcnow()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def can_proceed(self) -> tuple[bool, str]:
        """호출 진행 가능 여부."""
        if self.state == CircuitState.CLOSED:
            return True, "circuit_closed"

        if self.state == CircuitState.OPEN:
            # recovery timeout 지났는지 확인
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True, "half_open_attempt"
            return False, f"circuit_open: {self.consecutive_failures} consecutive failures"

        # HALF_OPEN: 1회만 허용
        return True, "half_open_attempt"

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "failure_threshold": self.failure_threshold,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success": self.last_success_time.isoformat() if self.last_success_time else None,
            "success_rate": round(
                self.total_successes / max(self.total_failures + self.total_successes, 1), 3
            ),
        }


@dataclass
class SessionState:
    """세션 단위 상태. Turn 단위로 누적."""
    session_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    turn_counter: int = 0
    turn_id: Optional[str] = None  # 현재 진행중인 턴
    compacted: bool = False
    compaction_count: int = 0
    context_tokens_used: int = 0
    max_context_tokens: int = 200_000
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    # 최근 대화 (간단한 메모리)
    recent_messages: list[dict] = field(default_factory=list)
    max_recent_messages: int = 10

    def add_message(self, role: str, content: str, metadata: Optional[dict] = None):
        self.recent_messages.append({
            "role": role,
            "content": content[:2000],  # 컨텍스트 절약
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        })
        if len(self.recent_messages) > self.max_recent_messages:
            self.recent_messages = self.recent_messages[-self.max_recent_messages:]
            self.compacted = True
            self.compaction_count += 1
        self.last_activity = datetime.utcnow()

    def start_turn(self, turn_id: str):
        self.turn_counter += 1
        self.turn_id = turn_id
        self.last_activity = datetime.utcnow()

    def end_turn(self):
        self.turn_id = None

    def context_usage_ratio(self) -> float:
        return self.context_tokens_used / max(self.max_context_tokens, 1)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "turn_counter": self.turn_counter,
            "current_turn_id": self.turn_id,
            "compacted": self.compacted,
            "compaction_count": self.compaction_count,
            "context_tokens_used": self.context_tokens_used,
            "context_usage_ratio": round(self.context_usage_ratio(), 3),
            "max_context_tokens": self.max_context_tokens,
            "circuit_breaker": self.circuit_breaker.to_dict(),
            "recent_messages_count": len(self.recent_messages),
            "session_duration_seconds": (datetime.utcnow() - self.created_at).total_seconds(),
        }


class SessionStore:
    """세션 저장소. TTL 기반 정리."""

    DEFAULT_TTL_SECONDS = 60 * 60  # 1시간

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._sessions: dict[str, SessionState] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def get_or_create(self, session_id: str) -> SessionState:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                session = SessionState(session_id=session_id)
                self._sessions[session_id] = session
            self._maybe_cleanup()
            return session

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 20) -> list[SessionState]:
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.last_activity,
            reverse=True,
        )
        return sessions[:limit]

    def persist(self, session_id: str):
        """Persist a specific session's current state to DynamoDB."""
        session = self._sessions.get(session_id)
        if session:
            try:
                from api.persistence import get_persistence
                get_persistence().persist_session(session)
            except Exception:
                pass

    def delete(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)

    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now

        cutoff = datetime.utcnow() - timedelta(seconds=self._ttl)
        stale = [sid for sid, s in self._sessions.items() if s.last_activity < cutoff]
        for sid in stale:
            self._sessions.pop(sid, None)


# 싱글톤
_store = SessionStore()


def get_session_store() -> SessionStore:
    return _store
