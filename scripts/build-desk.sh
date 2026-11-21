#!/bin/sh
# Build the React Desk and bundle it inside the Python package so `pip install velora` ships a working UI.
set -e
cd "$(dirname "$0")/../frontend"
npm ci --no-audit --no-fund
npm run build
rm -rf ../velora/desk
cp -r dist ../velora/desk
echo "Desk bundled into velora/desk"
