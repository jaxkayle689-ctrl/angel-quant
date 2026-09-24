from __future__ import annotations

import pandas as pd

from .strategy_registry import get_strategy


def sma_crossover(frame: pd.DataFrame, fast: int = 20, slow: int = 60) -> pd.DataFrame:
    strategy = get_strategy("sma_crossover")
    return strategy.generate(frame, {"fast": fast, "slow": slow, "direction": "LONG_ONLY"})


def latest_sma_signal(frame: pd.DataFrame, fast: int = 20, slow: int = 60) -> dict[str, object]:
    signals = sma_crossover(frame, fast=fast, slow=slow)
    ready = signals.dropna(subset=["fast_sma", "slow_sma"])
    if ready.empty:
        return {
            "action": "WAIT",
            "reason": f"Need at least {slow} candles before SMA signal is ready.",
        }

    latest = ready.iloc[-1]
    previous = ready.iloc[-2] if len(ready) > 1 else latest
    current_signal = int(latest["signal"])
    previous_signal = int(previous["signal"])

    if previous_signal == 0 and current_signal == 1:
        action = "BUY"
    elif previous_signal == 1 and current_signal == 0:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "action": action,
        "close": float(latest["close"]),
        "fast_sma": float(latest["fast_sma"]),
        "slow_sma": float(latest["slow_sma"]),
        "signal": current_signal,
        "open_time": latest["open_time"],
    }
