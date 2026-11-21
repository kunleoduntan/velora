import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import DocTypeCreator from "../components/DocTypeCreator";
import { fail, mockServer } from "./helpers";

const GOOD_REPORT = { structure: "multiple", ok: true, errors: [], warnings: ["Sales Thing: date parts in the naming series 'ST-.YYYY.-.#####' were dropped"], conflicts: [], skipped: [], order: ["Order Line", "Sales Thing"],
  doctypes: [{ name: "Order Line", module: "Sales", fields: 2, child: true, submittable: false, links: [], path: "/x/order_line" }, { name: "Sales Thing", module: "Sales", fields: 3, child: false, submittable: true, links: ["Order Line"], path: "/x/sales_thing" }] };
const BAD_REPORT = { ...GOOD_REPORT, ok: false, errors: ["Alpha.l: Link target 'Nowhere' is not a DocType", "Single DocTypes are not supported"], order: [] };
const RESULT = { created: ["Order Line", "Sales Thing"], files: [], skipped: [], warnings: [], migration: ["CREATE TABLE tab_order_line (...)", "CREATE TABLE tab_sales_thing (...)"], note: "Other companies/sites pick the new tables up with `velora upgrade`." };

beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "boss", roles: "System Manager" }); });
const setup = (extra: Record<string, any> = {}, status = { available: true, apps: ["shop", "other"] }) => {
  const calls = mockServer({ "GET /api/devtools/status": () => status, ...extra });
  return { calls, ...render(<DocTypeCreator />) };
};
const paste = (v: string) => fireEvent.change(screen.getByLabelText("DocType JSON"), { target: { value: v } });
const btn = (n: string | RegExp) => screen.getByRole("button", { name: n }) as HTMLButtonElement;

