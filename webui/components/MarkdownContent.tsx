"use client";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

function normalizeInlineTables(markdown: string): string {
  return markdown
    .split("\n")
    .map((line) => {
      if (!line.includes("|") || !/\|\s*:?-{3,}:?\s*(?:\||$)/.test(line)) {
        return line;
      }
      return line.replace(/\s+\|\s+\|/g, "\n|");
    })
    .join("\n");
}

const components: Components = {
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-md border border-border">
      <table className="min-w-full border-collapse text-left font-mono text-xs">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-r border-border px-3 py-2 font-semibold text-foreground last:border-r-0">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="align-top border-b border-r border-border px-3 py-2 leading-6 last:border-r-0">
      {children}
    </td>
  ),
  tr: ({ children }) => (
    <tr className="border-border last:[&>td]:border-b-0">{children}</tr>
  ),
};

export function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {normalizeInlineTables(content)}
    </ReactMarkdown>
  );
}
