#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required to build the React frontend." >&2
  exit 1
fi

cd "$PROJECT_ROOT/frontend"
npm ci --no-fund
mkdir -p public/assets
cp "$PROJECT_ROOT/src/binance_quant/web/assets/custom-icon.jpg" public/assets/custom-icon.jpg
cp "$PROJECT_ROOT/src/binance_quant/web/assets/lobby.jpg" public/assets/lobby.jpg
npm run build

# Keep the current pywebview packaging contract: the generated static site
# is copied into the Python package only after a successful React build.
rm -rf "$PROJECT_ROOT/src/binance_quant/web-react"
mkdir -p "$PROJECT_ROOT/src/binance_quant/web-react"
cp -R dist/. "$PROJECT_ROOT/src/binance_quant/web-react/"
echo "React frontend built at src/binance_quant/web-react"
