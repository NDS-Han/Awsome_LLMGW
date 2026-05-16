import { useState } from "react";
import { Shield, PlayCircle, ArrowRightLeft, TrendingUp, Zap, Search, Lightbulb, CheckCircle2, RotateCcw, ChevronDown, ChevronRight, AlertTriangle, Loader2 } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  AreaChart,
  Area,
} from "recharts";
import { EvalEntry, EvalResult, TurnEvalResult, TurnEvalScore, ImprovementState, EvalAnalysis } from "../types";

interface Props {
  evalHistory: EvalEntry[];
  promptVersion: string;
  onSwitchPrompt: (version: string) => void;
  onRunEval: () => void;
  isEvalRunning?: boolean;
  turnEvals: Record<string, TurnEvalResult>;
  turnEvalOrder: string[];
  improvementState: ImprovementState;
  onApplyImprovement: () => void;
  onResetImprovement: () => void;
  evalAnalysis: EvalAnalysis | null;
  compact?: boolean;
}

type SubTab = "overview" | "analysis" | "deepdive";

function scoreColor(score: number): string {
  if (score >= 0.8) return "var(--green-light)";
  if (score >= 0.6) return "var(--amber)";
  return "var(--red-light)";
}

function scoreBarColor(score: number): string {
  if (score >= 0.8) return "#6aaf35";
  if (score >= 0.6) return "#ff9900";
  return "#e74c3c";
}

function scoreClass(score: number): string {
  if (score >= 0.8) return "high";
  if (score >= 0.6) return "medium";
  return "low";
}

const TOOL_COLORS: Record<string, string> = {
  query_sales_data: "#ff9900",
  analyze_reviews: "#0073bb",
  check_delivery_performance: "#6aaf35",
  get_seller_metrics: "#44b9d6",
  text2sql_query: "#8b5cf6",
  delegate_to_specialist: "#ec4899",
};

const CATEGORY_COLORS: Record<string, string> = {
  sales: "#ff9900",
  reviews: "#0073bb",
  delivery: "#6aaf35",
  sellers: "#44b9d6",
  general: "#6b7280",
};

// --- Turn Detail (Analysis tab) ---

