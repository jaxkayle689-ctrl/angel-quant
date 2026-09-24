from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from binance_quant.portfolio import PortfolioConfig
from binance_quant.sndk_engine import SNDKHybridBacktestEngine, _utc_series
from binance_quant.strategy_registry import get_strategy


NEW_YORK = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def sndk_portfolio(strategy_parameters: dict | None = None) -> PortfolioConfig:
    return PortfolioConfig.from_payload(
        {
            "portfolio_id": "sndk_test",
            "name": "SNDK测试",
            "strategy_id": "sndk_after_close",
            "initial_capital": 1000,
            "run_days": 30,
            "max_concurrent_positions": 1,
            "account_stop_pct": 20,
            "strategy_parameters": strategy_parameters or {},
            "projects": [
                {
                    "project_id": "sndk",
                    "name": "SNDK",
                    "symbol": "SNDKUSDT",
                    "budget": 1000,
                    "initial_stake": 500,
                    "leverage": 5,
                    "market": "equity_perpetual",
                }
            ],
        },
        strategy_validator=lambda strategy_id, values: get_strategy(strategy_id).normalized_parameters(values),
    )


class SNDKStrategyTests(unittest.TestCase):
    def test_after_hours_cutoff_is_same_shanghai_day_at_twenty_one(self) -> None:
        engine = SNDKHybridBacktestEngine()
        cases = ((date(2026, 7, 24), 4), (date(2026, 12, 4), 5))
        for trading_day, expected_entry_hour in cases:
            entry = engine._session_close(trading_day, 1).tz_convert(SHANGHAI)
            cutoff = engine._after_hours_cutoff(trading_day).tz_convert(SHANGHAI)
            self.assertEqual(entry.date(), cutoff.date())
            self.assertEqual((entry.hour, entry.minute), (expected_entry_hour, 1))
            self.assertEqual((cutoff.hour, cutoff.minute), (21, 0))
            self.assertLess(entry, cutoff)

    def test_cached_timestamps_accept_mixed_iso_fractions(self) -> None:
        values = pd.Series(["2026-07-21 16:00:00+00:00", "2026-07-22 16:00:00.123456+00:00"])
        parsed = _utc_series(values)
        self.assertEqual(str(parsed.dt.tz), "UTC")
        self.assertEqual(parsed.iloc[0].microsecond, 0)
        self.assertEqual(parsed.iloc[1].microsecond, 123456)

    def test_signal_blocks_third_large_bull_but_keeps_large_bear(self) -> None:
        strategy = get_strategy("sndk_after_close")
        frame = pd.DataFrame(
            {
                "trading_date": pd.date_range("2026-01-05", periods=4, freq="D").date,
                "open": [100, 110, 120, 130],
                "high": [108, 119, 130, 132],
                "low": [99, 109, 119, 120],
                "close": [106, 117, 128, 122],
            }
        )

        result = strategy.generate(frame, {})

        self.assertEqual(result["signal"].tolist(), [1, 1, 0, -1])
        self.assertEqual(result["signal_reason"].iloc[2], "LONG_STREAK_BLOCKED")
        self.assertEqual(strategy.backtest_adapter["engine"], "sndk_hybrid")
        self.assertFalse(strategy.backtest_adapter["supports_dry_run"])
        parameters = strategy.normalized_parameters(
            {"wait_for_pullback": True, "entry_pullback_pct": 0.5}
        )
        self.assertTrue(parameters["wait_for_pullback"])
        self.assertEqual(parameters["entry_pullback_pct"], 0.5)

    def test_portfolio_accepts_only_sndk_equity_perpetual(self) -> None:
        portfolio = sndk_portfolio()
        self.assertEqual(portfolio.active_projects[0].market, "equity_perpetual")
        payload = portfolio.to_dict()
        payload["projects"][0]["symbol"] = "MUUSDT"
        with self.assertRaisesRegex(ValueError, "SNDKUSDT"):
            PortfolioConfig.from_payload(payload)

    def test_hybrid_engine_applies_half_margin_leverage_fees_and_slippage(self) -> None:
        strategy = get_strategy("sndk_after_close")
        portfolio = sndk_portfolio()
        end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=44)
        dates = [start_date + timedelta(days=index) for index in range(45)]
        signal_date = end_date - timedelta(days=5)
        equity_rows = []
        for trading_day in dates:
            is_signal = trading_day == signal_date
            equity_rows.append(
                {
                    "open_time": pd.Timestamp(datetime.combine(trading_day, time(9, 30), NEW_YORK)),
                    "trading_date": trading_day,
                    "open": 100.0,
                    "high": 107.0 if is_signal else 101.0,
                    "low": 99.0,
                    "close": 106.0 if is_signal else 100.0,
                    "volume": 1000,
                }
            )
        equity = pd.DataFrame(equity_rows)
        entry_time = pd.Timestamp(
            datetime.combine(signal_date, time(16, 1), NEW_YORK).astimezone(timezone.utc)
        )
        futures = pd.DataFrame(
            {
                "open": [100.0, 100.2],
                "high": [100.4, 102.0],
                "low": [99.8, 100.0],
                "close": [100.2, 101.5],
                "volume": [1000, 1000],
            },
            index=[entry_time, entry_time + timedelta(minutes=1)],
        )
        empty_funding = pd.DataFrame(columns=["funding_rate", "mark_price"])

        with tempfile.TemporaryDirectory() as directory, patch(
            "binance_quant.sndk_engine.RESULT_ROOT", Path(directory)
        ):
            engine = SNDKHybridBacktestEngine()
            with patch.object(engine, "_equity_daily", return_value=equity), patch.object(
                engine, "_futures_minutes", return_value=futures
            ), patch.object(
                engine,
                "_funding_rates",
                return_value=(empty_funding, "test"),
            ):
                status = engine.start_portfolio_backtest(portfolio, strategy)

        result = status["result"]
        self.assertEqual(status["status"], "completed")
        self.assertEqual(result["total_trades"], 1)
        self.assertEqual(result["long"]["trades"], 1)
        self.assertGreater(result["profit_abs"], 0)
        self.assertGreater(result["estimated_fees"], 0)
        self.assertEqual(result["trades"][0]["margin"], 500)
        self.assertEqual(result["trades"][0]["leverage"], 5)
        self.assertEqual(result["trades"][0]["exit_reason"], "价格止盈")

    def test_hybrid_engine_waits_for_configured_pullback(self) -> None:
        strategy = get_strategy("sndk_after_close")
        portfolio = sndk_portfolio(
            {"wait_for_pullback": True, "entry_pullback_pct": 0.5}
        )
        end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=44)
        dates = [start_date + timedelta(days=index) for index in range(45)]
        signal_date = end_date - timedelta(days=5)
        equity = pd.DataFrame(
            [
                {
                    "open_time": pd.Timestamp(datetime.combine(trading_day, time(9, 30), NEW_YORK)),
                    "trading_date": trading_day,
                    "open": 100.0,
                    "high": 107.0 if trading_day == signal_date else 101.0,
                    "low": 99.0,
                    "close": 106.0 if trading_day == signal_date else 100.0,
                    "volume": 1000,
                }
                for trading_day in dates
            ]
        )
        search_start = pd.Timestamp(
            datetime.combine(signal_date, time(16, 1), NEW_YORK).astimezone(timezone.utc)
        )
        futures = pd.DataFrame(
            {
                "open": [106.0, 105.8, 106.0],
                "high": [106.2, 107.0, 107.0],
                "low": [105.8, 105.4, 105.8],
                "close": [106.0, 105.7, 106.8],
                "volume": [1000, 1000, 1000],
            },
            index=[search_start + timedelta(minutes=index) for index in range(3)],
        )
        empty_funding = pd.DataFrame(columns=["funding_rate", "mark_price"])

        with tempfile.TemporaryDirectory() as directory, patch(
            "binance_quant.sndk_engine.RESULT_ROOT", Path(directory)
        ):
            engine = SNDKHybridBacktestEngine()
            with patch.object(engine, "_equity_daily", return_value=equity), patch.object(
                engine, "_futures_minutes", return_value=futures
            ), patch.object(
                engine,
                "_funding_rates",
                return_value=(empty_funding, "test"),
            ):
                result = engine.start_portfolio_backtest(portfolio, strategy)["result"]

        trade = result["trades"][0]
        self.assertEqual(result["total_trades"], 1)
        self.assertEqual(trade["entry_mode"], "pullback")
        self.assertEqual(trade["reference_close"], 106.0)
        self.assertAlmostEqual(trade["entry_trigger_price"], 105.47)
        self.assertEqual(pd.Timestamp(trade["entry_time"]), search_start + timedelta(minutes=1))
        self.assertEqual(pd.Timestamp(trade["exit_time"]), search_start + timedelta(minutes=2))
        self.assertEqual(trade["exit_reason"], "价格止盈")

    def test_hybrid_engine_forces_exit_at_beijing_twenty_one(self) -> None:
        strategy = get_strategy("sndk_after_close")
        portfolio = sndk_portfolio()
        end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=44)
        dates = [start_date + timedelta(days=index) for index in range(45)]
        signal_date = end_date - timedelta(days=5)
        equity = pd.DataFrame(
            [
                {
                    "open_time": pd.Timestamp(datetime.combine(trading_day, time(9, 30), NEW_YORK)),
                    "trading_date": trading_day,
                    "open": 100.0,
                    "high": 107.0 if trading_day == signal_date else 101.0,
                    "low": 99.0,
                    "close": 106.0 if trading_day == signal_date else 100.0,
                    "volume": 1000,
                }
                for trading_day in dates
            ]
        )
        engine = SNDKHybridBacktestEngine()
        entry_time = engine._session_close(signal_date, 1)
        cutoff = engine._after_hours_cutoff(signal_date)
        minute_index = pd.date_range(
            entry_time,
            cutoff - timedelta(minutes=1),
            freq="min",
        )
        futures = pd.DataFrame(
            {
                "open": 100.0,
                "high": 100.2,
                "low": 99.8,
                "close": 100.0,
                "volume": 1000,
            },
            index=minute_index,
        )
        empty_funding = pd.DataFrame(columns=["funding_rate", "mark_price"])

        with tempfile.TemporaryDirectory() as directory, patch(
            "binance_quant.sndk_engine.RESULT_ROOT", Path(directory)
        ), patch.object(engine, "_equity_daily", return_value=equity), patch.object(
            engine, "_futures_minutes", return_value=futures
        ), patch.object(
            engine,
            "_funding_rates",
            return_value=(empty_funding, "test"),
        ):
            result = engine.start_portfolio_backtest(portfolio, strategy)["result"]

        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"], "北京时间21:00")
        self.assertEqual(pd.Timestamp(trade["exit_time"]), cutoff)
        self.assertEqual(pd.Timestamp(trade["entry_time"]).tz_convert(SHANGHAI).date(), cutoff.tz_convert(SHANGHAI).date())


if __name__ == "__main__":
    unittest.main()
