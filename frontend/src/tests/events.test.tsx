import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import NotificationBell from "../components/NotificationBell";
import { createParser, subscribeEvents } from "../events";

const enc = new TextEncoder();

/** A controllable event stream: push() chunks, end() to close it. */
function fakeStream() {
  let ctl!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(c) { ctl = c; } });
  return { response: () => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }), push: (s: string) => ctl.enqueue(enc.encode(s)), end: () => ctl.close() };
}
const flush = () => new Promise((r) => setTimeout(r, 15));
beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "alice@acme.ng", roles: "Sales User" }); });
afterEach(() => vi.unstubAllGlobals());

describe("createParser", () => {
  const collect = () => { const out: [string, string][] = []; return { out, parse: createParser((e, d) => out.push([e, d])) }; };
  it("parses events, ignores comments, and handles several per chunk", () => {
    const { out, parse } = collect();
    parse(": ping\n\nevent: notification\ndata: {\"kind\":\"notification\"}\n\nevent: read\ndata: {}\n\n");
    expect(out).toEqual([["notification", '{"kind":"notification"}'], ["read", "{}"]]);
  });
  it("copes with an event split anywhere across chunks, even inside a line", () => {
    const { out, parse } = collect();
    for (const piece of ["event: no", "tification\nda", "ta: {}\n", "\nevent: re", "ad\ndata: x\n\n"]) parse(piece);
    expect(out).toEqual([["notification", "{}"], ["read", "x"]]);
  });
  it("accepts CRLF line endings, a missing space after the colon, multi-line data and unknown fields", () => {
    const { out, parse } = collect();
    parse("event:ready\r\ndata:a\r\ndata: b\r\nid: 7\r\nretry: 3000\r\n\r\n");
    expect(out).toEqual([["ready", "a\nb"]]);
  });
  it("holds back an incomplete event until its blank line arrives", () => {
    const { out, parse } = collect();
    parse("event: notification\ndata: {}\n");
    expect(out).toEqual([]);
    parse("\n");
    expect(out).toHaveLength(1);
  });
});

