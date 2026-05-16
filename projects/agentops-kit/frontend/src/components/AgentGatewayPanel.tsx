import { useEffect, useState } from "react";
import { Users, ArrowRight, Network } from "lucide-react";
import { api } from "../api";
import { AgentGatewayState } from "../types";

const ROLE_COLORS: Record<string, string> = {
  main: "var(--amber)",
  reviews: "var(--blue-light)",
  logistics: "var(--green-light)",
};

export default function AgentGatewayPanel({ compact }: { compact?: boolean }) {
  const [state, setState] = useState<AgentGatewayState | null>(null);

  useEffect(() => {
    const load = () => api.getAgentGateway().then(setState).catch(() => {});
    load();
    const iv = setInterval(load, 2000);
    return () => clearInterval(iv);
  }, []);

  if (!state) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Users size={14}/>Agent Gateway</div>
        </div>
        <div className="panel-body"><div className="empty-state"><Users size={40}/><p>불러오는 중…</p></div></div>
      </div>
    );
  }

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Users size={14}/>Agent Gateway</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>에이전트 {state.agent_count}개</span>
        </div>
        <div className="panel-body">
          {state.agents.map(a => (
            <div key={a.arn} style={{display:"flex",justifyContent:"space-between",alignItems:"center",padding:"5px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{fontWeight:600,color:ROLE_COLORS[a.role] || "var(--gray-400)"}}>{a.name}</span>
              <span style={{fontSize:10,color:a.status==="READY"?"var(--green-light)":"var(--amber)"}}>{a.status}</span>
            </div>
          ))}
          {state.handoff_count > 0 && (
            <div style={{marginTop:6,fontSize:10,color:"var(--gray-500)"}}>핸드오프 {state.handoff_count}회</div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><Users size={14}/>Agent Gateway</div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>
          에이전트 {state.agent_count}개 · 핸드오프 {state.handoff_count}회
        </span>
      </div>
      <div className="panel-body">
        {state.error && (
          <div className="gw-error-banner">Agent Gateway 오류: {state.error}</div>
        )}
        {/* 프로토콜 */}
        <div style={{
          padding:10,
          background:"var(--navy-darkest)",
          border:"1px solid var(--navy-light)",
          borderLeft:"3px solid var(--blue-light)",
          borderRadius:"var(--radius)",
          marginBottom:14,
          display:"flex",
          alignItems:"center",
          gap:8,
        }}>
          <Network size={16} style={{color:"var(--blue-light)"}}/>
          <div>
            <div style={{fontSize:12,fontWeight:600,color:"var(--gray-200)"}}>프로토콜</div>
            <div style={{fontSize:11,color:"var(--gray-400)",fontFamily:"'JetBrains Mono',monospace"}}>
              {state.protocol}
            </div>
          </div>
        </div>

        {/* 등록된 에이전트 */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase",letterSpacing:0.5}}>
          등록된 에이전트
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:8,marginBottom:16}}>
          {state.agents.map(a => (
            <div key={a.arn} style={{
              padding:10,
              background:"var(--navy-darkest)",
              border:"1px solid var(--navy-light)",
              borderLeft:`3px solid ${ROLE_COLORS[a.role] || "var(--gray-500)"}`,
              borderRadius:"var(--radius)",
            }}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:2}}>
                <span style={{fontSize:12,fontWeight:600,color:"var(--gray-100)"}}>
                  {a.name}
                </span>
                <span style={{
                  fontSize:10,
                  padding:"2px 8px",
                  background:"var(--navy)",
                  borderRadius:10,
                  color:ROLE_COLORS[a.role] || "var(--gray-400)",
                  fontWeight:600,
                  textTransform:"uppercase",
                }}>
                  {a.role}
                </span>
              </div>
              <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:4}}>
                {a.description}
              </div>
              <div style={{fontSize:10,fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-500)",display:"flex",justifyContent:"space-between"}}>
                <span style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{a.arn}</span>
                <span style={{color:a.status==="READY"?"var(--green-light)":"var(--amber)",marginLeft:8}}>
                  {a.status}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* A2A 호출 그래프 (SVG edges + flow animation) */}
        {state.agents.length >= 3 && (
          <>
            <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase",letterSpacing:0.5}}>
              위임 그래프
            </div>
            <DelegationGraph lastTarget={state.last_handoff?.to || null} />
          </>
        )}

        {/* 최근 handoff */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase",letterSpacing:0.5}}>
          최근 핸드오프
        </div>
        {state.handoffs.length === 0 ? (
          <div style={{fontSize:11,color:"var(--gray-500)",padding:10}}>
            아직 A2A 위임 내역이 없습니다. main 에이전트에게 전문가 지식이 필요한 질문을 해보세요.
          </div>
        ) : (
          <div style={{display:"flex",flexDirection:"column",gap:4}}>
            {state.handoffs.slice(0,10).map((h, idx) => (
              <div
                key={h.turn_id + "-" + idx}
                className={idx === 0 && state.last_handoff?.turn_id === h.turn_id ? "slide-in" : ""}
                style={{
                  padding:"6px 10px",
                  background:"var(--navy-darkest)",
                  border:"1px solid var(--navy-light)",
                  borderRadius:"var(--radius)",
                  fontSize:11,
              }}>
                <div style={{display:"flex",alignItems:"center",gap:6,color:"var(--gray-400)",marginBottom:2}}>
                  <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--amber)"}}>{h.from}</span>
                  <ArrowRight size={10}/>
                  <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--blue-light)"}}>{h.to}</span>
                  <span style={{marginLeft:"auto",fontSize:10,color:"var(--gray-600)"}}>
                    {new Date(h.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <div style={{color:"var(--gray-300)",fontSize:11}}>{h.prompt}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AgentNode({ role, label, compact }: { role: string; label: string; compact?: boolean }) {
  const color = ROLE_COLORS[role] || "var(--gray-500)";
  return (
    <div style={{
      padding: compact ? "6px 10px" : "10px 14px",
      background: "var(--navy)",
      border: `2px solid ${color}`,
      borderRadius: "var(--radius)",
      minWidth: compact ? 90 : 120,
      textAlign: "center",
    }}>
      <div style={{fontSize:compact?11:13,fontWeight:600,color}}>
        {label}
      </div>
      <div style={{fontSize:10,color:"var(--gray-500)",fontFamily:"'JetBrains Mono',monospace"}}>
        agent
      </div>
    </div>
  );
}

function DelegationGraph({ lastTarget }: { lastTarget: string | null }) {
  const W = 360;
  const H = 120;
  const MAIN = { x: 70, y: H / 2 };
  const REVIEWS = { x: 290, y: 30 };
  const LOGISTICS = { x: 290, y: 90 };
  const amber = "var(--amber-light)";
  const dim = "var(--navy-lighter)";
  const reviewsActive = lastTarget === "reviews";
  const logisticsActive = lastTarget === "logistics";
  const anyActive = reviewsActive || logisticsActive;

  return (
    <div style={{
      padding:12,
      background:"var(--navy-darkest)",
      border:"1px solid var(--navy-light)",
      borderRadius:"var(--radius)",
      marginBottom:16,
      position:"relative",
      display:"flex",
      alignItems:"center",
      justifyContent:"center",
    }}>
      <svg width={W} height={H} style={{overflow:"visible"}}>
        {/* main → reviews */}
        <line
          x1={MAIN.x + 40} y1={MAIN.y} x2={REVIEWS.x - 40} y2={REVIEWS.y}
          stroke={reviewsActive ? amber : dim}
          strokeWidth={reviewsActive ? 2.5 : 1.5}
          className={reviewsActive ? "flow-edge" : ""}
        />
        {/* main → logistics */}
        <line
          x1={MAIN.x + 40} y1={MAIN.y} x2={LOGISTICS.x - 40} y2={LOGISTICS.y}
          stroke={logisticsActive ? amber : dim}
          strokeWidth={logisticsActive ? 2.5 : 1.5}
          className={logisticsActive ? "flow-edge" : ""}
        />
      </svg>
      <div style={{position:"absolute",left:12 + MAIN.x - 46,top:12 + MAIN.y - 26}}>
        <AgentNode role="main" label="Main" compact/>
      </div>
      <div style={{position:"absolute",left:12 + REVIEWS.x - 46,top:12 + REVIEWS.y - 20}}>
        <AgentNode role="reviews" label="Reviews" compact/>
      </div>
      <div style={{position:"absolute",left:12 + LOGISTICS.x - 46,top:12 + LOGISTICS.y - 20}}>
        <AgentNode role="logistics" label="Logistics" compact/>
      </div>
      {anyActive && (
        <div style={{
          position:"absolute",
          right:10,
          bottom:8,
          fontSize:10,
          color:"var(--amber-light)",
          fontFamily:"'JetBrains Mono',monospace",
        }}>
          ▸ main → {lastTarget}
        </div>
      )}
    </div>
  );
}
