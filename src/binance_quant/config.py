from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_secret: str
    base_url: str
    recv_window: int
    allow_live_trading: bool


@dataclass(frozen=True)
class FuturesSettings:
    api_key: str
    api_secret: str
    base_url: str
    recv_window: int
    allow_live_trading: bool


def load_settings(env_file: str = ".env") -> Settings:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    return Settings(
        api_key=os.getenv("BINANCE_API_KEY", "").strip(),
        api_secret=os.getenv("BINANCE_API_SECRET", "").strip(),
        base_url=os.getenv("BINANCE_BASE_URL", "https://testnet.binance.vision").rstrip("/"),
        recv_window=int(os.getenv("BINANCE_RECV_WINDOW", "5000")),
        allow_live_trading=_as_bool(os.getenv("ALLOW_LIVE_TRADING"), default=False),
    )


def load_futures_settings(env_file: str = ".env") -> FuturesSettings:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    return FuturesSettings(
        api_key=os.getenv("BINANCE_FUTURES_API_KEY", "").strip(),
        api_secret=os.getenv("BINANCE_FUTURES_API_SECRET", "").strip(),
        base_url=os.getenv("BINANCE_FUTURES_BASE_URL", "https://demo-fapi.binance.com").rstrip("/"),
        recv_window=int(os.getenv("BINANCE_FUTURES_RECV_WINDOW", "5000")),
        allow_live_trading=_as_bool(os.getenv("ALLOW_FUTURES_LIVE_TRADING"), default=False),
    )
