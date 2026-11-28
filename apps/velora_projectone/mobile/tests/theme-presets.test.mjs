import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const root = new URL('../', import.meta.url);
const read = (name) => readFile(new URL(name, root), 'utf8');

test('five named colour themes are available', async () => {
  const app = await read('App.tsx');
  for (const key of ['classic','ocean','midnight','emerald','rose']) assert.match(app, new RegExp(`${key}:\\s*\\{`));
  for (const label of ['Velora Classic','Ocean Blue','Executive Midnight','Emerald','Rose']) assert.ok(app.includes(label));
});
test('colour theme selection is persisted independently of light dark system mode', async () => {
  const app = await read('App.tsx');
  assert.match(app, /THEME_PRESET_STORAGE_KEY/);
  assert.match(app, /SecureStore\.getItemAsync\(THEME_PRESET_STORAGE_KEY\)/);
  assert.match(app, /SecureStore\.setItemAsync\(THEME_PRESET_STORAGE_KEY, preset\)/);
  assert.match(app, /themePreset,onThemePresetChange/);
});
test('each preset provides light and dark palette overrides', async () => {
  const app = await read('App.tsx');
  for (const key of ['classic','ocean','midnight','emerald','rose']) {
    const start = app.indexOf(`${key}: {`);
    assert.ok(start >= 0);
    const section = app.slice(start, start + 400);
    assert.match(section, /light:/);
    assert.match(section, /dark:/);
  }
});
