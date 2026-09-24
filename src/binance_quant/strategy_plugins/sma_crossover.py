from __future__ import annotations

from typing import Any

import pandas as pd

from ..strategy_api import ChartSeries, Strategy, StrategyParameter


class SMACrossoverStrategy(Strategy):
    strategy_id = "sma_crossover"
    name = "双均线交叉"
    description = "短均线在长均线上方做多，在下方做空或空仓。"
    parameters = (
        StrategyParameter("fast", "短均线", "integer", 20, minimum=2, maximum=200, step=1),
        StrategyParameter("slow", "长均线", "integer", 60, minimum=3, maximum=500, step=1),
        StrategyParameter(
            "direction",
            "交易方向",
            "choice",
            "LONG_SHORT",
            choices=("LONG_SHORT", "LONG_ONLY"),
        ),
    )
    chart_series = (
        ChartSeries("fast_sma", "短均线", "#f4c95d"),
        ChartSeries("slow_sma", "长均线", "#64d8a4"),
    )

    def generate(self, frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
        values = self.normalized_parameters(parameters)
        fast = values["fast"]
        slow = values["slow"]
        if fast >= slow:
            raise ValueError("短均线周期必须小于长均线周期。")

        result = frame.copy()
        close = pd.to_numeric(result["close"], errors="coerce")
        result["fast_sma"] = close.rolling(fast).mean()
        result["slow_sma"] = close.rolling(slow).mean()
        result["signal"] = 0
        ready = result["slow_sma"].notna()
        result.loc[ready & (result["fast_sma"] > result["slow_sma"]), "signal"] = 1
        if values["direction"] == "LONG_SHORT":
            result.loc[ready & (result["fast_sma"] < result["slow_sma"]), "signal"] = -1
        return result


STRATEGY = SMACrossoverStrategy()
