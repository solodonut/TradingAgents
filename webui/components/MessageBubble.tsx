"use client";
import { MarkdownContent } from "@/components/MarkdownContent";

export function MessageBubble({ agent, content }: { agent: string; content: string }) {
  return (
    <article className="rounded-lg border border-border bg-card">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div>
          <div className="font-mono text-[0.65rem] uppercase tracking-[0.18em] text-muted-foreground">
            Research Memo
          </div>
          <div className="mt-0.5 font-mono text-sm text-primary">{agent}</div>
        </div>
        <div className="rounded border border-border px-1.5 py-0.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-muted-foreground">
          streamed
        </div>
      </header>
      <div className="ta-prose prose prose-invert prose-sm max-w-none px-3 py-3 prose-pre:border prose-pre:border-border prose-pre:bg-background prose-table:text-sm">
        <MarkdownContent content={content} />
      </div>
    </article>
  );
}
