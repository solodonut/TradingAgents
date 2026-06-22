import assert from "node:assert/strict";
import test from "node:test";

import { sessionFactsProposal } from "./chat-profile.ts";
import type { ChatMessageT } from "./types.ts";

function message(toolCalls: Record<string, unknown>[]): ChatMessageT {
  return {
    message_id: "m1",
    session_id: "s1",
    role: "assistant",
    content: "",
    tool_calls: toolCalls,
    created_at: "2026-06-22T00:00:00Z",
  };
}

test("sessionFactsProposal reads proposal from propose_session_facts call", () => {
  const result = sessionFactsProposal(
    message([
      {
        tool: "propose_session_facts",
        args: { available_capital: 300000, capital_currency: "CNY" },
      },
    ]),
  );
  assert.deepEqual(result, { available_capital: 300000, capital_currency: "CNY" });
});

test("sessionFactsProposal returns null without the tool", () => {
  assert.equal(sessionFactsProposal(message([{ tool: "get_stock_data" }])), null);
});
