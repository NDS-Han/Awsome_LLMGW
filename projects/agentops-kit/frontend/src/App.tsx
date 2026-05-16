import { useState, useEffect, useCallback, useRef, Fragment, startTransition } from "react";
import { api } from "./api";
import {
  ChatMessage,
  Trace,
  MetricsData,
  EvalEntry,
  GuardrailResult,
  SessionState,
  CostGlobalState,
  SessionCostState,
  TurnEvalResult,
  ImprovementState,
  EvalAnalysis,
} from "./types";
import ChatPanel from "./components/ChatPanel";
import TraceViewer from "./components/TraceViewer";
import MetricsPanel from "./components/MetricsPanel";
import EvalPanel from "./components/EvalPanel";
import GuardrailsPanel from "./components/GuardrailsPanel";
import CostPanel from "./components/CostPanel";
import SessionHealthPanel from "./components/SessionHealthPanel";
import LLMGatewayPanel from "./components/LLMGatewayPanel";
import ToolGatewayPanel from "./components/ToolGatewayPanel";
import AgentGatewayPanel from "./components/AgentGatewayPanel";
import RegistryPanel from "./components/RegistryPanel";
import UsersPanel from "./components/UsersPanel";
import TeamsPanel from "./components/TeamsPanel";
import AnomalyPanel from "./components/AnomalyPanel";
import SessionExplorerPanel from "./components/SessionExplorerPanel";
import ToolAnalyticsPanel from "./components/ToolAnalyticsPanel";
import GatewayJourneyStrip from "./components/GatewayJourneyStrip";
import ErrorBoundary from "./components/ErrorBoundary";
import {
  Activity,
  MessageSquare,
  BarChart3,
  Shield,
  Zap,
  ShieldCheck,
  DollarSign,
  HeartPulse,
  Cpu,
  Wrench,
  Users,
  BookMarked,
  User,
  Briefcase,
  AlertTriangle,
  Layers,
  PieChart,
} from "lucide-react";
import "./styles.css";

type Tab =
  | "overview"
  | "chat"
  | "traces"
  | "metrics"
  | "evaluation"
  | "guardrails"
  | "cost"
  | "session"
  | "llm_gateway"
  | "tool_gateway"
  | "agent_gateway"
  | "registry"
  | "users"
  | "teams"
  | "anomaly"
  | "session_explorer"
  | "tool_analytics";

type PanelId = Exclude<Tab, "overview">;

interface TabConfig {
  main: PanelId;
  companions: PanelId[];
  defaultActive: PanelId[];
}

const TAB_CONFIG: Record<Tab, TabConfig> = {
  overview:         { main: "chat",              companions: ["traces","metrics","evaluation","guardrails","cost","session"],    defaultActive: ["chat","traces","metrics","evaluation","cost","session"] },
  chat:             { main: "chat",              companions: ["traces","guardrails","cost","metrics","session"],                defaultActive: ["traces","guardrails"] },
  traces:           { main: "traces",            companions: ["metrics","tool_analytics","session"],                              defaultActive: ["metrics"] },
  metrics:          { main: "metrics",           companions: ["traces","cost","session"],                                      defaultActive: ["traces","cost"] },
  evaluation:       { main: "evaluation",        companions: ["metrics","cost","chat"],                                        defaultActive: ["metrics"] },
  guardrails:       { main: "guardrails",        companions: ["chat","traces","cost"],                                         defaultActive: ["chat","traces"] },
  cost:             { main: "cost",              companions: ["metrics","session","guardrails","anomaly"],                      defaultActive: ["metrics","session"] },
  session:          { main: "session",           companions: ["traces","guardrails","cost","anomaly"],                          defaultActive: ["traces","cost"] },
  llm_gateway:      { main: "llm_gateway",       companions: ["cost","metrics","guardrails"],                                  defaultActive: ["cost"] },
  tool_gateway:     { main: "tool_gateway",      companions: ["tool_analytics","traces"],                                      defaultActive: ["tool_analytics"] },
  agent_gateway:    { main: "agent_gateway",     companions: ["traces","session"],                                             defaultActive: ["traces"] },
  registry:         { main: "registry",          companions: ["tool_gateway","agent_gateway"],                                 defaultActive: [] },
  users:            { main: "users",             companions: ["cost","session"],                                               defaultActive: ["cost"] },
  teams:            { main: "teams",             companions: ["cost","users"],                                                 defaultActive: ["cost"] },
  session_explorer: { main: "session_explorer",  companions: ["traces","metrics","session"],                                   defaultActive: ["traces"] },
  tool_analytics:   { main: "tool_analytics",    companions: ["traces","tool_gateway"],                                        defaultActive: ["traces"] },
  anomaly:          { main: "anomaly",           companions: ["metrics","guardrails","session"],                                defaultActive: ["metrics"] },
};

