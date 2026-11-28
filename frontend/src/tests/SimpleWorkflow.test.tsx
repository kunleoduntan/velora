import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as apiMod from "../api";
import SimpleWorkflow, { isSimple, pickStateField, quickApproval } from "../components/SimpleWorkflow";
import { checkWorkflow } from "../components/WorkflowBuilder";
import type { Workflow } from "../components/WorkflowBuilder";

beforeEach(() => {
  vi.spyOn(apiMod.api, "knownRoles").mockResolvedValue(["System Manager", "Finance Manager"]);
  vi.spyOn(apiMod.api, "meta").mockResolvedValue({ fields: [{ fieldname: "workflow_status", label: "Workflow Status", fieldtype: "Select" }, { fieldname: "total", fieldtype: "Currency" }] } as never);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("simple workflow tables", () => {
  it("starts with a sensible approval and saves exactly what the two tables say", async () => {
    const save = vi.spyOn(apiMod.api, "saveWorkflow").mockResolvedValue({});
    const onSaved = vi.fn();
    render(<SimpleWorkflow workflows={[]} selectedDoctype="Purchase Invoice" onSaved={onSaved} onAdvanced={() => undefined} />);
    await waitFor(() => expect((screen.getByLabelText("Status field") as HTMLSelectElement).value).toBe("workflow_status"));
    fireEvent.change(screen.getByLabelText("Transition 2 who"), { target: { value: "Finance Manager" } });
    fireEvent.change(screen.getByLabelText("Transition 2 button"), { target: { value: "Sign off" } });
    fireEvent.click(screen.getByRole("button", { name: "Save workflow" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const body = save.mock.calls[0][0] as any;
    expect(body).toMatchObject({ doctype: "Purchase Invoice", initial_state: "Draft", state_field: "workflow_status", enabled: true });
    expect(body.transitions[1]).toMatchObject({ action: "Sign off", from_state: "Pending Approval", to_state: "Approved", roles: ["Finance Manager"], anyone: false });
    expect(body.transitions[0]).toMatchObject({ anyone: true, roles: [] });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
  it("renaming a state follows through every transition, and removing one removes its transitions", async () => {
    render(<SimpleWorkflow workflows={[]} selectedDoctype="X" onSaved={() => undefined} onAdvanced={() => undefined} />);
    fireEvent.change(screen.getByLabelText("State 2 name"), { target: { value: "Manager Check" } });
    expect((screen.getByLabelText("Transition 1 to") as HTMLSelectElement).value).toBe("Manager Check");
    fireEvent.click(screen.getByRole("button", { name: "Remove Rejected" }));
    expect(screen.queryByLabelText("Transition 3 who")).toBeNull();
  });
  it("tells you what to fix instead of saving a broken flow", async () => {
    const save = vi.spyOn(apiMod.api, "saveWorkflow").mockResolvedValue({});
    render(<SimpleWorkflow workflows={[]} selectedDoctype="X" onSaved={() => undefined} onAdvanced={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove transition 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save workflow" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/reached|way out|transition/i);
    expect(save).not.toHaveBeenCalled();
  });
  it("sends advanced workflows to the advanced designer instead of flattening them", () => {
    const adv: Workflow = { name: "A", doctype: "X", initial_state: "Draft", states: [{ name: "Draft" }, { name: "Done", is_final: true }], transitions: [{ action: "Go", from_state: "Draft", to_state: "Done", roles: ["A", "B"], users: [], approval_mode: "single", required_approvals: 1, conditions: [] }] };
    expect(isSimple(adv)).toBe(false);
    const go = vi.fn();
    render(<SimpleWorkflow workflows={[adv]} selectedDoctype="X" onSaved={() => undefined} onAdvanced={go} />);
    fireEvent.click(screen.getByRole("button", { name: "Open advanced designer" }));
    expect(go).toHaveBeenCalled();
  });
});


describe("quick approval and the state field", () => {
  it("never picks a business status such as Document Status; prefers the approval field, then the built-in Workflow State", () => {
    expect(pickStateField([{ fieldname: "document_status" }, { fieldname: "workflow_state" }])).toBe("workflow_state");
    expect(pickStateField([{ fieldname: "document_status" }, { fieldname: "approval_status" }, { fieldname: "workflow_state" }])).toBe("approval_status");
    expect(pickStateField([{ fieldname: "document_status" }])).toBe("");
  });
  it("builds a valid one- or two-step approval in which the raiser cannot approve", () => {
    for (const second of ["", "Finance Manager"]) {
      const q = quickApproval("Accountant", second);
      expect(checkWorkflow(q.initial, q.states, q.transitions)).toEqual([]);
      expect(q.states.find((s) => s.name === "Approved")).toMatchObject({ allows_submit: true });
      expect(q.transitions.filter((t) => t.action !== "Send for approval" && t.action !== "Reopen for correction").every((t) => t.prevent_self_approval)).toBe(true);
    }
    expect(quickApproval("Accountant", "Finance Manager").transitions.find((t) => t.action === "Final approve")?.roles).toEqual(["Finance Manager"]);
  });
  it("the Quick approval row fills the tables and saves them", async () => {
    const save = vi.spyOn(apiMod.api, "saveWorkflow").mockResolvedValue({});
    render(<SimpleWorkflow workflows={[]} selectedDoctype="Purchase Invoice" onSaved={() => undefined} onAdvanced={() => undefined} />);
    await waitFor(() => expect(screen.getAllByRole("option", { name: "Finance Manager" }).length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("First approver"), { target: { value: "Finance Manager" } });
    fireEvent.click(screen.getByRole("button", { name: "Fill the tables" }));
    fireEvent.click(screen.getByRole("button", { name: "Save workflow" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const body = save.mock.calls[0][0] as any;
    expect(body.transitions.find((t: any) => t.action === "Approve")).toMatchObject({ roles: ["Finance Manager"], prevent_self_approval: true });
  });
});
