import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FileExplorer from "../components/FileExplorer";
import { fail, mockServer } from "./helpers";

const root = { path: "", can_write: false, entries: [
  { name: "apps", type: "dir", size: null, modified: null, editable: false, can_delete: false },
  { name: "backups", type: "dir", size: null, modified: null, editable: false, can_delete: false } ] };
const files = (extra: object[] = []) => ({ path: "files", can_write: true, entries: [
  { name: "docs", type: "dir", size: null, modified: "2026-01-01T00:00:00+00:00", editable: false, can_delete: true },
  { name: "notes.txt", type: "file", size: 12, modified: "2026-01-01T00:00:00+00:00", editable: true, can_delete: true }, ...extra ] });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const listRoutes = (over: Record<string, any> = {}) => ({
  "GET /api/filemanager/list": ({ url }: any) => (url.searchParams.get("path") ? files() : root), ...over });

describe("File explorer", () => {
  it("opens a folder and shows read-only at the top level", async () => {
    mockServer(listRoutes());
    render(<FileExplorer />);
    expect(await screen.findByText("Pick a folder to begin.")).toBeTruthy();
    expect(screen.queryByText("Upload files")).toBeNull();
    fireEvent.click(screen.getByLabelText("Open folder apps"));
    // the stub returns the writable listing for any non-empty path
    expect(await screen.findByText("Upload files")).toBeTruthy();
    expect(screen.getByText("notes.txt")).toBeTruthy();
  });

  it("uploads a dropped file into the current folder", async () => {
    const calls = mockServer(listRoutes({ "POST /api/filemanager/upload": () => ({ path: "files/a.txt", size: 3 }) }));
    const { container } = render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    await screen.findByText("Upload files");
    const file = new File(["abc"], "a.txt", { type: "text/plain" });
    fireEvent.drop(container.querySelector(".file-explorer")!, { dataTransfer: { files: [file] } });
    await screen.findByText("Uploaded 1 file.");
    const up = calls.find(c => c.key === "POST /api/filemanager/upload")!;
    expect(up.url.searchParams.get("path")).toBe("files");
    expect(up.headers!["X-Filename"]).toBe("a.txt");
  });

  it("pasting files uploads them too", async () => {
    const calls = mockServer(listRoutes({ "POST /api/filemanager/upload": () => ({ path: "files/p.txt", size: 1 }) }));
    const { container } = render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    await screen.findByText("Upload files");
    fireEvent.paste(container.querySelector(".file-explorer")!, { clipboardData: { files: [new File(["x"], "p.txt")] } });
    await waitFor(() => expect(calls.some(c => c.key === "POST /api/filemanager/upload")).toBe(true));
  });

  it("edits a text file and warns by sending the version it started from", async () => {
    const calls = mockServer(listRoutes({
      "GET /api/filemanager/read": () => ({ path: "files/notes.txt", content: "hello", modified: 777, editable: true }),
      "PUT /api/filemanager/write": () => ({ path: "files/notes.txt", modified: 778, size: 6 }) }));
    render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    fireEvent.click(await screen.findByLabelText("Open notes.txt"));
    const box = await screen.findByLabelText("File contents");
    fireEvent.change(box, { target: { value: "hello!" } });
    fireEvent.click(screen.getByText("Save"));
    await screen.findByText("Saved.");
    const w = calls.find(c => c.key === "PUT /api/filemanager/write")!;
    expect(w.body).toEqual({ path: "files/notes.txt", content: "hello!", expected_modified: 777 });
  });

  it("shows the server's refusal when the file changed underneath", async () => {
    mockServer(listRoutes({
      "GET /api/filemanager/read": () => ({ path: "files/notes.txt", content: "hello", modified: 1, editable: true }),
      "PUT /api/filemanager/write": () => fail(409, "Conflict", "The file changed since you opened it") }));
    render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    fireEvent.click(await screen.findByLabelText("Open notes.txt"));
    fireEvent.change(await screen.findByLabelText("File contents"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Save"));
    expect(await screen.findByText(/changed since you opened it/)).toBeTruthy();
  });

  it("asks before deleting and deletes a folder recursively", async () => {
    const calls = mockServer(listRoutes({ "POST /api/filemanager/delete": () => ({ deleted: "files/docs" }) }));
    render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    fireEvent.click(await screen.findByLabelText("Delete docs"));
    expect(calls.some(c => c.key === "POST /api/filemanager/delete")).toBe(false);
    fireEvent.click(screen.getByText("Delete permanently"));
    await screen.findByText("Deleted.");
    expect(calls.find(c => c.key === "POST /api/filemanager/delete")!.body).toEqual({ path: "files/docs", recursive: true });
  });

  it("cancel keeps the file", async () => {
    const calls = mockServer(listRoutes());
    render(<FileExplorer />);
    fireEvent.click(await screen.findByLabelText("Open folder apps"));
    fireEvent.click(await screen.findByLabelText("Delete notes.txt"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(calls.some(c => c.key === "POST /api/filemanager/delete")).toBe(false);
  });
});

describe("File explorer deep link", () => {
  it("opens the folder named in the link", async () => {
    const calls = mockServer(listRoutes());
    render(<FileExplorer initialPath="apps/shop/doctype/gadget" />);
    await screen.findByText("Upload files");
    expect(calls[0].url.searchParams.get("path")).toBe("apps/shop/doctype/gadget");
  });
});
