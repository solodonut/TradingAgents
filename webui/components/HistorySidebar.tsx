"use client";
import type { HistorySummary } from "@/lib/types";

export function HistorySidebar({
  items,
  onOpen,
  onDelete,
}: {
  items: HistorySummary[];
  onOpen: (runId: string) => void;
  onDelete: (runId: string) => void;
}) {
  return (
    <aside className="w-64 shrink-0 border-r border-zinc-800 bg-zinc-950 p-2 space-y-1 overflow-y-auto">
      <div className="text-xs text-zinc-500 font-mono uppercase tracking-wider px-2 py-1">
        历史分析
      </div>
      {items.map((it) => (
        <div
          key={it.run_id}
          className="group flex items-center justify-between px-2 py-1.5 rounded hover:bg-zinc-800 cursor-pointer"
          onClick={() => onOpen(it.run_id)}
        >
          <span className="font-mono text-sm text-zinc-300 truncate">
            {it.ticker} · {it.trade_date} · {it.decision ?? it.status}
          </span>
          <button
            className="opacity-0 group-hover:opacity-100 text-red-400 text-xs shrink-0 ml-2 hover:text-red-300"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(it.run_id);
            }}
          >
            ✕
          </button>
        </div>
      ))}
    </aside>
  );
}
