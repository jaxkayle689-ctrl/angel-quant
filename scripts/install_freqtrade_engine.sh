#!/bin/sh
set -eu

RUNTIME_DIR="$HOME/Library/Application Support/Binance Quant/freqtrade-runtime"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Python 3.12 is required. Install it with: brew install python@3.12" >&2
  exit 1
fi

if command -v brew >/dev/null 2>&1 && ! brew list ta-lib >/dev/null 2>&1; then
  brew install ta-lib
fi

python3.12 -m venv "$RUNTIME_DIR"
"$RUNTIME_DIR/bin/python" -m pip install --upgrade pip
"$RUNTIME_DIR/bin/pip" install 'freqtrade==2026.7'
"$RUNTIME_DIR/bin/freqtrade" --version

echo "Freqtrade runtime installed at: $RUNTIME_DIR"
