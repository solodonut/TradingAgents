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
      <div className="rounded-lg border border-border bg-card px-3 py-3 font-mono text-sm">
        <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          Archived Run
        </div>
        <div className="mt-1 text-foreground">
          {run.ticker} · {run.trade_date}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
          <span>状态 {run.status}</span>
          <span>开始 {fmtTime(run.created_at)}</span>
          <span>结束 {fmtTime(run.completed_at)}</span>
        </div>
      </div>

      {run.status === "running" && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 font-mono text-xs text-amber-300">
          仍在进行，以下为目前已生成的部分
        </div>
      )}

      {run.status === "error" && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
          该分析以错误结束
        </div>
      )}

      {run.status === "cancelled" && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 font-mono text-xs text-amber-300">
          该分析已停止，以下为停止前已生成的部分
        </div>
      )}

      {isEmpty && run.status === "running" && (
        <div className="rounded-md border border-dashed border-border bg-card px-3 py-3 font-mono text-xs text-muted-foreground">
          尚未生成可持久化的阶段报告
        </div>
      )}

      {isEmpty && run.status !== "running" && run.status !== "error" && run.status !== "cancelled" && (
        <div className="rounded-md border border-dashed border-border bg-card px-3 py-3 font-mono text-xs text-muted-foreground">
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
