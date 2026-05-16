export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  trace_id?: string;
  turn_id?: string;
  latency_ms?: number;
  tools_used?: string[];
  token_usage?: TokenUsage;
  cost?: CostBreakdown;
  guardrails?: GuardrailResult;
  redacted?: boolean;
  circuit_state?: string;
  eval?: { avg_score: number; label: string };
  evalLoading?: boolean;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens?: number;
  cache_read_tokens?: number;
  total_tokens: number;
  billable_tokens?: number;
}

export interface CostBreakdown {
  input_cost: number;
  output_cost: number;
  cache_write_cost?: number;
  cache_read_cost?: number;
  total_cost: number;
}

export interface ToolCall {
  tool_use_id: string;
  name: string;
  input: Record<string, any>;
  output: string;
  status: "success" | "error";
}

export interface Trace {
  trace_id: string;
  turn_id?: string;
  session_id?: string;
  timestamp: string;
  prompt?: string;
  response?: string;
  system_prompt?: string;
  model?: string;
  guardrail_result?: GuardrailResult;
  latency_ms?: number;
  duration_ms?: number;
  tools_used?: string[];
  tool_calls?: ToolCall[];
  token_usage?: TokenUsage;
  cost?: CostBreakdown;
  prompt_version?: string;
  spans?: Span[];
  span_source?: "otel" | "local";
  error?: any;
  status?: string;
  attributes?: Record<string, any>;
}

export interface Span {
  span_id: string;
  parent_span_id?: string;
  name: string;
  type: "interaction" | "llm" | "tool" | "guardrail" | "cost" | "other";
  kind?: string;
  start_ms: number;
  duration_ms: number;
  status?: string;
  attributes?: Record<string, any>;
  events?: { name: string; timestamp_ms: number; attributes: any; body?: string }[];
  error?: string;
  subsegments?: Span[];
}

export interface MetricsData {
  invocation_count: number;
  latency: {
    avg: number;
    p50: number;
    p99: number;
    values: TimeseriesPoint[];
  };
  tokens: {
    total: number;
    input?: number;
    output?: number;
    avg_per_call: number;
    values: TimeseriesPoint[];
  };
  cost: {
    total_usd: number;
    values: TimeseriesPoint[];
  };
  errors?: {
    total: number;
    user_errors: number;
    system_errors: number;
    throttles: number;
    error_rate: number;
    values: TimeseriesPoint[];
  };
  duration?: {
    avg_total_ms: number;
    avg_llm_ms: number;
    llm_ratio_pct: number;
    avg_duration_ms: number;
    values: TimeseriesPoint[];
  };
  compute?: {
    cpu_vcpu_hours: number;
    memory_gb_hours: number;
  };
  event_loop?: {
    total_cycles: number;
    avg_cycles_per_invocation: number;
    avg_cycle_duration_ms: number;
  };
  tool_calls: Record<string, number>;
  tool_durations?: Record<string, number>;
  source: string;
  cost_global?: CostGlobalState;
  analytics?: { queued: number; flushed: number; dropped: number };
  event_counts?: Record<string, number>;
}

export interface CostGlobalState {
  total_usage: TokenUsage;
  total_cost: number;
  active_sessions: number;
  top_sessions: { session_id: string; cost: number; calls: number }[];
}

export interface TimeseriesPoint {
  timestamp: string;
  value: number;
}

export interface EvalResult {
  evaluator: string;
  score: number;
  label: string;
  explanation: string;
  trace_count: number;
  eval_source?: "agentcore" | "simulation";
}

export interface EvalEntry {
  eval_id: string;
  timestamp: string;
  prompt_version: string;
  evaluators: string[];
  results: EvalResult[];
  trace_count: number;
}

// --- Online Evaluation (per-turn) ---

export interface TurnEvalScore {
  evaluator: string;
  score: number;
  label: string;
  eval_source?: "agentcore" | "custom" | "simulation";
  explanation?: string;
}

export interface TurnEvalResult {
  turn_id: string;
  trace_id: string;
  scores: TurnEvalScore[];
  avg_score: number;
  prompt_version: string;
  timestamp: string;
  eval_source: "agentcore" | "simulation";
  prompt?: string;
  response?: string;
  tools_used?: string[];
  category?: string;
}

export interface ImprovementChange {
  aspect: string;
  before: string;
  after: string;
}

export interface ImprovementState {
  status: "idle" | "analyzing" | "ready" | "applied";
  trigger_score?: number | null;
  suggestion?: {
    current_version: string;
    suggested_version: string;
    changes: ImprovementChange[];
    expected_delta: string;
    reason: string;
  } | null;
  before_score?: number | null;
  after_score?: number | null;
}

