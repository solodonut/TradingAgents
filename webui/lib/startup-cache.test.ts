import test from "node:test";
import assert from "node:assert/strict";
import { formatBytes, startupCacheToServiceItem, startupCacheReady } from "./startup-cache.ts";
import type { StartupCacheStatusDetail } from "./types.ts";

const state = (status: StartupCacheStatusDetail["status"]): StartupCacheStatusDetail => ({
  status,
  phase: status,
  message: status === "completed" ? "启动缓存清理完成" : "正在清理 endpoint 本地数据缓存",
  current_path: status === "running" ? "akshare/demo.pkl" : null,
  processed_items: status === "running" ? 2 : 3,
  total_items: 3,
  deleted_files: 2,
  released_bytes: 1536,
  errors: [],
  started_at: "2026-07-08T00:00:00Z",
  completed_at: status === "running" ? null : "2026-07-08T00:00:02Z",
  updated_at: "2026-07-08T00:00:02Z",
  cache_root: "/Users/me/.tradingagents/cache",
});

test("startupCacheReady is true only when completed", () => {
  assert.equal(startupCacheReady(state("completed")), true);
  assert.equal(startupCacheReady(state("running")), false);
  assert.equal(startupCacheReady(null), false);
});

test("formatBytes renders compact binary units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.5 KB");
});

test("startupCacheToServiceItem converts running state to system item", () => {
  const item = startupCacheToServiceItem(state("running"));
  assert.ok(item);
  assert.equal(item.id, "system:startup-cache-clear");
  assert.equal(item.kind, "system");
  assert.equal(item.status, "checking");
  assert.match(item.message, /2\/3/);
  assert.match(item.message, /1.5 KB/);
});
