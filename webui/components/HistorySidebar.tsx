"use client";
import { Trash2 } from "lucide-react";
import type { HistorySummary } from "@/lib/types";

const DECISION_TONE: Record<string, string> = {
  Buy: "border-emerald-500/50 text-emerald-300",
  Overweight: "border-emerald-500/40 text-emerald-200",
  Hold: "border-border text-muted-foreground",
  Underweight: "border-red-500/40 text-red-300",
  Sell: "border-red-500/50 text-red-300",
};

export function HistorySidebar({
  items,
  selectedId,
  onOpen,
  onDelete,
}: {
  items: HistorySummary[];
  selectedId: string | null;
  onOpen: (runId: string) => void;
  onDelete: (runId: string) => void;
}) {
  return (
    <aside className="glass h-full overflow-y-auto rounded-none text-sidebar-foreground">
      <div className="glass-readable sticky top-0 z-10 rounded-none border-x-0 border-t-0 px-3 py-3">
        <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          History Queue
        </div>
        <div className="mt-0.5 text-sm text-foreground">历史分析</div>
      </div>

      <div className="space-y-1 p-2">
        {items.length === 0 && (
          <div className="glass-readable rounded-md border-dashed border-sidebar-border px-3 py-3 text-xs leading-relaxed text-muted-foreground">
            完成的分析会出现在这里。打开历史记录可以复盘每个 agent 的报告和最终决策。
          </div>
        )}

        {items.map((it) => {
          const active = it.run_id === selectedId;
          const decisionTone = it.decision
            ? DECISION_TONE[it.decision] ?? "border-border text-muted-foreground"
            : "border-border text-muted-foreground";
          return (
            <div
              key={it.run_id}
              role="button"
              tabIndex={0}
              aria-current={active ? "true" : undefined}
              className={`group rounded-md border px-2.5 py-2 transition-colors focus-visible:outline-none focus-visible:border-primary ${
                active
                  ? "glass-strong border-primary/30 text-foreground"
                  : "border-transparent hover:border-sidebar-border hover:bg-sidebar-accent/70"
              }`}
              onClick={() => onOpen(it.run_id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onOpen(it.run_id);
                }
              }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-mono text-sm text-foreground">{it.ticker}</div>
                  {it.instrument_name && (
                    <div className="mt-0.5 truncate text-xs text-muted-foreground">
                      {it.instrument_name}
                    </div>
                  )}
                  <div className="mt-0.5 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-muted-foreground">
                    {it.trade_date}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`删除 ${it.ticker} ${it.trade_date} 分析`}
                  className="shrink-0 rounded p-1 text-muted-foreground opacity-0 transition-colors hover:text-destructive focus-visible:opacity-100 focus-visible:outline-none focus-visible:text-destructive group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(it.run_id);
                  }}
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
              <div className="mt-2 flex items-center gap-1.5">
                <span
                  className={`rounded border px-1.5 py-0.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] ${decisionTone}`}
                >
                  {it.decision ?? it.status}
                </span>
                <span className="truncate font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
                  {it.status}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
