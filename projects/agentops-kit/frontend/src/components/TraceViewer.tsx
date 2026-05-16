import { useState, useEffect, memo } from "react";
import { Zap, ChevronRight, ChevronDown, Copy } from "lucide-react";
import { Trace, Span } from "../types";
import { api } from "../api";

interface Props {
  traces: Trace[];
  selectedTrace: Trace | null;
  onSelectTrace: (trace: Trace | null) => void;
  compact?: boolean;
}

const SPAN_COLORS: Record<string, string> = {
  interaction: "#8b5cf6",
  llm: "#3b82f6",
  tool: "#f59e0b",
  guardrail: "#22c55e",
  cost: "#ec4899",
  other: "#6b7280",
};

const SPAN_LABELS: Record<string, string> = {
  interaction: "Interaction",
  llm: "LLM Call",
  tool: "Tool Call",
  guardrail: "Guardrail",
  cost: "Cost",
  other: "Other",
};

const STEP_COLORS: Record<string, string> = {
  llm_call: "#8b5cf6",
  tool_selection: "#06b6d4",
  tool_execution: "#f59e0b",
  a2a_handoff: "#ec4899",
  guardrail: "#22c55e",
  response: "#3b82f6",
};

const STEP_LABELS: Record<string, string> = {
  llm_call: "LLM",
  tool_selection: "Select",
  tool_execution: "Tool",
  a2a_handoff: "A2A",
  guardrail: "Guard",
  response: "Response",
};

const SOURCE_STYLES: Record<string, { color: string; bg: string; label: string }> = {
  otel: { color: "#22c55e", bg: "rgba(34,197,94,0.12)", label: "OTEL" },
  local: { color: "#6b7280", bg: "rgba(107,114,128,0.12)", label: "Local" },
};

// --- Helpers (reused) ---

function flattenSpans(spans: Span[], depth: number = 0): { span: Span; depth: number }[] {
  const result: { span: Span; depth: number }[] = [];
  for (const span of spans) {
    result.push({ span, depth });
    if (span.subsegments?.length) {
      result.push(...flattenSpans(span.subsegments, depth + 1));
    }
  }
  return result;
}

function inferAgentSteps(spans: Span[]): { type: string; name: string; duration_ms: number; start_ms: number; count: number }[] {
  const allFlat = flattenSpans(spans);
  const steps: { [key: string]: { type: string; name: string; count: number; duration_ms: number; start_ms: number } } = {};

  for (const { span } of allFlat) {
    if (span.type === "llm") {
      if (!steps["llm_call"]) {
        steps["llm_call"] = { type: "llm_call", name: "LLM Call", count: 0, duration_ms: 0, start_ms: span.start_ms };
      }
      steps["llm_call"].count++;
      steps["llm_call"].duration_ms += span.duration_ms;
      steps["llm_call"].start_ms = Math.min(steps["llm_call"].start_ms, span.start_ms);
    } else if (span.type === "tool") {
      if (!steps["tool_execution"]) {
        steps["tool_execution"] = { type: "tool_execution", name: "Tool Execution", count: 0, duration_ms: 0, start_ms: span.start_ms };
      }
      steps["tool_execution"].count++;
      steps["tool_execution"].duration_ms += span.duration_ms;
      steps["tool_execution"].start_ms = Math.min(steps["tool_execution"].start_ms, span.start_ms);
    } else if (span.type === "guardrail") {
      if (!steps["guardrail"]) {
        steps["guardrail"] = { type: "guardrail", name: "Guardrail", count: 0, duration_ms: 0, start_ms: span.start_ms };
      }
      steps["guardrail"].count++;
      steps["guardrail"].duration_ms += span.duration_ms;
      steps["guardrail"].start_ms = Math.min(steps["guardrail"].start_ms, span.start_ms);
    }
  }

  if (!steps["response"]) {
    const maxStart = allFlat.length > 0 ? Math.max(...allFlat.map((f) => f.span.start_ms + f.span.duration_ms)) : 0;
    steps["response"] = { type: "response", name: "Response", count: 1, duration_ms: 0, start_ms: maxStart };
  }

  return Object.values(steps).sort((a, b) => a.start_ms - b.start_ms);
}

