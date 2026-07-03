"use client";

import { useMemo, useRef, useState } from "react";
import { filterLogs, type LogEvent } from "@/lib/logs";

const TYPE_COLORS: Record<string, string> = {
  run_start: "text-emerald-600",
  run_end: "text-emerald-700",
  node_enter: "text-slate-500",
  node_exit: "text-slate-400",
  llm_call: "text-violet-600",
  tool_call: "text-indigo-600",
  vendor_call: "text-blue-600",
  debate_round: "text-amber-600",
  report_section: "text-teal-600",
  memory_op: "text-fuchsia-600",
  checkpoint_op: "text-cyan-600",
  error: "text-red-600",
};

export function LogPanel({ logs }: { logs: LogEvent[] }) {
  const [types, setTypes] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const allTypes = useMemo(
    () => Array.from(new Set(logs.map((l) => l.event_type))).sort(),
    [logs],
  );
  const shown = useMemo(() => filterLogs(logs, { types, query }), [logs, types, query]);

  const toggleType = (t: string) =>
    setTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <button
        className="flex w-full items-center justify-between px-4 py-2 text-sm font-medium"
        onClick={() => setOpen((o) => !o)}
      >
        <span>详细日志 ({logs.length})</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-slate-100 p-3">
          <div className="mb-2 flex flex-wrap gap-1">
            {allTypes.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded px-2 py-0.5 text-xs ${
                  types.includes(t) ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索日志…"
            className="mb-2 w-full rounded border border-slate-200 px-2 py-1 text-sm"
          />
          <div ref={scrollRef} className="max-h-96 overflow-auto font-mono text-xs">
            {shown.map((log) => (
              <div key={log.seq} className="border-b border-slate-50 py-1">
                <button
                  className="flex w-full gap-2 text-left"
                  onClick={() => setExpanded(expanded === log.seq ? null : log.seq)}
                >
                  <span className="text-slate-400">{log.seq}</span>
                  <span className={TYPE_COLORS[log.event_type] ?? "text-slate-700"}>
                    {log.event_type}
                  </span>
                  <span className="truncate text-slate-500">
                    {(log.node as string | undefined) ??
                      (log.model as string | undefined) ??
                      (log.method as string | undefined) ??
                      (log.section as string | undefined) ??
                      ""}
                  </span>
                </button>
                {expanded === log.seq && (
                  <pre className="mt-1 whitespace-pre-wrap break-all rounded bg-slate-50 p-2 text-slate-700">
                    {JSON.stringify(log, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
