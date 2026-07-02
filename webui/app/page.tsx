"use client";
import { ArrowLeft, Activity, LoaderCircle, MessageCircle, OctagonX, Terminal } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConfigCard } from "@/components/ConfigCard";
import { AgentProgress } from "@/components/AgentProgress";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import { HistorySidebar } from "@/components/HistorySidebar";
import { RunDetail } from "@/components/RunDetail";
import { RuntimeStatusPanel } from "@/components/RuntimeStatusPanel";
import { QueuePanel } from "@/components/QueuePanel";
import { ServiceHealthPanel } from "@/components/ServiceHealthPanel";
import {
  deleteHistory,
  getConfigOptions,
  getHistory,
  getHistoryDetail,
  getAnalysisStatus,
  cancelAnalysis,
  enqueueAnalysis,
  getQueue,
  removeQueueItem,
  clearQueue,
  reorderQueue,
  checkServiceHealth,
  historyReportsZipUrl,
  subscribeServiceHealth,
} from "@/lib/api";
import { subscribe } from "@/lib/sse";
import { sortServiceHealthItems } from "@/lib/service-health";
import type {
  ConfigOptions,
  Decision,
  HistorySummary,
  QueueState,
  RunResult,
  RunStatusDetail,
  ServiceHealthItem,
  ServiceHealthSummary,
  SSEEvent,
} from "@/lib/types";

const AGENT_SECTION_MAP: { agent: string; section: string }[] = [
  { agent: "market_analyst", section: "market_report" },
  { agent: "social_analyst", section: "sentiment_report" },
  { agent: "news_analyst", section: "news_report" },
  { agent: "fundamentals_analyst", section: "fundamentals_report" },
  { agent: "research_manager", section: "investment_plan" },
  { agent: "trader", section: "trader_investment_plan" },
  { agent: "portfolio_manager", section: "final_trade_decision" },
  { agent: "report_validator", section: "validation_report" },
];

const SECTION_TO_AGENT = Object.fromEntries(
  AGENT_SECTION_MAP.map(({ agent, section }) => [section, agent]),
);

const SECTION_LABELS: Record<string, string> = {
  market_report: "市场",
  sentiment_report: "情绪",
  news_report: "新闻",
  fundamentals_report: "基本面",
  investment_plan: "研究经理",
  trader_investment_plan: "交易员",
  final_trade_decision: "组合经理",
  validation_report: "报告校验",
};

function summarizeHealthItems(items: ServiceHealthItem[]): ServiceHealthSummary {
  return {
    total: items.length,
    checking: items.filter((item) => item.status === "checking").length,
    ok: items.filter((item) => item.status === "ok").length,
    error: items.filter((item) => item.status === "error").length,
    disabled: items.filter((item) => item.status === "disabled").length,
  };
}

// Agent Matrix row order, including the bull/bear debate and 3-way risk debate
// phases. Neither debate has a report section of its own (the bull/bear debate
// only produces investment_plan via the research manager; the risk debate only
// produces final_trade_decision via the portfolio manager), so each lives just
// before the manager that consumes it and is derived from runtime signals
// rather than a section field.
const MATRIX_ORDER = [
  "market_analyst",
  "social_analyst",
  "news_analyst",
  "fundamentals_analyst",
  "debate",
  "research_manager",
  "trader",
  "risk_debate",
  "portfolio_manager",
  "report_validator",
];

function workingAgentLabel(statuses: Record<string, string>): string | null {
  const id = Object.entries(statuses).find(([, v]) => v === "working")?.[0];
  if (!id) return null;
  if (id === "debate") return "多空辩论";
  if (id === "risk_debate") return "风险辩论";
  const section = AGENT_SECTION_MAP.find((m) => m.agent === id)?.section;
  return (section && SECTION_LABELS[section]) || id;
}

function hasSection(result: RunResult["result"], section: string): boolean {
  const value = result?.[section];
  return typeof value === "string" && value.trim().length > 0;
}

function nextLiveStatuses(
  prev: Record<string, string>,
  doneAgent: string,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const [agent, status] of Object.entries(prev)) {
    if (status === "done") next[agent] = "done";
  }
  next[doneAgent] = "done";
  if (doneAgent === "research_manager") next["debate"] = "done";
  if (doneAgent === "portfolio_manager") next["risk_debate"] = "done";

  const working = MATRIX_ORDER.find((agent) => next[agent] !== "done");
  if (working) next[working] = "working";
  return next;
}

