import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as apiMod from "../api";
import WorkflowBuilder, { checkWorkflow, layout, PRESETS } from "../components/WorkflowBuilder";

const META = { fields: [{ fieldname: "approval_status", label: "Approval Status", fieldtype: "Select" }, { fieldname: "grand_total", label: "Grand Total", fieldtype: "Currency" }] };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(apiMod.api, "doctypes").mockResolvedValue([{ name: "Purchase Invoice", module: "Finance" }] as never);
  vi.spyOn(apiMod.api, "meta").mockResolvedValue(META as never);
  vi.spyOn(apiMod.api, "knownRoles").mockResolvedValue(["Finance Manager", "System Manager"]);
});

describe("checking a workflow", () => {
  it("accepts every preset", () => {
    for (const p of Object.values(PRESETS)) { const w = p.build("X"); expect(checkWorkflow(w.initial_state, w.states, w.transitions)).toEqual([]); }
  });
  it("reports unreachable states, dead ends, nobody assigned and duplicate names", () => {
    const w = PRESETS.single.build("X");
    const states = [...w.states, { name: "Island" }, { name: "Draft" }];
    const msgs = checkWorkflow("Draft", states, [...w.transitions, { ...w.transitions[0], anyone: false, roles: [], users: [] }]).join(" | ");
    expect(msgs).toMatch(/different from each other/); expect(msgs).toMatch(/Island.*cannot be reached/); expect(msgs).toMatch(/needs someone/);
  });
  it("lays the states out left to right by distance from the start", () => {
    const w = PRESETS.two.build("X");
    const { pos } = layout(w.initial_state, w.states, w.transitions);
    expect(pos.get("Draft")!.x).toBeLessThan(pos.get("Manager Review")!.x); expect(pos.get("Manager Review")!.x).toBeLessThan(pos.get("Director Review")!.x);
  });
});

describe("the builder", () => {
  it("starts from a preset, lets you change who approves, and saves the whole definition", async () => {
    const save = vi.spyOn(apiMod.api, "saveWorkflow").mockResolvedValue({});
    const onSaved = vi.fn();
    render(<WorkflowBuilder workflows={[]} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText("Applies to"), { target: { value: "Purchase Invoice" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "Approval Status" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "One approver" }));
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Purchase Invoice approval");
    expect((screen.getByLabelText("Keep the state in field") as HTMLSelectElement).value).toBe("approval_status");
    const second = screen.getByRole("group", { name: "Transition 2" });
    const roles = within(second).getByLabelText("Transition 2 roles");
    fireEvent.change(roles, { target: { value: "Finance Manager" } }); fireEvent.keyDown(roles, { key: "Enter" });
    fireEvent.click(screen.getByLabelText("Active: documents follow this workflow"));
    fireEvent.click(screen.getByRole("button", { name: "Save workflow" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const body = save.mock.calls[0][0] as any;
    expect(body).toMatchObject({ name: "Purchase Invoice approval", doctype: "Purchase Invoice", state_field: "approval_status", enabled: true, initial_state: "Draft" });
    expect(body.transitions[1].roles).toEqual(["System Manager", "Finance Manager"]);
    expect(body.states.find((s: any) => s.name === "Approved")).toMatchObject({ allows_submit: true, is_final: true });
    expect(onSaved).toHaveBeenCalled();
  });

  it("builds a condition, a quorum and a parallel group without any JSON", () => {
    render(<WorkflowBuilder workflows={[]} onSaved={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "One approver" }));
    const tr = screen.getByRole("group", { name: "Transition 2" });
    fireEvent.click(within(tr).getByRole("button", { name: "+ Add condition" }));
    expect(within(tr).getByLabelText("Transition 2 condition 1 operator")).toBeTruthy();
    fireEvent.change(within(tr).getByLabelText("Transition 2 approval mode"), { target: { value: "quorum" } });
    expect(within(tr).getByLabelText("Transition 2 approvals needed")).toBeTruthy();
    fireEvent.click(within(tr).getByRole("button", { name: "+ Add group" }));
    expect(within(tr).getByLabelText("Transition 2 group 1 name")).toBeTruthy();
  });

  it("renaming a state follows through every transition that uses it", () => {
    render(<WorkflowBuilder workflows={[]} onSaved={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "One approver" }));
    fireEvent.change(screen.getByLabelText("State 2 name"), { target: { value: "Waiting" } });
    expect((screen.getByLabelText("Transition 1 to") as HTMLSelectElement).value).toBe("Waiting");
    expect((screen.getByLabelText("Transition 2 from") as HTMLSelectElement).value).toBe("Waiting");
  });

  it("refuses to save while something is wrong and says what", async () => {
    const save = vi.spyOn(apiMod.api, "saveWorkflow").mockResolvedValue({});
    render(<WorkflowBuilder workflows={[]} onSaved={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "X" } });
    fireEvent.change(screen.getByLabelText("Applies to"), { target: { value: "Purchase Invoice" } });
    fireEvent.click(screen.getByRole("button", { name: "Save workflow" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/state a new document starts in|at least one transition/);
    expect(save).not.toHaveBeenCalled();
  });
});
