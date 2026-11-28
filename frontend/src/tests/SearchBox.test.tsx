import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import SearchBox, { hitHref } from "../components/SearchBox";
import { fail, mockServer } from "./helpers";

const H = [{ doctype: "Customer", name: "CUST-0001", title: "Acme Ltd" }, { doctype: "Customer", name: "CUST-0002", title: "Acme Foods" }, { doctype: "Sales Order", name: "SO-0007", title: "SO-0007" }];
beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "alice@acme.ng", roles: "Sales User" }); window.location.hash = ""; });
const box = () => screen.getByRole("combobox", { name: "Search" }) as HTMLInputElement;
const type = (v: string) => fireEvent.change(box(), { target: { value: v } });
const searches = (calls: { key: string; url: URL }[]) => calls.filter((c) => c.key === "GET /api/search");

describe("hitHref", () => { it("links to the document, encoding awkward names", () => { expect(hitHref({ doctype: "Sales Order", name: "SO 1/2" })).toBe("#/app/Sales%20Order/SO%201%2F2"); }); });

describe("SearchBox", () => {
  it("waits for a pause in typing, then sends ONE request with the trimmed, encoded query", async () => {
    const calls = mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={40} />);
    type("a"); type("ac"); type("acm"); type("  acme & co ");
    await screen.findAllByRole("option");
    expect(searches(calls)).toHaveLength(1);
    const u = searches(calls)[0].url;
    expect(u.searchParams.get("q")).toBe("acme & co");
    expect(u.searchParams.get("limit")).toBe("12");
  });

  it("keeps waiting while you are still typing: a pause shorter than the delay does not trigger a search", async () => {
    const calls = mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={120} />);
    type("ac");
    await new Promise((r) => setTimeout(r, 50));                                                       // a pause, but shorter than the delay
    type("acme");
    await new Promise((r) => setTimeout(r, 50));
    expect(searches(calls)).toHaveLength(0);                                                           // still nothing sent
    await screen.findAllByRole("option");
    expect(searches(calls)).toHaveLength(1);
    expect(searches(calls)[0].url.searchParams.get("q")).toBe("acme");                                 // and only for what you finished typing
  });

  it("does not search for fewer than 2 characters or only spaces, and clears old results", async () => {
    const calls = mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    type("a"); type("   ");
    await new Promise((r) => setTimeout(r, 40));
    expect(searches(calls)).toHaveLength(0);
    type("acme");
    await screen.findAllByRole("option");
    type("a");
    await waitFor(() => expect(screen.queryAllByRole("option")).toHaveLength(0));
  });

  it("groups the results by DocType and shows the name beside a title (not when they are the same)", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    type("acme");
    await screen.findAllByRole("option");
    expect(screen.getByRole("group", { name: "Customer" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Sales Order" })).toBeTruthy();
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByText("CUST-0001")).toBeTruthy();
    expect(screen.getAllByText("SO-0007")).toHaveLength(1);                                           // title === name: shown once
    expect(screen.getAllByRole("option")[0].getAttribute("href")).toBe("#/app/Customer/CUST-0001");
  });

  it("arrow keys move the highlight, Enter opens that document and closes and clears the box", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    type("acme");
    await screen.findAllByRole("option");
    expect(screen.getAllByRole("option")[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });                                                    // stops at the last one
    expect(screen.getAllByRole("option")[2].getAttribute("aria-selected")).toBe("true");
    expect(box().getAttribute("aria-activedescendant")).toBe(screen.getAllByRole("option")[2].id);
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(window.location.hash).toBe("#/app/Customer/CUST-0002");
    expect(box().value).toBe("");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("clicking a result opens it", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    type("acme");
    fireEvent.click((await screen.findAllByRole("option"))[2]);
    expect(window.location.hash).toBe("#/app/Sales%20Order/SO-0007");
  });

  it("Escape closes the list first, then clears the text", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    type("acme");
    await screen.findAllByRole("option");
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box().value).toBe("acme");
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(box().value).toBe("");
  });

  it("Ctrl+K (or Cmd+K) focuses the box from anywhere", () => {
    mockServer({});
    render(<SearchBox />);
    expect(document.activeElement).not.toBe(box());
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    expect(document.activeElement).toBe(box());
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document, { key: "K", metaKey: true });
    expect(document.activeElement).toBe(box());
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document, { key: "k" });                                                          // a plain k does nothing
    expect(document.activeElement).not.toBe(box());
  });

  it("only the LATEST search may update the screen (a slow, older answer is ignored)", async () => {
    let release!: () => void;
    const slow = new Promise<void>((r) => { release = r; });
    mockServer({ "GET /api/search": async ({ url }: any) => { if (url.searchParams.get("q") === "ac") { await slow; return [{ doctype: "Customer", name: "OLD", title: "Stale result" }]; } return [{ doctype: "Customer", name: "NEW", title: "Fresh result" }]; } });
    render(<SearchBox delayMs={5} />);
    type("ac");
    await new Promise((r) => setTimeout(r, 30));
    type("acme");
    await screen.findByText("Fresh result");
    await act(async () => { release(); await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.queryByText("Stale result")).toBeNull();
    expect(screen.getByText("Fresh result")).toBeTruthy();
  });

  it("says when nothing matches, quoting what was typed", async () => {
    mockServer({ "GET /api/search": () => [] });
    render(<SearchBox delayMs={5} />);
    type("zzzz");
    expect(await screen.findByText(/No matching records for “zzzz”/)).toBeTruthy();
  });

  it("shows the server's reason when search fails, and recovers on the next try", async () => {
    let n = 0;
    mockServer({ "GET /api/search": () => (++n === 1 ? fail(500, "Boom", "The search service is down") : H) });
    render(<SearchBox delayMs={5} />);
    type("acme");
    expect((await screen.findByRole("alert")).textContent).toContain("The search service is down");
    type("acme foods");
    await screen.findAllByRole("option");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the search box visible and explains a missing search endpoint (404)", async () => {
    mockServer({ "GET /api/search": () => fail(404, "DoesNotExist", "Search is not installed") });
    const { container } = render(<SearchBox delayMs={5} />);
    type("acme");
    expect((await screen.findByRole("alert")).textContent).toContain("Search service is unavailable");
    expect(container.querySelector(".search")).not.toBeNull();
  });

  it("is a proper combobox for assistive technology", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<SearchBox delayMs={5} />);
    expect(box().getAttribute("aria-expanded")).toBe("false");
    expect(box().getAttribute("aria-autocomplete")).toBe("list");
    type("acme");
    await screen.findAllByRole("option");
    expect(box().getAttribute("aria-expanded")).toBe("true");
    expect(box().getAttribute("aria-controls")).toBe(screen.getByRole("listbox").id);
  });

  it("clicking elsewhere closes the list", async () => {
    mockServer({ "GET /api/search": () => H });
    render(<div><SearchBox delayMs={5} /><button>elsewhere</button></div>);
    type("acme");
    await screen.findAllByRole("option");
    fireEvent.mouseDown(screen.getByText("elsewhere"));
    expect(screen.queryByRole("listbox")).toBeNull();
  });
});

describe("in the app shell", () => {
  it("the search box sits in the top bar next to the bell", async () => {
    mockServer({ "GET /api/search": () => [], "GET /api/notifications": () => ({ items: [], unread: 0, total: 0 }) });
    const { default: App } = await import("../App");
    await act(async () => { render(<App />); });
    expect(await screen.findByRole("combobox", { name: "Search" })).toBeTruthy();
  });
});
