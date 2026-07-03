import assert from "node:assert/strict";
import test from "node:test";
import {
  filterTimelineRows,
  getTimelineBarStyle,
  msLabel,
  type TimelineRow,
} from "./log-view.ts";

const rows: TimelineRow[] = [
  {
    seq: 1,
    type: "llm_call",
    label: "gpt-test",
    start_ms: 500,
    end_ms: 2000,
    duration_ms: 1500,
    duration_label: "1.5 s",
    ts: "2026-07-03T00:00:02+00:00",
    ok: null,
    detail: "response",
  },
  {
    seq: 2,
    type: "vendor_call",
    label: "get_news / akshare",
    start_ms: 2500,
    end_ms: 3300,
    duration_ms: 800,
    duration_label: "800 ms",
    ts: "2026-07-03T00:00:03+00:00",
    ok: false,
    detail: "HTTP 500",
  },
];

test("msLabel formats milliseconds, seconds, and minutes", () => {
  assert.equal(msLabel(120), "120 ms");
  assert.equal(msLabel(1500), "1.5 s");
  assert.equal(msLabel(125000), "2m 5.0s");
});

test("filterTimelineRows filters by event type, minimum duration, and query", () => {
  assert.deepEqual(
    filterTimelineRows(rows, { type: "vendor_call", minMs: 0, query: "" }).map((row) => row.seq),
    [2],
  );
  assert.deepEqual(
    filterTimelineRows(rows, { type: "", minMs: 1000, query: "" }).map((row) => row.seq),
    [1],
  );
  assert.deepEqual(
    filterTimelineRows(rows, { type: "", minMs: 0, query: "akshare" }).map((row) => row.seq),
    [2],
  );
});

test("getTimelineBarStyle returns percentage position from run duration", () => {
  assert.deepEqual(getTimelineBarStyle(rows[0], 5000), { left: "10%", width: "30%" });
  assert.deepEqual(getTimelineBarStyle(rows[1], 0), { left: "0%", width: "100%" });
});
