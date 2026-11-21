import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import { resetScripts } from "../clientScripts";
import App from "../App";
import { META, fail, mockServer, reportDef, reportResult, themeState } from "./helpers";

const PROFILE = {
  user: { email: "alice@example.com", full_name: "Alice", is_platform_admin: false },
  companies: [
    { id: "COMP-001", name: "Velora Technologies", tenant: "Enterprise Group", status: "active", roles: ["System Manager"] },
    { id: "COMP-002", name: "Value Impacts Consulting", tenant: "Enterprise Group", status: "active", roles: ["Sales User"] },
    { id: "COMP-003", name: "Dormant Co", tenant: "Enterprise Group", status: "suspended", roles: ["Sales User"] },
  ],
  active_company: null,
};
const ONE = { ...PROFILE, companies: [PROFILE.companies[0]], active_company: "COMP-001" };

beforeEach(() => {
  resetScripts(); localStorage.clear(); sessionStorage.clear();
  setAuthMode("developer"); setProfile(null); setSession(null);
  window.location.hash = "";
});

const platform = (extra: Record<string, any> = {}) => mockServer({
  "GET /api/auth/config": () => ({ mode: "password" }),
  "GET /api/doctypes": () => [{ name: "Customer", module: "CRM", app: "crm", is_submittable: false, can_create: true }],
  "POST /api/auth/switch-company": ({ body }: any) => ({ id: body.company_id, name: "x", roles: [] }),
  "POST /api/auth/logout": () => ({ signed_out: true }),
  ...extra,
});
const doctypeCalls = (calls: any[]) => calls.filter((c) => c.key === "GET /api/doctypes");

describe("App - sign-in and company switching (platform mode)", () => {
  it("shows the sign-in form, reports a wrong password, then signs in and asks which company", async () => {
    let attempts = 0;
    const calls = platform({
      "GET /api/auth/me": () => (attempts < 2 ? fail(401, "AuthenticationRequired", "Sign in required") : PROFILE),
      "POST /api/auth/login": ({ body }: any) => { attempts++; return body.password === "right-password" ? PROFILE : fail(401, "AuthenticationRequired", "Invalid email or password"); },
    });
    render(<App />);
    fireEvent.change(await screen.findByLabelText("Email address"), { target: { value: "alice@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Invalid email or password");
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "right-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Choose a company" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Dormant Co/ }).hasAttribute("disabled")).toBe(true);     // suspended: not selectable
    const logins = calls.filter((c) => c.key === "POST /api/auth/login");
    expect(logins.map((c) => c.body.password)).toEqual(["wrong", "right-password"]);
    expect(doctypeCalls(calls)).toHaveLength(0);                                                          // nothing company-scoped before a company is chosen
  });

  it("picking a company loads ITS DocTypes, sending that company on every request", async () => {
    const calls = platform({ "GET /api/auth/me": () => PROFILE });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Velora Technologies/ }));
    expect(await screen.findByRole("link", { name: "Customer" })).toBeTruthy();
    expect(sessionStorage.getItem("velora.company")).toBe("COMP-001");
    expect(calls.find((c) => c.key === "POST /api/auth/switch-company")!.body).toEqual({ company_id: "COMP-001" });
    const h = ((globalThis.fetch as any).mock.calls.filter((c: any[]) => String(c[0]).includes("/api/doctypes")).at(-1)[1].headers);
    expect(h["X-Velora-Company"]).toBe("COMP-001");
  });

  it("a single-company user goes straight in, and a reload restores the session without a login form", async () => {
    platform({ "GET /api/auth/me": () => ONE });
    render(<App />);
    expect(await screen.findByRole("link", { name: "Customer" })).toBeTruthy();
    expect(screen.queryByLabelText("Password")).toBeNull();
    expect(screen.getByText("alice@example.com")).toBeTruthy();
  });

  it("switches company from the top bar WITHOUT signing in again, refetching DocTypes for the new company", async () => {
    const calls = platform({ "GET /api/auth/me": () => PROFILE });
    window.location.hash = "#/app/Customer";
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /Velora Technologies/ }));
    await screen.findByRole("link", { name: "Customer" });
    const logins = () => calls.filter((c) => c.key === "POST /api/auth/login").length;
    fireEvent.click(screen.getByRole("button", { name: /ACTIVE COMPANY/ }));
    const list = within(screen.getByRole("listbox", { name: "Companies" }));
    expect(list.getByRole("option", { name: /Dormant Co/ }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(list.getByRole("option", { name: /Value Impacts Consulting/ }));
    await waitFor(() => expect(sessionStorage.getItem("velora.company")).toBe("COMP-002"));
    expect(calls.filter((c) => c.key === "POST /api/auth/switch-company").map((c) => c.body.company_id)).toEqual(["COMP-001", "COMP-002"]);
    await waitFor(() => expect(doctypeCalls(calls).length).toBeGreaterThanOrEqual(2));
    const last = ((globalThis.fetch as any).mock.calls.filter((c: any[]) => String(c[0]).includes("/api/doctypes")).at(-1)[1].headers);
    expect(last["X-Velora-Company"]).toBe("COMP-002");
    expect(logins()).toBe(0);                                                                             // never asked for credentials
    expect(screen.getByRole("button", { name: /ACTIVE COMPANY/ }).textContent).toContain("Value Impacts Consulting");
    expect(window.location.hash).toBe("#/app");                                                          // back to the workspace home
  });

  it("returns to the sign-in form when the session expires mid-use", async () => {
    platform({ "GET /api/auth/me": () => ONE });
    render(<App />);
    await screen.findByRole("link", { name: "Customer" });
    act(() => { window.dispatchEvent(new Event("velora:unauthorized")); });
    expect(await screen.findByLabelText("Password")).toBeTruthy();
    expect(sessionStorage.getItem("velora.company")).toBeNull();
  });

  it("sign out ends the server session and clears the company", async () => {
    const calls = platform({ "GET /api/auth/me": () => ONE });
    render(<App />);
    await screen.findByRole("link", { name: "Customer" });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByLabelText("Password")).toBeTruthy();
    expect(calls.some((c) => c.key === "POST /api/auth/logout")).toBe(true);
    expect(sessionStorage.getItem("velora.company")).toBeNull();
  });

  it("a user with no companies is told to ask an administrator", async () => {
    platform({ "GET /api/auth/me": () => ({ ...PROFILE, companies: [] }) });
    render(<App />);
    expect(await screen.findByText(/not been given access to any company/)).toBeTruthy();
  });
});

