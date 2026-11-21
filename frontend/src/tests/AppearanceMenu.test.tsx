import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import AppearanceMenu from "../components/AppearanceMenu";
import { loadAppearance } from "../theme";
import { setAuthMode, setProfile, setSession } from "../api";
import { themeState } from "./helpers";

beforeEach(() => { localStorage.clear(); setAuthMode("developer"); setProfile(null); setSession({ user: "appearance-test", roles: "System Manager" }); document.documentElement.removeAttribute("data-theme"); document.documentElement.removeAttribute("data-density"); });

describe("appearance menu", () => {
  it("applies and persists the selected theme mode and density", () => {
    render(<AppearanceMenu theme={themeState({ default_mode: "light", spec: { density: "comfortable", allow_user_override: true } })} />);
    fireEvent.click(screen.getByRole("button", { name: /Appearance/ }));
    const dlg = within(screen.getByRole("dialog"));
    fireEvent.click(dlg.getByRole("radio", { name: /^Dark/ }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(dlg.getByRole("radio", { name: /^Compact/ }));
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");
    expect(loadAppearance()).toEqual({ mode: "dark", density: "compact" });
  });
  it("does not expose personal overrides when company policy disables them", () => {
    const { container } = render(<AppearanceMenu theme={themeState({ spec: { allow_user_override: false } })} />);
    expect(container.firstChild).toBeNull();
  });
});
