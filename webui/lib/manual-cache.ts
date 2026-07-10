import type { StartupCacheStatusDetail } from "./types";

export function manualCacheActionDisabled(
  state: Pick<StartupCacheStatusDetail, "status"> | null,
): boolean {
  return state?.status === "running";
}
