import assert from "node:assert/strict";
import test from "node:test";
import type { ServiceHealthItem } from "./types.ts";
import { sortServiceHealthItems } from "./service-health.ts";

const item = (id: string, status: ServiceHealthItem["status"]): ServiceHealthItem => ({
  id,
  name: id,
  kind: "data",
  status,
  message: "",
  latency_ms: null,
});

test("sortServiceHealthItems orders reachable, errors, warnings, checking, then disabled", () => {
  const sorted = sortServiceHealthItems([
    item("disabled-a", "disabled"),
    item("warning-a", "warning"),
    item("error-a", "error"),
    item("ok-a", "ok"),
    item("checking-a", "checking"),
    item("error-b", "error"),
    item("disabled-b", "disabled"),
    item("ok-b", "ok"),
  ]);

  assert.deepEqual(
    sorted.map((service) => service.id),
    [
      "ok-a",
      "ok-b",
      "error-a",
      "error-b",
      "warning-a",
      "checking-a",
      "disabled-a",
      "disabled-b",
    ],
  );
});

test("sortServiceHealthItems keeps checking services after actionable statuses", () => {
  const sorted = sortServiceHealthItems([
    item("disabled-a", "disabled"),
    item("checking-a", "checking"),
    item("error-a", "error"),
    item("ok-a", "ok"),
  ]);

  assert.deepEqual(
    sorted.map((service) => service.id),
    ["ok-a", "error-a", "checking-a", "disabled-a"],
  );
});