describe("DocTypeCreator", () => {
  it("says what it needs when developer mode is off", async () => {
    setup({}, { available: false, apps: [] });
    expect(await screen.findByText(/needs/)).toBeTruthy();
    expect(screen.queryByLabelText("DocType JSON")).toBeNull();
  });

  it("previews first: shows the structure, the order, the links and the warnings, and only then allows creating", async () => {
    const { calls } = setup({ "POST /api/devtools/doctype-creator/preview": () => GOOD_REPORT });
    await screen.findByLabelText("DocType JSON");
    expect(btn("Preview").disabled).toBe(true);
    expect(btn("Create DocTypes").disabled).toBe(true);
    paste('{"doctypes": []}');
    expect(btn("Create DocTypes").disabled).toBe(true);                                                       // creating needs a clean preview of THIS input
    fireEvent.click(btn("Preview"));
    const rep = within(await screen.findByTestId("creator-report"));
    expect(rep.getByText("Ready: 2 DocType(s)")).toBeTruthy();
    expect(rep.getByText(/date parts in the naming series/)).toBeTruthy();
    expect(rep.getByText("Order Line → Sales Thing", { exact: false })).toBeTruthy();
    expect(rep.getAllByRole("row").map((r) => r.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("Child table"), expect.stringContaining("Submittable")]));
    expect(btn("Create DocTypes").disabled).toBe(false);
    expect(calls.find((c) => c.key.endsWith("/preview"))!.body).toMatchObject({ app: "shop", on_conflict: "error", json: '{"doctypes": []}' });
    paste('{"doctypes": [{"name": "X"}]}');                                                                   // any edit throws the preview away
    expect(screen.queryByTestId("creator-report")).toBeNull();
    expect(btn("Create DocTypes").disabled).toBe(true);
  });

  it("lists every error and refuses to create while there are any", async () => {
    setup({ "POST /api/devtools/doctype-creator/preview": () => BAD_REPORT });
    await screen.findByLabelText("DocType JSON");
    paste("[]"); fireEvent.click(btn("Preview"));
    const rep = within(await screen.findByTestId("creator-report"));
    expect(rep.getByText("Not ready")).toBeTruthy();
    expect(rep.getByText(/Link target 'Nowhere'/)).toBeTruthy();
    expect(rep.getByText(/Single DocTypes are not supported/)).toBeTruthy();
    expect(rep.getByRole("alert").textContent).toContain("nothing will be created");
    expect(btn("Create DocTypes").disabled).toBe(true);
  });

  it("catches broken JSON in the browser with the position, without calling the server", async () => {
    const { calls } = setup();
    await screen.findByLabelText("DocType JSON");
    paste("{oops"); fireEvent.click(btn("Preview"));
    expect((await screen.findByRole("alert")).textContent).toContain("That is not valid JSON");
    expect(calls.some((c) => c.key.includes("doctype-creator"))).toBe(false);
  });

  it("sends the options (app, module, name, flags, conflict policy) and shows what was created, where to go next, and the database changes", async () => {
    const { calls } = setup({ "POST /api/devtools/doctype-creator/preview": () => GOOD_REPORT, "POST /api/devtools/doctype-creator/create": () => RESULT });
    await screen.findByLabelText("DocType JSON");
    paste('[{"fieldname": "title", "fieldtype": "Data"}]');
    fireEvent.change(screen.getByLabelText("Create in app"), { target: { value: "other" } });
    fireEvent.change(screen.getByLabelText(/^Module/), { target: { value: "Sales" } });
    fireEvent.change(screen.getByLabelText(/^DocType name/), { target: { value: "Voucher" } });
    fireEvent.change(screen.getByLabelText("Name documents after field"), { target: { value: "title" } });
    fireEvent.change(screen.getByLabelText("If a DocType already exists"), { target: { value: "skip" } });
    fireEvent.click(screen.getByLabelText("Submittable")); fireEvent.click(screen.getByLabelText("Track changes"));
    fireEvent.click(btn("Preview")); await screen.findByTestId("creator-report");
    fireEvent.click(btn("Create DocTypes"));
    const res = within(await screen.findByTestId("creator-result"));
    expect(res.getByText("Created 2 DocType(s).")).toBeTruthy();
    expect(res.getAllByRole("link", { name: "open list" })[1].getAttribute("href")).toBe("#/app/Sales%20Thing");
    expect(res.getAllByRole("link", { name: "design form" })[0].getAttribute("href")).toBe("#/settings/layout/Order%20Line");
    expect(res.getByText(/Database changes \(2\)/)).toBeTruthy();
    expect(res.getByText(/velora upgrade/)).toBeTruthy();
    expect(calls.find((c) => c.key.endsWith("/create"))!.body).toEqual({ json: '[{"fieldname": "title", "fieldtype": "Data"}]', app: "other", module: "Sales", name: "Voucher", on_conflict: "skip",
      is_submittable: true, track_changes: true, is_autoname: true, autoname_field_name: "title" });
    expect(screen.queryByTestId("creator-report")).toBeNull();                                                  // the preview is cleared once it has been acted on
  });

  it("shows the server's refusal (e.g. not allowed, or something now exists) and creates nothing", async () => {
    setup({ "POST /api/devtools/doctype-creator/preview": () => GOOD_REPORT, "POST /api/devtools/doctype-creator/create": () => fail(422, "ValidationError", "Nothing was created:\n  - Sales Thing already exists") });
    await screen.findByLabelText("DocType JSON");
    paste("{}"); fireEvent.click(btn("Preview")); await screen.findByTestId("creator-report");
    fireEvent.click(btn("Create DocTypes"));
    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
    expect(screen.queryByTestId("creator-result")).toBeNull();
  });

  it("tidies the JSON on request", async () => {
    setup();
    await screen.findByLabelText("DocType JSON");
    paste('{"a":1,"b":[2]}');
    fireEvent.click(btn("Format JSON"));
    expect((screen.getByLabelText("DocType JSON") as HTMLTextAreaElement).value).toBe('{\n  "a": 1,\n  "b": [\n    2\n  ]\n}');
    paste("{bad"); fireEvent.click(btn("Format JSON"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("not valid JSON"));
  });
});
