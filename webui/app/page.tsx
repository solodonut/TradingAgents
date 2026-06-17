"use client";
import { ArrowLeft, Activity, LoaderCircle, OctagonX, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ConfigCard } from "@/components/ConfigCard";
import { AgentProgress } from "@/components/AgentProgress";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import { HistorySidebar } from "@/components/HistorySidebar";
import { RunDetail } from "@/components/RunDetail";
import {
  deleteHistory,
  getConfigOptions,
  getHistory,
  getHistoryDetail,
  cancelAnalysis,
  startAnalysis,
} from "@/lib/api";
import { subscribe } from "@/lib/sse";
import type {
  ConfigOptions,
  Decision,
  HistorySummary,
  RunResult,
  SSEEvent,
} from "@/lib/types";

export default function Home() {
  const [options, setOptions] = useState<ConfigOptions | null>(null);
  const [history, setHistory] = useState<HistorySummary[]>([]);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<{ agent: string; content: string }[]>([]);
  const [decision, setDecision] = useState<{ d: Decision; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [canceling, setCanceling] = useState(false);
  const unsubscribeRef = useRef<(() => void) | null>(null);

  // Detail (history replay) mode
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const refreshHistory = () => getHistory().then(setHistory).catch(() => setHistory([]));

  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
    return () => unsubscribeRef.current?.();
  }, []);

  const exitDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
  };

  const onOpenDetail = async (runId: string) => {
    setSelectedId(runId);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const r = await getHistoryDetail(runId);
      setDetail(r);
    } catch (err) {
      setDetailError((err as Error).message);
    } finally {
      setDetailLoading(false);
    }
  };

  const onDeleteHistory = (id: string) => {
    if (id === selectedId) exitDetail();
    deleteHistory(id).then(refreshHistory);
  };

  const onStart = async (req: Parameters<typeof startAnalysis>[0]) => {
    exitDetail();
    setStatuses({});
    setMessages([]);
    setDecision(null);
    setError(null);
    setRunning(true);
    setCanceling(false);
    try {
      const runId = await startAnalysis(req);
      setCurrentRunId(runId);
      unsubscribeRef.current = subscribe(
        runId,
        (e: SSEEvent) => {
          if (e.event === "agent_status")
            setStatuses((s) => ({ ...s, [e.data.agent]: e.data.status }));
          else if (e.event === "message")
            setMessages((m) => [...m, { agent: e.data.agent, content: e.data.content }]);
          else if (e.event === "done")
            setDecision({ d: e.data.decision, detail: e.data.final_trade_decision });
          else if (e.event === "error") setError(e.data.message);
          else if (e.event === "cancelled") setError("分析已停止");
        },
        () => {
          setRunning(false);
          setCanceling(false);
          setCurrentRunId(null);
          unsubscribeRef.current = null;
          refreshHistory();
        },
      );
    } catch (err) {
      setRunning(false);
      setCanceling(false);
      setCurrentRunId(null);
      const msg = (err as Error).message;
      setError(
        msg === "已有分析正在运行"
          ? "已有分析正在运行，请等待当前分析完成后再试。"
          : msg,
      );
    }
  };

  const cancelRun = async (runId: string) => {
    if (canceling) return;
    setCanceling(true);
    try {
      await cancelAnalysis(runId);
      setError("分析已停止");
      setRunning(false);
      if (currentRunId === runId) setCurrentRunId(null);
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      refreshHistory();
      if (selectedId === runId) {
        const next = await getHistoryDetail(runId);
        setDetail(next);
      }
      setCanceling(false);
    } catch (err) {
      setCanceling(false);
      setError((err as Error).message);
    }
  };

  const onCancel = () => {
    if (!currentRunId) return;
    void cancelRun(currentRunId);
  };

  const inDetailMode = selectedId !== null;
  const showEmptyState =
    !inDetailMode &&
    !running &&
    messages.length === 0 &&
    !decision;
  const latestMessage = messages.at(-1);
  const completedAgents = Object.values(statuses).filter((s) => s === "done").length;
  const workingAgents = Object.values(statuses).filter((s) => s === "working").length;

  return (
    <div className="min-h-screen bg-background text-foreground lg:h-screen lg:overflow-hidden">
      <div className="grid min-h-screen grid-cols-1 lg:h-screen lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
        <div className="order-3 min-h-[18rem] lg:order-1 lg:min-h-0">
          <HistorySidebar
            items={history}
            selectedId={selectedId}
            onOpen={onOpenDetail}
            onDelete={onDeleteHistory}
          />
        </div>

        <main className="order-2 min-h-0 border-border lg:order-2 lg:h-screen lg:overflow-y-auto lg:border-r">
          <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-3 py-3 sm:px-4 lg:px-5">
            <header className="mb-3 rounded-lg border border-border bg-card px-3 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                    <Terminal className="size-3.5" aria-hidden="true" />
                    TradingAgents WebUI
                  </div>
                  <h1 className="mt-1 text-lg font-semibold tracking-tight text-foreground">
                    研究工作台
                  </h1>
                </div>
                <div className="flex flex-wrap gap-2 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                  <span className="rounded border border-border px-2 py-1">
                    Done {completedAgents}
                  </span>
                  <span className="rounded border border-border px-2 py-1">
                    Active {workingAgents}
                  </span>
                </div>
              </div>
            </header>

            {inDetailMode ? (
              <section className="space-y-3">
                <button
                  type="button"
                  onClick={exitDetail}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  <ArrowLeft className="size-3.5" />
                  新分析
                </button>
                {detailLoading && (
                  <div className="space-y-3" aria-busy="true" aria-label="加载中">
                    <div className="h-16 rounded-lg border border-border bg-card" />
                    <div className="h-36 rounded-lg border border-border bg-card" />
                    <div className="h-36 rounded-lg border border-border bg-card" />
                  </div>
                )}
                {detailError && (
                  <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
                    {detailError}
                  </div>
                )}
                {detail && (
                  <RunDetail
                    run={detail}
                    onCancel={detail.status === "running" ? cancelRun : undefined}
                    canceling={canceling}
                  />
                )}
              </section>
            ) : (
              <section className="space-y-3">
                {error && (
                  <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
                    {error}
                  </div>
                )}
                {showEmptyState && (
                  <div className="rounded-lg border border-dashed border-border bg-card px-4 py-5">
                    <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                      Waiting For Run
                    </div>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground">
                      输入代码与日期，配置分析师与研究深度后开始。报告会按 agent
                      流式进入这里，最终由组合经理给出五档评级。
                    </p>
                    <p className="mt-2 font-mono text-xs text-muted-foreground">
                      这是研究脚手架，不是投资建议。
                    </p>
                  </div>
                )}
                {running && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
                    <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-amber-300">
                      <Activity className="size-3.5" aria-hidden="true" />
                      分析进行中
                    </div>
                    <button
                      type="button"
                      onClick={onCancel}
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
                  </div>
                )}
                {messages.map((m, i) => (
                  <MessageBubble key={i} agent={m.agent} content={m.content} />
                ))}
                {decision && <DecisionCard decision={decision.d} detail={decision.detail} />}
              </section>
            )}
          </div>
        </main>

        <aside className="order-1 border-b border-border bg-background p-3 lg:order-3 lg:h-screen lg:overflow-y-auto lg:border-b-0">
          <div className="space-y-3">
            <div className="rounded-lg border border-border bg-card px-3 py-3">
              <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                Active Context
              </div>
              <div className="mt-2 space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Mode</span>
                  <span className="font-mono text-foreground">
                    {inDetailMode ? "HISTORY" : running ? "LIVE" : "READY"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Latest</span>
                  <span className="max-w-[12rem] truncate font-mono text-foreground">
                    {latestMessage?.agent ?? (selectedId ? "DETAIL" : "NONE")}
                  </span>
                </div>
              </div>
            </div>

            {options && <ConfigCard options={options} onStart={onStart} running={running} />}

            {error && (
              <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
                {error}
              </div>
            )}

            <AgentProgress statuses={statuses} />

            {decision && (
              <DecisionCard decision={decision.d} detail={decision.detail} compact />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
