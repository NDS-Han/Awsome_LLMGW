import { useEffect, useState } from "react";
import { Briefcase, ArrowLeft, AlertCircle } from "lucide-react";
import { api } from "../api";
import { TeamRow, TeamUsage, BudgetState, UserDirectoryEntry } from "../types";

const STATUS_COLORS: Record<string, string> = {
  ok: "var(--green-light)",
  warning: "var(--amber)",
  critical: "var(--amber-light)",
  exceeded: "var(--red-light)",
  unlimited: "var(--gray-400)",
};

export default function TeamsPanel({ compact }: { compact?: boolean }) {
  const [days, setDays] = useState(7);
  const [teams, setTeams] = useState<TeamRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.getTopTeams(days).then(r => setTeams(r.teams || [])).catch(() => {});
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [days]);

  if (selected && !compact) return <TeamDetail teamId={selected} onBack={() => setSelected(null)} />;

  const totalCost = teams.reduce((s, t) => s + t.cost, 0);
  const maxCost = Math.max(...teams.map(t => t.cost), 1);

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><Briefcase size={14}/>팀</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>{teams.length}개 · ${totalCost.toFixed(2)}</span>
        </div>
        <div className="panel-body">
          {teams.slice(0, 5).map((t) => (
            <div key={t.team_id} style={{display:"flex",justifyContent:"space-between",padding:"4px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{fontWeight:600,color:"var(--gray-200)"}}>{t.team_id}</span>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--amber-light)"}}>${t.cost.toFixed(4)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><Briefcase size={14}/>팀 — 비용 합계</div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>
          {teams.length}개 팀 · ${totalCost.toFixed(2)}
        </span>
      </div>
      <div className="panel-body">
        {/* 컨트롤 */}
        <div style={{display:"flex",justifyContent:"flex-end",marginBottom:12}}>
          <select
            value={days}
            onChange={e => setDays(parseInt(e.target.value))}
            style={{
              padding:"8px 10px",borderRadius:"var(--radius)",
              background:"var(--navy-darkest)",color:"var(--gray-200)",
              border:"1px solid var(--navy-lighter)",fontSize:12,
            }}
          >
            <option value="7">최근 7일</option>
            <option value="30">최근 30일</option>
          </select>
        </div>

        {/* 팀 카드 */}
        <div style={{display:"flex",flexDirection:"column",gap:8}}>
          {teams.map(t => (
            <div
              key={t.team_id}
              onClick={() => setSelected(t.team_id)}
              style={{
                padding:14,background:"var(--navy-darkest)",
                border:"1px solid var(--navy-light)",borderLeft:"3px solid var(--amber)",
                borderRadius:"var(--radius)",cursor:"pointer",
              }}
              onMouseEnter={e => (e.currentTarget.style.borderColor="var(--amber)")}
              onMouseLeave={e => (e.currentTarget.style.borderColor="var(--navy-light)")}
            >
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:8}}>
                <span style={{fontSize:14,fontWeight:600,color:"var(--gray-100)"}}>{t.team_id}</span>
                <span style={{fontSize:13,fontWeight:700,color:"var(--amber-light)",fontFamily:"'JetBrains Mono',monospace"}}>
                  ${t.cost.toFixed(4)}
                </span>
              </div>
              <div style={{display:"flex",gap:16,fontSize:11,color:"var(--gray-400)",marginBottom:6}}>
                <span><strong style={{color:"var(--gray-200)"}}>{t.user_count}</strong>명</span>
                <span><strong style={{color:"var(--gray-200)"}}>{t.calls.toLocaleString()}</strong>회 호출</span>
                <span><strong style={{color:"var(--gray-200)"}}>{(t.tokens/1000).toFixed(1)}k</strong> 토큰</span>
                <span style={{marginLeft:"auto"}}>1인당 ${(t.cost/Math.max(t.user_count,1)).toFixed(4)}</span>
              </div>
              <div className="eval-bar-bg">
                <div className="eval-bar-fill" style={{width:`${(t.cost/maxCost)*100}%`,background:"var(--amber)"}}/>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function TeamDetail({ teamId, onBack }: { teamId: string; onBack: () => void }) {
  const [data, setData] = useState<{
    directory: UserDirectoryEntry; usage: TeamUsage; budget: BudgetState;
  } | null>(null);

  useEffect(() => {
    api.getTeamDetail(teamId, 30).then(setData).catch(() => {});
  }, [teamId]);

  if (!data) return <div className="panel"><div className="panel-body">불러오는 중…</div></div>;

  const dir = data.directory;
  const u = data.usage;
  const b = data.budget;
  const maxCost = Math.max(...u.by_user.map(x => x.cost), 1);

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <button onClick={onBack} className="btn btn-secondary btn-sm" style={{marginRight:8}}>
            <ArrowLeft size={12}/>
          </button>
          <Briefcase size={14}/>{dir?.name || teamId}
        </div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>{u.user_count}명 · ${u.total_cost_usd.toFixed(2)} ({u.window_days}일)</span>
      </div>
      <div className="panel-body">
        {/* 예산 */}
        {b && (
          <div style={{
            padding:12,background:"var(--navy-darkest)",
            border:`1px solid ${STATUS_COLORS[b.status]}40`,
            borderLeft:`3px solid ${STATUS_COLORS[b.status]}`,
            borderRadius:"var(--radius)",marginBottom:14,
          }}>
            <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:6}}>
              {(b.status === "warning" || b.status === "exceeded") && <AlertCircle size={14} style={{color:STATUS_COLORS[b.status]}}/>}
              <span style={{fontSize:12,fontWeight:600,color:STATUS_COLORS[b.status],textTransform:"uppercase"}}>
                팀 예산 {b.status} · {b.period}
              </span>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",fontSize:13,fontFamily:"'JetBrains Mono',monospace",marginBottom:6}}>
              <span>${b.used_usd.toFixed(4)} 사용</span>
              <span>${b.budget_usd.toFixed(2)} 예산</span>
            </div>
            <div className="eval-bar-bg">
              <div className="eval-bar-fill" style={{width:`${Math.min(b.ratio*100,100)}%`,background:STATUS_COLORS[b.status]}}/>
            </div>
          </div>
        )}

        {/* 합계 */}
        <div className="metrics-grid" style={{marginBottom:14}}>
          <div className="metric-card">
            <div className="metric-label">총 호출</div>
            <div className="metric-value">{u.total_calls.toLocaleString()}</div>
          </div>
          <div className="metric-card metric-card--blue">
            <div className="metric-label">팀원 수</div>
            <div className="metric-value">{u.user_count}</div>
          </div>
          <div className="metric-card metric-card--green">
            <div className="metric-label">1인당 평균 비용</div>
            <div className="metric-value">${(u.total_cost_usd/Math.max(u.user_count,1)).toFixed(4)}</div>
          </div>
        </div>

        {/* user 랭킹 */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase"}}>
          팀 내 비용 상위 사용자
        </div>
        <div style={{display:"flex",flexDirection:"column",gap:4,maxHeight:400,overflowY:"auto"}}>
          {u.by_user.slice(0,30).map((row, i) => (
            <div key={row.user_id} style={{
              display:"grid",gridTemplateColumns:"30px 2fr 80px 100px 100px",gap:8,
              padding:"6px 10px",fontSize:11,
              background:i%2===0?"var(--navy-darkest)":"transparent",
              borderRadius:3,alignItems:"center",
            }}>
              <span style={{color:i<3?"var(--amber)":"var(--gray-500)",fontWeight:i<3?700:400}}>{i+1}</span>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-200)"}}>{row.user_id}</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace"}}>{row.calls}</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace"}}>{(row.tokens/1000).toFixed(1)}k</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace",color:"var(--amber-light)"}}>
                ${row.cost.toFixed(4)}
                <div style={{height:3,background:"var(--amber)",opacity:0.5,marginTop:2,borderRadius:2,width:`${(row.cost/maxCost)*100}%`}}/>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
