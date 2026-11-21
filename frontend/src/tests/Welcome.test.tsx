import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession, type LifecycleEvent, type WelcomeData } from "../api";
import WelcomePage, { SEEN_KEY, WelcomeGate } from "../components/WelcomePage";
import { fail, mockServer } from "./helpers";

const ev = (over: Partial<LifecycleEvent> = {}): LifecycleEvent => ({ id: "e1", at: new Date(Date.now() - 3 * 60000).toISOString(), kind: "update", title: "Update complete", ok: true, version: "0.9.0", from_version: "0.8.1", to_version: "0.9.0",
  steps: [{ text: "Updated Velora from 0.8.1 to 0.9.0", ok: true }, { text: "Backed up every database first (/srv/b/upgrade-1)", ok: true }, { text: "Restarted the server", ok: true }], ...over });
const W = (over: Partial<WelcomeData> = {}): WelcomeData => ({ product: "Velora", powered_by: "Velora BiZ Solutions", version: "0.9.0", user: "boss@acme.ng", is_admin: true, company: { id: "COMP-001", name: "Acme Ltd" },
  latest: ev(), events: [ev(), ev({ id: "e0", kind: "install", title: "Velora is installed and ready", from_version: undefined, to_version: undefined, steps: [{ text: "Created your workspace", ok: true }] })],
  apps: [{ name: "velora_notify", title: "Notifications", description: "Rules and channels", built_in: true }, { name: "inventory", title: "Inventory", description: "", built_in: false }],
  features: { notifications: true, search: true, accounts: false }, domains: [], host: "localhost", tutorial_url: "/tutorial", platform: true, ...over });
const serve = (w: WelcomeData | (() => unknown)) => mockServer({ "GET /api/welcome": typeof w === "function" ? w : () => w });
beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "boss@acme.ng", roles: "System Manager" }); window.location.hash = "#/welcome"; });
afterEach(() => vi.restoreAllMocks());

