"use client";
import { Cpu, GripVertical, LoaderCircle, Play, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getWatchlist, lookupTicker, saveWatchlist } from "@/lib/api";
import type { AnalysisRequest, ConfigOptions } from "@/lib/types";

type TickerItem = { ticker: string; name: string };

export function ConfigCard({
  options,
  onStart,
  running = false,
}: {
  options: ConfigOptions;
  onStart: (
    req: { tickers: string[]; ticker_names?: Record<string, string> } & Omit<
      AnalysisRequest,
      "ticker"
    >,
  ) => void;
  running?: boolean;
}) {
  const [tickers, setTickers] = useState<TickerItem[]>([{ ticker: "NVDA", name: "" }]);
  const [tickersLoaded, setTickersLoaded] = useState(false);
  const [tickerInput, setTickerInput] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [date, setDate] = useState(() => {
    // 用本地日期,不能用 toISOString()(它按 UTC 取值,UTC+8 凌晨会回退到昨天)
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  });
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
  const [modelsOpen, setModelsOpen] = useState(false);
  const modelsRef = useRef<HTMLDivElement>(null);

  // 挂载后从 localStorage 回填用户上次的选择（仅当仍是当前 provider 的有效选项）
  useEffect(() => {
    const validDeep = new Set(options.model_options.deep.map(([, id]) => id));
    const validQuick = new Set(options.model_options.quick.map(([, id]) => id));
    const savedDeep = localStorage.getItem("ta:deep_think_llm");
    const savedQuick = localStorage.getItem("ta:quick_think_llm");
    if (savedDeep && validDeep.has(savedDeep)) setDeepLlm(savedDeep);
    if (savedQuick && validQuick.has(savedQuick)) setQuickLlm(savedQuick);
  }, [options]);

  // 弹出卡片：点击外部或按 Esc 关闭
  useEffect(() => {
    if (!modelsOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!modelsRef.current?.contains(e.target as Node)) setModelsOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setModelsOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [modelsOpen]);

  // 挂载后从后端 DB 回填代码清单（跨浏览器/设备/清缓存都不丢，读完才标记 loaded）。
  // DB 不可达或为空时回退到 localStorage 旧清单，并由下面的写回 effect 迁移进 DB。
  useEffect(() => {
    let cancelled = false;
    const readLocal = (): TickerItem[] | null => {
      const saved = localStorage.getItem("ta:ticker_list");
      if (!saved) return null;
      try {
        const parsed = JSON.parse(saved);
        return Array.isArray(parsed) ? parsed : null;
      } catch {
        return null; // 损坏的数据：忽略
      }
    };
    (async () => {
      let list: TickerItem[] | null = null;
      try {
        const remote = await getWatchlist();
        if (remote.length > 0) list = remote;
      } catch {
        // DB 不可达：回退本地镜像
      }
      if (!list) list = readLocal();
      if (cancelled) return;
      if (list && list.length > 0) setTickers(list);
      setTickersLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 清单每次变化都持久化到后端 DB（防抖 500ms），localStorage 作为离线兜底镜像。
  // 必须等读 effect 完成（tickersLoaded）才写，否则挂载时会用默认值覆盖掉已存清单
  // （React 19 严格模式下 effect 双调用尤其明显）。
  // 不要改成惰性 useState 初始化：本组件会在服务端 SSR，读 localStorage 会崩溃 / hydration 不一致。
  useEffect(() => {
    if (!tickersLoaded) return;
    localStorage.setItem("ta:ticker_list", JSON.stringify(tickers));
    const handle = setTimeout(() => {
      saveWatchlist(tickers).catch(() => {
        // 网络/后端异常：本地镜像已写，下次变更再试
      });
    }, 500);
    return () => clearTimeout(handle);
  }, [tickers, tickersLoaded]);

  // 加载后给名称为空的项补查一次：A 股/ETF 名称走 AKShare，首次因冷缓存可能超时返回空，
  // 缓存预热后再次打开页面即自愈。只在 loaded 翻转时跑一次，避免每次清单变化都重查。
  useEffect(() => {
    if (!tickersLoaded) return;
    const blanks = tickers.filter((t) => !t.name).map((t) => t.ticker);
    if (blanks.length === 0) return;
    let cancelled = false;
    (async () => {
      for (const code of blanks) {
        const res = await lookupTicker(code);
        if (cancelled) return;
        if (res.name) {
          setTickers((prev) =>
            prev.map((t) => (t.ticker === code ? { ...t, name: res.name as string } : t)),
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // 仅依赖 tickersLoaded：补查只在加载完成那一刻触发一次。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickersLoaded]);

  const toggle = (v: string) =>
    setAnalysts((a) => (a.includes(v) ? a.filter((x) => x !== v) : [...a, v]));

  const addTicker = async () => {
    const code = tickerInput.trim().toUpperCase();
    if (!code) return;
    if (tickers.some((t) => t.ticker === code)) {
      setTickerInput("");
      return; // 去重：已存在则忽略
    }
    setTickers((prev) => [...prev, { ticker: code, name: "" }]);
    setTickerInput("");
    const res = await lookupTicker(code);
    if (res.name) {
      setTickers((prev) =>
        prev.map((t) => (t.ticker === code ? { ...t, name: res.name as string } : t)),
      );
    }
  };

  const removeTicker = (code: string) =>
    setTickers((prev) => prev.filter((t) => t.ticker !== code));

  // 拖拽排序：把 from 位置的项移动到 to 位置（HTML5 原生拖放，dragenter 时实时重排）。
  const reorderTicker = (from: number, to: number) =>
    setTickers((prev) => {
      if (from === to || to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });

  const activeAnalysts = analysts.filter(
    (a) => !(assetType === "crypto" && a === "fundamentals"),
  );

  return (
    <form
      className="glass rounded-lg text-card-foreground"
      onSubmit={(e) => {
        e.preventDefault();
        onStart({
          tickers: tickers.map((t) => t.ticker),
          ticker_names: Object.fromEntries(
            tickers.filter((t) => t.name).map((t) => [t.ticker, t.name]),
          ),
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
      <div ref={modelsRef} className="relative border-b border-border px-3 py-2">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              Run Console
            </div>
            <div className="mt-0.5 text-sm text-foreground">新分析配置</div>
          </div>
          <button
            type="button"
            onClick={() => setModelsOpen((v) => !v)}
            aria-expanded={modelsOpen}
            aria-haspopup="dialog"
            title="选择模型"
            className={`glass-control inline-flex size-8 shrink-0 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:border-primary ${
              modelsOpen
                ? "border-primary/50 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <span className="sr-only">选择模型</span>
            <Cpu className="size-4" aria-hidden="true" />
          </button>
        </div>

        {modelsOpen && (
          <div
            role="dialog"
            aria-label="模型选择"
            className="absolute left-2 right-2 top-[calc(100%-0.25rem)] z-50 space-y-3 rounded-lg border border-white/10 bg-popover/98 p-3 shadow-2xl backdrop-blur-2xl backdrop-saturate-150 animate-in fade-in-0 zoom-in-95 duration-150"
          >
            <div className="flex items-center justify-between">
              <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                Models
              </div>
              <button
                type="button"
                onClick={() => setModelsOpen(false)}
                aria-label="关闭"
                className="inline-flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:border-primary"
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </div>
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
          </div>
        )}
      </div>

      <div className="space-y-4 p-3">
        <fieldset className="space-y-2">
          <legend className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Instrument
          </legend>
          <div className="space-y-2">
            <label className="space-y-1">
              <span className="sr-only">Ticker</span>
              <div className="flex gap-1.5">
                <input
                  type="text"
                  className="glass-control w-full rounded-md px-2.5 py-1.5 font-mono text-sm tracking-wide text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary"
                  value={tickerInput}
                  onChange={(e) => setTickerInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void addTicker();
                    }
                  }}
                  placeholder="输入代码，如 NVDA / 159241.SZ"
                />
                <button
                  type="button"
                  onClick={() => void addTicker()}
                  title="添加到清单"
                  className="glass-control inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:border-primary"
                >
                  <span className="sr-only">添加</span>
                  <Plus className="size-4" aria-hidden="true" />
                </button>
              </div>
            </label>

            {tickers.length === 0 ? (
              <p className="px-0.5 py-2 text-xs text-muted-foreground">清单为空，添加代码后开始分析。</p>
            ) : (
              <ul className="space-y-1">
                {tickers.map((t, i) => (
                  <li
                    key={t.ticker}
                    draggable
                    onDragStart={() => setDragIndex(i)}
                    onDragEnter={() => {
                      if (dragIndex !== null && dragIndex !== i) {
                        reorderTicker(dragIndex, i);
                        setDragIndex(i);
                      }
                    }}
                    onDragOver={(e) => e.preventDefault()}
                    onDragEnd={() => setDragIndex(null)}
                    className={`glass-control flex items-center gap-2 rounded-md px-2 py-1.5 transition-opacity ${
                      dragIndex === i ? "opacity-50" : ""
                    }`}
                  >
                    <span
                      aria-hidden="true"
                      className="flex shrink-0 cursor-grab items-center text-muted-foreground/60 transition-colors hover:text-foreground active:cursor-grabbing"
                    >
                      <GripVertical className="size-3.5" />
                    </span>
                    <span className="flex min-w-0 flex-1 items-baseline gap-2">
                      <span className="shrink-0 font-mono text-sm text-foreground">{t.ticker}</span>
                      {t.name ? (
                        <span
                          title={t.name}
                          className="group/name min-w-0 flex-1 overflow-hidden [container-type:inline-size]"
                        >
                          <span className="inline-block whitespace-nowrap text-xs text-muted-foreground transition-transform duration-[2000ms] ease-linear group-hover/name:translate-x-[min(0px,calc(100cqw_-_100%))]">
                            {t.name}
                          </span>
                        </span>
                      ) : null}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeTicker(t.ticker)}
                      aria-label="移除"
                      className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:text-destructive focus-visible:outline-none focus-visible:border-primary"
                    >
                      <X className="size-3.5" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

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

        <button
          type="submit"
          disabled={running || activeAnalysts.length === 0 || tickers.length === 0}
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
          {running
            ? "分析进行中"
            : tickers.length > 1
              ? `分析 ${tickers.length} 个标的`
              : "开始分析"}
        </button>
      </div>
    </form>
  );
}
