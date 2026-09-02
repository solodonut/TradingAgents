"use client";
import { ChevronDown, ChevronUp, Eye, ListOrdered, OctagonX, Trash2, X } from "lucide-react";
import type { QueueState } from "@/lib/types";

// Mirrors MAX_PARALLEL_RUNS_LIMIT in api/schemas.py.
const PARALLEL_OPTIONS = [1, 2, 3, 4];

export function QueuePanel({
  queue,
  onRemove,
  onClear,
  onReorder,
  onCancelRunning,
  maxParallel,
  onChangeMaxParallel,
  followedRunId = null,
  onFollow,
  canceling = false,
  disabled = false,
  disabledReason = "",
}: {
  queue: QueueState;
  onRemove: (runId: string) => void;
  onClear: () => void;
  onReorder: (orderedRunIds: string[]) => void;
  onCancelRunning: (runId: string) => void;
  maxParallel: number;
  onChangeMaxParallel: (value: number) => void;
  followedRunId?: string | null;
  onFollow: (runId: string) => void;
  canceling?: boolean;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const pending = queue.pending;

  const move = (index: number, delta: number) => {
    const next = [...pending];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onReorder(next.map((p) => p.run_id));
  };

  return (
    <div className="glass rounded-lg px-3 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          <ListOrdered className="size-3.5" aria-hidden="true" />
          分析队列
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
            并发
            <select
              value={maxParallel}
              onChange={(e) => onChangeMaxParallel(Number(e.target.value))}
              title="同时运行的分析数量"
              className="glass-control rounded px-1.5 py-0.5 font-mono text-[0.68rem] text-foreground focus-visible:outline-none focus-visible:border-primary"
            >
              {PARALLEL_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          {pending.length > 0 && (
            <button
              type="button"
              onClick={onClear}
              disabled={disabled}
              title={disabled ? disabledReason : undefined}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Trash2 className="size-3" aria-hidden="true" />
              清空
            </button>
          )}
        </div>
      </div>
      {disabled && disabledReason && (
        <p className="mt-2 font-mono text-[0.68rem] leading-5 text-amber-300">{disabledReason}</p>
      )}

      <ul className="mt-2 space-y-1.5">
        {queue.running.map((item) => {
          const followed = item.run_id === followedRunId;
          return (
            <li
              key={item.run_id}
              className={`thinking-panel flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 ${
                followed ? "border-primary" : ""
              }`}
            >
              <span className="truncate font-mono text-xs text-foreground">{item.ticker}</span>
              <span className="flex items-center gap-1">
                <span className="mr-1 font-mono text-[0.6rem] uppercase tracking-[0.14em] text-amber-300">
                  {followed ? "观察中" : "运行中"}
                </span>
                <button
                  type="button"
                  onClick={() => onFollow(item.run_id)}
                  disabled={followed}
                  title={followed ? "已在下方实时面板显示" : "在下方实时面板观察这个分析"}
                  aria-label={`观察 ${item.ticker}`}
                  className={`inline-flex size-6 items-center justify-center rounded transition-colors focus-visible:outline-none focus-visible:border-primary ${
                    followed
                      ? "text-primary opacity-100"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Eye className="size-3.5" aria-hidden="true" />
                </button>
                <button
                  type="button"
                  onClick={() => onCancelRunning(item.run_id)}
                  disabled={canceling}
                  aria-label={`停止 ${item.ticker}`}
                  className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50 focus-visible:outline-none focus-visible:border-primary"
                >
                  <OctagonX className="size-3.5" aria-hidden="true" />
                </button>
              </span>
            </li>
          );
        })}

        {pending.map((item, index) => (
          <li
            key={item.run_id}
            className="glass-control flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5"
          >
            <span className="truncate font-mono text-xs text-muted-foreground">
              <span className="mr-1.5 text-[0.62rem] text-muted-foreground/70">
                {index + 1}
              </span>
              {item.ticker}
            </span>
            <span className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => move(index, -1)}
                disabled={disabled || index === 0}
                title={disabled ? disabledReason : "上移"}
                aria-label="上移"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
              >
                <ChevronUp className="size-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                disabled={disabled || index === pending.length - 1}
                title={disabled ? disabledReason : "下移"}
                aria-label="下移"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:border-primary"
              >
                <ChevronDown className="size-3.5" aria-hidden="true" />
              </button>
              <button
                type="button"
                onClick={() => onRemove(item.run_id)}
                disabled={disabled}
                title={disabled ? disabledReason : "移除"}
                aria-label="移除"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:border-primary"
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
