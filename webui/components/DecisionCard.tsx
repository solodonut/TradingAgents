"use client";
import ReactMarkdown from "react-markdown";
import type { Decision } from "@/lib/types";

const COLORS: Record<string, string> = {
  Buy: "text-emerald-400",
  Overweight: "text-emerald-300",
  Hold: "text-zinc-300",
  Underweight: "text-red-300",
  Sell: "text-red-400",
};

const BORDERS: Record<string, string> = {
  Buy: "border-emerald-700",
  Overweight: "border-emerald-800",
  Hold: "border-zinc-700",
  Underweight: "border-red-800",
  Sell: "border-red-700",
};

export function DecisionCard({ decision, detail }: { decision: Decision; detail: string }) {
  return (
    <div
      className={`rounded-lg border-2 bg-zinc-900 p-4 ${BORDERS[decision] ?? "border-zinc-700"}`}
    >
      <div className="text-[0.65rem] text-zinc-500 font-mono uppercase tracking-widest mb-1">
        最终决策
      </div>
      <div className={`text-4xl font-bold font-mono tracking-tight ${COLORS[decision] ?? ""}`}>
        {decision}
      </div>
      <div className="prose prose-invert prose-sm max-w-none mt-3">
        <ReactMarkdown>{detail}</ReactMarkdown>
      </div>
    </div>
  );
}
