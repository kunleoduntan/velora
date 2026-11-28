import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import PeopleAccess from "../components/PeopleAccess";
import { mockServer } from "./helpers";

const OPTS = { profiles: [{ name: "Accountant", roles: ["Accountant"], description: "Prepares invoices" }, { name: "Finance Manager", roles: ["Finance Manager", "Accountant"], description: "Approves" }],
  roles: [{ name: "Accountant", areas: ["Finance"] }, { name: "Finance Manager", areas: ["Finance"] }, { name: "Storekeeper", areas: ["Inventory"] }] };
beforeEach(() => { clearCaches(); setAuthMode("developer"); setProfile(null); setSession({ user: "admin", roles: "System Manager" }); vi.stubGlobal("confirm", () => true); });

describe("People & Access", () => {
  it("adds a person in one step from a profile and shows the one-time password", async () => {
    const calls = mockServer({ "GET /api/people": () => [], "GET /api/people/options": () => OPTS,
      "POST /api/people": ({ body }: any) => ({ email: body.email, full_name: body.full_name, roles: ["Accountant", "Finance Manager"], new_user: true, temporary_password: "Temp-1234-abcd" }) });
    render(<PeopleAccess />);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "ada@x.com" } });
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Ada" } });
    fireEvent.click(await screen.findByLabelText("Finance Manager"));
    expect(screen.getByText(/Roles given: Accountant, Finance Manager/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    expect(await screen.findByText("Temp-1234-abcd")).toBeTruthy();
    const post = calls.find((c) => c.key === "POST /api/people")!;
    expect(post.body).toEqual({ email: "ada@x.com", full_name: "Ada", profiles: ["Finance Manager"], roles: [] });
  });

  it("a refusal shows its advice instead of a bare error", async () => {
    mockServer({ "GET /api/people": () => [], "GET /api/people/options": () => OPTS,
      "POST /api/people": () => new Response(JSON.stringify({ error: "ValidationError", message: "This company has no role 'Acountant' (did you mean 'Accountant'?).",
        advice: { hint: "Pick roles from the list.", actions: [{ label: "Role Permissions", href: "#/settings/permissions" }] } }), { status: 417 }) });
    render(<PeopleAccess />);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "x@x.com" } });
    fireEvent.click(await screen.findByLabelText("Accountant"));
    fireEvent.click(screen.getByRole("button", { name: "Add person" }));
    const box = await screen.findByRole("alert");
    expect(box.textContent).toContain("did you mean 'Accountant'");
    expect(box.textContent).toContain("How to fix it: Pick roles from the list.");
    expect(screen.getByRole("link", { name: "Role Permissions" })).toBeTruthy();
  });

  it("changes a person's roles with tick boxes", async () => {
    const calls = mockServer({ "GET /api/people": () => [{ email: "bo@x.com", full_name: "Bo", is_active: true, last_login: null, roles: ["Accountant"] }],
      "GET /api/people/options": () => OPTS, "POST /api/people/bo@x.com/roles": ({ body }: any) => ({ email: "bo@x.com", roles: body.roles }) });
    render(<PeopleAccess />);
    fireEvent.click(await screen.findByRole("button", { name: "Change access" }));
    const dlg = await screen.findByRole("dialog");
    fireEvent.click(dlg.querySelector('input[aria-label="Storekeeper"]')!);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/people/bo@x.com/roles")).toBe(true));
    expect(calls.find((c) => c.key === "POST /api/people/bo@x.com/roles")!.body).toEqual({ roles: ["Accountant", "Storekeeper"] });
  });
});
