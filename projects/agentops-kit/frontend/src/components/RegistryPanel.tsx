import { useEffect, useState, useCallback } from "react";
import { BookMarked } from "lucide-react";
import { api } from "../api";
import { RegistryState } from "../types";
import RegistryOverviewTab from "./registry/RegistryOverviewTab";
import RegistryPublishTab from "./registry/RegistryPublishTab";
import RegistryCurationTab from "./registry/RegistryCurationTab";
import RegistryRecordsTab from "./registry/RegistryRecordsTab";

type SubTab = "overview" | "records" | "publish" | "curation";

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: "overview", label: "개요" },
  { id: "records", label: "레코드" },
  { id: "publish", label: "등록" },
  { id: "curation", label: "큐레이션" },
];

export default function RegistryPanel({ compact }: { compact?: boolean }) {
  const [state, setState] = useState<RegistryState | null>(null);
  const [subTab, setSubTab] = useState<SubTab>("overview");

  const reload = useCallback(() => {
    api.getRegistry().then(setState).catch(() => {});
  }, []);

  useEffect(() => {
    reload();
    const iv = setInterval(reload, 12000);
    return () => clearInterval(iv);
  }, [reload]);

  if (!state) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
        </div>
        <div className="panel-body">
          <div className="empty-state"><BookMarked size={40}/><p>불러오는 중…</p></div>
        </div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
        </div>
        <div className="panel-body">
          <div className="empty-state">
            <BookMarked size={40}/>
            <p>레지스트리가 설정되지 않았습니다</p>
            <p className="empty-hint">{state.error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
          <span style={{ fontSize: 11, color: "var(--gray-500)" }}>레코드 {state.record_count}개</span>
        </div>
        <div className="panel-body">
          {state.records.slice(0, 5).map(r => (
            <div key={r.record_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0", fontSize: 11, borderBottom: "1px solid var(--navy-light)" }}>
              <span style={{ fontWeight: 600, color: "var(--gray-100)" }}>{r.name}</span>
              <span style={{ fontSize: 10, color: "var(--gray-400)", fontFamily: "'JetBrains Mono',monospace" }}>{r.descriptor_type}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><BookMarked size={14}/>AgentCore Registry</div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="badge badge--neutral badge--mono">{state.record_count}개</span>
          <span className="badge badge--success">{state.status}</span>
        </div>
      </div>
      <div className="panel-body">
        {/* Sub-tab navigation */}
        <div style={{ display: "flex", gap: 2, marginBottom: 14, borderBottom: "1px solid var(--navy-light)", paddingBottom: 8 }}>
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setSubTab(t.id)}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: subTab === t.id ? 600 : 400,
                color: subTab === t.id ? "var(--blue-light)" : "var(--gray-400)",
                background: subTab === t.id ? "var(--navy-light)" : "transparent",
                border: "none",
                borderRadius: "var(--radius)",
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Sub-tab content */}
        {subTab === "overview" && <RegistryOverviewTab state={state} />}
        {subTab === "records" && <RegistryRecordsTab state={state} />}
        {subTab === "publish" && <RegistryPublishTab onPublished={reload} />}
        {subTab === "curation" && <RegistryCurationTab records={state.records} onAction={reload} />}
      </div>
    </div>
  );
}
