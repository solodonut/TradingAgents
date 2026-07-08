import type {
  AnalysisRequest,
  ChatMessageT,
  ChatSessionT,
  ConfigOptions,
  HistorySummary,
  PortfolioHolding,
  QueueState,
  RunResult,
  RunStatusDetail,
  ServiceHealthItem,
  ServiceHealthEvent,
  StartupCacheEvent,
  StartupCacheStatusDetail,
} from "./types";
import type { LogViewPayload } from "./log-view";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function getConfigOptions(): Promise<ConfigOptions> {
  const r = await fetch(`${BASE}/api/config/options`);
  if (!r.ok) throw new Error("failed to load config options");
  return r.json();
}

export async function lookupTicker(
  code: string,
): Promise<{ ticker: string; name: string | null; valid: boolean }> {
  const t = code.trim().toUpperCase();
  try {
    const r = await fetch(`${BASE}/api/ticker/${encodeURIComponent(t)}`);
    if (!r.ok) return { ticker: t, name: null, valid: false };
    return await r.json();
  } catch {
    return { ticker: t, name: null, valid: false };
  }
}

export type WatchlistItem = { ticker: string; name: string };

export async function getWatchlist(): Promise<WatchlistItem[]> {
  const r = await fetch(`${BASE}/api/watchlist`);
  if (!r.ok) throw new Error("failed to load watchlist");
  return r.json();
}

export async function saveWatchlist(items: WatchlistItem[]): Promise<WatchlistItem[]> {
  const r = await fetch(`${BASE}/api/watchlist`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(items),
  });
  if (!r.ok) throw new Error("failed to save watchlist");
  return r.json();
}

export async function startAnalysis(req: AnalysisRequest): Promise<string> {
  const r = await fetch(`${BASE}/api/analysis`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (r.status === 409) throw new Error("已有分析正在运行");
  if (!r.ok) throw new Error("failed to start analysis");
  return (await r.json()).run_id as string;
}

export interface EnqueueRequest {
  tickers: string[];
  ticker_names?: Record<string, string>;
  trade_date: string;
  asset_type: AnalysisRequest["asset_type"];
  analysts: string[];
  research_depth: 1 | 3 | 5;
  output_language: string;
  llm_provider: string | null;
  deep_think_llm: string | null;
  quick_think_llm: string | null;
}

export async function enqueueAnalysis(
  req: EnqueueRequest,
): Promise<{ run_ids: string[]; running_run_id: string | null; queue: QueueState }> {
  const r = await fetch(`${BASE}/api/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error("无法加入分析队列");
  return r.json();
}

export async function getQueue(): Promise<QueueState> {
  const r = await fetch(`${BASE}/api/queue`);
  return r.ok ? r.json() : { running: null, pending: [] };
}

export async function removeQueueItem(runId: string): Promise<void> {
  const r = await fetch(`${BASE}/api/queue/${runId}`, { method: "DELETE" });
  if (r.status === 409) throw new Error("该项已在分析中，无法移除");
  if (!r.ok && r.status !== 204) throw new Error("移除排队项失败");
}

export async function clearQueue(): Promise<number> {
  const r = await fetch(`${BASE}/api/queue`, { method: "DELETE" });
  if (!r.ok) throw new Error("清空队列失败");
  return (await r.json()).removed as number;
}

export async function reorderQueue(orderedRunIds: string[]): Promise<QueueState> {
  const r = await fetch(`${BASE}/api/queue/order`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_run_ids: orderedRunIds }),
  });
  if (!r.ok) throw new Error("调整顺序失败");
  return r.json();
}

export async function cancelAnalysis(runId: string): Promise<void> {
  const r = await fetch(`${BASE}/api/analysis/${runId}/cancel`, { method: "POST" });
  if (r.status === 404) throw new Error("未找到正在运行的分析");
  if (r.status === 409) throw new Error("该分析已结束，无法停止");
  if (!r.ok) throw new Error("failed to cancel analysis");
}

export async function getHistory(): Promise<HistorySummary[]> {
  const r = await fetch(`${BASE}/api/history`);
  return r.ok ? r.json() : [];
}

export async function getHistoryDetail(runId: string): Promise<RunResult> {
  const r = await fetch(`${BASE}/api/history/${runId}`);
  if (!r.ok) throw new Error(r.status === 404 ? "未找到该分析记录" : "无法加载分析详情");
  return r.json();
}

export async function getAnalysisStatus(runId: string): Promise<RunStatusDetail> {
  const r = await fetch(`${BASE}/api/analysis/${runId}/status`);
  if (!r.ok) throw new Error("无法加载后台状态");
  return r.json();
}

export async function getLogView(runId: string): Promise<LogViewPayload> {
  const r = await fetch(`${BASE}/api/analysis/${runId}/logs/view`);
  if (!r.ok) throw new Error(r.status === 404 ? "未找到该运行日志" : "无法加载运行日志");
  return r.json();
}

export async function deleteHistory(runId: string): Promise<void> {
  await fetch(`${BASE}/api/history/${runId}`, { method: "DELETE" });
}

export function reportUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/report`;
}

export function historyReportsZipUrl(runIds: string[] = []): string {
  const url = new URL(`${BASE}/api/history/reports.zip`);
  for (const runId of runIds) url.searchParams.append("run_ids", runId);
  return url.toString();
}

export function streamUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/stream`;
}

export function serviceHealthStreamUrl(): string {
  return `${BASE}/api/health/services/stream`;
}

export function startupCacheStatusUrl(): string {
  return `${BASE}/api/startup-cache/status`;
}

export function startupCacheStreamUrl(): string {
  return `${BASE}/api/startup-cache/stream`;
}

export async function checkServiceHealth(serviceId: string): Promise<ServiceHealthItem> {
  const encodedId = serviceId.split("/").map(encodeURIComponent).join("/");
  const r = await fetch(`${BASE}/api/health/services/${encodedId}`);
  if (!r.ok) throw new Error("单项服务检查失败");
  return r.json();
}

export function subscribeServiceHealth(
  onEvent: (e: ServiceHealthEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(serviceHealthStreamUrl());
  const serviceHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "service_status", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    }
  };
  const summaryHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "summary", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    } finally {
      es.close();
      onClose();
    }
  };
  es.addEventListener("service_status", serviceHandler);
  es.addEventListener("summary", summaryHandler);
  es.onerror = () => {
    es.close();
    onError("服务检查连接中断");
    onClose();
  };
  return () => es.close();
}

export async function getStartupCacheStatus(): Promise<StartupCacheStatusDetail> {
  const r = await fetch(startupCacheStatusUrl());
  if (!r.ok) throw new Error("无法加载启动缓存清理状态");
  return r.json();
}

export function subscribeStartupCacheClear(
  onEvent: (e: StartupCacheEvent) => void,
  onClose: () => void,
  onError: (message: string) => void,
): () => void {
  const es = new EventSource(startupCacheStreamUrl());
  const statusHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "cache_clear_status", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    }
  };
  const summaryHandler = (ev: MessageEvent) => {
    try {
      onEvent({ event: "summary", data: JSON.parse(ev.data) });
    } catch {
      /* ignore malformed */
    } finally {
      es.close();
      onClose();
    }
  };
  es.addEventListener("cache_clear_status", statusHandler);
  es.addEventListener("summary", summaryHandler);
  es.onerror = () => {
    es.close();
    onError("启动缓存清理连接中断");
    onClose();
  };
  return () => es.close();
}

export async function createChatSession(runIds: string[]): Promise<string> {
  const r = await fetch(`${BASE}/api/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  });
  if (!r.ok) throw new Error("failed to create chat session");
  return (await r.json()).session_id as string;
}

