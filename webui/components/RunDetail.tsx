"use client";
import { Download, LoaderCircle, OctagonX } from "lucide-react";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import { RuntimeStatusPanel } from "@/components/RuntimeStatusPanel";
import type { RunResult, RunStatusDetail } from "@/lib/types";

// section field name -> Chinese agent label, in REPORT_SECTIONS order (api/runner.py).
// final_trade_decision is rendered as the DecisionCard, not a MessageBubble.
const SECTIONS: { field: string; label: string }[] = [
  { field: "market_report", label: "市场" },
  { field: "sentiment_report", label: "情绪" },
  { field: "news_report", label: "新闻" },
  { field: "fundamentals_report", label: "基本面" },
  { field: "investment_plan", label: "研究经理" },
  { field: "trader_investment_plan", label: "交易员" },
  { field: "validation_report", label: "报告校验" },
];

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

// Assemble the full run into a single Markdown document. Each report field is
// already a Markdown string, so we just wrap them under `##` headings.
function buildMarkdown(run: RunResult): string {
  const result = run.result ?? {};
  const title = run.instrument_name ? `${run.ticker} ${run.instrument_name}` : run.ticker;
  const lines: string[] = [
    `# ${title} · ${run.trade_date} 分析报告`,
    "",
    `- 决策：${run.decision ?? "—"}`,
    `- 状态：${run.status}`,
    `- 开始：${fmtTime(run.created_at)}`,
    `- 结束：${fmtTime(run.completed_at)}`,
    "",
  ];
  for (const s of SECTIONS) {
    const v = result[s.field];
    if (typeof v === "string" && v.trim().length > 0) {
      lines.push(`## ${s.label}`, "", v.trim(), "");
    }
  }
  const final = result["final_trade_decision"];
  if (typeof final === "string" && final.trim().length > 0) {
    lines.push("## 最终决策", "", final.trim(), "");
  }
  return lines.join("\n");
}

function exportMarkdown(run: RunResult): void {
  const blob = new Blob([buildMarkdown(run)], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${run.ticker}_${run.trade_date}_analysis.md`;
  a.click();
  URL.revokeObjectURL(url);
}

export function RunDetail({
  run,
  runtime,
  runtimeError,
  currentAgentLabel,
  onCancel,
  canceling = false,
}: {
  run: RunResult;
  runtime?: RunStatusDetail | null;
  runtimeError?: string | null;
  currentAgentLabel?: string | null;
  onCancel?: (runId: string) => void;
  canceling?: boolean;
}) {
  const result = run.result ?? {};
  const title = run.instrument_name ? `${run.ticker} ${run.instrument_name}` : run.ticker;
  const sections = SECTIONS.filter((s) => {
    const v = result[s.field];
    return typeof v === "string" && v.trim().length > 0;
  });
  const finalDetail = result["final_trade_decision"];
  const hasFinal = typeof finalDetail === "string" && finalDetail.trim().length > 0;
  const isEmpty = sections.length === 0 && !hasFinal && !run.decision;

  return (
    <div className="space-y-3">
      <div className="glass rounded-lg px-3 py-3 font-mono text-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Archived Run
          </div>
          {(sections.length > 0 || hasFinal) && (
            <button
              type="button"
              onClick={() => exportMarkdown(run)}
              className="glass-control inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-mono text-[0.68rem] uppercase tracking-[0.12em] transition-colors hover:brightness-110 focus-visible:outline-none"
            >
              <Download className="size-3.5" />
              导出 Markdown
            </button>
          )}
        </div>
        <div className="mt-1 text-foreground">
          {title} · {run.trade_date}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5 text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
          <span>状态 {run.status}</span>
          <span>开始 {fmtTime(run.created_at)}</span>
          <span>结束 {fmtTime(run.completed_at)}</span>
        </div>
      </div>

      {run.status === "running" && (
        <div className="thinking-panel flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2">
          <div className="font-mono text-xs text-amber-300">
            仍在进行，以下为目前已生成的部分
          </div>
          {onCancel && (
            <button
              type="button"
              onClick={() => onCancel(run.run_id)}
              disabled={canceling}
              className="thinking-border inline-flex h-7 items-center gap-1.5 rounded-md px-2 font-mono text-[0.68rem] uppercase tracking-[0.12em] transition-colors hover:brightness-110 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-70"
            >
              {canceling ? (
                <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
              ) : (
                <OctagonX className="size-3.5" />
              )}
              停止分析
            </button>
          )}
        </div>
      )}

      {run.status === "running" && (
        <RuntimeStatusPanel
          runtime={runtime}
          runtimeError={runtimeError}
          currentAgentLabel={currentAgentLabel}
        />
      )}

      {run.status === "error" && (
        <div className="glass-readable rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
          该分析以错误结束
        </div>
      )}

      {run.status === "cancelled" && (
        <div className="glass-readable rounded-md border-amber-500/40 bg-amber-500/10 px-3 py-2 font-mono text-xs text-amber-300">
          该分析已停止，以下为停止前已生成的部分
        </div>
      )}

      {isEmpty && run.status === "running" && (
        <div className="glass-readable rounded-md border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
          尚未生成可持久化的阶段报告
        </div>
      )}

      {isEmpty && run.status !== "running" && run.status !== "error" && run.status !== "cancelled" && (
        <div className="glass-readable rounded-md border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
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
