const API_BASE = "/api";
import { getIdToken, signOut as authSignOut } from "./auth";
import { TraceSSEEvent, TraceSSEEventType } from "./types";

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
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    traceparent,
  };

  const token = await getIdToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      ...headers,
      ...(options?.headers || {}),
    },
    ...options,
  });

  if (res.status === 401) {
    await authSignOut();
    window.location.reload();
    throw new Error("Session expired");
  }

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
  const token = await getIdToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    traceparent,
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers,
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

  getTraces: (limit = 20, hours = 6) => request<any>(`/traces?limit=${limit}&hours=${hours}`),

  getTrace: (traceId: string) => request<any>(`/traces/${traceId}`),

  connectTraceStream: (onEvent: (event: TraceSSEEvent) => void): (() => void) => {
    const es = new EventSource(`${API_BASE}/traces/stream`);

    const handleEvent = (type: TraceSSEEventType) => (e: MessageEvent) => {
      try {
        onEvent({ type, data: JSON.parse(e.data) });
      } catch {}
    };

    es.addEventListener("trace_start", handleEvent("trace_start"));
    es.addEventListener("span_start", handleEvent("span_start"));
    es.addEventListener("span_end", handleEvent("span_end"));
    es.addEventListener("trace_end", handleEvent("trace_end"));

    return () => es.close();
  },

  getAgents: () => request<{ agents: { agent_id: string; name: string; resource_arn: string }[]; count: number }>("/agents"),

  getMetrics: (hours = 24, agentId?: string, userId?: string) => {
    const params = new URLSearchParams({ hours: String(hours) });
    if (agentId) params.set("agent_id", agentId);
    if (userId) params.set("user_id", userId);
    return request<any>(`/metrics?${params}`);
  },

  // Evaluation — AgentCore Evaluation API
  getEvaluators: () => request<any>("/evaluations/evaluators"),
  getOnlineConfigs: () => request<any>("/evaluations/online/configs"),
  getOnlineConfig: (configId: string) => request<any>(`/evaluations/online/config/${configId}`),
  createOnlineConfig: (params: { name: string; evaluator_ids: string[]; sampling_rate: number; description?: string }) =>
    request<any>("/evaluations/online/config", { method: "POST", body: JSON.stringify(params) }),
  updateOnlineConfig: (configId: string, params: { sampling_rate?: number; evaluator_ids?: string[]; enabled?: boolean }) =>
    request<any>(`/evaluations/online/config/${configId}`, { method: "PUT", body: JSON.stringify(params) }),
  deleteOnlineConfig: (configId: string) =>
    request<any>(`/evaluations/online/config/${configId}`, { method: "DELETE" }),
  getOnlineResults: (configId: string, hours: number = 24) =>
    request<any>(`/evaluations/online/results/${configId}?hours=${hours}`),
  runEvaluation: (evaluators: string[], lookbackDays: number = 7) =>
    request<any>("/evaluations/run", {
      method: "POST",
      body: JSON.stringify({ evaluators, lookback_days: lookbackDays }),
    }),
  startBatchEval: (params: { name?: string; evaluator_ids: string[] }) =>
    request<any>("/evaluations/batch", { method: "POST", body: JSON.stringify(params) }),
  listBatchEvals: () => request<any>("/evaluations/batch"),
  getBatchEval: (batchId: string) => request<any>(`/evaluations/batch/${batchId}`),
  // Optimization (AgentCore Optimization API)
  getOptimizationStatus: () => request<any>("/optimization/status"),
  generateRecommendation: (evaluatorId: string = "Builtin.GoalSuccessRate", lookbackDays: number = 7) =>
    request<any>("/optimization/recommendations", { method: "POST", body: JSON.stringify({ evaluator_id: evaluatorId, lookback_days: lookbackDays }) }),
  getRecommendations: () => request<any>("/optimization/recommendations"),
  getRecommendation: (id: string) => request<any>(`/optimization/recommendations/${id}`),
  getBundles: () => request<any>("/optimization/bundles"),
  getBundle: (bundleId: string, versionId?: string) => {
    const params = versionId ? `?version_id=${versionId}` : "";
    return request<any>(`/optimization/bundles/${bundleId}${params}`);
  },
  createBundle: (bundleName: string, systemPrompt: string, description?: string) =>
    request<any>("/optimization/bundles", { method: "POST", body: JSON.stringify({ bundle_name: bundleName, system_prompt: systemPrompt, description }) }),
  createABTest: (params: { control_bundle_arn: string; control_version: string; treatment_bundle_arn: string; treatment_version: string; control_weight?: number; treatment_weight?: number }) =>
    request<any>("/optimization/ab-tests", { method: "POST", body: JSON.stringify(params) }),
  completeABTest: (ruleId: string, winner: "control" | "treatment") =>
    request<any>(`/optimization/ab-tests/${ruleId}/complete`, { method: "POST", body: JSON.stringify({ winner }) }),
  applyRecommendation: (systemPrompt: string, recommendationId?: string) =>
    request<any>("/optimization/apply", { method: "POST", body: JSON.stringify({ system_prompt: systemPrompt, recommendation_id: recommendationId }) }),
  deployWinner: (systemPrompt: string, versionLabel?: string) =>
    request<any>("/optimization/deploy", { method: "POST", body: JSON.stringify({ system_prompt: systemPrompt, version_label: versionLabel }) }),
  resetOptimization: () =>
    request<any>("/optimization/reset", { method: "POST" }),


  getPromptInfo: () => request<any>("/system-prompt"),
  getPromptByVersion: (version: string) => request<any>(`/system-prompt/${version}`),
  getPromptVersions: () => request<any>("/system-prompt/versions"),

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
  publishRegistryRecord: (payload: { name: string; description: string; descriptor_type: string; descriptor_url?: string }) =>
    request<any>("/registry/records", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  approveRegistryRecord: (recordId: string) =>
    request<any>(`/registry/records/${recordId}/approve`, { method: "PUT" }),
  rejectRegistryRecord: (recordId: string) =>
    request<any>(`/registry/records/${recordId}/reject`, { method: "PUT" }),
  deprecateRegistryRecord: (recordId: string) =>
    request<any>(`/registry/records/${recordId}/deprecate`, { method: "PUT" }),
  searchRegistry: (query: string, maxResults = 10) =>
    request<any>("/registry/search", {
      method: "POST",
      body: JSON.stringify({ query, max_results: maxResults }),
    }),
  getRegistryMcpEndpoint: () => request<any>("/registry/mcp-endpoint"),
  getPublishableResources: () => request<any>("/registry/publishable"),

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


  // Observability
  getAnomalies: () => request<any>("/observability/anomalies"),
  getAgentTimeline: (limit = 20) => request<any>(`/observability/agent-timeline?limit=${limit}`),
  getToolAnalytics: (hours = 24) => request<any>(`/observability/tool-analytics?hours=${hours}`),
};
