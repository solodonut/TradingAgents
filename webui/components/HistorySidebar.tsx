"use client";
import { ChevronDown, Download, LoaderCircle, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { getExpandedHistoryDates } from "@/lib/history-groups";
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
  selectedRunIds,
  onOpen,
  onDelete,
  onToggleRun,
  onToggleDate,
  onExportSelected,
  exporting = false,
}: {
  items: HistorySummary[];
  selectedId: string | null;
  selectedRunIds: Set<string>;
  onOpen: (runId: string) => void;
  onDelete: (runId: string) => void;
  onToggleRun: (runId: string) => void;
  onToggleDate: (runIds: string[], selected: boolean) => void;
  onExportSelected: () => void;
  exporting?: boolean;
}) {
  const selectedCount = selectedRunIds.size;
  const groups = useMemo(() => {
    const byDate = new Map<string, HistorySummary[]>();
    for (const item of items) {
      const group = byDate.get(item.trade_date) ?? [];
      group.push(item);
      byDate.set(item.trade_date, group);
    }
    return Array.from(byDate.entries()).map(([tradeDate, runs]) => ({
      tradeDate,
      runs,
      runIds: runs.map((run) => run.run_id),
    }));
  }, [items]);
  const selectedTradeDate =
    selectedId ? (items.find((item) => item.run_id === selectedId)?.trade_date ?? null) : null;
  const tradeDates = useMemo(() => groups.map((group) => group.tradeDate), [groups]);
  const [expandedDates, setExpandedDates] = useState<Set<string> | null>(null);
  const visibleExpandedDates = useMemo(
    () =>
      getExpandedHistoryDates({
        tradeDates,
        selectedTradeDate,
        previousExpanded: expandedDates,
      }),
    [expandedDates, selectedTradeDate, tradeDates],
  );

  const toggleDateExpanded = (tradeDate: string) => {
    setExpandedDates((previousExpanded) => {
      const next = getExpandedHistoryDates({
        tradeDates,
        selectedTradeDate,
        previousExpanded,
      });
      if (next.has(tradeDate)) {
        next.delete(tradeDate);
      } else {
        next.add(tradeDate);
      }
      return next;
    });
  };

  return (
    <aside className="dark-scrollbar glass h-full overflow-y-auto rounded-none text-sidebar-foreground">
      <div className="glass-readable sticky top-0 z-10 rounded-none border-x-0 border-t-0 px-3 py-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              History Queue
            </div>
            <div className="mt-0.5 text-sm text-foreground">历史分析</div>
          </div>
          <button
            type="button"
            onClick={onExportSelected}
            disabled={selectedCount === 0 || exporting}
            title="导出已选报告"
            className="glass-control inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:border-primary"
          >
            <span className="sr-only">导出已选报告</span>
            {exporting ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
            ) : (
              <Download className="size-4" aria-hidden="true" />
            )}
          </button>
        </div>
        {selectedCount > 0 && (
          <div className="mt-2 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
            已选择 {selectedCount}
          </div>
        )}
      </div>

      <div className="space-y-1 p-2">
        {items.length === 0 && (
          <div className="glass-readable rounded-md border-dashed border-sidebar-border px-3 py-3 text-xs leading-relaxed text-muted-foreground">
            完成的分析会出现在这里。打开历史记录可以复盘每个 agent 的报告和最终决策。
          </div>
        )}

        {groups.map((group) => {
          const selectedInGroup = group.runIds.filter((runId) => selectedRunIds.has(runId)).length;
          const allSelected = selectedInGroup === group.runIds.length;
          const partiallySelected = selectedInGroup > 0 && !allSelected;
          const expanded = visibleExpandedDates.has(group.tradeDate);
          return (
            <div key={group.tradeDate} className="space-y-1">
              <div className="glass-control flex items-center gap-2 rounded-md px-2 py-1.5">
                <DateCheckbox
                  checked={allSelected}
                  indeterminate={partiallySelected}
                  onChange={() => onToggleDate(group.runIds, !allSelected)}
                />
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left focus-visible:outline-none focus-visible:text-foreground"
                  aria-expanded={expanded}
                  onClick={() => toggleDateExpanded(group.tradeDate)}
                >
                  <span className="truncate font-mono text-[0.68rem] uppercase tracking-[0.12em] text-muted-foreground">
                    {group.tradeDate}
                  </span>
                  <ChevronDown
                    className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${
                      expanded ? "rotate-0" : "-rotate-90"
                    }`}
                    aria-hidden="true"
                  />
                </button>
              </div>

              {expanded && group.runs.map((it) => {
                const active = it.run_id === selectedId;
                const checked = selectedRunIds.has(it.run_id);
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
                      <div className="flex min-w-0 items-start gap-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          aria-label={`选择 ${it.ticker} ${it.trade_date} 报告`}
                          className="mt-0.5 size-4 shrink-0 accent-primary"
                          onChange={() => onToggleRun(it.run_id)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <div className="min-w-0">
                          <div className="truncate font-mono text-sm text-foreground">
                            {it.ticker}
                          </div>
                          {it.instrument_name && (
                            <div className="mt-0.5 truncate text-xs text-muted-foreground">
                              {it.instrument_name}
                            </div>
                          )}
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
                    <div className="mt-2 flex items-center gap-1.5 pl-6">
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
          );
        })}
      </div>
    </aside>
  );
}

function DateCheckbox({
  checked,
  indeterminate,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      aria-label="按日期选择报告"
      className="size-4 shrink-0 accent-primary"
      onChange={onChange}
    />
  );
}
