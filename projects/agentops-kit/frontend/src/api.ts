const API_BASE = "/api";

function generateHex(bytes: number): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, "0")).join("");
}

function makeTraceparent(): string {
  const traceId = generateHex(16);
  const spanId = generateHex(8);
  return `00-${traceId}-${spanId}-01`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const traceparent = makeTraceparent();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      traceparent,
      ...(options?.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    const msg = typeof detail === "string"
      ? detail
      : detail?.error?.message || detail?.error?.code || JSON.stringify(detail) || "Request failed";
    throw new Error(msg);
  }
  return res.json();
}

export type StreamEvent =
  | { type: "session"; session_id: string; turn_id: string }
  | { type: "text_delta"; delta: string }
  | { type: "tool_use"; name: string }
  | { type: "final"; response: string; tools_used: string[]; usage: any; latency_ms: number; otel_trace_id?: string; [k: string]: any }
  | { type: "complete"; session_id: string; turn_id: string; trace_id: string; latency_ms: number; cost: any; guardrails: any; redacted: boolean; circuit_state: string }
  | { type: "error"; message: string; category?: string };

/**
 * Stream chat response via SSE (Server-Sent Events).
 * Calls POST /chat/stream with a fetch ReadableStream and parses
 * `data: {...}\n\n` frames into typed events for the caller.
 */
export async function streamChat(
  prompt: string,
  opts: {
    sessionId?: string;
    promptVersion?: string;
    onEvent: (ev: StreamEvent) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  const traceparent = makeTraceparent();
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      traceparent,
    },
    body: JSON.stringify({
      prompt,
      session_id: opts.sessionId,
      prompt_version: opts.promptVersion,
    }),
    signal: opts.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `stream request failed: ${res.status}`);
  }
  if (!res.body) {
    throw new Error("response has no body — streaming not supported");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE frames are separated by \n\n
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 2);
        if (!frame) continue;
        const dataLine = frame.startsWith("data:")
          ? frame.slice("data:".length).trim()
          : frame;
        try {
          const ev = JSON.parse(dataLine) as StreamEvent;
          opts.onEvent(ev);
        } catch {
          // non-JSON frame — ignore
        }
      }
    }
  } finally {
    try { reader.releaseLock(); } catch { /* noop */ }
  }
}

export const api = {
  chat: (prompt: string, sessionId?: string, promptVersion?: string) =>
    request<any>("/chat", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        session_id: sessionId,
        prompt_version: promptVersion,
      }),
    }),

  streamChat,

  getTraces: (limit = 20) => request<any>(`/traces?limit=${limit}`),

  getTrace: (traceId: string) => request<any>(`/traces/${traceId}`),

  getAgents: () => request<{ agents: { agent_id: string; name: string; resource_arn: string }[]; count: number }>("/agents"),

  getMetrics: (hours = 24, agentId?: string) => {
    const params = new URLSearchParams({ hours: String(hours) });
    if (agentId) params.set("agent_id", agentId);
    return request<any>(`/metrics?${params}`);
  },

  runEvaluation: (evaluators: string[]) =>
    request<any>("/evaluations", {
      method: "POST",
      body: JSON.stringify({ evaluators }),
    }),

  getEvalHistory: () => request<any>("/evaluations/history"),

  getTurnEvals: () => request<any>("/evaluations/turns"),
  getTurnEval: (turnId: string) => request<any>(`/evaluations/turn/${turnId}`),
  getImprovement: () => request<any>("/improvement"),
  applyImprovement: () =>
    request<any>("/improvement/apply", { method: "POST" }),
  resetImprovement: () =>
    request<any>("/improvement/reset", { method: "POST" }),

  setPromptVersion: (version: string) =>
    request<any>("/system-prompt", {
      method: "PUT",
      body: JSON.stringify({ version }),
    }),

  getPromptInfo: () => request<any>("/system-prompt"),

  getHealth: () => request<any>("/health"),

  // --- New: Production validation APIs ---
  getSession: (sessionId: string) => request<any>(`/session/${sessionId}`),
  listSessions: (limit = 20) => request<any>(`/sessions?limit=${limit}`),
  getSessionTurns: (sessionId: string, limit = 50) => request<any>(`/sessions/${sessionId}/turns?limit=${limit}`),
  getSessionCost: (sessionId: string) => request<any>(`/cost/${sessionId}`),
  getCostOverview: () => request<any>("/cost"),
  setBudget: (sessionId: string, budgetUsd: number) =>
    request<any>("/budget", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, budget_usd: budgetUsd }),
    }),
  getAnalyticsEvents: (eventName?: string, limit = 100) => {
    const qs = eventName ? `?event_name=${eventName}&limit=${limit}` : `?limit=${limit}`;
    return request<any>(`/analytics/events${qs}`);
  },
  getAnalyticsSummary: () => request<any>("/analytics/summary"),
  testGuardrails: (text: string, toolOutputs: string[] = []) =>
    request<any>("/guardrails/test", {
      method: "POST",
      body: JSON.stringify({ text, tool_outputs: toolOutputs }),
    }),
  getCircuit: (sessionId: string) => request<any>(`/circuit/${sessionId}`),
  resetCircuit: (sessionId: string) =>
    request<any>(`/circuit/${sessionId}/reset`, { method: "POST" }),

  // Gateway pages
  getLLMGateway: () => request<any>("/gateways/llm"),
  getToolGateway: () => request<any>("/gateways/tool"),
  getAgentGateway: () => request<any>("/gateways/agent"),
  getGatewayJourney: () => request<any>("/gateways/journey"),
  getRegistry: () => request<any>("/registry"),

  // Users / Teams
  getTopUsers: (days = 7) => request<any>(`/users?top=true&days=${days}`),
  getUsersList: (teamId?: string) =>
    request<any>(`/users${teamId ? `?team_id=${teamId}` : ""}`),
  getUserDetail: (userId: string, days = 30) =>
    request<any>(`/users/${userId}?days=${days}`),
  getTopTeams: (days = 7) => request<any>(`/teams?top=true&days=${days}`),
  getTeamsList: () => request<any>("/teams"),
  getTeamDetail: (teamId: string, days = 30) =>
    request<any>(`/teams/${teamId}?days=${days}`),
  setEntityBudget: (entityType: string, entityId: string, budgetUsd: number) =>
    request<any>("/budgets", {
      method: "POST",
      body: JSON.stringify({
        entity_type: entityType,
        entity_id: entityId,
        budget_usd: budgetUsd,
      }),
    }),

  // Evaluation Analysis
  getEvalAnalysis: (threshold = 0.65) => request<any>(`/evaluations/analysis?threshold=${threshold}`),
  registerCustomEvaluator: () => request<any>("/evaluations/custom/register", { method: "POST" }),
  getCustomEvaluatorStatus: () => request<any>("/evaluations/custom/status"),

  // Observability
  getAnomalies: () => request<any>("/observability/anomalies"),
  getAgentTimeline: (limit = 20) => request<any>(`/observability/agent-timeline?limit=${limit}`),
  getToolAnalytics: (hours = 24) => request<any>(`/observability/tool-analytics?hours=${hours}`),
};
