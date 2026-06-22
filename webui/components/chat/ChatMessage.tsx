"use client";

import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { exportScopeOptions, visibleDataSources } from "@/lib/chat-export";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatMessageT } from "@/lib/types";

export function ChatMessage({
  message,
  choicesEnabled = false,
  onChoice,
}: {
  message: ChatMessageT;
  choicesEnabled?: boolean;
  onChoice?: (choice: string) => void;
}) {
  const isUser = message.role === "user";
  const isThinking = message.role === "assistant" && message.content.trim().length === 0;
  const choices = exportScopeOptions(message);
  const dataSources = visibleDataSources(message);
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-3 py-2",
          isThinking
            ? "thinking-border min-w-40"
            : isUser
            ? "glass border-primary/30 bg-primary/10"
            : "glass-readable",
        )}
        aria-busy={isThinking ? "true" : undefined}
      >
        {isThinking ? (
          <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em]">
            <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" />
            正在思考
          </div>
        ) : isUser ? (
          <p className="whitespace-pre-wrap text-sm">{message.content}</p>
        ) : (
          <MarkdownContent content={message.content} />
        )}
        {choices.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2" aria-label="导出范围选项">
            {choices.map((choice) => (
              <button
                key={choice}
                type="button"
                disabled={!choicesEnabled}
                onClick={() => onChoice?.(choice)}
                className="glass-control rounded-md px-2.5 py-1.5 text-left text-xs text-foreground transition-colors hover:border-primary/60 hover:text-primary disabled:cursor-not-allowed disabled:opacity-45"
              >
                {choice}
              </button>
            ))}
          </div>
        )}
        {dataSources.length > 0 && (
          <div className="mt-1 font-mono text-[0.6rem] text-muted-foreground">
            数据来源: {dataSources.join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