const PANEL_LABELS: Record<PanelId, { label: string; icon: React.ReactNode }> = {
  chat:             { label: "채팅",        icon: <MessageSquare size={12}/> },
  traces:           { label: "트레이스",    icon: <Zap size={12}/> },
  metrics:          { label: "메트릭",      icon: <BarChart3 size={12}/> },
  evaluation:       { label: "평가",        icon: <Shield size={12}/> },
  guardrails:       { label: "가드레일",    icon: <ShieldCheck size={12}/> },
  cost:             { label: "비용",        icon: <DollarSign size={12}/> },
  session:          { label: "세션",        icon: <HeartPulse size={12}/> },
  llm_gateway:      { label: "LLM Gateway", icon: <Cpu size={12}/> },
  tool_gateway:     { label: "Tool Gateway",icon: <Wrench size={12}/> },
  agent_gateway:    { label: "Agent Gateway",icon: <Users size={12}/> },
  registry:         { label: "레지스트리",   icon: <BookMarked size={12}/> },
  users:            { label: "사용자",      icon: <User size={12}/> },
  teams:            { label: "팀",          icon: <Briefcase size={12}/> },
  session_explorer: { label: "세션 탐색",   icon: <Layers size={12}/> },
  tool_analytics:   { label: "도구 분석",   icon: <PieChart size={12}/> },
  anomaly:          { label: "이상 탐지",   icon: <AlertTriangle size={12}/> },
};

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null);
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [evalHistory, setEvalHistory] = useState<EvalEntry[]>([]);
  const [promptVersion, setPromptVersion] = useState("v1");
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);

  // New: production validation state
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const [costGlobal, setCostGlobal] = useState<CostGlobalState | null>(null);
  const [sessionCost, setSessionCost] = useState<SessionCostState | null>(null);
  const [latestGuardrail, setLatestGuardrail] = useState<GuardrailResult | null>(null);

  // Agent selection state
  const [agents, setAgents] = useState<{ agent_id: string; name: string }[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | undefined>(undefined);

  // Online evaluation state
  const [turnEvals, setTurnEvals] = useState<Record<string, TurnEvalResult>>({});
  const [turnEvalOrder, setTurnEvalOrder] = useState<string[]>([]);
  const [improvementState, setImprovementState] = useState<ImprovementState>({ status: "idle" });
  const [evalAnalysis, setEvalAnalysis] = useState<EvalAnalysis | null>(null);
  const [isEvalRunning, setIsEvalRunning] = useState(false);

  // Companion panel toggle state
  const [activeCompanions, setActiveCompanions] = useState<Record<Tab, PanelId[]>>(() => {
    const initial: Record<string, PanelId[]> = {};
    for (const [tab, config] of Object.entries(TAB_CONFIG)) {
      initial[tab] = [...config.defaultActive];
    }
    return initial as Record<Tab, PanelId[]>;
  });

  const toggleCompanion = (tab: Tab, panelId: PanelId) => {
    setActiveCompanions(prev => {
      const current = prev[tab];
      const next = current.includes(panelId)
        ? current.filter(id => id !== panelId)
        : [...current, panelId];
      return { ...prev, [tab]: next };
    });
  };

  // Health check
  useEffect(() => {
    api
      .getHealth()
      .then((h) => {
        setConnected(true);
        setPromptVersion(h.prompt_version);
      })
      .catch(() => setConnected(false));
  }, []);

  const refreshData = useCallback(async () => {
    try {
      const calls: Promise<any>[] = [
        api.getTraces(20),
        api.getMetrics(24, selectedAgentId),
        api.getEvalHistory(),
        api.getCostOverview(),
        api.getTurnEvals(),
        api.getImprovement(),
        api.getAgents(),
        api.getEvalAnalysis(),
      ];
      if (currentSessionId) {
        calls.push(api.getSession(currentSessionId));
      }
      const results = await Promise.all(calls);
      setTraces(results[0].traces || []);
      setMetrics(results[1]);
      setEvalHistory(results[2].history || []);
      setCostGlobal(results[3]);
      // Turn evals + improvement
      const turnData = results[4];
      setTurnEvals(turnData.turn_evals || {});
      setTurnEvalOrder(turnData.trend?.map((t: any) => t.turn_id) || []);
      setImprovementState(results[5] || { status: "idle" });
      setAgents(results[6]?.agents || []);
      setEvalAnalysis(results[7] || null);
      // Attach eval results to existing messages
      setMessages((prev) =>
        prev.map((msg) => {
          if (msg.role !== "assistant" || !msg.turn_id) return msg;
          const ev = turnData.turn_evals?.[msg.turn_id];
          if (ev && !msg.eval) {
            return { ...msg, eval: { avg_score: ev.avg_score, label: ev.scores?.[0]?.label || "" }, evalLoading: false };
          }
          return msg;
        }),
      );
      if (currentSessionId && results[8]) {
        setSessionState(results[8]);
        setSessionCost(results[8].cost_state);
      }
    } catch {
      // silent
    }
  }, [currentSessionId, selectedAgentId]);

  useEffect(() => {
    if (connected) {
      refreshData();
      const iv = setInterval(refreshData, 5000);
      return () => clearInterval(iv);
    }
  }, [connected, refreshData]);

  const handleSend = async (prompt: string) => {
    const userMsg: ChatMessage = {
      role: "user",
      content: prompt,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    // Streaming assistant message — 서버에서 text_delta가 오는 대로 누적.
    const assistantIdx = (prevLen: number) => prevLen;
    let finalPayload: any = null;

    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      timestamp: new Date().toISOString(),
    };
    let placeholderIndex = -1;
    setMessages((prev) => {
      placeholderIndex = assistantIdx(prev.length);
      return [...prev, placeholder];
    });

    // ── 스무스 렌더링을 위한 RAF 기반 문자 드립 큐 ─────────────────
    // Bedrock은 토큰을 5~20자 burst로 내보냄. 데이터는 그대로 받되
    // 화면 갱신 속도만 requestAnimationFrame 주기(~16ms)로 균일화해
    // 사람 눈에 끊기지 않고 흐르는 것처럼 보이게 한다.
    const queueRef: { buf: string; raf: number | null; last: number; lastFlush: number; done: boolean } = {
      buf: "", raf: null, last: 0, lastFlush: 0, done: false,
    };
    const CHARS_PER_SEC = 180;     // 시각적 스트리밍 속도 (Sonnet 평균에 근접)
    const MIN_FLUSH_MS = 45;       // setState 최소 간격 — 20fps. 이것이 탭 전환 시 freeze의 주원인이었음.
    const flushPending = () => {
      const now = performance.now();
      const elapsedSinceLastFlush = now - queueRef.lastFlush;
      // 아직 플러시 간격에 도달 안 했고, 스트림도 살아있으면 다음 RAF로 미룸
      if (elapsedSinceLastFlush < MIN_FLUSH_MS && !queueRef.done) {
        queueRef.raf = requestAnimationFrame(flushPending);
        return;
      }
      if (queueRef.buf.length === 0) {
        queueRef.raf = null;
        return;
      }
      const elapsedSinceLastChars = now - queueRef.last;
      let take = Math.max(1, Math.round((CHARS_PER_SEC * elapsedSinceLastChars) / 1000));
      if (queueRef.done) take = Math.max(take, 64);
      const chunk = queueRef.buf.slice(0, take);
      queueRef.buf = queueRef.buf.slice(take);
      queueRef.last = now;
      queueRef.lastFlush = now;
      setMessages((prev) => {
        const copy = prev.slice();
        const idx = copy.length - 1;
        if (idx >= 0 && copy[idx].role === "assistant") {
          copy[idx] = { ...copy[idx], content: (copy[idx].content || "") + chunk };
        }
        return copy;
      });
      if (queueRef.buf.length > 0) {
        queueRef.raf = requestAnimationFrame(flushPending);
      } else {
        queueRef.raf = null;
      }
    };
    const appendDelta = (delta: string) => {
      queueRef.buf += delta;
      if (queueRef.raf === null) {
        queueRef.last = performance.now();
        queueRef.raf = requestAnimationFrame(flushPending);
      }
    };
    const waitForDrain = () => new Promise<void>((resolve) => {
      queueRef.done = true;
      const check = () => {
        if (queueRef.buf.length === 0 && queueRef.raf === null) {
          resolve();
        } else {
          requestAnimationFrame(check);
        }
      };
      check();
    });

    const mergeMeta = (meta: Partial<ChatMessage>) => {
      setMessages((prev) => {
        const copy = prev.slice();
        const idx = copy.length - 1;
        if (idx >= 0 && copy[idx].role === "assistant") {
          copy[idx] = { ...copy[idx], ...meta };
        }
        return copy;
      });
    };

    try {
      await api.streamChat(prompt, {
        sessionId: currentSessionId || undefined,
        onEvent: (ev) => {
          switch (ev.type) {
            case "session":
              if (!currentSessionId) setCurrentSessionId(ev.session_id);
              mergeMeta({ turn_id: ev.turn_id });
              // 스트림이 열렸으니 '로딩 닷'은 숨긴다 — 텍스트가 바로 나오기 시작함.
              setLoading(false);
              break;
            case "text_delta":
              appendDelta(ev.delta);
              // session 이벤트를 못 받았을 경우에도 첫 delta에서 로딩 닷 제거.
              setLoading(false);
              break;
            case "tool_use":
              // 메시지의 현재 tools_used에 누적 추가 (중복 방지)
              setMessages((prev) => {
                const copy = prev.slice();
                const idx = copy.length - 1;
                if (idx >= 0 && copy[idx].role === "assistant") {
                  const cur = copy[idx].tools_used || [];
                  if (!cur.includes(ev.name)) {
                    copy[idx] = { ...copy[idx], tools_used: [...cur, ev.name] };
                  }
                }
                return copy;
              });
              break;
            case "final":
              finalPayload = ev;
              // 메타데이터는 텍스트가 다 렌더된 후 적용 — 아직 큐에 남아 있을 수 있음
              break;
            case "complete":
              // complete는 최종 cost/guardrails까지 포함 — final 합쳐 보관만
              finalPayload = { ...(finalPayload || {}), _complete: ev };
              if (ev.guardrails) setLatestGuardrail(ev.guardrails);
              break;
            case "error":
              mergeMeta({ content: `Error: ${ev.message}` });
              break;
          }
        },
      });

      // 서버 스트림은 끝났지만 RAF 큐에 아직 문자가 남아 있을 수 있음.
      // 완전히 화면에 다 그려진 후 메타데이터를 붙인다.
      await waitForDrain();

      if (finalPayload) {
        const complete = finalPayload._complete || {};
        mergeMeta({
          tools_used: finalPayload.tools_used || [],
          token_usage: finalPayload.usage,
          latency_ms: complete.latency_ms ?? finalPayload.latency_ms,
          trace_id: complete.trace_id || finalPayload.otel_trace_id,
          cost: complete.cost,
          guardrails: complete.guardrails,
          redacted: complete.redacted,
          circuit_state: complete.circuit_state,
          evalLoading: true,
        });
      }
      refreshData();
    } catch (e: any) {
      mergeMeta({ content: `Error: ${e.message}` });
    } finally {
      setLoading(false);
    }
    void placeholderIndex;
  };

  const handleSwitchPrompt = async (version: string) => {
    try {
      await api.setPromptVersion(version);
      setPromptVersion(version);
    } catch (e: any) {
      console.error("Failed to switch prompt:", e);
    }
  };

  const handleRunEval = async () => {
    setIsEvalRunning(true);
    try {
      await api.runEvaluation([
        "Builtin.Helpfulness",
        "Builtin.Correctness",
        "Builtin.GoalSuccessRate",
        "Builtin.Faithfulness",
        "Builtin.ToolSelectionAccuracy",
        "Builtin.Conciseness",
      ]);
      refreshData();
    } catch (e: any) {
      console.error("Failed to run evaluation:", e);
    } finally {
      setIsEvalRunning(false);
    }
  };

  const handleApplyImprovement = async () => {
    try {
      await api.applyImprovement();
      const imp = await api.getImprovement();
      setImprovementState(imp);
      if (imp.suggestion?.suggested_version) {
        setPromptVersion(imp.suggestion.suggested_version);
      }
      refreshData();
    } catch (e: any) {
      console.error("Failed to apply improvement:", e);
    }
  };

  const handleResetImprovement = async () => {
    try {
      await api.resetImprovement();
      setImprovementState({ status: "idle" });
    } catch (e: any) {
      console.error("Failed to reset improvement:", e);
    }
  };

  const renderPanel = (panelId: PanelId, compact: boolean) => {
    return (
      <ErrorBoundary key={panelId} panelName={PANEL_LABELS[panelId]?.label}>
        {renderPanelInner(panelId, compact)}
      </ErrorBoundary>
    );
  };

  const renderPanelInner = (panelId: PanelId, compact: boolean) => {
    switch (panelId) {
      case "chat":
        return <ChatPanel messages={messages} onSend={handleSend} loading={loading} compact={compact} />;
      case "traces":
        return <TraceViewer traces={traces} selectedTrace={selectedTrace} onSelectTrace={setSelectedTrace} compact={compact} />;
      case "metrics":
        return <MetricsPanel metrics={metrics} compact={compact} agents={agents} selectedAgentId={selectedAgentId} onSelectAgent={setSelectedAgentId} />;
      case "evaluation":
        return <EvalPanel evalHistory={evalHistory} promptVersion={promptVersion} onSwitchPrompt={handleSwitchPrompt} onRunEval={handleRunEval} isEvalRunning={isEvalRunning} turnEvals={turnEvals} turnEvalOrder={turnEvalOrder} improvementState={improvementState} onApplyImprovement={handleApplyImprovement} onResetImprovement={handleResetImprovement} evalAnalysis={evalAnalysis} compact={compact} />;
      case "guardrails":
        return <GuardrailsPanel latestGuardrail={latestGuardrail} compact={compact} />;
      case "cost":
        return <CostPanel global={costGlobal} session={sessionCost} compact={compact} />;
      case "session":
        return <SessionHealthPanel session={sessionState} onReset={refreshData} compact={compact} />;
      case "llm_gateway":
        return <LLMGatewayPanel compact={compact} />;
      case "tool_gateway":
        return <ToolGatewayPanel compact={compact} />;
      case "agent_gateway":
        return <AgentGatewayPanel compact={compact} />;
      case "registry":
        return <RegistryPanel compact={compact} />;
      case "users":
        return <UsersPanel compact={compact} />;
      case "teams":
        return <TeamsPanel compact={compact} />;
      case "session_explorer":
        return <SessionExplorerPanel onSelectTrace={(traceId) => {
          const t = traces.find(tr => tr.trace_id === traceId);
          if (t) { setSelectedTrace(t); setActiveTab("traces"); }
        }} compact={compact} />;
      case "tool_analytics":
        return <ToolAnalyticsPanel compact={compact} />;
      case "anomaly":
        return <AnomalyPanel compact={compact} />;
    }
  };

  // --- Resizable panels ---
  const gridRef = useRef<HTMLDivElement>(null);
  const [mainFlex, setMainFlex] = useState(3);
  const [companionHeights, setCompanionHeights] = useState<Record<string, number[]>>({});

  const handleHDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const grid = gridRef.current;
    if (!grid) return;
    const gridW = grid.getBoundingClientRect().width;
    const startFlex = mainFlex;
    const totalFlex = 5;

    const onMove = (ev: MouseEvent) => {
      const dx = ev.clientX - startX;
      const dFlex = (dx / gridW) * totalFlex;
      const next = Math.max(1, Math.min(totalFlex - 0.5, startFlex + dFlex));
      setMainFlex(next);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const handleVDragStart = (e: React.MouseEvent, idx: number, key: string, count: number) => {
    e.preventDefault();
    const companionsEl = (e.target as HTMLElement).closest(".flex-grid-companions") as HTMLElement | null;
    if (!companionsEl) return;
    const totalH = companionsEl.getBoundingClientRect().height;
    const current = companionHeights[key] || Array(count).fill(1);
    const startY = e.clientY;
    const sumFlex = current.reduce((a, b) => a + b, 0);

    const onMove = (ev: MouseEvent) => {
      const dy = ev.clientY - startY;
      const dFlex = (dy / totalH) * sumFlex;
      const next = [...current];
      next[idx] = Math.max(0.2, current[idx] + dFlex);
      next[idx + 1] = Math.max(0.2, current[idx + 1] - dFlex);
      setCompanionHeights(prev => ({ ...prev, [key]: next }));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const config = TAB_CONFIG[activeTab];
  const companions = activeCompanions[activeTab].filter(id => config.companions.includes(id));
  const companionKey = companions.join(",");
  const cHeights = companionHeights[companionKey] || Array(companions.length).fill(1);

  type TabItem = { id: Tab; label: string; icon: React.ReactNode };
  const tabGroups: { name: string; tabs: TabItem[] }[] = [
    {
      name: "종합",
      tabs: [
        { id: "overview", label: "종합", icon: <Activity size={14} /> },
      ],
    },
    {
      name: "분석",
      tabs: [
        { id: "chat", label: "채팅", icon: <MessageSquare size={14} /> },
        { id: "traces", label: "트레이스", icon: <Zap size={14} /> },
        { id: "metrics", label: "메트릭", icon: <BarChart3 size={14} /> },
        { id: "evaluation", label: "평가", icon: <Shield size={14} /> },
      ],
    },
    {
      name: "Gateway",
      tabs: [
        { id: "llm_gateway", label: "LLM Gateway", icon: <Cpu size={14} /> },
        { id: "tool_gateway", label: "Tool Gateway", icon: <Wrench size={14} /> },
        { id: "agent_gateway", label: "Agent Gateway", icon: <Users size={14} /> },
        { id: "registry", label: "레지스트리", icon: <BookMarked size={14} /> },
      ],
    },
    {
      name: "운영",
      tabs: [
        { id: "cost", label: "비용", icon: <DollarSign size={14} /> },
        { id: "session", label: "세션", icon: <HeartPulse size={14} /> },
        { id: "guardrails", label: "가드레일", icon: <ShieldCheck size={14} /> },
        { id: "anomaly", label: "이상 탐지", icon: <AlertTriangle size={14} /> },
        { id: "tool_analytics", label: "도구 분석", icon: <PieChart size={14} /> },
        { id: "session_explorer", label: "세션 탐색", icon: <Layers size={14} /> },
        { id: "users", label: "사용자", icon: <User size={14} /> },
        { id: "teams", label: "팀", icon: <Briefcase size={14} /> },
      ],
    },
  ];

  return (
    <div className="app">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <div className="logo">
            <Activity size={20} />
            <span>AgentOps</span>
          </div>
          <span className="header-subtitle">
            이커머스 분석 에이전트 대시보드 · 운영 검증 파이프라인
          </span>
        </div>
        <div className="header-right">
          {sessionState?.circuit_breaker && (
            <div
              className={`status-badge ${
                sessionState.circuit_breaker.state === "closed"
                  ? "connected"
                  : "disconnected"
              }`}
            >
              <span className="status-dot" />
              Circuit Breaker: {sessionState.circuit_breaker.state}
            </div>
          )}
          {costGlobal && (
            <div className="prompt-badge">
              <DollarSign size={10} style={{ verticalAlign: "middle" }} />
              ${costGlobal.total_cost.toFixed(4)}
            </div>
          )}
          <div
            className={`status-badge ${connected ? "connected" : "disconnected"}`}
          >
            <span className="status-dot" />
            {connected ? "연결됨" : "연결 끊김"}
          </div>
          <div className="prompt-badge">
            프롬프트: <strong>{promptVersion.toUpperCase()}</strong>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="nav">
        {tabGroups.map((group, gi) => (
          <Fragment key={group.name}>
            {gi > 0 && <span className="nav-group-divider" aria-hidden />}
            <span className="nav-group-label">{group.name}</span>
            {group.tabs.map((tab) => (
              <button
                key={tab.id}
                className={`nav-tab ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => startTransition(() => setActiveTab(tab.id))}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}
          </Fragment>
        ))}
      </nav>

      {/* Content */}
      <main className="main">
        {activeTab === "overview" ? (
          <div className="overview-grid">
            {(["chat", "traces", "metrics", "evaluation", "cost", "session"] as PanelId[]).map(id => (
              <div key={id} className="overview-grid-cell">
                {renderPanel(id, true)}
              </div>
            ))}
          </div>
        ) : (
          <>
            {config.companions.length > 0 && (
              <div className="companion-toggle-bar">
                {config.companions.map(id => (
                  <button
                    key={id}
                    className={`companion-toggle ${companions.includes(id) ? "active" : ""}`}
                    onClick={() => toggleCompanion(activeTab, id)}
                  >
                    {PANEL_LABELS[id].icon}
                    {PANEL_LABELS[id].label}
                  </button>
                ))}
              </div>
            )}
            {activeTab === "chat" && <GatewayJourneyStrip />}
            <div ref={gridRef} className={`flex-grid ${companions.length === 0 ? "full" : ""}`}>
              <div className="flex-grid-main" style={{ flex: companions.length > 0 ? mainFlex : 1 }}>
                {renderPanel(config.main, false)}
              </div>
              {companions.length > 0 && (
                <>
                  <div className="resize-handle-h" onMouseDown={handleHDragStart} />
                  <div className="flex-grid-companions" style={{ flex: 5 - mainFlex }}>
                    {companions.map((id, idx) => (
                      <Fragment key={id}>
                        {idx > 0 && (
                          <div
                            className="resize-handle-v"
                            onMouseDown={(e) => handleVDragStart(e, idx - 1, companionKey, companions.length)}
                          />
                        )}
                        <div className="flex-grid-companion" style={{ flex: cHeights[idx] }}>
                          {renderPanel(id, true)}
                        </div>
                      </Fragment>
                    ))}
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
