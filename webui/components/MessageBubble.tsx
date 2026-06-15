"use client";
import ReactMarkdown from "react-markdown";

export function MessageBubble({ agent, content }: { agent: string; content: string }) {
  return (
    <div className="rounded-lg border border-zinc-700/80 bg-zinc-900 p-3">
      <div className="text-xs text-emerald-400 font-mono uppercase tracking-wider mb-1.5">
        {agent}
      </div>
      <div className="prose prose-invert prose-sm max-w-none prose-pre:bg-zinc-950 prose-pre:border prose-pre:border-zinc-800">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