export async function listChatSessions(): Promise<ChatSessionT[]> {
  const r = await fetch(`${BASE}/api/chat/sessions`);
  return r.json();
}

export async function getChatSession(
  id: string,
): Promise<{ session: ChatSessionT; messages: ChatMessageT[] }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}`);
  if (!r.ok) throw new Error("session not found");
  return r.json();
}

export async function deleteChatSession(id: string): Promise<void> {
  await fetch(`${BASE}/api/chat/sessions/${id}`, { method: "DELETE" });
}

export async function deleteChatSessions(ids: string[]): Promise<string[]> {
  const r = await fetch(`${BASE}/api/chat/sessions`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_ids: ids }),
  });
  if (!r.ok) throw new Error("failed to delete chat sessions");
  return (await r.json()).deleted as string[];
}

export async function renameChatSession(id: string, title: string): Promise<ChatSessionT> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("failed to rename chat session");
  return r.json();
}

export async function updateChatSessionReports(
  id: string,
  runIds: string[],
): Promise<ChatSessionT> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/reports`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  });
  if (!r.ok) throw new Error("无法保存关联分析报告");
  return r.json();
}

export async function uploadPortfolio(
  id: string,
  files: File | File[],
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const fd = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];
  if (uploadFiles[0]) fd.append("file", uploadFiles[0]);
  uploadFiles.forEach((file) => fd.append("files", file));
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    throw new Error(detail?.detail ?? "持仓截图上传失败");
  }
  return r.json();
}

export async function savePortfolio(
  id: string,
  holdings: PortfolioHolding[],
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ holdings, source: "manual" }),
  });
  return r.json();
}

export async function getPortfolio(
  id: string,
): Promise<{ holdings: PortfolioHolding[]; source: string }> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/portfolio`);
  return r.json();
}

export function chatStreamUrl(id: string): string {
  return `${BASE}/api/chat/sessions/${id}/stream`;
}
