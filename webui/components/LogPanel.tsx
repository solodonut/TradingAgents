"use client";

import { useMemo, useRef, useState } from "react";
import { filterLogs, type LogEvent } from "@/lib/logs";

const TYPE_COLORS: Record<string, string> = {
  run_start: "text-emerald-300",
  run_end: "text-emerald-200",
  node_enter: "text-slate-300",
  node_exit: "text-slate-400",
  llm_call: "text-violet-300",
  tool_call: "text-indigo-300",
  vendor_call: "text-cyan-300",
  debate_round: "text-amber-300",
  report_section: "text-teal-300",
  memory_op: "text-fuchsia-300",
  checkpoint_op: "text-sky-300",
  error: "text-red-300",
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
    <section className="glass-readable rounded-lg">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 border-b border-border/60 px-3 py-2 text-left transition-colors hover:bg-white/[0.03] focus-visible:outline-none focus-visible:border-primary"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          详细日志 ({logs.length})
        </span>
        <span className="font-mono text-xs text-muted-foreground">{open ? "收起" : "展开"}</span>
      </button>
      {open && (
        <div className="flex h-72 min-h-44 resize-y flex-col overflow-hidden p-3 lg:h-80 lg:max-h-[min(34rem,60vh)]">
          <div className="mb-2 flex flex-wrap gap-1">
            {allTypes.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => toggleType(t)}
                className={`rounded-md border px-2 py-1 font-mono text-[0.68rem] transition-colors ${
                  types.includes(t)
                    ? "border-primary/60 bg-primary/15 text-primary"
                    : "border-border/70 bg-white/[0.04] text-muted-foreground hover:border-primary/40 hover:text-foreground"
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
            className="glass-control mb-2 h-9 w-full rounded-md px-3 font-mono text-xs text-foreground placeholder:text-muted-foreground/70 focus-visible:outline-none focus-visible:border-primary"
          />
          <div
            ref={scrollRef}
            className="dark-scrollbar min-h-0 flex-1 overflow-auto font-mono text-xs"
          >
            {shown.map((log) => (
              <div key={log.seq} className="border-b border-border/45 py-1.5">
                <button
                  type="button"
                  className="grid w-full grid-cols-[2.25rem_minmax(7rem,11rem)_minmax(0,1fr)] gap-2 text-left"
                  onClick={() => setExpanded(expanded === log.seq ? null : log.seq)}
                >
                  <span className="text-muted-foreground tabular-nums">{log.seq}</span>
                  <span className={TYPE_COLORS[log.event_type] ?? "text-slate-300"}>
                    {log.event_type}
                  </span>
                  <span className="truncate text-muted-foreground">
                    {(log.node as string | undefined) ??
                      (log.model as string | undefined) ??
                      (log.method as string | undefined) ??
                      (log.section as string | undefined) ??
                      ""}
                  </span>
                </button>
                {expanded === log.seq && (
                  <pre className="mt-2 whitespace-pre-wrap break-all rounded-md border border-border/60 bg-black/30 p-2 text-[0.68rem] leading-5 text-slate-200">
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
