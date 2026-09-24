from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from binance_quant.freqtrade_engine import (
    FreqtradeEngine,
    _network_error,
    _pair_for_symbol,
    _subprocess_environment,
)


class FreqtradeEngineTests(unittest.TestCase):
    def test_strategy_template_uses_calibrated_multitimeframe_risk(self) -> None:
        source = resources.read_text(
            "binance_quant.resources",
            "freqtrade_strategy1.py.txt",
            encoding="utf-8",
        )
        self.assertIn('@informative("5m")', source)
        self.assertIn('@informative("15m")', source)
        self.assertIn('minimal_roi = {"0": 0.15}', source)
        self.assertIn("stoploss = -0.23", source)
        self.assertIn("position_adjustment_enable = False", source)
        self.assertIn('self._project_value(pair, "leverage", 20.0)', source)
        self.assertIn('self._project_value(pair, "initial_stake", self.initial_stake)', source)

    def test_pair_conversion_only_accepts_usdt_contracts(self) -> None:
        self.assertEqual(_pair_for_symbol("ethusdt"), "ETH/USDT:USDT")
        with self.assertRaisesRegex(ValueError, "USDT"):
            _pair_for_symbol("ETHUSD")

    def test_generated_config_is_keyless_isolated_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("binance_quant.freqtrade_engine.FREQTRADE_DIR", root / "freqtrade"), patch(
                "binance_quant.freqtrade_engine.FREQTRADE_RUNTIME", root / "runtime"
            ):
                engine = FreqtradeEngine()
                engine._write_config("ETHUSDT", 5000, initial_state="running")
                config = json.loads(engine.config_path.read_text(encoding="utf-8"))

        self.assertTrue(config["dry_run"])
        self.assertEqual(config["initial_state"], "running")
        self.assertEqual(config["trading_mode"], "futures")
        self.assertEqual(config["margin_mode"], "isolated")
        self.assertEqual(config["tradable_balance_ratio"], 0.05)
        self.assertEqual(config["exchange"]["pair_whitelist"], ["ETH/USDT:USDT"])
        self.assertEqual(config["exchange"]["key"], "")
        self.assertEqual(config["exchange"]["secret"], "")
        self.assertEqual(config["entry_pricing"]["price_side"], "other")
        self.assertEqual(config["exit_pricing"]["price_side"], "other")
        self.assertTrue(config["exchange"]["ccxt_config"]["trust_env"])
        self.assertTrue(config["exchange"]["ccxt_async_config"]["aiohttp_trust_env"])

    def test_generated_portfolio_config_keeps_project_risk_per_pair(self) -> None:
        projects = [
            {"project_id": "btc", "symbol": "BTCUSDT", "budget": 1000, "initial_stake": 50, "leverage": 20},
            {"project_id": "eth", "symbol": "ETHUSDT", "budget": 1200, "initial_stake": 75, "leverage": 15},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("binance_quant.freqtrade_engine.FREQTRADE_DIR", root / "freqtrade"), patch(
                "binance_quant.freqtrade_engine.FREQTRADE_RUNTIME", root / "runtime"
            ):
                engine = FreqtradeEngine()
                engine._write_config(
                    ["BTCUSDT", "ETHUSDT"],
                    5000,
                    max_open_trades=2,
                    projects=projects,
                )
                config = json.loads(engine.config_path.read_text(encoding="utf-8"))

        self.assertEqual(config["max_open_trades"], 2)
        self.assertEqual(config["tradable_balance_ratio"], 1.0)
        self.assertEqual(config["exchange"]["pair_whitelist"], ["BTC/USDT:USDT", "ETH/USDT:USDT"])
        self.assertEqual(config["bq_projects"]["ETH/USDT:USDT"]["initial_stake"], 75)
        self.assertEqual(config["bq_projects"]["ETH/USDT:USDT"]["leverage"], 15)

    def test_subprocess_environment_inherits_system_proxy(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "binance_quant.freqtrade_engine.getproxies",
            return_value={"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        ):
            environment = _subprocess_environment()

        self.assertEqual(environment["HTTP_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(environment["http_proxy"], "http://127.0.0.1:7890")
        self.assertEqual(environment["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(environment["https_proxy"], "http://127.0.0.1:7890")

    def test_subprocess_environment_keeps_explicit_proxy(self) -> None:
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://explicit:8080"}, clear=True), patch(
            "binance_quant.freqtrade_engine.getproxies",
            return_value={"https": "http://system:7890"},
        ):
            environment = _subprocess_environment()

        self.assertEqual(environment["HTTPS_PROXY"], "http://explicit:8080")
        self.assertNotIn("https_proxy", environment)

    def test_network_error_is_translated_for_binance_failures(self) -> None:
        logs = [
            "ExchangeNotAvailable: binance GET https://fapi.binance.com/fapi/v1/exchangeInfo",
            "Markets were not loaded.",
        ]
        self.assertIn("无法连接 Binance Futures", _network_error(logs))

    def test_result_parser_reads_freqtrade_zip(self) -> None:
        payload = {
            "strategy": {
                "Strategy1": {
                    "total_trades": 4,
                    "wins": 3,
                    "profit_total": 0.12,
                    "profit_total_abs": 600,
                    "max_drawdown_account": 0.04,
                }
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            result_file = Path(directory) / "result.zip"
            with zipfile.ZipFile(result_file, "w") as archive:
                archive.writestr("result.json", json.dumps(payload))
            engine = FreqtradeEngine.__new__(FreqtradeEngine)
            result = engine._parse_latest_result([result_file], "ETHUSDT", 30, 5000)

        self.assertEqual(result["total_trades"], 4)
        self.assertEqual(result["win_rate_pct"], 75)
        self.assertEqual(result["profit_pct"], 12)
        self.assertEqual(result["max_drawdown_pct"], 4)


if __name__ == "__main__":
    unittest.main()
