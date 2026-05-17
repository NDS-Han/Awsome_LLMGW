import { useState } from "react";
import { CheckCircle, XCircle, Archive, Loader2, Clock } from "lucide-react";
import { api } from "../../api";
import { RegistryRecord } from "../../types";

const TYPE_COLORS: Record<string, string> = {
  A2A: "var(--blue-light)",
  MCP: "var(--amber)",
  CUSTOM: "var(--green-light)",
  AGENT_SKILLS: "var(--red-light)",
};

interface Props {
  records: RegistryRecord[];
  onAction: () => void;
}

export default function RegistryCurationTab({ records, onAction }: Props) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "SUBMITTED" | "APPROVED">("all");

  const filtered = records.filter(r => {
    if (filter === "all") return true;
    return r.status === filter;
  });

  const handleAction = async (recordId: string, action: "approve" | "reject" | "deprecate") => {
    setActionLoading(`${recordId}-${action}`);
    try {
      if (action === "approve") await api.approveRegistryRecord(recordId);
      else if (action === "reject") await api.rejectRegistryRecord(recordId);
      else await api.deprecateRegistryRecord(recordId);
      onAction();
    } catch {
      // silent
    } finally {
      setActionLoading(null);
    }
  };

  const pendingCount = records.filter(r => r.status === "SUBMITTED").length;
  const approvedCount = records.filter(r => r.status === "APPROVED").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Stats bar */}
      <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
        <span style={{ color: "var(--amber)" }}>승인 대기: {pendingCount}</span>
        <span style={{ color: "var(--green-light)" }}>승인됨: {approvedCount}</span>
        <span style={{ color: "var(--gray-500)" }}>전체: {records.length}</span>
      </div>

      {/* Filter */}
      <div style={{ display: "flex", gap: 4 }}>
        {(["all", "SUBMITTED", "APPROVED"] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: "4px 10px",
              fontSize: 11,
              background: filter === f ? "var(--navy-light)" : "transparent",
              color: filter === f ? "var(--gray-100)" : "var(--gray-500)",
              border: "1px solid var(--navy-light)",
              borderRadius: "var(--radius)",
              cursor: "pointer",
            }}
          >
            {f === "all" ? "전체" : f === "SUBMITTED" ? "대기 중" : "승인됨"}
          </button>
        ))}
      </div>

      {/* Record list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 20, textAlign: "center", color: "var(--gray-500)", fontSize: 12 }}>
            해당 상태의 레코드가 없습니다.
          </div>
        ) : filtered.map(r => (
          <div key={r.record_id} style={{
            padding: 10,
            background: "var(--navy-darkest)",
            border: "1px solid var(--navy-light)",
            borderLeft: `3px solid ${TYPE_COLORS[r.descriptor_type] || "var(--gray-500)"}`,
            borderRadius: "var(--radius)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <div>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-100)" }}>{r.name}</span>
                <span style={{ fontSize: 10, marginLeft: 8, color: TYPE_COLORS[r.descriptor_type] || "var(--gray-400)", fontFamily: "'JetBrains Mono',monospace" }}>{r.descriptor_type}</span>
              </div>
              <span style={{
                fontSize: 10,
                padding: "2px 6px",
                background: "var(--navy)",
                borderRadius: 3,
                color: r.status === "SUBMITTED" ? "var(--amber)" : r.status === "APPROVED" ? "var(--green-light)" : "var(--gray-400)",
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
              }}>
                <Clock size={10} />
                {r.status}
              </span>
            </div>
            <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>{r.description}</div>

            {/* Action buttons */}
            <div style={{ display: "flex", gap: 6 }}>
              {r.status === "SUBMITTED" && (
                <>
                  <button
                    onClick={() => handleAction(r.record_id, "approve")}
                    disabled={actionLoading === `${r.record_id}-approve`}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", fontSize: 11, fontWeight: 600,
                      background: "transparent", border: "1px solid var(--green-light)",
                      color: "var(--green-light)", borderRadius: "var(--radius)", cursor: "pointer",
                    }}
                  >
                    {actionLoading === `${r.record_id}-approve` ? <Loader2 size={12} className="spin" /> : <CheckCircle size={12} />}
                    승인
                  </button>
                  <button
                    onClick={() => handleAction(r.record_id, "reject")}
                    disabled={actionLoading === `${r.record_id}-reject`}
                    style={{
                      display: "flex", alignItems: "center", gap: 4,
                      padding: "4px 10px", fontSize: 11, fontWeight: 600,
                      background: "transparent", border: "1px solid var(--red-light)",
                      color: "var(--red-light)", borderRadius: "var(--radius)", cursor: "pointer",
                    }}
                  >
                    {actionLoading === `${r.record_id}-reject` ? <Loader2 size={12} className="spin" /> : <XCircle size={12} />}
                    거부
                  </button>
                </>
              )}
              {r.status === "APPROVED" && (
                <button
                  onClick={() => handleAction(r.record_id, "deprecate")}
                  disabled={actionLoading === `${r.record_id}-deprecate`}
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "4px 10px", fontSize: 11, fontWeight: 600,
                    background: "transparent", border: "1px solid var(--gray-500)",
                    color: "var(--gray-500)", borderRadius: "var(--radius)", cursor: "pointer",
                  }}
                >
                  {actionLoading === `${r.record_id}-deprecate` ? <Loader2 size={12} className="spin" /> : <Archive size={12} />}
                  폐기
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
