"use client";
import { useEffect, useState } from "react";
import { ConfigCard } from "@/components/ConfigCard";
import { AgentProgress } from "@/components/AgentProgress";
import { MessageBubble } from "@/components/MessageBubble";
import { DecisionCard } from "@/components/DecisionCard";
import { HistorySidebar } from "@/components/HistorySidebar";
import {
  deleteHistory,
  getConfigOptions,
  getHistory,
  startAnalysis,
} from "@/lib/api";
import { subscribe } from "@/lib/sse";
import type { ConfigOptions, Decision, HistorySummary, SSEEvent } from "@/lib/types";

export default function Home() {
  const [options, setOptions] = useState<ConfigOptions | null>(null);
  const [history, setHistory] = useState<HistorySummary[]>([]);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [messages, setMessages] = useState<{ agent: string; content: string }[]>([]);
  const [decision, setDecision] = useState<{ d: Decision; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshHistory = () => getHistory().then(setHistory);

  useEffect(() => {
    getConfigOptions().then(setOptions).catch(() => setError("无法连接后端"));
    refreshHistory();
  }, []);

  const onStart = async (req: Parameters<typeof startAnalysis>[0]) => {
    setStatuses({});
    setMessages([]);
    setDecision(null);
    setError(null);
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
        refreshHistory,
      );
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="flex h-screen bg-black text-zinc-200">
      <HistorySidebar
        items={history}
        onOpen={() => {}}
        onDelete={(id) => deleteHistory(id).then(refreshHistory)}
      />
      <main className="flex-1 overflow-y-auto p-4 space-y-3 max-w-3xl mx-auto">
        <h1 className="font-mono text-emerald-400 text-lg tracking-tight uppercase">
          TradingAgents 分析助手
        </h1>
        {error && (
          <div className="rounded border border-red-800 bg-red-950/40 px-3 py-2 text-red-400 font-mono text-sm">
            {error}
          </div>
        )}
        {options && <ConfigCard options={options} onStart={onStart} />}
        <AgentProgress statuses={statuses} />
        {messages.map((m, i) => (
          <MessageBubble key={i} agent={m.agent} content={m.content} />
        ))}
        {decision && <DecisionCard decision={decision.d} detail={decision.detail} />}
      </main>
    </div>
  );
}
