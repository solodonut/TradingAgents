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
    <div className="rounded-lg border border-border bg-card px-3 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
        关联分析报告
      </div>
      <select
        className="mt-2 w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
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
