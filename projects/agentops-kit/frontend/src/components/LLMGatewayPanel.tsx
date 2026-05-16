import { useEffect, useState } from "react";
import { Cpu, ShieldCheck, Zap } from "lucide-react";
import { api } from "../api";
import { LLMGatewayState } from "../types";

export default function LLMGatewayPanel({ compact }: { compact?: boolean }) {
  const [state, setState] = useState<LLMGatewayState | null>(null);

  useEffect(() => {
    const load = () => api.getLLMGateway().then(setState).catch(() => {});
    load();
    const iv = setInterval(load, 2000);
    return () => clearInterval(iv);
  }, []);

  if (!state) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Cpu size={14}/>LLM Gateway</div>
        </div>
        <div className="panel-body">
          <div className="empty-state"><Cpu size={40}/><p>불러오는 중…</p></div>
        </div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Cpu size={14}/>LLM Gateway</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>{state.routing_policy} · 호출 {state.total_calls}회</span>
        </div>
        <div className="panel-body">
          {state.models.map(m => (
            <div key={m.id} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{fontWeight:600,color:"var(--gray-100)"}}>{m.name}</span>
              <div style={{display:"flex",gap:8,fontSize:10,color:"var(--gray-400)"}}>
                <span>{m.calls}회</span>
                <span style={{color:"var(--amber-light)"}}>${m.cost_usd.toFixed(5)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><Cpu size={14}/>LLM Gateway</div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>
          정책: {state.routing_policy} · 호출 {state.total_calls}회
        </span>
      </div>
      <div className="panel-body">
        {state.error && (
          <div className="gw-error-banner">LLM Gateway 통계를 가져올 수 없습니다: {state.error}</div>
        )}
        {state.last_routing_reason && (
          <div style={{
            marginBottom:12,
            padding:"6px 10px",
            background:"var(--navy-darkest)",
            border:"1px solid var(--navy-light)",
            borderLeft:"3px solid var(--amber)",
            borderRadius:"var(--radius)",
            fontSize:11,
            color:"var(--gray-300)",
            fontFamily:"'JetBrains Mono',monospace",
          }}>
            <span style={{color:"var(--gray-500)",marginRight:6}}>라우팅:</span>
            {state.last_routing_reason}
          </div>
        )}
        {/* 모델 카탈로그 */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:8,textTransform:"uppercase",letterSpacing:0.5}}>
          모델 카탈로그
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))",gap:10,marginBottom:14}}>
          {state.models.map(m => (
            <div
              key={m.id}
              className={state.last_model_used && m.id === state.last_model_used ? "pulse-amber" : ""}
              style={{
                padding:10,
                background:"var(--navy-darkest)",
                border:"1px solid var(--navy-light)",
                borderLeft:`3px solid ${m.tier === "quality" ? "var(--amber)" : "var(--blue-light)"}`,
                borderRadius:"var(--radius)",
            }}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                <span style={{fontSize:12,fontWeight:600,color:"var(--gray-100)"}}>{m.name}</span>
                <span style={{fontSize:10,color:m.tier==="quality"?"var(--amber-light)":"var(--blue-light)",
                  padding:"2px 6px",background:"var(--navy)",borderRadius:3,fontWeight:600}}>
                  {m.tier}
                </span>
              </div>
              <div style={{fontSize:10,color:"var(--gray-500)",fontFamily:"'JetBrains Mono',monospace",marginBottom:6,wordBreak:"break-all"}}>
                {m.id}
              </div>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:4,fontSize:11}}>
                <div><span style={{color:"var(--gray-500)"}}>호출:</span> <b>{m.calls}회</b></div>
                <div><span style={{color:"var(--gray-500)"}}>평균:</span> <b>{m.avg_latency_ms}ms</b></div>
                <div><span style={{color:"var(--gray-500)"}}>토큰:</span> <b>{(m.input_tokens+m.output_tokens).toLocaleString()}</b></div>
                <div><span style={{color:"var(--gray-500)"}}>비용:</span> <b style={{color:"var(--amber-light)"}}>${m.cost_usd.toFixed(5)}</b></div>
              </div>
            </div>
          ))}
        </div>

        {/* 가드레일 */}
        <div style={{
          padding:10,
          background:"var(--navy-darkest)",
          border:"1px solid var(--navy-light)",
          borderRadius:"var(--radius)",
          marginBottom:14,
          display:"flex",
          alignItems:"center",
          gap:16,
        }}>
          <ShieldCheck size={18} style={{color:"var(--green-light)"}}/>
          <div>
            <div style={{fontSize:11,fontWeight:600,color:"var(--gray-200)"}}>가드레일 (PII 마스킹)</div>
            <div style={{fontSize:11,color:"var(--gray-500)"}}>
              입력 마스킹: <b style={{color:"var(--amber-light)"}}>{state.guardrails.input_scrubs}건</b> ·
              출력 마스킹: <b style={{color:"var(--amber-light)"}}>{state.guardrails.output_scrubs}건</b>
            </div>
          </div>
          {Object.entries(state.guardrails.detected_tags).length > 0 && (
            <div style={{marginLeft:"auto",display:"flex",gap:6,flexWrap:"wrap"}}>
              {Object.entries(state.guardrails.detected_tags).map(([tag,count])=>(
                <span key={tag} className="tool-badge">{tag}: {count}</span>
              ))}
            </div>
          )}
        </div>

        {/* 최근 호출 */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase",letterSpacing:0.5}}>
          최근 LLM 호출
        </div>
        {state.recent_calls.length === 0 ? (
          <div style={{fontSize:11,color:"var(--gray-500)",padding:10}}>아직 호출 내역이 없습니다 — 에이전트를 호출하면 표시됩니다.</div>
        ) : (
          <div style={{display:"flex",flexDirection:"column",gap:3,maxHeight:300,overflowY:"auto"}}>
            {state.recent_calls.slice(0,15).map((c,i) => (
              <div key={i} style={{
                display:"grid",
                gridTemplateColumns:"120px 1fr 80px 80px 80px",
                gap:8,
                padding:"4px 8px",
                fontSize:11,
                fontFamily:"'JetBrains Mono',monospace",
                color:"var(--gray-400)",
                borderRadius:3,
                background:i%2===0?"var(--navy-darkest)":"transparent",
              }}>
                <span>{new Date(c.timestamp*1000).toLocaleTimeString()}</span>
                <span style={{color:"var(--gray-300)",overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                  {c.model.split(".").slice(-1)[0]}
                </span>
                <span><Zap size={10} style={{verticalAlign:"middle"}}/> {c.latency_ms}ms</span>
                <span>{c.input_tokens+c.output_tokens} 토큰</span>
                <span style={{color:"var(--amber-light)"}}>${c.cost_usd.toFixed(5)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
