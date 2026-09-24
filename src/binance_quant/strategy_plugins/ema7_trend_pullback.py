from __future__ import annotations

from collections import deque
from typing import Any

import pandas as pd

from ..strategy_api import ChartSeries, Strategy, StrategyContext, StrategyParameter


def _numeric_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "close_time" not in result.columns:
        if "open_time" not in result.columns:
            raise ValueError("策略行情缺少 open_time/close_time。")
        result["close_time"] = pd.to_datetime(result["open_time"], utc=True)
    result = result.sort_values("close_time").reset_index(drop=True)
    for column in ("open", "high", "low", "close"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        (
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ),
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _confirmed_swings(frame: pd.DataFrame, span: int = 2) -> pd.DataFrame:
    """Expose a pivot only after `span` later candles have closed."""

    result = pd.DataFrame(index=frame.index)
    last_highs: deque[float] = deque(maxlen=2)
    last_lows: deque[float] = deque(maxlen=2)
    latest_high = float("nan")
    latest_low = float("nan")
    rows: list[dict[str, Any]] = []
    for index in range(len(frame)):
        pivot_index = index - span
        if pivot_index >= span:
            window = frame.iloc[pivot_index - span : pivot_index + span + 1]
            pivot_high = float(frame.at[pivot_index, "high"])
            pivot_low = float(frame.at[pivot_index, "low"])
            if pivot_high == float(window["high"].max()):
                latest_high = pivot_high
                last_highs.append(pivot_high)
            if pivot_low == float(window["low"].min()):
                latest_low = pivot_low
                last_lows.append(pivot_low)
        rows.append(
            {
                "swing_high": latest_high,
                "swing_low": latest_low,
                "higher_structure": (
                    len(last_highs) == 2
                    and len(last_lows) == 2
                    and last_highs[-1] > last_highs[-2]
                    and last_lows[-1] > last_lows[-2]
                ),
                "lower_structure": (
                    len(last_highs) == 2
                    and len(last_lows) == 2
                    and last_highs[-1] < last_highs[-2]
                    and last_lows[-1] < last_lows[-2]
                ),
            }
        )
    return pd.DataFrame(rows, index=result.index)


def _asof(left: pd.DataFrame, right: pd.DataFrame, columns: list[str], prefix: str) -> pd.DataFrame:
    source = right[["close_time", *columns]].rename(
        columns={column: f"{prefix}{column}" for column in columns}
    )
    return pd.merge_asof(
        left.sort_values("close_time"),
        source.sort_values("close_time"),
        on="close_time",
        direction="backward",
    )


class EMA7TrendPullbackStrategy(Strategy):
    strategy_id = "ema7_trend_pullback"
    name = "EMA7 多周期顺势回调"
    description = "15m/5m EMA 多头排列时，1m 前绿后红快速挂多；做空仍等待下降结构确认。"
    primary_interval = "1m"
    required_intervals = ("5m", "15m")
    history_limit = 320
    automation_defaults = {
        "leverage": 50,
        "allocation_pct": 5,
        "stop_loss_pct": 15,
        "take_profit_pct": 3,
        "daily_max_loss_pct": 3,
        "risk_unit": "ROI",
    }
    parameters = (
        StrategyParameter("support_ema", "支撑 EMA", "integer", 7, minimum=3, maximum=30, step=1),
        StrategyParameter("trend_ema", "趋势 EMA", "integer", 20, minimum=10, maximum=80, step=1),
        StrategyParameter("major_ema", "主趋势 EMA", "integer", 60, minimum=30, maximum=200, step=1),
        StrategyParameter("atr_period", "ATR 周期", "integer", 14, minimum=7, maximum=50, step=1),
        StrategyParameter("max_spread_bps", "最大点差(bps)", "number", 2.0, minimum=0.2, maximum=20, step=0.1),
        StrategyParameter(
            "direction",
            "交易方向",
            "choice",
            "LONG_SHORT",
            choices=("LONG_SHORT", "LONG_ONLY", "SHORT_ONLY"),
        ),
    )
    chart_series = (
        ChartSeries("ema7", "支撑 EMA", "#66d6a7"),
        ChartSeries("ema20", "趋势 EMA", "#f0c453"),
        ChartSeries("ema60", "主趋势 EMA", "#71a9e8"),
    )

    def execution_policy(self, parameters: dict[str, Any]) -> dict[str, Any]:
        values = self.normalized_parameters(parameters)
        if not (values["support_ema"] < values["trend_ema"] < values["major_ema"]):
            raise ValueError("EMA 周期必须满足：支撑 EMA < 趋势 EMA < 主趋势 EMA。")
        return {
            "minimum_leverage": 50,
            "protection_mode": "NET_ROI_STRUCTURAL",
            "entry_order": "MAKER_GTX",
            "entry_timeout_seconds": 4.0,
            "hold_until_protection": True,
            "cooldown_candles": 3,
            "max_consecutive_losses": 3,
            "loss_pause_minutes": 30,
            "max_trades_per_hour": 10,
            "max_spread_bps": values["max_spread_bps"],
            "exit_slippage_bps": 1.0,
        }

    def generate(self, frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
        context = StrategyContext(
            frames={"1m": frame, "5m": frame, "15m": frame},
            execution_interval="1m",
        )
        return self.generate_with_context(context, parameters)

    def generate_with_context(
        self,
        context: StrategyContext,
        parameters: dict[str, Any],
    ) -> pd.DataFrame:
        values = self.normalized_parameters(parameters)
        self.execution_policy(values)
        support_period = values["support_ema"]
        trend_period = values["trend_ema"]
        major_period = values["major_ema"]
        atr_period = values["atr_period"]

        minute = _numeric_frame(context.frames["1m"])
        five = _numeric_frame(context.frames["5m"])
        fifteen = _numeric_frame(context.frames["15m"])

        minute["ema7"] = minute["close"].ewm(span=support_period, adjust=False).mean()
        minute["ema20"] = minute["close"].ewm(span=trend_period, adjust=False).mean()
        minute["ema60"] = minute["close"].ewm(span=major_period, adjust=False).mean()
        minute["atr14"] = _atr(minute, atr_period)

        five["ema7"] = five["close"].ewm(span=support_period, adjust=False).mean()
        five["ema20"] = five["close"].ewm(span=trend_period, adjust=False).mean()
        five["ema60"] = five["close"].ewm(span=major_period, adjust=False).mean()
        five["atr14"] = _atr(five, atr_period)
        swings = _confirmed_swings(five)
        five = pd.concat((five, swings), axis=1)
        five["trend_up"] = (
            (five["ema7"] > five["ema20"])
            & (five["ema20"] > five["ema60"])
        )
        five["trend_down"] = (
            (five["ema7"] < five["ema20"])
            & (five["ema20"] < five["ema60"])
            & (five["ema20"] <= five["ema20"].shift(3))
            & (five["ema60"] <= five["ema60"].shift(3))
            & five["lower_structure"]
        )

        fifteen["ema20"] = fifteen["close"].ewm(span=trend_period, adjust=False).mean()
        fifteen["ema60"] = fifteen["close"].ewm(span=major_period, adjust=False).mean()
        fifteen["trend_up"] = (
            (fifteen["close"] > fifteen["ema60"])
            & (fifteen["ema20"] > fifteen["ema60"])
        )
        fifteen["trend_down"] = (
            (fifteen["close"] < fifteen["ema60"])
            & (fifteen["ema20"] < fifteen["ema60"])
            & (fifteen["ema20"] < fifteen["ema20"].shift(3))
        )

        result = _asof(
            minute,
            five,
            ["ema7", "atr14", "swing_high", "swing_low", "trend_up", "trend_down"],
            "m5_",
        )
        result = _asof(result, fifteen, ["trend_up", "trend_down"], "m15_")

        pullback_low = result["low"].rolling(3).min()
        pullback_high = result["high"].rolling(3).max()
        short_touch = (
            (pullback_high >= result["ema7"] - result["atr14"] * 0.15)
            & (pullback_high <= result["ema7"] + result["atr14"] * 0.20)
        )
        short_body_safe = (result["close"] <= result["ema20"]).rolling(3).min().fillna(0).astype(bool)
        long_structure_safe = result["m5_swing_low"].isna() | (result["low"] > result["m5_swing_low"])
        short_structure_safe = pullback_high < result["m5_swing_high"]

        body = (result["close"] - result["open"]).abs().clip(lower=1e-12)
        upper_wick = result["high"] - result[["open", "close"]].max(axis=1)
        previous_green_current_red = (
            (result["close"].shift(1) > result["open"].shift(1))
            & (result["close"] < result["open"])
        )
        short_confirmation = (
            (result["close"] < result["ema7"])
            & (result["close"] < result["open"])
            & ((upper_wick >= body * 0.6) | (result["close"] < result["low"].shift(1)))
        )
        no_long_chase = (result["close"] - result["m5_ema7"]).abs() <= result["m5_atr14"]
        no_short_chase = no_long_chase

        target_fraction = float(context.metadata.get("target_price_fraction", 0.0017))
        long_room = (
            result["m5_swing_high"].isna()
            | (result["m5_swing_high"] <= result["close"])
            | ((result["m5_swing_high"] / result["close"] - 1) >= target_fraction)
        )
        short_room = (
            result["m5_swing_low"].isna()
            | (result["m5_swing_low"] >= result["close"])
            | ((1 - result["m5_swing_low"] / result["close"]) >= target_fraction)
        )

        long_setup = (
            result["m15_trend_up"].fillna(False)
            & result["m5_trend_up"].fillna(False)
            & previous_green_current_red.fillna(False)
            & (result["close"] > result["ema20"]).fillna(False)
            & long_structure_safe.fillna(False)
            & no_long_chase.fillna(False)
            & long_room.fillna(False)
        )
        short_setup = (
            result["m15_trend_down"].fillna(False)
            & result["m5_trend_down"].fillna(False)
            & short_touch.fillna(False)
            & short_body_safe.fillna(False)
            & short_structure_safe.fillna(False)
            & short_confirmation.fillna(False)
            & no_short_chase.fillna(False)
            & short_room.fillna(False)
        )
        if values["direction"] == "LONG_ONLY":
            short_setup[:] = False
        elif values["direction"] == "SHORT_ONLY":
            long_setup[:] = False

        long_event = long_setup & ~long_setup.shift(1, fill_value=False)
        short_event = short_setup & ~short_setup.shift(1, fill_value=False)
        result["signal"] = 0
        result.loc[long_event, "signal"] = 1
        result.loc[short_event, "signal"] = -1
        result["stop_price"] = float("nan")
        result.loc[long_event, "stop_price"] = (
            result.loc[long_event, "low"] - result.loc[long_event, "atr14"] * 0.10
        )
        result.loc[short_event, "stop_price"] = (
            pullback_high[short_event] + result.loc[short_event, "atr14"] * 0.10
        )
        result["trend_state"] = "NEUTRAL"
        result.loc[result["m15_trend_up"].fillna(False) & result["m5_trend_up"].fillna(False), "trend_state"] = "UP"
        result.loc[result["m15_trend_down"].fillna(False) & result["m5_trend_down"].fillna(False), "trend_state"] = "DOWN"
        result["support_level"] = result["m5_swing_low"]
        result["resistance_level"] = result["m5_swing_high"]
        return result


STRATEGY = EMA7TrendPullbackStrategy()
