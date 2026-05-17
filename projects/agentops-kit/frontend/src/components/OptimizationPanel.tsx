import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import { OptimizationStatus, Recommendation } from "../types";
import {
  TrendingUp,
  Sparkles,
  Rocket,
  Loader2,
  CheckCircle2,
  XCircle,
  RotateCcw,
  ArrowRight,
  Zap,
  ChevronDown,
  ChevronRight,
  Package,
  FlaskConical,
  BarChart3,
  AlertTriangle,
} from "lucide-react";

interface Props {
  status: OptimizationStatus;
  promptVersion: string;
  compact?: boolean;
}

const STAGES = [
  { key: "recommend", label: "추천", icon: Sparkles },
  { key: "bundle", label: "Bundle", icon: Package },
  { key: "ab_test", label: "A/B 테스트", icon: FlaskConical },
  { key: "deploy", label: "배포", icon: Rocket },
];

function stageIndex(stage: string): number {
  switch (stage) {
    case "idle": return -1;
    case "recommending": return 0;
    case "recommended": return 0;
    case "applied": return 1;
    case "testing": return 2;
    case "deploying": return 3;
    case "complete": return 3;
    default: return -1;
  }
}

export default function OptimizationPanel({ status, promptVersion, compact }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(status.active_recommendation || null);
  const [abTest, setAbTest] = useState<OptimizationStatus["active_test"]>(status.active_test || null);
  const [pollingRec, setPollingRec] = useState(false);

  const activeIdx = stageIndex(status.stage);

  useEffect(() => {
    setRecommendation(status.active_recommendation || null);
    setAbTest(status.active_test || null);
  }, [status]);

  useEffect(() => {
    if (!pollingRec || !recommendation?.recommendation_id) return;
    const interval = setInterval(async () => {
      try {
        const rec = await api.getRecommendation(recommendation.recommendation_id);
        setRecommendation(rec);
        if (rec.status === "COMPLETED" || rec.status === "FAILED") {
          setPollingRec(false);
        }
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(interval);
  }, [pollingRec, recommendation?.recommendation_id]);

  const handleGenerateRecommendation = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rec = await api.generateRecommendation("Builtin.GoalSuccessRate", 7);
      setRecommendation(rec);
      setPollingRec(true);
    } catch (e: any) {
      setError(e.message || "추천 생성 실패");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleApply = useCallback(async () => {
    if (!recommendation?.recommended_prompt) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.applyRecommendation(
        recommendation.recommended_prompt,
        recommendation.recommendation_id,
      );
      setRecommendation({
        ...recommendation,
        bundle_arn: result.bundle_arn || result.bundle_id || "",
        bundle_version: result.bundle_version || "",
      });
    } catch (e: any) {
      setError(e.message || "Bundle 저장 실패");
    } finally {
      setLoading(false);
    }
  }, [recommendation]);

  const handleCreateABTest = useCallback(async () => {
    if (!recommendation?.bundle_arn) {
      setError("Bundle ARN이 없습니다. 먼저 Bundle을 저장해주세요.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const test = await api.createABTest({
        control_bundle_arn: recommendation.bundle_arn,
        control_version: "current",
        treatment_bundle_arn: recommendation.bundle_arn,
        treatment_version: recommendation.bundle_version || "latest",
        control_weight: 80,
        treatment_weight: 20,
      });
      setAbTest(test);
    } catch (e: any) {
      setError(e.message || "A/B 테스트 생성 실패");
    } finally {
      setLoading(false);
    }
  }, [recommendation]);

  const handleCompleteTest = useCallback(async (winner: "control" | "treatment") => {
    if (!abTest?.rule_id) return;
    setLoading(true);
    try {
      await api.completeABTest(abTest.rule_id, winner);
      setAbTest(null);
    } catch (e: any) {
      setError(e.message || "테스트 종료 실패");
    } finally {
      setLoading(false);
    }
  }, [abTest]);

  const handleDeploy = useCallback(async () => {
    if (!recommendation?.recommended_prompt) return;
    setLoading(true);
    try {
      await api.deployWinner(recommendation.recommended_prompt);
      setRecommendation(null);
      setAbTest(null);
    } catch (e: any) {
      setError(e.message || "배포 실패");
    } finally {
      setLoading(false);
    }
  }, [recommendation]);

  const handleReset = useCallback(async () => {
    try {
      await api.resetOptimization();
      setRecommendation(null);
      setAbTest(null);
      setError(null);
    } catch { /* ignore */ }
  }, []);

  return (
    <div className="panel" style={{ padding: compact ? 12 : 20, maxHeight: "calc(100vh - 120px)", overflowY: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
        <TrendingUp size={18} style={{ color: "var(--accent)" }} />
        <span style={{ fontSize: 15, fontWeight: 700 }}>AgentCore Optimization</span>
        <span className="badge badge--info" style={{ marginLeft: "auto" }}>
          프롬프트: {promptVersion.toUpperCase()}
        </span>
      </div>

      {/* Pipeline stages */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
        {STAGES.map((stage, i) => {
          const Icon = stage.icon;
          const active = i <= activeIdx;
          const current = i === activeIdx;
          return (
            <div key={stage.key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 5, padding: "6px 12px",
                borderRadius: 8, fontSize: 11, fontWeight: current ? 700 : 500,
                background: active ? "rgba(106, 175, 53, 0.18)" : "var(--navy-light)",
                color: active ? "#8fd44f" : "var(--gray-400)",
                border: current ? "1.5px solid rgba(106, 175, 53, 0.6)" : "1px solid transparent",
                boxShadow: current ? "0 0 8px rgba(106, 175, 53, 0.2)" : "none",
                transition: "all 0.2s",
              }}>
                <Icon size={12} />
                {stage.label}
              </div>
              {i < STAGES.length - 1 && (
                <ArrowRight size={12} style={{ color: active ? "#8fd44f" : "var(--gray-600)" }} />
              )}
            </div>
          );
        })}
        <button onClick={handleReset} className="btn btn-sm" style={{ marginLeft: "auto", fontSize: 11 }}>
          <RotateCcw size={11} /> 초기화
        </button>
      </div>

      {error && (
        <div style={{ padding: "8px 12px", background: "rgba(231, 76, 60, 0.12)", border: "1px solid rgba(231, 76, 60, 0.4)", borderRadius: "var(--radius)", fontSize: 12, color: "#f87171", marginBottom: 14, display: "flex", alignItems: "center", gap: 6 }}>
          <XCircle size={13} /> {error}
        </div>
      )}

      {/* Stage 1-2: Recommendation + Bundle */}
      {(status.stage === "idle" || status.stage === "recommending" || status.stage === "recommended" || status.stage === "applied") && (
        <RecommendationSection
          recommendation={recommendation}
          loading={loading}
          onGenerate={handleGenerateRecommendation}
          onApply={handleApply}
          onCreateTest={handleCreateABTest}
          onDeploy={handleDeploy}
        />
      )}

      {/* Stage 3: A/B Testing */}
      {(status.stage === "testing") && abTest && (
        <ABTestSection
          test={abTest}
          loading={loading}
          onComplete={handleCompleteTest}
        />
      )}

      {/* Stage 4: Complete */}
      {(status.stage === "complete") && (
        <div style={{ padding: "14px 18px", background: "rgba(106, 175, 53, 0.12)", border: "1.5px solid rgba(106, 175, 53, 0.5)", borderRadius: "var(--radius)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, fontWeight: 700, color: "#8fd44f" }}>
            <CheckCircle2 size={18} />
            최적화 완료 — Winner 배포됨
          </div>
        </div>
      )}

      {/* History */}
      {status.history && status.history.length > 0 && (
        <HistorySection history={status.history} />
      )}
    </div>
  );
}

// --- Sub-components ---

function RecommendationSection({
  recommendation,
  loading,
  onGenerate,
  onApply,
  onCreateTest,
  onDeploy,
}: {
  recommendation: Recommendation | null;
  loading: boolean;
  onGenerate: () => void;
  onApply: () => void;
  onCreateTest: () => void;
  onDeploy: () => void;
}) {
  if (!recommendation) {
    return (
      <div style={{ padding: "20px", background: "var(--navy-light)", borderRadius: "var(--radius)", textAlign: "center" }}>
        <Sparkles size={24} style={{ color: "var(--accent)", marginBottom: 10 }} />
        <div style={{ fontSize: 13, color: "var(--gray-200)", marginBottom: 6, lineHeight: 1.5 }}>
          에이전트 trace를 분석하여 시스템 프롬프트 개선안을 생성합니다.
        </div>
        <div style={{ fontSize: 11, color: "var(--gray-400)", marginBottom: 14, lineHeight: 1.4 }}>
          GoalSuccessRate evaluator 기준 · 최근 7일 CloudWatch Logs 세션 분석
        </div>
        <button className="btn btn-primary" onClick={onGenerate} disabled={loading} style={{ padding: "8px 18px", fontSize: 13 }}>
          {loading ? <><Loader2 size={13} className="spin" /> 생성 중...</> : <><Sparkles size={13} /> 추천 생성</>}
        </button>
      </div>
    );
  }

  if (recommendation.status === "PENDING" || recommendation.status === "IN_PROGRESS") {
    return (
      <div style={{ padding: "18px", background: "var(--navy-light)", borderRadius: "var(--radius)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <Loader2 size={16} className="spin" style={{ color: "var(--accent)" }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--gray-200)" }}>Trace 분석 중...</span>
        </div>
        <div style={{ fontSize: 12, color: "var(--gray-300)", lineHeight: 1.5 }}>
          AgentCore가 세션 trace를 분석하여 실패 패턴을 식별하고 개선된 시스템 프롬프트를 생성하고 있습니다.
        </div>
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--gray-400)" }}>
          ID: {recommendation.recommendation_id} | 상태: {recommendation.status}
        </div>
      </div>
    );
  }

  if (recommendation.status === "FAILED") {
    return (
      <div style={{ padding: "14px 18px", background: "rgba(231, 76, 60, 0.1)", border: "1.5px solid rgba(231, 76, 60, 0.4)", borderRadius: "var(--radius)" }}>
        <div style={{ fontSize: 13, color: "#f87171", fontWeight: 600, marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
          <XCircle size={14} /> 추천 생성 실패
        </div>
        <div style={{ fontSize: 12, color: "var(--gray-300)" }}>
          {recommendation.error_message || "알 수 없는 오류"}
        </div>
        <button className="btn btn-sm" onClick={onGenerate} style={{ marginTop: 10, fontSize: 11 }}>다시 시도</button>
      </div>
    );
  }

  return (
    <CompletedRecommendation
      recommendation={recommendation}
      loading={loading}
      onApply={onApply}
      onCreateTest={onCreateTest}
      onDeploy={onDeploy}
    />
  );
}


function CompletedRecommendation({
  recommendation,
  loading,
  onApply,
  onCreateTest,
  onDeploy,
}: {
  recommendation: Recommendation;
  loading: boolean;
  onApply: () => void;
  onCreateTest: () => void;
  onDeploy: () => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState<string>("");

  useEffect(() => {
    api.getPromptInfo().then((info: any) => setCurrentPrompt(info.prompt || "")).catch(() => {});
  }, []);

  const hasBundle = !!recommendation.bundle_arn;

  return (
    <div style={{ padding: "14px 18px", background: "rgba(255, 153, 0, 0.06)", border: "1.5px solid rgba(255, 153, 0, 0.35)", borderRadius: "var(--radius)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <CheckCircle2 size={16} style={{ color: "#8fd44f" }} />
        <span style={{ fontSize: 14, fontWeight: 700, color: "#8fd44f" }}>추천 완료</span>
        {hasBundle && (
          <span style={{ fontSize: 10, color: "var(--gray-300)", background: "var(--navy)", padding: "2px 8px", borderRadius: 4, marginLeft: 8 }}>
            Bundle 저장됨
          </span>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          style={{ background: "none", border: "none", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, padding: 0, fontSize: 11, color: "var(--gray-400)", marginLeft: "auto" }}
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          {collapsed ? "펼치기" : "접기"}
        </button>
      </div>

      {!collapsed && recommendation.recommended_prompt && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <div style={{ fontSize: 11, color: "var(--gray-300)", marginBottom: 4, fontWeight: 600 }}>현재 프롬프트</div>
              <div style={{
                fontSize: 11, color: "var(--gray-300)", padding: "10px 12px",
                background: "var(--navy)", borderRadius: 6,
                maxHeight: 240, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.5,
              }}>
                {currentPrompt || "(로딩 중...)"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: "#8fd44f", marginBottom: 4, fontWeight: 600 }}>추천 프롬프트</div>
              <div style={{
                fontSize: 11, color: "var(--gray-200)", padding: "10px 12px",
                background: "var(--navy)", borderRadius: 6,
                maxHeight: 240, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.5,
                border: "1.5px solid rgba(106,175,53,0.4)",
              }}>
                {recommendation.recommended_prompt}
              </div>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {!hasBundle ? (
          <button className="btn btn-primary btn-sm" onClick={onApply} disabled={loading} style={{ fontSize: 12, padding: "6px 14px" }}>
            {loading ? <><Loader2 size={12} className="spin" /> 저장 중...</> : <><Package size={12} /> Configuration Bundle 저장</>}
          </button>
        ) : (
          <>
            <button className="btn btn-primary btn-sm" onClick={onCreateTest} disabled={loading} style={{ fontSize: 12, padding: "6px 14px" }}>
              <FlaskConical size={12} /> A/B 테스트 시작
            </button>
            <button className="btn btn-sm" onClick={onDeploy} style={{ fontSize: 12, padding: "6px 14px" }}>
              <Rocket size={12} /> 바로 배포
            </button>
          </>
        )}
      </div>
    </div>
  );
}


function ABTestSection({
  test,
  loading,
  onComplete,
}: {
  test: NonNullable<OptimizationStatus["active_test"]>;
  loading: boolean;
  onComplete: (winner: "control" | "treatment") => void;
}) {
  return (
    <div style={{ padding: "16px 18px", background: "rgba(0, 115, 187, 0.08)", border: "1.5px solid rgba(59, 158, 255, 0.4)", borderRadius: "var(--radius)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <FlaskConical size={16} style={{ color: "#3b9eff" }} />
        <span style={{ fontSize: 14, fontWeight: 700, color: "#3b9eff" }}>A/B 테스트 진행 중</span>
        <span style={{ fontSize: 11, color: "var(--gray-300)", marginLeft: "auto", background: "var(--navy)", padding: "2px 8px", borderRadius: 4 }}>
          ID: {test.rule_id?.slice(0, 8)}...
        </span>
      </div>

      <div style={{ fontSize: 12, color: "var(--gray-300)", marginBottom: 12, lineHeight: 1.5, background: "var(--navy)", padding: "10px 12px", borderRadius: 6 }}>
        AgentCore Gateway가 Session ID 기반으로 트래픽을 분배 중입니다.
        Online Evaluation이 각 세션을 스코어링하여 통계적 유의성(p &lt; 0.05)에 도달하면 결과를 확인할 수 있습니다.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
        <div style={{ padding: "12px 14px", background: "var(--navy)", borderRadius: 6, border: "1px solid var(--navy-light)" }}>
          <div style={{ fontSize: 11, color: "var(--gray-300)", marginBottom: 6, fontWeight: 500 }}>Control (현재)</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "var(--gray-100)" }}>
            {test.control_weight}%
          </div>
          <div style={{ fontSize: 11, color: "var(--gray-400)", marginTop: 2 }}>트래픽</div>
        </div>
        <div style={{ padding: "12px 14px", background: "var(--navy)", borderRadius: 6, border: "1px solid rgba(59, 158, 255, 0.3)" }}>
          <div style={{ fontSize: 11, color: "#3b9eff", marginBottom: 6, fontWeight: 500 }}>Treatment (추천)</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "var(--accent)" }}>
            {test.treatment_weight}%
          </div>
          <div style={{ fontSize: 11, color: "var(--gray-400)", marginTop: 2 }}>트래픽</div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10 }}>
        <button className="btn btn-primary btn-sm" onClick={() => onComplete("treatment")} disabled={loading} style={{ fontSize: 12, padding: "6px 14px" }}>
          <Zap size={12} /> Treatment 승리 → 배포
        </button>
        <button className="btn btn-sm" onClick={() => onComplete("control")} disabled={loading} style={{ fontSize: 12, padding: "6px 14px" }}>
          Control 유지
        </button>
      </div>
    </div>
  );
}


function HistorySection({ history }: { history: OptimizationStatus["history"] }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState<string>("");

  useEffect(() => {
    api.getPromptInfo().then((info: any) => setCurrentPrompt(info.prompt || "")).catch(() => {});
  }, []);

  const loadDetail = useCallback(async (h: OptimizationStatus["history"][0], idx: number) => {
    if (expandedIdx === idx) {
      setExpandedIdx(null);
      setDetail(null);
      return;
    }
    setExpandedIdx(idx);
    setDetail(null);
    setDetailLoading(true);
    try {
      if (h.type === "recommendation" && h.id) {
        const rec = await api.getRecommendation(h.id);
        setDetail({ type: "recommendation", data: rec });
      } else if (h.type === "bundle_version" && h.bundle_id && h.version_id) {
        const bundle = await api.getBundle(h.bundle_id, h.version_id);
        setDetail({ type: "bundle_version", data: bundle });
      }
    } catch (e: any) {
      setDetail({ type: "error", data: { message: e.message || "로드 실패" } });
    } finally {
      setDetailLoading(false);
    }
  }, [expandedIdx]);

  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ fontSize: 12, color: "var(--gray-300)", marginBottom: 10, fontWeight: 600 }}>최적화 이력 (AgentCore)</div>
      {history.slice(0, 8).map((h, i) => {
        let icon = <CheckCircle2 size={12} style={{ color: "#8fd44f", flexShrink: 0 }} />;
        let label = "";
        const canExpand = h.type === "recommendation" || h.type === "bundle_version";

        switch (h.type) {
          case "recommendation":
            icon = <Sparkles size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />;
            label = `추천: ${h.name || h.id || ""}`;
            if (h.status) label += ` [${h.status}]`;
            break;
          case "bundle_version":
            icon = <Package size={12} style={{ color: "#3b9eff", flexShrink: 0 }} />;
            label = h.commit_message || `Bundle 버전 ${h.version_id?.slice(0, 8) || ""}`;
            break;
          case "error":
            icon = <AlertTriangle size={12} style={{ color: "#ff6b6b", flexShrink: 0 }} />;
            label = h.message || "API 조회 실패";
            break;
          default:
            label = h.type;
        }

        const isExpanded = expandedIdx === i;

        return (
          <div key={i} style={{ borderBottom: i < Math.min(history.length, 8) - 1 ? "1px solid var(--navy-light)" : "none" }}>
            <div
              onClick={() => canExpand && loadDetail(h, i)}
              style={{
                fontSize: 12, color: "var(--gray-200)", padding: "8px 0",
                display: "flex", alignItems: "center", gap: 8,
                cursor: canExpand ? "pointer" : "default",
              }}
            >
              {icon}
              <span style={{ flex: 1 }}>{label}</span>
              {canExpand && (
                isExpanded ? <ChevronDown size={11} style={{ color: "var(--gray-400)" }} /> : <ChevronRight size={11} style={{ color: "var(--gray-400)" }} />
              )}
              <span style={{ fontSize: 10, color: "var(--gray-400)", whiteSpace: "nowrap" }}>
                {h.timestamp?.slice(0, 16).replace("T", " ")}
              </span>
            </div>
            {isExpanded && (
              <HistoryDetail loading={detailLoading} detail={detail} currentPrompt={currentPrompt} />
            )}
          </div>
        );
      })}
      {history.length === 0 && (
        <div style={{ fontSize: 11, color: "var(--gray-400)", padding: "8px 0" }}>이력 없음</div>
      )}
    </div>
  );
}


function HistoryDetail({ loading, detail, currentPrompt }: { loading: boolean; detail: any; currentPrompt: string }) {
  if (loading) {
    return (
      <div style={{ padding: "8px 0 12px 20px", display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--gray-400)" }}>
        <Loader2 size={11} className="spin" /> 상세 로딩 중...
      </div>
    );
  }
  if (!detail) return null;

  if (detail.type === "error") {
    return (
      <div style={{ padding: "6px 0 10px 20px", fontSize: 11, color: "#f87171" }}>
        {detail.data.message}
      </div>
    );
  }

  if (detail.type === "recommendation") {
    const rec = detail.data;
    return (
      <div style={{ padding: "6px 0 12px 0" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, fontSize: 11, marginBottom: 8, color: "var(--gray-300)" }}>
          <span>상태: <b style={{ color: rec.status === "COMPLETED" ? "#8fd44f" : "#f87171" }}>{rec.status}</b></span>
          <span>타입: {rec.type || "-"}</span>
          <span>생성: {rec.created_at?.slice(0, 16).replace("T", " ") || "-"}</span>
        </div>
        {rec.recommended_prompt && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--gray-300)", marginBottom: 3, fontWeight: 600 }}>현재 프롬프트</div>
              <div style={{
                fontSize: 10, color: "var(--gray-300)", padding: "8px 10px",
                background: "var(--navy)", borderRadius: 5,
                maxHeight: 160, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.4,
                border: "1px solid var(--navy-light)",
              }}>
                {currentPrompt || "(로딩 중...)"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "#8fd44f", marginBottom: 3, fontWeight: 600 }}>추천된 프롬프트</div>
              <div style={{
                fontSize: 10, color: "var(--gray-200)", padding: "8px 10px",
                background: "var(--navy)", borderRadius: 5,
                maxHeight: 160, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.4,
                border: "1px solid rgba(106,175,53,0.3)",
              }}>
                {rec.recommended_prompt}
              </div>
            </div>
          </div>
        )}
        {rec.error_message && (
          <div style={{ fontSize: 11, color: "#f87171", marginTop: 6 }}>오류: {rec.error_message}</div>
        )}
      </div>
    );
  }

  if (detail.type === "bundle_version") {
    const b = detail.data;
    return (
      <div style={{ padding: "6px 0 12px 0" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 11, marginBottom: 8, color: "var(--gray-300)" }}>
          <span>Bundle: {b.bundle_name || b.bundle_id}</span>
          <span>버전: {b.version_id?.slice(0, 8) || "-"}</span>
        </div>
        {b.commit_message && (
          <div style={{ fontSize: 11, color: "var(--gray-300)", marginBottom: 6 }}>{b.commit_message}</div>
        )}
        {b.system_prompt ? (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--gray-300)", marginBottom: 3, fontWeight: 600 }}>현재 프롬프트</div>
              <div style={{
                fontSize: 10, color: "var(--gray-300)", padding: "8px 10px",
                background: "var(--navy)", borderRadius: 5,
                maxHeight: 160, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.4,
                border: "1px solid var(--navy-light)",
              }}>
                {currentPrompt || "(로딩 중...)"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: "#3b9eff", marginBottom: 3, fontWeight: 600 }}>
                적용된 프롬프트{b.prompt_source === "recommendation" ? " (추천에서 로드)" : ""}
              </div>
              <div style={{
                fontSize: 10, color: "var(--gray-200)", padding: "8px 10px",
                background: "var(--navy)", borderRadius: 5,
                maxHeight: 160, overflow: "auto",
                whiteSpace: "pre-wrap", lineHeight: 1.4,
                border: "1px solid rgba(59,158,255,0.3)",
              }}>
                {b.system_prompt}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 11, color: "var(--gray-400)" }}>
            프롬프트 조회 불가{b.recommendation_id ? ` (${b.recommendation_id} — 삭제됨 또는 테스트 데이터)` : ""}
          </div>
        )}
      </div>
    );
  }

  return null;
}
