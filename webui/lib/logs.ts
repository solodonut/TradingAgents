export type LogEvent = {
  ts: string;
  seq: number;
  run_id: string;
  event_type: string;
  [key: string]: unknown;
};

export function filterLogs(
  logs: LogEvent[],
  opts: { types: string[]; query: string },
): LogEvent[] {
  const q = opts.query.trim().toLowerCase();
  return logs.filter((log) => {
    if (opts.types.length > 0 && !opts.types.includes(log.event_type)) return false;
    if (!q) return true;
    return JSON.stringify(log).toLowerCase().includes(q);
  });
}
