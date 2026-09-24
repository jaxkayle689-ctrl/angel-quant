from __future__ import annotations

from typing import Any

import pandas as pd

from ..strategy_api import Strategy, StrategyParameter


class SNDKAfterCloseStrategy(Strategy):
    """SNDK cash-session candle signal executed on the Binance equity perp."""

    strategy_id = "sndk_after_close"
    name = "SNDK 盘后动量"
    description = (
        "SNDK正股收出大实体日K后，在Binance SNDKUSDT盘后顺势交易；"
        "可选按正股收盘价等待多单回撤或空单反弹后入场；"
        "第三根及之后的连续大阳线禁止追多，连续大阴线仍允许做空。"
    )
    version = "1.2.0"
    primary_interval = "1d"
    required_intervals = ()
    history_limit = 90
    market_types = ("equity_perpetual",)
    capabilities = (
        "long",
        "short",
        "fixed_position",
        "cross_market_signal",
        "validation_only",
    )
    automation_defaults = {
        "symbol": "SNDKUSDT",
        "leverage": 5,
        "allocation_pct": 50,
        "take_profit_price_pct": 1,
        "stop_loss_price_pct": 5,
        "risk_unit": "PRICE_MOVE",
        "real_trading": False,
    }
    parameters = (
        StrategyParameter("large_body_pct", "大实体最小涨跌", "number", 5.0, minimum=0.5, maximum=20, step=0.5),
        StrategyParameter("min_body_ratio", "实体占振幅", "number", 0.5, minimum=0.1, maximum=1, step=0.05),
        StrategyParameter("long_streak_limit", "连续大阳禁多根数", "integer", 3, minimum=2, maximum=10, step=1),
        StrategyParameter("take_profit_pct", "价格止盈", "number", 1.0, minimum=0.2, maximum=10, step=0.1),
        StrategyParameter("stop_loss_pct", "价格止损", "number", 5.0, minimum=0.5, maximum=20, step=0.5),
        StrategyParameter("entry_delay_minutes", "收盘后延迟", "integer", 1, minimum=1, maximum=30, step=1),
        StrategyParameter("wait_for_pullback", "等待回撤入场", "boolean", False),
        StrategyParameter("entry_pullback_pct", "回撤/反弹幅度(%)", "number", 0.5, minimum=0.1, maximum=10, step=0.1),
        StrategyParameter("taker_fee_bps", "单边手续费", "number", 5.0, minimum=0, maximum=30, step=0.1),
        StrategyParameter("slippage_bps", "单边滑点", "number", 10.0, minimum=0, maximum=100, step=1),
    )
    backtest_adapter = {
        "engine": "sndk_hybrid",
        "supports_portfolio": True,
        "supports_dry_run": False,
        "fixed_symbols": ["SNDKUSDT"],
        "market": "equity_perpetual",
        "default_capital": 1000,
        "default_budget": 1000,
        "default_initial_stake": 500,
        "default_leverage": 5,
        "max_leverage": 10,
    }

    def normalized_parameters(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = super().normalized_parameters(values)
        if normalized["take_profit_pct"] >= normalized["stop_loss_pct"]:
            raise ValueError("SNDK盘后策略的价格止盈应小于价格止损。")
        return normalized

    def execution_policy(self, parameters: dict[str, Any]) -> dict[str, Any]:
        values = self.normalized_parameters(parameters)
        return {
            "signal_source": "SNDK_US_EQUITY_REGULAR_SESSION_DAILY",
            "execution_symbol": "SNDKUSDT",
            "entry_order": "MARKET_BACKTEST_ONLY",
            "entry_delay_minutes": values["entry_delay_minutes"],
            "wait_for_pullback": values["wait_for_pullback"],
            "entry_pullback_pct": values["entry_pullback_pct"],
            "beijing_cutoff_time": "21:00",
            "allow_overnight": False,
            "take_profit_price_pct": values["take_profit_pct"],
            "stop_loss_price_pct": values["stop_loss_pct"],
            "real_trading": False,
        }

    def generate(self, frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
        values = self.normalized_parameters(parameters)
        required = {"open", "high", "low", "close"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"SNDK正股日线缺少字段：{', '.join(sorted(missing))}。")

        result = frame.copy()
        sort_column = "trading_date" if "trading_date" in result.columns else "open_time"
        if sort_column in result.columns:
            result = result.sort_values(sort_column)
        result = result.reset_index(drop=True)
        for column in required:
            result[column] = pd.to_numeric(result[column], errors="coerce")

        candle_range = (result["high"] - result["low"]).abs()
        body = result["close"] - result["open"]
        result["body_pct"] = body / result["open"] * 100
        result["body_ratio"] = body.abs().div(candle_range.where(candle_range > 0)).fillna(0)
        threshold = values["large_body_pct"]
        min_ratio = values["min_body_ratio"]
        result["large_bull"] = (result["body_pct"] >= threshold) & (result["body_ratio"] >= min_ratio)
        result["large_bear"] = (result["body_pct"] <= -threshold) & (result["body_ratio"] >= min_ratio)

        streaks: list[int] = []
        streak = 0
        for is_large_bull in result["large_bull"].fillna(False):
            streak = streak + 1 if bool(is_large_bull) else 0
            streaks.append(streak)
        result["large_bull_streak"] = streaks
        long_allowed = result["large_bull"] & (
            result["large_bull_streak"] < values["long_streak_limit"]
        )
        result["signal"] = 0
        result.loc[long_allowed, "signal"] = 1
        result.loc[result["large_bear"], "signal"] = -1
        result["signal_reason"] = "NO_LARGE_BODY"
        result.loc[long_allowed, "signal_reason"] = "LARGE_BULL"
        result.loc[result["large_bear"], "signal_reason"] = "LARGE_BEAR"
        result.loc[
            result["large_bull"] & ~long_allowed,
            "signal_reason",
        ] = "LONG_STREAK_BLOCKED"
        return result
