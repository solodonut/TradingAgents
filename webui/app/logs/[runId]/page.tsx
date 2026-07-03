"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, Clock, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getLogView } from "@/lib/api";
import {
  filterTimelineRows,
  getTimelineBarStyle,
  msLabel,
  type LogViewPayload,
  type TimelineRow,
} from "@/lib/log-view";

const TYPE_TONE: Record<string, string> = {
  node_exit: "bg-emerald-400/75 text-emerald-950",
  llm_call: "bg-violet-300/80 text-violet-950",
  vendor_call: "bg-cyan-300/80 text-cyan-950",
  error: "bg-destructive text-background",
};

export default function RunLogPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [data, setData] = useState<LogViewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [type, setType] = useState("");
  const [minMs, setMinMs] = useState(0);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getLogView(runId)
      .then(setData)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    getLogView(runId)
      .then((nextData) => {
        if (!cancelled) setData(nextData);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const visibleRows = useMemo(
    () => filterTimelineRows(data?.timeline ?? [], { type, minMs, query }),
    [data?.timeline, minMs, query, type],
  );
  const eventTypes = useMemo(
    () => Object.keys(data?.event_counts ?? {}).filter((item) => item !== "node_enter").sort(),
    [data?.event_counts],
  );

  return (
    <main className="min-h-screen text-foreground">
      <div className="glass-glow" aria-hidden="true" />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-4 py-4 lg:px-6">
        <header className="glass-readable rounded-lg px-4 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                Run Log Timeline
              </div>
              <h1 className="mt-1 text-xl font-semibold tracking-tight">运行日志视图</h1>
              <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                {runId}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href="/"
                className="glass-control inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:border-primary"
              >
                <ArrowLeft className="size-3.5" />
                返回工作台
              </Link>
              <button
                type="button"
                onClick={load}
                disabled={loading}
                className="glass-control inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground transition-colors hover:text-primary disabled:opacity-60 focus-visible:outline-none focus-visible:border-primary"
              >
                <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
                刷新
              </button>
            </div>
          </div>
        </header>

        {loading && (
          <div className="grid gap-3 md:grid-cols-4" aria-busy="true" aria-label="加载日志">
            <div className="glass h-20 rounded-lg" />
            <div className="glass h-20 rounded-lg" />
            <div className="glass h-20 rounded-lg" />
            <div className="glass h-20 rounded-lg" />
          </div>
        )}

        {error && (
          <section className="glass-readable rounded-lg border-destructive/50 bg-destructive/10 px-4 py-3 text-destructive">
            {error}
          </section>
        )}

        {data && (
          <>
            <section className="grid gap-3 md:grid-cols-4">
              <Metric label="总运行时间" value={data.elapsed_label} />
              <Metric label="耗时事件" value={String(data.timeline.length)} />
              <Metric label="LLM 总耗时" value={msLabel(data.duration_totals.llm_call ?? 0)} />
              <Metric label="数据源总耗时" value={msLabel(data.duration_totals.vendor_call ?? 0)} />
            </section>

            {data.errors.length > 0 && (
              <section className="glass-readable rounded-lg px-4 py-4">
                <div className="mb-3 flex items-center gap-2 text-destructive">
                  <AlertTriangle className="size-4" aria-hidden="true" />
                  <h2 className="font-mono text-[0.72rem] uppercase tracking-[0.16em]">
                    错误原因汇总
                  </h2>
                </div>
                <div className="space-y-2">
                  {data.errors.map((item, index) => (
                    <div
                      key={`${item.seq ?? "result"}-${index}`}
                      className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2"
                    >
                      <div className="font-mono text-[0.68rem] uppercase tracking-[0.12em] text-destructive/80">
                        {item.seq ? `#${item.seq}` : "RESULT"} · {item.source}
                      </div>
                      <div className="mt-1 text-sm text-foreground">{item.message}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section className="glass-readable rounded-lg px-4 py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 font-mono text-[0.72rem] uppercase tracking-[0.16em] text-muted-foreground">
                  <Clock className="size-4" aria-hidden="true" />
                  时序图
                </h2>
                <div className="flex flex-wrap gap-2">
                  <select
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                    className="glass-control h-8 rounded-md px-2 font-mono text-xs"
                    aria-label="按事件类型过滤"
                  >
                    <option value="">全部</option>
                    {eventTypes.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={0}
                    step={100}
                    value={minMs}
                    onChange={(e) => setMinMs(Number(e.target.value || 0))}
                    className="glass-control h-8 w-28 rounded-md px-2 font-mono text-xs"
                    aria-label="最小耗时毫秒"
                  />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="搜索 node/model/vendor"
                    className="glass-control h-8 w-56 rounded-md px-2 font-mono text-xs placeholder:text-muted-foreground/70"
                  />
                </div>
              </div>
              <Timeline rows={visibleRows} elapsedMs={data.elapsed_ms} />
            </section>

            <section className="grid gap-3 lg:grid-cols-2">
              <LogTable title="慢操作排行" rows={data.slow_events} />
              <DurationTable rows={data.node_totals} />
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass-readable rounded-lg px-4 py-3">
      <div className="font-mono text-[0.65rem] uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-lg text-foreground">{value}</div>
    </div>
  );
}

function Timeline({ rows, elapsedMs }: { rows: TimelineRow[]; elapsedMs: number }) {
  return (
    <div className="dark-scrollbar overflow-x-auto rounded-md border border-border/70 bg-black/20">
      <div className="min-w-[64rem]">
        <div className="relative h-8 border-b border-border/70 bg-black/20">
          {Array.from({ length: 6 }, (_, index) => {
            const left = index * 20;
            return (
              <span
                key={left}
                className="absolute top-2 -translate-x-1/2 font-mono text-[0.65rem] text-muted-foreground"
                style={{ left: `${left}%` }}
              >
                {msLabel((elapsedMs * index) / 5)}
              </span>
            );
          })}
        </div>
        {rows.length === 0 ? (
          <div className="px-3 py-5 text-sm text-muted-foreground">没有匹配的耗时事件。</div>
        ) : (
          rows.map((row) => {
            const tone = row.ok === false ? TYPE_TONE.error : (TYPE_TONE[row.type] ?? "bg-slate-300/80 text-slate-950");
            return (
              <div key={`${row.seq}-${row.type}`} className="relative h-9 border-b border-border/40">
                <div
                  className={`absolute top-2 h-5 overflow-hidden rounded px-2 font-mono text-[0.68rem] leading-5 ${tone}`}
                  style={getTimelineBarStyle(row, elapsedMs)}
                  title={`#${row.seq ?? "-"} ${row.type} ${row.label} ${row.duration_label}\n${row.detail}`}
                >
                  #{row.seq ?? "-"} {row.label} · {row.duration_label}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function LogTable({ title, rows }: { title: string; rows: TimelineRow[] }) {
  return (
    <section className="glass-readable rounded-lg px-4 py-4">
      <h2 className="mb-3 font-mono text-[0.72rem] uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </h2>
      <div className="dark-scrollbar max-h-[28rem] overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-card/95 text-muted-foreground">
            <tr>
              <th className="border-b border-border/60 px-2 py-2 text-left font-mono text-[0.65rem] uppercase tracking-[0.12em]">事件</th>
              <th className="border-b border-border/60 px-2 py-2 text-right font-mono text-[0.65rem] uppercase tracking-[0.12em]">耗时</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.seq}-${row.type}`} className="border-b border-border/40">
                <td className="px-2 py-2">
                  <div className="font-mono text-xs text-foreground">#{row.seq ?? "-"} {row.label}</div>
                  <div className="mt-0.5 truncate text-xs text-muted-foreground">{row.type}</div>
                </td>
                <td className="px-2 py-2 text-right font-mono text-xs text-foreground">{row.duration_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DurationTable({ rows }: { rows: { label: string; duration_label: string }[] }) {
  return (
    <section className="glass-readable rounded-lg px-4 py-4">
      <h2 className="mb-3 font-mono text-[0.72rem] uppercase tracking-[0.16em] text-muted-foreground">
        节点总耗时
      </h2>
      <div className="dark-scrollbar max-h-[28rem] overflow-auto">
        <table className="w-full border-collapse text-sm">
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-border/40">
                <td className="px-2 py-2 font-mono text-xs text-foreground">{row.label}</td>
                <td className="px-2 py-2 text-right font-mono text-xs text-foreground">{row.duration_label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