const ATTR_GROUP_ORDER = [
  { prefix: "gen_ai.", label: "GenAI", color: "#8b5cf6", defaultOpen: true },
  { prefix: "tool.", label: "Tool", color: "#f59e0b", defaultOpen: true },
  { prefix: "http.", label: "HTTP", color: "#06b6d4", defaultOpen: false },
  { prefix: "aws.", label: "AWS", color: "#ec4899", defaultOpen: false },
];

function groupAttributes(attrs: Record<string, any>): { label: string; color: string; defaultOpen: boolean; entries: [string, any][] }[] {
  const groups: Record<string, [string, any][]> = {};
  const other: [string, any][] = [];

  for (const [k, v] of Object.entries(attrs)) {
    const match = ATTR_GROUP_ORDER.find((g) => k.startsWith(g.prefix));
    if (match) {
      if (!groups[match.prefix]) groups[match.prefix] = [];
      groups[match.prefix].push([k.slice(match.prefix.length), v]);
    } else {
      other.push([k, v]);
    }
  }

  const result: { label: string; color: string; defaultOpen: boolean; entries: [string, any][] }[] = [];
  for (const g of ATTR_GROUP_ORDER) {
    if (groups[g.prefix]?.length) {
      result.push({ label: g.label, color: g.color, defaultOpen: g.defaultOpen, entries: groups[g.prefix] });
    }
  }
  if (other.length) {
    result.push({ label: "Other", color: "#6b7280", defaultOpen: false, entries: other });
  }
  return result;
}

