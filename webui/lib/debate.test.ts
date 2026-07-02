import assert from "node:assert/strict";
import test from "node:test";

import { INVEST_LABELS, RISK_LABELS, parseDebateHistory } from "./debate.ts";

test("parses bull/bear history into ordered turns with round math", () => {
  const history =
    "\nBull Analyst: 看多理由一\nBear Analyst: 看空理由一\nBull Analyst: 看多理由二\nBear Analyst: 看空理由二";
  const turns = parseDebateHistory(history, 2, INVEST_LABELS);
  assert.equal(turns.length, 4);
  assert.deepEqual(turns[0], { round: 1, speakerLabel: "多方", content: "看多理由一" });
  assert.deepEqual(turns[1], { round: 1, speakerLabel: "空方", content: "看空理由一" });
  assert.equal(turns[2].round, 2);
  assert.equal(turns[3].speakerLabel, "空方");
});

test("parses 3-way risk history with groupSize 3", () => {
  const history =
    "\nAggressive Analyst: 激进\nConservative Analyst: 保守\nNeutral Analyst: 中立\nAggressive Analyst: 再激进";
  const turns = parseDebateHistory(history, 3, RISK_LABELS);
  assert.equal(turns.length, 4);
  assert.equal(turns[0].speakerLabel, "激进");
  assert.equal(turns[2].round, 1);
  assert.equal(turns[3].round, 2);
});

test("returns empty for non-string or blank history", () => {
  assert.deepEqual(parseDebateHistory(undefined, 2, INVEST_LABELS), []);
  assert.deepEqual(parseDebateHistory("", 2, INVEST_LABELS), []);
  assert.deepEqual(parseDebateHistory("   ", 3, RISK_LABELS), []);
});
