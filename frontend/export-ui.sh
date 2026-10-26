#!/bin/sh
# Export the existing interface without modifying its source or managed preview.
set -eu
cd "$(dirname "$0")/.."
unset FIGMA_PUBLIC_URL
pnpm build
mkdir -p flask-app/ui
cp -R dist/. flask-app/ui/
