import type {
  AnalysisRequest,
  ChatMessageT,
  ChatSessionT,
  ConfigOptions,
  HistorySummary,
  PortfolioHolding,
  RunResult,
  RunStatusDetail,
  SessionProfile,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function getConfigOptions(): Promise<ConfigOptions> {
  const r = await fetch(`${BASE}/api/config/options`);
  if (!r.ok) throw new Error("failed to load config options");
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

export async function deleteHistory(runId: string): Promise<void> {
  await fetch(`${BASE}/api/history/${runId}`, { method: "DELETE" });
}

export function reportUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/report`;
}

export function streamUrl(runId: string): string {
  return `${BASE}/api/analysis/${runId}/stream`;
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

export async function getSessionProfile(id: string): Promise<SessionProfile> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/profile`);
  if (!r.ok) throw new Error("无法加载会话参数");
  return r.json();
}

export async function saveSessionProfile(
  id: string,
  profile: SessionProfile,
): Promise<SessionProfile> {
  const r = await fetch(`${BASE}/api/chat/sessions/${id}/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  if (!r.ok) throw new Error("无法保存会话参数");
  return r.json();
}
