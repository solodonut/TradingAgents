"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Calculator,
  Check,
  FileDown,
  Pencil,
  Home,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  deleteChatSession,
  deleteChatSessions,
  getChatSession,
  getConfigOptions,
  getPortfolio,
  listChatSessions,
  renameChatSession,
  savePortfolio,
  chatStreamUrl,
  updateChatSessionReports,
} from "@/lib/api";
import { streamChat } from "@/lib/sse";
import { EXPORT_REPORT_PROMPT, exportScopeOptions } from "@/lib/chat-export";
import type { ChatMessageT, ChatSessionT, PortfolioHolding } from "@/lib/types";
import { RunPicker } from "@/components/chat/RunPicker";
import { PortfolioUpload } from "@/components/chat/PortfolioUpload";
import { HoldingsTable } from "@/components/chat/HoldingsTable";
import { ChatMessage } from "@/components/chat/ChatMessage";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [sessions, setSessions] = useState<ChatSessionT[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(new Set());
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [savingReports, setSavingReports] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [chatModels, setChatModels] = useState<[string, string][]>([]);
  const [chatLlm, setChatLlm] = useState("");
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
    setRunIds(data.session.run_ids);
    setReportError(null);
    setMessages(data.messages);
    const portfolio = await getPortfolio(data.session.session_id).catch(() => ({
      holdings: [],
      source: "manual",
    }));
    setHoldings(portfolio.holdings);
  };

  const createNewSession = async (nextRunIds: string[] = runIds) => {
    const sid = await createChatSession(nextRunIds);
    setSelectedSessionIds(new Set());
    setSelectMode(false);
    await refreshSessions();
    await openSession(sid);
  };

  const removeSession = async (id: string) => {
    if (streaming || deletingSessionId) return;
    setDeletingSessionId(id);
    try {
      await deleteChatSession(id);
      const remaining = await refreshSessions();
      setSelectedSessionIds((ids) => {
        const nextIds = new Set(ids);
        nextIds.delete(id);
        return nextIds;
      });
      if (id !== sessionId) return;

      const next = remaining.find((session) => session.session_id !== id);
      if (next) {
        await openSession(next.session_id);
      } else {
        setSessionId(null);
        setMessages([]);
        setHoldings([]);
        await createNewSession(runIds);
      }
    } finally {
      setDeletingSessionId(null);
    }
  };

  const removeSelectedSessions = async () => {
    if (streaming || deletingSessionId || selectedSessionIds.size === 0) return;
    const ids = Array.from(selectedSessionIds);
    setDeletingSessionId("__bulk__");
    try {
      await deleteChatSessions(ids);
      const remaining = await refreshSessions();
      setSelectedSessionIds(new Set());
      setSelectMode(false);

      if (!sessionId || !ids.includes(sessionId)) return;
      if (remaining[0]) {
        await openSession(remaining[0].session_id);
      } else {
        setSessionId(null);
        setMessages([]);
        setHoldings([]);
        await createNewSession(runIds);
      }
    } finally {
      setDeletingSessionId(null);
    }
  };

  const toggleSelectedSession = (id: string) => {
    setSelectedSessionIds((ids) => {
      const next = new Set(ids);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startRename = (session: ChatSessionT) => {
    setRenamingSessionId(session.session_id);
    setRenameTitle(session.title ?? "通用咨询");
  };

  const cancelRename = () => {
    setRenamingSessionId(null);
    setRenameTitle("");
  };

  const saveRename = async () => {
    if (!renamingSessionId || !renameTitle.trim()) return;
    await renameChatSession(renamingSessionId, renameTitle.trim());
    await refreshSessions();
    cancelRename();
  };

  useEffect(() => {
    let alive = true;
    (async () => {
      const next = await refreshSessions();
      if (!alive) return;
      if (next[0]) await openSession(next[0].session_id);
      else await createNewSession([]);
    })();
    return () => {
      alive = false;
    };
    // Intentionally run once on page load; run selection is a context for new sessions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    getConfigOptions()
      .then((opts) => {
        // deep + quick 合并去重（按 model_id）
        const seen = new Set<string>();
        const merged: [string, string][] = [];
        for (const [label, id] of [
          ...opts.model_options.quick,
          ...opts.model_options.deep,
        ]) {
          if (!seen.has(id)) {
            seen.add(id);
            merged.push([label, id]);
          }
        }
        setChatModels(merged);
        const saved = localStorage.getItem("ta:chat_llm");
        const fallback = opts.configured_quick_llm ?? "";
        setChatLlm(saved && seen.has(saved) ? saved : fallback);
      })
      .catch(() => {
        /* 配置加载失败时下拉为空，发消息仍走后端默认 */
      });
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const sendMessage = async (rawQuestion: string) => {
    const question = rawQuestion.trim();
    if (!sessionId || !question || streaming) return;
    const now = Date.now();
    const userMsg: ChatMessageT = {
      message_id: `local-${now}`,
      session_id: sessionId,
      role: "user",
      content: question,
      tool_calls: [],
      created_at: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    setInput("");
    setStreaming(true);
    streamingRef.current = "";

    const assistantId = `stream-${now}`;
    setMessages((m) => [
      ...m,
      { message_id: assistantId, session_id: sessionId, role: "assistant", content: "", tool_calls: [], created_at: new Date().toISOString() },
    ]);

    try {
      await streamChat(
        chatStreamUrl(sessionId),
        question,
        (e) => {
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
        },
        undefined,
        chatLlm || undefined,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "连接失败";
      setMessages((current) =>
        current.map((item) =>
          item.message_id === assistantId
            ? { ...item, content: `⚠️ 出错了:${message}` }
            : item,
        ),
      );
    } finally {
      setStreaming(false);
      void refreshSessions();
    }
  };

  const send = () => void sendMessage(input);

  const persistHoldings = async (next: PortfolioHolding[]) => {
    setHoldings(next);
    if (sessionId) await savePortfolio(sessionId, next);
  };

  const changeReports = async (nextRunIds: string[]) => {
    const previous = runIds;
    setRunIds(nextRunIds);
    setReportError(null);
    if (!sessionId) return;
    setSavingReports(true);
    try {
      await updateChatSessionReports(sessionId, nextRunIds);
      await refreshSessions();
    } catch (error) {
      setRunIds(previous);
      setReportError(
        error instanceof Error ? error.message : "无法保存关联分析报告",
      );
    } finally {
      setSavingReports(false);
    }
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
    (currentSession?.run_ids.length ? "关联分析会话" : "通用咨询");
  const latestMessage = messages.at(-1);
  const activeChoiceMessageId =
    latestMessage?.role === "assistant" && exportScopeOptions(latestMessage).length > 0
      ? latestMessage.message_id
      : null;
  const canRequestExport =
    Boolean(sessionId) &&
    !streaming &&
    !deletingSessionId &&
    messages.some(
      (message) => message.role === "assistant" && message.content.trim().length > 0,
    );

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
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                <button
                  type="button"
                  onClick={() => void createNewSession(runIds)}
                  className="glass-control inline-flex h-8 min-w-0 items-center justify-center gap-2 rounded-md px-3 font-mono text-xs uppercase tracking-[0.14em] transition-colors hover:border-primary/60 hover:text-primary"
                >
                  <Plus className="size-4" />
                  新会话
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectMode((value) => !value);
                    setSelectedSessionIds(new Set());
                  }}
                  className="glass-control inline-flex h-8 items-center justify-center rounded-md px-2 text-xs transition-colors hover:border-primary/60 hover:text-primary"
                >
                  {selectMode ? "取消" : "选择"}
                </button>
              </div>
              {selectMode && (
                <button
                  type="button"
                  onClick={() => void removeSelectedSessions()}
                  disabled={selectedSessionIds.size === 0 || deletingSessionId === "__bulk__"}
                  className="glass-control mt-2 inline-flex h-8 w-full items-center justify-center gap-2 rounded-md px-3 text-sm text-destructive transition-colors hover:border-destructive/50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                  删除所选 {selectedSessionIds.size > 0 ? selectedSessionIds.size : ""}
                </button>
              )}
            </div>

            <div className="ios-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto p-2 pt-0">
              {sessions.map((session) => {
                const active = session.session_id === sessionId;
                const renaming = renamingSessionId === session.session_id;
                return (
                  <div
                    key={session.session_id}
                    className={`group flex w-full items-stretch gap-1 rounded-md border p-1 transition-colors ${
                      active
                        ? "glass-strong border-primary/30"
                        : "border-transparent hover:border-sidebar-border hover:bg-sidebar-accent/70"
                    }`}
                  >
                    {selectMode && (
                      <label className="flex shrink-0 items-center pl-1">
                        <input
                          type="checkbox"
                          checked={selectedSessionIds.has(session.session_id)}
                          onChange={() => toggleSelectedSession(session.session_id)}
                          className="size-4 accent-primary"
                          aria-label={`选择会话 ${session.title ?? "通用咨询"}`}
                        />
                      </label>
                    )}
                    {renaming ? (
                      <div className="min-w-0 flex-1 rounded-[calc(var(--radius)-0.25rem)] px-2 py-1.5 text-left">
                        <div className="flex items-start gap-2">
                          <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-primary" />
                          <div className="min-w-0 flex-1">
                            <input
                              value={renameTitle}
                              onChange={(e) => setRenameTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") void saveRename();
                                if (e.key === "Escape") cancelRename();
                              }}
                              className="glass-control h-7 w-full rounded-md px-2 text-sm outline-none focus:border-primary"
                              autoFocus
                              aria-label="会话名称"
                            />
                            <div className="mt-1 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
                              {formatSessionTime(session.updated_at)}
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : (
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
                    )}
                    {renaming ? (
                      <div className="flex shrink-0 items-center gap-1 self-center">
                        <button
                          type="button"
                          onClick={() => void saveRename()}
                          disabled={!renameTitle.trim()}
                          className="glass-control inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-35"
                          aria-label="保存会话名称"
                          title="保存"
                        >
                          <Check className="size-3.5" aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          onClick={cancelRename}
                          className="glass-control inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
                          aria-label="取消重命名"
                          title="取消"
                        >
                          <X className="size-3.5" aria-hidden="true" />
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => startRename(session)}
                        disabled={selectMode || streaming}
                        className="glass-control inline-flex size-8 shrink-0 items-center justify-center self-center rounded-md text-muted-foreground opacity-70 transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-35 lg:opacity-0 lg:group-hover:opacity-100 lg:focus-visible:opacity-100"
                        aria-label={`重命名会话 ${session.title ?? "通用咨询"}`}
                        title="重命名"
                      >
                        <Pencil className="size-3.5" aria-hidden="true" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void removeSession(session.session_id)}
                      disabled={selectMode || streaming || deletingSessionId === session.session_id}
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
              {chatModels.length > 0 && (
                <label className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">模型</span>
                  <select
                    value={chatLlm}
                    onChange={(e) => {
                      setChatLlm(e.target.value);
                      localStorage.setItem("ta:chat_llm", e.target.value);
                    }}
                    disabled={streaming}
                    className="glass-control h-8 rounded-md px-2 font-mono text-xs text-foreground outline-none transition-colors focus:border-primary disabled:opacity-50"
                  >
                    {chatModels.map(([label, id]) => (
                      <option key={id} value={id}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void sendMessage(EXPORT_REPORT_PROMPT)}
                disabled={!canRequestExport}
                aria-label="导出当前会话报告"
                title="通过对话选择范围并导出报告"
              >
                <FileDown className="size-3.5" aria-hidden="true" />
                导出报告
              </Button>
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
            {messages.map((message) => (
              <ChatMessage
                key={message.message_id}
                message={message}
                choicesEnabled={
                  message.message_id === activeChoiceMessageId && !streaming
                }
                onChoice={(choice) => void sendMessage(choice)}
              />
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
            <RunPicker
              value={runIds}
              onChange={(next) => void changeReports(next)}
              disabled={streaming || savingReports}
            />
            {reportError && (
              <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {reportError}
              </div>
            )}
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
