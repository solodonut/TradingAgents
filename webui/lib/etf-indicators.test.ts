import test from "node:test";
import assert from "node:assert/strict";
import { parseIndicatorText, interpretIndicator } from "./etf-indicators.ts";

const SAMPLE = `## macd
## macd values from 2026-05-10 to 2026-07-09:

2026-07-09: N/A: Not a trading day (weekend or holiday)
2026-07-08: -0.0037541886179495165
2026-07-07: 0.005792660185561793
2026-07-06: 0.014839108510254384

MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers.

## rsi
## rsi values from 2026-05-10 to 2026-07-09:

2026-07-09: N/A: Not a trading day (weekend or holiday)
2026-07-08: 43.49441344548053
2026-07-07: 45.138244338264116

RSI: Measures momentum to flag overbought/oversold conditions.

## close_50_sma
## close_50_sma values from 2026-05-10 to 2026-07-09:

2026-07-08: 5.0983
2026-07-07: 5.09802

50 SMA: A medium-term trend indicator.
`;

test("parseIndicatorText splits into one block per indicator", () => {
  const out = parseIndicatorText(SAMPLE);
  assert.deepEqual(
    out.map((i) => i.key),
    ["macd", "rsi", "close_50_sma"],
  );
});

test("latest is the most recent non-N/A value, not the N/A row", () => {
  const macd = parseIndicatorText(SAMPLE)[0];
  assert.equal(macd.latest?.date, "2026-07-08");
  assert.ok(macd.latest && Math.abs(macd.latest.value - -0.00375418) < 1e-6);
});

test("series is chronological (oldest first) and drops N/A rows", () => {
  const macd = parseIndicatorText(SAMPLE)[0];
  assert.deepEqual(
    macd.series.map((p) => p.date),
    ["2026-07-06", "2026-07-07", "2026-07-08"],
  );
});

test("label maps known keys to human names", () => {
  const out = parseIndicatorText(SAMPLE);
  assert.equal(out[0].label, "MACD");
  assert.equal(out[1].label, "RSI");
  assert.equal(out[2].label, "50日均线");
});

test("description captures the trailing prose line", () => {
  const rsi = parseIndicatorText(SAMPLE)[1];
  assert.match(rsi.description, /overbought\/oversold/);
});

test("parseIndicatorText tolerates empty / missing text", () => {
  assert.deepEqual(parseIndicatorText(""), []);
  assert.deepEqual(parseIndicatorText(undefined), []);
});

test("interpretIndicator flags RSI overbought / oversold / neutral", () => {
  assert.equal(interpretIndicator("rsi", 82, null).label, "超买");
  assert.equal(interpretIndicator("rsi", 18, null).label, "超卖");
  assert.equal(interpretIndicator("rsi", 50, null).tone, "muted");
});

test("interpretIndicator reads MACD momentum sign", () => {
  assert.equal(interpretIndicator("macd", 0.04, null).tone, "up");
  assert.equal(interpretIndicator("macd", -0.04, null).tone, "down");
});

test("interpretIndicator compares price against a moving average", () => {
  assert.equal(interpretIndicator("close_50_sma", 5.0, 5.2).tone, "up"); // price above MA
  assert.equal(interpretIndicator("close_50_sma", 5.0, 4.8).tone, "down"); // price below MA
});
