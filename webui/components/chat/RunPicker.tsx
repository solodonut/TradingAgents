"use client";

import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { getHistory } from "@/lib/api";
import type { HistorySummary } from "@/lib/types";

export function RunPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string[];
  onChange: (runIds: string[]) => void;
  disabled?: boolean;
}) {
  const [runs, setRuns] = useState<HistorySummary[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    getHistory()
      .then(setRuns)
      .catch(() => setRuns([]));
  }, []);

  const toggleRun = (runId: string) => {
    onChange(
      value.includes(runId)
        ? value.filter((id) => id !== runId)
        : [...value, runId],
    );
  };

  const statusLabel = (status: HistorySummary["status"]) => {
    if (status === "running") return "分析中";
    if (status === "error") return "失败";
    if (status === "cancelled") return "已取消";
    return "已完成";
  };

  return (
    <div className="glass-readable rounded-lg px-3 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
        关联分析报告
      </div>
      <button
        type="button"
        className="glass-control mt-2 flex h-9 w-full items-center justify-between gap-2 rounded-md px-3 text-left text-sm outline-none transition-colors hover:border-primary/60 focus:border-primary disabled:cursor-not-allowed disabled:opacity-50"
        onClick={() => setOpen((current) => !current)}
        disabled={disabled}
        aria-expanded={open}
      >
        <span className="truncate">
          {value.length === 0 ? "不关联（通用咨询）" : `已选择 ${value.length} 份报告`}
        </span>
        <ChevronDown
          className={`size-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div className="ios-scrollbar mt-2 max-h-56 overflow-y-auto border-y border-border/70">
          {runs.length === 0 && (
            <div className="px-2 py-3 text-xs text-muted-foreground">暂无分析记录</div>
          )}
          {runs.map((run) => {
            const selectable = run.status === "completed";
            return (
              <label
                key={run.run_id}
                className={`flex items-start gap-2 border-b border-border/50 px-2 py-2 last:border-b-0 ${
                  selectable ? "cursor-pointer hover:bg-sidebar-accent/60" : "cursor-not-allowed opacity-45"
                }`}
              >
                <input
                  type="checkbox"
                  checked={value.includes(run.run_id)}
                  onChange={() => toggleRun(run.run_id)}
                  disabled={!selectable || disabled}
                  className="mt-0.5 size-4 shrink-0 accent-primary"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-foreground">
                    {run.ticker} · {run.trade_date}
                  </span>
                  <span className="mt-0.5 flex items-center justify-between gap-2 font-mono text-[0.62rem] uppercase text-muted-foreground">
                    <span>{run.decision ?? "—"}</span>
                    <span>{statusLabel(run.status)}</span>
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
