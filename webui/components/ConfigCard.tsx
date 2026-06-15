"use client";
import { useState } from "react";
import type { AnalysisRequest, ConfigOptions } from "@/lib/types";

export function ConfigCard({
  options,
  onStart,
}: {
  options: ConfigOptions;
  onStart: (req: AnalysisRequest) => void;
}) {
  const [ticker, setTicker] = useState("NVDA");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [assetType, setAssetType] = useState<"stock" | "crypto">("stock");
  const [analysts, setAnalysts] = useState<string[]>([
    "market",
    "social",
    "news",
    "fundamentals",
  ]);
  const [depth, setDepth] = useState<1 | 3 | 5>(3);
  const [language, setLanguage] = useState("Chinese");

  const toggle = (v: string) =>
    setAnalysts((a) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]));

  return (
    <div className="rounded-lg border border-zinc-700/80 bg-zinc-900 p-4 space-y-3">
      <div className="flex flex-wrap gap-2">
        <input
          className="flex-1 min-w-[180px] bg-zinc-800 px-2.5 py-1.5 rounded font-mono text-sm tracking-wide text-zinc-100 placeholder:text-zinc-500 border border-zinc-700 focus:border-emerald-500 focus:outline-none"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="NVDA / 0700.HK / BTC-USD"
        />
        <input
          type="date"
          className="bg-zinc-800 px-2.5 py-1.5 rounded font-mono text-sm text-zinc-100 border border-zinc-700 focus:border-emerald-500 focus:outline-none"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>

      {/* Asset type toggle */}
      <div className="flex gap-1.5">
        {(["stock", "crypto"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setAssetType(t)}
            className={`px-3 py-1 rounded text-xs font-mono uppercase tracking-wider transition-colors ${
              assetType === t
                ? "bg-emerald-600 text-black"
                : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {t === "stock" ? "股票" : "加密"}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {options.analysts.map((a) => {
          const disabled = assetType === "crypto" && a.value === "fundamentals";
          const on = analysts.includes(a.value) && !disabled;
          return (
            <button
              key={a.value}
              disabled={disabled}
              onClick={() => toggle(a.value)}
              className={`px-3 py-1 rounded-full text-sm transition-colors ${
                on ? "bg-emerald-600 text-black" : "bg-zinc-800 text-zinc-300"
              } ${disabled ? "opacity-40 cursor-not-allowed" : "hover:bg-zinc-700"}`}
            >
              {a.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {options.research_depth.map((d) => (
          <button
            key={d.value}
            onClick={() => setDepth(d.value as 1 | 3 | 5)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              depth === d.value
                ? "bg-emerald-600 text-black"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            }`}
          >
            {d.label}
          </button>
        ))}
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="ml-auto bg-zinc-800 px-2.5 py-1.5 rounded font-mono text-sm text-zinc-100 border border-zinc-700 focus:border-emerald-500 focus:outline-none"
        >
          {options.languages.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
      </div>

      <button
        className="w-full bg-emerald-500 text-black font-bold py-2 rounded hover:bg-emerald-400 transition-colors"
        onClick={() =>
          onStart({
            ticker,
            trade_date: date,
            asset_type: assetType,
            analysts: analysts.filter(
              (a) => !(assetType === "crypto" && a === "fundamentals"),
            ),
            research_depth: depth,
            output_language: language,
            llm_provider: null,
            deep_think_llm: null,
            quick_think_llm: null,
          })
        }
      >
        🚀 开始分析
      </button>
    </div>
  );
}