describe("WelcomePage", () => {
  it("greets you and says exactly what just happened, step by step", async () => {
    serve(W());
    render(<WelcomePage />);
    expect(await screen.findByRole("heading", { name: "Update complete" })).toBeTruthy();
    expect(screen.getByText("Here is exactly what just happened.")).toBeTruthy();
    const card = within(screen.getByRole("region", { name: "What just happened" }));
    expect(card.getByText("Updated Velora from 0.8.1 to 0.9.0")).toBeTruthy();
    expect(card.getByText("Backed up every database first (/srv/b/upgrade-1)")).toBeTruthy();
    expect(card.getByText("Restarted the server")).toBeTruthy();
    expect(card.getByText(/3 min ago/)).toBeTruthy();
    expect(screen.getAllByText("0.8.1").length).toBeGreaterThan(0);                                              // the version jump is shown in the hero
    expect(screen.getByText("0.9.0", { selector: ".wl-versions span" })).toBeTruthy();
  });

  it("says 'Your system is ready' after an install", async () => {
    serve(W({ latest: ev({ kind: "install", title: "Velora is installed and ready", from_version: undefined, to_version: undefined }) }));
    render(<WelcomePage />);
    expect(await screen.findByRole("heading", { name: "Your system is ready" })).toBeTruthy();
    expect(screen.getByText("Velora is installed. Here is exactly what was set up for you.")).toBeTruthy();
  });

  it("is honest when something failed: it says so, shows the failing step, and offers no celebration", async () => {
    serve(W({ latest: ev({ ok: false, title: "Update failed and was undone", steps: [{ text: "COMP-002 Beta could not be upgraded: column x is missing", ok: false }, { text: "Something failed, so every database and the code were put back exactly as they were", ok: false }] }) }));
    const { container } = render(<WelcomePage />);
    expect(await screen.findByRole("heading", { name: "Something needs your attention" })).toBeTruthy();
    expect(screen.getByText(/COMP-002 Beta could not be upgraded: column x is missing/)).toBeTruthy();
    expect(container.querySelectorAll(".wl-steps li.bad")).toHaveLength(2);
    expect(container.querySelector(".wl-bad")).toBeTruthy();
    expect(screen.getAllByText("Problem:", { exact: false }).length).toBeGreaterThan(0);                         // screen readers hear "Problem:" not just a cross
  });

  it("with nothing recorded yet it still welcomes you and explains where the history will appear", async () => {
    serve(W({ latest: null, events: [] }));
    render(<WelcomePage />);
    expect(await screen.findByRole("heading", { name: "Welcome to Velora" })).toBeTruthy();
    expect(screen.getByText(/Nothing has been recorded yet/)).toBeTruthy();
    expect(screen.getByText(/history of installs, updates and changes will appear here/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Take me to my work" })).toBeTruthy();
  });

  it("opens the full tutorial in a new tab, safely", async () => {
    serve(W());
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<WelcomePage />);
    fireEvent.click(await screen.findByRole("button", { name: /Open the full tutorial/ }));
    expect(open).toHaveBeenCalledWith("/tutorial", "_blank", "noopener");
  });

  it("'Got it' remembers this event and goes to your work; a newer event will show again", async () => {
    serve(W());
    render(<WelcomePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Got it, take me to my work" }));
    expect(localStorage.getItem(SEEN_KEY)).toBe("e1");
    expect(window.location.hash).toBe("#/");
  });

  it("shows the system: version, company, who you are, and which apps are built in", async () => {
    serve(W());
    const { container } = render(<WelcomePage />);
    await screen.findByRole("heading", { name: "Update complete" });
    const sys = within(screen.getByRole("region", { name: "Your system" }));
    expect(sys.getByText("version 0.9.0")).toBeTruthy();
    expect(sys.getByText("Acme Ltd")).toBeTruthy();
    expect(sys.getByText("(COMP-001)")).toBeTruthy();
    expect(sys.getByText("boss@acme.ng · administrator")).toBeTruthy();
    expect(sys.getByText("Notifications · built in")).toBeTruthy();
    expect(sys.getByText("Inventory")).toBeTruthy();
    expect(container.querySelectorAll(".wl-chip.built")).toHaveLength(1);
  });

  it("an administrator gets working links; an ordinary user is told to ask one", async () => {
    serve(W());
    const { unmount } = render(<WelcomePage />);
    const start = within(await screen.findByRole("region", { name: "Start here" }));
    expect(start.getByRole("link", { name: "Open the DocType Creator" }).getAttribute("href")).toBe("#/settings/doctype-creator");
    expect(start.getByRole("link", { name: "Create a notification rule" }).getAttribute("href")).toBe("#/app/Notification Rule");
    unmount();
    serve(W({ is_admin: false }));
    render(<WelcomePage />);
    const s2 = within(await screen.findByRole("region", { name: "Start here" }));
    expect(s2.queryByRole("link", { name: "Open the DocType Creator" })).toBeNull();
    expect(s2.getByText("Ask an administrator to open the DocType Creator.")).toBeTruthy();
    expect(s2.getByText("Notifications are on.")).toBeTruthy();
  });

  it("a feature that is not installed says how to get it instead of showing a dead link", async () => {
    serve(W({ features: { notifications: false, search: false, accounts: false } }));
    render(<WelcomePage />);
    const start = within(await screen.findByRole("region", { name: "Start here" }));
    expect(start.queryByRole("link", { name: "Create a notification rule" })).toBeNull();
    expect(start.getByText("velora install-app velora_notify")).toBeTruthy();
    expect(start.getByText("velora install-app velora_search")).toBeTruthy();
    expect(start.queryByText("Ctrl")).toBeNull();
  });

  it("explains how to add an address with a one-click copy, or shows the addresses you already have", async () => {
    serve(W());
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    const { unmount } = render(<WelcomePage />);
    expect(await screen.findByText("sudo velora domain add erp.yourcompany.com")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(write).toHaveBeenCalledWith("sudo velora domain add erp.yourcompany.com");
    unmount();
    serve(W({ domains: [{ domain: "erp.acme.com", primary: true, tls: true, locked: true }] }));
    render(<WelcomePage />);
    expect(await screen.findByText("erp.acme.com")).toBeTruthy();
    expect(screen.getByText(/Already set:/)).toBeTruthy();
  });

  it("explains the framework in plain language, in sections you can open", async () => {
    serve(W());
    const { container } = render(<WelcomePage />);
    await screen.findByRole("region", { name: "How Velora works" });
    const titles = [...container.querySelectorAll(".wl-explain summary")].map((s) => s.textContent);
    expect(titles).toEqual(["Velora is a framework, not an ERP", "Every company has its own database", "Updating is safe", "Notifications and search", "Built for PostgreSQL"]);
    expect(container.querySelectorAll(".wl-explain[open]")).toHaveLength(0);                                       // closed until you want them
  });

  it("keeps a history, newest first, each openable to see its steps, failures marked", async () => {
    serve(W({ events: [ev(), ev({ id: "x", kind: "uninstall-app", ok: false, title: "Removed the app crm", steps: [{ text: "COMP-002: failed", ok: false }] }), ev({ id: "e0", kind: "install", title: "Velora is installed and ready", steps: [{ text: "Created your workspace", ok: true }] })] }));
    const { container } = render(<WelcomePage />);
    await screen.findByRole("region", { name: "What's new" });
    const items = [...container.querySelectorAll(".wl-timeline > li")];
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain("Updated");
    expect(items[1].textContent).toContain("App removed");
    expect(items[2].textContent).toContain("Installed");
    expect(items[1].classList.contains("bad")).toBe(true);
    expect(items[0].classList.contains("bad")).toBe(false);
  });

  it("always credits Velora BiZ Solutions", async () => {
    serve(W());
    render(<WelcomePage />);
    expect((await screen.findByText("Velora BiZ Solutions")).closest("footer")!.textContent).toBe("Powered by Velora BiZ Solutions");
  });

  it("shows the server's reason if it cannot load, and a loading note first", async () => {
    serve(() => fail(500, "Boom", "The welcome service is down"));
    render(<WelcomePage />);
    expect(screen.getByText(/Loading your welcome page/)).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toContain("The welcome service is down");
  });
});

describe("WelcomeGate (the first-run redirect)", () => {
  const gate = async (w: WelcomeData | (() => unknown), hash: string, seen?: string) => {
    window.location.hash = hash;
    if (seen) localStorage.setItem(SEEN_KEY, seen);
    const calls = serve(w);
    await act(async () => { render(<WelcomeGate />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
    return calls;
  };

  it("opens the welcome page once after something new happened, when you are at the home screen", async () => {
    await gate(W(), "");
    expect(window.location.hash).toBe("#/welcome");
  });
  it("also from '#/' and '#'", async () => {
    await gate(W(), "#/");
    expect(window.location.hash).toBe("#/welcome");
    await gate(W(), "#");
    expect(window.location.hash).toBe("#/welcome");
  });
  it("never again for an event you already dismissed", async () => {
    await gate(W(), "", "e1");
    expect(window.location.hash).toBe("");
  });
  it("shows again for a NEWER event", async () => {
    await gate(W({ latest: ev({ id: "e2" }) }), "", "e1");
    expect(window.location.hash).toBe("#/welcome");
  });
  it("never interrupts what you are doing: not when you are already somewhere else", async () => {
    await gate(W(), "#/app/Customer/CUST-0001");
    expect(window.location.hash).toBe("#/app/Customer/CUST-0001");
  });
  it("does nothing when there is nothing to say, or the page cannot be loaded", async () => {
    await gate(W({ latest: null, events: [] }), "");
    expect(window.location.hash).toBe("");
    await gate(() => fail(404, "NotFound", "nope"), "");
    expect(window.location.hash).toBe("");
    await gate(() => fail(500, "Boom", "down"), "");
    expect(window.location.hash).toBe("");
  });
});

describe("in the app", () => {
  it("the header has a Guide button and the route opens the page", async () => {
    mockServer({ "GET /api/welcome": () => W(), "GET /api/notifications": () => ({ items: [], unread: 0, total: 0 }), "GET /api/search": () => [] });
    window.location.hash = "#/welcome";
    const { default: App } = await import("../App");
    await act(async () => { render(<App />); });
    expect(await screen.findByRole("heading", { name: "Update complete" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Welcome and guide" }).getAttribute("href")).toBe("#/welcome");
  });
  it("the home screen points at the guide", async () => {
    mockServer({ "GET /api/welcome": () => W({ latest: null, events: [] }), "GET /api/notifications": () => ({ items: [], unread: 0, total: 0 }), "GET /api/search": () => [] });
    window.location.hash = "";
    const { default: App } = await import("../App");
    await act(async () => { render(<App />); });
    expect((await screen.findByRole("link", { name: "welcome guide" })).getAttribute("href")).toBe("#/welcome");
  });
});
