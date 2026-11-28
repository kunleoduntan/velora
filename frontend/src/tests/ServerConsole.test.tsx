import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { consoleLock } from "../api";
import ServerConsole from "../components/ServerConsole";
import { fail, mockServer } from "./helpers";

const root = { path: "", can_write: false, entries: [
  { name: "apps", type: "dir", size: null, modified: null, editable: false, can_delete: false },
  { name: "framework", type: "dir", size: null, modified: null, editable: false, can_delete: false, elevated: true } ] };
const framework = { path: "framework", can_write: true, needs_unlock: true, entries: [
  { name: "mod.py", type: "file", size: 6, modified: "2026-01-01T00:00:00+00:00", editable: true, can_delete: false } ] };
afterEach(() => { cleanup(); consoleLock.clear(); vi.unstubAllGlobals(); });

const routes = (over: Record<string, any> = {}) => ({
  "GET /api/filemanager/list": ({ url }: any) => (url.searchParams.get("path") ? framework : root),
  "GET /api/filemanager/read": () => ({ path: "framework/mod.py", content: "X = 1\n", modified: 1, editable: true, needs_unlock: true }),
  "PUT /api/filemanager/write": () => ({ path: "framework/mod.py", modified: 2, size: 6, restart_required: true }),
  "POST /api/console/unlock": () => ({ token: "123.abc", expires_in: 600 }),
  "GET /api/platform/companies": () => [{ id: "COMP-001", name: "Acme", status: "active" }],
  "GET /api/console/db/COMP-001/tables": () => [{ name: "tab_customer", rows: 2, columns: 5 }],
  ...over });

describe("Server console", () => {
  it("asks for the password before saving framework code, then saves and says a restart is needed", async () => {
    const calls = mockServer(routes());
    render(<ServerConsole />);
    fireEvent.click(await screen.findByLabelText("Open folder framework"));
    fireEvent.click(await screen.findByLabelText("Open mod.py"));
    fireEvent.change(await screen.findByLabelText("File contents"), { target: { value: "X = 2\n" } });
    fireEvent.click(screen.getByText("Save"));
    const box = await screen.findByLabelText("Password");                           // locked: it asks, nothing is written yet
    expect(calls.some(c => c.key === "PUT /api/filemanager/write")).toBe(false);
    fireEvent.change(box, { target: { value: "my-password" } });
    fireEvent.click(screen.getAllByText("Unlock").find(b => b.tagName === "BUTTON" && b.closest("[role=dialog]"))!);
    expect(await screen.findByText(/Restart the service/)).toBeTruthy();            // the save went through straight after unlocking
    const write = calls.find(c => c.key === "PUT /api/filemanager/write")!;
    expect(write.headers?.["X-Velora-Elevation"]).toBe("123.abc");
  });

  it("shows a wrong password and stays locked", async () => {
    mockServer(routes({ "POST /api/console/unlock": () => fail(401, "AuthenticationRequired", "That password is not correct") }));
    render(<ServerConsole />);
    fireEvent.click(await screen.findByText("Unlock"));
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getAllByText("Unlock").find(b => b.closest("[role=dialog]"))!);
    expect(await screen.findByText("That password is not correct")).toBeTruthy();
    expect(consoleLock.left()).toBe(0);
  });

  it("runs a read-only query, and gates a changing statement behind preview and unlock", async () => {
    const calls = mockServer(routes({
      "POST /api/console/db/COMP-001/sql": ({ body }: any) => body.mode === "read"
        ? { kind: "read", columns: ["n"], rows: [[2]], truncated: false, seconds: 0.01 }
        : body.mode === "preview" ? { kind: "preview", would_affect: 1, plan: "p.1" } : { kind: "applied", affected: 1 },
      "GET /api/console/db/COMP-001/table/tab_customer": () => ({ structure: { name: "tab_customer", primary_key: ["name"], columns: [], indexes: [] }, data: { columns: ["name"], rows: [["A"]], truncated: false, seconds: 0, total: 1 } }),
    }));
    render(<ServerConsole initialTab="database" />);
    const box = await screen.findByLabelText("SQL statement");
    fireEvent.change(box, { target: { value: "select count(*) as n from tab_customer" } });
    fireEvent.click(screen.getByText("Run"));
    expect(await screen.findByText("2")).toBeTruthy();
    fireEvent.change(box, { target: { value: "delete from tab_customer where name = 'A'" } });
    expect(screen.queryByText("Run")).toBeNull();
    expect((screen.getByText("Apply to the database") as HTMLButtonElement).disabled).toBe(true);     // nothing to apply before a preview
    fireEvent.click(screen.getByText("Preview changes"));
    await screen.findByLabelText("Password");                                                          // preview needs the unlock
    expect(calls.some(c => c.body?.mode === "preview")).toBe(false);
  });
});
