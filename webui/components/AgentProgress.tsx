"use client";
import { Check, Circle, LoaderCircle } from "lucide-react";

const AGENTS: { id: string; label: string }[] = [
  { id: "market_analyst", label: "市场" },
  { id: "social_analyst", label: "情绪" },
  { id: "news_analyst", label: "新闻" },
  { id: "fundamentals_analyst", label: "基本面" },
  { id: "research_manager", label: "研究经理" },
  { id: "trader", label: "交易员" },
  { id: "portfolio_manager", label: "组合经理" },
];

export function AgentProgress({ statuses }: { statuses: Record<string, string> }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-3 py-2">
        <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          Agent Matrix
        </div>
      </div>
      <div className="grid grid-cols-1 divide-y divide-border/70">
      {AGENTS.map((a) => {
        const s = statuses[a.id] ?? "pending";
        const tone =
          s === "done"
            ? "text-primary"
            : s === "working"
              ? "text-amber-300"
              : "text-muted-foreground";
        const working = s === "working";
        const statusText = s === "done" ? "DONE" : working ? "WORKING" : "PENDING";
        const Icon = s === "done" ? Check : working ? LoaderCircle : Circle;
        return (
          <div
            key={a.id}
            className="grid grid-cols-[1rem_minmax(0,1fr)_4.75rem] items-center gap-2 px-3 py-2 font-mono text-xs"
          >
            <Icon
              className={`size-3.5 ${tone} ${working ? "animate-spin motion-reduce:animate-none" : ""}`}
              aria-hidden="true"
            />
            <div className="min-w-0">
              <div className="truncate text-foreground">{a.label}</div>
              <div className="truncate text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                {a.id}
              </div>
            </div>
            <span
              className={`text-right text-[0.65rem] uppercase tracking-[0.12em] tabular-nums ${tone}`}
            >
              {statusText}
            </span>
          </div>
        );
      })}
      </div>
    </div>
  );
}
