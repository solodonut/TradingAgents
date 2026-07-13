"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getEtfSnapshot, getEtfSnapshotDates } from "@/lib/api";
import type { EtfSnapshot } from "@/lib/types";
import { buildLinePath, buildAreaPath, chartMarks } from "@/lib/etf-chart";
import { parseIndicatorText, interpretIndicator, type IndicatorTone } from "@/lib/etf-indicators";
import { MarkdownContent } from "@/components/MarkdownContent";

// 红涨绿跌 (A-share convention): gains are red, losses are green.
const UP = "#ff6b6b";
const DOWN = "#6affb0";

const TONE_CLASS: Record<IndicatorTone, string> = {
  up: "text-[#ff6b6b] bg-[#ff6b6b]/12",
  down: "text-[#6affb0] bg-[#6affb0]/12",
  warn: "text-[#ffcf70] bg-[#ffcf70]/12",
  muted: "text-muted-foreground bg-muted",
};

type Kline = { date: string; o: number; h: number; l: number; c: number; vol: number };

function fmtNum(n: number, digits = 3): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtVol(n: number): string {
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(1)}万`;
  return `${n}`;
}

function fmtIndicatorValue(key: string, v: number): string {
  if (key === "rsi") return v.toFixed(1);
  if (key === "macd") return v.toFixed(4);
  return v.toFixed(3);
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-center rounded-lg border border-dashed border-border/60 py-10 text-sm text-muted-foreground">
      {children}
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="glass rounded-xl p-5">
      <div className="mb-4 flex items-baseline justify-between">
        <h2 className="font-heading text-sm font-semibold tracking-wide">{title}</h2>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

// A large area chart with gradient fill, high/low guides, and a current dot.
function PriceChart({ points, id }: { points: { t: string; price: number }[]; id: string }) {
  const W = 800,
    H = 220,
    PAD = 16;
  const marks = chartMarks(points, W, H, PAD);
  if (!marks || points.length < 2) return <EmptyNote>本次预取暂缺,不可用。</EmptyNote>;
  const rising = points[points.length - 1].price >= points[0].price;
  const stroke = rising ? UP : DOWN;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-56 w-full" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        {/* high / low guide lines */}
        <line x1={PAD} x2={W - PAD} y1={marks.high.y} y2={marks.high.y} stroke="currentColor" strokeOpacity={0.12} strokeDasharray="3 4" />
        <line x1={PAD} x2={W - PAD} y1={marks.low.y} y2={marks.low.y} stroke="currentColor" strokeOpacity={0.12} strokeDasharray="3 4" />
        <path d={buildAreaPath(points, W, H, PAD)} fill={`url(#grad-${id})`} />
        <path d={buildLinePath(points, W, H, PAD)} fill="none" stroke={stroke} strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <circle cx={marks.last.x} cy={marks.last.y} r={4} fill={stroke} />
      </svg>
      <div className="mt-3 flex items-center justify-between font-mono text-xs text-muted-foreground">
        <span>
          高 <span className="text-foreground">{fmtNum(marks.max)}</span>
          <span className="mx-2 opacity-40">·</span>
          低 <span className="text-foreground">{fmtNum(marks.min)}</span>
        </span>
        <span>
          {points[0].t} <span className="opacity-40">→</span> {points[points.length - 1].t}
        </span>
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const pts = values.map((v, i) => ({ t: String(i), price: v }));
  const rising = values[values.length - 1] >= values[0];
  return (
    <svg viewBox="0 0 120 32" className="h-8 w-full" preserveAspectRatio="none">
      <path
        d={buildLinePath(pts, 120, 32, 2)}
        fill="none"
        stroke={rising ? UP : DOWN}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

function IndicatorCards({ text, latestClose }: { text: string | undefined; latestClose: number | null }) {
  const indicators = useMemo(() => parseIndicatorText(text), [text]);
  if (indicators.length === 0) return <EmptyNote>本次预取暂缺,不可用。</EmptyNote>;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {indicators.map((ind) => {
        const v = ind.latest?.value ?? null;
        const verdict = v != null ? interpretIndicator(ind.key, v, latestClose) : null;
        return (
          <div key={ind.key} className="flex flex-col gap-3 rounded-lg border border-border/60 p-4" title={ind.description}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium tracking-wide text-muted-foreground">{ind.label}</span>
              {verdict ? (
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${TONE_CLASS[verdict.tone]}`}>
                  {verdict.label}
                </span>
              ) : null}
            </div>
            <div className="font-mono text-2xl font-semibold tabular-nums">
              {v != null ? fmtIndicatorValue(ind.key, v) : "—"}
            </div>
            <Sparkline values={ind.series.map((p) => p.value)} />
            {ind.latest ? (
              <div className="font-mono text-[11px] text-muted-foreground">截至 {ind.latest.date}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function Kpi({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-xl font-semibold tabular-nums" style={color ? { color } : undefined}>
        {value}
      </span>
      {sub ? <span className="font-mono text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

export default function EtfDetailPage() {
  const params = useParams<{ ticker: string }>();
  const ticker = decodeURIComponent(params.ticker);
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<string>("");
  const [snap, setSnap] = useState<EtfSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    getEtfSnapshotDates(ticker)
      .then((ds) => {
        if (cancelled) return;
        setDates(ds);
        setDate(ds[0] ?? "");
      })
      .catch(() => {
        if (!cancelled) setDates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  useEffect(() => {
    if (!date) return;
    let cancelled = false;
    getEtfSnapshot(ticker, date)
      .then((s) => {
        if (!cancelled) setSnap(s);
      })
      .catch(() => {
        if (!cancelled) setSnap(null);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, date]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cat = (name: string): any => snap?.categories?.[name]?.payload;

  const fundItems = (cat("fundamentals")?.items ?? []) as { label: string; value: string }[];
  const pick = (label: string) => fundItems.find((it) => it.label === label)?.value;
  const fundName = pick("基金简称");

  const kline = (cat("indicators")?.kline ?? []) as Kline[];
  const dailyPoints = kline.map((k) => ({ t: k.date, price: k.c }));
  const last = kline[kline.length - 1];
  const prev = kline[kline.length - 2];
  const change = last && prev ? last.c - prev.c : null;
  const changePct = change != null && prev ? (change / prev.c) * 100 : null;
  const changeColor = change == null ? undefined : change >= 0 ? UP : DOWN;

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-6">
      {/* Header: identity + date picker */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-4 w-4" /> 返回
          </Link>
          <Link
            href="/etf/diagnostics"
            className="rounded-md border border-border/60 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-primary"
          >
            端点诊断
          </Link>
        </div>
        <select
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="glass-control rounded-md px-3 py-1.5 text-sm"
        >
          {dates.length === 0 ? <option value="">无快照</option> : null}
          {dates.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="font-heading text-2xl font-bold">{fundName ?? ticker}</h1>
        <span className="font-mono text-sm text-muted-foreground">{ticker}</span>
        {pick("管理人") ? <span className="text-sm text-muted-foreground">· {pick("管理人")}</span> : null}
      </div>

      {!date ? (
        <EmptyNote>该 ETF 当天无数据快照。</EmptyNote>
      ) : (
        <>
          {/* KPI strip */}
          <section className="glass grid grid-cols-2 gap-4 rounded-xl p-5 sm:grid-cols-4">
            <Kpi
              label="最新收盘"
              value={last ? fmtNum(last.c) : "—"}
              color={changeColor}
              sub={
                change != null && changePct != null
                  ? `${change >= 0 ? "+" : ""}${fmtNum(change)} (${change >= 0 ? "+" : ""}${changePct.toFixed(2)}%)`
                  : undefined
              }
            />
            <Kpi label="日内区间" value={last ? `${fmtNum(last.l)} – ${fmtNum(last.h)}` : "—"} />
            <Kpi label="成交量" value={last ? fmtVol(last.vol) : "—"} sub="股" />
            <Kpi label="最新净值" value={pick("最新净值") ?? "—"} sub={pick("上市日期") ? `上市 ${pick("上市日期")}` : undefined} />
          </section>

          <Section title="价格走势" hint={`${dailyPoints.length} 个交易日 · 收盘价`}>
            <PriceChart points={dailyPoints} id="daily" />
          </Section>

          <Section title="技术指标">
            <IndicatorCards text={cat("indicators")?.indicator_text} latestClose={last?.c ?? null} />
          </Section>

          <Section title="相关新闻">
            {cat("news")?.text ? (
              <div className="ta-prose prose prose-invert prose-sm max-w-none prose-headings:font-heading prose-h1:text-base prose-h1:mt-0 prose-h2:text-sm prose-h3:text-sm">
                <MarkdownContent content={cat("news").text} />
              </div>
            ) : (
              <EmptyNote>本次预取暂缺,不可用。</EmptyNote>
            )}
          </Section>
        </>
      )}
    </main>
  );
}
