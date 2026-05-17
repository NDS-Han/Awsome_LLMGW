import { useState } from "react";
import { Search, CheckCircle, Clock, Zap, Link2, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "../../api";
import { RegistryState, RegistryRecord } from "../../types";

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

export default function RegistryRecordsTab({ state }: { state: RegistryState }) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [semantic, setSemantic] = useState(false);
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResults, setSemanticResults] = useState<RegistryRecord[]>([]);
  const [semanticSearching, setSemanticSearching] = useState(false);
  const [semanticSearched, setSemanticSearched] = useState(false);
  const [connectedTools, setConnectedTools] = useState<Set<string>>(new Set());
  const [connecting, setConnecting] = useState<string | null>(null);

  const handleSemanticSearch = async () => {
    if (!semanticQuery.trim()) return;
    setSemanticSearching(true);
    setSemanticSearched(false);
    try {
      const resp = await api.searchRegistry(semanticQuery.trim());
      setSemanticResults(resp.records || []);
    } catch {
      setSemanticResults([]);
    } finally {
      setSemanticSearching(false);
      setSemanticSearched(true);
    }
  };

  const handleConnect = (recordId: string) => {
    setConnecting(recordId);
    setTimeout(() => {
      setConnectedTools(prev => new Set([...prev, recordId]));
      setConnecting(null);
    }, 1200);
  };

  const filteredRecords = state.records.filter(r => {
    if (typeFilter !== "all" && r.descriptor_type !== typeFilter) return false;
    if (search && !(`${r.name} ${r.description}`.toLowerCase().includes(search.toLowerCase()))) return false;
    return true;
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {/* Search bar + semantic toggle */}
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        {semantic ? (
          <>
            <div style={{ position: "relative", flex: 1 }}>
              <Zap size={12} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "var(--blue-light)" }} />
              <input
                className="chat-input"
                placeholder="자연어로 검색 (예: 매출 분석 도구, 배송 성능 확인)…"
                value={semanticQuery}
                onChange={e => setSemanticQuery(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") handleSemanticSearch(); }}
                style={{ paddingLeft: 28, width: "100%" }}
              />
            </div>
            <button
              onClick={handleSemanticSearch}
              disabled={semanticSearching || !semanticQuery.trim()}
              style={{
                padding: "8px 14px",
                background: "var(--blue-light)",
                color: "#000",
                border: "none",
                borderRadius: "var(--radius)",
                fontSize: 12,
                fontWeight: 600,
                cursor: semanticSearching ? "not-allowed" : "pointer",
                opacity: semanticSearching || !semanticQuery.trim() ? 0.6 : 1,
                display: "flex",
                alignItems: "center",
                gap: 4,
                whiteSpace: "nowrap",
              }}
            >
              {semanticSearching ? <Loader2 size={14} className="spin" /> : <Search size={14} />}
              검색
            </button>
          </>
        ) : (
          <>
            <div style={{ position: "relative", flex: 1 }}>
              <Search size={12} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "var(--gray-500)" }} />
              <input
                className="chat-input"
                placeholder="레코드 검색 (이름 또는 설명)…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ paddingLeft: 28, width: "100%" }}
              />
            </div>
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value)}
              style={{
                padding: "8px 10px",
                borderRadius: "var(--radius)",
                background: "var(--navy-darkest)",
                color: "var(--gray-200)",
                border: "1px solid var(--navy-lighter)",
                fontSize: 12,
              }}
            >
              <option value="all">전체 유형</option>
              <option value="A2A">A2A (에이전트)</option>
              <option value="MCP">MCP (서버)</option>
              <option value="CUSTOM">커스텀</option>
              <option value="AGENT_SKILLS">Agent Skills</option>
            </select>
          </>
        )}
        <button
          onClick={() => {
            setSemantic(s => !s);
            setSemanticSearched(false);
            setSemanticResults([]);
          }}
          style={{
            padding: "8px 12px",
            background: semantic ? "rgba(96,165,250,0.15)" : "transparent",
            border: `1px solid ${semantic ? "var(--blue-light)" : "var(--navy-lighter)"}`,
            color: semantic ? "var(--blue-light)" : "var(--gray-400)",
            borderRadius: "var(--radius)",
            fontSize: 11,
            fontWeight: 600,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 4,
            whiteSpace: "nowrap",
          }}
        >
          <Zap size={12} />
          시맨틱 검색
        </button>
      </div>

      {semantic && (
        <div style={{
          padding: "8px 12px",
          background: "var(--navy-darkest)",
          border: "1px solid var(--navy-light)",
          borderLeft: "3px solid var(--blue-light)",
          borderRadius: "var(--radius)",
          fontSize: 11,
          color: "var(--gray-400)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <Zap size={12} style={{ color: "var(--blue-light)", flexShrink: 0 }} />
          에이전트 동적 발견 시뮬레이션 — 에이전트가 런타임에 Registry를 검색하여 적합한 도구를 찾고 연결합니다.
        </div>
      )}

      {/* Card grid */}
      {semantic ? (
        <>
          {semanticSearched && semanticResults.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "var(--gray-500)", fontSize: 12 }}>
              검색 결과가 없습니다. 다른 키워드로 시도해보세요.
            </div>
          )}
          {semanticResults.length > 0 && (
            <>
              <div style={{ fontSize: 11, color: "var(--gray-500)" }}>
                검색 결과: {semanticResults.length}건
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                {semanticResults.map(r => (
                  <SemanticCard
                    key={r.record_id}
                    r={r}
                    isConnected={connectedTools.has(r.record_id)}
                    isConnecting={connecting === r.record_id}
                    onConnect={() => handleConnect(r.record_id)}
                  />
                ))}
              </div>
            </>
          )}
          {!semanticSearched && semanticResults.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "var(--gray-500)", fontSize: 12 }}>
              자연어로 검색어를 입력하고 검색 버튼을 누르세요.
            </div>
          )}
        </>
      ) : (
        <>
          {filteredRecords.length > 0 ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
              {filteredRecords.map(r => (
                <RecordCard key={r.record_id} r={r} />
              ))}
            </div>
          ) : (
            <div style={{ padding: 20, textAlign: "center", color: "var(--gray-500)", fontSize: 12 }}>
              등록된 레코드가 없습니다.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function RecordCard({ r }: { r: RegistryRecord }) {
  const typeColor = TYPE_COLORS[r.descriptor_type] || "#6b7280";
  const statusColor = STATUS_COLORS[r.status] || "#6b7280";
  return (
    <div style={{
      padding: 12,
      background: "var(--navy-darkest)",
      border: "1px solid var(--navy-light)",
      borderTop: `3px solid ${typeColor}`,
      borderRadius: "var(--radius)",
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, overflow: "hidden" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-100)", lineHeight: 1.3, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
        <span style={{
          fontSize: 10, padding: "2px 6px", background: "var(--navy)", borderRadius: 3,
          color: statusColor, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 3,
          flexShrink: 0,
        }}>
          {r.status === "APPROVED" ? <CheckCircle size={10} /> : <Clock size={10} />}
          {r.status}
        </span>
      </div>
      <div style={{ fontSize: 11, color: "var(--gray-400)", lineHeight: 1.4, flex: 1 }}>
        {r.description}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{
          fontSize: 10, padding: "2px 6px", background: "var(--navy)", borderRadius: 3,
          color: typeColor, fontFamily: "'JetBrains Mono',monospace", fontWeight: 600,
        }}>{r.descriptor_type}</span>
        <span style={{ fontSize: 10, color: "var(--gray-600)" }}>
          {r.updated_at?.slice(0, 10)}
        </span>
      </div>
    </div>
  );
}

function SemanticCard({ r, isConnected, isConnecting, onConnect }: {
  r: RegistryRecord;
  isConnected: boolean;
  isConnecting: boolean;
  onConnect: () => void;
}) {
  const typeColor = TYPE_COLORS[r.descriptor_type] || "#6b7280";
  return (
    <div style={{
      padding: 12,
      background: "var(--navy-darkest)",
      border: `1px solid ${isConnected ? "var(--green-light)" : "var(--navy-light)"}`,
      borderTop: `3px solid ${typeColor}`,
      borderRadius: "var(--radius)",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      transition: "border-color 0.3s",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, overflow: "hidden" }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-100)", lineHeight: 1.3, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
        {r.search_score != null && (
          <span style={{ fontSize: 10, color: "var(--gray-500)", flexShrink: 0 }}>
            {(r.search_score * 100).toFixed(0)}%
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: "var(--gray-400)", lineHeight: 1.4, flex: 1 }}>
        {r.description}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{
          fontSize: 10, padding: "2px 6px", background: "var(--navy)", borderRadius: 3,
          color: typeColor, fontFamily: "'JetBrains Mono',monospace", fontWeight: 600,
        }}>{r.descriptor_type}</span>
        {isConnected ? (
          <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--green-light)" }}>
            <CheckCircle2 size={12} />
            연결됨
          </span>
        ) : (
          <button
            onClick={onConnect}
            disabled={isConnecting}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 10px", fontSize: 11, fontWeight: 600,
              background: "transparent", border: "1px solid var(--blue-light)",
              color: "var(--blue-light)", borderRadius: "var(--radius)", cursor: "pointer",
            }}
          >
            {isConnecting ? <Loader2 size={12} className="spin" /> : <Link2 size={12} />}
            {isConnecting ? "연결 중…" : "도구 연결"}
          </button>
        )}
      </div>
    </div>
  );
}
