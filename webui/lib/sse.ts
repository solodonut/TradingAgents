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
    [
      "agent_status",
      "message",
      "report_section",
      "stats",
      "done",
      "error",
      "cancelled",
      "debate_round",
    ] as const
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
  model?: string,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(model ? { message, chat_llm: model } : { message }),
    signal,
  });
  if (!resp.body) return;
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // Normalize CRLF (sse-starlette uses \r\n) so the framing below is
    // line-ending agnostic. SSE separates events with a blank line.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      let eventName = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        // SSE allows multiple data: lines; join with \n per the spec so a
        // payload containing newlines is reassembled, not truncated.
        else if (line.startsWith("data:")) {
          dataLine += (dataLine ? "\n" : "") + line.slice(5).trimStart();
        }
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
