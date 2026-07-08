import test from "node:test";
import assert from "node:assert/strict";
import { buildLinePath } from "./etf-chart.ts";

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
