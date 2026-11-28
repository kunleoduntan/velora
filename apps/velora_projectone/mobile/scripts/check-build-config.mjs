import { createRequire } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
const require = createRequire(import.meta.url);
const { resolvePublicConfig } = require('./public-config.cjs');

function loadDotEnv(filePath = resolve(process.cwd(), '.env')) {
  if (!existsSync(filePath)) return {};
  const values = {};
  for (const line of readFileSync(filePath, 'utf8').split(/\\r?\\n/)) {
    const match = line.match(/^\\s*(?:export\\s+)?([A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*(.*?)\\s*$/);
    if (!match || match[1].startsWith('#')) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    values[match[1]] = value;
  }
  return values;
}

export function validateBuildEnvironment(env = process.env) {
  const effectiveEnv = { ...loadDotEnv(), ...env };
  const config = resolvePublicConfig(effectiveEnv);
  const missing = [];
  const invalid = [];
  if (!config.projectOneApiBase) missing.push('EXPO_PUBLIC_PROJECTONE_API_BASE');
  try {
    const parsed = new URL(config.projectOneApiBase);
    if (parsed.protocol !== 'https:') invalid.push('EXPO_PUBLIC_PROJECTONE_API_BASE must use HTTPS');
    if (parsed.username || parsed.password) invalid.push('EXPO_PUBLIC_PROJECTONE_API_BASE must not contain embedded credentials');
    if (parsed.search || parsed.hash) invalid.push('EXPO_PUBLIC_PROJECTONE_API_BASE must not contain query parameters or a fragment');
  } catch {
    invalid.push('EXPO_PUBLIC_PROJECTONE_API_BASE must be a valid absolute URL');
  }
  return { ok: missing.length === 0 && invalid.length === 0, missing, invalid, config };
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const result = validateBuildEnvironment();
  if (!result.ok) {
    console.error('Mobile build configuration is incomplete.');
    for (const item of result.missing) console.error(`  Missing: ${item}`);
    for (const item of result.invalid) console.error(`  Invalid: ${item}`);
    process.exitCode = 1;
  } else {
    console.log('Mobile build configuration checks passed.');
    console.log(`ProjectOne API: ${result.config.projectOneApiBase}`);
    console.log('Authentication: Velora native password/session API');
  }
}
