import type { ChatMessageT } from "@/lib/types";

export const EXPORT_REPORT_PROMPT =
  "请根据当前会话导出报告。请先根据上下文提供可选的导出范围，不要立即导出。";

const INTERNAL_EXPORT_TOOLS = new Set([
  "request_export_scope",
  "export_chat_report",
  "propose_session_facts",
  "compute_position_sizing",
]);

export function exportScopeOptions(message: ChatMessageT): string[] {
  const call = message.tool_calls.find(
    (item) => item.tool === "request_export_scope",
  );
  const args = call?.args;
  if (!args || typeof args !== "object") return [];
  const options = (args as { options?: unknown }).options;
  if (!Array.isArray(options)) return [];
  return options.filter(
    (option): option is string =>
      typeof option === "string" && option.trim().length > 0,
  );
}

export function visibleDataSources(message: ChatMessageT): string[] {
  return message.tool_calls
    .map((item) => (typeof item.tool === "string" ? item.tool : ""))
    .filter((name) => name && !INTERNAL_EXPORT_TOOLS.has(name));
}
