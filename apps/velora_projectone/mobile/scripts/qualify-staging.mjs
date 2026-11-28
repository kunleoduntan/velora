#!/usr/bin/env node
/**
 * Live Velora Framework v1.13.0 + ProjectOne Mobile v1.4.0 staging qualifier.
 * Required: EXPO_PUBLIC_PROJECTONE_API_BASE, VELORA_TEST_EMAIL, VELORA_TEST_PASSWORD
 * Optional: VELORA_TEST_TOTP, VELORA_TEST_SWITCH_COMPANY_ID
 * Never prints passwords, TOTP values, or bearer tokens. Use a dedicated staging account.
 */
const base = (process.env.EXPO_PUBLIC_PROJECTONE_API_BASE || "").replace(/\/$/, "");
const email = process.env.VELORA_TEST_EMAIL || "";
const password = process.env.VELORA_TEST_PASSWORD || "";
const totp = process.env.VELORA_TEST_TOTP || "";
const switchCompanyId = process.env.VELORA_TEST_SWITCH_COMPANY_ID || "";
const deniedCompanyId = process.env.VELORA_TEST_DENIED_COMPANY_ID || "__VELORA_MOBILE_QUALIFICATION_NO_ACCESS__";
const checks = [];
function record(name, ok, detail = "") {
  checks.push({ name, ok: ok === null ? null : Boolean(ok), detail });
  const status = ok === null ? "SKIP" : ok ? "PASS" : "FAIL";
  console.log(`${status} ${name}${detail ? ` — ${detail}` : ""}`);
}
function assertConfig() {
  let parsed;
  try { parsed = new URL(base); } catch {}
  if (!parsed || parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
    console.error("FAIL Configuration — set EXPO_PUBLIC_PROJECTONE_API_BASE to an HTTPS origin without credentials, query or fragment.");
    process.exit(2);
  }
  if (!email || !password) {
    console.error("FAIL Credentials — set VELORA_TEST_EMAIL and VELORA_TEST_PASSWORD in your local shell; do not commit them.");
    process.exit(2);
  }
}
async function request(path, { method = "GET", token, company, body } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (company) headers["X-Velora-Company"] = company;
  const response = await fetch(`${base}${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body), redirect: "error",
  });
  let payload = {};
  const raw = await response.text();
  try { payload = raw ? JSON.parse(raw) : {}; } catch { payload = { message: raw.slice(0, 300) }; }
  return { response, payload };
}
async function main() {
  assertConfig();
  const config = await request("/api/auth/config");
  record("Public authentication configuration", config.response.ok && config.payload?.data?.mode === "password", `HTTP ${config.response.status}`);
  if (!config.response.ok) throw new Error("Authentication configuration endpoint failed.");

  const anonymous = await request("/api/auth/me");
  record("Unauthenticated session is rejected", anonymous.response.status === 401, `HTTP ${anonymous.response.status}`);
  if (anonymous.response.status !== 401) throw new Error("Unauthenticated /me did not return HTTP 401.");

  const loginBody = { email, password, return_token: true };
  if (totp) loginBody.totp_code = totp;
  const login = await request("/api/auth/login", { method: "POST", body: loginBody });
  const token = login.payload?.data?.token;
  const profile = login.payload?.data;
  record("Password/MFA login returns a bearer session", login.response.ok && typeof token === "string" && token.length >= 32,
    `HTTP ${login.response.status}; token ${token ? "present" : "missing"}`);
  if (!login.response.ok || !token) throw new Error("Login failed or Framework did not return a mobile token.");

  try {
    const companies = Array.isArray(profile.companies) ? profile.companies : [];
    const activeCompany = profile.active_company || profile.default_company || "";
    let expectedActiveCompany = profile.active_company || null;
    record("Login profile contains user and company context", Boolean(profile.user?.email) && Array.isArray(profile.companies),
      `${companies.length} authorised company membership(s)`);
    if (!profile.user?.email || !Array.isArray(profile.companies)) throw new Error("Unexpected profile response shape.");

    const me = await request("/api/auth/me", { token, company: activeCompany || undefined });
    record("Bearer session restoration via /me", me.response.ok && me.payload?.data?.user?.email === profile.user.email, `HTTP ${me.response.status}`);
    if (!me.response.ok) throw new Error("Bearer session restoration failed.");

    if (switchCompanyId) {
      if (!companies.some((company) => company.id === switchCompanyId)) throw new Error("Requested test company is not in the authenticated user's authorised company list.");
      const switched = await request("/api/auth/switch-company", { method: "POST", token, body: { company_id: switchCompanyId } });
      record("Authorised company switch", switched.response.ok && switched.payload?.data?.id === switchCompanyId, `HTTP ${switched.response.status}`);
      if (!switched.response.ok) throw new Error("Company switch failed.");
      const scoped = await request("/api/auth/me", { token, company: switchCompanyId });
      record("Session resolves under selected company", scoped.response.ok, `HTTP ${scoped.response.status}`);
      if (!scoped.response.ok) throw new Error("Selected company context could not be resolved.");
      if (activeCompany && activeCompany !== switchCompanyId) {
        const restored = await request("/api/auth/switch-company", { method: "POST", token, body: { company_id: activeCompany } });
        record("Restore original active company", restored.response.ok, `HTTP ${restored.response.status}`);
        if (!restored.response.ok) throw new Error("Could not restore original company selection.");
        expectedActiveCompany = activeCompany;
      }
    } else {
      record("Authorised company switching", null, "not exercised; set VELORA_TEST_SWITCH_COMPANY_ID for a multi-company account");
    }

    if (companies.some((company) => company.id === deniedCompanyId) || deniedCompanyId === switchCompanyId) {
      throw new Error("VELORA_TEST_DENIED_COMPANY_ID must identify a company not authorised for this test user.");
    }
    const deniedSwitch = await request("/api/auth/switch-company", {
      method: "POST", token, body: { company_id: deniedCompanyId },
    });
    record("Unauthorised company switch is rejected", deniedSwitch.response.status === 403,
      `HTTP ${deniedSwitch.response.status}`);
    if (deniedSwitch.response.status !== 403) throw new Error("Framework did not reject the unauthorised company switch with HTTP 403.");
    const afterDeniedSwitch = await request("/api/auth/me", { token });
    const expectedCompany = expectedActiveCompany;
    record("Denied switch leaves active company unchanged",
      afterDeniedSwitch.response.ok && (afterDeniedSwitch.payload?.data?.active_company || null) === expectedCompany,
      `HTTP ${afterDeniedSwitch.response.status}`);
    if (!afterDeniedSwitch.response.ok || (afterDeniedSwitch.payload?.data?.active_company || null) !== expectedCompany) {
      throw new Error("Active company changed after a denied company switch.");
    }

    const health = await request("/api/projectone/health", { token, company: expectedCompany || undefined });
    record("ProjectOne server health endpoint", health.response.ok && health.payload?.data?.version === "2.15.0",
      `HTTP ${health.response.status}`);
    if (!health.response.ok) throw new Error("ProjectOne health endpoint could not be reached with the mobile session.");

    const logout = await request("/api/auth/logout", { method: "POST", token });
    record("Server-side logout", logout.response.ok && logout.payload?.data?.signed_out === true, `HTTP ${logout.response.status}`);
    if (!logout.response.ok) throw new Error("Logout endpoint failed.");
    const afterLogout = await request("/api/auth/me", { token });
    record("Revoked token cannot be reused", afterLogout.response.status === 401, `HTTP ${afterLogout.response.status}`);
    if (afterLogout.response.status !== 401) throw new Error("Token remained usable after logout.");
  } catch (error) {
    try { await request("/api/auth/logout", { method: "POST", token }); } catch {}
    throw error;
  }
  const failed = checks.filter((item) => item.ok === false);
  const passed = checks.filter((item) => item.ok === true);
  const skipped = checks.filter((item) => item.ok === null);
  console.log(`\nStaging qualification: ${passed.length} passed, ${failed.length} failed, ${skipped.length} skipped.`);
  if (failed.length) process.exitCode = 1;
}
main().catch((error) => { console.error(`\nSTAGING QUALIFICATION STOPPED: ${error.message}`); process.exitCode = 1; });
