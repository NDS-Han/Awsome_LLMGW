import { useEffect, useState } from "react";
import { BookMarked, CheckCircle, Clock, Search } from "lucide-react";
import { api } from "../api";
import { RegistryState, RegistryRecord } from "../types";

const TYPE_COLORS: Record<string, string> = {
  A2A: "var(--blue-light)",
  MCP: "var(--amber)",
  CUSTOM: "var(--green-light)",
  AGENT_SKILLS: "var(--red-light)",
};

const STATUS_COLORS: Record<string, string> = {
  APPROVED: "var(--green-light)",
  DRAFT: "var(--gray-500)",
  SUBMITTED: "var(--amber)",
  REJECTED: "var(--red-light)",
};

export default function RegistryPanel({ compact }: { compact?: boolean }) {
  const [state, setState] = useState<RegistryState | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  useEffect(() => {
    const load = () => api.getRegistry().then(setState).catch(() => {});
    load();
    const iv = setInterval(load, 12000);
    return () => clearInterval(iv);
  }, []);

  if (!state) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
        </div>
        <div className="panel-body"><div className="empty-state"><BookMarked size={40}/><p>불러오는 중…</p></div></div>
      </div>
    );
  }

  if (state.error) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
        </div>
        <div className="panel-body"><div className="empty-state">
          <BookMarked size={40}/>
          <p>레지스트리가 설정되지 않았습니다</p>
          <p className="empty-hint">{state.error}</p>
        </div></div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><BookMarked size={14}/>레지스트리</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>레코드 {state.record_count}개</span>
        </div>
        <div className="panel-body">
          {state.records.slice(0, 5).map(r => (
            <div key={r.record_id} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{fontWeight:600,color:"var(--gray-100)"}}>{r.name}</span>
              <span style={{fontSize:10,color:TYPE_COLORS[r.descriptor_type] || "var(--gray-400)",fontFamily:"'JetBrains Mono',monospace"}}>{r.descriptor_type}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const filtered = state.records.filter(r => {
    if (typeFilter !== "all" && r.descriptor_type !== typeFilter) return false;
    if (search && !(`${r.name} ${r.description}`.toLowerCase().includes(search.toLowerCase()))) return false;
    return true;
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><BookMarked size={14}/>AgentCore Registry</div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>
          레코드 {state.record_count}개 · 인증 {state.authorizer_type}
        </span>
      </div>
      <div className="panel-body">
        {/* Registry 메타 */}
        <div style={{
          padding:12,
          background:"var(--navy-darkest)",
          border:"1px solid var(--navy-light)",
          borderLeft:"3px solid var(--amber)",
          borderRadius:"var(--radius)",
          marginBottom:14,
        }}>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
            <BookMarked size={14} style={{color:"var(--amber)"}}/>
            <span style={{fontSize:12,fontWeight:600,color:"var(--gray-200)"}}>
              {state.registry_name}
            </span>
            <span style={{
              fontSize:10,
              padding:"2px 8px",
              background:"var(--navy-light)",
              borderRadius:10,
              color: state.status === "READY" ? "var(--green-light)" : "var(--amber)",
            }}>
              {state.status}
            </span>
          </div>
          <div style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-500)",marginBottom:8}}>
            {state.registry_id}
          </div>
          {/* 타입/상태 통계 */}
          <div style={{display:"flex",gap:16,fontSize:11}}>
            <div>
              <span style={{color:"var(--gray-500)"}}>유형: </span>
              {Object.entries(state.by_type).map(([t,n]) => (
                <span key={t} style={{
                  marginRight:6,
                  padding:"1px 6px",
                  background:"var(--navy-light)",
                  borderRadius:3,
                  color:TYPE_COLORS[t] || "var(--gray-400)",
                  fontFamily:"'JetBrains Mono',monospace",
                }}>{t}:{n}</span>
              ))}
            </div>
            <div>
              <span style={{color:"var(--gray-500)"}}>상태: </span>
              {Object.entries(state.by_status).map(([s,n]) => (
                <span key={s} style={{
                  marginRight:6,
                  padding:"1px 6px",
                  background:"var(--navy-light)",
                  borderRadius:3,
                  color:STATUS_COLORS[s] || "var(--gray-400)",
                  fontFamily:"'JetBrains Mono',monospace",
                }}>{s}:{n}</span>
              ))}
            </div>
          </div>
        </div>

        {/* 검색 + 필터 */}
        <div style={{display:"flex",gap:8,marginBottom:10}}>
          <div style={{flex:1,position:"relative"}}>
            <Search size={12} style={{position:"absolute",left:8,top:"50%",transform:"translateY(-50%)",color:"var(--gray-500)"}}/>
            <input
              className="chat-input"
              placeholder="레코드 검색 (이름 또는 설명)…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{paddingLeft:28,width:"100%"}}
            />
          </div>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            style={{
              padding:"8px 10px",
              borderRadius:"var(--radius)",
              background:"var(--navy-darkest)",
              color:"var(--gray-200)",
              border:"1px solid var(--navy-lighter)",
              fontSize:12,
            }}
          >
            <option value="all">전체 유형</option>
            <option value="A2A">A2A (에이전트)</option>
            <option value="MCP">MCP (서버)</option>
            <option value="CUSTOM">커스텀</option>
            <option value="AGENT_SKILLS">Agent Skills</option>
          </select>
        </div>

        {/* 레코드 목록 */}
        <div style={{display:"flex",flexDirection:"column",gap:6}}>
          {filtered.length === 0 ? (
            <div style={{padding:20,textAlign:"center",color:"var(--gray-500)",fontSize:12}}>
              조건에 맞는 레코드가 없습니다.
            </div>
          ) : filtered.map(r => (
            <RecordRow key={r.record_id} r={r} />
          ))}
        </div>
      </div>
    </div>
  );
}

function RecordRow({ r }: { r: RegistryRecord }) {
  const typeColor = TYPE_COLORS[r.descriptor_type] || "var(--gray-500)";
  const statusColor = STATUS_COLORS[r.status] || "var(--gray-500)";
  return (
    <div style={{
      padding:10,
      background:"var(--navy-darkest)",
      border:"1px solid var(--navy-light)",
      borderLeft:`3px solid ${typeColor}`,
      borderRadius:"var(--radius)",
    }}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
        <span style={{fontSize:12,fontWeight:600,color:"var(--gray-100)"}}>{r.name}</span>
        <div style={{display:"flex",gap:6}}>
          <span style={{
            fontSize:10,padding:"2px 6px",background:"var(--navy)",borderRadius:3,
            color:typeColor,fontFamily:"'JetBrains Mono',monospace",fontWeight:600,
          }}>{r.descriptor_type}</span>
          <span style={{
            fontSize:10,padding:"2px 6px",background:"var(--navy)",borderRadius:3,
            color:statusColor,fontWeight:600,display:"inline-flex",alignItems:"center",gap:3,
          }}>
            {r.status === "APPROVED" ? <CheckCircle size={10}/> : <Clock size={10}/>}
            {r.status}
          </span>
        </div>
      </div>
      <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:4}}>
        {r.description}
      </div>
      <div style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-600)"}}>
        {r.record_id} · 업데이트 {r.updated_at?.slice(0,19).replace("T"," ")}
      </div>
    </div>
  );
}
