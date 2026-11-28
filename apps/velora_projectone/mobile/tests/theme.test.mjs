import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const read = (name) => readFile(new URL(name, root), 'utf8');

test('mobile app exposes light, dark and system appearance choices', async () => {
  const app = await read('App.tsx');
  for (const mode of ['light', 'dark', 'system']) assert.match(app, new RegExp(`\\['${mode}'`));
  assert.match(app, /Follow your device appearance/);
});

test('theme preference is stored in platform secure storage and restored', async () => {
  const app = await read('App.tsx');
  assert.match(app, /SecureStore\.getItemAsync\(THEME_STORAGE_KEY\)/);
  assert.match(app, /SecureStore\.setItemAsync\(THEME_STORAGE_KEY, mode\)/);
  assert.match(app, /Appearance\.addChangeListener/);
});

test('dark and light palettes define core semantic colours', async () => {
  const app = await read('App.tsx');
  assert.match(app, /light:\s*\{/);
  assert.match(app, /dark:\s*\{/);
  for (const token of ['bg:', 'card:', 'text:', 'muted:', 'border:', 'inputBg:']) assert.ok(app.includes(token));
});

test('theme selector is accessible and release metadata is advanced', async () => {
  const app = await read('App.tsx');
  const config = await read('app.json');
  const pkg = JSON.parse(await read('package.json'));
  assert.equal(pkg.dependencies['expo-system-ui'], '~6.0.9');
  assert.match(app, /accessibilityRole="radio"/);
  assert.match(app, /Mobile app 1\.4\.0/);
  assert.match(config, /"version": "1\.4\.0"/);
  assert.match(config, /"userInterfaceStyle": "automatic"/);
  assert.equal(pkg.version, '1.4.0');
});
