import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { clearCaches, setAuthMode, setProfile, setSession } from "../api";
import VisualDocTypeBuilder from "../components/VisualDocTypeBuilder";
import { mockServer } from "./helpers";

const report = { structure: "single", ok: true, errors: [], warnings: [], conflicts: [], skipped: [], order: ["Customer Note"],
  doctypes: [{ name: "Customer Note", module: "CRM", fields: 2, child: false, submittable: false, links: [], path: "/apps/crm" }] };
const result = { created: ["Customer Note"], files: ["Customer Note.json", "Customer Note.py"], skipped: [], warnings: [], migration: [], note: "Created" };
beforeEach(() => { clearCaches(); localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "boss", roles: "System Manager" }); });

describe("VisualDocTypeBuilder", () => {
  it("builds a DocType definition, previews it, and creates only after a successful preview", async () => {
    const calls = mockServer({ "POST /api/devtools/doctype-creator/preview": () => report, "POST /api/devtools/doctype-creator/create": () => result });
    render(<VisualDocTypeBuilder apps={["crm", "sales"]} />);
    fireEvent.change(screen.getByLabelText("Module"), { target: { value: "CRM" } });
    fireEvent.change(screen.getByLabelText("DocType name"), { target: { value: "Customer Note" } });
    fireEvent.change(screen.getByLabelText("Fieldname 1"), { target: { value: "subject" } });
    fireEvent.change(screen.getByLabelText("Label 1"), { target: { value: "Subject" } });
    fireEvent.click(screen.getByLabelText("Required 1"));
    fireEvent.click(screen.getByRole("button", { name: "Preview DocType" }));
    expect(await screen.findByText("Definition valid")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create DocType" }));
    expect(await screen.findByText(/Created Customer Note/)).toBeTruthy();
    const sent = calls.find((c) => c.key.endsWith("/preview"))!.body as any;
    expect(sent.app).toBe("crm");
    const spec = JSON.parse(sent.json);
    expect(spec.name).toBe("Customer Note");
    expect(spec.fields[0]).toMatchObject({ fieldname: "subject", label: "Subject", fieldtype: "Data", required: true });
    expect(spec.permissions[0]).toMatchObject({ role: "System Manager", read: true, write: true, create: true });
  });

  it("includes advanced conditional field properties in generated metadata", async () => {
    const calls = mockServer({ "POST /api/devtools/doctype-creator/preview": () => report });
    render(<VisualDocTypeBuilder apps={["crm"]} />);
    fireEvent.change(screen.getByLabelText("Module"), { target: { value: "CRM" } });
    fireEvent.change(screen.getByLabelText("DocType name"), { target: { value: "Conditional Record" } });
    fireEvent.change(screen.getByLabelText("Fieldname 1"), { target: { value: "subject" } });
    fireEvent.change(screen.getByLabelText("Depends on 1"), { target: { value: 'eval:doc.status == "Open"' } });
    fireEvent.change(screen.getByLabelText("Mandatory depends on 1"), { target: { value: 'eval:doc.status == "Open"' } });
    fireEvent.change(screen.getByLabelText("Read only depends on 1"), { target: { value: 'eval:doc.docstatus == 1' } });
    fireEvent.change(screen.getByLabelText("Description 1"), { target: { value: "Subject of the record" } });
    fireEvent.click(screen.getByLabelText("Unique 1"));
    fireEvent.click(screen.getByLabelText("Read only 1"));
    fireEvent.click(screen.getByLabelText("Hidden 1"));
    fireEvent.click(screen.getByLabelText("Standard filter 1"));
    fireEvent.click(screen.getByRole("button", { name: "Preview DocType" }));
    expect(await screen.findByText("Definition valid")).toBeTruthy();
    const sent = calls.find((c) => c.key.endsWith("/preview"))!.body as any;
    const spec = JSON.parse(sent.json);
    expect(spec.fields[0]).toMatchObject({
      description: "Subject of the record", unique: true, read_only: true, hidden: true, in_standard_filter: true,
      depends_on: 'eval:doc.status == "Open"',
      mandatory_depends_on: 'eval:doc.status == "Open"',
      read_only_depends_on: 'eval:doc.docstatus == 1',
    });
  });

  it("supports child DocTypes without submittable flags", () => {
    render(<VisualDocTypeBuilder apps={["crm"]} />);
    fireEvent.click(screen.getByLabelText("Child table"));
    expect((screen.getByLabelText("Submittable") as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByText("Role permissions")).toBeNull();
  });
});
