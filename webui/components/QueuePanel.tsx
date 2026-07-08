"use client";
import { ChevronDown, ChevronUp, ListOrdered, OctagonX, Trash2, X } from "lucide-react";
import type { QueueState } from "@/lib/types";

export function QueuePanel({
  queue,
  onRemove,
  onClear,
  onReorder,
  onCancelRunning,
  canceling = false,
  disabled = false,
  disabledReason = "",
}: {
  queue: QueueState;
  onRemove: (runId: string) => void;
  onClear: () => void;
  onReorder: (orderedRunIds: string[]) => void;
  onCancelRunning: (runId: string) => void;
  canceling?: boolean;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const pending = queue.pending;
  const hasItems = queue.running !== null || pending.length > 0;
  if (!hasItems) return null;

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

      <ul className="mt-2 space-y-1.5">
        {queue.running && (
          <li className="thinking-panel flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5">
            <span className="truncate font-mono text-sm text-foreground">
              {queue.running.ticker}
            </span>
            <span className="flex items-center gap-2">
              <span className="font-mono text-[0.6rem] uppercase tracking-[0.14em] text-amber-300">
                运行中
              </span>
              <button
                type="button"
                onClick={() => onCancelRunning(queue.running!.run_id)}
                disabled={canceling}
                aria-label="停止当前分析"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50 focus-visible:outline-none focus-visible:border-primary"
              >
                <OctagonX className="size-3.5" aria-hidden="true" />
              </button>
            </span>
          </li>
        )}

        {pending.map((item, index) => (
          <li
            key={item.run_id}
            className="glass-control flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5"
          >
            <span className="truncate font-mono text-sm text-muted-foreground">
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
