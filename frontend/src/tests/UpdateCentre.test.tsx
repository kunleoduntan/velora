import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import UpdateCentre from "../components/UpdateCentre";
import * as apiMod from "../api";

const base = { drop_folder: "/srv/velora/workspace/updates", current: { velora: "1.4.2", apps: { velora_erp: "2.78.0" } }, running: null, last: null, restart_command: "" };

describe("UpdateCentre", () => {
  beforeEach(() => { vi.restoreAllMocks(); });
  it("shows a new-update notice, lists the newer wheel and runs the update after confirmation", async () => {
    vi.spyOn(apiMod.updateCentre, "state").mockResolvedValue({ ...base, update_available: true, files: [{ file: "velora-1.6.7-py3-none-any.whl", package: "velora", version: "1.6.7", installed: "1.4.2", newer: true, note: "" }] } as never);
    const run = vi.spyOn(apiMod.updateCentre, "run").mockResolvedValue({ job: "20261118-120000" });
    render(<UpdateCentre />);
    await screen.findByText("A new update is ready to install.");
    expect(screen.getByText("Newer — will install")).toBeTruthy();
    fireEvent.click(screen.getByText("Install updates"));
    fireEvent.click(await screen.findByText("Yes, install now"));
    await waitFor(() => expect(run).toHaveBeenCalled());
  });
  it("disables Install when nothing is newer", async () => {
    vi.spyOn(apiMod.updateCentre, "state").mockResolvedValue({ ...base, update_available: false, files: [] } as never);
    render(<UpdateCentre />);
    const btn = (await screen.findByText("Install updates")) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByText("The folder is empty.")).toBeTruthy();
  });
  it("shows the steps and log of a failed job, with the reason", async () => {
    vi.spyOn(apiMod.updateCentre, "state").mockResolvedValue({ ...base, update_available: false, files: [],
      last: { id: "20261118-120000", state: "failed", started: "x", error: "Upgrade databases failed (exit 1)", steps: [{ name: "Install new code", state: "done", detail: "" }, { name: "Upgrade databases", state: "running", detail: "" }], log: ["STOPPED: boom"] } } as never);
    render(<UpdateCentre />);
    await screen.findByText("Last update failed");
    expect(screen.getByText("Upgrade databases failed (exit 1)")).toBeTruthy();
  });
});
