"use client";

import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  createChatSession,
  getChatSession,
  getPortfolio,
  savePortfolio,
  chatStreamUrl,
} from "@/lib/api";
import { streamChat } from "@/lib/sse";
import type { ChatMessageT, PortfolioHolding } from "@/lib/types";
import { RunPicker } from "@/components/chat/RunPicker";
import { PortfolioUpload } from "@/components/chat/PortfolioUpload";
import { HoldingsTable } from "@/components/chat/HoldingsTable";
import { ChatMessage } from "@/components/chat/ChatMessage";

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef("");

  useEffect(() => {
    createChatSession(runId).then((sid) => {
      setSessionId(sid);
      setMessages([]);
      getPortfolio(sid).then((p) => setHoldings(p.holdings));
    });
  }, [runId]);

  const send = async () => {
    if (!sessionId || !input.trim() || streaming) return;
    const userMsg: ChatMessageT = {
      message_id: `local-${Date.now()}`,
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

    const assistantId = `stream-${Date.now()}`;
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
      }
    });
    setStreaming(false);
  };

  const persistHoldings = async (next: PortfolioHolding[]) => {
    setHoldings(next);
    if (sessionId) await savePortfolio(sessionId, next);
  };

  return (
    <main className="grid h-screen grid-cols-[20rem_minmax(0,1fr)] gap-4 p-4">
      <aside className="flex flex-col gap-3 overflow-y-auto">
        <h1 className="font-mono text-sm uppercase tracking-[0.18em] text-muted-foreground">
          投资操作顾问
        </h1>
        <RunPicker value={runId} onChange={setRunId} />
        <div className="rounded-lg border border-border bg-card px-3 py-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
              当前持仓
            </span>
            {sessionId && (
              <PortfolioUpload sessionId={sessionId} onExtracted={persistHoldings} />
            )}
          </div>
          <HoldingsTable holdings={holdings} onChange={persistHoldings} />
        </div>
      </aside>

      <section className="flex h-full flex-col rounded-lg border border-border bg-background">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m) => (
            <ChatMessage key={m.message_id} message={m} />
          ))}
        </div>
        <div className="flex items-center gap-2 border-t border-border p-3">
          <input
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="问问该如何操作…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={streaming}
          />
          <Button onClick={send} disabled={streaming || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </section>
    </main>
  );
}
