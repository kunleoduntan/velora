import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PublishPanel from "../components/PublishPanel";
import { fail, mockServer } from "./helpers";

const profile = { id: "velora-core", label: "velora-core", source: "upload", app: null, company_id: "COMP-001", company_name: "My Company", repo_url: "https://github.com/kunleoduntan/velora",
  branch: "main", author_name: "V", author_email: "v@x", has_token: true, workdir: "publish/velora-core", last_push: null };
const catalog = (over: object = {}) => ({ profiles: [profile], apps: ["shop"], git: true, companies: [{ id: "COMP-001", name: "My Company", status: "active" }, { id: "COMP-002", name: "Complexia Ltd", status: "active" }, { id: "COMP-003", name: "Paused", status: "suspended" }], ...over });
const base = (over: Record<string, any> = {}) => ({ "GET /api/publish/profiles": () => catalog(), "GET /api/publish/profiles/velora-core/status": () => ({ profile, git: true, ready: true, changes: ["M a.txt"], last_commit: "abc one" }), ...over });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Publish to GitHub", () => {
  it("names the company and repository before pushing, and pushes only after the confirmation", async () => {
    const calls = mockServer(base({ "POST /api/publish/profiles/velora-core/push": () => ({ pushed: true, commit: "def456", new_commit: true, already_up_to_date: false, to: "repo (main)", company_check: { company: "My Company", checked: false, note: "" } }) }));
    render(<PublishPanel />);
    expect(await screen.findByText("My Company")).toBeTruthy();
    fireEvent.click(screen.getByText("Push to GitHub"));
    const dlg = await screen.findByRole("dialog", { name: "Confirm push" });
    expect(dlg.textContent).toContain("My Company");
    expect(dlg.textContent).toContain("https://github.com/kunleoduntan/velora");
    expect(calls.some(c => c.key === "POST /api/publish/profiles/velora-core/push")).toBe(false);
    fireEvent.click(screen.getByText("Yes, push now"));
    expect(await screen.findByText(/Pushed commit def456/)).toBeTruthy();
    expect(calls.find(c => c.key === "POST /api/publish/profiles/velora-core/push")!.body).toEqual({ message: "Update", on_top: false });
  });

  it("cancelling the confirmation pushes nothing", async () => {
    const calls = mockServer(base());
    render(<PublishPanel />);
    fireEvent.click(await screen.findByText("Push to GitHub"));
    fireEvent.click(await screen.findByText("Cancel"));
    expect(calls.some(c => c.key.endsWith("/push"))).toBe(false);
  });

  it("will not offer a push when no token is saved", async () => {
    mockServer(base({ "GET /api/publish/profiles": () => catalog({ profiles: [{ ...profile, has_token: false }] }) }));
    render(<PublishPanel />);
    const btn = (await screen.findByText("Push to GitHub")) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("shows the server's explanation when the push is refused", async () => {
    mockServer(base({ "POST /api/publish/profiles/velora-core/push": () => fail(422, "ValidationError", "The repository already has commits that this copy does not. Nothing was overwritten.") }));
    render(<PublishPanel />);
    fireEvent.click(await screen.findByText("Push to GitHub"));
    fireEvent.click(await screen.findByText("Yes, push now"));
    expect(await screen.findByText(/Nothing was overwritten/)).toBeTruthy();
  });

  it("uploads the chosen zip with its name", async () => {
    const calls = mockServer(base({ "POST /api/publish-upload/velora-core": () => ({ files: 12, skipped_count: 2, skipped: [], stripped_top_folder: true }) }));
    render(<PublishPanel />);
    const input = await screen.findByLabelText("Choose project zip");
    fireEvent.change(input, { target: { files: [new File(["zip"], "velora.zip")] } });
    expect(await screen.findByText(/Uploaded 12 files/)).toBeTruthy();
    expect(calls.find(c => c.key === "POST /api/publish-upload/velora-core")!.headers!["X-Filename"]).toBe("velora.zip");
  });

  it("creating a profile needs a company and offers only active companies", async () => {
    const calls = mockServer(base({ "POST /api/publish/profiles": ({ body }: any) => ({ ...profile, id: body.id }) }));
    render(<PublishPanel />);
    fireEvent.click(await screen.findByText("New profile"));
    const save = screen.getByText("Save profile") as HTMLButtonElement;
    expect(screen.queryByText(/Paused/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Profile name"), { target: { value: "shop-co" } });
    fireEvent.change(screen.getByLabelText("Company this belongs to"), { target: { value: "" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Company this belongs to"), { target: { value: "COMP-002" } });
    fireEvent.change(screen.getByLabelText("GitHub access token"), { target: { value: "ghp_abcdefgh1234" } });
    fireEvent.click(save);
    await waitFor(() => expect(calls.some(c => c.key === "POST /api/publish/profiles")).toBe(true));
    expect(calls.find(c => c.key === "POST /api/publish/profiles")!.body).toMatchObject({ id: "shop-co", company_id: "COMP-002", source: "upload", token: "ghp_abcdefgh1234" });
  });

  it("warns when git is missing", async () => {
    mockServer(base({ "GET /api/publish/profiles": () => catalog({ git: false }) }));
    render(<PublishPanel />);
    expect(await screen.findByText(/git is not installed/)).toBeTruthy();
  });

  it("Publish on top shows what will change and pushes on top only after Yes", async () => {
    const calls = mockServer(base({
      "GET /api/publish/profiles/velora-core/compare": () => ({ remote_exists: true, relation: "different", added: ["a.txt"], changed: ["b.txt"], removed: ["README.md"], counts: { added: 1, changed: 1, removed: 1 } }),
      "POST /api/publish/profiles/velora-core/push": () => ({ pushed: true, commit: "abc999", new_commit: true, already_up_to_date: false, placed_on_top: true, to: "repo (main)", company_check: { company: "My Company", checked: false, note: "" } }) }));
    render(<PublishPanel />);
    fireEvent.click(await screen.findByText("Publish on top of GitHub…"));
    const dlg = await screen.findByRole("dialog", { name: "Publish on top of GitHub" });
    expect(dlg.textContent).toContain("Its history is kept");
    expect(dlg.textContent).toMatch(/1 file\(s\) added, 1 changed, 1 removed/);
    expect(calls.some(c => c.key === "POST /api/publish/profiles/velora-core/push")).toBe(false);
    fireEvent.click(screen.getByText("Yes, publish on top"));
    expect(await screen.findByText(/Published commit abc999 on top/)).toBeTruthy();
    expect(calls.find(c => c.key === "POST /api/publish/profiles/velora-core/push")!.body).toEqual({ message: "Update", on_top: true });
  });

  it("Install / Update is offered for an app profile, confirms the company, and reports each step", async () => {
    const app = { ...profile, id: "crm-a", label: "crm-a", source: "app", app: "crm", workdir: "apps/crm" };
    const calls = mockServer({ "GET /api/publish/profiles": () => catalog({ profiles: [app] }), "GET /api/publish/profiles/crm-a/status": () => ({ profile: app, git: true, ready: true, changes: [], last_commit: null }),
      "POST /api/publish/profiles/crm-a/install": () => ({ app: "crm", company: "My Company", commit: "f00", previous: null, installed: ["crm"], changed: true, steps: ["Downloaded crm.", "Installed in My Company."] }) });
    render(<PublishPanel />);
    fireEvent.click(await screen.findByText("Install / Update from GitHub"));
    const dlg = await screen.findByRole("dialog", { name: "Install from GitHub" });
    expect(dlg.textContent).toContain("My Company");
    expect(calls.some(c => c.key === "POST /api/publish/profiles/crm-a/install")).toBe(false);
    fireEvent.click(screen.getByText("Yes, install / update"));
    expect(await screen.findByText(/Downloaded crm\. Installed in My Company\./)).toBeTruthy();
  });

  it("an upload profile has no Install button", async () => {
    mockServer(base());
    render(<PublishPanel />);
    await screen.findByText("Publish on top of GitHub…");
    expect(screen.queryByText("Install / Update from GitHub")).toBeNull();
  });
});
