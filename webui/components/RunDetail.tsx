"use client";
import { Activity, AlertTriangle, Clock3, LoaderCircle, OctagonX, Radio } from "lucide-react";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
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
];

const SECTION_LABELS = Object.fromEntries(SECTIONS.map((s) => [s.field, s.label]));

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function RunDetail({
  run,
  runtime,
  runtimeError,
  onCancel,
  canceling = false,
}: {
  run: RunResult;
  runtime?: RunStatusDetail | null;
  runtimeError?: string | null;
  onCancel?: (runId: string) => void;
  canceling?: boolean;
}) {
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
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
          <div className="font-mono text-xs text-amber-300">
            仍在进行，以下为目前已生成的部分
          </div>
          {onCancel && (
            <button
              type="button"
              onClick={() => onCancel(run.run_id)}
              disabled={canceling}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-amber-500/50 px-2 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-amber-100 transition-colors hover:bg-amber-500/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/40 disabled:cursor-not-allowed disabled:opacity-60"
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
        <div className="rounded-lg border border-border bg-card px-3 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              <Radio className="size-3.5" aria-hidden="true" />
              Runtime Status
            </div>
            <div className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
              {runtime?.updated_at ? `更新 ${fmtTime(runtime.updated_at)}` : "等待遥测"}
            </div>
          </div>

          {runtimeError && (
            <div className="mt-3 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
              {runtimeError}
            </div>
          )}

          {!runtime && !runtimeError && (
            <div className="mt-3 rounded-md border border-dashed border-border px-3 py-3 font-mono text-xs text-muted-foreground">
              暂无后台遥测，可能是旧分析、服务重启前启动，或正在初始化。
            </div>
          )}

          {runtime && (
            <div className="mt-3 space-y-3">
              <div className="grid gap-2 text-sm sm:grid-cols-2">
                <div className="rounded-md border border-border px-3 py-2">
                  <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                    <Activity className="size-3.5" aria-hidden="true" />
                    Process
                  </div>
                  <div className="mt-1 text-foreground">
                    {runtime.process_alive ? "后台线程/队列仍存在" : "未发现活动后台进程"}
                  </div>
                </div>
                <div className="rounded-md border border-border px-3 py-2">
                  <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                    <Clock3 className="size-3.5" aria-hidden="true" />
                    LLM
                  </div>
                  <div className="mt-1 text-foreground">
                    {runtime.llm_active
                      ? `正在等待 LLM 返回 (${runtime.active_llm_calls})`
                      : "当前没有活动 LLM 调用"}
                  </div>
                </div>
              </div>

              <dl className="grid gap-x-4 gap-y-2 font-mono text-xs sm:grid-cols-2">
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">模型</dt>
                  <dd className="max-w-[14rem] truncate text-foreground">
                    {runtime.last_llm_model ?? "未知"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">最后发出</dt>
                  <dd className="text-foreground">{fmtTime(runtime.last_llm_start_at)}</dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">最后返回</dt>
                  <dd className="text-foreground">{fmtTime(runtime.last_llm_end_at)}</dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">最近阶段</dt>
                  <dd className="text-foreground">
                    {runtime.last_report_section
                      ? (SECTION_LABELS[runtime.last_report_section] ?? runtime.last_report_section)
                      : "—"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">阶段写入</dt>
                  <dd className="text-foreground">{fmtTime(runtime.last_report_at)}</dd>
                </div>
                <div className="flex justify-between gap-3 border-b border-border/60 pb-1">
                  <dt className="text-muted-foreground">Prompt 字符</dt>
                  <dd className="text-foreground">
                    {runtime.last_prompt_chars === null ? "—" : runtime.last_prompt_chars}
                  </dd>
                </div>
              </dl>

              {runtime.last_llm_error && (
                <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2">
                  <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.14em] text-destructive">
                    <AlertTriangle className="size-3.5" aria-hidden="true" />
                    Last LLM Error · {fmtTime(runtime.last_llm_error_at)}
                  </div>
                  <p className="mt-1 font-mono text-xs text-destructive">
                    {runtime.last_llm_error}
                  </p>
                </div>
              )}

              {runtime.last_prompt_preview && (
                <details className="rounded-md border border-border px-3 py-2">
                  <summary className="cursor-pointer font-mono text-[0.65rem] uppercase tracking-[0.14em] text-muted-foreground">
                    最近一次发给 LLM 的 Prompt 摘要
                  </summary>
                  <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-muted-foreground">
                    {runtime.last_prompt_preview}
                  </pre>
                </details>
              )}
            </div>
          )}
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
