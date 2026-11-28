import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import AppHub from "../components/AppHub";
import { visibleHubs } from "../hubs";
import type { DocTypeInfo } from "../types";

const t = (name: string, app: string, module: string, can_create = true): DocTypeInfo => ({ name, app, module, is_submittable: false, can_create });
const types = [
  t("Sales Invoice", "velora_erp", "Finance"), t("Payment", "velora_erp", "Finance"), t("Account", "velora_erp", "Finance"), t("Fixed Asset", "velora_erp", "Finance"),
  t("Employee", "velora_erp", "HR"), t("Salary Slip", "velora_erp", "Finance"),
  t("Project", "velora_projectone", "Projects"), t("Risk", "velora_projectone", "Governance"), t("Sprint", "velora_projectone", "Agile"),
  t("Request", "velora_admin", "Administration"), t("Gadget", "some_other_app", "Stuff"),
  t("Engagement Log", "velora_erp", "Engagement"), t("Occasion", "velora_erp", "Engagement"), t("Moment Template", "velora_erp", "Engagement"),
  t("Travel Booking", "farepoint", "Farepoint"), t("Travel Enquiry", "farepoint", "Farepoint"), t("Visa Application", "farepoint", "Farepoint"),
  t("Travel Supplier", "farepoint", "Farepoint"), t("Customer Trip Request", "farepoint", "Farepoint"), t("Farepoint Settings", "farepoint", "Farepoint"),
];
const reports = [{ name: "Trial Balance", module: "Finance", description: "", ref_doctype: "Account", type: "Script", can_export: true }];
afterEach(() => { cleanup(); localStorage.clear(); window.location.hash = ""; });

describe("App Hub", () => {
  it("gives each application its own hub and keeps pay documents with people", () => {
    const hubs = visibleHubs(types, reports);
    const names = (id: string) => hubs.find(h => h.hub.id === id)!.items.filter(i => i.kind === "doctype").map(i => i.label);
    expect(hubs.map(h => h.hub.id)).toEqual(expect.arrayContaining(["finance", "hr", "projects", "administration", "app-some_other_app"]));
    expect(names("hr").sort()).toEqual(["Employee", "Salary Slip"]);
    expect(names("projects").sort()).toEqual(["Project", "Risk", "Sprint"]);        // every ProjectOne group is one hub
    expect(names("finance")).not.toContain("Salary Slip");
  });

  it("offers each application's how-to guide, with a welcome line, on the hub list and on the hub", () => {
    const { rerender } = render(<AppHub types={types} reports={reports} />);
    const hrefs = screen.getAllByRole("link").map(a => a.getAttribute("href"));
    expect(hrefs).toEqual(expect.arrayContaining(["/tutorial", "/guide/velora_erp", "/guide/velora_projectone", "/guide/velora_admin"]));
    rerender(<AppHub types={types} reports={reports} hubId="administration" />);
    expect(screen.getByText(/quiet work that keeps an organisation running/)).toBeTruthy();
    expect(screen.getByText("How-to guide ↗").getAttribute("href")).toBe("/guide/velora_admin");
  });

  it("splits Finance into named sections and lists the reports on its documents", () => {
    const fin = visibleHubs(types, reports).find(h => h.hub.id === "finance")!;
    const section = (label: string) => fin.items.find(i => i.label === label)!.section;
    expect(section("Sales Invoice")).toBe("Sales & Receivables");
    expect(section("Payment")).toBe("Receipts & Payments");
    expect(section("Fixed Asset")).toBe("Fixed Assets");
    expect(fin.items.some(i => i.kind === "report" && i.label === "Trial Balance")).toBe(true);
  });

  it("gives Farepoint its own hub with travel sections, its reports and centre links", () => {
    const reps = [...reports, { name: "Travel Executive Summary", module: "Farepoint", description: "", ref_doctype: "Travel Booking", type: "Script", can_export: true }];
    const hubs = visibleHubs(types, reps);
    expect(hubs.some(h => h.hub.id === "app-farepoint")).toBe(false);
    const fp = hubs.find(h => h.hub.id === "farepoint")!;
    expect(fp.hub.title).toBe("Farepoint");
    const section = (label: string) => fp.items.find(i => i.label === label)!.section;
    expect(section("Travel Enquiry")).toBe("Sales & Enquiries");
    expect(section("Travel Booking")).toBe("Bookings & Trips");
    expect(section("Visa Application")).toBe("Visas & Documents");
    expect(section("Travel Supplier")).toBe("Suppliers");
    expect(section("Customer Trip Request")).toBe("Corporate Travel");
    expect(section("Farepoint Settings")).toBe("Rates, Targets & Settings");
    expect(fp.items.some(i => i.kind === "report" && i.label === "Travel Executive Summary")).toBe(true);
    expect(fp.items.some(i => i.kind === "report" && i.label === "Trial Balance")).toBe(false);
    expect(fp.items.find(i => i.label === "Farepoint Dashboard")?.href).toBe("#/dashboards");
    expect(fp.items.some(i => i.label === "Customers")).toBe(false);   // needs the Customer form, which this person does not have
  });

  it("gives Engagement its own hub with sections and the Engagement reports only", () => {
    const reps = [...reports, { name: "Upcoming Moments", module: "Engagement", description: "", ref_doctype: "Engagement Log", type: "Script", can_export: true }];
    const hubs = visibleHubs(types, reps);
    expect(hubs.some(h => h.hub.id === "app-velora_erp")).toBe(false);
    const eng = hubs.find(h => h.hub.id === "engagement")!;
    const section = (label: string) => eng.items.find(i => i.label === label)!.section;
    expect(section("Engagement Log")).toBe("Messages Sent");
    expect(section("Occasion")).toBe("Calendar & Dates");
    expect(section("Moment Template")).toBe("Templates & Brand");
    expect(eng.items.some(i => i.kind === "report" && i.label === "Upcoming Moments")).toBe(true);
    expect(eng.items.some(i => i.kind === "report" && i.label === "Trial Balance")).toBe(false);
  });

  it("gives the Administration reports their own Business Insights hub", () => {
    const reps = [...reports, { name: "Cash Outlook", module: "Administration", description: "", ref_doctype: "Customer", type: "Script", can_export: true }];
    const ins = visibleHubs(types, reps).find(h => h.hub.id === "insights")!;
    expect(ins.items.filter(i => i.kind === "report").map(i => i.label)).toEqual(["Cash Outlook"]);
    expect(visibleHubs(types, reports).some(h => h.hub.id === "insights")).toBe(false);          // nothing to show without those reports
  });

  it("shows tiles, opens a hub, searches and keeps favourites", () => {
    const { rerender } = render(<AppHub types={types} reports={reports} />);
    expect(screen.getByText("Projects").closest("a")?.getAttribute("href")).toBe("#/hub/projects");
    rerender(<AppHub types={types} reports={reports} hubId="projects" />);
    expect(screen.getByText("Sprint")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search Projects"), { target: { value: "risk" } });
    expect(screen.queryByText("Sprint")).toBeNull();
    fireEvent.click(screen.getByLabelText("Add Risk to favourites"));
    expect(JSON.parse(localStorage.getItem("velora.hub.favourites")!)).toEqual(["doctype|Risk"]);
    fireEvent.click(screen.getByRole("tab", { name: "Favourites" }));
    expect(screen.getByText("Risk")).toBeTruthy();
  });
});
