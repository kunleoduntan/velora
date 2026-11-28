import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const workflow = readFileSync(resolve('..', '.github/workflows/android-preview.yml'), 'utf8');
const pkg = JSON.parse(readFileSync(resolve('package.json'), 'utf8'));
const app = JSON.parse(readFileSync(resolve('app.json'), 'utf8')).expo;

test('Android preview workflow runs tests and typecheck before EAS build', () => {
  assert.match(workflow, /npm test/);
  assert.match(workflow, /npm run typecheck/);
  assert.match(workflow, /eas-cli@latest build --platform android --profile preview/);
  assert.ok(workflow.indexOf('npm test') < workflow.indexOf('eas-cli@latest build'));
});

test('CI workflow uses GitHub variables for public endpoints and secret for Expo token', () => {
  assert.match(workflow, /vars\.EXPO_PUBLIC_PROJECTONE_API_BASE/);
  assert.match(workflow, /check:release-env/);
  assert.doesNotMatch(workflow, /EXPO_PUBLIC_OIDC/);
  assert.match(workflow, /secrets\.EXPO_TOKEN/);
});

test('mobile v1.4.0 metadata and native build numbers are aligned', () => {
  assert.equal(pkg.version, '1.4.0');
  assert.equal(app.version, '1.4.0');
  assert.equal(app.android.versionCode, 8);
  assert.equal(app.ios.buildNumber, '8');
});
