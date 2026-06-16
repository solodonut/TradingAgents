"use client";
import type { HistorySummary } from "@/lib/types";

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
    <aside className="w-64 shrink-0 border-r border-zinc-800 bg-zinc-950 p-2 space-y-1 overflow-y-auto">
      <div className="text-xs text-zinc-500 font-mono uppercase tracking-wider px-2 py-1">
        历史分析
      </div>
      {items.map((it) => {
        const active = it.run_id === selectedId;
        return (
          <div
            key={it.run_id}
            role="button"
            tabIndex={0}
            aria-current={active ? "true" : undefined}
            className={`group flex items-center justify-between px-2 py-1.5 rounded cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 ${
              active ? "bg-zinc-800" : "hover:bg-zinc-800"
            }`}
            onClick={() => onOpen(it.run_id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen(it.run_id);
              }
            }}
          >
            <span
              className={`font-mono text-sm truncate ${
                active ? "text-emerald-400" : "text-zinc-300"
              }`}
            >
              {it.ticker} · {it.trade_date} · {it.decision ?? it.status}
            </span>
            <button
              aria-label="删除该分析"
              className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-red-400 text-xs shrink-0 ml-2 hover:text-red-300 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/50"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(it.run_id);
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
    </aside>
  );
}
