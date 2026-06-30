import assert from "node:assert/strict";
import test from "node:test";
import { getExpandedHistoryDates } from "./history-groups.ts";

test("getExpandedHistoryDates opens the newest date by default", () => {
  const expanded = getExpandedHistoryDates({
    tradeDates: ["2026-06-30", "2026-06-29"],
    selectedTradeDate: null,
    previousExpanded: null,
  });

  assert.deepEqual(Array.from(expanded), ["2026-06-30"]);
});

test("getExpandedHistoryDates opens the selected run date", () => {
  const expanded = getExpandedHistoryDates({
    tradeDates: ["2026-06-30", "2026-06-29"],
    selectedTradeDate: "2026-06-29",
    previousExpanded: null,
  });

  assert.deepEqual(Array.from(expanded), ["2026-06-29"]);
});

test("getExpandedHistoryDates preserves user choices for dates still present", () => {
  const expanded = getExpandedHistoryDates({
    tradeDates: ["2026-06-30", "2026-06-29"],
    selectedTradeDate: null,
    previousExpanded: new Set(["2026-06-29", "2026-06-28"]),
  });

  assert.deepEqual(Array.from(expanded), ["2026-06-29"]);
});
