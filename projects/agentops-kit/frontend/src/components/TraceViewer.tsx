import { useState, useEffect, memo } from "react";
import { Zap, ChevronRight, ChevronDown, Copy } from "lucide-react";
import { Trace, Span, TraceSSEEvent } from "../types";
import { api } from "../api";

interface Props {
  traces: Trace[];
  selectedTrace: Trace | null;
  onSelectTrace: (trace: Trace | null) => void;
  onHoursChange?: (hours: number) => void;
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
          {group.entries.map(([k, v]) => {
            const strVal = typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4)) : String(v);
            const isJson = typeof v === "string" && (v.startsWith("{") || v.startsWith("["));
            let parsed: any = null;
            if (isJson) { try { parsed = JSON.parse(v); } catch {} }
            return (
              <div key={k} style={{ display: "contents" }}>
                <span style={{ color: "var(--gray-500)", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, alignSelf: parsed ? "start" : "center" }}>{k}</span>
                {parsed ? (
                  <pre style={{
                    margin: 0, padding: "3px 6px", borderRadius: 3, fontSize: 10,
                    whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.4,
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid var(--gray-700, #374151)",
                    color: "var(--gray-300, #d1d5db)",
                    fontFamily: "'JetBrains Mono', monospace",
                    maxHeight: 200, overflowY: "auto",
                  }}>
                    {JSON.stringify(parsed, null, 2)}
                  </pre>
                ) : (
                  <span style={{ color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, wordBreak: "break-all" }}>
                    {strVal}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const LLM_EVENT_STYLES: Record<string, { label: string; color: string; icon: string }> = {
  "gen_ai.input.message": { label: "Input", color: "#0073bb", icon: "▶" },
  "gen_ai.choice": { label: "Output", color: "#8b5cf6", icon: "◀" },
  "gen_ai.tool_call": { label: "Tool Use", color: "#06b6d4", icon: "⚙" },
  "gen_ai.tool.message": { label: "Tool Result", color: "#f59e0b", icon: "⚒" },
  "gen_ai.message": { label: "Message", color: "#6b7280", icon: "●" },
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
            const hasRoles = /^\[(system|user|assistant|tool)\]\s/m.test(content);
            const isToolCall = ev.name === "gen_ai.tool_call";
            const isToolResult = ev.name === "gen_ai.tool.message";
            return (
              <div key={i}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                  <span style={{ color: style.color, fontSize: 10 }}>{style.icon}</span>
                  <span style={{ color: style.color, fontWeight: 700, fontSize: 10 }}>{style.label}</span>
                  <span style={{ color: "var(--gray-600)", fontSize: 9 }}>{ev.timestamp_ms.toFixed(0)}ms</span>
                </div>
                {content && ((isToolCall || isToolResult)
                  ? <JsonContentBlock text={content} maxHeight={160} />
                  : hasRoles
                  ? <RoleMessageBlock text={content} maxHeight={200} />
                  : <StepContentBlock text={content} maxHeight={160} />
                )}
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

const ROLE_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  system: { label: "System", color: "#6b7280", bg: "rgba(107,114,128,0.08)" },
  user: { label: "User", color: "#3b82f6", bg: "rgba(59,130,246,0.08)" },
  assistant: { label: "Assistant", color: "#8b5cf6", bg: "rgba(139,92,246,0.08)" },
  tool: { label: "Tool", color: "#f59e0b", bg: "rgba(245,158,11,0.08)" },
};

function parseRoleMessages(text: string): { role: string; content: string }[] | null {
  const regex = /^\[(system|user|assistant|tool)\]\s/m;
  if (!regex.test(text)) return null;
  const parts: { role: string; content: string }[] = [];
  const lines = text.split("\n");
  let currentRole = "";
  let currentContent: string[] = [];
  for (const line of lines) {
    const match = line.match(/^\[(system|user|assistant|tool)\]\s?(.*)/);
    if (match) {
      if (currentRole) {
        parts.push({ role: currentRole, content: currentContent.join("\n") });
      }
      currentRole = match[1];
      currentContent = match[2] ? [match[2]] : [];
    } else {
      currentContent.push(line);
    }
  }
  if (currentRole) {
    parts.push({ role: currentRole, content: currentContent.join("\n") });
  }
  return parts.length > 0 ? parts : null;
}

function RoleMessageBlock({ text, maxHeight }: { text: string; maxHeight: number }) {
  const [expanded, setExpanded] = useState(false);
  const messages = parseRoleMessages(text);
  if (!messages) return <StepContentBlock text={text} maxHeight={maxHeight} />;

  const totalLen = messages.reduce((acc, m) => acc + m.content.length, 0);
  const isLong = totalLen > 400;

  return (
    <div>
      <div style={{ maxHeight: expanded ? "none" : maxHeight, overflowY: expanded ? "auto" : "hidden", position: "relative" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {messages.map((msg, i) => {
            const rs = ROLE_STYLES[msg.role] || ROLE_STYLES.user;
            let displayContent = msg.content;
            if (msg.role === "tool" || msg.role === "assistant") {
              try {
                const parsed = JSON.parse(msg.content);
                displayContent = JSON.stringify(parsed, null, 2);
              } catch { /* keep as-is */ }
            }
            return (
              <div key={i} style={{ background: rs.bg, borderRadius: 4, padding: "4px 8px", borderLeft: `2px solid ${rs.color}` }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: rs.color, marginBottom: 2 }}>{rs.label}</div>
                <div style={{
                  fontSize: 10, color: "var(--gray-200)", whiteSpace: "pre-wrap", wordBreak: "break-word",
                  fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.5,
                  maxHeight: msg.role === "system" ? 40 : undefined, overflow: msg.role === "system" ? "hidden" : undefined,
                }}>
                  {displayContent.slice(0, 1500)}{displayContent.length > 1500 ? "..." : ""}
                </div>
              </div>
            );
          })}
        </div>
        {!expanded && isLong && (
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 32, background: "linear-gradient(transparent, var(--bg-secondary, #1e293b))" }} />
        )}
      </div>
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{ background: "none", border: "none", color: "var(--amber-light)", fontSize: 10, cursor: "pointer", padding: "2px 0", marginTop: 2 }}
        >
          {expanded ? "접기" : "더 보기"}
        </button>
      )}
    </div>
  );
}

function JsonContentBlock({ text, maxHeight }: { text: string; maxHeight: number }) {
  const [expanded, setExpanded] = useState(false);
  let display = text;
  try {
    const parsed = JSON.parse(text);
    display = JSON.stringify(parsed, null, 2);
  } catch {
    const jsonStart = text.search(/\{["\w]/);
    if (jsonStart > 0) {
      const prefix = text.slice(0, jsonStart).trim();
      const jsonPart = text.slice(jsonStart);
      try {
        const parsed = JSON.parse(jsonPart);
        display = (prefix ? prefix + "\n" : "") + JSON.stringify(parsed, null, 2);
      } catch { /* keep as-is */ }
    }
  }
  const isLong = display.length > 400;
  return (
    <div>
      <pre style={{
        margin: 0, padding: "6px 8px", borderRadius: 4, fontSize: 10,
        whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5,
        background: "rgba(255,255,255,0.03)", border: "1px solid var(--gray-700, #374151)",
        color: "var(--gray-300)", fontFamily: "'JetBrains Mono', monospace",
        maxHeight: expanded ? "none" : maxHeight, overflow: expanded ? "auto" : "hidden",
      }}>
        {display.slice(0, 3000)}
      </pre>
      {isLong && (
        <button onClick={() => setExpanded(!expanded)} style={{ background: "none", border: "none", color: "var(--amber-light)", fontSize: 10, cursor: "pointer", padding: "2px 0", marginTop: 2 }}>
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
  system_prompt: "⚙",
  user_input: "👤",
  assistant_response: "🤖",
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
  const icon = PSEUDO_ICONS[row.id] || "●";

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

function SpanAttributeRow({ name, value }: { name: string; value: any }) {
  const strVal = typeof value === "string" ? value : JSON.stringify(value);
  const isJson = strVal.startsWith("{") || strVal.startsWith("[");
  const isError = strVal.includes("error") || strVal.includes("Error") || strVal.includes("500");

  let parsed: any = null;
  if (isJson) {
    try { parsed = JSON.parse(strVal); } catch {}
  }

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ color: "var(--gray-600, #6b7280)", fontSize: 10, marginBottom: 2 }}>{name}</div>
      {parsed ? (
        <pre style={{
          margin: 0, padding: "4px 8px", borderRadius: 3, fontSize: 10,
          whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.5,
          background: isError ? "rgba(239,68,68,0.08)" : "rgba(255,255,255,0.03)",
          border: `1px solid ${isError ? "rgba(239,68,68,0.2)" : "var(--gray-700, #374151)"}`,
          color: isError ? "#fca5a5" : "var(--gray-400, #9ca3af)",
        }}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      ) : (
        <span style={{
          wordBreak: "break-all",
          color: isError ? "#fca5a5" : "var(--gray-400, #9ca3af)",
        }}>
          {strVal}
        </span>
      )}
    </div>
  );
}

function GanttTimeline({ trace }: { trace: Trace }) {
  const [expandedSpan, setExpandedSpan] = useState<string | null>(null);
  const [labelWidth, setLabelWidth] = useState(180);
  const dragRef = { startX: 0, startWidth: 0 };

  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragRef.startX = e.clientX;
    dragRef.startWidth = labelWidth;
    const onMove = (ev: MouseEvent) => {
      const newWidth = Math.max(80, Math.min(400, dragRef.startWidth + ev.clientX - dragRef.startX));
      setLabelWidth(newWidth);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const allSpans = trace.spans ? flattenSpans(trace.spans) : [];
  const totalDuration = trace.duration_ms || trace.latency_ms || 1;

  const axisTicks = 5;
  const tickInterval = totalDuration / axisTicks;
  const timeLabels = Array.from({ length: axisTicks + 1 }, (_, i) => {
    const ms = i * tickInterval;
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
  });

  return (
    <div>
      <style>{`
  @keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(400%); }
  }
`}</style>
      {/* Time axis (right side only) */}
      <div style={{ display: "flex", marginBottom: 4 }}>
        <div style={{ width: labelWidth, flexShrink: 0, position: "relative" }}>
          <div
            onMouseDown={onResizeStart}
            style={{
              position: "absolute", right: 0, top: 0, bottom: 0, width: 4,
              cursor: "col-resize", background: "transparent",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--gray-600, #6b7280)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          />
        </div>
        <div style={{
          flex: 1, height: 20,
          borderBottom: "1px solid var(--gray-700, #374151)",
          display: "flex", justifyContent: "space-between",
          fontSize: 9, color: "var(--gray-600, #6b7280)", padding: "0 4px",
        }}>
          {timeLabels.map((label, i) => <span key={i}>{label}</span>)}
        </div>
      </div>

      {/* Spans */}
      <div>
        {allSpans.map(({ span, depth }, idx) => {
          const leftPct = (span.start_ms / totalDuration) * 100;
          const widthPct = Math.max((span.duration_ms / totalDuration) * 100, 0.5);
          const color = SPAN_COLORS[span.type] || SPAN_COLORS.other;
          const isExpanded = expandedSpan === span.span_id;
          const isRunning = span.status === "running";
          const displayName = span.name.replace(/^(strands\.telemetry\.|botocore\.)/, "");
          const isRoot = depth === 0;
          const isNewGroup = idx === 0 || allSpans[idx - 1].depth < depth || (depth === 1 && allSpans[idx - 1].depth <= depth && span.parent_span_id !== allSpans[idx - 1].span.parent_span_id);

          return (
            <div key={span.span_id}>
              <div
                onClick={() => setExpandedSpan(isExpanded ? null : span.span_id)}
                style={{
                  display: "flex", alignItems: "center", height: 32, cursor: "pointer",
                  borderBottom: "1px solid var(--gray-800, #1f2937)",
                  marginTop: isRoot || isNewGroup ? 8 : 0,
                  borderTop: isRoot ? "1px solid var(--gray-700, #374151)" : undefined,
                }}
              >
                {/* Span name (left) */}
                <div
                  title={displayName}
                  style={{
                    width: labelWidth, flexShrink: 0, position: "relative",
                    fontSize: 11, color,
                    display: "flex", alignItems: "center", height: 32,
                    paddingLeft: depth * 14 + 4,
                  }}
                >
                  {/* Tree connector lines (absolute, no layout impact) */}
                  {depth > 0 && (
                    <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, display: "flex", alignItems: "stretch" }}>
                      {Array.from({ length: depth - 1 }, (_, i) => (
                        <span key={i} style={{ width: 14, borderLeft: "1px solid var(--gray-700, #374151)" }} />
                      ))}
                      <span style={{ width: 14, borderLeft: "1px solid var(--gray-700, #374151)", borderBottom: "1px solid var(--gray-700, #374151)", borderBottomLeftRadius: 3, height: "50%" }} />
                    </span>
                  )}
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {displayName}
                  </span>
                  <span style={{ color: "var(--gray-600, #6b7280)", marginLeft: 4, fontSize: 9, flexShrink: 0 }}>
                    {span.duration_ms >= 1000 ? `${(span.duration_ms / 1000).toFixed(1)}s` : `${Math.round(span.duration_ms)}ms`}
                  </span>
                </div>

                {/* Gantt bar (right) */}
                <div style={{ flex: 1, position: "relative", height: 14 }}>
                  <div style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: 14,
                    background: isRunning ? `linear-gradient(90deg, ${color}33, ${color}11)` : `${color}22`,
                    border: `1px solid ${isRunning ? color : `${color}66`}`,
                    borderRadius: 3,
                    minWidth: 4,
                    overflow: isRunning ? "hidden" : undefined,
                  }}>
                    {isRunning && (
                      <div style={{
                        position: "absolute", top: 0, left: 0, bottom: 0, width: "30%",
                        background: `linear-gradient(90deg, transparent, ${color}44, transparent)`,
                        animation: "shimmer 1.5s infinite",
                      }} />
                    )}
                  </div>
                </div>
              </div>

              {/* Expanded detail panel */}
              {isExpanded && (
                <div style={{
                  marginLeft: labelWidth, marginBottom: 8, padding: "8px 12px",
                  background: "var(--bg-secondary, #1e293b)", borderRadius: 4,
                  border: "1px solid var(--gray-700, #374151)", fontSize: 11,
                }}>
                  {span.attributes && Object.keys(span.attributes).length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ color: "var(--gray-500)", marginBottom: 4 }}>Attributes:</div>
                      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 12px", alignItems: "baseline" }}>
                        {Object.entries(span.attributes).map(([k, v]) => {
                          const strVal = typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4)) : String(v);
                          const isJson = typeof v === "string" && (strVal.startsWith("{") || strVal.startsWith("["));
                          let parsed: any = null;
                          if (isJson) { try { parsed = JSON.parse(strVal); } catch {} }
                          const isError = strVal.includes("error") || strVal.includes("Error") || strVal.includes("500");
                          return (
                            <div key={k} style={{ display: "contents" }}>
                              <span style={{ color: "var(--gray-500)", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, whiteSpace: "nowrap" }}>{k}</span>
                              {parsed ? (
                                <pre style={{
                                  margin: 0, padding: "3px 6px", borderRadius: 3, fontSize: 10,
                                  whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.4,
                                  background: isError ? "rgba(239,68,68,0.08)" : "rgba(255,255,255,0.03)",
                                  border: `1px solid ${isError ? "rgba(239,68,68,0.2)" : "var(--gray-700, #374151)"}`,
                                  color: isError ? "#fca5a5" : "var(--gray-300, #d1d5db)",
                                  fontFamily: "'JetBrains Mono', monospace",
                                  maxHeight: 200, overflowY: "auto",
                                }}>
                                  {JSON.stringify(parsed, null, 2)}
                                </pre>
                              ) : (
                                <span style={{
                                  color: isError ? "#fca5a5" : "var(--gray-300, #d1d5db)",
                                  fontFamily: "'JetBrains Mono', monospace", fontSize: 10, wordBreak: "break-all",
                                }}>
                                  {strVal}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {span.events && span.events.length > 0 && (
                    <div>
                      <div style={{ color: "var(--gray-500)", marginBottom: 4 }}>Events:</div>
                      {span.events.map((ev, i) => {
                        const content = ev.body || "";
                        const evStyle = LLM_EVENT_STYLES[ev.name];
                        const hasRoles = /^\[(system|user|assistant|tool)\]\s/m.test(content);
                        const isToolCall = ev.name === "gen_ai.tool_call";
                        const isToolResult = ev.name === "gen_ai.tool.message";
                        return (
                          <div key={i} style={{ marginBottom: 6 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                              {evStyle && <span style={{ color: evStyle.color, fontSize: 10 }}>{evStyle.icon}</span>}
                              <span style={{ color: evStyle?.color || "var(--gray-500)", fontWeight: 600, fontSize: 10 }}>{evStyle?.label || ev.name}</span>
                              <span style={{ color: "var(--gray-600)", fontSize: 9 }}>{ev.timestamp_ms?.toFixed(0)}ms</span>
                            </div>
                            {content && ((isToolCall || isToolResult)
                              ? <JsonContentBlock text={content} maxHeight={160} />
                              : hasRoles
                              ? <RoleMessageBlock text={content} maxHeight={200} />
                              : <StepContentBlock text={content} maxHeight={160} />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{
        display: "flex", gap: 16, marginTop: 16, paddingTop: 12,
        borderTop: "1px solid var(--gray-700, #374151)", fontSize: 10,
      }}>
        {Object.entries(SPAN_COLORS).filter(([k]) => k !== "cost" && k !== "other").map(([type, color]) => (
          <div key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ width: 10, height: 10, background: color, borderRadius: 2 }} />
            <span style={{ color: "var(--gray-500)" }}>{SPAN_LABELS[type]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


// --- Main Component ---

function TraceViewerImpl({ traces, selectedTrace, onSelectTrace, onHoursChange, compact }: Props) {
  const [selectedHours, setSelectedHours] = useState(6);
  const TIME_PRESETS = [
    { label: "1h", value: 1 },
    { label: "6h", value: 6 },
    { label: "24h", value: 24 },
    { label: "7d", value: 168 },
  ];
  const [liveTraces, setLiveTraces] = useState<Map<string, Trace>>(new Map());
  const liveTraceList = Array.from(liveTraces.values());
  const displayTraces = compact
    ? [...liveTraceList, ...traces].slice(0, 8)
    : [...liveTraceList, ...traces];
  const [detailedTrace, setDetailedTrace] = useState<Trace | null>(null);

  useEffect(() => {
    const disconnect = api.connectTraceStream((event: TraceSSEEvent) => {
      setLiveTraces((prev) => {
        const next = new Map(prev);

        switch (event.type) {
          case "trace_start":
            next.set(event.data.trace_id, {
              trace_id: event.data.trace_id,
              prompt: event.data.prompt,
              model: event.data.model,
              timestamp: event.data.timestamp || new Date().toISOString(),
              status: "live",
              spans: [],
              tools_used: [],
              span_source: "otel",
            });
            break;

          case "span_start": {
            const t = next.get(event.data.trace_id);
            if (t && t.spans) {
              t.spans = [...t.spans, {
                span_id: event.data.span_id || "",
                name: event.data.name || "",
                type: event.data.span_type || "other",
                start_ms: event.data.start_ms || 0,
                duration_ms: 0,
                status: "running",
              }];
              if (event.data.span_type === "tool" && event.data.name) {
                t.tools_used = [...(t.tools_used || []), event.data.name];
              }
            }
            break;
          }

          case "span_end": {
            const t = next.get(event.data.trace_id);
            if (t && t.spans) {
              t.spans = t.spans.map((s) =>
                s.span_id === event.data.span_id
                  ? { ...s, duration_ms: event.data.duration_ms || 0, status: event.data.status || "ok" }
                  : s
              );
            }
            break;
          }

          case "trace_end": {
            next.delete(event.data.trace_id);
            break;
          }
        }

        return next;
      });
    });

    return () => disconnect();
  }, []);

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

            {/* Clean Summary Bar */}
            <div style={{
              display: "flex", gap: 20, padding: "10px 12px",
              background: "var(--bg-secondary, #1e293b)", borderRadius: 6, marginBottom: 12,
              fontSize: 11, alignItems: "center", flexWrap: "wrap",
            }}>
              <div><span style={{ color: "var(--gray-600, #6b7280)" }}>Duration</span>{" "}<span style={{ color: "var(--gray-100, #f1f5f9)" }}>{(traceToShow.duration_ms || 0) >= 1000 ? `${((traceToShow.duration_ms || 0) / 1000).toFixed(1)}s` : `${traceToShow.duration_ms || 0}ms`}</span></div>
              <div><span style={{ color: "var(--gray-600, #6b7280)" }}>Model</span>{" "}<span style={{ color: "#a5b4fc" }}>{(traceToShow.model || "").replace(/^global\.anthropic\./, "").replace(/^us\.amazon\./, "")}</span></div>
              <div><span style={{ color: "var(--gray-600, #6b7280)" }}>Tokens</span>{" "}<span style={{ color: "var(--gray-100, #f1f5f9)" }}>{traceToShow.token_usage?.input_tokens || 0} in / {traceToShow.token_usage?.output_tokens || 0} out</span></div>
              <div><span style={{ color: "var(--gray-600, #6b7280)" }}>Tools</span>{" "}<span style={{ color: "#fbbf24" }}>{traceToShow.tools_used?.length || 0}</span></div>
              {traceToShow.prompt_version && <div><span style={{ color: "var(--gray-600, #6b7280)" }}>Version</span>{" "}<span style={{ color: "var(--gray-500)" }}>{traceToShow.prompt_version}</span></div>}
            </div>

            {/* Agent Step Summary Strip */}
            <AgentStepSummaryStrip trace={traceToShow} />

            {/* Gantt Timeline */}
            <div
              style={{
                background: "var(--bg-tertiary, #0f172a)",
                borderRadius: 6,
                border: "1px solid var(--gray-700, #374151)",
                padding: "6px 4px",
                overflow: "auto",
              }}
            >
              <GanttTimeline trace={traceToShow} />
            </div>
          </div>
        ) : (
          <div className="trace-list">
            {/* Time range filter */}
            <div style={{ display: "flex", gap: 6, marginBottom: 12, alignItems: "center" }}>
              <span style={{ fontSize: 11, color: "var(--gray-500)" }}>Time:</span>
              {TIME_PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => {
                    setSelectedHours(p.value);
                    onHoursChange?.(p.value);
                  }}
                  style={{
                    padding: "3px 10px",
                    borderRadius: 4,
                    border: `1px solid ${selectedHours === p.value ? "#6366f1" : "var(--gray-700, #374151)"}`,
                    background: selectedHours === p.value ? "#312e81" : "var(--bg-secondary, #1e293b)",
                    color: selectedHours === p.value ? "#a5b4fc" : "var(--gray-500)",
                    fontSize: 11,
                    cursor: "pointer",
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Table header */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "1fr 160px 60px 60px",
              gap: 8,
              padding: "6px 8px",
              fontSize: 10,
              color: "var(--gray-600, #6b7280)",
              borderBottom: "1px solid var(--gray-700, #374151)",
            }}>
              <span>Prompt</span>
              <span>Tools</span>
              <span>Tokens</span>
              <span>Latency</span>
            </div>

            {/* Table rows */}
            {displayTraces.map((trace) => {
              const isLive = trace.status === "live";
              const totalTokens = trace.token_usage
                ? (trace.token_usage.total_tokens ?? ((trace.token_usage.input_tokens || 0) + (trace.token_usage.output_tokens || 0)))
                : 0;
              const latency = trace.latency_ms ?? trace.duration_ms ?? 0;

              return (
                <div
                  key={trace.trace_id}
                  onClick={() => onSelectTrace(trace)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 160px 60px 60px",
                    gap: 8,
                    padding: "8px",
                    borderBottom: "1px solid var(--gray-800, #1e293b)",
                    alignItems: "center",
                    cursor: "pointer",
                    background: isLive ? "#1e1b4b" : "transparent",
                    borderRadius: 4,
                    marginTop: 2,
                  }}
                >
                  {/* Prompt */}
                  <span style={{
                    fontSize: 12,
                    color: "var(--gray-100, #f1f5f9)",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}>
                    {trace.prompt || "—"}
                  </span>

                  {/* Tools */}
                  <div style={{ display: "flex", gap: 3, flexWrap: "wrap", overflow: "hidden" }}>
                    {(trace.tools_used || []).slice(0, 3).map((tool) => (
                      <span key={tool} style={{
                        padding: "1px 5px",
                        borderRadius: 2,
                        background: "rgba(245,158,11,0.08)",
                        color: "#fbbf24",
                        fontSize: 9,
                        border: "1px solid rgba(245,158,11,0.25)",
                        whiteSpace: "nowrap",
                      }}>
                        {tool.replace(/^(query_|check_|get_|analyze_)/, "")}
                      </span>
                    ))}
                  </div>

                  {/* Tokens */}
                  <span style={{ fontSize: 11, color: "var(--gray-500)", fontFamily: "'JetBrains Mono', monospace" }}>
                    {totalTokens > 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : totalTokens || "—"}
                  </span>

                  {/* Latency */}
                  <span style={{
                    fontSize: 11,
                    color: "var(--gray-500)",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {latency > 1000 ? `${(latency / 1000).toFixed(1)}s` : `${Math.round(latency)}ms`}
                  </span>

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
