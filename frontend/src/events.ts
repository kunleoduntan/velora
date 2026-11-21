import { raw } from "./api";

export type LiveEvent = "notification" | "read" | "resync";
const KNOWN = new Set<string>(["notification", "read", "resync"]);

/** Parse a server-sent-events byte stream into (event, data) pairs. Handles events split across chunks, CRLF line ends, comments and unknown fields. */
export function createParser(onMessage: (event: string, data: string) => void) {
  let buf = "";
  return (chunk: string) => {
    buf += chunk.replace(/\r\n/g, "\n");
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      let event = "message"; const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;                         // a comment (the server's keep-alive ping)
        const c = line.indexOf(":");
        const field = c < 0 ? line : line.slice(0, c);
        const value = c < 0 ? "" : line.slice(c + 1).replace(/^ /, "");
        if (field === "event") event = value; else if (field === "data") data.push(value);
      }
      if (event !== "message" || data.length) onMessage(event, data.join("\n"));
    }
  };
}

export interface SubscribeOptions { retryMs?: number; maxRetryMs?: number; onRetry?: (delayMs: number) => void }

/**
 * Live events from /api/events with automatic reconnection (1 s, 2 s, 4 s ... up to 30 s). `onState(true)` once the stream is ready, `onState(false)` when it drops.
 * It gives up for good on 401 (signed out), 403 and 404 (notifications not installed); on 429 and network errors it keeps trying slowly. Returns the function that stops it.
 * Uses fetch (not EventSource) so the Desk's normal authentication headers are sent.
 */
export function subscribeEvents(onEvent: (e: LiveEvent) => void, onState: (connected: boolean) => void = () => {}, opts: SubscribeOptions = {}): () => void {
  const ctl = new AbortController();
  const base = opts.retryMs ?? 1000, max = opts.maxRetryMs ?? 30000;
  let stopped = false;

  const wait = (ms: number) => new Promise<void>((resolve) => { const t = setTimeout(resolve, ms); ctl.signal.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true }); });

  (async () => {
    let delay = base;
    while (!stopped) {
      let ready = false;
      try {
        const res = await raw("GET", "/api/events", undefined, ctl.signal);
        if (res.status === 401 || res.status === 403 || res.status === 404) { onState(false); return; }
        if (res.ok && res.body) {
          const parse = createParser((event, data) => {
            if (event === "ready") { ready = true; delay = base; onState(true); }
            else if (KNOWN.has(event) && !stopped) onEvent(event as LiveEvent);
            void data;
          });
          const reader = res.body.getReader(); const dec = new TextDecoder();
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            parse(dec.decode(value, { stream: true }));
          }
        }
      } catch { /* network error or abort: fall through to the retry logic */ }
      if (stopped) return;
      if (ready) onState(false);                                             // we had a live stream and lost it
      opts.onRetry?.(delay);
      await wait(delay);
      delay = Math.min(delay * 2, max);
    }
  })();

  return () => { stopped = true; ctl.abort(); };
}
