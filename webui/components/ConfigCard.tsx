"use client";
import { LoaderCircle, Play } from "lucide-react";
import { useEffect, useState } from "react";
import type { AnalysisRequest, ConfigOptions } from "@/lib/types";

export function ConfigCard({
  options,
  onStart,
  running = false,
}: {
  options: ConfigOptions;
  onStart: (req: AnalysisRequest) => void;
  running?: boolean;
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
  const [deepLlm, setDeepLlm] = useState(options.configured_deep_llm ?? "");
  const [quickLlm, setQuickLlm] = useState(options.configured_quick_llm ?? "");

  // 挂载后从 localStorage 回填用户上次的选择（仅当仍是当前 provider 的有效选项）
  useEffect(() => {
    const validDeep = new Set(options.model_options.deep.map(([, id]) => id));
    const validQuick = new Set(options.model_options.quick.map(([, id]) => id));
    const savedDeep = localStorage.getItem("ta:deep_think_llm");
    const savedQuick = localStorage.getItem("ta:quick_think_llm");
    if (savedDeep && validDeep.has(savedDeep)) setDeepLlm(savedDeep);
    if (savedQuick && validQuick.has(savedQuick)) setQuickLlm(savedQuick);
  }, [options]);

  const toggle = (v: string) =>
    setAnalysts((a) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]));

  const activeAnalysts = analysts.filter(
    (a) => !(assetType === "crypto" && a === "fundamentals"),
  );

  return (
    <form
      className="glass rounded-lg text-card-foreground"
      onSubmit={(e) => {
        e.preventDefault();
        onStart({
          ticker,
          trade_date: date,
          asset_type: assetType,
          analysts: activeAnalysts,
          research_depth: depth,
          output_language: language,
          llm_provider: null,
          deep_think_llm: deepLlm || null,
          quick_think_llm: quickLlm || null,
        });
      }}
    >
      <div className="border-b border-border px-3 py-2">
        <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
          Run Console
        </div>
        <div className="mt-0.5 text-sm text-foreground">新分析配置</div>
      </div>

      <div className="space-y-4 p-3">
        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Instrument
          </legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_9.5rem] lg:grid-cols-1 xl:grid-cols-[minmax(0,1fr)_9.5rem]">
            <label className="space-y-1">
              <span className="sr-only">Ticker</span>
              <input
                className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm tracking-wide text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                placeholder="159241.SZ"
              />
            </label>
            <label className="space-y-1">
              <span className="sr-only">Trade date</span>
              <input
                type="date"
                className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
          </div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Scope
          </legend>
          <div className="glass-control grid grid-cols-2 rounded-md p-1">
            {(["stock", "crypto"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setAssetType(t)}
                aria-pressed={assetType === t}
                className={`h-8 rounded-sm px-2 font-mono text-xs uppercase tracking-[0.16em] transition-colors focus-visible:outline-none focus-visible:border-primary ${
                  assetType === t
                    ? "bg-[#6affb0] text-[#00363a]"
                    : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                }`}
              >
                {t === "stock" ? "股票" : "加密"}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Analysts
          </legend>
          <div className="grid grid-cols-2 gap-1.5">
            {options.analysts.map((a) => {
              const disabled = assetType === "crypto" && a.value === "fundamentals";
              const on = analysts.includes(a.value) && !disabled;
              return (
                <button
                  key={a.value}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggle(a.value)}
                  aria-pressed={on}
                  className={`min-h-8 rounded-md border px-2 py-1 text-left text-xs transition-colors focus-visible:outline-none focus-visible:border-primary ${
                    on
                      ? "glass-control border-primary/50 text-primary"
                      : "glass-control text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                  } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
                >
                  {a.label}
                </button>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Research
          </legend>
          <div className="grid grid-cols-3 gap-1.5">
            {options.research_depth.map((d) => (
              <button
                key={d.value}
                type="button"
                onClick={() => setDepth(d.value as 1 | 3 | 5)}
                aria-pressed={depth === d.value}
                className={`h-8 rounded-md border px-2 text-xs transition-colors focus-visible:outline-none focus-visible:border-primary ${
                  depth === d.value
                    ? "glass-control border-primary/50 text-primary"
                    : "glass-control text-muted-foreground hover:bg-muted/70 hover:text-foreground"
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
          <label className="block">
            <span className="sr-only">Output language</span>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              {options.languages.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Models
          </legend>
          <label className="block space-y-1">
            <span className="text-[0.7rem] text-muted-foreground">深度思考模型</span>
            <select
              value={deepLlm}
              onChange={(e) => {
                setDeepLlm(e.target.value);
                localStorage.setItem("ta:deep_think_llm", e.target.value);
              }}
              className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              {options.model_options.deep.map(([label, id]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-[0.7rem] text-muted-foreground">快速思考模型</span>
            <select
              value={quickLlm}
              onChange={(e) => {
                setQuickLlm(e.target.value);
                localStorage.setItem("ta:quick_think_llm", e.target.value);
              }}
              className="glass-control h-9 w-full rounded-md px-2.5 font-mono text-sm text-foreground outline-none transition-colors focus:border-primary"
            >
              {options.model_options.quick.map(([label, id]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </fieldset>

        <button
          type="submit"
          disabled={running || activeAnalysts.length === 0}
          className={`inline-flex h-10 w-full items-center justify-center gap-2 rounded-md px-3 font-mono text-xs font-bold uppercase tracking-[0.18em] transition-colors focus-visible:outline-none focus-visible:border-primary disabled:cursor-not-allowed ${
            running
              ? "thinking-border"
              : "border border-transparent bg-[#6affb0] text-[#00363a] hover:bg-[#52e89a] active:scale-[0.98] disabled:bg-muted disabled:text-muted-foreground"
          }`}
        >
          {running ? (
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Play className="size-4" />
          )}
          {running ? "分析进行中" : "开始分析"}
        </button>
      </div>
    </form>
  );
}
