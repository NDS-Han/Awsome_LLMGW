import { useEffect, useState } from "react";
import { Users, ArrowRight, Network } from "lucide-react";
import { api } from "../api";
import { AgentGatewayAgent, AgentGatewayState } from "../types";

const ROLE_COLORS: Record<string, string> = {
  main: "var(--amber)",
  reviews: "var(--blue-light)",
  logistics: "var(--green-light)",
};

const SPECIALIST_PALETTE = [
  "var(--blue-light)",
  "var(--green-light)",
  "var(--amber-light)",
  "var(--red-light)",
];

function colorForRole(role: string, specialistIndex = 0): string {
  return ROLE_COLORS[role] || SPECIALIST_PALETTE[specialistIndex % SPECIALIST_PALETTE.length];
}

function titleCase(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

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
        <div style={{display:"flex",gap:6,alignItems:"center"}}>
          <span className="badge badge--neutral badge--mono">{state.agent_count}개</span>
          <span className="badge badge--info badge--mono">핸드오프 {state.handoff_count}</span>
        </div>
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
        <div className="section-block__title">
          <Users size={10} />
          <span>등록된 에이전트</span>
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
                <div style={{display:"flex",alignItems:"center",gap:6}}>
                  <span className={`status-dot ${a.status==="READY" ? "status-dot--active" : "status-dot--warning"}`} />
                  <span style={{fontSize:12,fontWeight:600,color:"var(--gray-100)"}}>
                    {a.name}
                  </span>
                </div>
                <span className="badge" style={{background:`${ROLE_COLORS[a.role] || "var(--gray-500)"}20`,color:ROLE_COLORS[a.role] || "var(--gray-400)",border:`1px solid ${ROLE_COLORS[a.role] || "var(--gray-500)"}40`}}>
                  {a.role}
                </span>
              </div>
              <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:4}}>
                {a.description}
              </div>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginTop:4}}>
                <span className="badge badge--neutral badge--mono" style={{maxWidth:"70%",overflow:"hidden",textOverflow:"ellipsis"}}>{a.arn}</span>
                <span className={`badge ${a.status==="READY"?"badge--success":"badge--warning"}`}>{a.status}</span>
              </div>
            </div>
          ))}
        </div>

        {/* A2A 호출 그래프 (SVG edges + flow animation) */}
        {state.agents.length >= 2 && (
          <>
            <div className="divider" />
            <div className="section-block__title">
              <Network size={10} />
              <span>위임 그래프</span>
            </div>
            <DelegationGraph
              agents={state.agents}
              lastTarget={state.last_handoff?.to || null}
            />
          </>
        )}

        {/* 최근 handoff */}
        <div className="section-block__title">
          <ArrowRight size={10} />
          <span>최근 핸드오프</span>
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

function AgentNode({ color, label, compact }: { color: string; label: string; compact?: boolean }) {
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

function DelegationGraph({
  agents,
  lastTarget,
}: {
  agents: AgentGatewayAgent[];
  lastTarget: string | null;
}) {
  const main = agents.find(a => a.role === "main") || agents[0];
  const specialists = agents.filter(a => a !== main);
  if (!main || specialists.length === 0) return null;

  const NODE_W = 92;
  const NODE_HALF = NODE_W / 2;
  const W = 360;
  const ROW_H = 56; // specialist 노드 한 줄 높이
  const MIN_H = 120;
  const H = Math.max(MIN_H, specialists.length * ROW_H + 32);

  const mainPoint = { x: 60, y: H / 2 };
  const specialistX = W - 60;
  // 우측에 균등 배치
  const specialistPoints = specialists.map((_, i) => {
    if (specialists.length === 1) return { x: specialistX, y: H / 2 };
    const top = 24;
    const bottom = H - 24;
    const t = i / (specialists.length - 1);
    return { x: specialistX, y: top + (bottom - top) * t };
  });

  const amber = "var(--amber-light)";
  const dim = "var(--navy-lighter)";

  // 선의 시작/끝을 노드 가장자리로 자르기 위해 단위 벡터로 보정
  const trim = (from: {x:number;y:number}, to: {x:number;y:number}, padFrom: number, padTo: number) => {
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    return {
      x1: from.x + ux * padFrom,
      y1: from.y + uy * padFrom,
      x2: to.x - ux * padTo,
      y2: to.y - uy * padTo,
    };
  };

  const activeSpecialist = specialists.find(a => a.role === lastTarget || a.name === lastTarget);

  return (
    <div style={{
      padding:12,
      background:"var(--navy-darkest)",
      border:"1px solid var(--navy-light)",
      borderRadius:"var(--radius)",
      marginBottom:16,
      display:"flex",
      justifyContent:"center",
    }}>
      <div style={{position:"relative",width:W,height:H}}>
        <svg width={W} height={H} style={{position:"absolute",inset:0,overflow:"visible"}}>
          {specialists.map((agent, i) => {
            const active = agent === activeSpecialist;
            const line = trim(mainPoint, specialistPoints[i], NODE_HALF, NODE_HALF);
            return (
              <line
                key={agent.arn || agent.name}
                x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2}
                stroke={active ? amber : dim}
                strokeWidth={active ? 2.5 : 1.5}
                className={active ? "flow-edge" : ""}
              />
            );
          })}
        </svg>
        <NodePin x={mainPoint.x} y={mainPoint.y} color={colorForRole(main.role)} label={titleCase(main.role || main.name)} />
        {specialists.map((agent, i) => (
          <NodePin
            key={agent.arn || agent.name}
            x={specialistPoints[i].x}
            y={specialistPoints[i].y}
            color={colorForRole(agent.role, i)}
            label={titleCase(agent.role || agent.name)}
          />
        ))}
        {activeSpecialist && (
          <div style={{
            position:"absolute",
            right:0,
            bottom:-4,
            fontSize:10,
            color:"var(--amber-light)",
            fontFamily:"'JetBrains Mono',monospace",
          }}>
            ▸ {main.role || main.name} → {activeSpecialist.role || activeSpecialist.name}
          </div>
        )}
      </div>
    </div>
  );
}

function NodePin({ x, y, color, label }: { x: number; y: number; color: string; label: string }) {
  return (
    <div style={{
      position:"absolute",
      left:x,
      top:y,
      transform:"translate(-50%, -50%)",
    }}>
      <AgentNode color={color} label={label} compact />
    </div>
  );
}
