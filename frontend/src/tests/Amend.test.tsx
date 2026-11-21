import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import FormView, { PREFILL_KEY } from "../components/FormView";
import { resetScripts } from "../clientScripts";
import so from "./fixtures/sales_order.meta.json";
import { fail, mockServer, META } from "./helpers";

const AMENDED_FROM = { fieldname: "amended_from", fieldtype: "Link", label: "Amended From", options: "Sales Order", read_only: true, hidden: true };
const SO_META = (perms: Record<string, boolean> = {}) => ({ ...(so as Record<string, any>), fields: [...(so as any).fields, AMENDED_FROM], permissions: { ...(so as any).permissions, ...perms } });
const DOC = (over: Record<string, unknown> = {}) => ({ doctype: "Sales Order", name: "SO-0001", docstatus: 2, customer: "Acme Ltd", order_date: "2026-03-02", total: 250, items: [{ name: "r1", description: "Widget", qty: 2, rate: 100 }], ...over });
const COPY = (mode: string, over: Record<string, unknown> = {}) => ({ doctype: "Sales Order", mode, source: "SO-0001", values: { customer: "Acme Ltd", order_date: "2026-03-02", items: [{ description: "Widget", qty: 2, rate: 100 }], ...(mode === "amend" ? { amended_from: "SO-0001" } : {}) },
  amended_from: mode === "amend" ? "SO-0001" : null, suggested_name: mode === "amend" ? "SO-0001-1" : null, ...over });
const serve = (doc: Record<string, unknown>, extra: Record<string, any> = {}, perms: Record<string, boolean> = {}) =>
  mockServer({ "GET /api/meta/Sales Order": () => SO_META(perms), [`GET /api/resource/Sales Order/${doc.name}`]: () => doc, ...extra });
beforeEach(() => { clearCaches(); resetScripts(); sessionStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "sam", roles: "Sales User" }); window.location.hash = ""; vi.stubGlobal("confirm", () => true); });
void META;
const btn = (n: string) => screen.queryByRole("button", { name: n });

