import test from "node:test";
import assert from "node:assert/strict";
import { buildLinePath, buildAreaPath, chartMarks } from "./etf-chart.ts";

test("buildLinePath returns empty string for no points", () => {
  assert.equal(buildLinePath([], 100, 40, 2), "");
});

test("buildLinePath maps first point to left and scales within bounds", () => {
  const d = buildLinePath(
    [
      { t: "09:30", price: 1 },
      { t: "09:35", price: 2 },
    ],
    100,
    40,
    2,
  );
  assert.equal(d.startsWith("M"), true);
  assert.equal(d.includes("L"), true);
});

test("buildAreaPath closes the path back to the baseline", () => {
  const d = buildAreaPath(
    [
      { t: "a", price: 1 },
      { t: "b", price: 3 },
    ],
    100,
    40,
    2,
  );
  assert.equal(d.startsWith("M"), true);
  assert.equal(d.trimEnd().endsWith("Z"), true);
});

test("chartMarks reports last point plus high and low extremes", () => {
  const marks = chartMarks(
    [
      { t: "a", price: 5 },
      { t: "b", price: 9 },
      { t: "c", price: 2 },
      { t: "d", price: 7 },
    ],
    100,
    40,
    2,
  );
  assert.ok(marks);
  assert.equal(marks.high.price, 9);
  assert.equal(marks.low.price, 2);
  assert.equal(marks.last.price, 7);
});

test("chartMarks returns null for empty input", () => {
  assert.equal(chartMarks([], 100, 40, 2), null);
});
