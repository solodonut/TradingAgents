"use client";

import { useMemo, useRef, useState } from "react";

import { subscribeEtfDiagnostics } from "@/lib/api";
import type { DiagnosticCell, DiagnosticStatus, DiagnosticSummary } from "@/lib/types";

const GROUPS = ["ETF 核心", "股票基本面", "参考·与 ETF 无关"] as const;

const STATUS_META: Record<DiagnosticStatus, { label: string; icon: string; cls: string }> = {
  ok: { label: "成功", icon: "✅", cls: "text-[#6affb0]" },
  no_data: { label: "无数据·输入不对", icon: "⚠️", cls: "text-[#ffcf70]" },
  no_perm: { label: "无权限", icon: "🔒", cls: "text-[#8ab4ff]" },
  unavailable: { label: "不可用", icon: "❌", cls: "text-[#ff6b6b]" },
};

function cellKey(method: string, vendor: string): string {
  return `${method}::${vendor}`;
}

export default function EtfDiagnosticsPage() {
  const [code, setCode] = useState("");
  const [refDate, setRefDate] = useState(new Date().toISOString().slice(0, 10));
  const [running, setRunning] = useState(false);
  const [total, setTotal] = useState(0);
  const [cells, setCells] = useState<Record<string, DiagnosticCell>>({});
  const [summary, setSummary] = useState<DiagnosticSummary | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const closeRef = useRef<(() => void) | null>(null);

  const done = Object.keys(cells).length;

  const grouped = useMemo(() => {
    const byGroup: Record<string, DiagnosticCell[]> = {};
    for (const c of Object.values(cells)) (byGroup[c.group] ??= []).push(c);
    return byGroup;
  }, [cells]);

  function start() {
    if (!code.trim() || running) return;
    setCells({});
    setSummary(null);
    setTotal(0);
    setRunning(true);
    closeRef.current = subscribeEtfDiagnostics(
      code.trim(),
      refDate,
      (e) => {
        if (e.event === "start") setTotal(e.data.total);
        else if (e.event === "cell")
          setCells((prev) => ({ ...prev, [cellKey(e.data.method, e.data.vendor)]: e.data }));
        else if (e.event === "done") setSummary(e.data);
      },
      () => setRunning(false),
      () => setRunning(false),
    );
  }

  function stop() {
    closeRef.current?.();
    closeRef.current = null;
    setRunning(false);
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <h1 className="text-lg font-semibold">ETF 数据端点诊断</h1>

      <div className="glass flex flex-wrap items-end gap-3 rounded-lg p-4">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          ETF 代码
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="510300.SS"
            className="rounded-md border border-border/60 bg-black/20 px-2 py-1 font-mono text-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          参考日期
          <input
            type="date"
            value={refDate}
            onChange={(e) => setRefDate(e.target.value)}
            className="rounded-md border border-border/60 bg-black/20 px-2 py-1 font-mono text-sm"
          />
        </label>
        {running ? (
          <button
            onClick={stop}
            className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary"
          >
            停止 ({done}/{total})
          </button>
        ) : (
          <button
            onClick={start}
            disabled={!code.trim()}
            className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary disabled:opacity-40"
          >
            测试
          </button>
        )}
      </div>

      {summary && (
        <div className="glass flex flex-wrap gap-4 rounded-lg px-4 py-3 font-mono text-sm">
          <span className={STATUS_META.ok.cls}>✅ {summary.ok}</span>
          <span className={STATUS_META.no_data.cls}>⚠️ {summary.no_data}</span>
          <span className={STATUS_META.no_perm.cls}>🔒 {summary.no_perm}</span>
          <span className={STATUS_META.unavailable.cls}>❌ {summary.unavailable}</span>
          <span className="text-muted-foreground">用时 {(summary.elapsed_ms / 1000).toFixed(1)}s</span>
        </div>
      )}

      {GROUPS.filter((g) => grouped[g]?.length).map((group) => (
        <section key={group} className="glass rounded-lg p-4">
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">{group}</h2>
          <div className="flex flex-col divide-y divide-border/40">
            {grouped[group].map((c) => {
              const k = cellKey(c.method, c.vendor);
              const meta = STATUS_META[c.status];
              return (
                <div key={k} className="py-1.5">
                  <button
                    onClick={() => setExpanded(expanded === k ? null : k)}
                    className="flex w-full items-center gap-2 text-left font-mono text-xs"
                  >
                    <span className={meta.cls}>{meta.icon}</span>
                    <span className="w-56 truncate">{c.method}</span>
                    <span className="w-28 truncate text-muted-foreground">{c.vendor}</span>
                    <span className="text-muted-foreground">{c.elapsed_ms.toFixed(0)}ms</span>
                  </button>
                  {expanded === k && (
                    <pre className="mt-1 max-h-72 overflow-auto rounded-md border border-border/60 bg-black/30 p-2 text-[11px] whitespace-pre-wrap">
                      {c.error_type ? `[${c.error_type}] ` : ""}
                      {c.raw}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </main>
  );
}
