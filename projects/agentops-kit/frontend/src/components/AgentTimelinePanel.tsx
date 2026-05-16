import { useState, useEffect } from "react";
import { GitBranch, ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../api";
import { Trace } from "../types";

interface AgentStep {
  step_index: number;
  type: "llm_call" | "tool_selection" | "tool_execution" | "a2a_handoff" | "guardrail" | "response";
  name: string;
  duration_ms: number;
  start_ms: number;
  details: Record<string, any>;
}

interface AgentTurnTimeline {
  turn_id: string;
  trace_id: string;
  timestamp: string;
  total_duration_ms: number;
  steps: AgentStep[];
  tools_used: string[];
  prompt_version: string;
}

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

function StepBar({
  step,
  totalDuration,
}: {
  step: AgentStep;
  totalDuration: number;
}) {
  const [hovered, setHovered] = useState(false);
  const color = STEP_COLORS[step.type] || "#6b7280";
  const leftPct = totalDuration > 0 ? (step.start_ms / totalDuration) * 100 : 0;
  const widthPct = totalDuration > 0 ? Math.max(1, (step.duration_ms / totalDuration) * 100) : 100;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        height: 28,
        fontSize: 11,
        position: "relative",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Step label */}
      <div
        style={{
          width: 140,
          minWidth: 140,
          paddingLeft: 8,
          display: "flex",
          alignItems: "center",
          gap: 6,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: 2,
            background: color,
            flexShrink: 0,
          }}
        />
        <span style={{ color: "var(--gray-300)", fontSize: 10 }}>
          {step.name}
        </span>
      </div>

      {/* Bar area */}
      <div style={{ flex: 1, position: "relative", height: "100%" }}>
        <div
          style={{
            position: "absolute",
            left: `${leftPct}%`,
            width: `${widthPct}%`,
            top: 6,
            height: 16,
            background: `${color}cc`,
            borderRadius: 3,
            minWidth: 4,
            opacity: hovered ? 1 : 0.85,
            transition: "opacity 0.15s",
          }}
        />
        {hovered && (
          <div
            style={{
              position: "absolute",
              left: `${Math.min(leftPct + widthPct + 1, 70)}%`,
              top: 0,
              background: "var(--bg-secondary, #161e2d)",
              border: "1px solid var(--gray-600)",
              borderRadius: 4,
              padding: "3px 8px",
              fontSize: 10,
              color: "var(--gray-300)",
              whiteSpace: "nowrap",
              zIndex: 10,
              pointerEvents: "none",
            }}
          >
            <strong>{step.name}</strong> · {step.duration_ms.toFixed(0)}ms ·{" "}
            <span style={{ color }}>{STEP_LABELS[step.type]}</span>
            {step.details?.model && (
              <span style={{ marginLeft: 6, color: "var(--gray-500)" }}>
                model={step.details.model}
              </span>
            )}
            {step.details?.tool && (
              <span style={{ marginLeft: 6, color: "var(--gray-500)" }}>
                tool={step.details.tool}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Duration */}
      <div
        style={{
          width: 60,
          minWidth: 60,
          textAlign: "right",
          fontFamily: "'JetBrains Mono', monospace",
          color: "var(--gray-400)",
          fontSize: 10,
          paddingRight: 4,
        }}
      >
        {step.duration_ms.toFixed(0)}ms
      </div>
    </div>
  );
}

function TurnTimeline({ timeline }: { timeline: AgentTurnTimeline }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        background: "var(--bg-tertiary, #0f172a)",
        borderRadius: 6,
        marginBottom: 8,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "8px 12px",
          cursor: "pointer",
          gap: 12,
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown size={14} style={{ color: "var(--gray-500)" }} />
        ) : (
          <ChevronRight size={14} style={{ color: "var(--gray-500)" }} />
        )}

        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "var(--gray-400)",
          }}
        >
          {timeline.trace_id.slice(0, 8)}
        </span>

        {/* Step type indicators */}
        <div style={{ display: "flex", gap: 2, flex: 1 }}>
          {timeline.steps.map((step, i) => (
            <div
              key={i}
              style={{
                width: Math.max(4, (step.duration_ms / timeline.total_duration_ms) * 200),
                height: 12,
                background: STEP_COLORS[step.type] || "#6b7280",
                borderRadius: 2,
                opacity: 0.8,
              }}
              title={`${step.name}: ${step.duration_ms.toFixed(0)}ms`}
            />
          ))}
        </div>

        {timeline.tools_used.length > 0 && (
          <span className="tool-badge">{timeline.tools_used.length} tools</span>
        )}

        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
            color: "var(--amber-light)",
            fontWeight: 600,
          }}
        >
          {timeline.total_duration_ms.toFixed(0)}ms
        </span>

        <span style={{ fontSize: 10, color: "var(--gray-600)" }}>
          {new Date(timeline.timestamp).toLocaleTimeString("ko-KR", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ padding: "0 8px 8px" }}>
          {/* Timeline header */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              height: 18,
              fontSize: 9,
              color: "var(--gray-600)",
              borderBottom: "1px solid var(--gray-700, #374151)",
              marginBottom: 2,
            }}
          >
            <div style={{ width: 140, minWidth: 140, paddingLeft: 8 }}>Step</div>
            <div
              style={{
                flex: 1,
                display: "flex",
                justifyContent: "space-between",
                paddingRight: 4,
              }}
            >
              <span>0ms</span>
              <span>{(timeline.total_duration_ms / 2).toFixed(0)}ms</span>
              <span>{timeline.total_duration_ms.toFixed(0)}ms</span>
            </div>
            <div style={{ width: 60, minWidth: 60, textAlign: "right", paddingRight: 4 }}>
              Duration
            </div>
          </div>

          {timeline.steps.map((step) => (
            <StepBar
              key={step.step_index}
              step={step}
              totalDuration={timeline.total_duration_ms}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface Props {
  traces: Trace[];
}

export default function AgentTimelinePanel({ traces }: Props) {
  const [timelines, setTimelines] = useState<AgentTurnTimeline[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .getAgentTimeline(20)
        .then((res) => setTimelines(res.timelines || []))
        .catch((e) => setError(e.message));
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <GitBranch size={14} />
          Agent Trace Timeline
        </div>
        <span style={{ fontSize: 11, color: "var(--gray-500)" }}>
          {timelines.length} turns
        </span>
      </div>

      <div className="panel-body">
        {error ? (
          <div className="empty-state">
            <GitBranch size={32} />
            <p>Could not load agent timeline: {error}</p>
          </div>
        ) : timelines.length === 0 ? (
          <div className="empty-state">
            <GitBranch size={32} />
            <p>No agent traces yet. Send a chat message to see the agent's decision flow.</p>
          </div>
        ) : (
          <>
            {/* Legend */}
            <div
              style={{
                display: "flex",
                gap: 14,
                marginBottom: 12,
                fontSize: 10,
                color: "var(--gray-500)",
                flexWrap: "wrap",
              }}
            >
              {Object.entries(STEP_COLORS).map(([type, color]) => (
                <span key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span
                    style={{
                      display: "inline-block",
                      width: 10,
                      height: 10,
                      borderRadius: 2,
                      background: color,
                    }}
                  />
                  {STEP_LABELS[type]}
                </span>
              ))}
            </div>

            {timelines.map((tl) => (
              <TurnTimeline key={tl.turn_id || tl.trace_id} timeline={tl} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
