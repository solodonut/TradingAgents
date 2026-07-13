import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveVendorSelection } from "./etf-diagnostics.ts";

const ALL = ["akshare", "tushare", "yfinance"];

test("null saved → all available", () => {
  assert.deepEqual(resolveVendorSelection(null, ALL), ALL);
});

test("subset preserved and filtered to available", () => {
  assert.deepEqual(resolveVendorSelection(["tushare", "akshare"], ALL), ["tushare", "akshare"]);
});

test("stale saved entries dropped", () => {
  assert.deepEqual(resolveVendorSelection(["tushare", "gone"], ALL), ["tushare"]);
});

test("all-stale saved → all available", () => {
  assert.deepEqual(resolveVendorSelection(["gone", "x"], ALL), ALL);
});

test("empty saved → all available", () => {
  assert.deepEqual(resolveVendorSelection([], ALL), ALL);
});