function deriveHistoryProgress(
  run: RunResult | null,
  runtime: RunStatusDetail | null,
): Record<string, string> {
  if (!run) return {};

  const next: Record<string, string> = {};
  for (const { agent, section } of AGENT_SECTION_MAP) {
    if (hasSection(run.result, section)) next[agent] = "done";
  }
  // The debate feeds the research manager; once investment_plan exists it's over.
  if (hasSection(run.result, "investment_plan")) next["debate"] = "done";
  // The risk debate feeds the portfolio manager; once final_trade_decision
  // exists it's over.
  if (hasSection(run.result, "final_trade_decision")) next["risk_debate"] = "done";

  if (run.status === "running") {
    const lastAgent = runtime?.last_report_section
      ? SECTION_TO_AGENT[runtime.last_report_section]
      : null;
    if (lastAgent && next[lastAgent] !== "done") next[lastAgent] = "working";

    if (!Object.values(next).includes("working")) {
      const working = MATRIX_ORDER.find((agent) => next[agent] !== "done");
      // Two windows have no report section of their own, so a debate phase
      // (quick model) and the manager that consumes it (deep model) share one
      // window. Tell them apart by the live model: deep ⇒ manager judging,
      // otherwise still debating. If deep == quick we can't distinguish, so it
      // stays on the debate row until the manager's section lands.
      const deep =
        typeof run.config?.deep_think_llm === "string" ? run.config.deep_think_llm : null;
      const model = runtime?.last_llm_model ?? null;
      const managerJudging = deep != null && model === deep;
      if (working === "debate" || working === "research_manager") {
        // analysts done, no investment_plan yet: bull/bear debate vs research manager
        if (managerJudging) {
          next["debate"] = "done";
          next["research_manager"] = "working";
        } else {
          next["debate"] = "working";
        }
      } else if (working === "risk_debate" || working === "portfolio_manager") {
        // trader done, no final_trade_decision yet: 3-way risk debate vs portfolio manager
        if (managerJudging) {
          next["risk_debate"] = "done";
          next["portfolio_manager"] = "working";
        } else {
          next["risk_debate"] = "working";
        }
      } else if (working) {
        next[working] = "working";
      }
    }
  }

  return next;
}

