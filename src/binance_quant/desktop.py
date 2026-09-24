from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from .app_api import DashboardAPI


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        root = Path(sys._MEIPASS) / "binance_quant"
    else:
        root = Path(__file__).resolve().parent
    return root.joinpath(*parts)


def main() -> None:
    frontend_dir = "web" if os.getenv("BINANCE_QUANT_FRONTEND", "").lower() == "legacy" else "web-react"
    index_path = resource_path(frontend_dir, "index.html")
    if not index_path.exists():
        raise SystemExit(f"Desktop assets not found: {index_path}")

    api = DashboardAPI()
    webview.create_window(
        "只想玩天使的量化",
        url=index_path.as_uri(),
        js_api=api,
        width=1440,
        height=920,
        min_size=(1120, 720),
        background_color="#f7f6f0",
        text_select=True,
    )
    try:
        webview.start(
            func=api.apply_application_icon,
            gui="cocoa",
            debug=os.getenv("BINANCE_QUANT_DEBUG", "").lower() in {"1", "true", "yes"},
            private_mode=True,
        )
    finally:
        api.shutdown()


if __name__ == "__main__":
    main()
