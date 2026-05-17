import { BarChart3, TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle2, Activity } from "lucide-react";
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
  metricsHours?: number;
  onChangeHours?: (hours: number) => void;
  metricsScope?: "all" | "me";
  onChangeScope?: (scope: "all" | "me") => void;
}

const TIME_RANGES = [
  { label: "1h", value: 1 },
  { label: "6h", value: 6 },
  { label: "24h", value: 24 },
  { label: "7d", value: 168 },
];

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
    <ResponsiveContainer width="100%" height={40}>
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

function TrendIndicator({ values }: { values?: { timestamp: string; value: number }[] }) {
  if (!values || values.length < 2) return null;
  const recent = values.slice(-3);
  const older = values.slice(0, Math.max(1, values.length - 3));
  const recentAvg = recent.reduce((s, v) => s + v.value, 0) / recent.length;
  const olderAvg = older.reduce((s, v) => s + v.value, 0) / older.length;
  const delta = olderAvg === 0 ? 0 : ((recentAvg - olderAvg) / olderAvg) * 100;

  if (Math.abs(delta) < 1) {
    return <span className="metrics-trend metrics-trend--neutral"><Minus size={10} /> 안정</span>;
  }
  if (delta > 0) {
    return <span className="metrics-trend metrics-trend--up"><TrendingUp size={10} /> +{delta.toFixed(0)}%</span>;
  }
  return <span className="metrics-trend metrics-trend--down"><TrendingDown size={10} /> {delta.toFixed(0)}%</span>;
}

function HealthBadge({ metrics }: { metrics: MetricsData }) {
  const errorRate = metrics.errors?.error_rate ?? 0;
  const p99 = metrics.latency.p99;
  const throttles = metrics.errors?.throttles ?? 0;

  let score = 100;
  if (errorRate > 5) score -= 30;
  else if (errorRate > 1) score -= 15;
  if (p99 > 10000) score -= 25;
  else if (p99 > 5000) score -= 10;
  if (throttles > 5) score -= 20;
  else if (throttles > 0) score -= 5;
  score = Math.max(0, score);

  let status: "healthy" | "warning" | "critical";
  let label: string;
  if (score >= 80) { status = "healthy"; label = "정상"; }
  else if (score >= 50) { status = "warning"; label = "주의"; }
  else { status = "critical"; label = "위험"; }

  return (
    <div className={`metrics-health metrics-health--${status}`}>
      {status === "healthy" && <CheckCircle2 size={12} />}
      {status === "warning" && <AlertTriangle size={12} />}
      {status === "critical" && <AlertTriangle size={12} />}
      <span>{label}</span>
      <span className="metrics-health__score">{score}</span>
    </div>
  );
}

