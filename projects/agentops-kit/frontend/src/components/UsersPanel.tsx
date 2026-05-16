import { useEffect, useState } from "react";
import { User, Search, ArrowLeft, AlertCircle } from "lucide-react";
import { api } from "../api";
import { UserRow, UserUsage, UserDirectoryEntry, BudgetState } from "../types";

const STATUS_COLORS: Record<string, string> = {
  ok: "var(--green-light)",
  warning: "var(--amber)",
  critical: "var(--amber-light)",
  exceeded: "var(--red-light)",
  unlimited: "var(--gray-400)",
};

export default function UsersPanel({ compact }: { compact?: boolean }) {
  const [days, setDays] = useState(7);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.getTopUsers(days).then(r => setUsers(r.users || [])).catch(() => {});
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [days]);

  const filtered = users.filter(u =>
    !search || u.user_id.toLowerCase().includes(search.toLowerCase()) ||
    u.team_id.toLowerCase().includes(search.toLowerCase())
  );

  if (selected && !compact) {
    return <UserDetail userId={selected} onBack={() => setSelected(null)} />;
  }

  const totalCost = users.reduce((s, u) => s + u.cost, 0);

  if (compact) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><User size={14}/>사용자</div>
          <span style={{fontSize:11,color:"var(--gray-500)"}}>{users.length}명 · ${totalCost.toFixed(2)}</span>
        </div>
        <div className="panel-body">
          {users.slice(0, 5).map((u, i) => (
            <div key={u.user_id} style={{display:"flex",justifyContent:"space-between",padding:"4px 0",fontSize:11,borderBottom:"1px solid var(--navy-light)"}}>
              <span style={{color:i<3?"var(--amber)":"var(--gray-400)"}}>{i+1}. {u.user_id}</span>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--amber-light)"}}>${u.cost.toFixed(4)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title"><User size={14}/>사용자 — 비용 상위</div>
        <span style={{fontSize:11,color:"var(--gray-500)"}}>
          {users.length}명 · ${totalCost.toFixed(2)}
        </span>
      </div>
      <div className="panel-body">
        {/* 컨트롤 */}
        <div style={{display:"flex",gap:8,marginBottom:12}}>
          <div style={{flex:1,position:"relative"}}>
            <Search size={12} style={{position:"absolute",left:8,top:"50%",transform:"translateY(-50%)",color:"var(--gray-500)"}}/>
            <input
              className="chat-input"
              placeholder="사용자 ID 또는 팀으로 검색…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{paddingLeft:28,width:"100%"}}
            />
          </div>
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
            <option value="14">최근 14일</option>
            <option value="30">최근 30일</option>
          </select>
        </div>

        {/* 헤더 row */}
        <div style={{
          display:"grid",gridTemplateColumns:"30px 2fr 1fr 80px 100px 100px",
          gap:8,padding:"6px 10px",fontSize:10,color:"var(--gray-500)",
          textTransform:"uppercase",letterSpacing:0.5,
        }}>
          <span>#</span><span>사용자</span><span>팀</span><span style={{textAlign:"right"}}>호출</span>
          <span style={{textAlign:"right"}}>토큰</span><span style={{textAlign:"right"}}>비용</span>
        </div>

        <div style={{display:"flex",flexDirection:"column",gap:2,maxHeight:550,overflowY:"auto"}}>
          {filtered.map((u, i) => (
            <div
              key={u.user_id}
              onClick={() => setSelected(u.user_id)}
              style={{
                display:"grid",gridTemplateColumns:"30px 2fr 1fr 80px 100px 100px",
                gap:8,padding:"6px 10px",fontSize:11,
                background:i%2===0?"var(--navy-darkest)":"transparent",
                borderRadius:3,cursor:"pointer",alignItems:"center",
              }}
              onMouseEnter={e => (e.currentTarget.style.background="var(--navy-light)")}
              onMouseLeave={e => (e.currentTarget.style.background=i%2===0?"var(--navy-darkest)":"transparent")}
            >
              <span style={{color:i<3?"var(--amber)":"var(--gray-500)",fontWeight:i<3?700:400}}>{i+1}</span>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-200)"}}>{u.user_id}</span>
              <span style={{color:"var(--gray-400)"}}>{u.team_id}</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-300)"}}>{u.calls.toLocaleString()}</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-300)"}}>{(u.tokens/1000).toFixed(1)}k</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace",color:"var(--amber-light)",fontWeight:600}}>${u.cost.toFixed(4)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function UserDetail({ userId, onBack }: { userId: string; onBack: () => void }) {
  const [data, setData] = useState<{
    directory: UserDirectoryEntry; usage: UserUsage; budget: BudgetState;
  } | null>(null);

  useEffect(() => {
    api.getUserDetail(userId, 30).then(setData).catch(() => {});
  }, [userId]);

  if (!data) return <div className="panel"><div className="panel-body">불러오는 중…</div></div>;

  const dir = data.directory;
  const u = data.usage;
  const b = data.budget;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <button onClick={onBack} className="btn btn-secondary btn-sm" style={{marginRight:8}}>
            <ArrowLeft size={12}/>
          </button>
          <User size={14}/>{dir?.name || userId}
        </div>
        <span style={{fontSize:11,color:"var(--gray-500)",fontFamily:"'JetBrains Mono',monospace"}}>{userId}</span>
      </div>
      <div className="panel-body">
        {/* 프로필 */}
        <div style={{
          display:"grid",gridTemplateColumns:"1fr 1fr 1fr 1fr",gap:10,marginBottom:14,
          padding:12,background:"var(--navy-darkest)",border:"1px solid var(--navy-light)",
          borderRadius:"var(--radius)",
        }}>
          <KV label="팀" value={dir?.team_id || "—"}/>
          <KV label="역할" value={dir?.role || "—"}/>
          <KV label="이메일" value={dir?.email || "—"}/>
          <KV label="생성" value={dir?.created_at?.slice(0,10) || "—"}/>
        </div>

        {/* 예산 */}
        {b && (
          <div style={{
            padding:12,background:"var(--navy-darkest)",
            border:`1px solid ${STATUS_COLORS[b.status] || "var(--navy-light)"}40`,
            borderLeft:`3px solid ${STATUS_COLORS[b.status]}`,
            borderRadius:"var(--radius)",marginBottom:14,
          }}>
            <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:6}}>
              {(b.status === "warning" || b.status === "exceeded") && <AlertCircle size={12} style={{color:STATUS_COLORS[b.status]}}/>}
              <span style={{fontSize:11,fontWeight:600,color:STATUS_COLORS[b.status],textTransform:"uppercase"}}>
                예산 {b.status} · {b.period}
              </span>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",fontSize:12,fontFamily:"'JetBrains Mono',monospace",marginBottom:6}}>
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
            <div className="metric-label">토큰</div>
            <div className="metric-value">{(u.total_tokens/1000).toFixed(1)}<span className="metric-unit">k</span></div>
          </div>
          <div className="metric-card metric-card--green">
            <div className="metric-label">비용 ({u.window_days}일)</div>
            <div className="metric-value">${u.total_cost_usd.toFixed(4)}</div>
          </div>
        </div>

        {/* by model */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase"}}>모델별</div>
        <div style={{marginBottom:14,display:"flex",flexDirection:"column",gap:4}}>
          {Object.entries(u.by_model).map(([m,v]) => (
            <div key={m} style={{
              display:"grid",gridTemplateColumns:"1fr 80px 100px 100px",gap:8,
              padding:"6px 10px",background:"var(--navy-darkest)",
              border:"1px solid var(--navy-light)",borderRadius:"var(--radius)",fontSize:11,
            }}>
              <span style={{fontFamily:"'JetBrains Mono',monospace",color:"var(--gray-300)"}}>
                {m.split(".").slice(-1)[0]}
              </span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace"}}>{v.calls}</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace"}}>{(v.tokens/1000).toFixed(1)}k</span>
              <span style={{textAlign:"right",fontFamily:"'JetBrains Mono',monospace",color:"var(--amber-light)"}}>${v.cost.toFixed(4)}</span>
            </div>
          ))}
        </div>

        {/* by day */}
        <div style={{fontSize:11,color:"var(--gray-400)",marginBottom:6,textTransform:"uppercase"}}>일자별 추세 (최근 14일)</div>
        <DailyChart byDay={u.by_day}/>
      </div>
    </div>
  );
}

