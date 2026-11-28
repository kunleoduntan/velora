const DEFAULT_API_BASE = 'https://projectone.yourdomain.com';

function stripTrailingSlashes(value) {
  return String(value ?? '').trim().replace(/\/+$/, '');
}

function resolvePublicConfig(env = process.env) {
  return {
    projectOneApiBase: stripTrailingSlashes(env.EXPO_PUBLIC_PROJECTONE_API_BASE || DEFAULT_API_BASE),
  };
}

module.exports = { DEFAULT_API_BASE, resolvePublicConfig, stripTrailingSlashes };
