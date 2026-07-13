"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { getEtfDiagnosticsMeta, subscribeEtfDiagnostics } from "@/lib/api";
import { resolveVendorSelection } from "@/lib/etf-diagnostics";
import type {
  DiagnosticCell,
  DiagnosticMeta,
  DiagnosticStatus,
  DiagnosticSummary,
} from "@/lib/types";

const GROUPS = ["ETF 核心", "股票基本面", "参考·与 ETF 无关"] as const;
const STORAGE_KEY = "etf-diag-vendors";

const STATUS_META: Record<DiagnosticStatus, { label: string; icon: string; cls: string }> = {
  ok: { label: "成功", icon: "✅", cls: "text-[#6affb0]" },
  no_data: { label: "无数据·输入不对", icon: "⚠️", cls: "text-[#ffcf70]" },
  no_perm: { label: "无权限", icon: "🔒", cls: "text-[#8ab4ff]" },
  unavailable: { label: "不可用", icon: "❌", cls: "text-[#ff6b6b]" },
};

function cellKey(method: string, vendor: string): string {
  return `${method}::${vendor}`;
}

function readSaved(): string[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === "string") : null;
  } catch {
    return null;
  }
}

export default function EtfDiagnosticsPage() {
  const [code, setCode] = useState("");
  const [refDate, setRefDate] = useState(new Date().toISOString().slice(0, 10));
  const [running, setRunning] = useState(false);
  const [total, setTotal] = useState(0);
  const [cells, setCells] = useState<Record<string, DiagnosticCell>>({});
  const [summary, setSummary] = useState<DiagnosticSummary | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [meta, setMeta] = useState<DiagnosticMeta | null>(null);
  const [metaError, setMetaError] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const closeRef = useRef<(() => void) | null>(null);

  // 首屏拉 meta,并用 localStorage∩可用供应商 初始化勾选。
  useEffect(() => {
    let alive = true;
    getEtfDiagnosticsMeta()
      .then((m) => {
        if (!alive) return;
        setMeta(m);
        setSelected(new Set(resolveVendorSelection(readSaved(), m.vendors)));
      })
      .catch(() => alive && setMetaError(true));
    return () => {
      alive = false;
    };
  }, []);

  const done = Object.keys(cells).length;

  // group → method(按 meta 顺序)→ 该 method 的 cells。
  const byMethod = useMemo(() => {
    const acc: Record<string, DiagnosticCell[]> = {};
    for (const c of Object.values(cells)) (acc[c.method] ??= []).push(c);
    return acc;
  }, [cells]);

  const methodsByGroup = useMemo(() => {
    const acc: Record<string, { name: string; desc: string }[]> = {};
    for (const m of meta?.methods ?? []) (acc[m.group] ??= []).push({ name: m.name, desc: m.desc });
    return acc;
  }, [meta]);

  function persist(next: Set<string>) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
    } catch {
      /* ignore quota / private mode */
    }
  }

  function toggleVendor(v: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      persist(next);
      return next;
    });
  }

  function setAll(on: boolean) {
    const next = on ? new Set(meta?.vendors ?? []) : new Set<string>();
    setSelected(next);
    persist(next);
  }

  function start() {
    if (!code.trim() || running || selected.size === 0) return;
    setCells({});
    setSummary(null);
    setTotal(0);
    setRunning(true);
    closeRef.current = subscribeEtfDiagnostics(
      code.trim(),
      refDate,
      [...selected],
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

  const canRun = !!code.trim() && selected.size > 0;

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <h1 className="text-lg font-semibold">ETF 数据端点诊断</h1>

      <div className="glass flex flex-col gap-3 rounded-lg p-4">
        <div className="flex flex-wrap items-end gap-3">
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
              disabled={!canRun}
              className="rounded-md border border-border/60 px-3 py-1.5 text-sm hover:text-primary disabled:opacity-40"
            >
              测试
            </button>
          )}
        </div>

        {/* 供应商多选 */}
        <div className="flex flex-col gap-2 border-t border-border/40 pt-3">
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>供应商</span>
            <button onClick={() => setAll(true)} className="hover:text-primary">
              全选
            </button>
            <button onClick={() => setAll(false)} className="hover:text-primary">
              清空
            </button>
            <span className="text-[11px]">已选 {selected.size}</span>
          </div>
          {metaError ? (
            <p className="text-xs text-[#ff6b6b]">供应商列表加载失败,请刷新页面重试。</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {(meta?.vendors ?? []).map((v) => (
                <label key={v} className="flex items-center gap-1.5 font-mono text-xs">
                  <input
                    type="checkbox"
                    checked={selected.has(v)}
                    onChange={() => toggleVendor(v)}
                  />
                  {v}
                </label>
              ))}
            </div>
          )}
          {!metaError && selected.size === 0 && (
            <p className="text-[11px] text-[#ffcf70]">至少选择一个供应商才能测试。</p>
          )}
        </div>
      </div>

      {summary && (
        <div className="glass flex flex-wrap gap-4 rounded-lg px-4 py-3 font-mono text-sm">
          <span className={STATUS_META.ok.cls}>✅ {summary.ok}</span>
          <span className={STATUS_META.no_data.cls}>⚠️ {summary.no_data}</span>
          <span className={STATUS_META.no_perm.cls}>🔒 {summary.no_perm}</span>
          <span className={STATUS_META.unavailable.cls}>❌ {summary.unavailable}</span>
          <span className="text-muted-foreground">
            用时 {(summary.elapsed_ms / 1000).toFixed(1)}s
          </span>
        </div>
      )}

      {GROUPS.map((group) => {
        const methods = (methodsByGroup[group] ?? []).filter((m) => byMethod[m.name]?.length);
        if (!methods.length) return null;
        return (
          <section key={group} className="glass rounded-lg p-4">
            <h2 className="mb-2 text-sm font-medium text-muted-foreground">{group}</h2>
            <div className="flex flex-col gap-3">
              {methods.map((m) => (
                <div key={m.name}>
                  <div className="flex items-baseline gap-2 font-mono text-xs">
                    <span className="font-medium">{m.name}</span>
                    <span className="text-[11px] text-muted-foreground">— {m.desc}</span>
                  </div>
                  <div className="mt-1 flex flex-col divide-y divide-border/40 pl-3">
                    {byMethod[m.name].map((c) => {
                      const k = cellKey(c.method, c.vendor);
                      const cm = STATUS_META[c.status];
                      return (
                        <div key={k} className="py-1.5">
                          <button
                            onClick={() => setExpanded(expanded === k ? null : k)}
                            className="flex w-full items-center gap-2 text-left font-mono text-xs"
                          >
                            <span className={cm.cls}>{cm.icon}</span>
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
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
