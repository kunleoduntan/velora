import test from 'node:test';
import assert from 'node:assert/strict';
import { validateBuildEnvironment } from '../scripts/check-build-config.mjs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { DEFAULT_API_BASE, resolvePublicConfig } = require('../scripts/public-config.cjs');

test('default API address is the deployment URL supplied by the user', () => {
  assert.equal(DEFAULT_API_BASE, 'https://projectone.yourdomain.com');
  assert.equal(resolvePublicConfig({}).projectOneApiBase, DEFAULT_API_BASE);
});

test('environment variables override the default Velora API address', () => {
  const config = resolvePublicConfig({ EXPO_PUBLIC_PROJECTONE_API_BASE: 'https://staging.example.org/' });
  assert.equal(config.projectOneApiBase, 'https://staging.example.org');
});

test('build configuration accepts the existing Velora authentication integration without OIDC settings', () => {
  assert.equal(validateBuildEnvironment({}).ok, true);
});

test('build configuration rejects insecure endpoints and invalid URL values', () => {
  const result = validateBuildEnvironment({ EXPO_PUBLIC_PROJECTONE_API_BASE: 'http://projectone.example.com' });
  assert.equal(result.ok, false);
  assert.ok(result.invalid.some((item) => item.includes('must use HTTPS')));
});

test('build configuration rejects API URLs with embedded credentials or query parameters', () => {
  const result = validateBuildEnvironment({ EXPO_PUBLIC_PROJECTONE_API_BASE: 'https://user:pass@example.org/api?x=1' });
  assert.equal(result.ok, false);
  assert.ok(result.invalid.some((item) => item.includes('credentials')));
  assert.ok(result.invalid.some((item) => item.includes('query parameters')));
});
