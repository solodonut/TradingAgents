"use client";

import type { PortfolioHolding } from "@/lib/types";

export function HoldingsTable({
  holdings,
  onChange,
}: {
  holdings: PortfolioHolding[];
  onChange: (next: PortfolioHolding[]) => void;
}) {
  if (holdings.length === 0) {
    return (
      <div className="glass-control rounded-md border-dashed border-border/70 px-3 py-2 text-sm text-muted-foreground">
        尚无持仓。上传截图或手动添加。
      </div>
    );
  }
  const update = (i: number, field: keyof PortfolioHolding, raw: string) => {
    const next = [...holdings];
    const numeric = [
      "shares",
      "avg_cost",
      "current_price",
      "market_value",
      "weight",
      "unrealized_pnl",
      "return_rate",
      "daily_pnl",
      "daily_return_rate",
    ];
    next[i] = {
      ...next[i],
      [field]: numeric.includes(field) ? (raw === "" ? null : Number(raw)) : raw,
    };
    onChange(next);
  };
  const displayName = (h: PortfolioHolding) => h.name || h.ticker;
  const updateIdentity = (i: number, raw: string) => {
    const next = [...holdings];
    next[i] = { ...next[i], name: raw, ticker: raw };
    onChange(next);
  };
  return (
    <div className="space-y-2">
      {holdings.map((h, i) => (
        <div key={i} className="border-t border-border pt-2">
          <input
            className="mb-1 w-full bg-transparent text-sm font-medium text-foreground"
            value={displayName(h)}
            onChange={(e) => updateIdentity(i, e.target.value)}
            aria-label="持仓名称"
          />
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4">
            <label className="text-muted-foreground">
              市值/金额
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.market_value ?? ""}
                onChange={(e) => update(i, "market_value", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              持有收益
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.unrealized_pnl ?? ""}
                onChange={(e) => update(i, "unrealized_pnl", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              收益率%
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.return_rate ?? ""}
                onChange={(e) => update(i, "return_rate", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              当日/昨日
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.daily_pnl ?? ""}
                onChange={(e) => update(i, "daily_pnl", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              股数/份额
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.shares ?? ""}
                onChange={(e) => update(i, "shares", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              成本
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.avg_cost ?? ""}
                onChange={(e) => update(i, "avg_cost", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              现价
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.current_price ?? ""}
                onChange={(e) => update(i, "current_price", e.target.value)}
              />
            </label>
            <label className="text-muted-foreground">
              占比%
              <input
                className="mt-0.5 w-full bg-transparent text-foreground"
                value={h.weight ?? ""}
                onChange={(e) => update(i, "weight", e.target.value)}
              />
            </label>
          </div>
        </div>
      ))}
    </div>
  );
}
