export interface TimelineRow {
  seq: number | null;
  type: string;
  label: string;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  duration_label: string;
  ts: string;
  ok: boolean | null;
  detail: string;
}

export interface LogErrorSummary {
  seq: number | null;
  source: string;
  message: string;
}

export interface DurationRow {
  label: string;
  duration_ms: number;
  duration_label: string;
}

export interface LogViewPayload {
  run_id: string;
  elapsed_ms: number;
  elapsed_label: string;
  event_counts: Record<string, number>;
  duration_totals: Record<string, number>;
  timeline: TimelineRow[];
  slow_events: TimelineRow[];
  node_totals: DurationRow[];
  errors: LogErrorSummary[];
}

export function msLabel(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds % 60).toFixed(1)}s`;
}

export function filterTimelineRows(
  rows: TimelineRow[],
  opts: { type: string; minMs: number; query: string },
): TimelineRow[] {
  const q = opts.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (opts.type && row.type !== opts.type) return false;
    if (row.duration_ms < opts.minMs) return false;
    if (!q) return true;
    return [row.type, row.label, row.detail, row.ts, String(row.seq ?? "")]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });
}

export function getTimelineBarStyle(
  row: TimelineRow,
  elapsedMs: number,
): { left: string; width: string } {
  if (elapsedMs <= 0) return { left: "0%", width: "100%" };
  const left = Math.max(0, Math.min(100, (row.start_ms / elapsedMs) * 100));
  const width = Math.max(0.2, Math.min(100 - left, (row.duration_ms / elapsedMs) * 100));
  return {
    left: `${trimPercent(left)}%`,
    width: `${trimPercent(width)}%`,
  };
}

function trimPercent(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}
