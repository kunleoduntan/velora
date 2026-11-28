#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npm install --no-audit --no-fund
npm test
npm run check:build-config
npm run typecheck
node --check scripts/qualify-staging.mjs
node --check app.config.js
echo "Local source verification completed."
