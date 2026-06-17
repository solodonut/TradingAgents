"use client";

import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/MarkdownContent";
import type { ChatMessageT } from "@/lib/types";

export function ChatMessage({ message }: { message: ChatMessageT }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-lg border border-border px-3 py-2",
          isUser ? "bg-primary/10" : "bg-card",
        )}
      >
        {isUser ? (
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
