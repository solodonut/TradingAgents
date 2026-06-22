import assert from "node:assert/strict";
import test from "node:test";

import {
  EXPORT_REPORT_PROMPT,
  exportScopeOptions,
  visibleDataSources,
} from "./chat-export.ts";

import type { ChatMessageT } from "./types.ts";

function message(toolCalls: Record<string, unknown>[]): ChatMessageT {
  return {
    message_id: "m1",
    session_id: "s1",
    role: "assistant",
    content: "请选择导出范围",
    tool_calls: toolCalls,
    created_at: "2026-06-22T00:00:00Z",
  };
}

test("shortcut prompt requires choices before export", () => {
  assert.match(EXPORT_REPORT_PROMPT, /提供可选的导出范围/);
  assert.match(EXPORT_REPORT_PROMPT, /不要立即导出/);
});

test("exportScopeOptions reads nonblank string options from the scope tool", () => {
  const result = exportScopeOptions(
    message([
      {
        tool: "request_export_scope",
        args: { options: ["全部最终结论", "", 3, "仅风险控制"] },
      },
    ]),
  );

  assert.deepEqual(result, ["全部最终结论", "仅风险控制"]);
});

test("visibleDataSources excludes internal export tools", () => {
  const result = visibleDataSources(
    message([
      { tool: "request_export_scope", args: {} },
      { tool: "get_stock_data", args: {} },
      { tool: "export_chat_report", args: {} },
      { tool: "compute_position_sizing", args: {} },
    ]),
  );

  assert.deepEqual(result, ["get_stock_data"]);
});