function SectionHeader({ title, icon }: { title: string; icon?: React.ReactNode }) {
  return (
    <div className="metrics-section-header">
      {icon}
      <span>{title}</span>
    </div>
  );
}

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="metrics-progress">
      <div className="metrics-progress__fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export default function MetricsPanel({ metrics, compact, agents, selectedAgentId, onSelectAgent, metricsHours, onChangeHours, metricsScope, onChangeScope }: Props) {
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
  })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const totalToolCalls = toolCallData.reduce((s, t) => s + t.count, 0);
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
          <HealthBadge metrics={metrics} />
          {onChangeScope && (
            <select
              value={metricsScope || "all"}
              onChange={(e) => onChangeScope(e.target.value as "all" | "me")}
              className="metrics-agent-select"
            >
              <option value="me">My</option>
              <option value="all">All</option>
            </select>
          )}
          {onChangeHours && (
            <select
              value={metricsHours || 6}
              onChange={(e) => onChangeHours(Number(e.target.value))}
              className="metrics-agent-select"
            >
              {TIME_RANGES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
          {agents && agents.length > 0 && (
            <select
              value={selectedAgentId || ""}
              onChange={(e) => onSelectAgent?.(e.target.value || undefined)}
              className="metrics-agent-select"
            >
              <option value="">전체 에이전트</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>

      <div className="panel-body">
        {/* Hero KPIs */}
        <div className="metrics-hero">
          <div className="metrics-hero__card">
            <div className="metrics-hero__header">
              <span className="metrics-hero__label">평균 지연시간</span>
              <TrendIndicator values={metrics.latency.values} />
            </div>
            <div className="metrics-hero__value">
              {metrics.latency.avg.toFixed(0)}
              <span className="metrics-hero__unit">ms</span>
            </div>
            <div className="metrics-hero__sub">
              P50: {metrics.latency.p50.toFixed(0)}ms · P99: {metrics.latency.p99.toFixed(0)}ms
            </div>
            <MiniChart data={metrics.latency.values} color="#ff9900" />
          </div>

          <div className="metrics-hero__card metrics-hero__card--blue">
            <div className="metrics-hero__header">
              <span className="metrics-hero__label">토큰 사용량</span>
              <TrendIndicator values={metrics.tokens.values} />
            </div>
            <div className="metrics-hero__value">
              {metrics.tokens.total.toLocaleString()}
            </div>
            <div className="metrics-hero__sub">
              호출당 평균 {metrics.tokens.avg_per_call.toLocaleString()} tokens
            </div>
            <MiniChart data={metrics.tokens.values} color="#0073bb" />
          </div>

          <div className="metrics-hero__card metrics-hero__card--green">
            <div className="metrics-hero__header">
              <span className="metrics-hero__label">예상 비용</span>
              <TrendIndicator values={metrics.cost.values} />
            </div>
            <div className="metrics-hero__value">
              ${metrics.cost.total_usd.toFixed(4)}
            </div>
            <div className="metrics-hero__sub">
              {metrics.invocation_count}회 호출 기준
            </div>
            <MiniChart data={metrics.cost.values} color="#6aaf35" />
          </div>
        </div>

        {/* Duration & LLM Breakdown */}
        {duration && (
          <>
            <div className="divider" />
            <SectionHeader title="처리 성능" icon={<Activity size={11} />} />
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">평균 소요시간</div>
                <div className="metric-value">
                  {duration.avg_duration_ms.toFixed(0)}
                  <span className="metric-unit">ms</span>
                </div>
                {!compact && <MiniChart data={duration.values} color="#9b59b6" />}
              </div>
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
                <ProgressBar value={duration.llm_ratio_pct} max={100} color="#ff9900" />
                {!compact && (
                  <div className="metrics-hint">LLM {duration.llm_ratio_pct}% · Tool {100 - duration.llm_ratio_pct}%</div>
                )}
              </div>
            </div>
          </>
        )}

        {/* Errors & Stability */}
        {errors && (
          <>
            <div className="divider" />
            <SectionHeader title="안정성" icon={<AlertTriangle size={11} />} />
            <div className="metrics-grid">
              <div className={`metric-card ${errors.error_rate > 0 ? "metric-card--red" : "metric-card--green"}`}>
                <div className="metric-label">오류율</div>
                <div className="metric-value" style={{ color: errors.error_rate > 5 ? "#e74c3c" : errors.error_rate > 0 ? "#f39c12" : "#6aaf35" }}>
                  {errors.error_rate}
                  <span className="metric-unit">%</span>
                </div>
                <ProgressBar value={errors.error_rate} max={100} color={errors.error_rate > 5 ? "#e74c3c" : errors.error_rate > 0 ? "#f39c12" : "#6aaf35"} />
              </div>
              <div className="metric-card">
                <div className="metric-label">오류 (사용자 / 시스템)</div>
                <div className="metric-value" style={{ color: errors.total > 0 ? "#e74c3c" : "inherit" }}>
                  {errors.total}
                </div>
                <div className="metrics-hint">
                  사용자 {errors.user_errors} · 시스템 {errors.system_errors}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">스로틀</div>
                <div className="metric-value" style={{ color: errors.throttles > 0 ? "#f39c12" : "inherit" }}>
                  {errors.throttles}
                </div>
              </div>
            </div>
          </>
        )}

        {/* Event Loop — Reasoning Cycles */}
        {eventLoop && eventLoop.total_cycles > 0 && (
          <>
            <div className="divider" />
            <SectionHeader title="추론 사이클" />
            <div className="metrics-grid">
              <div className="metric-card">
                <div className="metric-label">총 사이클</div>
                <div className="metric-value">{eventLoop.total_cycles}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">호출당 사이클</div>
                <div className="metric-value">{eventLoop.avg_cycles_per_invocation}</div>
              </div>
              <div className="metric-card">
                <div className="metric-label">사이클 평균시간</div>
                <div className="metric-value">
                  {eventLoop.avg_cycle_duration_ms.toFixed(0)}
                  <span className="metric-unit">ms</span>
                </div>
              </div>
            </div>
          </>
        )}

        {/* Compute Resources */}
        {compute && (compute.cpu_vcpu_hours > 0 || compute.memory_gb_hours > 0) && (
          <>
            <div className="divider" />
            <SectionHeader title="컴퓨트 리소스" />
            <div className="metrics-grid metrics-grid--2col">
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
          </>
        )}

        {/* Tool Call Table */}
        {toolCallData.length > 0 && (
          <>
            <div className="divider" />
            <SectionHeader title={`Tool 호출 (총 ${totalToolCalls}회)`} />
            <div className="metrics-tool-table">
              <div className="metrics-tool-table__header">
                <span>도구</span>
                <span>호출</span>
                <span>비중</span>
                <span>평균 시간</span>
              </div>
              {toolCallData.map((t) => (
                <div key={t.fullName} className="metrics-tool-table__row">
                  <span className="metrics-tool-table__name">
                    <span className="metrics-tool-table__dot" style={{ background: TOOL_COLORS[t.fullName] || "#879596" }} />
                    {t.name}
                  </span>
                  <span className="metrics-tool-table__count">{t.count}회</span>
                  <span className="metrics-tool-table__bar">
                    <ProgressBar value={t.count} max={toolCallData[0].count} color={TOOL_COLORS[t.fullName] || "#879596"} />
                  </span>
                  <span className="metrics-tool-table__duration">
                    {t.duration > 0 ? `${t.duration.toFixed(0)}ms` : "—"}
                  </span>
                </div>
              ))}
            </div>

            {!compact && (
              <div className="chart-container" style={{ marginTop: 10 }}>
                <div className="chart-label">Tool 호출 분포</div>
                <ResponsiveContainer width="100%" height={compact ? 80 : 120}>
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
                      formatter={(value: number) => [`${value}회`, "호출"]}
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
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
