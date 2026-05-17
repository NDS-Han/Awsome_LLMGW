import { useEffect, useRef, useState } from "react";
import { Wrench, Link2, Search } from "lucide-react";
import { api } from "../api";
import { ToolGatewayState } from "../types";

export default function ToolGatewayPanel({ compact }: { compact?: boolean }) {
  const [state, setState] = useState<ToolGatewayState | null>(null);
  const prevCountsRef = useRef<Record<string, number>>({});
  const [recentDelta, setRecentDelta] = useState<Record<string, number>>({});

  useEffect(() => {
    const load = () =>
      api.getToolGateway()
        .then((next: ToolGatewayState) => {
          const prev = prevCountsRef.current;
          const delta: Record<string, number> = {};
          for (const [name, cnt] of Object.entries(next.call_counts || {})) {
            const before = prev[name] || 0;
            if (cnt > before) delta[name] = cnt - before;
          }
          if (Object.keys(delta).length > 0) {
            setRecentDelta((d) => ({ ...d, ...delta }));
            Object.keys(delta).forEach((name) => {
              setTimeout(() => {
                setRecentDelta((d) => {
                  const { [name]: _removed, ...rest } = d;
                  return rest;
                });
              }, 1800);
            });
          }
          prevCountsRef.current = { ...(next.call_counts || {}) };
          setState(next);
        })
        .catch(() => {});
    load();
    const iv = setInterval(load, 2000);
    return () => clearInterval(iv);
  }, []);

  if (!state) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Wrench size={14}/>Tool Gateway</div>
        </div>
        <div className="panel-body"><div className="empty-state"><Wrench size={40}/><p>불러오는 중…</p></div></div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Wrench size={14}/>Tool Gateway</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>도구 {state.tool_count}개</span>
        </div>
        <div className="panel-body">
          {state.tools.slice(0, 4).map(t => (
            <div key={t.name} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--amber)"}}>{t.name}</span>
              {(state.call_counts[t.name] || 0) > 0 && (
                <span style={{fontSize:10,color:"var(--green-light)"}}>호출 {state.call_counts[t.name]}회</span>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><Wrench size={14}/>Tool Gateway</div>
        <div style={{display:"flex",gap:6,alignItems:"center"}}>
          <span className="badge badge--neutral badge--mono">{state.tool_count}개 도구</span>
          <span className="badge badge--info">{state.authorizer}</span>
        </div>
      </div>
      <div className="panel-body">
        {state.error && (
          <div className="gw-error-banner">Tool Gateway 오류: {state.error}</div>
        )}
        {/* Gateway 메타 */}
        <div style={{
          padding:12,
          background:"var(--navy-darkest)",
          border:"1px solid var(--navy-light)",
          borderLeft:"3px solid var(--amber)",
          borderRadius:"var(--radius)",
          marginBottom:14,
        }}>
          <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:4}}>
            <Link2 size={12} style={{color:"var(--amber)"}}/>
            <span style={{fontSize:12,fontWeight:600,color:"var(--gray-200)"}}>
              AgentCore Gateway (MCP Server)
            </span>
          </div>
          <div style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-400)",wordBreak:"break-all"}}>
            {state.gateway_url}
          </div>
          <div style={{display:"flex",gap:12,marginTop:6,fontSize:11,color:"var(--gray-500)"}}>
            <span>Gateway ID: <b style={{color:"var(--gray-300)"}}>{state.gateway_id.slice(0,20)}...</b></span>
            {state.semantic_search_enabled && (
              <span style={{color:"var(--green-light)",display:"inline-flex",alignItems:"center",gap:3}}>
                <Search size={10}/> Semantic Search 활성
              </span>
            )}
          </div>
        </div>

        {/* 도구 목록 */}
        <div className="section-block__title">
          <Wrench size={10} />
          <span>등록된 도구 ({state.tools.length}개)</span>
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:8}}>
          {state.tools.map(t => {
            const calls = state.call_counts[t.name] || 0;
            const delta = recentDelta[t.name];
            const isLast = state.last_tool_used === t.name;
            const pulse = isLast || delta != null;
            return (
              <div
                key={t.name}
                className={pulse ? "pulse-green" : ""}
                style={{
                  padding:10,
                  background:"var(--navy-darkest)",
                  border:"1px solid var(--navy-light)",
                  borderRadius:"var(--radius)",
              }}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4,gap:6}}>
                  <div style={{display:"flex",alignItems:"center",gap:6}}>
                    <span className={`status-dot ${calls > 0 ? "status-dot--active" : "status-dot--idle"}`} />
                    <span style={{fontSize:12,fontWeight:600,color:"var(--amber)",fontFamily:"'JetBrains Mono',monospace"}}>
                      {t.name}
                    </span>
                  </div>
                  <div style={{display:"flex",alignItems:"center",gap:6}}>
                    {delta != null && (
                      <span className="badge badge--success">+{delta}</span>
                    )}
                    {calls > 0 && (
                      <span className="badge badge--neutral badge--mono">호출 {calls}회</span>
                    )}
                  </div>
                </div>
                <div style={{fontSize:11,color:"var(--gray-300)",marginBottom:4}}>
                  {t.description}
                </div>
                {t.schema?.properties && (
                  <div style={{display:"flex",flexWrap:"wrap",gap:4,marginTop:4}}>
                    {Object.entries(t.schema.properties).slice(0,6).map(([k,v]: any)=>(
                      <span key={k} className="badge badge--neutral badge--mono">
                        {k}: {v?.type || "any"}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
