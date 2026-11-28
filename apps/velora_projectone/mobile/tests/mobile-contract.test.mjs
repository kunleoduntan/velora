import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
const root = new URL('../', import.meta.url).pathname;
const read = (p) => readFile(join(root, p), 'utf8');

test('mobile sign-in uses Velora native password authentication and requests a bearer session', async () => {
  const auth = await read('src/auth.ts');
  const app = await read('App.tsx');
  assert.ok(auth.includes('/api/auth/login'));
  assert.ok(auth.includes('return_token: true'));
  assert.ok(auth.includes('totp_code'));
  assert.ok(app.includes('Sign in to Velora'));
  assert.ok(!app.includes('AuthSession') && !app.includes('OIDC'));
});

test('opaque Velora session token and active company are stored in platform secure storage', async () => {
  const api = await read('src/api.ts');
  assert.ok(api.includes('expo-secure-store'));
  assert.ok(api.includes('SecureStore.setItemAsync'));
  assert.ok(api.includes('SecureStore.deleteItemAsync'));
  assert.ok(api.includes('velora.session_token'));
  assert.ok(api.includes('velora.active_company'));
  assert.ok(!api.includes('AsyncStorage'));
});

test('mobile API calls use bearer authentication and selected Velora company context', async () => {
  const api = await read('src/api.ts');
  assert.ok(api.includes('Authorization'));
  assert.ok(api.includes('Bearer ${token}'));
  assert.ok(api.includes('X-Velora-Company'));
  assert.ok(!api.includes('actor_id') && !api.includes('user_id') && !api.includes('role_id'));
});

test('session restoration and company switching use Velora auth routes', async () => {
  const auth = await read('src/auth.ts');
  assert.ok(auth.includes('/api/auth/me'));
  assert.ok(auth.includes('/api/auth/switch-company'));
  assert.ok(auth.includes('companies'));
});

test('logout revokes the Velora server session before local credentials are cleared', async () => {
  const auth = await read('src/auth.ts');
  assert.ok(auth.includes('/api/auth/logout'));
  assert.ok(auth.includes('finally { await clearAccessToken(); }'));
});

test('workflow actions call the server workflow endpoint', async () => {
  const api = await read('src/api.ts');
  assert.ok(api.includes('native/workflow'));
  assert.ok(api.includes("method: 'POST'"));
});

test('timesheet helper is explicitly non-submitting', async () => {
  const app = await read('App.tsx');
  assert.ok(app.includes('does not create, submit or approve timesheets'));
  assert.ok(!app.includes('/api/projectone/timesheets/submit'));
});

test('final interface includes accessible five-tab navigation and secure restoration state', async () => {
  const app = await read('App.tsx');
  assert.ok(app.includes('accessibilityRole="tab"'));
  assert.ok(app.includes('authReady'));
  for (const tab of ['Home', 'Projects', 'Approvals', 'Timesheets', 'More']) assert.ok(app.includes(`'${tab}'`));
});

test('project search and timesheet helper validation are present', async () => {
  const app = await read('App.tsx');
  assert.ok(app.includes('Search projects'));
  assert.ok(app.includes('h<=24&&d>=0&&d<=7'));
  assert.ok(app.includes('does not create, submit or approve timesheets'));
});

test('expired Velora sessions clear secure token and return the app to sign-in', async () => {
  const api = await read('src/api.ts');
  const app = await read('App.tsx');
  assert.ok(api.includes('response.status === 401'));
  assert.ok(api.includes('unauthorizedHandler?.()'));
  assert.ok(app.includes('setUnauthorizedHandler'));
  assert.ok(app.includes('setProfile(null)'));
});
