import { useEffect, useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { BookMarked, Wifi, WifiOff } from "lucide-react";
import { api } from "../../api";
import { RegistryState, RegistryMcpEndpoint } from "../../types";

const TYPE_COLORS: Record<string, string> = {
  A2A: "#60a5fa",
  MCP: "#f59e0b",
  CUSTOM: "#34d399",
  AGENT_SKILLS: "#f87171",
};

const STATUS_COLORS: Record<string, string> = {
  APPROVED: "#34d399",
  DRAFT: "#6b7280",
  SUBMITTED: "#f59e0b",
  REJECTED: "#f87171",
  DEPRECATED: "#9ca3af",
};

export default function RegistryOverviewTab({ state }: { state: RegistryState }) {
  const [mcpEndpoint, setMcpEndpoint] = useState<RegistryMcpEndpoint | null>(null);

  useEffect(() => {
    api.getRegistryMcpEndpoint().then(setMcpEndpoint).catch(() => {});
  }, []);

  const typeData = Object.entries(state.by_type).map(([name, value]) => ({ name, value }));
  const statusData = Object.entries(state.by_status).map(([name, value]) => ({ name, value }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Registry meta card */}
      <div style={{
        padding: 12,
        background: "var(--navy-darkest)",
        border: "1px solid var(--navy-light)",
        borderLeft: "3px solid var(--amber)",
        borderRadius: "var(--radius)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <BookMarked size={14} style={{ color: "var(--amber)" }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-200)" }}>
            {state.registry_name}
          </span>
          <span style={{
            fontSize: 10,
            padding: "2px 8px",
            background: "var(--navy-light)",
            borderRadius: 10,
            color: state.status === "READY" ? "var(--green-light)" : "var(--amber)",
          }}>
            {state.status}
          </span>
        </div>
        <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", color: "var(--gray-500)" }}>
          {state.registry_id} · 인증: {state.authorizer_type}
        </div>
      </div>

      {/* Charts row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* Type distribution */}
        <div style={{ background: "var(--navy-darkest)", border: "1px solid var(--navy-light)", borderRadius: "var(--radius)", padding: 12 }}>
          <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8 }}>유형별 분포</div>
          <ResponsiveContainer width="100%" height={120}>
            <PieChart>
              <Pie data={typeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={45} innerRadius={25}>
                {typeData.map((entry) => (
                  <Cell key={entry.name} fill={TYPE_COLORS[entry.name] || "#6b7280"} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            {typeData.map(d => (
              <span key={d.name} style={{ fontSize: 10, color: TYPE_COLORS[d.name] || "#6b7280" }}>
                {d.name}: {d.value}
              </span>
            ))}
          </div>
        </div>

        {/* Status distribution */}
        <div style={{ background: "var(--navy-darkest)", border: "1px solid var(--navy-light)", borderRadius: "var(--radius)", padding: 12 }}>
          <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8 }}>상태별 분포</div>
          <ResponsiveContainer width="100%" height={120}>
            <PieChart>
              <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={45} innerRadius={25}>
                {statusData.map((entry) => (
                  <Cell key={entry.name} fill={STATUS_COLORS[entry.name] || "#6b7280"} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            {statusData.map(d => (
              <span key={d.name} style={{ fontSize: 10, color: STATUS_COLORS[d.name] || "#6b7280" }}>
                {d.name}: {d.value}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* MCP Endpoint status */}
      <div style={{
        padding: 12,
        background: "var(--navy-darkest)",
        border: "1px solid var(--navy-light)",
        borderRadius: "var(--radius)",
      }}>
        <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8 }}>MCP 엔드포인트</div>
        {mcpEndpoint && !("error" in mcpEndpoint) ? (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {mcpEndpoint.status === "connected"
              ? <Wifi size={14} style={{ color: "var(--green-light)" }} />
              : <WifiOff size={14} style={{ color: "var(--red-light)" }} />}
            <div>
              <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono',monospace", color: "var(--gray-300)" }}>
                {mcpEndpoint.url || "URL 미설정"}
              </div>
              <div style={{ fontSize: 10, color: "var(--gray-500)" }}>
                인증: {mcpEndpoint.auth_type} · 상태: {mcpEndpoint.status} · 확인: {mcpEndpoint.last_checked?.slice(11, 19)}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "var(--gray-500)" }}>MCP 엔드포인트 정보를 가져올 수 없습니다.</div>
        )}
      </div>
    </div>
  );
}
