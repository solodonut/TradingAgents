import type { ServiceHealthItem, StartupCacheStatusDetail } from "./types";

export const STARTUP_CACHE_ITEM_ID = "system:startup-cache-clear";

export function startupCacheReady(state: StartupCacheStatusDetail | null): boolean {
  return state?.status === "completed";
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Number.isInteger(kb) ? kb : kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${Number.isInteger(mb) ? mb : mb.toFixed(1)} MB`;
}

export function startupCacheToServiceItem(
  state: StartupCacheStatusDetail | null,
): ServiceHealthItem | null {
  if (!state) return null;
  const status: ServiceHealthItem["status"] =
    state.status === "completed" ? "ok" : state.status === "error" ? "error" : "checking";
  const progress = state.total_items > 0 ? `${state.processed_items}/${state.total_items}` : "扫描中";
  const released = formatBytes(state.released_bytes);
  const suffix =
    state.status === "completed"
      ? `${state.deleted_files} files · ${released}`
      : state.status === "error"
        ? `失败 ${state.errors.length} 个 · ${progress}`
        : `${progress} · ${state.deleted_files} files · ${released}`;

  return {
    id: STARTUP_CACHE_ITEM_ID,
    name: "启动维护",
    kind: "system",
    status,
    message: `${state.message} · ${suffix}`,
    latency_ms: null,
  };
}
