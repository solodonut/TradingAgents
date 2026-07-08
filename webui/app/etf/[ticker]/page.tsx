"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { getEtfSnapshot, getEtfSnapshotDates } from "@/lib/api";
import type { EtfSnapshot } from "@/lib/types";
import { buildLinePath } from "@/lib/etf-chart";
import { MarkdownContent } from "@/components/MarkdownContent";

function MissingNote() {
  return <p className="text-sm text-muted-foreground">本次预取暂缺,不可用。</p>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function IntradayChart({ payload }: { payload: any }) {
  const points = (payload?.points ?? []) as { t: string; price: number }[];
  if (points.length === 0) return <MissingNote />;
  const W = 640, H = 200, PAD = 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-48">
      <path d={buildLinePath(points, W, H, PAD)} fill="none" stroke="currentColor" strokeWidth={1.5} />
    </svg>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function DailyChart({ payload }: { payload: any }) {
  const kline = (payload?.kline ?? []) as { date: string; c: number }[];
  if (kline.length === 0) return <MissingNote />;
  const pts = kline.map((k) => ({ t: k.date, price: k.c }));
  const W = 640, H = 200, PAD = 8;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-48">
        <path d={buildLinePath(pts, W, H, PAD)} fill="none" stroke="currentColor" strokeWidth={1.5} />
      </svg>
      {payload?.indicator_text ? <MarkdownContent content={payload.indicator_text} /> : null}
    </>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function Fundamentals({ payload }: { payload: any }) {
  const items = (payload?.items ?? []) as { label: string; value: string }[];
  if (items.length === 0) return <MissingNote />;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {items.map((it) => (
        <div key={it.label} className="rounded-lg border p-3">
          <div className="text-xs text-muted-foreground">{it.label}</div>
          <div className="text-lg font-semibold">{it.value}</div>
        </div>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border p-4">
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
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
    if (!date) {
      return;
    }
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

  const cat = (name: string) => snap?.categories?.[name]?.payload;

  return (
    <main className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground">
          <ArrowLeft className="h-4 w-4" /> 返回
        </Link>
        <h1 className="text-lg font-bold">{ticker}</h1>
        <select
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded-md border px-2 py-1 text-sm"
        >
          {dates.length === 0 ? <option value="">无快照</option> : null}
          {dates.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {!date ? <p className="text-sm text-muted-foreground">该 ETF 当天无数据快照。</p> : null}

      <Section title="分时价格"><IntradayChart payload={cat("intraday")} /></Section>
      <Section title="技术指标 / 日线"><DailyChart payload={cat("indicators")} /></Section>
      <Section title="新闻">
        {cat("news")?.text ? <MarkdownContent content={cat("news").text} /> : <MissingNote />}
      </Section>
      <Section title="基本面"><Fundamentals payload={cat("fundamentals")} /></Section>
    </main>
  );
}
