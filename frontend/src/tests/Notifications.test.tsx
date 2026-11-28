import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import NotificationBell, { ago, target } from "../components/NotificationBell";
import NotificationsPage from "../components/NotificationsPage";
import { fail, mockServer } from "./helpers";

const N = (i: number, over: Record<string, unknown> = {}) => ({ name: `N${i}`, subject: `Subject ${i}`, message: `Line one ${i}\nline two`, ref_doctype: "Sales Order", ref_name: `SO-${i}`, priority: "Normal", rule: "r", read: 0, read_on: null, creation: new Date(Date.now() - 5 * 60000).toISOString(), ...over });
beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "alice@acme.ng", roles: "Sales User" }); window.location.hash = ""; });

describe("helpers", () => {
  it("says how long ago, in plain words", () => {
    const now = Date.parse("2026-03-02T12:00:00Z");
    expect(ago("2026-03-02T11:59:40Z", now)).toBe("just now");
    expect(ago("2026-03-02T11:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-03-02T09:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-02-28T12:00:00Z", now)).toBe("2 d ago");
    expect(ago("2026-03-02 11:00:00", Date.parse("2026-03-02T11:30:00"))).toBe("30 min ago");                 // the server's "YYYY-MM-DD HH:MM:SS" form
  });
  it("links to the document, or to the inbox when there is none", () => {
    expect(target({ ref_doctype: "Sales Order", ref_name: "SO 1/2" })).toBe("#/app/Sales%20Order/SO%201%2F2");
    expect(target({ ref_doctype: null, ref_name: null })).toBe("#/notifications");
  });
});

describe("NotificationBell", () => {
  it("renders nothing when notifications are not installed (404)", async () => {
    const calls = mockServer({});
    const { container } = render(<NotificationBell intervalMs={20} />);
    await waitFor(() => expect(calls.some((c) => c.key === "GET /api/notifications")).toBe(true));
    expect(container.querySelector(".notif-bell")).toBeNull();
  });

  it("shows the unread count (capped), and an accessible name that says so", async () => {
    mockServer({ "GET /api/notifications": () => ({ items: [N(1)], unread: 150, total: 200 }) });
    render(<NotificationBell />);
    expect((await screen.findByRole("button", { name: "Notifications, 150 unread" })).textContent).toContain("99+");
  });

  it("no badge and a plain name when everything is read", async () => {
    mockServer({ "GET /api/notifications": () => ({ items: [N(1, { read: 1 })], unread: 0, total: 1 }) });
    const { container } = render(<NotificationBell />);
    await screen.findByRole("button", { name: "Notifications" });
    expect(container.querySelector(".notif-badge")).toBeNull();
  });

  it("refreshes by itself, and keeps the last good state if a refresh fails", async () => {
    let n = 1, calls = 0;
    mockServer({ "GET /api/notifications": () => { calls += 1; if (calls === 3) return fail(500, "Boom", "server error"); return { items: [], unread: n, total: n }; } });
    render(<NotificationBell intervalMs={30} />);
    await screen.findByRole("button", { name: "Notifications, 1 unread" });
    n = 4;
    await screen.findByRole("button", { name: "Notifications, 4 unread" });
    await waitFor(() => expect(calls).toBeGreaterThanOrEqual(4));                                                 // the failing call did not blank the bell
    expect(screen.getByRole("button", { name: /Notifications, 4 unread/ })).toBeTruthy();
  });

  it("opens a list: unread ones stand out, the first message line is shown, urgent ones are marked", async () => {
    mockServer({ "GET /api/notifications": () => ({ items: [N(1), N(2, { read: 1 }), N(3, { priority: "Urgent" })], unread: 2, total: 3 }) });
    const { container } = render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: /Notifications/ }));
    expect(container.querySelectorAll(".notif-item")).toHaveLength(3);
    expect(container.querySelectorAll(".notif-item.unread")).toHaveLength(2);
    expect(container.querySelectorAll(".notif-item.urgent")).toHaveLength(1);
    expect(screen.getAllByText("Line one 1")).toHaveLength(1);
    expect(screen.queryByText(/line two/)).toBeNull();
    expect(screen.getAllByText("5 min ago").length).toBe(3);
    expect(screen.getByRole("link", { name: "See all and settings" }).getAttribute("href")).toBe("#/notifications");
  });

  it("clicking one marks it read, refreshes the count, closes the list and goes to the document", async () => {
    let unread = 2;
    const calls = mockServer({ "GET /api/notifications": () => ({ items: [N(1), N(2)], unread, total: 2 }), "POST /api/notifications/N1/read": () => { unread = 1; return { read: "N1" }; } });
    render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications, 2 unread" }));
    fireEvent.click(screen.getByText("Subject 1"));
    await screen.findByRole("button", { name: "Notifications, 1 unread" });
    expect(calls.some((c) => c.key === "POST /api/notifications/N1/read")).toBe(true);
    expect(window.location.hash).toBe("#/app/Sales%20Order/SO-1");
    expect(screen.queryByText("See all and settings")).toBeNull();
  });

  it("clicking an already-read one does not call the server to mark it", async () => {
    const calls = mockServer({ "GET /api/notifications": () => ({ items: [N(1, { read: 1 })], unread: 0, total: 1 }) });
    render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    fireEvent.click(screen.getByText("Subject 1"));
    expect(calls.some((c) => c.key.includes("/read"))).toBe(false);
  });

  it("'Mark all read' is disabled with nothing unread, and works otherwise", async () => {
    let unread = 3;
    mockServer({ "GET /api/notifications": () => ({ items: [N(1)], unread, total: 3 }), "POST /api/notifications/read-all": () => { unread = 0; return { marked: 3 }; } });
    render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: /3 unread/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await screen.findByRole("button", { name: "Notifications" });                                                  // the count refreshed to zero; the list stays open
    await waitFor(() => expect((screen.getByRole("button", { name: "Mark all read" }) as HTMLButtonElement).disabled).toBe(true));
  });

  it("says so when there is nothing", async () => {
    mockServer({ "GET /api/notifications": () => ({ items: [], unread: 0, total: 0 }) });
    render(<NotificationBell />);
    fireEvent.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(screen.getByText("You are all caught up.")).toBeTruthy();
  });
});

