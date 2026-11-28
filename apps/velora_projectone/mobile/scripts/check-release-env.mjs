import { validateBuildEnvironment } from './check-build-config.mjs';

const result = validateBuildEnvironment();
const errors = [...result.invalid];
if (!result.ok) errors.push(...result.missing.map((name) => `${name} is required for a release build`));
const api = result.config.projectOneApiBase;
const hostname = (() => { try { return new URL(api).hostname.toLowerCase(); } catch { return ''; } })();
if (hostname === 'yourdomain.com' || hostname.endsWith('.yourdomain.com') ||
    hostname.endsWith('.invalid') || hostname.endsWith('.example') ||
    hostname.endsWith('.test') || hostname === 'example.com' || hostname === 'localhost') {
  errors.push('EXPO_PUBLIC_PROJECTONE_API_BASE must be the actual deployment host, not an example or placeholder');
}
if (errors.length) {
  console.error('Release environment is not ready:');
  for (const error of [...new Set(errors)]) console.error(`- ${error}`);
  process.exit(1);
}
console.log(`Release API host configured: ${new URL(api).host}`);
