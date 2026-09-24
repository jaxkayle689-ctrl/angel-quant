from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .strategy_api import validate_signal_frame
from .strategy_registry import get_strategy


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    summary: dict[str, float | int]


def run_strategy_backtest(
    frame: pd.DataFrame,
    strategy_id: str = "sma_crossover",
    parameters: dict[str, object] | None = None,
    initial_cash: float = 1000.0,
    fee_rate: float = 0.001,
    leverage: int = 1,
) -> BacktestResult:
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive.")
    if fee_rate < 0:
        raise ValueError("fee_rate cannot be negative.")
    if leverage < 1:
        raise ValueError("leverage must be at least 1.")

    strategy = get_strategy(strategy_id)
    data = validate_signal_frame(strategy.generate(frame, parameters or {})).copy()
    data["trade_signal"] = data["signal"].shift(1).fillna(0).astype(int)

    equity = float(initial_cash)
    previous_price: float | None = None
    previous_position = 0
    trades: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    for _, row in data.iterrows():
        price = float(row["close"])
        target_position = int(row["trade_signal"])
        if previous_price is not None:
            market_return = price / previous_price - 1
            equity *= max(0.0, 1 + previous_position * market_return * leverage)

        if target_position != previous_position:
            turnover = abs(target_position - previous_position)
            equity *= max(0.0, 1 - fee_rate * turnover * leverage)
            if previous_position != 0:
                trades.append(
                    {
                        "time": row["open_time"],
                        "side": "CLOSE_LONG" if previous_position == 1 else "CLOSE_SHORT",
                        "price": price,
                        "position": previous_position,
                        "equity_after": equity,
                    }
                )
            if target_position != 0:
                trades.append(
                    {
                        "time": row["open_time"],
                        "side": "OPEN_LONG" if target_position == 1 else "OPEN_SHORT",
                        "price": price,
                        "position": target_position,
                        "equity_after": equity,
                    }
                )

        previous_price = price
        previous_position = target_position
        equity_rows.append(
            {
                "time": row["open_time"],
                "close": price,
                "equity": equity,
                "signal": target_position,
            }
        )

    equity_curve = pd.DataFrame(equity_rows)
    trades_frame = pd.DataFrame(trades)
    if equity_curve.empty:
        summary: dict[str, float | int] = {
            "initial_cash": initial_cash,
            "final_equity": initial_cash,
            "total_return_pct": 0.0,
            "buy_and_hold_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_count": 0,
        }
        return BacktestResult(equity_curve, trades_frame, summary)

    final_equity = float(equity_curve["equity"].iloc[-1])
    first_close = float(data["close"].iloc[0])
    last_close = float(data["close"].iloc[-1])
    rolling_high = equity_curve["equity"].cummax()
    drawdown = equity_curve["equity"] / rolling_high - 1
    summary = {
        "initial_cash": round(initial_cash, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round((final_equity / initial_cash - 1) * 100, 2),
        "buy_and_hold_return_pct": round((last_close / first_close - 1) * 100, 2),
        "max_drawdown_pct": round(float(drawdown.min() * 100), 2),
        "trade_count": int(len(trades_frame)),
    }
    return BacktestResult(equity_curve, trades_frame, summary)


def run_sma_backtest(
    frame: pd.DataFrame,
    fast: int = 20,
    slow: int = 60,
    initial_cash: float = 1000.0,
    fee_rate: float = 0.001,
) -> BacktestResult:
    return run_strategy_backtest(
        frame,
        strategy_id="sma_crossover",
        parameters={"fast": fast, "slow": slow, "direction": "LONG_ONLY"},
        initial_cash=initial_cash,
        fee_rate=fee_rate,
    )