describe("App - theme and reports in the shell", () => {
  const withTheme = (extra: Record<string, any> = {}) => platform({
    "GET /api/auth/me": () => ONE,
    "GET /api/theme/public": () => themeState({ css: ":root{--brand:public}", default_mode: "system" }),
    "GET /api/theme": () => themeState({ css: ":root{--brand:company}", default_mode: "dark", can_edit: true }),
    "GET /api/reports": () => [{ name: "Sales by Customer Group", module: "Demo", description: "", ref_doctype: "Sales Order", type: "script", can_export: true }],
    ...extra,
  });
  const css = () => document.getElementById("velora-theme")?.textContent;

  it("themes the sign-in screen first, then switches to the company's own theme after sign-in", async () => {
    document.head.innerHTML = "";
    withTheme({ "GET /api/auth/me": () => fail(401, "AuthenticationRequired", "Sign in required"), "POST /api/auth/login": () => ONE });
    render(<App />);
    await screen.findByLabelText("Password");
    await waitFor(() => expect(css()).toBe(":root{--brand:public}"));                      // even the login page is on-brand
    expect(document.documentElement.getAttribute("data-theme")).toBe("system");
  });

  it("applies the company theme (incl. dark default) once a company is active", async () => {
    document.head.innerHTML = "";
    withTheme();
    render(<App />);
    await screen.findByRole("link", { name: "Customer" });
    await waitFor(() => expect(css()).toBe(":root{--brand:company}"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: /Appearance/ })).toBeTruthy();
  });

  it("lists the reports the user may run, and opens one; Theme settings only for people who can edit it", async () => {
    window.location.hash = "";
    withTheme({ [`GET /api/report/Sales by Customer Group`]: () => reportDef(), [`POST /api/report/Sales by Customer Group/run`]: () => reportResult() });
    render(<App />);
    const link = await screen.findByRole("link", { name: "Sales by Customer Group" });
    expect(screen.getByRole("link", { name: "Theme" })).toBeTruthy();
    fireEvent.click(link);
    await screen.findByRole("heading", { name: "Sales by Customer Group", level: 2 });          // only the report sheet has this (the company name is also in the top bar)
    expect(window.location.hash).toBe("#/report/Sales%20by%20Customer%20Group");
    expect(screen.getByRole("link", { name: "Sales by Customer Group" }).className).toContain("active");
  });

  it("shows a way to build reports and the user's saved reports, and keeps the list fresh", async () => {
    window.location.hash = "";
    let saved = [{ id: "SR-1", name: "Credit by group", doctype: "Customer", owner: "sam", shared: false, can_edit: true, updated_on: null }];
    withTheme({ "GET /api/saved-reports": () => saved, "GET /api/saved-report/SR-1": () => ({ ...saved[0], spec: { doctype: "Customer", group_by: ["status"], measures: [{ fn: "count" }], filters: [] } }),
      "GET /api/meta/Customer": () => META.Customer, "POST /api/adhoc-report/run": () => reportResult() });
    render(<App />);
    expect(await screen.findByRole("link", { name: /New report/ })).toBeTruthy();
    const mine = await screen.findByRole("link", { name: "Credit by group" });
    saved = [...saved, { id: "SR-2", name: "Shared view", doctype: "Customer", owner: "boss", shared: true, can_edit: false, updated_on: null }];
    act(() => { window.dispatchEvent(new Event("velora:saved-reports-changed")); });
    expect(await screen.findByRole("link", { name: /Shared view/ })).toBeTruthy();               // a newly saved report appears without a reload
    fireEvent.click(mine);
    expect(await screen.findByRole("heading", { name: "Credit by group", level: 1 })).toBeTruthy();
    expect(window.location.hash).toBe("#/builder/SR-1");
  });

  it("offers the DocType Creator only when it is available, and opens it", async () => {
    window.location.hash = "";
    withTheme({ "GET /api/devtools/status": () => ({ available: true, apps: ["shop"] }) });
    const { unmount } = render(<App />);
    fireEvent.click(await screen.findByRole("link", { name: "DocType Creator" }));
    expect(await screen.findByRole("heading", { name: "DocType Creator" })).toBeTruthy();
    expect(window.location.hash).toBe("#/settings/doctype-creator");
    unmount();
    window.location.hash = "";
    withTheme({ "GET /api/devtools/status": () => ({ available: false, apps: [] }) });
    render(<App />);
    await screen.findByRole("link", { name: "Sales by Customer Group" });
    expect(screen.queryByRole("link", { name: "DocType Creator" })).toBeNull();                          // never a dead link for people who cannot use it
  });

  it("shows the Settings group to a developer who cannot edit the theme (and only the Creator in it)", async () => {
    withTheme({ "GET /api/theme": () => themeState({ can_edit: false }), "GET /api/devtools/status": () => ({ available: true, apps: ["shop"] }) });
    render(<App />);
    await screen.findByRole("link", { name: "DocType Creator" });
    expect(screen.queryByRole("link", { name: "Theme" })).toBeNull();
  });

  it("opens the layout designer for a DocType from the settings route", async () => {
    window.location.hash = "#/settings/layout/Customer";
    withTheme({ "GET /api/layout/Customer": () => ({ source: "auto", layout: { tabs: [{ label: "Main", sections: [{ label: "S", rows: [[{ field: "customer_name", span: 12 }]] }] }] }, unplaced: [], fields: [{ fieldname: "customer_name", fieldtype: "Data", label: "Customer Name" }], editable: true, can_write_app: false }) });
    render(<App />);
    expect(await screen.findByText("Customize form: Customer")).toBeTruthy();
    expect(screen.getByLabelText("Resize Customer Name")).toBeTruthy();
  });

  it("hides the Settings link without edit rights", async () => {
    withTheme({ "GET /api/theme": () => themeState({ can_edit: false }) });
    render(<App />);
    await screen.findByRole("link", { name: "Sales by Customer Group" });
    expect(screen.queryByRole("link", { name: "Theme" })).toBeNull();
  });

  it("opens the theme settings page", async () => {
    window.location.hash = "#/settings/theme";
    withTheme();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Theme" })).toBeTruthy();
    expect(await screen.findByRole("radio", { name: /Velora/ })).toBeTruthy();
  });

  it("keeps working when theme/report endpoints are unavailable (built-in fallback tokens)", async () => {
    platform({ "GET /api/auth/me": () => ONE });                                           // no theme or report routes mocked: 404
    render(<App />);
    expect(await screen.findByRole("link", { name: "Customer" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Appearance/ })).toBeNull();
  });
});

describe("App - developer mode is unchanged", () => {
  it("shows the developer sign-in and no company switcher", async () => {
    mockServer({ "GET /api/auth/config": () => ({ mode: "developer" }), "GET /api/doctypes": () => [] });
    render(<App />);
    expect(await screen.findByText(/Developer sign-in/)).toBeTruthy();
    expect(screen.queryByLabelText("Password")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Sign out");
    expect(screen.queryByText("ACTIVE COMPANY")).toBeNull();
  });
});
