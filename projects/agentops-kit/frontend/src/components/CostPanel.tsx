import { DollarSign, AlertCircle } from "lucide-react";
import { CostGlobalState, SessionCostState } from "../types";

interface Props {
  global: CostGlobalState | null;
  session?: SessionCostState | null;
  compact?: boolean;
}

const BUDGET_COLOR: Record<string, string> = {
  ok: "var(--green-light)",
  warning: "var(--amber)",
  critical: "var(--amber-light)",
  exceeded: "var(--red-light)",
  unlimited: "var(--gray-400)",
};

export default function CostPanel({ global, session, compact }: Props) {
  if (!global) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">
            <DollarSign size={14} />
            비용 추적
          </div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <DollarSign size={40} />
            <p>아직 비용 데이터가 없습니다</p>
            <p className="empty-hint">에이전트가 호출되면 자동으로 집계됩니다</p>
          </div>
        </div>
      </div>
    );
  }

  const budget = session?.budget;
  const showBudget = budget && budget.status !== "unlimited" && budget.budget_usd;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <DollarSign size={14} />
          비용 추적
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          활성 세션 {global.active_sessions}개
        </span>
      </div>

      <div className="panel-body">
        {/* Global Totals */}
        <div className="metrics-grid" style={{ marginBottom: 12 }}>
          <div className="metric-card">
            <div className="metric-label">누적 비용</div>
            <div className="metric-value">
              ${global.total_cost.toFixed(4)}
            </div>
          </div>
          <div className="metric-card metric-card--blue">
            <div className="metric-label">총 토큰</div>
            <div className="metric-value">
              {(global.total_usage.total_tokens / 1000).toFixed(1)}
              <span className="metric-unit">k</span>
            </div>
          </div>
          <div className="metric-card metric-card--green">
            <div className="metric-label">활성 세션</div>
            <div className="metric-value">{global.active_sessions}</div>
          </div>
        </div>

        {/* Budget Status for current session */}
        {showBudget && (
          <div
            style={{
              padding: 12,
              background: "var(--navy-darkest)",
              border: `1px solid ${BUDGET_COLOR[budget.status]}40`,
              borderRadius: "var(--radius)",
              marginBottom: 12,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                marginBottom: 6,
                fontSize: 11,
                fontWeight: 600,
                color: BUDGET_COLOR[budget.status],
                textTransform: "uppercase",
              }}
            >
              {(budget.status === "warning" || budget.status === "exceeded") && (
                <AlertCircle size={12} />
              )}
              예산 상태: {budget.status}
            </div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 12,
                color: "var(--gray-300)",
                fontFamily: "'JetBrains Mono', monospace",
                marginBottom: 6,
              }}
            >
              <span>${budget.used_usd?.toFixed(4)} 사용</span>
              <span>${budget.budget_usd?.toFixed(2)} 예산</span>
            </div>
            <div className="eval-bar-bg">
              <div
                className="eval-bar-fill"
                style={{
                  width: `${Math.min((budget.used_ratio ?? 0) * 100, 100)}%`,
                  background: BUDGET_COLOR[budget.status],
                }}
              />
            </div>
            <div
              style={{
                fontSize: 10,
                color: "var(--gray-500)",
                marginTop: 4,
                textAlign: "right",
              }}
            >
              {((budget.used_ratio ?? 0) * 100).toFixed(1)}% 사용
            </div>
          </div>
        )}

        {/* Session Cost Breakdown */}
        {session && !compact && (
          <>
            <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>
              현재 세션 (호출 {session.call_count}회)
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 8,
                marginBottom: 12,
              }}
            >
              <div className="metric-card">
                <div className="metric-label">세션 비용</div>
                <div
                  className="metric-value"
                  style={{ fontSize: 16, color: "var(--amber-light)" }}
                >
                  ${session.total_cost.toFixed(4)}
                </div>
              </div>
              <div className="metric-card metric-card--blue">
                <div className="metric-label">과금 대상 토큰</div>
                <div className="metric-value" style={{ fontSize: 16 }}>
                  {session.total_usage.billable_tokens?.toLocaleString() ||
                    session.total_usage.total_tokens.toLocaleString()}
                </div>
              </div>
            </div>

            {/* Model Breakdown */}
            {Object.keys(session.model_breakdown).length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>
                  모델별 사용량
                </div>
                {Object.entries(session.model_breakdown).map(([model, stats]) => (
                  <div
                    key={model}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      padding: "6px 10px",
                      background: "var(--navy-darkest)",
                      border: "1px solid var(--navy-light)",
                      borderRadius: "var(--radius)",
                      marginBottom: 4,
                      fontSize: 11,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    <span style={{ color: "var(--gray-300)" }}>{model}</span>
                    <span style={{ color: "var(--amber-light)" }}>
                      ${stats.cost.toFixed(4)} ({stats.calls}회)
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Top Sessions */}
        {!compact && global.top_sessions.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>
              비용 상위 세션
            </div>
            {global.top_sessions.map((s) => (
              <div
                key={s.session_id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "4px 8px",
                  fontSize: 11,
                  fontFamily: "'JetBrains Mono', monospace",
                  color: "var(--gray-400)",
                }}
              >
                <span>{s.session_id.slice(0, 8)}...</span>
                <span style={{ color: "var(--amber-light)" }}>${s.cost.toFixed(4)}</span>
                <span style={{ color: "var(--gray-500)" }}>호출 {s.calls}회</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
