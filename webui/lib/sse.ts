import type { ChatSSEEvent, SSEEvent } from "./types";
import { streamUrl } from "./api";

export function subscribe(
  runId: string,
  onEvent: (e: SSEEvent) => void,
  onClose: () => void,
): () => void {
  const es = new EventSource(streamUrl(runId));
  const handler = (type: SSEEvent["event"]) => (ev: MessageEvent) => {
    try {
      onEvent({ event: type, data: JSON.parse(ev.data) } as SSEEvent);
    } catch {
      /* ignore malformed */
    }
  };
  (
    ["agent_status", "message", "report_section", "stats", "done", "error", "cancelled"] as const
  ).forEach((t) => es.addEventListener(t, handler(t)));
  es.addEventListener("done", () => {
    es.close();
    onClose();
  });
  es.addEventListener("cancelled", () => {
    es.close();
    onClose();
  });
  es.onerror = () => {
    es.close();
    onClose();
  };
  return () => es.close();
}

/**
 * POST a chat message and stream SSE events back via fetch + ReadableStream.
 * Native EventSource cannot POST, so we parse the SSE wire format manually.
 */
export async function streamChat(
  url: string,
  message: string,
  onEvent: (e: ChatSSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!resp.body) return;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      let eventName = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      try {
        onEvent({ event: eventName, data: JSON.parse(dataLine) } as ChatSSEEvent);
      } catch {
        /* ignore malformed block */
      }
    }
  }
}
