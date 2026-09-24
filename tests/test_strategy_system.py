from __future__ import annotations

import unittest

import pandas as pd

from binance_quant.app_api import DashboardAPI, aggregate_closed_trades
from binance_quant.backtest import run_strategy_backtest
from binance_quant.strategy_registry import discover_strategies, get_strategy


def rising_quick_entry_frame(rows: int = 320) -> pd.DataFrame:
    close = [100 + index * 0.01 for index in range(rows)]
    open_values = [value - 0.02 for value in close]
    open_values[-1] = close[-1] + 0.02
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=rows, freq="min", tz="UTC"),
            "open": open_values,
            "high": [max(open_value, close_value) + 0.10 for open_value, close_value in zip(open_values, close)],
            "low": [min(open_value, close_value) - 0.10 for open_value, close_value in zip(open_values, close)],
            "close": close,
            "volume": [1000] * rows,
        }
    )


def sample_frame(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC"),
            "open": [100 + index * 0.1 for index in range(rows)],
            "high": [101 + index * 0.1 for index in range(rows)],
            "low": [99 + index * 0.1 for index in range(rows)],
            "close": [100 + index * 0.1 + ((index % 20) - 10) * 0.2 for index in range(rows)],
            "volume": [1000 + index for index in range(rows)],
        }
    )


