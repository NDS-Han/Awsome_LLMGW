import { useEffect, useState } from "react";
import { PieChart } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { api } from "../api";

interface ToolStats {
  tool_name: string;
  total_calls: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p99_latency_ms: number;
  last_called: string;
}

interface SelectionPattern {
  from_tool: string;
  to_tool: string;
  count: number;
}

interface ToolAnalyticsData {
  tools: ToolStats[];
  total_calls: number;
  most_used: string;
  slowest: string;
  selection_patterns: SelectionPattern[];
}

const TOOL_COLORS: Record<string, string> = {
  query_sales_data: "#ff9900",
  analyze_reviews: "#0073bb",
  check_delivery_performance: "#6aaf35",
  get_seller_metrics: "#44b9d6",
  text2sql_query: "#8b5cf6",
  delegate_to_specialist: "#ec4899",
};

function getColor(name: string): string {
  return TOOL_COLORS[name] || "#879596";
}

function ToolCard({ tool }: { tool: ToolStats }) {
  const color = getColor(tool.tool_name);
  const successPct = (tool.success_rate * 100).toFixed(1);

  return (
    <div
      className="metric-card"
      style={{ borderLeft: `3px solid ${color}`, marginBottom: 8 }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-200)" }}>
          {tool.tool_name.replace(/_/g, " ")}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: tool.success_rate >= 0.95 ? "#22c55e" : tool.success_rate >= 0.8 ? "#f59e0b" : "#ef4444",
            padding: "1px 6px",
            borderRadius: 4,
            background: `${tool.success_rate >= 0.95 ? "#22c55e" : tool.success_rate >= 0.8 ? "#f59e0b" : "#ef4444"}20`,
          }}
        >
          성공률 {successPct}%
        </span>
      </div>

      <div style={{ display: "flex", gap: 16, fontSize: 10 }}>
        <div>
          <div style={{ color: "var(--gray-500)" }}>호출</div>
          <div style={{ fontWeight: 600, color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace" }}>
            {tool.total_calls}
          </div>
        </div>
        <div>
          <div style={{ color: "var(--gray-500)" }}>평균 지연</div>
          <div style={{ fontWeight: 600, color: "var(--amber-light)", fontFamily: "'JetBrains Mono', monospace" }}>
            {tool.avg_latency_ms.toFixed(0)}ms
          </div>
        </div>
        <div>
          <div style={{ color: "var(--gray-500)" }}>P50</div>
          <div style={{ fontWeight: 600, color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace" }}>
            {tool.p50_latency_ms.toFixed(0)}ms
          </div>
        </div>
        <div>
          <div style={{ color: "var(--gray-500)" }}>P99</div>
          <div style={{ fontWeight: 600, color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace" }}>
            {tool.p99_latency_ms.toFixed(0)}ms
          </div>
        </div>
        <div>
          <div style={{ color: "var(--gray-500)" }}>오류</div>
          <div
            style={{
              fontWeight: 600,
              color: tool.error_count > 0 ? "#ef4444" : "var(--gray-500)",
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {tool.error_count}
          </div>
        </div>
      </div>

      {/* Success rate bar */}
      <div
        style={{
          marginTop: 6,
          height: 4,
          background: "var(--bg-tertiary, #1e293b)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${tool.success_rate * 100}%`,
            height: "100%",
            background: color,
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
}

function PatternRow({ pattern }: { pattern: SelectionPattern }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 0",
        fontSize: 11,
        borderBottom: "1px solid var(--gray-800, #1f2937)",
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: getColor(pattern.from_tool),
          flexShrink: 0,
        }}
      />
      <span style={{ color: "var(--gray-300)", minWidth: 120 }}>
        {pattern.from_tool.replace(/_/g, " ")}
      </span>
      <span style={{ color: "var(--gray-600)" }}>→</span>
      <span
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: getColor(pattern.to_tool),
          flexShrink: 0,
        }}
      />
      <span style={{ color: "var(--gray-300)", flex: 1 }}>
        {pattern.to_tool.replace(/_/g, " ")}
      </span>
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          color: "var(--gray-400)",
          fontSize: 10,
        }}
      >
        {pattern.count}x
      </span>
    </div>
  );
}

export default function ToolAnalyticsPanel({ compact }: { compact?: boolean }) {
  const [data, setData] = useState<ToolAnalyticsData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .getToolAnalytics(24)
        .then((res: ToolAnalyticsData) => setData(res))
        .catch((e: Error) => setError(e.message));
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, []);

  const chartData = data?.tools.map((t) => ({
    name: t.tool_name.replace(/_/g, " "),
    fullName: t.tool_name,
    calls: t.total_calls,
    latency: t.avg_latency_ms,
  })) || [];

  if (compact && data && data.tools.length > 0) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><PieChart size={14} />도구 분석</div>
          <span style={{ fontSize: 11, color: "var(--gray-500)" }}>호출 {data.total_calls}회</span>
        </div>
        <div className="panel-body">
          {data.tools.slice(0, 3).map((tool) => (
            <ToolCard key={tool.tool_name} tool={tool} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <PieChart size={14} />
          도구 사용 분석
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          {data ? `총 호출 ${data.total_calls}회` : "불러오는 중…"}
        </span>
      </div>

      <div className="panel-body">
        {error ? (
          <div className="empty-state">
            <PieChart size={40} />
            <p>도구 분석 데이터를 불러올 수 없습니다</p>
            <p className="empty-hint">{error}</p>
          </div>
        ) : !data || data.tools.length === 0 ? (
          <div className="empty-state">
            <PieChart size={40} />
            <p>도구 사용 데이터가 없습니다</p>
            <p className="empty-hint">도구를 호출하는 채팅을 보내주세요</p>
          </div>
        ) : (
          <>
            {/* Summary cards */}
            <div className="metrics-grid" style={{ marginBottom: 16 }}>
              <div className="metric-card">
                <div className="metric-label">총 호출</div>
                <div className="metric-value">{data.total_calls}</div>
              </div>
              <div className="metric-card metric-card--blue">
                <div className="metric-label">최다 사용</div>
                <div className="metric-value" style={{ fontSize: 14 }}>
                  {data.most_used.replace(/_/g, " ")}
                </div>
              </div>
              <div className="metric-card metric-card--red">
                <div className="metric-label">최저 속도</div>
                <div className="metric-value" style={{ fontSize: 14 }}>
                  {data.slowest.replace(/_/g, " ")}
                </div>
              </div>
            </div>

            {/* Call distribution chart */}
            {chartData.length > 0 && (
              <div className="chart-container" style={{ marginBottom: 16 }}>
                <div className="chart-label">호출 분포</div>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={chartData} layout="vertical" margin={{ left: 100 }}>
                    <XAxis type="number" hide />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fontSize: 10, fill: "#879596" }}
                      width={100}
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
                      formatter={(value: number, name: string) => [
                        name === "calls" ? `${value}회` : `${value.toFixed(0)}ms`,
                        name === "calls" ? "호출" : "평균 지연",
                      ]}
                    />
                    <Bar dataKey="calls" radius={[0, 3, 3, 0]}>
                      {chartData.map((entry) => (
                        <Cell key={entry.fullName} fill={getColor(entry.fullName)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Tool cards */}
            <div style={{ marginBottom: 16 }}>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: "var(--gray-400)",
                  marginBottom: 8,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                }}
              >
                도구 성능
              </div>
              {data.tools.map((tool) => (
                <ToolCard key={tool.tool_name} tool={tool} />
              ))}
            </div>

            {/* Selection patterns */}
            {data.selection_patterns.length > 0 && (
              <div>
                <div
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: "var(--gray-400)",
                    marginBottom: 8,
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                  }}
                >
                  도구 선택 패턴
                </div>
                <div
                  style={{
                    background: "var(--bg-tertiary, #0f172a)",
                    borderRadius: 6,
                    padding: "4px 10px",
                  }}
                >
                  {data.selection_patterns.map((p, i) => (
                    <PatternRow key={`${p.from_tool}-${p.to_tool}-${i}`} pattern={p} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
