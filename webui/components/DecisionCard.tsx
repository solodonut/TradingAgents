"use client";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { Decision } from "@/lib/types";

const COLORS: Record<string, string> = {
  Buy: "text-emerald-300",
  Overweight: "text-emerald-200",
  Hold: "text-foreground",
  Underweight: "text-red-300",
  Sell: "text-red-300",
};

const BORDERS: Record<string, string> = {
  Buy: "border-emerald-500/60",
  Overweight: "border-emerald-500/50",
  Hold: "border-border",
  Underweight: "border-red-500/50",
  Sell: "border-red-500/60",
};

const SUMMARY: Record<string, string> = {
  Buy: "看多信号占优，仍需核对报告内风险条件。",
  Overweight: "偏多但保留风险约束，适合低于满仓的主动配置。",
  Hold: "方向证据不足，优先等待确认信号。",
  Underweight: "防守优先，配置低于基准权重。",
  Sell: "看空信号占优，报告建议退出或规避。",
};

export function DecisionCard({
  decision,
  detail,
  compact = false,
}: {
  decision: Decision;
  detail: string;
  compact?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border bg-card ${compact ? "p-3" : "p-4"} ${BORDERS[decision] ?? "border-border"}`}
    >
      <div className="mb-1 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
        最终决策
      </div>
      <div
        className={`font-mono font-bold tracking-tight ${compact ? "text-2xl" : "text-4xl"} ${COLORS[decision] ?? ""}`}
      >
        {decision}
      </div>
      {compact ? (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {SUMMARY[decision] ?? "最终评级已生成，查看主报告获取完整推理。"}
        </p>
      ) : (
        <div className="ta-prose prose prose-invert prose-sm mt-3 max-w-none prose-pre:border prose-pre:border-border prose-pre:bg-background">
          <MarkdownContent content={detail} />
        </div>
      )}
    </div>
  );
}
