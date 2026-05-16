import { HeartPulse, CircuitBoard, RefreshCw } from "lucide-react";
import { api } from "../api";
import { SessionState } from "../types";

interface Props {
  session: SessionState | null;
  onReset?: () => void;
  compact?: boolean;
}

const CIRCUIT_COLOR: Record<string, string> = {
  closed: "var(--green-light)",
  open: "var(--red-light)",
  half_open: "var(--amber)",
};

const CIRCUIT_LABEL: Record<string, string> = {
  closed: "CLOSED · 정상",
  open: "OPEN · 실패",
  half_open: "HALF-OPEN · 복구 중",
};

export default function SessionHealthPanel({ session, onReset, compact }: Props) {
  const handleReset = async () => {
    if (!session) return;
    try {
      await api.resetCircuit(session.session_id);
      onReset?.();
    } catch (e) {
      console.error("Reset failed:", e);
    }
  };

  if (!session) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">
            <HeartPulse size={14} />
            세션 상태
          </div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <HeartPulse size={40} />
            <p>활성 세션이 없습니다</p>
            <p className="empty-hint">채팅을 시작하면 세션 상태가 표시됩니다</p>
          </div>
        </div>
      </div>
    );
  }

  const cb = session.circuit_breaker;
  const contextPct = (session.context_usage_ratio * 100).toFixed(1);
  const contextColor =
    session.context_usage_ratio > 0.9
      ? "var(--red-light)"
      : session.context_usage_ratio > 0.7
      ? "var(--amber)"
      : "var(--green-light)";

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <HeartPulse size={14} />
          세션 상태
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          {session.session_id.slice(0, 8)}...
        </span>
      </div>

      <div className="panel-body">
        {/* Circuit Breaker Status */}
        <div
          style={{
            padding: 12,
            background: "var(--navy-darkest)",
            border: `1px solid ${CIRCUIT_COLOR[cb.state]}40`,
            borderLeft: `3px solid ${CIRCUIT_COLOR[cb.state]}`,
            borderRadius: "var(--radius)",
            marginBottom: 12,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 6,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontSize: 11,
                fontWeight: 600,
                color: CIRCUIT_COLOR[cb.state],
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              <CircuitBoard size={12} />
              {CIRCUIT_LABEL[cb.state]}
            </div>
            {cb.state === "open" && (
              <button className="btn btn-secondary btn-sm" onClick={handleReset}>
                <RefreshCw size={10} /> 초기화
              </button>
            )}
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: 8,
              fontSize: 10,
              color: "var(--gray-400)",
            }}
          >
            <div>
              <div>연속 실패</div>
              <div
                style={{
                  fontSize: 14,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: cb.consecutive_failures > 0 ? "var(--red-light)" : "var(--green-light)",
                }}
              >
                {cb.consecutive_failures} / {cb.failure_threshold}
              </div>
            </div>
            <div>
              <div>성공률</div>
              <div
                style={{
                  fontSize: 14,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: cb.success_rate >= 0.9 ? "var(--green-light)" : "var(--amber)",
                }}
              >
                {(cb.success_rate * 100).toFixed(1)}%
              </div>
            </div>
            <div>
              <div>총 호출</div>
              <div
                style={{
                  fontSize: 14,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "var(--gray-200)",
                }}
              >
                {cb.total_successes + cb.total_failures}
              </div>
            </div>
          </div>
        </div>

        {/* Session Metrics */}
        <div className="metrics-grid" style={{ marginBottom: 12 }}>
          <div className="metric-card">
            <div className="metric-label">현재 턴</div>
            <div className="metric-value">{session.turn_counter}</div>
          </div>
          <div className="metric-card metric-card--blue">
            <div className="metric-label">진행 시간</div>
            <div className="metric-value">
              {Math.floor(session.session_duration_seconds / 60)}
              <span className="metric-unit">분</span>
              {Math.floor(session.session_duration_seconds % 60)}
              <span className="metric-unit">초</span>
            </div>
          </div>
          <div className="metric-card metric-card--green">
            <div className="metric-label">메시지 수</div>
            <div className="metric-value">{session.recent_messages_count}</div>
          </div>
        </div>

        {/* Context Window Usage */}
        <div
          style={{
            padding: 10,
            background: "var(--navy-darkest)",
            border: "1px solid var(--navy-light)",
            borderRadius: "var(--radius)",
            marginBottom: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              marginBottom: 4,
            }}
          >
            <span style={{ color: "var(--gray-400)" }}>컨텍스트 윈도우</span>
            <span
              style={{
                color: contextColor,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              {session.context_tokens_used.toLocaleString()} /{" "}
              {(session.max_context_tokens / 1000).toFixed(0)}k ({contextPct}%)
            </span>
          </div>
          <div className="eval-bar-bg">
            <div
              className="eval-bar-fill"
              style={{
                width: `${Math.min(session.context_usage_ratio * 100, 100)}%`,
                background: contextColor,
              }}
            />
          </div>
          {session.compacted && (
            <div
              style={{
                fontSize: 10,
                color: "var(--amber)",
                marginTop: 4,
                fontStyle: "italic",
              }}
            >
              ⚠ 대화가 {session.compaction_count}회 압축되었습니다
            </div>
          )}
        </div>

        {!compact && (
          <div style={{ fontSize: 10, color: "var(--gray-500)", lineHeight: 1.5 }}>
            <div>생성: {new Date(session.created_at).toLocaleString()}</div>
            <div>마지막 활동: {new Date(session.last_activity).toLocaleString()}</div>
          </div>
        )}
      </div>
    </div>
  );
}
