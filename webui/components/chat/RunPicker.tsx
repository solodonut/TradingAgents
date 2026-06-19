"use client";

import { useEffect, useState } from "react";
import { getHistory } from "@/lib/api";
import type { HistorySummary } from "@/lib/types";

export function RunPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (runId: string | null) => void;
}) {
  const [runs, setRuns] = useState<HistorySummary[]>([]);
  useEffect(() => {
    getHistory()
      .then((rs) => setRuns(rs.filter((r) => r.status === "completed")))
      .catch(() => setRuns([]));
  }, []);
  return (
    <div className="glass-readable rounded-lg px-3 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
        关联分析报告
      </div>
      <select
        className="glass-control mt-2 w-full rounded-md px-2 py-1 text-sm outline-none focus:border-primary"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">不关联(通用咨询)</option>
        {runs.map((r) => (
          <option key={r.run_id} value={r.run_id}>
            {r.ticker} · {r.trade_date} · {r.decision ?? "—"}
          </option>
        ))}
      </select>
    </div>
  );
}
