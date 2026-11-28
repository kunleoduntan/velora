import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { auth } from "../api";
import { ChangePasswordRequired, ForgotPassword, Meter, ResetWithToken, strength } from "../components/PasswordScreens";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("password screens", () => {
  it("rates passwords like the server", () => {
    expect(strength("short1").ok).toBe(false);
    expect(strength("alllowercase").ok).toBe(false);
    expect(strength("Tulip-7-garden").ok).toBe(true);
    expect(strength("a long passphrase of words").ok).toBe(true);
    expect(strength("ada.lovelace1", "ada.lovelace@x.com").ok).toBe(false);
    render(<Meter password="Tulip-7-garden" />);
    expect(screen.getByRole("status").textContent).toMatch(/Good|Strong|Fair/);
  });
  it("forgot password explains the administrator route when email is off, without revealing accounts", async () => {
    vi.spyOn(auth, "forgotPassword").mockResolvedValue({ message: "x", mode: "administrator" });
    render(<ForgotPassword onBack={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "ada@example.com" } });
    fireEvent.click(screen.getByText("Reset my password"));
    expect(await screen.findByText("Request sent to your administrator")).toBeTruthy();
  });
  it("forgot password says 'check your email' when mail is on", async () => {
    vi.spyOn(auth, "forgotPassword").mockResolvedValue({ message: "x", mode: "email" });
    render(<ForgotPassword onBack={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "ada@example.com" } });
    fireEvent.click(screen.getByText("Reset my password"));
    expect(await screen.findByText("Check your email")).toBeTruthy();
  });
  it("reset link form blocks mismatched or weak passwords and saves a good one", async () => {
    const reset = vi.spyOn(auth, "resetPassword").mockResolvedValue({ reset: true });
    render(<ResetWithToken token="abc" onDone={() => undefined} />);
    const save = screen.getByText("Save new password") as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "weak" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "weak" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "Tulip-7-garden" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "different-1X" } });
    fireEvent.click(save);
    expect((await screen.findByRole("alert")).textContent).toContain("do not match");
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "Tulip-7-garden" } });
    fireEvent.click(save);
    await waitFor(() => expect(reset).toHaveBeenCalledWith("abc", "Tulip-7-garden"));
    expect(await screen.findByText("Password changed")).toBeTruthy();
  });
  it("forces a new password after a temporary one", async () => {
    const change = vi.spyOn(auth, "changePassword").mockResolvedValue({ changed: true });
    const done = vi.fn();
    render(<ChangePasswordRequired email="ada@example.com" onDone={done} />);
    fireEvent.change(screen.getByLabelText("Temporary password"), { target: { value: "Kd7m-Qx4R-p9Wt" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "Tulip-7-garden" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "Tulip-7-garden" } });
    fireEvent.click(screen.getByText("Save and sign in again"));
    await waitFor(() => expect(change).toHaveBeenCalledWith("Kd7m-Qx4R-p9Wt", "Tulip-7-garden"));
    await waitFor(() => expect(done).toHaveBeenCalled());
  });
});