describe("a cancelled document", () => {
  it("says it is cancelled, still on record, and offers Amend", async () => {
    serve(DOC(), { "GET /api/resource/Sales Order/SO-0001/amended-to": () => ({ amended_to: null }) });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    expect(await screen.findByText("This document is cancelled.")).toBeTruthy();
    expect(screen.getByText(/stays on record but no longer counts/)).toBeTruthy();
    expect(screen.getByText(/To correct it, press Amend/)).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Amend" })).toBeTruthy();
    expect(screen.getByText("Cancelled", { selector: ".pill" })).toBeTruthy();
  });

  it("Amend fetches the copy, hands it to a new unsaved form, and goes there", async () => {
    const calls = serve(DOC(), { "GET /api/resource/Sales Order/SO-0001/amended-to": () => ({ amended_to: null }), "GET /api/resource/Sales Order/SO-0001/copy": () => COPY("amend") });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    fireEvent.click(await screen.findByRole("button", { name: "Amend" }));
    await waitFor(() => expect(window.location.hash).toBe("#/app/Sales%20Order/new"));
    expect(calls.find((c) => c.key.endsWith("/copy"))!.url.searchParams.get("mode")).toBe("amend");
    const stored = JSON.parse(sessionStorage.getItem(PREFILL_KEY)!);
    expect(stored.mode).toBe("amend");
    expect(stored.values.amended_from).toBe("SO-0001");
  });

  it("once amended, there is no second Amend: it points to the amendment", async () => {
    serve(DOC(), { "GET /api/resource/Sales Order/SO-0001/amended-to": () => ({ amended_to: "SO-0001-1" }) });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    const link = await screen.findByRole("link", { name: "SO-0001-1" });
    expect(link.getAttribute("href")).toBe("#/app/Sales%20Order/SO-0001-1");
    expect(screen.getByText(/It was amended as/)).toBeTruthy();
    expect(btn("Amend")).toBeNull();
  });

  it("shows the server's reason if the amendment is refused (for example, someone else just amended it)", async () => {
    serve(DOC(), { "GET /api/resource/Sales Order/SO-0001/amended-to": () => ({ amended_to: null }), "GET /api/resource/Sales Order/SO-0001/copy": () => fail(422, "ValidationError", "SO-0001 has already been amended as SO-0001-1. Amend that one instead.") });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    fireEvent.click(await screen.findByRole("button", { name: "Amend" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already been amended as SO-0001-1");
    expect(window.location.hash).toBe("");
    expect(sessionStorage.getItem(PREFILL_KEY)).toBeNull();
  });

  it("without permission to create there is no Amend, and the banner does not promise one", async () => {
    serve(DOC(), { "GET /api/resource/Sales Order/SO-0001/amended-to": () => ({ amended_to: null }) }, { create: false });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    await screen.findByText("This document is cancelled.");
    expect(btn("Amend")).toBeNull();
    expect(screen.queryByText(/press Amend/)).toBeNull();
  });
});

describe("only a cancelled document can be amended", () => {
  it.each([[0, "Draft"], [1, "Submitted"]])("a %i document has no Amend button and no cancelled banner", async (docstatus) => {
    const calls = serve(DOC({ docstatus }));
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    await screen.findByRole("heading", { name: /SO-0001/ });
    expect(btn("Amend")).toBeNull();
    expect(screen.queryByText("This document is cancelled.")).toBeNull();
    expect(calls.some((c) => c.key.endsWith("/amended-to"))).toBe(false);                    // not even asked
  });
});

describe("Duplicate", () => {
  it("is offered on a saved document, whatever its status, and opens a pre-filled new form", async () => {
    const calls = serve(DOC({ docstatus: 1 }), { "GET /api/resource/Sales Order/SO-0001/copy": () => COPY("duplicate") });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    fireEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(window.location.hash).toBe("#/app/Sales%20Order/new"));
    expect(calls.find((c) => c.key.endsWith("/copy"))!.url.searchParams.get("mode")).toBe("duplicate");
  });

  it("is not offered on a new form, or without permission to create", async () => {
    serve({ doctype: "Sales Order", name: "new" } as any);
    const { unmount } = render(<FormView doctype="Sales Order" name="new" />);
    await screen.findByRole("heading", { name: "New Sales Order" });
    expect(btn("Duplicate")).toBeNull();
    unmount();
    clearCaches();                                                                           // (the metadata cache would otherwise keep the permissions of the first render)
    serve(DOC({ docstatus: 0 }), {}, { create: false });
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    await screen.findByRole("heading", { name: /SO-0001/ });
    expect(btn("Duplicate")).toBeNull();
  });
});

describe("the new form that Amend and Duplicate open", () => {
  const open = async (mode: "amend" | "duplicate", extra: Record<string, any> = {}) => {
    sessionStorage.setItem(PREFILL_KEY, JSON.stringify(COPY(mode)));
    const calls = mockServer({ "GET /api/meta/Sales Order": () => SO_META(), "POST /api/resource/Sales Order": ({ body }: any) => ({ ...body, name: mode === "amend" ? "SO-0001-1" : "SO-0002", docstatus: 0 }), ...extra });
    render(<FormView doctype="Sales Order" name="new" />);
    await screen.findByRole("heading", { name: "New Sales Order" });
    return calls;
  };

  it("an amendment is pre-filled, says what it amends and what it will be called, and is unsaved", async () => {
    await open("amend");
    expect((screen.getByLabelText(/^Customer/) as HTMLInputElement).value).toBe("Acme Ltd");
    expect(screen.getByText(/Amending/).textContent).toContain("it will be saved as SO-0001-1");
    expect(screen.getByRole("link", { name: "SO-0001" }).getAttribute("href")).toBe("#/app/Sales%20Order/SO-0001");
    expect(screen.getByText("Not Saved", { selector: ".pill" })).toBeTruthy();
  });

  it("a duplicate says where it came from and that nothing is saved yet", async () => {
    await open("duplicate");
    expect(screen.getByText(/Duplicated from/).textContent).toContain("Nothing is saved until you press Save");
    expect((screen.getByLabelText(/^Customer/) as HTMLInputElement).value).toBe("Acme Ltd");
  });

  it("saving sends the pre-filled values, including the link to the cancelled original", async () => {
    const calls = await open("amend");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/resource/Sales Order")).toBe(true));
    const body = calls.find((c) => c.key === "POST /api/resource/Sales Order")!.body;
    expect(body.amended_from).toBe("SO-0001");
    expect(body.customer).toBe("Acme Ltd");
    expect(body.items).toHaveLength(1);
    expect(body.items[0].description).toBe("Widget");
  });

  it("the hand-over is used once: opening a new form again starts blank", async () => {
    await open("duplicate");
    expect(sessionStorage.getItem(PREFILL_KEY)).toBeNull();
    const { unmount } = render(<FormView doctype="Sales Order" name="new" />);
    unmount();
    mockServer({ "GET /api/meta/Sales Order": () => SO_META() });
    render(<FormView doctype="Sales Order" name="new" />);
    await waitFor(() => expect(screen.getAllByRole("heading", { name: "New Sales Order" }).length).toBeGreaterThan(0));
    expect(screen.getAllByLabelText(/^Customer/).some((i) => (i as HTMLInputElement).value === "Acme Ltd")).toBe(true);        // (the first form is still mounted)
    expect(sessionStorage.getItem(PREFILL_KEY)).toBeNull();
  });

  it("a hand-over meant for another DocType, or a damaged one, is ignored", async () => {
    sessionStorage.setItem(PREFILL_KEY, JSON.stringify({ ...COPY("duplicate"), doctype: "Customer" }));
    mockServer({ "GET /api/meta/Sales Order": () => SO_META() });
    const { unmount } = render(<FormView doctype="Sales Order" name="new" />);
    await screen.findByRole("heading", { name: "New Sales Order" });
    expect((screen.getByLabelText(/^Customer/) as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/Duplicated from/)).toBeNull();
    unmount();
    sessionStorage.setItem(PREFILL_KEY, "{ not json");
    mockServer({ "GET /api/meta/Sales Order": () => SO_META() });
    render(<FormView doctype="Sales Order" name="new" />);
    await screen.findByRole("heading", { name: "New Sales Order" });
    expect(screen.queryByText(/Amending|Duplicated from/)).toBeNull();
  });
});

describe("an amended document", () => {
  it("says what it was amended from, with a link", async () => {
    serve(DOC({ docstatus: 1, name: "SO-0001-1", amended_from: "SO-0001" }));
    render(<FormView doctype="Sales Order" name="SO-0001-1" />);
    const banner = await screen.findByText(/Amended from/);
    expect(banner.closest(".banner")!.textContent).toContain("(cancelled)");
    expect(screen.getByRole("link", { name: "SO-0001" }).getAttribute("href")).toBe("#/app/Sales%20Order/SO-0001");
  });
  it("a normal document has no such banner", async () => {
    serve(DOC({ docstatus: 1 }));
    render(<FormView doctype="Sales Order" name="SO-0001" />);
    await screen.findByRole("heading", { name: /SO-0001/ });
    expect(screen.queryByText(/Amended from/)).toBeNull();
  });
});
