import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setAuthMode, setProfile, setSession } from "../api";
import AppearanceMenu from "../components/AppearanceMenu";
import ThemeSettings from "../components/ThemeSettings";
import { loadAppearance } from "../theme";
import { fail, mockServer, themeState } from "./helpers";

beforeEach(() => {
  document.head.innerHTML = ""; document.documentElement.removeAttribute("data-theme"); localStorage.clear(); sessionStorage.clear();
  setAuthMode("developer"); setProfile(null); setSession({ user: "boss", roles: "System Manager" });
});

const preview = (spec: any) => themeState({ spec, brand: spec.preset === "farepoint" ? "#e91e8c" : "#0f6cbd", css: `:root{--brand:${spec.preset}}` });

describe("Theme settings", () => {
  it("shows presets, the saved choice, a light AND dark preview, the Excel palette and the accessibility result", async () => {
    mockServer({ "GET /api/theme": () => themeState() });
    render(<ThemeSettings />);
    await screen.findByRole("radio", { name: /Velora/ });
    expect(screen.getByRole("radio", { name: /Velora/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /Farepoint/ }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByTestId("preview-light")).toBeTruthy();
    expect(screen.getByTestId("preview-dark")).toBeTruthy();
    expect((screen.getByTestId("preview-dark") as HTMLElement).style.getPropertyValue("--bg")).toBe("#1b1a19");     // the dark preview really uses the dark tokens
    expect((screen.getByTestId("excel-preview").firstChild as HTMLElement).style.background).toContain("rgb(213, 233, 255)");   // #d5e9ff
    expect(screen.getByTestId("audit-summary").textContent).toContain("All 40 contrast checks pass");
  });

  it("choosing a preset previews it live (server-compiled, applied instantly) and enables Save only when changed", async () => {
    const calls = mockServer({
      "GET /api/theme": () => themeState(),
      "POST /api/theme/preview": ({ body }: any) => preview(body),
    });
    render(<ThemeSettings />);
    const save = await screen.findByRole("button", { name: "Save theme" });
    expect(save.hasAttribute("disabled")).toBe(true);                                  // nothing changed yet
    fireEvent.click(screen.getByRole("radio", { name: /Farepoint/ }));
    await waitFor(() => expect(document.getElementById("velora-theme")?.textContent).toBe(":root{--brand:farepoint}"));
    expect(calls.find((c) => c.key === "POST /api/theme/preview")!.body.preset).toBe("farepoint");
    expect(screen.getByText(/Unsaved changes/)).toBeTruthy();
    expect(save.hasAttribute("disabled")).toBe(false);
    expect(calls.some((c) => c.key === "PUT /api/theme")).toBe(false);                 // previewing never stores anything
  });

  it("saves the chosen settings and confirms", async () => {
    const calls = mockServer({
      "GET /api/theme": () => themeState(),
      "POST /api/theme/preview": ({ body }: any) => preview(body),
      "PUT /api/theme": ({ body }: any) => preview(body),
    });
    render(<ThemeSettings />);
    await screen.findByRole("radio", { name: /Velora/ });
    fireEvent.click(screen.getByRole("radio", { name: /Farepoint/ }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Corners" })).getByRole("radio", { name: "Round" }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Density" })).getByRole("radio", { name: /^Compact/ }));
    fireEvent.change(screen.getByLabelText("Company name in the header"), { target: { value: "Velora Technologies" } });
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/theme/preview" && c.body.brand_name === "Velora Technologies")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Save theme" }));
    const put = calls.find((c) => c.key === "PUT /api/theme")!.body;
    expect(put).toMatchObject({ preset: "farepoint", radius: "round", density: "compact", brand_name: "Velora Technologies", brand: null });
    expect(await screen.findByText(/Theme saved/)).toBeTruthy();
  });

  it("a custom brand colour is validated before anything is sent", async () => {
    const calls = mockServer({ "GET /api/theme": () => themeState(), "POST /api/theme/preview": ({ body }: any) => preview(body) });
    render(<ThemeSettings />);
    await screen.findByRole("radio", { name: /Velora/ });
    fireEvent.change(screen.getByLabelText("Brand colour"), { target: { value: "not-a-colour" } });
    expect(await screen.findByText(/Use a hex colour/)).toBeTruthy();
    await new Promise((r) => setTimeout(r, 350));
    expect(calls.some((c) => c.key === "POST /api/theme/preview")).toBe(false);          // invalid input never reaches the server
    expect(screen.getByRole("button", { name: "Save theme" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByLabelText("Brand colour"), { target: { value: "#7a3cff" } });
    await waitFor(() => expect(calls.find((c) => c.key === "POST /api/theme/preview")?.body.brand).toBe("#7a3cff"));
    fireEvent.click(screen.getByRole("button", { name: "Use the preset colour" }));
    expect((screen.getByLabelText("Brand colour") as HTMLInputElement).value).toBe("");
  });

  it("Revert restores the saved theme", async () => {
    mockServer({ "GET /api/theme": () => themeState({ css: ":root{--brand:saved}" }), "POST /api/theme/preview": ({ body }: any) => preview(body) });
    render(<ThemeSettings />);
    await screen.findByRole("radio", { name: /Velora/ });
    fireEvent.click(screen.getByRole("radio", { name: /Verdant/ }));
    await waitFor(() => expect(document.getElementById("velora-theme")?.textContent).toBe(":root{--brand:verdant}"));
    fireEvent.click(screen.getByRole("button", { name: "Revert" }));
    expect(document.getElementById("velora-theme")?.textContent).toBe(":root{--brand:saved}");
    expect(screen.getByRole("radio", { name: /Velora/ }).getAttribute("aria-checked")).toBe("true");
  });

  it("surfaces failing contrast checks instead of hiding them", async () => {
    const audit = [{ mode: "dark", pair: "muted text on surface", fg: "#555", bg: "#333", ratio: 1.9, required: 4.5, pass: false }, { mode: "light", pair: "text on surface", fg: "#000", bg: "#fff", ratio: 21, required: 7, pass: true }];
    mockServer({ "GET /api/theme": () => themeState({ audit }) });
    render(<ThemeSettings />);
    expect((await screen.findByTestId("audit-summary")).textContent).toBe("1 of 2 contrast checks fail");
    fireEvent.click(screen.getByText("Show every check"));
    expect(screen.getByText("1.90:1")).toBeTruthy();
    expect(screen.getAllByText("fail")).toHaveLength(1);
  });

  it("is read-only for people who cannot edit, and says why", async () => {
    mockServer({ "GET /api/theme": () => themeState({ can_edit: false }) });
    render(<ThemeSettings />);
    expect(await screen.findByText(/Only a System Manager/)).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Farepoint/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Save theme" }).hasAttribute("disabled")).toBe(true);
    expect((screen.getByLabelText("Brand colour") as HTMLInputElement).disabled).toBe(true);
  });

  it("shows server-side validation errors", async () => {
    mockServer({ "GET /api/theme": () => themeState(), "POST /api/theme/preview": () => fail(422, "ThemeError", "Invalid theme: radius must be one of square, soft, round") });
    render(<ThemeSettings />);
    await screen.findByRole("radio", { name: /Velora/ });
    fireEvent.click(screen.getByRole("radio", { name: /Verdant/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("Invalid theme");
  });
});

describe("Appearance menu", () => {
  it("personal light/dark + density apply instantly, persist, and can return to the company default", async () => {
    const theme = themeState({ default_mode: "light", spec: { density: "comfortable" } }) as any;
    render(<AppearanceMenu theme={theme} />);
    fireEvent.click(screen.getByRole("button", { name: /Appearance/ }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Mode" })).getByRole("radio", { name: /^Dark/ }));
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Density" })).getByRole("radio", { name: /^Compact/ }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-density")).toBe("compact");
    expect(loadAppearance()).toEqual({ mode: "dark", density: "compact" });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Mode" })).getByRole("radio", { name: /^Company default/ }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("is not offered when the company disables personal overrides", () => {
    const { container } = render(<AppearanceMenu theme={themeState({ spec: { allow_user_override: false } }) as any} />);
    expect(container.textContent).toBe("");
  });
});
