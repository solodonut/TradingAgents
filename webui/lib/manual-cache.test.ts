import test from "node:test";
import assert from "node:assert/strict";
import { manualCacheActionDisabled } from "./manual-cache.ts";

test("manual cache action is disabled only during an active clear", () => {
  assert.equal(manualCacheActionDisabled(null), false);
  assert.equal(manualCacheActionDisabled({ status: "running" }), true);
  assert.equal(manualCacheActionDisabled({ status: "completed" }), false);
});
