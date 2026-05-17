"""
분석 이벤트 큐.

AgentOps 메트릭 수집을 위한 비동기 이벤트 파이프라인. 애플리케이션
스레드를 블로킹하지 않고 이벤트를 여러 sink로 fan-out.

운영 단계 핵심:
- 이벤트를 큐에 넣고 백그라운드 워커가 배치로 flush (지연시간 최소화)
- Sink 추상화: CloudWatch/S3/로컬 등 다중 backend 지원
- 민감 필드 자동 스크러빙 (prefix로 마킹된 필드는 신뢰 sink에만 전달)
- 배치 업로드 (10 이벤트 또는 5초마다)
"""

import time
import threading
import queue
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


# 민감 필드 프리픽스 - 이 prefix가 붙은 필드는 accepts_pii=True sink에만 전달됨
SENSITIVE_PREFIX = "_SENSITIVE_"


@dataclass
class AnalyticsEvent:
    """분석 이벤트 스키마."""
    event_name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    session_id: str = ""
    turn_id: str = ""
    properties: dict = field(default_factory=dict)

    def to_dict(self, include_pii: bool = False) -> dict:
        """
        이벤트를 dict로 변환.
        include_pii=False인 경우 민감 필드(SENSITIVE_PREFIX) 제거.
        """
        props = {}
        for k, v in self.properties.items():
            if k.startswith(SENSITIVE_PREFIX) and not include_pii:
                continue
            clean_key = k[len(SENSITIVE_PREFIX):] if k.startswith(SENSITIVE_PREFIX) else k
            if include_pii:
                props[clean_key] = v
            elif not k.startswith(SENSITIVE_PREFIX):
                props[k] = v
        return {
            "event_name": self.event_name,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "properties": props,
        }


class AnalyticsSink(ABC):
    """이벤트 sink 추상 클래스."""

    # PII 수신 가능 여부
    accepts_pii: bool = False
    name: str = "base"

    @abstractmethod
    def write(self, events: list[AnalyticsEvent]):
        """이벤트 배치 기록."""
        ...

    def flush(self):
        """대기 중인 이벤트 강제 flush."""
        pass


class InMemorySink(AnalyticsSink):
    """인메모리 sink - 대시보드에서 조회용."""

    accepts_pii = True  # first-party, PII 보관 가능
    name = "in_memory"

    def __init__(self, max_events: int = 1000):
        self.events: list[dict] = []
        self.max_events = max_events
        self._lock = threading.Lock()

    def write(self, events: list[AnalyticsEvent]):
        with self._lock:
            for e in events:
                self.events.append(e.to_dict(include_pii=self.accepts_pii))
            if len(self.events) > self.max_events:
                self.events = self.events[-self.max_events:]

    def get_events(self, filter_name: str = None, limit: int = 100) -> list[dict]:
        with self._lock:
            events = self.events
            if filter_name:
                events = [e for e in events if e["event_name"] == filter_name]
            return events[-limit:]

    def get_event_counts(self) -> dict[str, int]:
        with self._lock:
            counts = {}
            for e in self.events:
                name = e["event_name"]
                counts[name] = counts.get(name, 0) + 1
            return counts


