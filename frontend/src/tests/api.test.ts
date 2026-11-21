import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, auth, getCompany, setAuthMode, setCompany, setProfile, setSession, userKey } from "../api";
import { fail, mockServer } from "./helpers";

beforeEach(() => { setAuthMode("developer"); setProfile(null); setSession(null); sessionStorage.clear(); });

const headersOf = (calls: ReturnType<typeof mockServer>, i = -1) => {
  const f = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(i)![1] as RequestInit;
  return f.headers as Record<string, string>;
};

describe("request identity", () => {
  it("developer mode sends the identity headers and nothing else", async () => {
    setSession({ user: "sam", roles: "Sales User" });
    const calls = mockServer({ "GET /api/doctypes": () => [] });
    await api.doctypes();
    expect(headersOf(calls)).toEqual({ "X-Velora-User": "sam", "X-Velora-Roles": "Sales User" });
  });

  it("password mode sends the CSRF header + the company of THIS tab, never identity headers", async () => {
    setAuthMode("password");
    setSession({ user: "ignored", roles: "System Manager" });          // a stale developer session must not leak into password mode
    setCompany("COMP-002");
    const calls = mockServer({ "GET /api/doctypes": () => [] });
    await api.doctypes();
    expect(headersOf(calls)).toEqual({ "X-Velora-Request": "1", "X-Velora-Company": "COMP-002" });
    expect((globalThis.fetch as any).mock.calls.at(-1)[1].credentials).toBe("same-origin");     // the HttpOnly cookie travels
    setCompany(null);
    await api.doctypes();
    expect(headersOf(calls)).toEqual({ "X-Velora-Request": "1" });
  });

  it("the company lives in sessionStorage (per tab) and switching drops cached metadata", async () => {
    setAuthMode("password");
    const calls = mockServer({ "GET /api/doctypes": () => [] });
    setCompany("COMP-001");
    expect(getCompany()).toBe("COMP-001");
    await api.meta("Customer");
    await api.meta("Customer");
    expect(calls.filter((c) => c.key === "GET /api/meta/Customer")).toHaveLength(1);         // cached within a company
    setCompany("COMP-002");
    await api.meta("Customer");
    expect(calls.filter((c) => c.key === "GET /api/meta/Customer")).toHaveLength(2);         // a different company has different DocTypes
  });

  it("per-user preferences are keyed by user AND company", () => {
    setAuthMode("password");
    setProfile({ user: { email: "alice@x.com", full_name: "A", is_platform_admin: false }, companies: [], active_company: null });
    setCompany("COMP-001");
    const a = userKey();
    setCompany("COMP-002");
    expect([a, userKey()]).toEqual(["alice@x.com@COMP-001", "alice@x.com@COMP-002"]);
  });
});

describe("401 handling", () => {
  it("an expired session fires velora:unauthorized (but a wrong password at login does not)", async () => {
    setAuthMode("password");
    const seen = vi.fn();
    window.addEventListener("velora:unauthorized", seen);
    mockServer({
      "GET /api/doctypes": () => fail(401, "AuthenticationRequired", "Your session has expired. Sign in again."),
      "POST /api/auth/login": () => fail(401, "AuthenticationRequired", "Invalid email or password"),
    });
    await expect(api.doctypes()).rejects.toThrow("expired");
    expect(seen).toHaveBeenCalledTimes(1);
    await expect(auth.login("a@b.com", "x")).rejects.toThrow("Invalid email or password");
    expect(seen).toHaveBeenCalledTimes(1);
    window.removeEventListener("velora:unauthorized", seen);
  });
});
