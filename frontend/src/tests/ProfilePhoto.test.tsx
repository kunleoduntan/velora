import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setSession } from "../api";
import ProfilePhoto from "../components/ProfilePhoto";
import { mockServer } from "./helpers";

beforeEach(() => { setSession({ user: "sam", roles: "HR Manager" }); });

describe("Profile photo", () => {
  it("shows initials until a picture exists and asks to save a new record first", () => {
    render(<ProfilePhoto doctype="Employee" name={null} imageId="" title="Tunde Bello" canWrite onChange={() => {}} />);
    expect(screen.getByText("TB")).toBeTruthy();
    expect(screen.getByText("Save first, then add a photo.")).toBeTruthy();
  });
  it("uploads a chosen image as an attachment and hands its id to the form", async () => {
    const onChange = vi.fn();
    mockServer({ "POST /api/files": () => ({ id: "f123", file_name: "me.png" }) });
    render(<ProfilePhoto doctype="Employee" name="E-1" imageId="" title="Tunde Bello" canWrite onChange={onChange} />);
    const file = new File([new Uint8Array([1, 2, 3])], "me.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Choose photo"), { target: { files: [file] } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("f123"));
  });
  it("rejects a file that is not an image", async () => {
    const onChange = vi.fn();
    render(<ProfilePhoto doctype="Employee" name="E-1" imageId="" title="Tunde Bello" canWrite onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Choose photo"), { target: { files: [new File(["x"], "cv.pdf", { type: "application/pdf" })] } });
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/image file/));
    expect(onChange).not.toHaveBeenCalled();
  });
});
