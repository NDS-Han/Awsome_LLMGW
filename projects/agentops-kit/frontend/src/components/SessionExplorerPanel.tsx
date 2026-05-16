import { useState, useEffect } from "react";
import {
  MessageSquare,
  Clock,
  DollarSign,
  Zap,
  ChevronRight,
  Hash,
  Layers,
  AlertCircle,
} from "lucide-react";
import { api } from "../api";
import { SessionState, SessionTurn } from "../types";

interface Props {
  onSelectTrace?: (traceId: string) => void;
  compact?: boolean;
}

// Format helpers
function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}분 ${secs}초`;
}

function formatTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "방금";
  if (diffMins < 60) return `${diffMins}분 전`;
  if (diffHours < 24) return `${diffHours}시간 전`;
  if (diffDays < 7) return `${diffDays}일 전`;

  return date.toLocaleDateString();
}

function formatCost(cost: number): string {
  return `$${cost.toFixed(4)}`;
}

function getCircuitDotColor(state: string): string {
  switch (state) {
    case "closed":
      return "var(--green-light)";
    case "open":
      return "var(--red-light)";
    case "half_open":
      return "var(--amber)";
    default:
      return "var(--gray-500)";
  }
}

function getEvalScoreColor(score: number | null): string {
  if (score === null) return "var(--gray-500)";
  if (score >= 0.7) return "var(--green-light)";
  if (score >= 0.5) return "var(--amber)";
  return "var(--red-light)";
}

export default function SessionExplorerPanel({ onSelectTrace, compact }: Props) {
  const [sessions, setSessions] = useState<SessionState[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [expandedTurns, setExpandedTurns] = useState<Set<string>>(new Set());

  // Fetch sessions periodically
  useEffect(() => {
    const fetchSessions = async () => {
      try {
        setLoading(true);
        const data = await api.listSessions(50);
        setSessions(data.sessions || []);
        // Auto-select first session if none selected
        if (!selectedSessionId && data.sessions && data.sessions.length > 0) {
          setSelectedSessionId(data.sessions[0].session_id);
        }
      } catch (e) {
        console.error("Failed to fetch sessions:", e);
      } finally {
        setLoading(false);
      }
    };

    fetchSessions();
    const interval = setInterval(fetchSessions, 8000);
    return () => clearInterval(interval);
  }, []);

  // Fetch turns when session selected
  useEffect(() => {
    if (!selectedSessionId) {
      setTurns([]);
      return;
    }

    const fetchTurns = async () => {
      try {
        setTurnsLoading(true);
        const data = await api.getSessionTurns(selectedSessionId, 50);
        setTurns(data.turns || []);
      } catch (e) {
        console.error("Failed to fetch turns:", e);
      } finally {
        setTurnsLoading(false);
      }
    };

    fetchTurns();
    const interval = setInterval(fetchTurns, 5000);
    return () => clearInterval(interval);
  }, [selectedSessionId]);

  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);

  const toggleTurnExpanded = (turnId: string) => {
    const newSet = new Set(expandedTurns);
    if (newSet.has(turnId)) {
      newSet.delete(turnId);
    } else {
      newSet.add(turnId);
    }
    setExpandedTurns(newSet);
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <MessageSquare size={14} />
          세션 탐색기
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          세션 {sessions.length}개
        </span>
      </div>

      <div className="panel-body">
        {sessions.length === 0 ? (
          <div className="empty-state">
            <MessageSquare size={40} />
            <p>아직 세션이 없습니다</p>
            <p className="empty-hint">채팅을 시작하면 세션이 생성됩니다</p>
          </div>
        ) : (
          <div style={{ display: "flex", height: "100%", gap: 12 }}>
            {/* Left pane: Session list */}
            <div
              style={{
                width: 300,
                display: "flex",
                flexDirection: "column",
                gap: 6,
                overflowY: "auto",
                paddingRight: 4,
              }}
            >
              {sessions.map((session) => {
                const isSelected = session.session_id === selectedSessionId;
                const costStr = session.cost_state
                  ? formatCost(session.cost_state.total_cost)
                  : "$0.0000";
                const circuitColor = getCircuitDotColor(
                  session.circuit_breaker.state
                );

                return (
                  <div
                    key={session.session_id}
                    onClick={() => setSelectedSessionId(session.session_id)}
                    style={{
                      padding: 10,
                      background: isSelected ? "var(--navy-light)" : "transparent",
                      border: isSelected
                        ? "1px solid var(--amber)"
                        : "1px solid var(--navy-light)",
                      borderLeft: isSelected
                        ? "3px solid var(--amber)"
                        : "1px solid var(--navy-light)",
                      borderRadius: "var(--radius)",
                      cursor: "pointer",
                      transition: "all 0.1s",
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
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: 11,
                          color: "var(--amber-light)",
                          fontWeight: 600,
                        }}
                      >
                        {session.session_id.slice(0, 8)}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <div
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background: circuitColor,
                          }}
                        />
                        <span
                          style={{
                            fontSize: 9,
                            background: "var(--navy-darker)",
                            padding: "2px 6px",
                            borderRadius: 3,
                            color: "var(--gray-400)",
                          }}
                        >
                          {session.turn_counter}턴
                        </span>
                      </div>
                    </div>

                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--gray-400)",
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: 6,
                      }}
                    >
                      <div>
                        <div style={{ color: "var(--gray-500)" }}>진행 시간</div>
                        <div
                          style={{
                            fontFamily: "'JetBrains Mono', monospace",
                            color: "var(--gray-200)",
                          }}
                        >
                          {formatDuration(session.session_duration_seconds)}
                        </div>
                      </div>
                      <div>
                        <div style={{ color: "var(--gray-500)" }}>비용</div>
                        <div
                          style={{
                            fontFamily: "'JetBrains Mono', monospace",
                            color: "var(--amber-light)",
                          }}
                        >
                          {costStr}
                        </div>
                      </div>
                    </div>

                    <div
                      style={{
                        fontSize: 9,
                        color: "var(--gray-500)",
                        marginTop: 6,
                      }}
                    >
                      {formatTime(session.last_activity)}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Right pane: Turn detail */}
            <div
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                gap: 8,
                overflowY: "auto",
              }}
            >
              {!selectedSession ? (
                <div className="empty-state">
                  <AlertCircle size={40} />
                  <p>세션을 선택하면 턴이 표시됩니다</p>
                </div>
              ) : turnsLoading ? (
                <div className="empty-state">
                  <div style={{ fontSize: 12, color: "var(--gray-400)" }}>
                    턴을 불러오는 중…
                  </div>
                </div>
              ) : turns.length === 0 ? (
                <div className="empty-state">
                  <MessageSquare size={40} />
                  <p>이 세션에 기록된 턴이 없습니다</p>
                </div>
              ) : (
                turns.map((turn, idx) => {
                  const isExpanded = expandedTurns.has(turn.turn_id);
                  const evalScore = turn.eval?.avg_score ?? null;
                  const evalColor = getEvalScoreColor(evalScore);
                  const responsePreview =
                    turn.response.length > 300
                      ? turn.response.slice(0, 300) + "..."
                      : turn.response;

                  return (
                    <div
                      key={turn.turn_id}
                      style={{
                        background: "var(--navy-darkest)",
                        border: "1px solid var(--navy-light)",
                        borderRadius: "var(--radius)",
                        overflow: "hidden",
                      }}
                    >
                      {/* Header row */}
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                          padding: "8px 10px",
                          borderBottom: "1px solid var(--navy-light)",
                          fontSize: 11,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 4,
                            fontWeight: 600,
                            color: "var(--gray-200)",
                            fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >
                          <Hash size={10} />
                          {idx + 1}
                        </div>

                        <span style={{ color: "var(--gray-400)" }}>
                          {formatTime(turn.timestamp)}
                        </span>

                        <span
                          style={{
                            fontSize: 9,
                            background: "var(--navy-light)",
                            padding: "2px 6px",
                            borderRadius: 3,
                            color: "var(--amber-light)",
                          }}
                        >
                          {turn.prompt_version}
                        </span>

                        <div
                          style={{
                            width: 6,
                            height: 6,
                            borderRadius: "50%",
                            background:
                              turn.status === "success"
                                ? "var(--green-light)"
                                : turn.status === "error"
                                ? "var(--red-light)"
                                : "var(--gray-500)",
                          }}
                        />

                        <div style={{ marginLeft: "auto" }}>
                          <button
                            onClick={() =>
                              onSelectTrace?.(turn.trace_id)
                            }
                            style={{
                              background: "transparent",
                              border: "none",
                              color: "var(--blue-light)",
                              cursor: "pointer",
                              fontSize: 10,
                              fontFamily: "'JetBrains Mono', monospace",
                              textDecoration: "underline",
                              padding: 0,
                            }}
                          >
                            {turn.trace_id.slice(0, 8)}
                          </button>
                        </div>
                      </div>

                      {/* User prompt bubble */}
                      <div style={{ padding: "8px 10px" }}>
                        <div
                          style={{
                            background: "var(--blue)",
                            color: "var(--white)",
                            padding: "8px 10px",
                            borderRadius: "var(--radius)",
                            fontSize: 11,
                            lineHeight: 1.5,
                            marginBottom: 6,
                            wordBreak: "break-word",
                          }}
                        >
                          {turn.prompt}
                        </div>

                        {/* Assistant response bubble */}
                        <div
                          style={{
                            background: "var(--navy-light)",
                            color: "var(--gray-200)",
                            padding: "8px 10px",
                            borderRadius: "var(--radius)",
                            fontSize: 11,
                            lineHeight: 1.5,
                            marginBottom: 8,
                            wordBreak: "break-word",
                          }}
                        >
                          {isExpanded ? turn.response : responsePreview}
                          {turn.response.length > 300 && (
                            <>
                              {" "}
                              <button
                                onClick={() => toggleTurnExpanded(turn.turn_id)}
                                style={{
                                  background: "transparent",
                                  border: "none",
                                  color: "var(--amber-light)",
                                  cursor: "pointer",
                                  fontSize: 10,
                                  textDecoration: "underline",
                                  padding: 0,
                                }}
                              >
                                {isExpanded ? "접기" : "더 보기"}
                              </button>
                            </>
                          )}
                        </div>

                        {/* Metrics row */}
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            fontSize: 10,
                            color: "var(--gray-400)",
                            flexWrap: "wrap",
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 3,
                              fontFamily: "'JetBrains Mono', monospace",
                            }}
                          >
                            <Zap size={9} />
                            {turn.latency_ms}ms
                          </div>

                          {turn.token_usage && (
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 3,
                                fontFamily: "'JetBrains Mono', monospace",
                              }}
                            >
                              <Layers size={9} />
                              {turn.token_usage.input_tokens}/
                              {turn.token_usage.output_tokens}
                            </div>
                          )}

                          {turn.cost && (
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 3,
                                fontFamily: "'JetBrains Mono', monospace",
                                color: "var(--amber-light)",
                              }}
                            >
                              <DollarSign size={9} />
                              {turn.cost.total_cost.toFixed(5)}
                            </div>
                          )}

                          {turn.tools_used && turn.tools_used.length > 0 && (
                            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                              {turn.tools_used.map((tool) => (
                                <span
                                  key={tool}
                                  style={{
                                    background: "var(--amber)40",
                                    color: "var(--amber-light)",
                                    padding: "2px 6px",
                                    borderRadius: 3,
                                    fontSize: 9,
                                  }}
                                >
                                  {tool}
                                </span>
                              ))}
                            </div>
                          )}

                          {evalScore !== null && (
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 3,
                                color: evalColor,
                                fontWeight: 600,
                                marginLeft: "auto",
                              }}
                            >
                              <div
                                style={{
                                  width: 6,
                                  height: 6,
                                  borderRadius: "50%",
                                  background: evalColor,
                                }}
                              />
                              {evalScore.toFixed(2)}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
