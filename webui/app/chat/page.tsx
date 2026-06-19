"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Calculator,
  Home,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  getPortfolio,
  listChatSessions,
  savePortfolio,
  chatStreamUrl,
} from "@/lib/api";
import { streamChat } from "@/lib/sse";
import type { ChatMessageT, ChatSessionT, PortfolioHolding } from "@/lib/types";
import { RunPicker } from "@/components/chat/RunPicker";
import { PortfolioUpload } from "@/components/chat/PortfolioUpload";
import { HoldingsTable } from "@/components/chat/HoldingsTable";
import { ChatMessage } from "@/components/chat/ChatMessage";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionT[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const streamingRef = useRef("");
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const refreshSessions = async () => {
    const next = await listChatSessions().catch(() => []);
    setSessions(next);
    return next;
  };

  const openSession = async (id: string) => {
    const data = await getChatSession(id);
    setSessionId(data.session.session_id);
    setRunId(data.session.run_id);
    setMessages(data.messages);
    const portfolio = await getPortfolio(data.session.session_id).catch(() => ({
      holdings: [],
      source: "manual",
    }));
    setHoldings(portfolio.holdings);
  };

  const createNewSession = async (nextRunId: string | null = runId) => {
    const sid = await createChatSession(nextRunId);
    await refreshSessions();
    await openSession(sid);
  };

  const removeSession = async (id: string) => {
    if (streaming || deletingSessionId) return;
    setDeletingSessionId(id);
    try {
      await deleteChatSession(id);
      const remaining = await refreshSessions();
      if (id !== sessionId) return;

      const next = remaining.find((session) => session.session_id !== id);
      if (next) {
        await openSession(next.session_id);
      } else {
        setSessionId(null);
        setMessages([]);
        setHoldings([]);
        await createNewSession(runId);
      }
    } finally {
      setDeletingSessionId(null);
    }
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      const next = await refreshSessions();
      if (!alive) return;
      if (next[0]) await openSession(next[0].session_id);
      else await createNewSession(null);
    })();
    return () => {
      alive = false;
    };
    // Intentionally run once on page load; run selection is a context for new sessions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const send = async () => {
    if (!sessionId || !input.trim() || streaming) return;
    const now = Date.now();
    const userMsg: ChatMessageT = {
      message_id: `local-${now}`,
      session_id: sessionId,
      role: "user",
      content: input,
      tool_calls: [],
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    const question = input;
    setInput("");
    setStreaming(true);
    streamingRef.current = "";

    const assistantId = `stream-${now}`;
    setMessages((m) => [
      ...m,
      { message_id: assistantId, session_id: sessionId, role: "assistant", content: "", tool_calls: [], created_at: new Date().toISOString() },
    ]);

    await streamChat(chatStreamUrl(sessionId), question, (e) => {
      if (e.event === "token") {
        streamingRef.current += e.data.content;
        setMessages((m) =>
          m.map((msg) =>
            msg.message_id === assistantId
              ? { ...msg, content: streamingRef.current }
              : msg,
          ),
        );
      } else if (e.event === "done") {
        setMessages((m) =>
          m.map((msg) =>
            msg.message_id === assistantId
              ? { ...msg, content: e.data.content, tool_calls: e.data.tool_calls }
              : msg,
          ),
        );
      } else if (e.event === "error") {
        setMessages((m) =>
          m.map((msg) =>
            msg.message_id === assistantId
              ? { ...msg, content: `⚠️ 出错了:${e.data.message}` }
              : msg,
          ),
        );
      }
    });
    setStreaming(false);
    void refreshSessions();
  };

  const persistHoldings = async (next: PortfolioHolding[]) => {
    setHoldings(next);
    if (sessionId) await savePortfolio(sessionId, next);
  };

  const recalculateWeights = () => {
    const total = holdings.reduce(
      (sum, holding) => sum + (Number(holding.market_value) || 0),
      0,
    );
    if (total <= 0) return;

    void persistHoldings(
      holdings.map((holding) => ({
        ...holding,
        weight: Number((((Number(holding.market_value) || 0) / total) * 100).toFixed(2)),
      })),
    );
  };

  const currentSession = sessions.find((s) => s.session_id === sessionId) ?? null;
  const currentTitle =
    currentSession?.title ??
    (currentSession?.run_id ? "关联分析会话" : "通用咨询");

  const formatSessionTime = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? iso
      : d.toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <main className="min-h-screen text-foreground lg:h-screen lg:overflow-hidden">
      <div className="glass-glow" aria-hidden="true" />
      <div
        className={`grid min-h-screen grid-cols-1 gap-4 p-4 lg:h-full lg:min-h-0 lg:box-border ${
          showHistory
            ? "lg:grid-cols-[18rem_minmax(0,1fr)_22rem]"
            : "lg:grid-cols-[minmax(0,1fr)_22rem]"
        }`}
      >
        {showHistory && (
          <aside className="glass flex min-h-0 flex-col rounded-lg lg:h-full">
            <div className="glass-readable flex shrink-0 items-center justify-between gap-2 rounded-none border-x-0 border-t-0 px-3 py-3">
              <div>
                <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                  Chat History
                </div>
                <div className="mt-0.5 text-sm text-foreground">会话历史</div>
              </div>
              <button
                type="button"
                onClick={() => setShowHistory(false)}
                className="glass-control inline-flex size-8 items-center justify-center rounded-md transition-colors hover:border-primary/60 hover:text-primary"
                aria-label="隐藏会话历史"
              >
                <PanelLeftClose className="size-4" />
              </button>
            </div>

            <div className="shrink-0 p-2">
              <button
                type="button"
                onClick={() => void createNewSession(runId)}
                className="glass-control inline-flex h-8 w-full items-center justify-center gap-2 rounded-md px-3 font-mono text-xs uppercase tracking-[0.14em] transition-colors hover:border-primary/60 hover:text-primary"
              >
                <Plus className="size-4" />
                新会话
              </button>
            </div>

            <div className="ios-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto p-2 pt-0">
              {sessions.map((session) => {
                const active = session.session_id === sessionId;
                return (
                  <div
                    key={session.session_id}
                    className={`group flex w-full items-stretch gap-1 rounded-md border p-1 transition-colors ${
                      active
                        ? "glass-strong border-primary/30"
                        : "border-transparent hover:border-sidebar-border hover:bg-sidebar-accent/70"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => void openSession(session.session_id)}
                      className="min-w-0 flex-1 rounded-[calc(var(--radius)-0.25rem)] px-2 py-1.5 text-left focus-visible:outline-none focus-visible:border-primary"
                    >
                      <div className="flex items-start gap-2">
                      <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-primary" />
                      <div className="min-w-0">
                        <div className="truncate text-sm text-foreground">
                          {session.title ?? "通用咨询"}
                        </div>
                        <div className="mt-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
                          {formatSessionTime(session.updated_at)}
                        </div>
                      </div>
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeSession(session.session_id)}
                      disabled={streaming || deletingSessionId === session.session_id}
                      className="glass-control inline-flex size-8 shrink-0 items-center justify-center self-center rounded-md text-muted-foreground opacity-70 transition-colors hover:border-destructive/50 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-35 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                      aria-label={`删除会话 ${session.title ?? "通用咨询"}`}
                      title="删除会话"
                    >
                      <Trash2 className="size-3.5" aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
          </aside>
        )}

        <section className="glass flex min-h-[28rem] flex-col rounded-lg lg:h-full lg:min-h-0">
          <div className="flex shrink-0 items-center justify-between gap-2">
            <div className="flex items-center gap-2 px-4 py-3">
              {!showHistory && (
                <button
                  type="button"
                  onClick={() => setShowHistory(true)}
                  className="glass-control inline-flex size-8 items-center justify-center rounded-md transition-colors hover:border-primary/60 hover:text-primary"
                  aria-label="显示会话历史"
                >
                  <PanelLeftOpen className="size-4" />
                </button>
              )}
              <div>
                <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                  Advisor Chat
                </div>
                <h1 className="mt-0.5 text-sm font-semibold text-foreground">
                  {currentTitle}
                </h1>
              </div>
            </div>
            <div className="flex items-center gap-2 px-4 py-3">
              <Link
                href="/"
                className="glass-control inline-flex h-8 items-center gap-1.5 rounded-md px-2 font-mono text-[0.68rem] uppercase tracking-[0.12em] text-foreground transition-colors hover:border-primary/60 hover:text-primary focus-visible:outline-none focus-visible:border-primary"
              >
                <Home className="size-3.5" aria-hidden="true" />
                工作台
              </Link>
            </div>
          </div>
          <div className="ios-scrollbar flex-1 space-y-3 overflow-y-auto p-4">
            {messages.map((m) => (
              <ChatMessage key={m.message_id} message={m} />
            ))}
            <div ref={messagesEndRef} aria-hidden="true" />
          </div>
          <div className="flex items-center gap-2 border-t border-border p-3">
            <input
              className="glass-control flex-1 rounded-md px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
              placeholder="问问该如何操作…"
              aria-label="对话输入"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              disabled={streaming}
            />
            <Button onClick={send} disabled={streaming || !input.trim()} aria-label="发送">
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </section>

        <aside className="glass flex min-h-0 flex-col gap-3 rounded-lg p-3 lg:h-full">
          <div className="shrink-0">
            <RunPicker value={runId} onChange={setRunId} />
          </div>
          <div className="glass-readable flex min-h-0 flex-1 flex-col rounded-lg px-3 py-3">
            <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
              <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
                当前持仓
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={recalculateWeights}
                  disabled={holdings.length === 0}
                  className="glass-control inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <Calculator className="size-4" aria-hidden="true" />
                  重算占比
                </button>
                {sessionId && (
                  <PortfolioUpload sessionId={sessionId} onExtracted={persistHoldings} />
                )}
              </div>
            </div>
            <div className="ios-scrollbar min-h-0 flex-1 overflow-y-auto pr-0.5">
              <HoldingsTable holdings={holdings} onChange={persistHoldings} />
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
