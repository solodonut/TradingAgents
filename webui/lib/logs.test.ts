import assert from "node:assert/strict";
import test from "node:test";

import { filterLogs, type LogEvent } from "./logs.ts";

const logs: LogEvent[] = [
  { ts: "t", seq: 1, run_id: "r", event_type: "llm_call", model: "gpt" },
  { ts: "t", seq: 2, run_id: "r", event_type: "vendor_call", method: "get_news" },
  { ts: "t", seq: 3, run_id: "r", event_type: "node_enter", node: "Trader" },
];

test("filterLogs returns all when no type filter and empty query", () => {
  assert.equal(filterLogs(logs, { types: [], query: "" }).length, 3);
});

test("filterLogs filters by event type", () => {
  const out = filterLogs(logs, { types: ["vendor_call"], query: "" });
  assert.deepEqual(out.map((l) => l.seq), [2]);
});

test("filterLogs filters by case-insensitive substring across payload", () => {
  assert.deepEqual(filterLogs(logs, { types: [], query: "trader" }).map((l) => l.seq), [3]);
  assert.deepEqual(filterLogs(logs, { types: [], query: "GPT" }).map((l) => l.seq), [1]);
});
