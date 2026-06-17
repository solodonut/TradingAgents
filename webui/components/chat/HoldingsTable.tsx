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
      <div className="text-sm text-muted-foreground">尚无持仓。上传截图或手动添加。</div>
    );
  }
  const update = (i: number, field: keyof PortfolioHolding, raw: string) => {
    const next = [...holdings];
    const numeric = ["shares", "avg_cost", "market_value", "weight"];
    next[i] = {
      ...next[i],
      [field]: numeric.includes(field) ? (raw === "" ? null : Number(raw)) : raw,
    };
    onChange(next);
  };
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="font-mono text-[0.65rem] uppercase text-muted-foreground">
          <th className="text-left">代码</th>
          <th className="text-left">股数</th>
          <th className="text-left">成本</th>
          <th className="text-left">占比%</th>
        </tr>
      </thead>
      <tbody>
        {holdings.map((h, i) => (
          <tr key={i} className="border-t border-border">
            <td>
              <input
                className="w-full bg-transparent"
                value={h.ticker}
                onChange={(e) => update(i, "ticker", e.target.value)}
              />
            </td>
            <td>
              <input
                className="w-full bg-transparent"
                value={h.shares ?? ""}
                onChange={(e) => update(i, "shares", e.target.value)}
              />
            </td>
            <td>
              <input
                className="w-full bg-transparent"
                value={h.avg_cost ?? ""}
                onChange={(e) => update(i, "avg_cost", e.target.value)}
              />
            </td>
            <td>
              <input
                className="w-full bg-transparent"
                value={h.weight ?? ""}
                onChange={(e) => update(i, "weight", e.target.value)}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