describe("subscribeEvents", () => {
  it("reports ready, delivers known events and ignores unknown ones", async () => {
    const s = fakeStream();
    vi.stubGlobal("fetch", vi.fn(async () => s.response()));
    const events: string[] = [], states: boolean[] = [];
    const stop = subscribeEvents((e) => events.push(e), (c) => states.push(c));
    s.push("retry: 3000\n\nevent: ready\ndata: {}\n\n");
    await waitFor(() => expect(states).toEqual([true]));
    s.push("event: notification\ndata: {}\n\nevent: weird\ndata: {}\n\nevent: read\ndata: {}\n\nevent: resync\ndata: {}\n\n");
    await waitFor(() => expect(events).toEqual(["notification", "read", "resync"]));
    stop();
  });

  it("sends the Desk's own authentication headers", async () => {
    const s = fakeStream();
    const f = vi.fn(async () => s.response());
    vi.stubGlobal("fetch", f);
    const stop = subscribeEvents(() => {}, () => {});
    await waitFor(() => expect(f).toHaveBeenCalled());
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/events");
    expect((init.headers as Record<string, string>)["X-Velora-User"]).toBe("alice@acme.ng");
    stop();
  });

  it("reconnects after the stream ends, with a growing delay that resets once it is live again", async () => {
    let n = 0; const streams: ReturnType<typeof fakeStream>[] = [];
    vi.stubGlobal("fetch", vi.fn(async () => { n += 1; if (n === 3) throw new TypeError("network down"); const s = fakeStream(); streams.push(s); return s.response(); }));
    const states: boolean[] = [];
    const stop = subscribeEvents(() => {}, (c) => states.push(c), { retryMs: 10, maxRetryMs: 40 });
    streams[0].push("event: ready\ndata: {}\n\n");
    await waitFor(() => expect(states).toEqual([true]));
    streams[0].end();                                                                                      // the server went away
    await waitFor(() => expect(states).toEqual([true, false]));
    await waitFor(() => expect(streams.length).toBe(2));                                                   // it came back by itself
    streams[1].push("event: ready\ndata: {}\n\n");
    await waitFor(() => expect(states).toEqual([true, false, true]));
    streams[1].end();
    await waitFor(() => expect(n).toBeGreaterThanOrEqual(4));                                              // attempt 3 failed on the network; it kept trying and got through
    stop();
  });

  it("backs off 1x, 2x, 4x ... up to the maximum while the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("down"); }));
    const delays: number[] = [];
    const stop = subscribeEvents(() => {}, () => {}, { retryMs: 3, maxRetryMs: 12, onRetry: (d) => delays.push(d) });
    await waitFor(() => expect(delays.length).toBeGreaterThanOrEqual(5));
    expect(delays.slice(0, 5)).toEqual([3, 6, 12, 12, 12]);
    stop();
  });

  it.each([[401], [403], [404]])("gives up for good on %i and never retries", async (status) => {
    const f = vi.fn(async () => new Response("{}", { status }));
    vi.stubGlobal("fetch", f);
    const states: boolean[] = [];
    subscribeEvents(() => {}, (c) => states.push(c), { retryMs: 5 });
    await waitFor(() => expect(states).toEqual([false]));
    await new Promise((r) => setTimeout(r, 60));
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("keeps trying on 429 (too many connections) and on server errors", async () => {
    const f = vi.fn(async () => new Response("{}", { status: f.mock.calls.length < 3 ? 429 : 500 }));
    vi.stubGlobal("fetch", f);
    const stop = subscribeEvents(() => {}, () => {}, { retryMs: 5, maxRetryMs: 10 });
    await waitFor(() => expect(f.mock.calls.length).toBeGreaterThanOrEqual(4));
    stop();
  });

  it("stopping aborts the request and delivers nothing afterwards", async () => {
    const s = fakeStream();
    const f = vi.fn(async (_u: string, _i?: RequestInit) => s.response());
    vi.stubGlobal("fetch", f);
    const events: string[] = [];
    const stop = subscribeEvents((e) => events.push(e), () => {}, { retryMs: 5 });
    await waitFor(() => expect(f).toHaveBeenCalled());
    stop();
    expect((f.mock.calls[0][1] as RequestInit).signal!.aborted).toBe(true);
    s.push("event: notification\ndata: {}\n\n");
    await flush();
    expect(events).toEqual([]);
    expect(f).toHaveBeenCalledTimes(1);                                                                    // and it does not reconnect
  });
});

describe("the bell is live", () => {
  const item = { name: "N1", subject: "Hello", message: null, ref_doctype: null, ref_name: null, priority: "Normal", rule: null, read: 0, read_on: null, creation: new Date().toISOString() };
  function setup(unreadRef: { n: number }) {
    const s = fakeStream(); let listCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/events") return s.response();
      if (url.startsWith("/api/notifications")) { listCalls += 1; return new Response(JSON.stringify({ data: { items: [item], unread: unreadRef.n, total: unreadRef.n } }), { status: 200 }); }
      return new Response("{}", { status: 404 });
    }));
    return { s, calls: () => listCalls };
  }

  it("updates the count the moment an event arrives, without waiting for the poll", async () => {
    const unread = { n: 1 };
    const { s, calls } = setup(unread);
    render(<NotificationBell intervalMs={60000} liveIntervalMs={60000} />);
    await screen.findByRole("button", { name: "Notifications, 1 unread" });
    const before = calls();
    s.push("event: ready\ndata: {}\n\n");
    await waitFor(() => expect(calls()).toBeGreaterThan(before));                                          // connecting refetches once; let that settle first, so it cannot mask the event
    await flush();
    unread.n = 5;
    s.push("event: notification\ndata: {}\n\n");
    await screen.findByRole("button", { name: "Notifications, 5 unread" });                              // 60 s polling would never have shown this in time
  });

  it("another tab marking things read updates this tab too", async () => {
    const unread = { n: 3 };
    const { s, calls } = setup(unread);
    render(<NotificationBell intervalMs={60000} liveIntervalMs={60000} />);
    await screen.findByRole("button", { name: "Notifications, 3 unread" });
    const before = calls();
    s.push("event: ready\ndata: {}\n\n");
    await waitFor(() => expect(calls()).toBeGreaterThan(before));
    await flush();
    unread.n = 0;
    s.push("event: read\ndata: {}\n\n");
    await screen.findByRole("button", { name: "Notifications" });
  });

  it("polls quickly when there is no live connection and slowly when there is", async () => {
    const unread = { n: 1 };
    const { s, calls } = setup(unread);
    render(<NotificationBell intervalMs={30} liveIntervalMs={100000} />);
    await screen.findByRole("button", { name: /Notifications/ });
    const before = calls();
    await waitFor(() => expect(calls()).toBeGreaterThan(before + 2));                                      // not live: fast polling
    await act(async () => { s.push("event: ready\ndata: {}\n\n"); await flush(); });
    const live = calls();
    await new Promise((r) => setTimeout(r, 200));
    expect(calls() - live).toBeLessThanOrEqual(1);                                                         // live: the poll is only a slow safety net
  });

  it("refetches when it reconnects, because events during the gap are gone", async () => {
    const unread = { n: 1 };
    const { s, calls } = setup(unread);
    render(<NotificationBell intervalMs={100000} liveIntervalMs={100000} />);
    await screen.findByRole("button", { name: /Notifications/ });
    const before = calls();
    s.push("event: ready\ndata: {}\n\n");
    await waitFor(() => expect(calls()).toBeGreaterThan(before));
  });

  it("clicking still works while live", async () => {
    const unread = { n: 1 };
    setup(unread);
    render(<NotificationBell intervalMs={60000} liveIntervalMs={60000} />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 1 unread" }));
    expect(screen.getByText("Hello")).toBeTruthy();
  });
});