describe("NotificationsPage", () => {
  const prefs = { email_enabled: true, quiet_start: null, quiet_end: null, digest: "Immediately", muted_rules: [] };
  const setup = (extra: Record<string, any> = {}) => {
    const calls = mockServer({ "GET /api/notifications": ({ url }: any) => ({ items: url.searchParams.get("unread") === "1" ? [N(1)] : [N(1), N(2, { read: 1 })], unread: 1, total: 2 }),
      "GET /api/notification-preferences": () => prefs, ...extra });
    render(<NotificationsPage />);
    return calls;
  };

  it("lists notifications and filters to the unread ones", async () => {
    const calls = setup();
    await screen.findByText("Subject 2");
    expect(screen.getByText("1 unread")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Unread" }));
    await waitFor(() => expect(screen.queryByText("Subject 2")).toBeNull());
    expect(calls.filter((c) => c.key === "GET /api/notifications").at(-1)!.url.searchParams.get("unread")).toBe("1");
    expect(screen.getByRole("button", { name: "Unread" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("loads more pages without losing the ones already shown", async () => {
    const calls = setup({ "GET /api/notifications": ({ url }: any) => { const off = Number(url.searchParams.get("offset")); return { items: [N(off + 1), N(off + 2)], unread: 4, total: 4 }; } });
    await screen.findByText("Subject 1");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("Subject 3");
    expect(screen.getAllByText(/^Subject \d$/)).toHaveLength(4);
    expect(calls.filter((c) => c.key === "GET /api/notifications").at(-1)!.url.searchParams.get("offset")).toBe("2");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();                                         // everything is loaded
  });

  it("marks one read when you open it, and everything read on request", async () => {
    const calls = setup({ "POST /api/notifications/N1/read": () => ({ read: "N1" }), "POST /api/notifications/read-all": () => ({ marked: 1 }) });
    await screen.findByText("Subject 1");
    fireEvent.click(screen.getByRole("link", { name: "Subject 1" }));
    expect(calls.some((c) => c.key === "POST /api/notifications/N1/read")).toBe(true);
    fireEvent.click(screen.getByRole("link", { name: "Subject 2" }));
    expect(calls.some((c) => c.key === "POST /api/notifications/N2/read")).toBe(false);                             // N2 was already read
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/notifications/read-all")).toBe(true));
  });

  it("saves my settings exactly as set (muted rules as a clean list)", async () => {
    const calls = setup({ "PUT /api/notification-preferences": () => ({ saved: true }) });
    await screen.findByLabelText("Quiet hours start");
    fireEvent.click(screen.getByLabelText("Send me email"));
    fireEvent.change(screen.getByLabelText("Email me"), { target: { value: "Daily digest" } });
    fireEvent.change(screen.getByLabelText("Quiet hours start"), { target: { value: "22:00" } });
    fireEvent.change(screen.getByLabelText("Quiet hours end"), { target: { value: "07:30" } });
    fireEvent.change(screen.getByLabelText(/Muted rules/), { target: { value: "a\nb" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(calls.find((c) => c.key === "PUT /api/notification-preferences")!.body).toEqual({ email_enabled: false, quiet_start: "22:00", quiet_end: "07:30", digest: "Daily digest", muted_rules: ["a", "b"] });
  });

  it("refuses bad quiet hours in the browser, without calling the server", async () => {
    const calls = setup({ "PUT /api/notification-preferences": () => ({ saved: true }) });
    await screen.findByLabelText("Quiet hours start");
    fireEvent.change(screen.getByLabelText("Quiet hours start"), { target: { value: "25:00" } });
    fireEvent.change(screen.getByLabelText("Quiet hours end"), { target: { value: "07:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect((await screen.findByRole("alert")).textContent).toContain("HH:MM");
    fireEvent.change(screen.getByLabelText("Quiet hours start"), { target: { value: "22:00" } });
    fireEvent.change(screen.getByLabelText("Quiet hours end"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("both a start and an end"));
    expect(calls.some((c) => c.key === "PUT /api/notification-preferences")).toBe(false);
  });

  it("shows the server's reason if saving is refused", async () => {
    setup({ "PUT /api/notification-preferences": () => fail(422, "ValidationError", "Digest must be Immediately, Hourly digest or Daily digest") });
    await screen.findByLabelText("Quiet hours start");
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Digest must be");
  });
});

describe("in the app shell", () => {
  it("the bell appears next to the other header controls and the inbox route opens", async () => {
    window.location.hash = "#/notifications";
    mockServer({ "GET /api/notifications": () => ({ items: [N(1)], unread: 1, total: 1 }), "GET /api/notification-preferences": () => ({ email_enabled: true, quiet_start: null, quiet_end: null, digest: "Immediately", muted_rules: [] }) });
    const { default: App } = await import("../App");
    await act(async () => { render(<App />); });
    expect(await screen.findByRole("heading", { name: "Notifications" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Notifications, 1 unread" })).toBeTruthy();
  });
});