// --- Evaluation Analysis ---

export interface CategoryEvalData {
  count: number;
  avg_score: number;
  evaluator_scores: Record<string, number>;
}

export interface EvaluatorBreakdown {
  avg_score: number;
  count: number;
  trend: number[];
  lowest?: { turn_id: string; score: number; prompt: string; response: string } | null;
}

export interface TimeTrendPoint {
  turn_id: string;
  timestamp: string;
  avg_score: number;
  prompt_version: string;
  category: string;
}

export interface ToolCorrelation {
  avg_score_when_used: number;
  call_count: number;
}

export interface LowScoreAnalysis {
  summary: string;
  details: { evaluator: string; score: number; analysis: string }[];
  recommendations: string[];
}

export interface LowScoreTurn {
  turn_id: string;
  avg_score: number;
  prompt: string;
  response: string;
  category: string;
  tools_used: string[];
  scores: TurnEvalScore[];
  weakest_evaluator: string | null;
  prompt_version: string;
  timestamp: string;
  analysis: LowScoreAnalysis;
}

export interface EvalAnalysis {
  by_category: Record<string, CategoryEvalData>;
  by_evaluator: Record<string, EvaluatorBreakdown>;
  time_trend: TimeTrendPoint[];
  tool_correlation: Record<string, ToolCorrelation>;
  low_score_turns: LowScoreTurn[];
  summary: { improving: boolean; delta: number; total_turns: number };
  custom_evaluator: { registered: boolean; evaluator_id: string | null };
}

// --- New: Guardrails ---

export interface GuardrailViolation {
  rule_id: string;
  severity: "info" | "warn" | "critical";
  message: string;
  matched_text?: string | null;
  suggestion?: string;
}

export interface GuardrailResult {
  passed: boolean;
  duration_ms: number;
  critical_count: number;
  warn_count: number;
  info_count: number;
  checks_run: string[];
  violations: GuardrailViolation[];
}

// --- New: Session + Circuit Breaker ---

export interface CircuitBreakerState {
  state: "closed" | "open" | "half_open";
  consecutive_failures: number;
  total_failures: number;
  total_successes: number;
  failure_threshold: number;
  last_failure?: string | null;
  last_success?: string | null;
  success_rate: number;
}

export interface SessionState {
  session_id: string;
  created_at: string;
  last_activity: string;
  turn_counter: number;
  current_turn_id?: string | null;
  compacted: boolean;
  compaction_count: number;
  context_tokens_used: number;
  context_usage_ratio: number;
  max_context_tokens: number;
  circuit_breaker: CircuitBreakerState;
  recent_messages_count: number;
  session_duration_seconds: number;
  cost_state?: SessionCostState;
}

export interface SessionCostState {
  session_id: string;
  total_usage: TokenUsage;
  total_cost: number;
  call_count: number;
  budget: BudgetStatus;
  model_breakdown: Record<string, { calls: number; cost: number; tokens: number }>;
  duration_seconds: number;
}

export interface BudgetStatus {
  status: "ok" | "warning" | "critical" | "exceeded" | "unlimited";
  used_usd?: number;
  budget_usd?: number;
  used_ratio?: number;
  remaining_usd?: number;
}

// --- New: Analytics Events ---

// --- Gateway pages ---

export interface LLMGatewayModel {
  name: string;
  id: string;
  tier: "quality" | "cost";
  calls: number;
  input_tokens: number;
  output_tokens: number;
  avg_latency_ms: number;
  cost_usd: number;
}

export interface LLMGatewayState {
  routing_policy: string;
  models: LLMGatewayModel[];
  recent_calls: {
    timestamp: number;
    model: string;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
    tag: string;
    cost_usd: number;
    routing_reason?: string;
  }[];
  guardrails: {
    input_scrubs: number;
    output_scrubs: number;
    detected_tags: Record<string, number>;
  };
  total_calls: number;
  last_model_used?: string;
  last_routing_reason?: string;
  error?: string;
}

export interface ToolGatewayTool {
  name: string;
  description: string;
  schema: Record<string, any>;
}

export interface ToolGatewayState {
  gateway_id: string;
  gateway_name: string;
  gateway_url: string;
  semantic_search_enabled: boolean;
  authorizer: string;
  tool_count: number;
  tools: ToolGatewayTool[];
  call_counts: Record<string, number>;
  last_tool_used?: string | null;
  error?: string;
}

export interface AgentGatewayAgent {
  name: string;
  arn: string;
  status: string;
  role: string;
  description: string;
}

