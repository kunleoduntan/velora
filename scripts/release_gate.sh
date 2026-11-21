#!/bin/sh
# Release gate: refuses to package a release whose Desk bundle is stale or whose tests fail.
# Usage: scripts/release_gate.sh   (run from anywhere; needs node, python venv with pytest active)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
echo "== 1/5 type check";      npx tsc --noEmit
echo "== 2/5 frontend tests";  npx vitest run
echo "== 3/5 build desk";      npm run build
echo "== 4/5 bundle freshness"
rm -rf "$ROOT/velora/desk" && cp -r dist "$ROOT/velora/desk"
if ! diff -rq dist "$ROOT/velora/desk" >/dev/null; then echo "Desk bundle differs from the build"; exit 1; fi
cd "$ROOT"
echo "== 5/5 backend tests"
PYTHONPATH="$ROOT:$ROOT/apps/velora_erp:$ROOT/apps/velora_accounts:$ROOT/apps/velora_demo:$ROOT/apps/velora_erp/tests" python -m pytest -q -p no:cacheprovider
python scripts/release_preflight.py
echo "RELEASE GATE PASSED"