class AnalyticsQueue:
    """
    이벤트 큐 + 비동기 배치 flush.
    Producer는 enqueue만 호출하면 되고, 백그라운드 워커가 주기적으로 sink에 전달.
    """

    BATCH_SIZE = 10
    FLUSH_INTERVAL_SECONDS = 5

    def __init__(self):
        self._queue: queue.Queue[AnalyticsEvent] = queue.Queue(maxsize=10000)
        self._sinks: list[AnalyticsSink] = []
        self._worker: threading.Thread = None
        self._stop_event = threading.Event()
        self._stats = {"queued": 0, "flushed": 0, "dropped": 0}

    def add_sink(self, sink: AnalyticsSink):
        """Sink 등록 - 첫 번째 sink는 first-party (PII 수신)."""
        self._sinks.append(sink)
        if self._worker is None:
            self._start_worker()

    def enqueue(self, event: AnalyticsEvent):
        """이벤트를 큐에 추가. 큐 가득 차면 drop (silent)."""
        try:
            self._queue.put_nowait(event)
            self._stats["queued"] += 1
        except queue.Full:
            self._stats["dropped"] += 1

    def emit(self, event_name: str, session_id: str = "", turn_id: str = "", **properties):
        """편의 함수: 이벤트 생성 + 큐잉."""
        self.enqueue(AnalyticsEvent(
            event_name=event_name,
            session_id=session_id,
            turn_id=turn_id,
            properties=properties,
        ))

    def _start_worker(self):
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    def _worker_loop(self):
        """백그라운드 워커: 배치 모아서 flush."""
        batch: list[AnalyticsEvent] = []
        last_flush = time.time()

        while not self._stop_event.is_set():
            try:
                # 타임아웃 짧게 - FLUSH_INTERVAL 체크
                event = self._queue.get(timeout=1.0)
                batch.append(event)

                should_flush = (
                    len(batch) >= self.BATCH_SIZE
                    or time.time() - last_flush >= self.FLUSH_INTERVAL_SECONDS
                )
                if should_flush:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()

            except queue.Empty:
                # 타임아웃 - 부분 배치 flush
                if batch and time.time() - last_flush >= self.FLUSH_INTERVAL_SECONDS:
                    self._flush_batch(batch)
                    batch = []
                    last_flush = time.time()

        # 종료시 남은 이벤트 flush
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, events: list[AnalyticsEvent]):
        """모든 sink에 이벤트 배치 전송."""
        for sink in self._sinks:
            try:
                sink.write(events)
            except Exception:
                pass  # sink 실패는 다른 sink 영향 없음
        self._stats["flushed"] += len(events)

    def get_stats(self) -> dict:
        return dict(self._stats)

    def stop(self):
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2.0)


# --- 편의 이벤트 이름 상수 ---

class Events:
    # Chat / Agent
    CHAT_START = "chat.start"
    CHAT_COMPLETE = "chat.complete"
    CHAT_ERROR = "chat.error"
    # Tool
    TOOL_CALL_START = "tool.call.start"
    TOOL_CALL_COMPLETE = "tool.call.complete"
    TOOL_CALL_ERROR = "tool.call.error"
    # LLM
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"
    # Guardrail (event name strings, not credentials — Bandit B105 false positive)
    GUARDRAIL_PASS = "guardrail.pass"  # nosec B105
    GUARDRAIL_FAIL = "guardrail.fail"  # nosec B105
    GUARDRAIL_VIOLATION = "guardrail.violation"
    # Evaluation
    EVAL_RUN = "evaluation.run"
    # Cost
    BUDGET_WARNING = "cost.budget_warning"
    BUDGET_EXCEEDED = "cost.budget_exceeded"
    # Circuit breaker
    CIRCUIT_OPEN = "circuit.open"
    CIRCUIT_CLOSED = "circuit.closed"
    # Prompt
    PROMPT_VERSION_CHANGE = "prompt.version_change"


# 싱글톤
_queue = AnalyticsQueue()
_memory_sink = InMemorySink(max_events=1000)
_queue.add_sink(_memory_sink)
_cw_sink_registered = False


def _ensure_cw_sink():
    """Lazily register CloudWatch Logs sink (avoids circular import)."""
    global _cw_sink_registered
    if _cw_sink_registered:
        return
    _cw_sink_registered = True
    try:
        from api.cw_logs_sink import CloudWatchLogsSink
        _cw_sink = CloudWatchLogsSink()
        _queue.add_sink(_cw_sink)
    except Exception as e:
        print(f"[analytics] CloudWatch Logs sink init failed (non-critical): {e}")


def get_queue() -> AnalyticsQueue:
    return _queue


def get_memory_sink() -> InMemorySink:
    return _memory_sink


def emit(event_name: str, session_id: str = "", turn_id: str = "", **properties):
    """편의 함수 - 전역 큐에 이벤트 emit."""
    _queue.emit(event_name, session_id=session_id, turn_id=turn_id, **properties)
