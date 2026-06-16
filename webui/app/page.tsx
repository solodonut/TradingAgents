"use client";
import { useEffect, useState } from "react";
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

  // Detail (history replay) mode
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const refreshHistory = () => getHistory().then(setHistory);

  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
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
    try {
      const runId = await startAnalysis(req);
      subscribe(
        runId,
        (e: SSEEvent) => {
          if (e.event === "agent_status")
            setStatuses((s) => ({ ...s, [e.data.agent]: e.data.status }));
          else if (e.event === "message")
            setMessages((m) => [...m, { agent: e.data.agent, content: e.data.content }]);
          else if (e.event === "done")
            setDecision({ d: e.data.decision, detail: e.data.final_trade_decision });
          else if (e.event === "error") setError(e.data.message);
        },
        () => {
          setRunning(false);
          refreshHistory();
        },
      );
    } catch (err) {
      setRunning(false);
      const msg = (err as Error).message;
      setError(
        msg === "已有分析正在运行"
          ? "已有分析正在运行，请等待当前分析完成后再试。"
          : msg,
      );
    }
  };

  const inDetailMode = selectedId !== null;
  const showEmptyState =
    !inDetailMode &&
    !running &&
    messages.length === 0 &&
    !decision &&
    history.length === 0;

  return (
    <div className="flex h-screen bg-black text-zinc-200">
      <HistorySidebar
        items={history}
        selectedId={selectedId}
        onOpen={onOpenDetail}
        onDelete={onDeleteHistory}
      />
      <main className="flex-1 overflow-y-auto p-4 space-y-3 max-w-3xl mx-auto">
        <h1 className="font-mono text-emerald-400 text-lg tracking-tight uppercase">
          TradingAgents 分析助手
        </h1>

        {inDetailMode ? (
          <>
            <button
              onClick={exitDetail}
              className="font-mono text-xs uppercase tracking-wider text-zinc-400 transition-colors hover:text-emerald-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 rounded px-1 -mx-1"
            >
              ← 新分析
            </button>
            {detailLoading && (
              <div className="space-y-3" aria-busy="true" aria-label="加载中">
                <div className="h-12 rounded-lg border border-zinc-800 bg-zinc-900" />
                <div className="h-28 rounded-lg border border-zinc-800 bg-zinc-900" />
                <div className="h-28 rounded-lg border border-zinc-800 bg-zinc-900" />
              </div>
            )}
            {detailError && (
              <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 font-mono text-sm text-red-400">
                {detailError}
              </div>
            )}
            {detail && <RunDetail run={detail} />}
          </>
        ) : (
          <>
            {error && (
              <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-red-400 font-mono text-sm">
                {error}
              </div>
            )}
            {showEmptyState && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-3 font-mono text-xs leading-relaxed text-zinc-400 space-y-1.5">
                <p className="text-zinc-300">多智能体 LLM 分析 → 买入 / 持有 / 卖出</p>
                <p>
                  输入代码与日期，配置分析师与研究深度后开始。一组智能体将依次给出
                  市场、情绪、新闻、基本面报告，经研究与风险辩论得出最终决策。
                </p>
                <p>分析将实时流式输出，通常需要几分钟。</p>
              </div>
            )}
            {options && (
              <ConfigCard options={options} onStart={onStart} running={running} />
            )}
            {running && (
              <div className="rounded border border-amber-800/60 bg-amber-950/30 px-3 py-2 font-mono text-xs text-amber-400">
                分析进行中…
              </div>
            )}
            <AgentProgress statuses={statuses} />
            {messages.map((m, i) => (
              <MessageBubble key={i} agent={m.agent} content={m.content} />
            ))}
            {decision && <DecisionCard decision={decision.d} detail={decision.detail} />}
          </>
        )}
      </main>
    </div>
  );
}