function TurnDetailRow({ turn, index }: { turn: TurnEvalResult; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showResponse, setShowResponse] = useState(false);

  return (
    <div style={{ marginBottom: 6, border: "1px solid var(--navy-light)", borderRadius: "var(--radius)", overflow: "hidden" }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", cursor: "pointer", background: "rgba(255,255,255,0.02)" }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span style={{ fontSize: 11, color: "var(--gray-300)", width: 24 }}>#{index + 1}</span>
        <span className={`eval-score ${scoreClass(turn.avg_score)}`} style={{ fontSize: 11 }}>
          {(turn.avg_score * 100).toFixed(0)}%
        </span>
        {turn.category && (
          <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: CATEGORY_COLORS[turn.category] || "#6b7280", color: "#fff", fontWeight: 500 }}>
            {turn.category}
          </span>
        )}
        <span style={{ fontSize: 10, color: "var(--gray-500)", marginLeft: "auto" }}>
          {turn.prompt_version.toUpperCase()}
        </span>
      </div>
      {expanded && (
        <div style={{ padding: "8px 10px", borderTop: "1px solid var(--navy-light)" }}>
          {/* Collapsible prompt */}
          {turn.prompt && (
            <div style={{ marginBottom: 6 }}>
              <div
                onClick={() => setShowPrompt(!showPrompt)}
                style={{ fontSize: 10, color: "var(--gray-500)", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}
              >
                {showPrompt ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                Prompt
              </div>
              {showPrompt && (
                <div style={{ fontSize: 11, color: "var(--gray-300)", padding: "4px 8px", background: "var(--navy-light)", borderRadius: 4, whiteSpace: "pre-wrap", maxHeight: 120, overflow: "auto" }}>
                  {turn.prompt}
                </div>
              )}
            </div>
          )}

          {/* Collapsible response */}
          {turn.response && (
            <div style={{ marginBottom: 8 }}>
              <div
                onClick={() => setShowResponse(!showResponse)}
                style={{ fontSize: 10, color: "var(--gray-500)", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}
              >
                {showResponse ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                Response
              </div>
              {showResponse && (
                <div style={{ fontSize: 11, color: "var(--gray-300)", padding: "4px 8px", background: "var(--navy-light)", borderRadius: 4, whiteSpace: "pre-wrap", maxHeight: 150, overflow: "auto" }}>
                  {turn.response}
                </div>
              )}
            </div>
          )}

          {/* Per-evaluator scores + explanation */}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {turn.scores.map((s: TurnEvalScore) => (
              <div key={s.evaluator} style={{ padding: "4px 8px", background: "rgba(255,255,255,0.02)", borderRadius: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ color: "var(--gray-400)", flex: 1 }}>{s.evaluator.replace("Builtin.", "")}</span>
                  <span style={{ color: scoreBarColor(s.score), fontWeight: 600 }}>{(s.score * 100).toFixed(0)}%</span>
                  {s.eval_source === "custom" && (
                    <span style={{ fontSize: 9, padding: "0 4px", borderRadius: 3, background: "rgba(139,92,246,0.2)", color: "#8b5cf6" }}>custom</span>
                  )}
                </div>
                {s.explanation && (
                  <div style={{ fontSize: 10, color: "var(--gray-500)", marginTop: 2, lineHeight: 1.4 }}>
                    {s.explanation}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --- Sub-components ---

function EvalResultRow({ result }: { result: EvalResult }) {
  const displayName = result.evaluator.replace("Builtin.", "");
  return (
    <div className="eval-row">
      <div className="eval-row-header">
        <span className="eval-name">{displayName}</span>
        <span className={`eval-score ${scoreClass(result.score)}`}>
          {(result.score * 100).toFixed(1)}%
        </span>
      </div>
      <div className="eval-bar-bg">
        <div
          className="eval-bar-fill"
          style={{
            width: `${result.score * 100}%`,
            background: scoreColor(result.score),
          }}
        />
      </div>
      <div className="eval-explanation">{result.explanation}</div>
    </div>
  );
}

const PIPELINE_STAGES = [
  { key: "evaluate", label: "평가", icon: Zap },
  { key: "analyze", label: "분석", icon: Search },
  { key: "suggest", label: "제안", icon: Lightbulb },
  { key: "apply", label: "적용", icon: CheckCircle2 },
];

function stageIndex(status: string): number {
  switch (status) {
    case "idle": return 0;
    case "analyzing": return 1;
    case "ready": return 2;
    case "applied": return 3;
    default: return 0;
  }
}

function ImprovementPipeline({
  state,
  onApply,
  onReset,
}: {
  state: ImprovementState;
  onApply: () => void;
  onReset: () => void;
}) {
  const idx = stageIndex(state.status);

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
        <TrendingUp size={12} />
        프롬프트 개선 파이프라인
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 8 }}>
        {PIPELINE_STAGES.map((stage, i) => {
          const Icon = stage.icon;
          const active = i <= idx;
          const current = i === idx;
          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <div
                style={{
                  display: "flex", alignItems: "center", gap: 4, padding: "3px 8px",
                  borderRadius: 4, fontSize: 10, fontWeight: current ? 600 : 400,
                  background: active ? "rgba(106, 175, 53, 0.15)" : "var(--navy-light)",
                  color: active ? "var(--green-light)" : "var(--gray-500)",
                  border: current ? "1px solid rgba(106, 175, 53, 0.4)" : "1px solid transparent",
                }}
              >
                <Icon size={10} />
                {stage.label}
              </div>
              {i < PIPELINE_STAGES.length - 1 && (
                <div style={{ width: 12, height: 1, background: active ? "var(--green-light)" : "var(--gray-600)" }} />
              )}
            </div>
          );
        })}
      </div>

      {state.status === "ready" && state.suggestion && (
        <div style={{ padding: "8px 12px", background: "rgba(255, 153, 0, 0.08)", border: "1px solid rgba(255, 153, 0, 0.3)", borderRadius: "var(--radius)", marginBottom: 8 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--amber)", marginBottom: 6 }}>
            제안: {state.suggestion.suggested_version.toUpperCase()}로 전환 (예상 변화 {state.suggestion.expected_delta})
          </div>
          <div style={{ fontSize: 10, color: "var(--gray-400)", marginBottom: 6 }}>{state.suggestion.reason}</div>
          <table style={{ width: "100%", fontSize: 10, borderCollapse: "collapse" }}>
            <thead><tr style={{ color: "var(--gray-500)" }}><th style={{ textAlign: "left", padding: "2px 4px" }}>항목</th><th style={{ textAlign: "left", padding: "2px 4px" }}>이전</th><th style={{ textAlign: "left", padding: "2px 4px" }}>이후</th></tr></thead>
            <tbody>
              {state.suggestion.changes.map((c) => (
                <tr key={c.aspect} style={{ color: "var(--gray-300)" }}>
                  <td style={{ padding: "2px 4px", fontWeight: 500 }}>{c.aspect}</td>
                  <td style={{ padding: "2px 4px", color: "var(--red-light)" }}>{c.before}</td>
                  <td style={{ padding: "2px 4px", color: "var(--green-light)" }}>{c.after}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={onApply}>개선 적용</button>
            <button className="btn btn-sm" onClick={onReset} style={{ opacity: 0.7 }}><RotateCcw size={10} /> 초기화</button>
          </div>
        </div>
      )}

      {state.status === "applied" && (
        <div style={{ padding: "6px 10px", background: "rgba(106, 175, 53, 0.1)", border: "1px solid rgba(106, 175, 53, 0.3)", borderRadius: "var(--radius)", fontSize: 11, color: "var(--green-light)", display: "flex", alignItems: "center", gap: 8 }}>
          <CheckCircle2 size={12} />
          <span>개선이 적용되었습니다. 이전: {((state.before_score || 0) * 100).toFixed(0)}%</span>
          {state.after_score != null && (
            <span style={{ fontWeight: 600 }}>
              → 이후: {(state.after_score * 100).toFixed(0)}%
              {" "}(+{((state.after_score - (state.before_score || 0)) * 100).toFixed(0)}%)
            </span>
          )}
          <button className="btn btn-sm" onClick={onReset} style={{ marginLeft: "auto", opacity: 0.7, fontSize: 10 }}><RotateCcw size={10} /></button>
        </div>
      )}
    </div>
  );
}

function TurnTrendChart({ turnEvalOrder, turnEvals }: { turnEvalOrder: string[]; turnEvals: Record<string, TurnEvalResult> }) {
  const chartData = turnEvalOrder
    .map((tid, i) => {
      const ev = turnEvals[tid];
      if (!ev) return null;
      return { name: `T${i + 1}`, score: Math.round(ev.avg_score * 100), version: ev.prompt_version, raw: ev.avg_score };
    })
    .filter(Boolean) as { name: string; score: number; version: string; raw: number }[];

  if (chartData.length === 0) return null;

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>턴별 평가 추세</div>
      <ResponsiveContainer width="100%" height={100}>
        <BarChart data={chartData} barCategoryGap="20%">
          <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#999" }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#999" }} axisLine={false} tickLine={false} width={30} />
          <Tooltip
            contentStyle={{ background: "#1a2332", border: "1px solid #2a3a4a", borderRadius: 6, fontSize: 11 }}
            formatter={(value: number, _name: string, props: any) => [`${value}% (${props.payload.version})`, "Score"]}
          />
          <Bar dataKey="score" radius={[3, 3, 0, 0]}>
            {chartData.map((entry, i) => (
              <Cell key={i} fill={scoreBarColor(entry.raw)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- Analysis Tab ---

function CategoryScoreChart({ analysis }: { analysis: EvalAnalysis }) {
  const data = Object.entries(analysis.by_category).map(([cat, d]) => ({
    name: cat.charAt(0).toUpperCase() + cat.slice(1),
    score: Math.round(d.avg_score * 100),
    count: d.count,
    raw: d.avg_score,
    color: CATEGORY_COLORS[cat] || "#6b7280",
  })).sort((a, b) => b.score - a.score);

  if (data.length === 0) return <div style={{ fontSize: 11, color: "var(--gray-500)", padding: 8 }}>아직 카테고리 데이터가 없습니다.</div>;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>질문 카테고리별 점수</div>
      <ResponsiveContainer width="100%" height={Math.max(80, data.length * 32)}>
        <BarChart data={data} layout="vertical" barCategoryGap="25%" margin={{ left: 0, right: 8 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: "#999" }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "#bbb" }} axisLine={false} tickLine={false} width={70} />
          <Tooltip
            contentStyle={{ background: "#1a2332", border: "1px solid #2a3a4a", borderRadius: 6, fontSize: 11 }}
            formatter={(value: number, _: string, props: any) => [`${value}% (${props.payload.count}턴)`, "평균 점수"]}
          />
          <Bar dataKey="score" radius={[0, 3, 3, 0]}>
            {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EvaluatorLeaderboard({ analysis }: { analysis: EvalAnalysis }) {
  const evaluators = Object.entries(analysis.by_evaluator)
    .map(([name, d]) => ({ name: name.replace("Builtin.", ""), avg_score: d.avg_score, trend: d.trend, count: d.count }))
    .sort((a, b) => a.avg_score - b.avg_score);

  if (evaluators.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>평가기 순위 (낮은 순)</div>
      {evaluators.map((ev) => (
        <div key={ev.name} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: "var(--gray-300)", width: 130, flexShrink: 0 }}>{ev.name}</span>
          <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 80, height: 4, background: "var(--navy-light)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ width: `${ev.avg_score * 100}%`, height: "100%", background: scoreBarColor(ev.avg_score), borderRadius: 2 }} />
            </div>
            {ev.trend.length > 1 && (
              <div style={{ width: 60, height: 24 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={ev.trend.slice(-10).map((v, i) => ({ i, v: Math.round(v * 100) }))}>
                    <Area type="monotone" dataKey="v" stroke={scoreBarColor(ev.avg_score)} fill={scoreBarColor(ev.avg_score)} fillOpacity={0.2} strokeWidth={1} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
          <span className={`eval-score ${scoreClass(ev.avg_score)}`} style={{ fontSize: 11, minWidth: 40, textAlign: "right" }}>
            {(ev.avg_score * 100).toFixed(0)}%
          </span>
        </div>
      ))}
    </div>
  );
}

function TimeTrendChart({ analysis }: { analysis: EvalAnalysis }) {
  const data = analysis.time_trend.map((t, i) => ({
    name: `T${i + 1}`,
    score: Math.round(t.avg_score * 100),
    version: t.prompt_version,
    category: t.category,
  }));

  if (data.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
        시간별 점수 추세
        {analysis.summary.improving && (
          <span style={{ color: "var(--green-light)", fontSize: 10 }}>
            ↑ +{(analysis.summary.delta * 100).toFixed(1)}%
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={80}>
        <AreaChart data={data}>
          <XAxis dataKey="name" tick={{ fontSize: 9, fill: "#999" }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: "#999" }} axisLine={false} tickLine={false} width={25} />
          <Tooltip
            contentStyle={{ background: "#1a2332", border: "1px solid #2a3a4a", borderRadius: 6, fontSize: 11 }}
            formatter={(value: number, _: string, props: any) => [`${value}% (${props.payload.version}, ${props.payload.category})`, "Score"]}
          />
          <defs>
            <linearGradient id="evalTrendGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6aaf35" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#6aaf35" stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="score" stroke="#6aaf35" fill="url(#evalTrendGrad)" strokeWidth={1.5} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ToolCorrelationChart({ analysis }: { analysis: EvalAnalysis }) {
  const data = Object.entries(analysis.tool_correlation)
    .map(([tool, d]) => ({
      name: tool.replace(/_/g, " "),
      tool,
      score: Math.round(d.avg_score_when_used * 100),
      calls: d.call_count,
      raw: d.avg_score_when_used,
    }))
    .sort((a, b) => b.score - a.score);

  if (data.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>사용된 Tool별 평가 점수</div>
      <ResponsiveContainer width="100%" height={Math.max(80, data.length * 28)}>
        <BarChart data={data} layout="vertical" barCategoryGap="25%" margin={{ left: 0, right: 8 }}>
          <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: "#999" }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: "#bbb" }} axisLine={false} tickLine={false} width={100} />
          <Tooltip
            contentStyle={{ background: "#1a2332", border: "1px solid #2a3a4a", borderRadius: 6, fontSize: 11 }}
            formatter={(value: number, _: string, props: any) => [`${value}% (${props.payload.calls}회 호출)`, "평균 점수"]}
          />
          <Bar dataKey="score" radius={[0, 3, 3, 0]}>
            {data.map((entry, i) => <Cell key={i} fill={TOOL_COLORS[entry.tool] || "#6b7280"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- Deep Dive Tab ---

function LowScoreRow({ turn, index }: { turn: any; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{ marginBottom: 8, border: "1px solid var(--navy-light)", borderRadius: "var(--radius)", overflow: "hidden" }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", cursor: "pointer", background: "rgba(231, 76, 60, 0.05)" }}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span style={{ fontSize: 11, color: "var(--gray-300)", width: 24 }}>#{index + 1}</span>
        <span className={`eval-score ${scoreClass(turn.avg_score)}`} style={{ fontSize: 11 }}>
          {(turn.avg_score * 100).toFixed(0)}%
        </span>
        <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: CATEGORY_COLORS[turn.category] || "#6b7280", color: "#fff", fontWeight: 500 }}>
          {turn.category}
        </span>
        {turn.weakest_evaluator && (
          <span style={{ fontSize: 10, color: "var(--red-light)", marginLeft: "auto" }}>
            취약 항목: {turn.weakest_evaluator.replace("Builtin.", "")}
          </span>
        )}
      </div>
      {expanded && (
        <div style={{ padding: "8px 10px", borderTop: "1px solid var(--navy-light)" }}>
          <div style={{ fontSize: 10, color: "var(--gray-500)", marginBottom: 4 }}>프롬프트:</div>
          <div style={{ fontSize: 11, color: "var(--gray-300)", marginBottom: 8, padding: "4px 8px", background: "var(--navy-light)", borderRadius: 4 }}>
            {turn.prompt}
          </div>
          <div style={{ fontSize: 10, color: "var(--gray-500)", marginBottom: 4 }}>응답 (일부):</div>
          <div style={{ fontSize: 11, color: "var(--gray-300)", marginBottom: 8, padding: "4px 8px", background: "var(--navy-light)", borderRadius: 4, maxHeight: 100, overflow: "auto" }}>
            {turn.response}
          </div>
          {turn.tools_used.length > 0 && (
            <div style={{ fontSize: 10, color: "var(--gray-500)", marginBottom: 6 }}>
              사용된 Tool: {turn.tools_used.map((t: string) => (
                <span key={t} style={{ padding: "1px 5px", borderRadius: 3, background: TOOL_COLORS[t] || "#6b7280", color: "#fff", marginRight: 4, fontSize: 9 }}>{t}</span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
            {turn.scores.map((s: any) => (
              <div key={s.evaluator}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
                  <span style={{ color: "var(--gray-400)" }}>{s.evaluator.replace("Builtin.", "")}</span>
                  <span style={{ color: scoreBarColor(s.score), fontWeight: 600 }}>{(s.score * 100).toFixed(0)}%</span>
                </div>
                {s.explanation && (
                  <div style={{ fontSize: 9, color: "var(--gray-500)", marginTop: 1, marginLeft: 4, lineHeight: 1.3 }}>
                    {s.explanation}
                  </div>
                )}
              </div>
            ))}
          </div>
          {turn.analysis && (
            <div style={{ padding: "6px 8px", background: "rgba(255, 153, 0, 0.08)", border: "1px solid rgba(255, 153, 0, 0.2)", borderRadius: 4 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "var(--amber)", marginBottom: 4, display: "flex", alignItems: "center", gap: 4 }}>
                <Lightbulb size={10} /> 점수가 낮은 이유
              </div>
              <div style={{ fontSize: 10, color: "var(--gray-300)", marginBottom: 4 }}>{turn.analysis.summary}</div>
              {turn.analysis.recommendations.length > 0 && (
                <div style={{ fontSize: 10, color: "var(--gray-400)" }}>
                  {turn.analysis.recommendations.map((r: string, i: number) => (
                    <div key={i} style={{ marginBottom: 2 }}>• {r}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HeatmapGrid({ analysis }: { analysis: EvalAnalysis }) {
  const categories = Object.keys(analysis.by_category);
  const evaluators = [...new Set(
    Object.values(analysis.by_category).flatMap(c => Object.keys(c.evaluator_scores))
  )].map(e => e.replace("Builtin.", ""));

  const evaluatorsFull = [...new Set(
    Object.values(analysis.by_category).flatMap(c => Object.keys(c.evaluator_scores))
  )];

  if (categories.length === 0 || evaluators.length === 0) return null;

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 6 }}>평가기 × 카테고리 히트맵</div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ fontSize: 10, borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: "3px 6px", color: "var(--gray-500)" }}></th>
              {categories.map(c => (
                <th key={c} style={{ textAlign: "center", padding: "3px 6px", color: CATEGORY_COLORS[c] || "var(--gray-400)", fontWeight: 500 }}>
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {evaluators.map((ev, i) => (
              <tr key={ev}>
                <td style={{ padding: "3px 6px", color: "var(--gray-400)", whiteSpace: "nowrap" }}>{ev}</td>
                {categories.map(cat => {
                  const score = analysis.by_category[cat]?.evaluator_scores[evaluatorsFull[i]] ?? null;
                  if (score === null) return <td key={cat} style={{ textAlign: "center", padding: "3px 6px", color: "var(--gray-600)" }}>—</td>;
                  const bg = score >= 0.8
                    ? `rgba(106, 175, 53, ${score * 0.4})`
                    : score >= 0.6
                    ? `rgba(255, 153, 0, ${score * 0.3})`
                    : `rgba(231, 76, 60, ${(1 - score) * 0.4})`;
                  return (
                    <td key={cat} style={{ textAlign: "center", padding: "3px 6px", background: bg, borderRadius: 2, color: "#fff", fontWeight: 500 }}>
                      {(score * 100).toFixed(0)}%
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- Main Component ---

export default function EvalPanel({
  evalHistory,
  promptVersion,
  onSwitchPrompt,
  onRunEval,
  isEvalRunning,
  turnEvals,
  turnEvalOrder,
  improvementState,
  onApplyImprovement,
  onResetImprovement,
  evalAnalysis,
  compact,
}: Props) {
  const [subTab, setSubTab] = useState<SubTab>("overview");

  const latestEval = evalHistory[evalHistory.length - 1] || null;
  const v1Evals = evalHistory.filter((e) => e.prompt_version === "v1");
  const v2Evals = evalHistory.filter((e) => e.prompt_version === "v2");
  const v3Evals = evalHistory.filter((e) => e.prompt_version === "v3");
  const latestV1 = v1Evals[v1Evals.length - 1] || null;
  const latestV2 = v2Evals[v2Evals.length - 1] || null;
  const latestV3 = v3Evals[v3Evals.length - 1] || null;
  const hasComparison = (latestV1 && latestV2) || (latestV2 && latestV3);

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <Shield size={14} />
          평가
          {evalAnalysis?.custom_evaluator?.registered && (
            <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "rgba(139, 92, 246, 0.2)", color: "#8b5cf6", marginLeft: 6 }}>
              +커스텀
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
            배치 {evalHistory.length}회 · 온라인 {turnEvalOrder.length}회
          </span>
        </div>
      </div>

      {/* Sub-tab navigation */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid var(--navy-light)", padding: "0 12px" }}>
        {([["overview", "종합"], ["analysis", "분석"], ["deepdive", "심층 분석"]] as [SubTab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setSubTab(key)}
            style={{
              padding: "6px 12px", fontSize: 11, fontWeight: subTab === key ? 600 : 400, cursor: "pointer",
              background: "transparent", border: "none",
              color: subTab === key ? "var(--green-light)" : "var(--gray-400)",
              borderBottom: subTab === key ? "2px solid var(--green-light)" : "2px solid transparent",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {/* ===== OVERVIEW TAB ===== */}
        {subTab === "overview" && (
          <>
            {/* Controls */}
            <div className="eval-controls">
              <div className="eval-version-toggle">
                {["v1", "v2", "v3"].map((v) => (
                  <button
                    key={v}
                    className={`eval-version-btn ${promptVersion === v ? "active" : ""}`}
                    onClick={() => onSwitchPrompt(v)}
                  >
                    {v.toUpperCase()} {v === "v1" ? "기본" : v === "v2" ? "개선" : "최적화"}
                  </button>
                ))}
              </div>
              <button className="btn btn-primary btn-sm" onClick={onRunEval} disabled={isEvalRunning}>
                {isEvalRunning ? <Loader2 size={12} className="spin" /> : <PlayCircle size={12} />}
                {isEvalRunning ? "실행 중…" : "평가 실행"}
              </button>
            </div>
            {isEvalRunning && (
              <div style={{ fontSize: 11, color: "var(--gray-500)", padding: "4px 0" }}>
                CloudWatch에서 span을 가져와 평가기를 실행 중입니다…
              </div>
            )}

            <TurnTrendChart turnEvalOrder={turnEvalOrder} turnEvals={turnEvals} />
            <ImprovementPipeline state={improvementState} onApply={onApplyImprovement} onReset={onResetImprovement} />

            {!latestEval ? (
              <div className="empty-state" style={{ minHeight: compact ? 80 : 100 }}>
                <Shield size={24} />
                <p>아직 배치 평가가 없습니다</p>
                <p className="empty-hint">채팅 후에는 온라인 평가가 자동으로 실행됩니다</p>
              </div>
            ) : hasComparison && !compact ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, marginTop: 10 }}>
                  <ArrowRightLeft size={14} style={{ color: "var(--amber)" }} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--gray-200)" }}>버전 비교</span>
                </div>
                <div className="eval-comparison">
                  {latestV1 && (
                    <div className="eval-version-col">
                      <div className="eval-version-label v1">V1 기본</div>
                      {latestV1.results.map((r) => <CompactScore key={r.evaluator} result={r} />)}
                    </div>
                  )}
                  {latestV2 && (
                    <div className="eval-version-col">
                      <div className="eval-version-label v2">V2 개선</div>
                      {latestV2.results.map((r) => <CompactScore key={r.evaluator} result={r} />)}
                    </div>
                  )}
                  {latestV3 && (
                    <div className="eval-version-col">
                      <div className="eval-version-label v3">V3 최적화</div>
                      {latestV3.results.map((r) => <CompactScore key={r.evaluator} result={r} />)}
                    </div>
                  )}
                </div>
                {latestV1 && latestV2 && (
                  <div style={{ marginTop: 12, padding: "8px 12px", background: "rgba(106, 175, 53, 0.1)", border: "1px solid rgba(106, 175, 53, 0.3)", borderRadius: "var(--radius)" }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "var(--green-light)", marginBottom: 4 }}>개선 요약</div>
                    {latestV1.results.map((v1r) => {
                      const latest = latestV3 || latestV2;
                      const cmp = latest!.results.find((r) => r.evaluator === v1r.evaluator);
                      if (!cmp) return null;
                      const delta = cmp.score - v1r.score;
                      return (
                        <div key={v1r.evaluator} style={{ fontSize: 11, color: "var(--gray-300)", display: "flex", gap: 8 }}>
                          <span style={{ flex: 1 }}>{v1r.evaluator.replace("Builtin.", "")}</span>
                          <span style={{ color: delta > 0 ? "var(--green-light)" : "var(--red-light)" }}>
                            {delta > 0 ? "+" : ""}{(delta * 100).toFixed(1)}%
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            ) : (
              <div className="eval-results">
                <div style={{ fontSize: 11, color: "var(--gray-500)", marginBottom: 4 }}>
                  {latestEval.prompt_version.toUpperCase()} — {new Date(latestEval.timestamp).toLocaleTimeString()}
                </div>
                {latestEval.results.map((r) => <EvalResultRow key={r.evaluator} result={r} />)}
              </div>
            )}
          </>
        )}

        {/* ===== ANALYSIS TAB ===== */}
        {subTab === "analysis" && (
          <>
            {!evalAnalysis || evalAnalysis.summary.total_turns === 0 ? (
              <div className="empty-state" style={{ minHeight: 100 }}>
                <TrendingUp size={24} />
                <p>분석할 데이터가 없습니다</p>
                <p className="empty-hint">채팅 메시지를 보내면 매 턴마다 온라인 평가가 실행됩니다</p>
              </div>
            ) : (
              <>
                {/* Summary banner */}
                <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
                  <div style={{ flex: 1, padding: "6px 10px", background: "var(--navy-light)", borderRadius: "var(--radius)", textAlign: "center" }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: evalAnalysis.summary.improving ? "var(--green-light)" : "var(--amber)" }}>
                      {evalAnalysis.summary.total_turns}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--gray-500)" }}>평가된 턴 수</div>
                  </div>
                  <div style={{ flex: 1, padding: "6px 10px", background: "var(--navy-light)", borderRadius: "var(--radius)", textAlign: "center" }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: evalAnalysis.summary.improving ? "var(--green-light)" : "var(--gray-300)" }}>
                      {evalAnalysis.summary.improving ? "↑" : "→"}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--gray-500)" }}>
                      {evalAnalysis.summary.improving ? `상승 중 (+${(evalAnalysis.summary.delta * 100).toFixed(1)}%)` : "안정적"}
                    </div>
                  </div>
                  <div style={{ flex: 1, padding: "6px 10px", background: "var(--navy-light)", borderRadius: "var(--radius)", textAlign: "center" }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: "var(--gray-300)" }}>
                      {Object.keys(analysis_categories(evalAnalysis)).length}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--gray-500)" }}>카테고리 수</div>
                  </div>
                </div>

                <CategoryScoreChart analysis={evalAnalysis} />
                <EvaluatorLeaderboard analysis={evalAnalysis} />
                <TimeTrendChart analysis={evalAnalysis} />
                <ToolCorrelationChart analysis={evalAnalysis} />

                {/* Turn-by-Turn Results */}
                {turnEvalOrder.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                      <Search size={12} />
                      턴별 결과 ({turnEvalOrder.length}개)
                    </div>
                    {turnEvalOrder.map((tid, i) => {
                      const ev = turnEvals[tid];
                      if (!ev) return null;
                      return <TurnDetailRow key={tid} turn={ev} index={i} />;
                    })}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* ===== DEEP DIVE TAB ===== */}
        {subTab === "deepdive" && (
          <>
            {!evalAnalysis || evalAnalysis.low_score_turns.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 100 }}>
                <AlertTriangle size={24} />
                <p>저점수 턴이 아직 없습니다</p>
                <p className="empty-hint">65% 미만 턴이 분석과 함께 여기 표시됩니다</p>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                  <AlertTriangle size={12} style={{ color: "var(--red-light)" }} />
                  저점수 턴 {evalAnalysis.low_score_turns.length}개 (65% 미만)
                </div>

                {evalAnalysis.low_score_turns.map((turn, i) => (
                  <LowScoreRow key={turn.turn_id} turn={turn} index={i} />
                ))}

                <HeatmapGrid analysis={evalAnalysis} />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function analysis_categories(a: EvalAnalysis): Record<string, any> {
  return a.by_category;
}

function CompactScore({ result }: { result: EvalResult }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
      <span style={{ fontSize: 11, color: "var(--gray-400)", flex: 1 }}>
        {result.evaluator.replace("Builtin.", "")}
      </span>
      <div style={{ width: 60, height: 4, background: "var(--navy-light)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${result.score * 100}%`, height: "100%", background: scoreColor(result.score), borderRadius: 2 }} />
      </div>
      <span className={`eval-score ${scoreClass(result.score)}`} style={{ fontSize: 12, minWidth: 42, textAlign: "right" }}>
        {(result.score * 100).toFixed(0)}%
      </span>
    </div>
  );
}
