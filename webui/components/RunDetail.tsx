"use client";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import type { RunResult } from "@/lib/types";

// section field name -> Chinese agent label, in REPORT_SECTIONS order (api/runner.py).
// final_trade_decision is rendered as the DecisionCard, not a MessageBubble.
const SECTIONS: { field: string; label: string }[] = [
  { field: "market_report", label: "市场" },
  { field: "sentiment_report", label: "情绪" },
  { field: "news_report", label: "新闻" },
  { field: "fundamentals_report", label: "基本面" },
  { field: "investment_plan", label: "研究经理" },
  { field: "trader_investment_plan", label: "交易员" },
];

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function RunDetail({ run }: { run: RunResult }) {
  const result = run.result ?? {};
  const sections = SECTIONS.filter((s) => {
    const v = result[s.field];
    return typeof v === "string" && v.trim().length > 0;
  });
  const finalDetail = result["final_trade_decision"];
  const hasFinal = typeof finalDetail === "string" && finalDetail.trim().length > 0;
  const isEmpty = sections.length === 0 && !hasFinal && !run.decision;

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-zinc-700/80 bg-zinc-900 px-3 py-2.5 font-mono text-sm">
        <div className="text-zinc-200">
          {run.ticker} · {run.trade_date}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-500">
          <span>状态 {run.status}</span>
          <span>开始 {fmtTime(run.created_at)}</span>
          <span>结束 {fmtTime(run.completed_at)}</span>
        </div>
      </div>

      {run.status === "running" && (
        <div className="rounded border border-amber-800/60 bg-amber-950/30 px-3 py-2 font-mono text-xs text-amber-400">
          仍在进行 — 以下为目前已生成的部分
        </div>
      )}

      {run.status === "error" && (
        <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 font-mono text-sm text-red-400">
          该分析以错误结束
        </div>
      )}

      {isEmpty && run.status !== "error" && (
        <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-500">
          暂无可显示的报告内容
        </div>
      )}

      {sections.map((s) => (
        <MessageBubble key={s.field} agent={s.label} content={result[s.field] as string} />
      ))}

      {run.decision && (
        <DecisionCard decision={run.decision} detail={hasFinal ? (finalDetail as string) : ""} />
      )}
    </div>
  );
}