function DailyChart({ byDay }: { byDay: Record<string,{calls:number;tokens:number;cost:number}> }) {
  const days = Object.entries(byDay).sort((a,b) => a[0].localeCompare(b[0])).slice(-14);
  if (!days.length) return <div style={{fontSize:11,color:"var(--gray-500)"}}>데이터가 없습니다.</div>;
  const max = Math.max(...days.map(d => d[1].cost));
  return (
    <div style={{display:"flex",alignItems:"flex-end",gap:4,height:80,padding:8,background:"var(--navy-darkest)",borderRadius:"var(--radius)"}}>
      {days.map(([d,v]) => (
        <div key={d} style={{flex:1,display:"flex",flexDirection:"column",alignItems:"center",gap:2}}>
          <div style={{
            width:"100%",height:`${(v.cost/max)*60+2}px`,
            background:"var(--amber)",borderRadius:"2px 2px 0 0",
          }} title={`${d}: $${v.cost.toFixed(4)}`}/>
          <span style={{fontSize:8,color:"var(--gray-600)",fontFamily:"'JetBrains Mono',monospace",transform:"rotate(-45deg)",transformOrigin:"center",marginTop:4}}>
            {d.slice(5)}
          </span>
        </div>
      ))}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{fontSize:10,color:"var(--gray-500)",textTransform:"uppercase",marginBottom:2}}>{label}</div>
      <div style={{fontSize:12,color:"var(--gray-200)",fontFamily:"'JetBrains Mono',monospace"}}>{value}</div>
    </div>
  );
}
