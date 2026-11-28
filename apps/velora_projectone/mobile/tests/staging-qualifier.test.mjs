import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../scripts/qualify-staging.mjs', import.meta.url), 'utf8');
test('staging qualifier requires HTTPS and local credentials', () => {
  assert.match(source, /parsed\.protocol !== "https:"/);
  assert.match(source, /VELORA_TEST_EMAIL/);
  assert.match(source, /VELORA_TEST_PASSWORD/);
});
test('staging qualifier never prints credentials or bearer token values', () => {
  assert.doesNotMatch(source, /console\.(?:log|info|warn|error)\([^)]*(?:password|totp|token)\s*[,`]/i);
  assert.match(source, /never prints passwords/i);
});
test('staging qualifier exercises login, session, company switch, logout and revocation', () => {
  for (const fragment of ['"/api/auth/config"','"/api/auth/me"','"/api/auth/login"','"/api/auth/switch-company"','"/api/auth/logout"','afterLogout.response.status === 401'])
    assert.ok(source.includes(fragment), `missing ${fragment}`);
});
test('staging qualifier only switches to a company in the returned membership list', () => {
  assert.match(source, /companies\.some\(\(company\) => company\.id === switchCompanyId\)/);
});
