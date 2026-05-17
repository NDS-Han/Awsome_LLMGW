import { useEffect, useState } from "react";
import { Upload, CheckCircle, Loader2, Layers, Server, Shield, Activity } from "lucide-react";
import { api } from "../../api";
import { PublishableResource } from "../../types";

const TYPE_COLORS: Record<string, string> = {
  A2A: "#60a5fa",
  MCP: "#f59e0b",
  CUSTOM: "#34d399",
  AGENT_SKILLS: "#f87171",
};

const TYPE_ICONS: Record<string, typeof Layers> = {
  A2A: Layers,
  MCP: Server,
  CUSTOM: Shield,
  AGENT_SKILLS: Activity,
};

interface Props {
  onPublished: () => void;
}

export default function RegistryPublishTab({ onPublished }: Props) {
  const [resources, setResources] = useState<PublishableResource[]>([]);
  const [selected, setSelected] = useState<PublishableResource | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [result, setResult] = useState<{ record_id: string; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getPublishableResources()
      .then((r: any) => setResources(r.resources || []))
      .catch(() => {});
  }, []);

  const handlePublish = async () => {
    if (!selected) return;
    setPublishing(true);
    setError(null);
    setResult(null);
    try {
      const resp = await api.publishRegistryRecord({
        name: selected.name,
        description: selected.description,
        descriptor_type: selected.type,
        descriptor_url: selected.descriptor_url,
      });
      setResult(resp);
      onPublished();
    } catch (e: any) {
      setError(e.message || "발행 실패");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Instruction */}
      <div style={{ fontSize: 12, color: "var(--gray-400)", padding: "8px 12px", background: "var(--navy-darkest)", borderRadius: "var(--radius)", border: "1px solid var(--navy-light)" }}>
        기존 에이전트 또는 MCP 도구를 선택하여 Registry에 발행합니다. 발행 후 큐레이터의 승인을 거쳐야 검색 가능합니다.
      </div>

      {/* Resource card grid */}
      <div style={{ fontSize: 11, color: "var(--gray-400)", fontWeight: 600 }}>리소스 선택</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
        {resources.map(r => {
          const isSelected = selected?.name === r.name;
          const color = TYPE_COLORS[r.type] || "#6b7280";
          const Icon = TYPE_ICONS[r.type] || Layers;
          return (
            <div
              key={r.name}
              onClick={() => { setSelected(r); setResult(null); setError(null); }}
              style={{
                padding: 12,
                background: "var(--navy-darkest)",
                border: `1px solid ${isSelected ? "var(--blue-light)" : "var(--navy-light)"}`,
                borderTop: `3px solid ${color}`,
                borderRadius: "var(--radius)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                cursor: "pointer",
                transition: "border-color 0.2s",
                outline: isSelected ? "1px solid var(--blue-light)" : "none",
                outlineOffset: -1,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-100)", lineHeight: 1.3, display: "flex", alignItems: "center", gap: 6 }}>
                  <Icon size={13} style={{ color }} />
                  {r.name}
                </span>
                {isSelected && (
                  <span style={{
                    fontSize: 10, padding: "2px 6px", background: "rgba(96,165,250,0.15)", borderRadius: 3,
                    color: "var(--blue-light)", fontWeight: 600,
                  }}>
                    선택됨
                  </span>
                )}
              </div>
              <div style={{ fontSize: 11, color: "var(--gray-400)", lineHeight: 1.4, flex: 1 }}>
                {r.description}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{
                  fontSize: 10, padding: "2px 6px", background: "var(--navy)", borderRadius: 3,
                  color, fontFamily: "'JetBrains Mono',monospace", fontWeight: 600,
                }}>{r.type}</span>
                {r.descriptor_url && (
                  <span style={{ fontSize: 10, color: "var(--gray-600)", fontFamily: "'JetBrains Mono',monospace", maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.descriptor_url.replace(/^https?:\/\//, "").slice(0, 20)}…
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {resources.length === 0 && (
        <div style={{ padding: 20, textAlign: "center", color: "var(--gray-500)", fontSize: 12 }}>
          발행 가능한 리소스가 없습니다.
        </div>
      )}

      {/* Publish action */}
      {selected && (
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: 12,
          background: "var(--navy-darkest)",
          border: "1px solid var(--navy-light)",
          borderRadius: "var(--radius)",
        }}>
          <div>
            <div style={{ fontSize: 12, color: "var(--gray-200)", fontWeight: 600 }}>
              {selected.name}
            </div>
            <div style={{ fontSize: 10, color: "var(--gray-500)", marginTop: 2 }}>
              {selected.type} · {selected.descriptor_url || "URL 없음"}
            </div>
          </div>
          <button
            onClick={handlePublish}
            disabled={publishing}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              background: "var(--blue-light)",
              color: "#000",
              border: "none",
              borderRadius: "var(--radius)",
              fontSize: 12,
              fontWeight: 600,
              cursor: publishing ? "not-allowed" : "pointer",
              opacity: publishing ? 0.6 : 1,
              whiteSpace: "nowrap",
            }}
          >
            {publishing ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
            {publishing ? "발행 중…" : "Registry에 발행"}
          </button>
        </div>
      )}

      {/* Result */}
      {result && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 10, background: "var(--navy-darkest)", border: "1px solid var(--green-light)", borderRadius: "var(--radius)" }}>
          <CheckCircle size={14} style={{ color: "var(--green-light)" }} />
          <div>
            <div style={{ fontSize: 12, color: "var(--green-light)" }}>발행 완료 — 승인 대기 중</div>
            <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", color: "var(--gray-500)" }}>
              Record ID: {result.record_id}
            </div>
          </div>
        </div>
      )}

      {error && (
        <div style={{ fontSize: 12, color: "var(--red-light)", padding: 10, background: "var(--navy-darkest)", border: "1px solid var(--red-light)", borderRadius: "var(--radius)" }}>
          {error}
        </div>
      )}
    </div>
  );
}
