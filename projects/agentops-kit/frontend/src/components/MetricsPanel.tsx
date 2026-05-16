import { BarChart3 } from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import { MetricsData } from "../types";

interface AgentInfo {
  agent_id: string;
  name: string;
}

interface Props {
  metrics: MetricsData | null;
  compact?: boolean;
  agents?: AgentInfo[];
  selectedAgentId?: string;
  onSelectAgent?: (agentId: string | undefined) => void;
}

const TOOL_COLORS: Record<string, string> = {
  query_sales_data: "#ff9900",
  analyze_reviews: "#0073bb",
  check_delivery_performance: "#6aaf35",
  get_seller_metrics: "#44b9d6",
};

function MiniChart({ data, color }: { data: { timestamp: string; value: number }[]; color: string }) {
  if (!data || data.length === 0) return null;

  const chartData = data.map((d, i) => ({
    idx: i,
    value: d.value,
  }));

  return (
    <ResponsiveContainer width="100%" height={50}>
      <AreaChart data={chartData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`grad-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#grad-${color.replace("#", "")})`}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export default function MetricsPanel({ metrics, compact, agents, selectedAgentId, onSelectAgent }: Props) {
  if (!metrics) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">
            <BarChart3 size={14} />
            메트릭
          </div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <BarChart3 size={40} />
            <p>아직 메트릭 데이터가 없습니다</p>
            <p className="empty-hint">채팅을 시작하면 자동으로 수집됩니다</p>
          </div>
        </div>
      </div>
    );
  }

  const toolCallData = Object.entries(metrics.tool_calls || {}).map(([name, count]) => ({
    name: name.replace(/_/g, " "),
    count,
    duration: metrics.tool_durations?.[name] ?? 0,
    fullName: name,
  }));

  const errors = metrics.errors;
  const duration = metrics.duration;
  const eventLoop = metrics.event_loop;
  const compute = metrics.compute;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <BarChart3 size={14} />
          메트릭
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {agents && agents.length > 0 && (
            <select
              value={selectedAgentId || ""}
              onChange={(e) => onSelectAgent?.(e.target.value || undefined)}
              style={{
                fontSize: 11,
                padding: "2px 6px",
                background: "var(--bg-secondary, #1a2332)",
                color: "var(--text-primary, #d5dbdb)",
                border: "1px solid var(--border-color, #2a3f54)",
                borderRadius: 4,
                cursor: "pointer",
              }}
            >
              <option value="">전체 에이전트</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
          <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
            호출 {metrics.invocation_count}회
          </span>
        </div>
      </div>

      <div className="panel-body">
        {/* Summary Cards */}
        <div className="metrics-grid">
          <div className="metric-card">
            <div className="metric-label">평균 지연시간</div>
            <div className="metric-value">
              {metrics.latency.avg.toFixed(0)}
              <span className="metric-unit">ms</span>
            </div>
            <MiniChart data={metrics.latency.values} color="#ff9900" />
          </div>
          <div className="metric-card metric-card--blue">
            <div className="metric-label">총 토큰</div>
            <div className="metric-value">
              {metrics.tokens.total.toLocaleString()}
            </div>
            <MiniChart data={metrics.tokens.values} color="#0073bb" />
          </div>
          <div className="metric-card metric-card--green">
            <div className="metric-label">예상 비용</div>
            <div className="metric-value">
              ${metrics.cost.total_usd.toFixed(4)}
            </div>
            <MiniChart data={metrics.cost.values} color="#6aaf35" />
          </div>
        </div>

        {/* Latency Percentiles + Error Rate */}
        {!compact && (
          <div className="metrics-grid" style={{ marginBottom: 14 }}>
            <div className="metric-card">
              <div className="metric-label">P50 지연시간</div>
              <div className="metric-value">
                {metrics.latency.p50.toFixed(0)}
                <span className="metric-unit">ms</span>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">P99 지연시간</div>
              <div className="metric-value">
                {metrics.latency.p99.toFixed(0)}
                <span className="metric-unit">ms</span>
              </div>
            </div>
            <div className="metric-card metric-card--blue">
              <div className="metric-label">호출당 평균 토큰</div>
              <div className="metric-value">
                {metrics.tokens.avg_per_call.toLocaleString()}
              </div>
            </div>
          </div>
        )}

        {/* Error & Stability */}
        {!compact && errors && (
          <div className="metrics-grid" style={{ marginBottom: 14 }}>
            <div className="metric-card metric-card--red">
              <div className="metric-label">오류율</div>
              <div className="metric-value" style={{ color: errors.error_rate > 0 ? "#e74c3c" : "#6aaf35" }}>
                {errors.error_rate}
                <span className="metric-unit">%</span>
              </div>
              <MiniChart data={errors.values} color="#e74c3c" />
            </div>
            <div className="metric-card metric-card--red">
              <div className="metric-label">총 오류</div>
              <div className="metric-value" style={{ color: errors.total > 0 ? "#e74c3c" : "inherit" }}>
                {errors.total}
              </div>
              <div style={{ fontSize: 9, color: "var(--gray-500)", marginTop: 2 }}>
                사용자 오류: {errors.user_errors} · 시스템 오류: {errors.system_errors}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">스로틀</div>
              <div className="metric-value" style={{ color: errors.throttles > 0 ? "#f39c12" : "inherit" }}>
                {errors.throttles}
              </div>
            </div>
          </div>
        )}

        {/* Duration Breakdown — LLM vs Total */}
        {!compact && duration && (
          <div className="metrics-grid" style={{ marginBottom: 14 }}>
            <div className="metric-card">
              <div className="metric-label">LLM 처리시간</div>
              <div className="metric-value">
                {duration.avg_llm_ms.toFixed(0)}
                <span className="metric-unit">ms</span>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">LLM 비중</div>
              <div className="metric-value">
                {duration.llm_ratio_pct}
                <span className="metric-unit">%</span>
              </div>
              <div style={{ marginTop: 4, height: 6, background: "var(--bg-secondary, #1a2332)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${Math.min(duration.llm_ratio_pct, 100)}%`, height: "100%", background: "#ff9900", borderRadius: 3 }} />
              </div>
              <div style={{ fontSize: 9, color: "var(--gray-500)", marginTop: 2 }}>
                LLM vs Tool 실행 비율
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">평균 소요시간</div>
              <div className="metric-value">
                {duration.avg_duration_ms.toFixed(0)}
                <span className="metric-unit">ms</span>
              </div>
              <MiniChart data={duration.values} color="#9b59b6" />
            </div>
          </div>
        )}

        {/* Event Loop — Reasoning Cycles */}
        {!compact && eventLoop && eventLoop.total_cycles > 0 && (
          <div className="metrics-grid" style={{ marginBottom: 14 }}>
            <div className="metric-card">
              <div className="metric-label">추론 사이클</div>
              <div className="metric-value">
                {eventLoop.total_cycles}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">호출당 사이클</div>
              <div className="metric-value">
                {eventLoop.avg_cycles_per_invocation}
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">사이클당 평균 시간</div>
              <div className="metric-value">
                {eventLoop.avg_cycle_duration_ms.toFixed(0)}
                <span className="metric-unit">ms</span>
              </div>
            </div>
          </div>
        )}

        {/* Compute Resources */}
        {!compact && compute && (compute.cpu_vcpu_hours > 0 || compute.memory_gb_hours > 0) && (
          <div className="metrics-grid" style={{ marginBottom: 14 }}>
            <div className="metric-card">
              <div className="metric-label">CPU 사용량</div>
              <div className="metric-value">
                {compute.cpu_vcpu_hours.toFixed(4)}
                <span className="metric-unit">vCPU·h</span>
              </div>
            </div>
            <div className="metric-card">
              <div className="metric-label">메모리 사용량</div>
              <div className="metric-value">
                {compute.memory_gb_hours.toFixed(4)}
                <span className="metric-unit">GB·h</span>
              </div>
            </div>
          </div>
        )}

        {/* Tool Call Distribution with Duration */}
        {toolCallData.length > 0 && (
          <div className="chart-container">
            <div className="chart-label">Tool 호출 횟수 및 평균 소요시간</div>
            <ResponsiveContainer width="100%" height={compact ? 80 : 140}>
              <BarChart data={toolCallData} layout="vertical" margin={{ left: 80 }}>
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "#c4cdd3" }}
                  width={80}
                  axisLine={{ stroke: "#3b506d" }}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: "rgba(255, 153, 0, 0.05)" }}
                  contentStyle={{
                    background: "rgba(20, 28, 44, 0.95)",
                    border: "1px solid #3b506d",
                    borderRadius: 8,
                    fontSize: 11,
                    boxShadow: "0 4px 12px rgba(0, 0, 0, 0.4)",
                  }}
                  itemStyle={{ color: "#eaeded" }}
                  labelStyle={{ color: "#ff9900", fontWeight: 600 }}
                  formatter={(value: number, name: string) =>
                    name === "count" ? [`${value}회`, "호출"] : [`${value.toFixed(0)} ms`, "평균 소요시간"]
                  }
                />
                <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                  {toolCallData.map((entry) => (
                    <Cell
                      key={entry.fullName}
                      fill={TOOL_COLORS[entry.fullName] || "#879596"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            {!compact && Object.keys(metrics.tool_durations || {}).length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                {toolCallData.map((t) => (
                  t.duration > 0 && (
                    <span key={t.fullName} style={{ fontSize: 10, color: "var(--gray-500)" }}>
                      <span style={{ color: TOOL_COLORS[t.fullName] || "#879596" }}>●</span>{" "}
                      {t.name}: 평균 {t.duration.toFixed(0)}ms
                    </span>
                  )
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