function AttrGroup({ group }: { group: { label: string; color: string; defaultOpen: boolean; entries: [string, any][] } }) {
  const [open, setOpen] = useState(group.defaultOpen);
  return (
    <div style={{ marginBottom: 4 }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer", fontSize: 10, color: group.color, fontWeight: 600 }}
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        {group.label}
        <span style={{ color: "var(--gray-600)", fontWeight: 400 }}>({group.entries.length})</span>
      </div>
      {open && (
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "1px 10px", paddingLeft: 14, marginTop: 2 }}>
          {group.entries.map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <span style={{ color: "var(--gray-500)", fontFamily: "'JetBrains Mono', monospace", fontSize: 10 }}>{k}</span>
              <span style={{ color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, wordBreak: "break-all" }}>
                {typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4)) : String(v)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const LLM_EVENT_STYLES: Record<string, { label: string; color: string; icon: string }> = {
  "gen_ai.input.message": { label: "Input", color: "#0073bb", icon: "\u25B6" },
  "gen_ai.choice": { label: "Output", color: "#8b5cf6", icon: "\u25C0" },
  "gen_ai.tool_call": { label: "Tool Use", color: "#06b6d4", icon: "\u2699" },
  "gen_ai.tool.message": { label: "Tool Result", color: "#f59e0b", icon: "\u2692" },
  "gen_ai.message": { label: "Message", color: "#6b7280", icon: "\u25CF" },
};

function LLMEventSection({ events }: { events: NonNullable<Span["events"]> }) {
  const llmEvents = events.filter((ev) => ev.name in LLM_EVENT_STYLES);
  const otherEvents = events.filter((ev) => !(ev.name in LLM_EVENT_STYLES));

  return (
    <div style={{ marginTop: 6, borderTop: "1px solid var(--gray-700)", paddingTop: 4 }}>
      {llmEvents.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: otherEvents.length ? 6 : 0 }}>
          {llmEvents.map((ev, i) => {
            const style = LLM_EVENT_STYLES[ev.name];
            const content = ev.body || ev.attributes?.["gen_ai.content"] || "";
            return (
              <div key={i}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                  <span style={{ color: style.color, fontSize: 10 }}>{style.icon}</span>
                  <span style={{ color: style.color, fontWeight: 700, fontSize: 10 }}>{style.label}</span>
                  <span style={{ color: "var(--gray-600)", fontSize: 9 }}>{ev.timestamp_ms.toFixed(0)}ms</span>
                </div>
                {content && <StepContentBlock text={content} maxHeight={160} />}
              </div>
            );
          })}
        </div>
      )}
      {otherEvents.length > 0 && (
        <div>
          <div style={{ color: "var(--gray-500)", marginBottom: 2, fontSize: 10 }}>이벤트:</div>
          {otherEvents.map((ev, i) => (
            <div key={i} style={{ color: "var(--gray-400)", fontSize: 10 }}>
              <span style={{ color: "var(--amber)" }}>{ev.timestamp_ms.toFixed(0)}ms</span>{" "}
              {ev.name}
              {ev.body && <span style={{ color: "var(--gray-600)", marginLeft: 4 }}>{ev.body.slice(0, 80)}{ev.body.length > 80 ? "..." : ""}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SpanDetailPanel({ span }: { span: Span }) {
  const attrs = span.attributes || {};
  const entries = Object.entries(attrs);
  if (entries.length === 0 && !span.events?.length) return null;

  const groups = groupAttributes(attrs);

  return (
    <div
      style={{
        background: "var(--bg-secondary, #161e2d)",
        border: "1px solid var(--gray-700, #374151)",
        borderLeft: `3px solid ${SPAN_COLORS[span.type] || SPAN_COLORS.other}`,
        borderRadius: 6,
        padding: "8px 12px",
        marginLeft: 20,
        marginBottom: 4,
        fontSize: 11,
      }}
    >
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: entries.length ? 6 : 0 }}>
        <div>
          <span style={{ color: "var(--gray-500)" }}>Type: </span>
          <span style={{ color: SPAN_COLORS[span.type] || SPAN_COLORS.other, fontWeight: 600 }}>
            {SPAN_LABELS[span.type] || span.type}
          </span>
        </div>
        <div>
          <span style={{ color: "var(--gray-500)" }}>소요시간: </span>
          <span style={{ color: "var(--amber-light)", fontFamily: "'JetBrains Mono', monospace" }}>
            {span.duration_ms.toFixed(1)}ms
          </span>
        </div>
        {span.status && span.status !== "ok" && (
          <div>
            <span style={{ color: "var(--gray-500)" }}>상태: </span>
            <span style={{ color: "#ef4444" }}>{span.status}</span>
          </div>
        )}
      </div>
      {groups.length > 0 && (
        <div style={{ borderTop: "1px solid var(--gray-700)", paddingTop: 4, marginTop: 2 }}>
          {groups.map((g) => (
            <AttrGroup key={g.label} group={g} />
          ))}
        </div>
      )}
      {span.events && span.events.length > 0 && (
        <LLMEventSection events={span.events} />
      )}
    </div>
  );
}

function StepContentBlock({ text, maxHeight }: { text: string; maxHeight: number }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = text.length > 300;

  return (
    <div>
      <div
        style={{
          background: "var(--navy-darkest, #0f1b2d)",
          border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 4,
          padding: 8,
          maxHeight: expanded ? "none" : maxHeight,
          overflowY: expanded ? "auto" : "hidden",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          color: "var(--gray-200)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.5,
          position: "relative",
        }}
      >
        {text}
        {!expanded && isLong && (
          <div
            style={{
              position: "absolute",
              bottom: 0,
              left: 0,
              right: 0,
              height: 32,
              background: "linear-gradient(transparent, var(--navy-darkest, #0f1b2d))",
            }}
          />
        )}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            background: "none",
            border: "none",
            color: "var(--amber-light)",
            fontSize: 10,
            cursor: "pointer",
            padding: "2px 0",
            marginTop: 2,
          }}
        >
          {expanded ? "접기" : "더 보기"}
        </button>
      )}
    </div>
  );
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

// --- New Unified Components ---

interface TimelineRow {
  type: "real" | "pseudo";
  id: string;
  label?: string;
  content?: string;
  color?: string;
  span?: Span;
  depth?: number;
}

function buildTimelineRows(trace: Trace): TimelineRow[] {
  const rows: TimelineRow[] = [];

  if (trace.system_prompt) {
    rows.push({
      type: "pseudo",
      id: "system_prompt",
      label: `System Prompt (${trace.prompt_version?.toUpperCase() || "V1"})`,
      content: trace.system_prompt,
      color: "#6b7280",
    });
  }

  if (trace.prompt) {
    rows.push({
      type: "pseudo",
      id: "user_input",
      label: "User Input",
      content: trace.prompt,
      color: "#0073bb",
    });
  }

  const allFlat = flattenSpans(trace.spans || []);
  for (const { span, depth } of allFlat) {
    rows.push({ type: "real", id: span.span_id, span, depth });
  }

  if (trace.response) {
    rows.push({
      type: "pseudo",
      id: "assistant_response",
      label: "Assistant Response",
      content: trace.response,
      color: "#3b82f6",
    });
  }

  return rows;
}

function UnifiedMetadataBar({ trace }: { trace: Trace }) {
  const source = trace.span_source || "local";
  const ss = SOURCE_STYLES[source] || SOURCE_STYLES.local;
  const model = trace.model || trace.attributes?.["gen_ai.request.model"] || "";
  const shortModel = model.replace(/^global\.anthropic\./, "").replace(/^us\.amazon\./, "");
  const latency = trace.latency_ms ?? trace.duration_ms ?? 0;
  const tokenIn = trace.token_usage?.input_tokens || 0;
  const tokenOut = trace.token_usage?.output_tokens || 0;
  const allFlat = flattenSpans(trace.spans || []);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const copyId = (label: string, value: string) => {
    navigator.clipboard.writeText(value);
    setCopiedId(label);
    setTimeout(() => setCopiedId(null), 1500);
  };

  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        flexWrap: "wrap",
        alignItems: "center",
        marginBottom: 10,
        padding: "8px 12px",
        background: "var(--bg-tertiary, #0f172a)",
        borderRadius: 8,
        border: "1px solid var(--gray-700, #374151)",
        fontSize: 11,
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 4,
          background: ss.bg,
          color: ss.color,
          fontWeight: 700,
          fontSize: 10,
          letterSpacing: "0.03em",
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: ss.color }} />
        {ss.label}
      </span>

      {shortModel && (
        <span style={{ color: "var(--gray-300)", fontWeight: 600 }}>{shortModel}</span>
      )}

      {trace.prompt_version && (
        <span
          style={{
            padding: "1px 6px",
            borderRadius: 3,
            background: "rgba(245,158,11,0.12)",
            color: "var(--amber)",
            fontWeight: 700,
            fontSize: 10,
          }}
        >
          {trace.prompt_version.toUpperCase()}
        </span>
      )}

      <span
        style={{
          fontSize: 14,
          fontWeight: 700,
          color: "var(--amber-light)",
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {latency.toFixed(0)}ms
      </span>

      {(tokenIn > 0 || tokenOut > 0) && (
        <span style={{ fontSize: 11, color: "var(--gray-400)", fontFamily: "'JetBrains Mono', monospace" }}>
          <span style={{ color: "#3b82f6" }}>{tokenIn}</span>
          <span style={{ color: "var(--gray-500)" }}> 입력 / </span>
          <span style={{ color: "#8b5cf6" }}>{tokenOut}</span>
          <span style={{ color: "var(--gray-500)" }}> 출력</span>
        </span>
      )}

      <span style={{ color: "var(--gray-500)", fontSize: 10 }}>
        스팬 {allFlat.length}개
      </span>

      {trace.tools_used && trace.tools_used.length > 0 && (
        <div style={{ display: "flex", gap: 3 }}>
          {trace.tools_used.map((t) => (
            <span key={t} className="tool-badge">{t}</span>
          ))}
        </div>
      )}

      {trace.status === "error" && (
        <span style={{ padding: "1px 6px", borderRadius: 3, background: "rgba(239,68,68,0.15)", color: "#ef4444", fontSize: 10, fontWeight: 700 }}>
          ERROR
        </span>
      )}

      <span
        style={{ color: "var(--gray-500)", fontSize: 10, cursor: "pointer" }}
        title={trace.trace_id}
        onClick={() => copyId("trace", trace.trace_id)}
      >
        트레이스:{" "}
        <span style={{ color: copiedId === "trace" ? "#22c55e" : "var(--gray-400)", fontFamily: "'JetBrains Mono', monospace", transition: "color 0.2s" }}>
          {trace.trace_id.slice(0, 12)}...
        </span>
        <Copy size={9} style={{ marginLeft: 3, verticalAlign: "middle", color: copiedId === "trace" ? "#22c55e" : "var(--gray-600)" }} />
      </span>

      {trace.session_id && (
        <span
          style={{ color: "var(--gray-500)", fontSize: 10, cursor: "pointer" }}
          title={trace.session_id}
          onClick={() => copyId("session", trace.session_id!)}
        >
          세션:{" "}
          <span style={{ color: copiedId === "session" ? "#22c55e" : "var(--gray-400)", fontFamily: "'JetBrains Mono', monospace" }}>
            {trace.session_id.slice(0, 8)}...
          </span>
        </span>
      )}
    </div>
  );
}

function AgentStepSummaryStrip({ trace }: { trace: Trace }) {
  const steps = inferAgentSteps(trace.spans || []);
  if (steps.length === 0) return null;

  const totalDuration = steps.reduce((sum, s) => sum + s.duration_ms, 0);

  return (
    <div
      style={{
        background: "var(--bg-tertiary, #0f172a)",
        border: "1px solid var(--gray-700, #374151)",
        borderRadius: 6,
        padding: "6px 8px",
        marginBottom: 10,
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", height: 24, gap: 8 }}>
        <div style={{ display: "flex", gap: 2, flex: 1, alignItems: "center" }}>
          {steps.map((step) => {
            const widthPct = totalDuration > 0 ? Math.max(2, (step.duration_ms / totalDuration) * 100) : 100 / steps.length;
            const color = STEP_COLORS[step.type] || "#6b7280";

            return (
              <div
                key={step.type}
                style={{
                  flex: `${widthPct} 0 0`,
                  height: 18,
                  background: color,
                  borderRadius: 3,
                  opacity: 0.85,
                  minWidth: 4,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                  position: "relative",
                }}
                title={`${STEP_LABELS[step.type]}: ${step.duration_ms.toFixed(0)}ms (${step.count})`}
              >
                {widthPct > 18 && (
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      color: "rgba(255,255,255,0.8)",
                      textShadow: "0 1px 2px rgba(0,0,0,0.5)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {STEP_LABELS[step.type]} {widthPct.toFixed(0)}%
                  </span>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", gap: 6, fontSize: 10, color: "var(--gray-400)", whiteSpace: "nowrap" }}>
          {steps.map((step) => (
            <span key={step.type} style={{ display: "flex", alignItems: "center", gap: 2 }}>
              <span
                style={{
                  display: "inline-block",
                  width: 6,
                  height: 6,
                  borderRadius: 2,
                  background: STEP_COLORS[step.type] || "#6b7280",
                }}
              />
              {STEP_LABELS[step.type]}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function UnifiedTimelineHeader({ totalDuration }: { totalDuration: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        height: 20,
        fontSize: 10,
        color: "var(--gray-500)",
        borderBottom: "1px solid var(--gray-700, #374151)",
        marginBottom: 4,
      }}
    >
      <div style={{ width: 200, minWidth: 200, paddingLeft: 4 }}>스팬</div>
      <div style={{ flex: 1, display: "flex", justifyContent: "space-between", paddingRight: 4 }}>
        <span>0ms</span>
        <span>{(totalDuration / 4).toFixed(0)}ms</span>
        <span>{(totalDuration / 2).toFixed(0)}ms</span>
        <span>{((totalDuration * 3) / 4).toFixed(0)}ms</span>
        <span>{totalDuration.toFixed(0)}ms</span>
      </div>
      <div style={{ width: 70, minWidth: 70, textAlign: "right", paddingRight: 4 }}>토큰</div>
      <div style={{ width: 55, minWidth: 55, textAlign: "right", paddingRight: 4 }}>소요시간</div>
    </div>
  );
}

function UnifiedSpanRow({
  span,
  depth,
  traceStart,
  totalDuration,
  expanded,
  onToggle,
  hasChildren,
}: {
  span: Span;
  depth: number;
  traceStart: number;
  totalDuration: number;
  expanded: boolean;
  onToggle: () => void;
  hasChildren: boolean;
}) {
  const color = SPAN_COLORS[span.type] || SPAN_COLORS.other;
  const leftPct = totalDuration > 0 ? ((span.start_ms - traceStart) / totalDuration) * 100 : 0;
  const widthPct = totalDuration > 0 ? Math.max(0.5, (span.duration_ms / totalDuration) * 100) : 100;

  const inputTokens = span.attributes?.["gen_ai.usage.input_tokens"] || 0;
  const outputTokens = span.attributes?.["gen_ai.usage.output_tokens"] || 0;
  const hasTokens = inputTokens > 0 || outputTokens > 0;

  const hasExpandable = hasChildren || Object.keys(span.attributes || {}).length > 0 || (span.events?.length || 0) > 0;

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          height: 28,
          fontSize: 11,
          cursor: "pointer",
          borderRadius: 3,
          background: expanded ? "rgba(255,255,255,0.03)" : "transparent",
        }}
        onClick={onToggle}
      >
        <div
          style={{
            width: 200,
            minWidth: 200,
            paddingLeft: depth * 16 + 4,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            color: "var(--gray-300)",
            display: "flex",
            alignItems: "center",
            gap: 3,
          }}
        >
          {hasExpandable ? (
            expanded ? <ChevronDown size={10} style={{ color: "var(--gray-500)", flexShrink: 0 }} /> : <ChevronRight size={10} style={{ color: "var(--gray-500)", flexShrink: 0 }} />
          ) : (
            <span style={{ width: 10, flexShrink: 0 }} />
          )}
          {depth > 0 && (
            <span style={{ color: "var(--gray-600)", marginRight: 2 }}>{"└"}</span>
          )}
          <span
            style={{
              display: "inline-block",
              width: 7,
              height: 7,
              borderRadius: "50%",
              background: color,
              flexShrink: 0,
            }}
          />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }} title={span.name}>{span.name}</span>
          {span.status && span.status !== "ok" && (
            <span
              style={{
                padding: "1px 4px",
                borderRadius: 2,
                background: "rgba(239,68,68,0.2)",
                color: "#ef4444",
                fontSize: 9,
                marginLeft: "auto",
                flexShrink: 0,
              }}
            >
              ERR
            </span>
          )}
        </div>

        <div style={{ flex: 1, position: "relative", height: "100%" }}>
          <div
            style={{
              position: "absolute",
              left: `${leftPct}%`,
              width: `${widthPct}%`,
              top: 7,
              height: 14,
              background: `${color}cc`,
              borderRadius: 3,
              minWidth: 3,
            }}
            title={`${span.name}: ${span.duration_ms.toFixed(0)}ms`}
          />
        </div>

        <div
          style={{
            width: 70,
            minWidth: 70,
            textAlign: "right",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            paddingRight: 4,
            whiteSpace: "nowrap",
          }}
        >
          {hasTokens ? (
            <>
              <span style={{ color: "#3b82f6" }}>{inputTokens}</span>
              <span style={{ color: "var(--gray-600)" }}>/</span>
              <span style={{ color: "#8b5cf6" }}>{outputTokens}</span>
            </>
          ) : (
            <span style={{ color: "var(--gray-700)" }}>&mdash;</span>
          )}
        </div>

        <div
          style={{
            width: 55,
            minWidth: 55,
            textAlign: "right",
            fontFamily: "'JetBrains Mono', monospace",
            color: "var(--gray-400)",
            fontSize: 10,
            paddingRight: 4,
          }}
        >
          {span.duration_ms.toFixed(0)}ms
        </div>
      </div>
      {expanded && <SpanDetailPanel span={span} />}
    </>
  );
}

const PSEUDO_ICONS: Record<string, string> = {
  system_prompt: "\u2699",
  user_input: "\uD83D\uDC64",
  assistant_response: "\uD83E\uDD16",
};

function PseudoSpanRow({
  row,
  expanded,
  onToggle,
}: {
  row: TimelineRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const icon = PSEUDO_ICONS[row.id] || "\u25CF";

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          height: 32,
          fontSize: 11,
          cursor: "pointer",
          borderRadius: 4,
          background: expanded ? `${row.color}18` : `${row.color}0a`,
          borderLeft: `3px solid ${row.color || "var(--gray-600)"}`,
          marginBottom: 2,
          paddingLeft: 1,
        }}
        onClick={onToggle}
      >
        <div
          style={{
            width: 200,
            minWidth: 200,
            paddingLeft: 4,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            color: row.color || "var(--gray-400)",
            display: "flex",
            alignItems: "center",
            gap: 5,
            fontWeight: 600,
          }}
        >
          {expanded ? (
            <ChevronDown size={10} style={{ color: row.color || "var(--gray-500)", flexShrink: 0 }} />
          ) : (
            <ChevronRight size={10} style={{ color: row.color || "var(--gray-500)", flexShrink: 0 }} />
          )}
          <span style={{ fontSize: 11, flexShrink: 0 }}>{icon}</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{row.label}</span>
        </div>

        <div style={{ flex: 1, height: "100%", position: "relative" }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 15, height: 1, borderTop: `1px dashed ${row.color}44` }} />
        </div>

        <div style={{ width: 70, minWidth: 70, textAlign: "right", paddingRight: 4 }}>
          <span style={{ fontSize: 9, color: `${row.color}88`, fontStyle: "italic" }}>
            {row.id === "system_prompt" ? "prompt" : row.id === "user_input" ? "input" : "output"}
          </span>
        </div>
        <div style={{ width: 55, minWidth: 55 }} />
      </div>

      {expanded && row.content && (
        <div
          style={{
            paddingLeft: 24,
            paddingRight: 8,
            marginBottom: 6,
            borderLeft: `3px solid ${row.color}44`,
            marginLeft: 0,
          }}
        >
          <StepContentBlock
            text={row.content}
            maxHeight={row.id === "system_prompt" ? 120 : row.id === "assistant_response" ? 200 : 160}
          />
        </div>
      )}
    </>
  );
}

function UnifiedSpanTimeline({ trace }: { trace: Trace }) {
  const [expandedSpans, setExpandedSpans] = useState<Set<string>>(new Set());

  const allRows = buildTimelineRows(trace);
  const allFlat = flattenSpans(trace.spans || []);

  const realSpans = allFlat.map((f) => f.span);
  const traceStart = realSpans.length > 0 ? Math.min(...realSpans.map((s) => s.start_ms)) : 0;
  const traceEnd = realSpans.length > 0 ? Math.max(...realSpans.map((s) => s.start_ms + s.duration_ms)) : 0;
  const totalDuration = traceEnd - traceStart || 1;

  const toggleSpan = (id: string) => {
    setExpandedSpans((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (allRows.length === 0) {
    return (
      <div style={{ fontSize: 11, color: "var(--gray-500)", padding: 8 }}>
        No trace data available
      </div>
    );
  }

  return (
    <div>
      {realSpans.length > 0 && <UnifiedTimelineHeader totalDuration={totalDuration} />}

      {allRows.map((row) =>
        row.type === "pseudo" ? (
          <PseudoSpanRow
            key={row.id}
            row={row}
            expanded={expandedSpans.has(row.id)}
            onToggle={() => toggleSpan(row.id)}
          />
        ) : row.span ? (
          <UnifiedSpanRow
            key={row.id}
            span={row.span}
            depth={row.depth || 0}
            traceStart={traceStart}
            totalDuration={totalDuration}
            expanded={expandedSpans.has(row.span.span_id)}
            onToggle={() => toggleSpan(row.span!.span_id)}
            hasChildren={!!row.span.subsegments?.length}
          />
        ) : null
      )}
    </div>
  );
}

// --- Main Component ---

function TraceViewerImpl({ traces, selectedTrace, onSelectTrace, compact }: Props) {
  const displayTraces = compact ? traces.slice(0, 8) : traces;
  const [detailedTrace, setDetailedTrace] = useState<Trace | null>(null);

  useEffect(() => {
    if (!selectedTrace) {
      setDetailedTrace(null);
      return;
    }
    Promise.all([
      api.getTrace(selectedTrace.trace_id).catch(() => ({})),
      api.getPromptInfo().catch(() => null),
    ]).then(([detail, promptInfo]) => {
      const merged = { ...detail, ...selectedTrace };
      if (detail.spans?.length) merged.spans = detail.spans;
      if (detail.token_usage) merged.token_usage = detail.token_usage;
      if (detail.prompt && detail.prompt.length > (selectedTrace.prompt?.length || 0)) {
        merged.prompt = detail.prompt;
      }
      if (detail.response) merged.response = detail.response;
      if (promptInfo?.prompt && !merged.system_prompt) {
        merged.system_prompt = promptInfo.prompt;
        merged.prompt_version = merged.prompt_version || promptInfo.version;
      }
      setDetailedTrace(merged);
    });
  }, [selectedTrace]);

  const traceToShow = detailedTrace || selectedTrace;

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <Zap size={14} />
          트레이스
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          트레이스 {traces.length}개
        </span>
      </div>

      <div className="panel-body">
        {traces.length === 0 ? (
          <div className="empty-state">
            <Zap size={40} />
            <p>아직 트레이스가 없습니다</p>
            <p className="empty-hint">채팅을 보내면 OTEL 트레이스가 자동 수집됩니다</p>
          </div>
        ) : traceToShow && selectedTrace ? (
          <div>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => onSelectTrace(null)}
              style={{ marginBottom: 10 }}
            >
              ← 목록으로
            </button>

            {/* Unified Metadata Bar */}
            <UnifiedMetadataBar trace={traceToShow} />

            {/* Agent Step Summary Strip */}
            <AgentStepSummaryStrip trace={traceToShow} />

            {/* Unified Span Timeline */}
            <div
              style={{
                background: "var(--bg-tertiary, #0f172a)",
                borderRadius: 6,
                border: "1px solid var(--gray-700, #374151)",
                padding: "6px 4px",
                overflow: "auto",
              }}
            >
              <UnifiedSpanTimeline trace={traceToShow} />
            </div>
          </div>
        ) : (
          <div className="trace-list">
            {displayTraces.map((trace) => {
              const model = (trace.model || "").replace(/^global\.anthropic\./, "").replace(/^us\.amazon\./, "");
              const spanCount = trace.spans?.length;
              return (
                <div
                  key={trace.trace_id}
                  className="trace-item"
                  onClick={() => onSelectTrace(trace)}
                >
                  <span className={`trace-status ${trace.status === "error" || trace.error ? "error" : "ok"}`} />
                  <span className="trace-id">
                    {trace.trace_id.slice(0, 8)}
                  </span>
                  {trace.prompt_version && (
                    <span style={{
                      fontSize: 9, padding: "0px 4px", borderRadius: 3,
                      background: "rgba(245,158,11,0.12)", color: "var(--amber)",
                      fontWeight: 700, flexShrink: 0,
                    }}>
                      {trace.prompt_version.toUpperCase()}
                    </span>
                  )}
                  <span style={{ fontSize: 11, color: "var(--gray-500)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {trace.prompt ? trace.prompt.slice(0, 30) + (trace.prompt.length > 30 ? "..." : "") : "\u2014"}
                  </span>
                  {model && (
                    <span style={{ fontSize: 9, color: "var(--gray-500)", fontFamily: "'JetBrains Mono', monospace", flexShrink: 0 }}>
                      {model}
                    </span>
                  )}
                  {spanCount != null && spanCount > 0 && (
                    <span style={{ fontSize: 9, color: "var(--gray-600)", flexShrink: 0 }}>
                      {spanCount}sp
                    </span>
                  )}
                  {trace.tools_used?.length ? (
                    <span className="tool-badge">도구 {trace.tools_used.length}개</span>
                  ) : null}
                  {trace.token_usage && (
                    <span style={{ fontSize: 9, fontFamily: "'JetBrains Mono', monospace", color: "var(--gray-500)" }}>
                      {trace.token_usage.total_tokens ?? ((trace.token_usage.input_tokens || 0) + (trace.token_usage.output_tokens || 0))} 토큰
                    </span>
                  )}
                  <span className="trace-latency">{trace.latency_ms ?? trace.duration_ms ?? 0}ms</span>
                  <span style={{ fontSize: 10, color: "var(--gray-600)" }}>
                    {formatTime(trace.timestamp)}
                  </span>
                  <ChevronRight size={12} style={{ color: "var(--gray-600)" }} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(TraceViewerImpl);