class StrategySystemTests(unittest.TestCase):
    def test_built_in_strategy_obeys_contract(self) -> None:
        strategy = get_strategy("sma_crossover")
        result = strategy.generate(
            sample_frame(),
            {"fast": 5, "slow": 20, "direction": "LONG_SHORT"},
        )
        self.assertIn("signal", result.columns)
        self.assertTrue(set(result["signal"].unique()).issubset({-1, 0, 1}))

    def test_sndk_strategy_is_registered_as_validation_only(self) -> None:
        strategy = get_strategy("sndk_after_close")
        self.assertEqual(strategy.market_types, ("equity_perpetual",))
        self.assertEqual(strategy.backtest_adapter["engine"], "sndk_hybrid")
        self.assertEqual(strategy.backtest_adapter["fixed_symbols"], ["SNDKUSDT"])
        self.assertFalse(strategy.backtest_adapter["supports_dry_run"])

    def test_ema_pullback_is_registered_and_uses_one_minute_execution(self) -> None:
        strategy = get_strategy("ema7_trend_pullback")
        result = strategy.generate(sample_frame(320), {})
        self.assertEqual(strategy.execution_interval("15m"), "1m")
        self.assertEqual(strategy.market_intervals("15m"), ("1m", "5m", "15m"))
        self.assertEqual(strategy.automation_defaults["leverage"], 50)
        self.assertIn("stop_price", result.columns)
        self.assertIn("trend_state", result.columns)
        self.assertTrue(set(result["signal"].unique()).issubset({-1, 0, 1}))

    def test_ema_pullback_enters_long_on_green_then_red_in_uptrend(self) -> None:
        strategy = get_strategy("ema7_trend_pullback")
        result = strategy.generate(rising_quick_entry_frame(), {})
        self.assertEqual(int(result["signal"].iloc[-2]), 0)
        self.assertEqual(int(result["signal"].iloc[-1]), 1)
        self.assertEqual(result["trend_state"].iloc[-1], "UP")
        self.assertLess(float(result["stop_price"].iloc[-1]), float(result["close"].iloc[-1]))

    def test_user_strategy_is_discoverable(self) -> None:
        DashboardAPI()
        strategies, errors = discover_strategies()
        self.assertIn("strategy_1", strategies)
        self.assertEqual(errors, [])
        strategy = strategies["strategy_1"]
        self.assertEqual(strategy.name, "策略1")
        self.assertEqual(strategy.primary_interval, "1m")
        self.assertEqual(strategy.required_intervals, ("5m", "15m"))
        self.assertEqual(strategy.parameters, ())
        self.assertEqual([item.key for item in strategy.chart_series], ["ema7", "ema25"])
        self.assertEqual(strategy.automation_defaults["leverage"], 20)
        self.assertEqual(strategy.automation_defaults["take_profit_pct"], 15)
        self.assertEqual(strategy.automation_defaults["stop_loss_pct"], 25)
        self.assertEqual(strategy.execution_policy({})["protection_mode"], "NET_ROI_FIXED")
        self.assertFalse(strategy.execution_policy({})["reverse_on_signal_change"])
        self.assertEqual(strategy.version, "2.0.0")
        self.assertIn("portfolio", strategy.capabilities)
        self.assertEqual(strategy.backtest_adapter["engine"], "freqtrade")

    def test_strategy_1_waits_for_filtered_pullback_events(self) -> None:
        strategy = get_strategy("strategy_1")
        frame = sample_frame(320)
        result = strategy.generate(frame, {})
        self.assertIn("trend_state", result.columns)
        self.assertTrue(set(result["signal"].unique()).issubset({-1, 0, 1}))
        self.assertLess(int(result["signal"].ne(0).sum()), len(result) // 4)

    def test_trade_history_aggregates_entry_exit_fees_and_net_pnl(self) -> None:
        trades = [
            {"id": 1, "orderId": 10, "symbol": "BTCUSDT", "side": "BUY", "positionSide": "BOTH", "price": "100", "qty": "1", "realizedPnl": "0", "commission": "0.10", "commissionAsset": "USDT", "time": 1000},
            {"id": 2, "orderId": 20, "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "price": "110", "qty": "0.4", "realizedPnl": "4", "commission": "0.044", "commissionAsset": "USDT", "time": 2000},
            {"id": 3, "orderId": 30, "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "price": "90", "qty": "0.6", "realizedPnl": "-6", "commission": "0.054", "commissionAsset": "USDT", "time": 3000},
        ]
        records = aggregate_closed_trades(trades, 0)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["entry_price"], 100.0)
        self.assertEqual(records[0]["exit_price"], 90.0)
        self.assertAlmostEqual(records[0]["commission"], 0.114)
        self.assertAlmostEqual(records[0]["net_pnl"], -6.114)
        self.assertEqual(records[1]["exit_price"], 110.0)
        self.assertAlmostEqual(records[1]["net_pnl"], 3.916)

    def test_trade_history_can_infer_entry_before_query_seed(self) -> None:
        records = aggregate_closed_trades(
            [{"id": 2, "orderId": 20, "symbol": "BTCUSDT", "side": "SELL", "positionSide": "BOTH", "price": "110", "qty": "0.5", "realizedPnl": "5", "commission": "0.055", "commissionAsset": "USDT", "time": 2000}],
            0,
        )
        self.assertEqual(records[0]["entry_price"], 100.0)
        self.assertTrue(records[0]["entry_estimated"])

    def test_generic_backtest_accepts_strategy_id(self) -> None:
        result = run_strategy_backtest(
            sample_frame(),
            strategy_id="sma_crossover",
            parameters={"fast": 5, "slow": 20, "direction": "LONG_SHORT"},
            initial_cash=1000,
            fee_rate=0.0005,
            leverage=3,
        )
        self.assertEqual(len(result.equity_curve), 120)
        self.assertIn("total_return_pct", result.summary)
        self.assertGreaterEqual(result.summary["trade_count"], 1)

    def test_account_metrics_are_safe_for_zero_balance(self) -> None:
        metrics = DashboardAPI._account_metrics({})
        self.assertEqual(metrics["return_pct"], 0)
        self.assertEqual(metrics["margin_usage_pct"], 0)

    def test_position_normalizes_margin_type_for_frontend(self) -> None:
        position = DashboardAPI._position({"marginType": "ISOLATED"})
        self.assertEqual(position["margin_type"], "isolated")

    def test_account_snapshot_backfills_demo_position_leverage(self) -> None:
        class DemoClientWithoutPositionLeverage:
            def account(self) -> dict[str, str]:
                return {
                    "totalWalletBalance": "4985.15",
                    "totalUnrealizedProfit": "-3.34",
                    "totalMarginBalance": "4981.81",
                    "totalInitialMargin": "222.0",
                    "availableBalance": "4737.61",
                }

            def position_risk(self) -> list[dict[str, str]]:
                return [{
                    "symbol": "ETHUSDT",
                    "positionAmt": "-5.959",
                    "entryPrice": "1862.65",
                    "markPrice": "1863.21",
                    "unRealizedProfit": "-3.34",
                    "positionInitialMargin": "11100.0",
                    "liquidationPrice": "1889.80",
                    "marginType": "ISOLATED",
                }]

            def symbol_config(self, symbol: str | None = None) -> list[dict[str, object]]:
                return [{"symbol": symbol or "ETHUSDT", "leverage": 50, "marginType": "ISOLATED"}]

        api = DashboardAPI()
        api._client = DemoClientWithoutPositionLeverage()  # type: ignore[assignment]
        response = api.account_snapshot("ETHUSDT")

        self.assertTrue(response["ok"])
        position = response["data"]["positions"][0]
        self.assertEqual(position["leverage"], 50)
        self.assertEqual(position["margin_type"], "isolated")
        self.assertTrue(response["data"]["selected_position"]["config_resolved"])
        expected_margin = abs(position["amount"] * position["entry_price"]) / 50
        self.assertAlmostEqual(position["roi_pct"], position["unrealized_pnl"] / expected_margin * 100)


if __name__ == "__main__":
    unittest.main()
