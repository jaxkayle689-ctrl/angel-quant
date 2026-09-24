#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Missing .venv. Create it and install requirements-build.txt first." >&2
  exit 1
fi

cd "$PROJECT_ROOT"
sh "$PROJECT_ROOT/scripts/build_react_frontend.sh"
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "只想玩天使的量化" \
  --icon "$PROJECT_ROOT/packaging/Updated.icns" \
  --osx-bundle-identifier "com.angelquant.desktop" \
  --paths "$PROJECT_ROOT/src" \
  --add-data "$PROJECT_ROOT/src/binance_quant/web:binance_quant/web" \
  --add-data "$PROJECT_ROOT/src/binance_quant/web-react:binance_quant/web-react" \
  --add-data "$PROJECT_ROOT/src/binance_quant/resources:binance_quant/resources" \
  --hidden-import webview.platforms.cocoa \
  "$PROJECT_ROOT/scripts/desktop_entry.py"

APP_PATH="$PROJECT_ROOT/dist/只想玩天使的量化.app"
PLIST_PATH="$APP_PATH/Contents/Info.plist"
plutil -replace CFBundleDisplayName -string "只想玩天使的量化" "$PLIST_PATH"
plutil -replace CFBundleName -string "只想玩天使的量化" "$PLIST_PATH"
plutil -replace CFBundleShortVersionString -string "0.12.0" "$PLIST_PATH"
plutil -replace CFBundleVersion -string "0.12.0" "$PLIST_PATH"
codesign --force --deep --sign - "$APP_PATH"

echo "Built: $APP_PATH"
