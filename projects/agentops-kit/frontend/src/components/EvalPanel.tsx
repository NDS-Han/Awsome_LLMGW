import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import {
  Shield, PlayCircle, Plus, Trash2, ToggleLeft, ToggleRight,
  RefreshCw, Loader2, CheckCircle2, AlertTriangle, Zap, Activity,
  ChevronDown, ChevronRight, Settings2, List, Layers, Clock, Hash, Percent,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import {
  Evaluator, OnlineEvalConfig, OnlineEvalResults, EvalResultEntry,
  BatchEvalSummary, BatchEvalDetail,
} from "../types";

interface Props {
  compact?: boolean;
}

type SubTab = "online" | "batch" | "evaluators";

function scoreColor(score: number): string {
  if (score >= 0.8) return "#6aaf35";
  if (score >= 0.6) return "#ff9900";
  return "#e74c3c";
}

function scoreLabel(score: number): string {
  if (score >= 0.9) return "Excellent";
  if (score >= 0.8) return "Very Good";
  if (score >= 0.6) return "Good";
  if (score >= 0.4) return "Fair";
  return "Poor";
}

function ScoreGauge({ score, size = 56 }: { score: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const filled = circumference * score;
  const color = scoreColor(score);

  return (
    <div className="eval-gauge">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(59, 80, 109, 0.4)" strokeWidth={4} />
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={`${filled} ${circumference}`} strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dasharray 0.6s ease" }} />
      </svg>
      <div className="eval-gauge__value" style={{ color }}>{(score * 100).toFixed(0)}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = status === "ACTIVE" || status === "ENABLED" ? "#6aaf35"
    : status === "CREATING" || status === "IN_PROGRESS" ? "#ff9900"
    : status === "DISABLED" ? "#6b7280"
    : "#e74c3c";
  return <span className="eval-status-badge" style={{ background: `${color}22`, color, borderColor: `${color}44` }}>{status}</span>;
}

// --- Online Config Card ---

function OnlineConfigCard({
  config, onToggle, onDelete,
}: {
  config: OnlineEvalConfig;
  onRefreshResults: (configId: string) => void;
  onToggle: (configId: string, enabled: boolean) => void;
  onDelete: (configId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [results, setResults] = useState<OnlineEvalResults | null>(null);
  const [loading, setLoading] = useState(false);
  const isEnabled = config.execution_status === "ENABLED";

  const fetchResults = async () => {
    setLoading(true);
    try {
      const data = await api.getOnlineResults(config.config_id, 24);
      setResults(data);
    } catch { /* ignore */ }
    setLoading(false);
  };

  const handleToggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !results) {
      fetchResults();
    }
  };

  return (
    <div className="eval-config-card">
      <div className="eval-config-card__header" onClick={handleToggle}>
        <div className="eval-config-card__left">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="eval-config-card__name">{config.config_name}</span>
          <StatusBadge status={config.execution_status} />
        </div>
        <div className="eval-config-card__right">
          <span className="eval-config-card__sampling">{config.sampling_rate}%</span>
          <button className="btn-icon" title={isEnabled ? "비활성화" : "활성화"}
            onClick={(e) => { e.stopPropagation(); onToggle(config.config_id, !isEnabled); }}>
            {isEnabled ? <ToggleRight size={16} style={{ color: "#6aaf35" }} /> : <ToggleLeft size={16} style={{ color: "#6b7280" }} />}
          </button>
          <button className="btn-icon" title="결과 새로고침" onClick={(e) => { e.stopPropagation(); fetchResults(); }}>
            <RefreshCw size={13} />
          </button>
          <button className="btn-icon btn-icon--danger" title="삭제" onClick={(e) => { e.stopPropagation(); onDelete(config.config_id); }}>
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      {expanded && (
        <div className="eval-config-card__body">
          <div className="eval-config-card__details">
            <div className="info-row">
              <span className="info-row__icon"><Shield size={10} /></span>
              <span className="info-row__label">평가기</span>
              <span style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                {config.evaluators.map(e => (
                  <span key={e} className="badge badge--info badge--mono">{e.replace("Builtin.", "")}</span>
                ))}
              </span>
            </div>
            <div className="info-row">
              <span className="info-row__icon"><Percent size={10} /></span>
              <span className="info-row__label">샘플링</span>
              <span className="info-row__value">{config.sampling_rate}%</span>
            </div>
            <div className="info-row">
              <span className="info-row__icon"><Clock size={10} /></span>
              <span className="info-row__label">생성</span>
              <span className="info-row__value">{config.created_at ? new Date(config.created_at).toLocaleString() : "—"}</span>
            </div>
          </div>
          {loading && (
            <div style={{ textAlign: "center", padding: 12 }}><Loader2 size={14} className="spin" /></div>
          )}
          {results && <ResultsView results={results} configName={config.config_name} />}
          {!loading && !results && (
            <div style={{ textAlign: "center", padding: 8, fontSize: 11, color: "var(--gray-500)" }}>
              결과를 불러오는 중...
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- Results View ---

function ResultsView({ results, configName }: { results: OnlineEvalResults; configName: string }) {
  if (results.error) {
    return <div className="eval-error">{results.error}</div>;
  }

  const { summary } = results;
  if (!summary || summary.count === 0) {
    return (
      <div className="empty-state" style={{ minHeight: 80 }}>
        <Activity size={20} />
        <p>아직 평가 결과가 없습니다</p>
        <p className="empty-hint">에이전트에 트래픽이 발생하면 자동으로 평가됩니다</p>
      </div>
    );
  }

  const evaluatorData = Object.entries(summary.by_evaluator).map(([id, d]) => ({
    name: id.replace("Builtin.", ""),
    avg: d.avg_score,
    count: d.count,
    min: d.min_score,
    max: d.max_score,
  })).sort((a, b) => a.avg - b.avg);


  return (
    <div className="eval-results-view">
      <div className="eval-results-view__header">
        <span>{configName} — 결과 요약</span>
        <span className="eval-results-view__count">{summary.count}건</span>
      </div>

      <div className="eval-summary-card">
        <div className="eval-summary-card__left">
          <ScoreGauge score={summary.avg_score} />
          <div className="eval-summary-card__info">
            <div className="eval-summary-card__label">{scoreLabel(summary.avg_score)}</div>
            <div className="eval-summary-card__meta">{summary.count}건 평가</div>
          </div>
        </div>
      </div>

      {evaluatorData.length > 0 && (
        <div className="eval-analysis-block">
          <div className="eval-analysis-block__title">평가기별 평균 점수</div>
          <div className="eval-batch-detail__cards">
            {evaluatorData.map(e => (
              <div key={e.name} className="eval-batch-detail__score-card">
                <div className="eval-batch-detail__score-card-name">{e.name}</div>
                <div className="eval-batch-detail__score-card-value" style={{ color: scoreColor(e.avg) }}>
                  {(e.avg * 100).toFixed(1)}%
                </div>
                <div className="eval-batch-detail__score-card-meta">
                  {e.count}건 평가
                </div>
                <div className="eval-batch-detail__score-card-range">
                  {(e.min * 100).toFixed(0)}% ~ {(e.max * 100).toFixed(0)}%
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(() => {
        // Group by session for trend chart
        const sessionMap = new Map<string, { scores: number[]; timestamp: string }>();
        for (const r of results.results) {
          const key = r.session_id || r.trace_id || "unknown";
          if (!sessionMap.has(key)) sessionMap.set(key, { scores: [], timestamp: r.timestamp || "" });
          if (r.score !== null) sessionMap.get(key)!.scores.push(r.score);
        }
        const trendData = [...sessionMap.entries()]
          .map(([id, { scores, timestamp }]) => ({
            session: id.slice(0, 6),
            avg: scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0,
            time: timestamp ? new Date(timestamp).toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "",
          }))
          .sort((a, b) => a.time.localeCompare(b.time));

        if (trendData.length < 2) return null;
        return (
          <div className="eval-analysis-block">
            <div className="eval-analysis-block__title">세션별 평균 점수 추세</div>
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={trendData} margin={{ top: 16, right: 8, left: 0, bottom: 20 }}>
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#c4cdd3" }} axisLine={false} tickLine={false} interval={0} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 10, fill: "#879596" }} axisLine={false} tickLine={false} width={32} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                <Tooltip
                  contentStyle={{ background: "rgba(20, 28, 44, 0.95)", border: "1px solid #3b506d", borderRadius: 6, fontSize: 12 }}
                  formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, "세션 평균"]}
                  labelFormatter={(time) => String(time)}
                />
                <Bar dataKey="avg" radius={[4, 4, 0, 0]} label={{ position: "top", fontSize: 11, fill: "#c4cdd3", formatter: (v: number) => `${(v * 100).toFixed(0)}%` }}>
                  {trendData.map((d, i) => <Cell key={i} fill={scoreColor(d.avg)} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })()}

      <OnlineResultsList results={results.results} />
    </div>
  );
}

function OnlineResultsList({ results }: { results: EvalResultEntry[] }) {
  if (!results || results.length === 0) return null;

  // Group by session/trace
  const grouped = new Map<string, EvalResultEntry[]>();
  for (const r of results) {
    const key = r.session_id || r.trace_id || "unknown";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(r);
  }
  // Sort groups by most recent timestamp
  const groups = [...grouped.entries()].sort((a, b) => {
    const tA = a[1][0]?.timestamp || "";
    const tB = b[1][0]?.timestamp || "";
    return tB.localeCompare(tA);
  });

  return (
    <div className="eval-batch-detail__results-section">
      <div className="eval-batch-detail__results-section-title">
        평가 결과 상세 ({groups.length}개 세션, {results.length}건)
      </div>
      <div className="eval-online-results-grouped">
        {groups.slice(0, 20).map(([sessionId, items]) => (
          <SessionResultGroup key={sessionId} sessionId={sessionId} items={items} />
        ))}
        {groups.length > 20 && (
          <div className="eval-batch-detail__more">외 {groups.length - 20}개 세션</div>
        )}
      </div>
    </div>
  );
}

function SessionResultGroup({ sessionId, items }: { sessionId: string; items: EvalResultEntry[] }) {
  const [open, setOpen] = useState(false);
  const avgScore = items.reduce((sum, r) => sum + (r.score ?? 0), 0) / items.length;
  const timestamp = items[0]?.timestamp;

  return (
    <div className="eval-session-group">
      <div className="eval-session-group__header" onClick={() => setOpen(!open)}>
        <div className="eval-session-group__left">
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="eval-session-group__id">{sessionId.slice(0, 12)}</span>
          <span className="eval-session-group__avg" style={{ color: scoreColor(avgScore) }}>
            평균 {(avgScore * 100).toFixed(0)}%
          </span>
          <span className="eval-session-group__count">{items.length}개 평가</span>
        </div>
        {timestamp && (
          <span className="eval-session-group__time">{new Date(timestamp).toLocaleString()}</span>
        )}
      </div>
      {open && (
        <div className="eval-session-group__body">
          {items.map((r, i) => (
            <div key={i} className="eval-online-result-item">
              <div className="eval-online-result-item__header">
                <span className="eval-online-result-item__evaluator">{r.evaluator_id.replace("Builtin.", "")}</span>
                <span style={{ color: scoreColor(r.score ?? 0), fontWeight: 600 }}>
                  {r.score !== null ? `${(r.score * 100).toFixed(0)}%` : "—"}
                </span>
                {r.label && <span className="eval-online-result-item__label">{r.label}</span>}
              </div>
              {r.explanation && (
                <div className="eval-online-result-item__explanation">{r.explanation}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Create Config Dialog ---

function CreateConfigForm({
  evaluators, onClose, onCreated,
}: {
  evaluators: Evaluator[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [samplingRate, setSamplingRate] = useState(100);
  const [selectedEvals, setSelectedEvals] = useState<string[]>([
    "Builtin.Helpfulness", "Builtin.Correctness", "Builtin.GoalSuccessRate",
  ]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleEval = (id: string) => {
    setSelectedEvals(prev => prev.includes(id) ? prev.filter(e => e !== id) : [...prev, id]);
  };

  const handleCreate = async () => {
    if (!name.trim()) { setError("이름을 입력하세요"); return; }
    if (selectedEvals.length === 0) { setError("평가기를 1개 이상 선택하세요"); return; }
    setCreating(true);
    setError(null);
    try {
      await api.createOnlineConfig({ name: name.trim(), evaluator_ids: selectedEvals, sampling_rate: samplingRate, description: description.trim() || undefined });
      onCreated();
      onClose();
    } catch (e: any) {
      setError(e.message || "생성 실패");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="eval-create-form">
      <div className="eval-create-form__title">
        <Settings2 size={13} /> 온라인 평가 설정 생성
      </div>
      <div className="eval-create-form__field">
        <label>이름</label>
        <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="e.g. production-eval" />
      </div>
      <div className="eval-create-form__field">
        <label>설명 (선택)</label>
        <input type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="설명" />
      </div>
      <div className="eval-create-form__field">
        <label>샘플링 비율: {samplingRate}%</label>
        <input type="range" min={1} max={100} value={samplingRate} onChange={e => setSamplingRate(Number(e.target.value))} />
      </div>
      <div className="eval-create-form__field">
        <label>평가기 선택</label>
        <div className="eval-create-form__evaluators">
          {evaluators.filter(e => e.status === "ACTIVE").map(ev => (
            <label key={ev.evaluator_id} className="eval-create-form__eval-item">
              <input type="checkbox" checked={selectedEvals.includes(ev.evaluator_id)} onChange={() => toggleEval(ev.evaluator_id)} />
              <span>{ev.name.replace("Builtin.", "")}</span>
            </label>
          ))}
        </div>
      </div>
      {error && <div className="eval-error">{error}</div>}
      <div className="eval-create-form__actions">
        <button className="btn btn-sm" onClick={onClose}>취소</button>
        <button className="btn btn-primary btn-sm" onClick={handleCreate} disabled={creating}>
          {creating ? <Loader2 size={12} className="spin" /> : <Plus size={12} />}
          생성
        </button>
      </div>
    </div>
  );
}

// --- Batch Eval Card (collapsible like OnlineConfigCard) ---

function BatchCard({ batch, onViewDetail }: { batch: BatchEvalSummary; onViewDetail: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<BatchEvalDetail | null>(null);
  const [loading, setLoading] = useState(false);

  const handleToggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail) {
      setLoading(true);
      try {
        const d = await api.getBatchEval(batch.batch_id);
        setDetail(d);
        onViewDetail(batch.batch_id);
      } catch { /* ignore */ }
      setLoading(false);
    }
  };

  return (
    <div className="eval-config-card">
      <div className="eval-config-card__header" onClick={handleToggle}>
        <div className="eval-config-card__left">
          {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <span className="eval-config-card__name">{batch.name || batch.batch_id.slice(0, 8)}</span>
          <StatusBadge status={batch.status} />
        </div>
        <div className="eval-config-card__right">
          <span style={{ fontSize: 11, color: "#9ca3af" }}>
            {batch.created_at ? new Date(batch.created_at).toLocaleString() : ""}
          </span>
        </div>
      </div>
      {expanded && (
        <div className="eval-config-card__body">
          {loading ? (
            <div style={{ textAlign: "center", padding: 12 }}><Loader2 size={14} className="spin" /></div>
          ) : detail ? (
            <BatchDetailBody detail={detail} />
          ) : null}
        </div>
      )}
    </div>
  );
}

function BatchDetailBody({ detail }: { detail: BatchEvalDetail }) {
  const [showResults, setShowResults] = useState(false);
  const total = detail.total_sessions;
  const progress = total > 0 ? ((detail.sessions_completed / total) * 100).toFixed(0) : "0";
  const byEvaluator = detail.results_summary?.by_evaluator;
  const isCompleted = detail.status === "COMPLETED";
  const isRunning = detail.status === "IN_PROGRESS" || detail.status === "STARTING";

  return (
    <>
      {/* Meta Info */}
      <div className="eval-batch-detail__meta">
        <span className="badge badge--neutral badge--mono"><Hash size={9} /> {detail.batch_id.slice(0, 12)}</span>
        <span className="badge badge--neutral"><Clock size={9} /> {detail.created_at ? new Date(detail.created_at).toLocaleString() : "—"}</span>
        <span className="badge badge--neutral"><Layers size={9} /> {total}개 세션</span>
      </div>

      {/* Progress */}
      <div className="eval-batch-detail__progress">
        <div className="eval-batch-detail__progress-bar">
          <div style={{ width: `${progress}%`, background: isCompleted ? "#6aaf35" : "#ff9900" }} />
        </div>
        <span>
          {isCompleted ? `${total}/${total} 완료` : `${detail.sessions_completed}/${total} (${progress}%)`}
        </span>
        {detail.sessions_failed > 0 && (
          <span style={{ color: "#e74c3c", marginLeft: 8 }}>
            <AlertTriangle size={11} /> {detail.sessions_failed} 실패
          </span>
        )}
        {isRunning && detail.sessions_in_progress > 0 && (
          <span style={{ color: "#ff9900", marginLeft: 8 }}>
            <Loader2 size={11} className="spin" /> {detail.sessions_in_progress} 진행 중
          </span>
        )}
      </div>

      {/* Evaluator Summary Cards */}
      {detail.evaluator_summaries.length > 0 && (
        <div className="eval-batch-detail__cards">
          {detail.evaluator_summaries.map(s => {
            const extra = byEvaluator?.[s.evaluator_id];
            return (
              <div key={s.evaluator_id} className="eval-batch-detail__score-card">
                <div className="eval-batch-detail__score-card-name">
                  {s.evaluator_id.replace("Builtin.", "")}
                </div>
                <div className="eval-batch-detail__score-card-value" style={{ color: scoreColor(s.average_score) }}>
                  {(s.average_score * 100).toFixed(1)}%
                </div>
                <div className="eval-batch-detail__score-card-meta">
                  {s.total_evaluated}건 평가{s.total_failed > 0 ? ` · ${s.total_failed} 실패` : ""}
                </div>
                {extra && (
                  <div className="eval-batch-detail__score-card-range">
                    {(extra.min_score * 100).toFixed(0)}% ~ {(extra.max_score * 100).toFixed(0)}%
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* No evaluator data yet */}
      {detail.evaluator_summaries.length === 0 && isRunning && (
        <div style={{ textAlign: "center", padding: 12, fontSize: 11, color: "var(--gray-500)" }}>
          <Loader2 size={14} className="spin" style={{ marginBottom: 4 }} /><br />
          평가 진행 중입니다...
        </div>
      )}

      {detail.evaluator_summaries.length === 0 && isCompleted && (
        <div style={{ textAlign: "center", padding: 12, fontSize: 11, color: "var(--gray-500)" }}>
          평가 결과가 없습니다
        </div>
      )}

      {/* Session Results (collapsible) */}
      {detail.results && detail.results.length > 0 && (
        <div className="eval-batch-detail__results-section">
          <div className="eval-batch-detail__results-toggle" onClick={() => setShowResults(!showResults)}>
            {showResults ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span>세션별 결과 ({detail.results.length}건)</span>
          </div>
          {showResults && (
            <div className="eval-batch-detail__result-list">
              {detail.results.slice(0, 30).map((r, i) => (
                <div key={i} className="eval-batch-detail__result-item">
                  <span className="eval-batch-detail__result-evaluator">{r.evaluator_id.replace("Builtin.", "")}</span>
                  <span style={{ color: scoreColor(r.score ?? 0), fontWeight: 600 }}>
                    {r.score !== null ? `${(r.score * 100).toFixed(0)}%` : "—"}
                  </span>
                  <span className="eval-batch-detail__result-session" title={r.session_id}>
                    {r.session_id?.slice(0, 8) || "—"}
                  </span>
                  {r.explanation && (
                    <span className="eval-batch-detail__result-explanation" title={r.explanation}>
                      {r.explanation.slice(0, 80)}{r.explanation.length > 80 ? "…" : ""}
                    </span>
                  )}
                </div>
              ))}
              {detail.results.length > 30 && (
                <div className="eval-batch-detail__more">외 {detail.results.length - 30}건</div>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

// --- Main Component ---

export default function EvalPanel({ compact }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("online");
  const [evaluators, setEvaluators] = useState<Evaluator[]>([]);
  const [configs, setConfigs] = useState<OnlineEvalConfig[]>([]);
  const [batches, setBatches] = useState<BatchEvalSummary[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(false);
  const [batchRunning, setBatchRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [evs, cfgs, bList] = await Promise.all([
        api.getEvaluators(),
        api.getOnlineConfigs(),
        api.listBatchEvals(),
      ]);
      setEvaluators(evs.evaluators || evs || []);
      setConfigs(cfgs.configs || cfgs || []);
      setBatches(bList.batches || bList || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);


  const handleToggle = async (configId: string, enabled: boolean) => {
    try {
      await api.updateOnlineConfig(configId, { enabled });
      loadData();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleDelete = async (configId: string) => {
    try {
      await api.deleteOnlineConfig(configId);
      loadData();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const hasInProgress = batches.some(b => b.status === "IN_PROGRESS" || b.status === "STARTING");

  const handleStartBatch = async () => {
    if (hasInProgress) {
      setError("진행 중인 배치 평가가 있습니다. 완료 후 다시 시도하세요.");
      return;
    }
    setBatchRunning(true);
    setError(null);
    try {
      const evalIds = evaluators.filter(e => e.status === "ACTIVE").slice(0, 6).map(e => e.evaluator_id);
      await api.startBatchEval({ name: `batch_${Date.now()}`, evaluator_ids: evalIds });
      loadData();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBatchRunning(false);
    }
  };


  const onlineCount = configs.length;
  const batchCount = batches.length;
  const evalCount = evaluators.length;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <Shield size={14} />
          평가 (AgentCore Evaluation)
        </div>
        <button className="btn-icon" title="새로고침" onClick={loadData}>
          <RefreshCw size={13} className={loading ? "spin" : ""} />
        </button>
      </div>

      <div className="eval-tabs">
        {([
          ["online", "온라인 평가", onlineCount],
          ["batch", "배치 평가", batchCount],
          ["evaluators", "평가기", evalCount],
        ] as [SubTab, string, number][]).map(([key, label, count]) => (
          <button key={key} onClick={() => setSubTab(key)}
            className={`eval-tabs__btn ${subTab === key ? "eval-tabs__btn--active" : ""}`}>
            {label}
            {count > 0 && <span className="eval-tabs__badge">{count}</span>}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {error && <div className="eval-error" onClick={() => setError(null)}>{error}</div>}

        {/* ===== ONLINE EVALUATION TAB ===== */}
        {subTab === "online" && (
          <>
            <div className="eval-controls">
              <span className="eval-controls__version">
                <Activity size={11} /> 실시간 자동 평가
              </span>
              <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
                <Plus size={12} /> 설정 추가
              </button>
            </div>

            {showCreate && (
              <CreateConfigForm
                evaluators={evaluators}
                onClose={() => setShowCreate(false)}
                onCreated={loadData}
              />
            )}

            {configs.length === 0 && !showCreate ? (
              <div className="empty-state" style={{ minHeight: compact ? 80 : 120 }}>
                <Zap size={24} />
                <p>온라인 평가 설정이 없습니다</p>
                <p className="empty-hint">
                  "설정 추가"를 눌러 AgentCore Online Evaluation Config를 생성하세요.<br/>
                  에이전트 트래픽이 자동으로 샘플링되어 평가됩니다.
                </p>
              </div>
            ) : (
              <div className="eval-configs-list">
                {configs.map(cfg => (
                  <OnlineConfigCard
                    key={cfg.config_id}
                    config={cfg}
                    onRefreshResults={() => {}}
                    onToggle={handleToggle}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}

          </>
        )}

        {/* ===== BATCH EVALUATION TAB ===== */}
        {subTab === "batch" && (
          <>
            <div className="eval-controls">
              <span className="eval-controls__version">
                <List size={11} /> 대량 세션 일괄 평가
              </span>
              <button className="btn btn-primary btn-sm" onClick={handleStartBatch} disabled={batchRunning || hasInProgress}>
                {batchRunning ? <Loader2 size={12} className="spin" /> : <PlayCircle size={12} />}
                {hasInProgress ? "진행 중..." : "배치 실행"}
              </button>
            </div>

            {batches.length === 0 ? (
              <div className="empty-state" style={{ minHeight: compact ? 80 : 100 }}>
                <Shield size={24} />
                <p>배치 평가 내역이 없습니다</p>
                <p className="empty-hint">"배치 실행"으로 CloudWatch 로그의 세션을 일괄 평가합니다</p>
              </div>
            ) : (
              <div className="eval-batch-list">
                {batches.map(b => (
                  <BatchCard key={b.batch_id} batch={b} onViewDetail={() => {}} />
                ))}
              </div>
            )}
          </>
        )}

        {/* ===== EVALUATORS TAB ===== */}
        {subTab === "evaluators" && (
          <>
            <div className="eval-controls">
              <span className="eval-controls__version">
                <CheckCircle2 size={11} /> AgentCore 내장 평가기
              </span>
            </div>

            {evaluators.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 80 }}>
                <Loader2 size={20} className="spin" />
                <p>평가기 목록 로딩 중...</p>
              </div>
            ) : (
              <div className="eval-evaluators-list">
                {evaluators.map(ev => (
                  <div key={ev.evaluator_id} className="eval-evaluator-card">
                    <div className="eval-evaluator-card__header">
                      <span className="eval-evaluator-card__name">{ev.name.replace("Builtin.", "")}</span>
                      <StatusBadge status={ev.status} />
                      <span className="badge badge--info">{ev.type}</span>
                    </div>
                    <div className="eval-evaluator-card__desc">{ev.description}</div>
                    <div className="divider" />
                    <div className="eval-evaluator-card__meta">
                      <span className="badge badge--neutral"><Layers size={9} /> {ev.level}</span>
                      <span className="badge badge--neutral badge--mono">{ev.evaluator_id}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
