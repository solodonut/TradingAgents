"use client";

import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatMessageT } from "@/lib/types";

export function ChatMessage({ message }: { message: ChatMessageT }) {
  const isUser = message.role === "user";
  const isThinking = message.role === "assistant" && message.content.trim().length === 0;
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
        {message.tool_calls.length > 0 && (
          <div className="mt-1 font-mono text-[0.6rem] text-muted-foreground">
            数据来源:{" "}
            {message.tool_calls
              .map((t) => String((t as { tool?: string }).tool ?? ""))
              .join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}
