from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd


KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


class KlineClient(Protocol):
    def klines(self, symbol: str, interval: str, limit: int = 500) -> object:
        ...


def klines_to_frame(rows: list[list[object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_asset_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["number_of_trades"] = pd.to_numeric(frame["number_of_trades"], errors="coerce")
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    return frame


def fetch_klines(client: KlineClient, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    rows = client.klines(symbol=symbol, interval=interval, limit=limit)
    if not isinstance(rows, list):
        raise TypeError(f"Expected kline rows list, got {type(rows).__name__}.")
    return klines_to_frame(rows)


def save_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return output_path
