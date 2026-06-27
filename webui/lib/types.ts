export type AssetType = "stock" | "crypto";
export type Decision = "Buy" | "Overweight" | "Hold" | "Underweight" | "Sell";
export type RunStatus = "pending" | "running" | "completed" | "error" | "cancelled";

export interface AnalysisRequest {
  ticker: string;
  trade_date: string;
  asset_type: AssetType;
  analysts: string[];
  research_depth: 1 | 3 | 5;
  output_language: string;
  llm_provider: string | null;
  deep_think_llm: string | null;
  quick_think_llm: string | null;
}

export interface ConfigOptions {
  analysts: { value: string; label: string }[];
  research_depth: { value: number; label: string }[];
  languages: string[];
  configured_provider: string | null;
  configured_deep_llm: string | null;
  configured_quick_llm: string | null;
  model_options: { deep: [string, string][]; quick: [string, string][] };
}

export interface HistorySummary {
  run_id: string;
  ticker: string;
  trade_date: string;
  decision: Decision | null;
  status: RunStatus;
  created_at: string;
  instrument_name?: string | null;
}

export interface QueueItem {
  run_id: string;
  ticker: string;
  status: RunStatus;
  queue_position: number | null;
  created_at: string;
}

export interface QueueState {
  running: QueueItem | null;
  pending: QueueItem[];
}

export interface RunResult {
  run_id: string;
  ticker: string;
  trade_date: string;
  asset_type: string;
  instrument_name?: string | null;
  decision: Decision | null;
  status: RunStatus;
  config: Record<string, unknown>;
  result: Record<string, string> | null;
  created_at: string;
  completed_at: string | null;
}

export interface RunStatusDetail {
  run_id: string;
  db_status: RunStatus;
  process_alive: boolean;
  llm_active: boolean;
  active_llm_calls: number;
  last_llm_start_at: string | null;
  last_llm_end_at: string | null;
  last_llm_error_at: string | null;
  last_llm_error: string | null;
  last_llm_model: string | null;
  last_prompt_preview: string | null;
  last_prompt_chars: number | null;
  last_report_section: string | null;
  last_report_at: string | null;
  updated_at: string | null;
}

export type ServiceHealthStatus = "checking" | "ok" | "error" | "disabled";
export type ServiceHealthKind = "llm" | "data" | "system";

export interface ServiceHealthItem {
  id: string;
  name: string;
  kind: ServiceHealthKind;
  status: ServiceHealthStatus;
  message: string;
  latency_ms: number | null;
}

export interface ServiceHealthSummary {
  total: number;
  checking: number;
  ok: number;
  error: number;
  disabled: number;
}

export type ServiceHealthEvent =
  | { event: "service_status"; data: ServiceHealthItem }
  | { event: "summary"; data: ServiceHealthSummary };

export type SSEEvent =
  | { event: "agent_status"; data: { agent: string; team: string; status: string } }
  | { event: "message"; data: { agent: string; team: string; content: string; ts: number } }
  | { event: "report_section"; data: { section: string; content: string } }
  | { event: "stats"; data: Record<string, number> }
  | { event: "done"; data: { decision: Decision; final_trade_decision: string; run_id: string } }
  | { event: "error"; data: { message: string } }
  | { event: "cancelled"; data: { run_id: string; message: string } };

export interface PortfolioHolding {
  ticker: string;
  name?: string | null;
  shares?: number | null;
  avg_cost?: number | null;
  current_price?: number | null;
  market_value?: number | null;
  weight?: number | null;
  unrealized_pnl?: number | null;
  return_rate?: number | null;
  daily_pnl?: number | null;
  daily_return_rate?: number | null;
  action?: "buy" | "sell" | null;
  trade_date?: string | null;
}

export interface ChatMessageT {
  message_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls: Record<string, unknown>[];
  created_at: string;
}

export interface ChatSessionT {
  session_id: string;
  run_id: string | null;
  run_ids: string[];
  title: string | null;
  created_at: string;
  updated_at: string;
}

export type ChatSSEEvent =
  | { event: "tool_call"; data: { tool: string; args: Record<string, unknown> } }
  | { event: "token"; data: { content: string } }
  | { event: "done"; data: { content: string; tool_calls: Record<string, unknown>[] } }
  | { event: "error"; data: { message: string } };
