import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../scripts/check-release-env.mjs', import.meta.url), 'utf8');

test('release environment rejects the example API host', () => {
  assert.match(source, /yourdomain\.com/);
  assert.match(source, /endsWith\('.example'\)/);
  assert.match(source, /actual deployment host/);
});

test('release environment requires a real configured HTTPS host', () => {
  assert.match(source, /validateBuildEnvironment/);
  assert.match(source, /process\.exit\(1\)/);
});