export interface AgentGatewayHandoff {
  turn_id: string;
  timestamp: string;
  from: string;
  to: string;
  prompt: string;
}

// --- Users / Teams (Work B) ---

export interface UserRow {
  user_id: string;
  team_id: string;
  calls: number;
  tokens: number;
  cost: number;
}

export interface UserDirectoryEntry {
  entity_id: string;
  entity_type: string;
  name: string;
  email?: string;
  team_id?: string;
  role?: string;
  budget_usd?: number;
  member_count?: number;
  created_at?: string;
}

export interface BudgetState {
  entity_type: string;
  entity_id: string;
  period: string;
  used_usd: number;
  budget_usd: number;
  remaining_usd: number;
  ratio: number;
  status: "ok" | "warning" | "critical" | "exceeded" | "unlimited";
}

export interface UserUsage {
  user_id: string;
  window_days: number;
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  by_model: Record<string, { calls: number; tokens: number; cost: number }>;
  by_day: Record<string, { calls: number; tokens: number; cost: number }>;
  recent_calls: any[];
}

export interface TeamRow {
  team_id: string;
  user_count: number;
  calls: number;
  tokens: number;
  cost: number;
}

export interface TeamUsage {
  team_id: string;
  window_days: number;
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  user_count: number;
  by_user: { user_id: string; calls: number; tokens: number; cost: number }[];
}

// --- Registry ---

export interface RegistryRecord {
  record_id: string;
  name: string;
  description: string;
  descriptor_type: "MCP" | "A2A" | "CUSTOM" | "AGENT_SKILLS";
  status: "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED";
  created_at: string | null;
  updated_at: string | null;
}

export interface RegistryState {
  registry_id: string;
  registry_name: string;
  authorizer_type: string;
  status: string;
  record_count: number;
  records: RegistryRecord[];
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  error?: string;
}

export interface AgentGatewayState {
  protocol: string;
  agent_count: number;
  agents: AgentGatewayAgent[];
  handoffs: AgentGatewayHandoff[];
  handoff_count: number;
  last_handoff?: {
    turn_id: string;
    from: string;
    to: string;
    timestamp: string;
  } | null;
  error?: string;
}

export interface GatewayJourneyState {
  active: boolean;
  turn_id: string;
  trace_id?: string;
  timestamp?: string;
  prompt_snippet?: string;
  llm: { model: string; reason: string };
  tool: { last: string | null; used: string[] };
  agent: { handoff: boolean; target: string | null };
  summary: { cost_usd: number; total_tokens: number; duration_ms: number };
}

export interface AnalyticsEvent {
  event_name: string;
  timestamp: string;
  session_id: string;
  turn_id: string;
  properties: Record<string, any>;
}

// --- Observability: Agent Timeline ---

export interface AgentStep {
  step_index: number;
  type: "llm_call" | "tool_selection" | "tool_execution" | "a2a_handoff" | "guardrail" | "response";
  name: string;
  duration_ms: number;
  start_ms: number;
  details: Record<string, any>;
}

export interface AgentTurnTimeline {
  turn_id: string;
  trace_id: string;
  timestamp: string;
  total_duration_ms: number;
  steps: AgentStep[];
  tools_used: string[];
  prompt_version: string;
}

// --- Observability: Tool Analytics ---

export interface ToolStats {
  tool_name: string;
  total_calls: number;
  success_count: number;
  error_count: number;
  success_rate: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p99_latency_ms: number;
  last_called: string;
  calls_by_turn: { turn_id: string; timestamp: string; latency_ms: number; success: boolean }[];
}

export interface ToolAnalyticsData {
  tools: ToolStats[];
  total_calls: number;
  most_used: string;
  slowest: string;
  selection_patterns: { from_tool: string; to_tool: string; count: number }[];
}

// --- Observability: Anomaly Detection ---

export interface AnomalyAlarm {
  metric_name: string;
  display_name: string;
  state: "OK" | "ALARM" | "INSUFFICIENT_DATA";
  current_value: number;
  expected_low: number;
  expected_high: number;
  unit: string;
  timestamp: string;
}

// --- Session Explorer ---

export interface SessionTurn {
  turn_id: string;
  trace_id: string;
  timestamp: string;
  prompt: string;
  response: string;
  latency_ms: number;
  tools_used: string[];
  token_usage: TokenUsage | null;
  cost: CostBreakdown | null;
  prompt_version: string;
  status: string;
  eval: { avg_score: number; scores: { evaluator: string; score: number; label: string }[] } | null;
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  last_activity: string;
  turn_count: number;
  total_duration_s: number;
  total_cost: number;
  circuit_state: string;
}
