"use client";
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
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs font-mono rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2">
      {AGENTS.map((a) => {
        const s = statuses[a.id] ?? "pending";
        const color =
          s === "done"
            ? "text-emerald-400"
            : s === "working"
              ? "text-amber-400"
              : "text-zinc-600";
        const working = s === "working";
        const mark = s === "done" ? "✓" : working ? "⟳" : "·";
        return (
          <span key={a.id} className={`${color} tabular-nums`}>
            <span
              className={`inline-block ${working ? "animate-spin motion-reduce:animate-none" : ""}`}
              aria-hidden="true"
            >
              {mark}
            </span>{" "}
            {a.label}
          </span>
        );
      })}
    </div>
  );
}
