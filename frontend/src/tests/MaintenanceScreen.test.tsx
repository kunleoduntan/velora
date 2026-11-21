import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import { api } from "../api";
import App from "../App";
import MaintenanceScreen from "../components/MaintenanceScreen";
import { fail, mockServer } from "./helpers";

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" }); });

describe("MaintenanceScreen", () => {
  it("explains an upgrade in progress and reloads by itself when the server is healthy again", async () => {
    let healthy = false;
    const calls = mockServer({ "GET /api/health": () => (healthy ? { status: "ok" } : fail(503, "Maintenance", "upgrading")) });
    const recovered = vi.fn();
    render(<MaintenanceScreen info={{ kind: "Maintenance", message: "Back in a minute" }} intervalMs={20} onRecovered={recovered} />);
    expect(screen.getByRole("alert").textContent).toContain("Upgrading Velora");
    expect(screen.getByText("Back in a minute")).toBeTruthy();
    await waitFor(() => expect(calls.filter((c) => c.key === "GET /api/health").length).toBeGreaterThanOrEqual(2));
    expect(recovered).not.toHaveBeenCalled();                                              // still upgrading: keep waiting
    healthy = true;
    await waitFor(() => expect(recovered).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 80));
    expect(recovered).toHaveBeenCalledTimes(1);                                            // reloads once, not in a loop
  });

  it("tells people when an administrator must finish an upgrade, and keeps checking through network errors", async () => {
    let n = 0;
    mockServer({ "GET /api/health": () => { n += 1; if (n === 1) throw new TypeError("connection refused"); return { status: "ok" }; } });
    const recovered = vi.fn();
    render(<MaintenanceScreen info={{ kind: "UpgradePending", message: "This database needs an upgrade" }} intervalMs={20} onRecovered={recovered} />);
    expect(screen.getByRole("alert").textContent).toContain("An upgrade is needed");
    expect(screen.getByText(/velora upgrade/)).toBeTruthy();
    await waitFor(() => expect(recovered).toHaveBeenCalled());                              // survived the first failed poll (server restarting)
  });
});

describe("maintenance in the app shell", () => {
  it("a 503 Maintenance/UpgradePending answer anywhere switches the whole app to the upgrade screen", async () => {
    mockServer({ "GET /api/auth/config": () => ({ mode: "developer" }), "GET /api/doctypes": () => fail(503, "Maintenance", "Velora is being upgraded."), "GET /api/health": () => fail(503, "Maintenance", "x") });
    render(<App />);                                                                         // already signed in (developer session)
    expect((await screen.findByRole("alert")).textContent).toContain("Upgrading Velora");
    expect(screen.getByText("Velora is being upgraded.")).toBeTruthy();
    expect(screen.queryByText("Sign out")).toBeNull();
  });

  it("only maintenance answers trigger it (not 403/404/500), and the error is still thrown to the caller", async () => {
    const seen = vi.fn();
    window.addEventListener("velora:maintenance", seen);
    mockServer({ "GET /api/doctypes": () => fail(503, "ServiceUnavailable", "db down"), "GET /api/reports": () => fail(403, "PermissionDenied", "no"), "GET /api/saved-reports": () => fail(503, "UpgradePending", "needs upgrade") });
    await expect(api.doctypes()).rejects.toThrow("db down");
    await expect(api.reports()).rejects.toThrow("no");
    expect(seen).not.toHaveBeenCalled();
    await expect(api.savedReports()).rejects.toThrow("needs upgrade");
    expect(seen).toHaveBeenCalledTimes(1);
    expect((seen.mock.calls[0][0] as CustomEvent).detail).toEqual({ kind: "UpgradePending", message: "needs upgrade" });
    window.removeEventListener("velora:maintenance", seen);
  });
});