export default function Home() {
  const [options, setOptions] = useState<ConfigOptions | null>(null);
  const [history, setHistory] = useState<HistorySummary[]>([]);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<{ agent: string; content: string }[]>([]);
  const [debateDetails, setDebateDetails] = useState<Record<string, string>>({});
  const [decision, setDecision] = useState<{ d: Decision; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [liveRuntimeStatus, setLiveRuntimeStatus] = useState<RunStatusDetail | null>(null);
  const [liveRuntimeError, setLiveRuntimeError] = useState<string | null>(null);
  const [canceling, setCanceling] = useState(false);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const healthUnsubscribeRef = useRef<(() => void) | null>(null);
  const followGenRef = useRef(0);

  const [queue, setQueue] = useState<QueueState>({ running: null, pending: [] });
  const [healthItems, setHealthItems] = useState<Record<string, ServiceHealthItem>>({});
  const [healthSummary, setHealthSummary] = useState<ServiceHealthSummary | null>(null);
  const [healthChecking, setHealthChecking] = useState(false);
  const [healthCheckingIds, setHealthCheckingIds] = useState<Set<string>>(new Set());
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthLastCheckedAt, setHealthLastCheckedAt] = useState<string | null>(null);
  const lastFailureHealthRunRef = useRef<string | null>(null);

  const refreshQueue = () =>
    getQueue()
      .then(setQueue)
      .catch(() => setQueue({ running: null, pending: [] }));

  // Detail (history replay) mode
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [exportingHistory, setExportingHistory] = useState(false);
  const [selectedHistoryRunIds, setSelectedHistoryRunIds] = useState<Set<string>>(new Set());
  const [runtimeStatus, setRuntimeStatus] = useState<RunStatusDetail | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  const refreshHistory = () =>
    getHistory()
      .then((items) => {
        setHistory(items);
        setSelectedHistoryRunIds((prev) => {
          const existing = new Set(items.map((item) => item.run_id));
          return new Set(Array.from(prev).filter((runId) => existing.has(runId)));
        });
        if (!items.some((item) => item.status === "running")) {
          setError(null);
        }
      })
      .catch(() => setHistory([]));

  const runServiceHealthCheck = useCallback(() => {
    healthUnsubscribeRef.current?.();
    setHealthChecking(true);
    setHealthCheckingIds(new Set());
    setHealthError(null);
    setHealthSummary(null);
    setHealthItems({});
    healthUnsubscribeRef.current = subscribeServiceHealth(
      (event) => {
        if (event.event === "service_status") {
          setHealthItems((items) => ({ ...items, [event.data.id]: event.data }));
        } else {
          setHealthSummary(event.data);
        }
      },
      () => {
        healthUnsubscribeRef.current = null;
        setHealthChecking(false);
        setHealthLastCheckedAt(new Date().toISOString());
      },
      (message) => setHealthError(message),
    );
  }, []);

  const runSingleServiceHealthCheck = useCallback((serviceId: string) => {
    const currentItem = healthItems[serviceId] ?? null;
    if (!currentItem) return;

    const checkingItems = {
      ...healthItems,
      [serviceId]: {
        ...currentItem,
        status: "checking" as const,
        message: "Checking service",
        latency_ms: null,
      },
    };
    setHealthItems(checkingItems);
    setHealthSummary(summarizeHealthItems(Object.values(checkingItems)));
    setHealthCheckingIds((ids) => new Set(ids).add(serviceId));
    checkServiceHealth(serviceId)
      .then((item) => {
        const next = { ...checkingItems, [item.id]: item };
        setHealthItems(next);
        setHealthSummary(summarizeHealthItems(Object.values(next)));
        setHealthError(null);
        setHealthLastCheckedAt(new Date().toISOString());
      })
      .catch((err) => {
        const next = {
          ...checkingItems,
          [serviceId]: {
            ...currentItem,
            status: "error" as const,
            message: (err as Error).message,
            latency_ms: null,
          },
        };
        setHealthItems(next);
        setHealthSummary(summarizeHealthItems(Object.values(next)));
      })
      .finally(() => {
        setHealthCheckingIds((ids) => {
          const next = new Set(ids);
          next.delete(serviceId);
          return next;
        });
      });
  }, [healthItems]);

  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
    refreshQueue();
    const healthTimer = window.setTimeout(runServiceHealthCheck, 0);
    return () => {
      window.clearTimeout(healthTimer);
      unsubscribeRef.current?.();
      healthUnsubscribeRef.current?.();
    };
  }, [runServiceHealthCheck]);

  // The backend advances the queue whenever a runner thread finishes
  // (scheduler.advance). The live SSE stream-close callback drives the UI in the
  // common case, but it can't cover every path: a page reload re-mounts with no
  // SSE subscription, and viewing a running run's history detail only polls that
  // one run. While the queue has items the backend is still progressing, so poll
  // both the queue panel and the history sidebar independently — otherwise both
  // freeze on stale state until the page is reloaded. Keep the last known values
  // on a transient error instead of blanking them.
  const queueActive = queue.running !== null || queue.pending.length > 0;
  useEffect(() => {
    if (!queueActive) return;
    const timer = window.setInterval(() => {
      getQueue().then(setQueue).catch(() => {});
      getHistory().then(setHistory).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [queueActive]);

  useEffect(() => {
    if (!currentRunId || !running) return;
    let alive = true;

    const refreshRuntime = () => {
      getAnalysisStatus(currentRunId)
        .then((s) => {
          if (!alive) return;
          setLiveRuntimeStatus(s);
          setLiveRuntimeError(null);
        })
        .catch((err) => {
          if (!alive) return;
          setLiveRuntimeError((err as Error).message);
        });
    };

    refreshRuntime();
    const timer = window.setInterval(refreshRuntime, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [currentRunId, running]);

  const exitDetail = () => {
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(false);
    setRuntimeStatus(null);
    setRuntimeError(null);
  };

  const onOpenDetail = async (runId: string) => {
    setSelectedId(runId);
    setDetail(null);
    setDetailError(null);
    setRuntimeStatus(null);
    setRuntimeError(null);
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

  useEffect(() => {
    if (!selectedId || detail?.status !== "running") return;
    let alive = true;

    const refreshRuntime = () => {
      Promise.all([
        getAnalysisStatus(selectedId),
        getHistoryDetail(selectedId).catch(() => null),
      ])
        .then(([s, nextDetail]) => {
          if (!alive) return;
          setRuntimeStatus(s);
          setRuntimeError(null);
          if (nextDetail) setDetail(nextDetail);
          if (nextDetail && nextDetail.status !== "running") {
            refreshHistory();
            if (nextDetail.status === "error" && lastFailureHealthRunRef.current !== selectedId) {
              lastFailureHealthRunRef.current = selectedId;
              runServiceHealthCheck();
            }
          }
        })
        .catch((err) => {
          if (!alive) return;
          setRuntimeError((err as Error).message);
        });
    };

    refreshRuntime();
    const timer = window.setInterval(refreshRuntime, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [selectedId, detail?.status, runServiceHealthCheck]);

  const onDeleteHistory = (id: string) => {
    if (id === selectedId) exitDetail();
    setSelectedHistoryRunIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    deleteHistory(id).then(refreshHistory);
  };

  const onToggleHistoryRun = (runId: string) => {
    setSelectedHistoryRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  const onToggleHistoryDate = (runIds: string[], selected: boolean) => {
    setSelectedHistoryRunIds((prev) => {
      const next = new Set(prev);
      for (const runId of runIds) {
        if (selected) next.add(runId);
        else next.delete(runId);
      }
      return next;
    });
  };

  const onExportHistoryReports = async () => {
    const runIds = Array.from(selectedHistoryRunIds);
    if (exportingHistory || runIds.length === 0) return;
    setExportingHistory(true);
    setError(null);
    try {
      const resp = await fetch(historyReportsZipUrl(runIds));
      if (resp.status === 404) throw new Error("暂无可导出的历史报告");
      if (!resp.ok) throw new Error("批量导出报告失败");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tradingagents_reports_${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExportingHistory(false);
    }
  };

  const resetRunView = () => {
    setStatuses({});
    setMessages([]);
    setDebateDetails({});
    setDecision(null);
    setError(null);
    setLiveRuntimeStatus(null);
    setLiveRuntimeError(null);
    setCanceling(false);
  };

  const followRun = (runId: string) => {
    followGenRef.current += 1;
    setCurrentRunId(runId);
    setRunning(true);
    unsubscribeRef.current = subscribe(
      runId,
      (e: SSEEvent) => {
        if (e.event === "agent_status")
          setStatuses((s) =>
            e.data.status === "done" ? nextLiveStatuses(s, e.data.agent) : s,
          );
        else if (e.event === "message")
          setMessages((m) => [...m, { agent: e.data.agent, content: e.data.content }]);
        else if (e.event === "done")
          setDecision({ d: e.data.decision, detail: e.data.final_trade_decision });
        else if (e.event === "error") {
          setError(e.data.message);
          lastFailureHealthRunRef.current = runId;
          runServiceHealthCheck();
        }
        else if (e.event === "cancelled") setError("分析已停止");
        else if (e.event === "debate_round") {
          const id = e.data.team === "invest" ? "debate" : "risk_debate";
          const teamLabel = e.data.team === "invest" ? "多空辩论" : "风险辩论";
          const detail = `第 ${e.data.round}/${e.data.total} 轮 · ${e.data.speaker_label}`;
          setMessages((m) => [...m, { agent: `${teamLabel} · ${detail}`, content: e.data.content }]);
          setStatuses((s) => (s[id] === "done" ? s : { ...s, [id]: "working" }));
          setDebateDetails((d) => ({ ...d, [id]: detail }));
        }
      },
      () => {
        unsubscribeRef.current = null;
        refreshHistory();
        void followNextInQueue();
      },
    );
  };

  // Poll the queue and attach to the next running run. Retries briefly because
  // after a cancel the backend advances only once the runner thread notices the
  // cancel between graph chunks — the next run may not be `running` on the first poll.
  const followNextInQueue = async (attempt = 0): Promise<void> => {
    const gen = followGenRef.current;
    const q = await getQueue().catch(() => null);
    if (followGenRef.current !== gen) return; // a newer follow-origin superseded us
    if (!q) {
      setRunning(false);
      setCanceling(false);
      setCurrentRunId(null);
      return;
    }
    setQueue(q);
    if (q.running) {
      resetRunView();
      followRun(q.running.run_id);
      return;
    }
    if (q.pending.length > 0 && attempt < 5) {
      window.setTimeout(() => {
        if (followGenRef.current !== gen) return; // superseded before retry fired
        void followNextInQueue(attempt + 1);
      }, 600);
      return;
    }
    setRunning(false);
    setCanceling(false);
    setCurrentRunId(null);
  };

  const onStart = async (req: Parameters<typeof enqueueAnalysis>[0]) => {
    followGenRef.current += 1;
    exitDetail();
    resetRunView();
    setError(null);
    try {
      const { running_run_id, queue: nextQueue } = await enqueueAnalysis(req);
      setQueue(nextQueue);
      refreshHistory();
      if (running_run_id) followRun(running_run_id);
    } catch (err) {
      setRunning(false);
      setCanceling(false);
      setCurrentRunId(null);
      setError((err as Error).message);
    }
  };

  const cancelRun = async (runId: string) => {
    if (canceling) return;
    setCanceling(true);
    const isLiveRun = currentRunId === runId;
    try {
      await cancelAnalysis(runId);
      setError("分析已停止");
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      refreshHistory();
      if (selectedId === runId) {
        const next = await getHistoryDetail(runId);
        setDetail(next);
        const status = await getAnalysisStatus(runId).catch(() => null);
        setRuntimeStatus(status);
      }
      if (isLiveRun) {
        // Drive the follow-next logic so the UI picks up the auto-advanced run.
        // followNextInQueue sets running/canceling/currentRunId appropriately.
        void followNextInQueue();
      } else {
        setRunning(false);
        setCanceling(false);
      }
    } catch (err) {
      setCanceling(false);
      setError((err as Error).message);
    }
  };

  const onCancel = () => {
    if (!currentRunId) return;
    void cancelRun(currentRunId);
  };

  const onRemoveQueueItem = (runId: string) =>
    removeQueueItem(runId).then(refreshQueue).catch((e) => setError((e as Error).message));

  const onClearQueue = () =>
    clearQueue().then(refreshQueue).catch((e) => setError((e as Error).message));

  const onReorderQueue = (orderedRunIds: string[]) =>
    reorderQueue(orderedRunIds).then(setQueue).catch((e) => setError((e as Error).message));

  const inDetailMode = selectedId !== null;
  const selectedRunning = detail?.status === "running";
  const sidebarStatuses = selectedRunning
    ? deriveHistoryProgress(detail, runtimeStatus)
    : statuses;
  const sidebarLastSection = selectedRunning
    ? runtimeStatus?.last_report_section
    : liveRuntimeStatus?.last_report_section;
  const showEmptyState =
    !inDetailMode &&
    !running &&
    messages.length === 0 &&
    !decision;
  const latestMessage = messages.at(-1);
  const completedAgents = Object.values(sidebarStatuses).filter((s) => s === "done").length;
  const workingAgents = Object.values(sidebarStatuses).filter((s) => s === "working").length;
  const sortedHealthItems = sortServiceHealthItems(Object.values(healthItems));

  return (
    <div className="min-h-screen text-foreground lg:h-screen lg:overflow-hidden">
      <div className="glass-glow" aria-hidden="true" />
      <div className="grid min-h-screen grid-cols-1 lg:h-screen lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
        <div className="order-3 min-h-[18rem] lg:order-1 lg:min-h-0">
          <HistorySidebar
            items={history}
            selectedId={selectedId}
            selectedRunIds={selectedHistoryRunIds}
            onOpen={onOpenDetail}
            onDelete={onDeleteHistory}
            onToggleRun={onToggleHistoryRun}
            onToggleDate={onToggleHistoryDate}
            onExportSelected={() => void onExportHistoryReports()}
            exporting={exportingHistory}
          />
        </div>

        <main className="order-2 min-h-0 border-border lg:order-2 lg:h-screen lg:overflow-y-auto lg:border-r">
          <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-3 py-3 sm:px-4 lg:px-5">
            <div className="mb-3">
              <ServiceHealthPanel
                items={sortedHealthItems}
                summary={healthSummary}
                checking={healthChecking}
                error={healthError}
                lastCheckedAt={healthLastCheckedAt}
                onCheck={runServiceHealthCheck}
                onCheckOne={runSingleServiceHealthCheck}
                checkingIds={healthCheckingIds}
              />
            </div>

            <header className="glass mb-3 rounded-lg px-3 py-3">
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
                <div className="flex flex-wrap items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
                  <Link
                    href="/chat"
                    className="glass-control inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-foreground transition-colors hover:border-primary/60 hover:text-primary focus-visible:outline-none focus-visible:border-primary"
                  >
                    <MessageCircle className="size-3.5" aria-hidden="true" />
                    顾问对话
                  </Link>
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
                  className="glass inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:border-primary"
                >
                  <ArrowLeft className="size-3.5" />
                  新分析
                </button>
                {detailLoading && (
                  <div className="space-y-3" aria-busy="true" aria-label="加载中">
                    <div className="glass h-16 rounded-lg" />
                    <div className="glass h-36 rounded-lg" />
                    <div className="glass h-36 rounded-lg" />
                  </div>
                )}
                {detailError && (
                  <div className="glass-readable rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
                    {detailError}
                  </div>
                )}
                {detail && (
                  <RunDetail
                    run={detail}
                    runtime={runtimeStatus}
                    runtimeError={runtimeError}
                    currentAgentLabel={workingAgentLabel(sidebarStatuses)}
                    onCancel={detail.status === "running" ? cancelRun : undefined}
                    canceling={canceling}
                  />
                )}
              </section>
            ) : (
              <section className="space-y-3">
                {error && (
                  <div className="glass-readable rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-sm text-destructive">
                    {error}
                  </div>
                )}
                {showEmptyState && (
                  <div className="glass rounded-lg px-4 py-5">
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
                  <div className="thinking-panel flex flex-wrap items-center justify-between gap-2 rounded-md px-3 py-2">
                    <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-amber-300">
                      <Activity className="size-3.5" aria-hidden="true" />
                      分析进行中
                    </div>
                    <button
                      type="button"
                      onClick={onCancel}
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
                  </div>
                )}
                {running && (
                  <RuntimeStatusPanel
                    runtime={liveRuntimeStatus}
                    runtimeError={liveRuntimeError}
                    currentAgentLabel={workingAgentLabel(statuses)}
                  />
                )}
                {messages.map((m, i) => (
                  <MessageBubble key={i} agent={m.agent} content={m.content} />
                ))}
                {decision && <DecisionCard decision={decision.d} detail={decision.detail} />}
              </section>
            )}
          </div>
        </main>

        <aside className="dark-scrollbar order-1 border-b border-border p-3 lg:order-3 lg:h-screen lg:overflow-y-auto lg:border-b-0">
          <div className="space-y-3">
            <div className="glass rounded-lg px-3 py-3">
              <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                Active Context
              </div>
              <div className="mt-2 space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Mode</span>
                  <span className="font-mono text-foreground">
                    {selectedRunning ? "RUNNING" : inDetailMode ? "HISTORY" : running ? "LIVE" : "READY"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-muted-foreground">Latest</span>
                  <span className="max-w-[12rem] truncate font-mono text-foreground">
                    {selectedRunning
                      ? sidebarLastSection
                        ? (SECTION_LABELS[sidebarLastSection] ?? sidebarLastSection)
                        : "RUNNING"
                      : latestMessage?.agent ?? (selectedId ? "DETAIL" : "NONE")}
                  </span>
                </div>
              </div>
            </div>

            {!selectedRunning &&
              options && <ConfigCard options={options} onStart={onStart} running={running} />}

            {error && (
              <div className="glass-readable rounded-md border-destructive/50 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive">
                {error}
              </div>
            )}

            <QueuePanel
              queue={queue}
              onRemove={onRemoveQueueItem}
              onClear={onClearQueue}
              onReorder={onReorderQueue}
              onCancelRunning={(runId) => void cancelRun(runId)}
              canceling={canceling}
            />

            <AgentProgress statuses={sidebarStatuses} details={debateDetails} />

            {decision && (
              <DecisionCard decision={decision.d} detail={decision.detail} compact />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
