from __future__ import annotations

import base64
import hashlib
import hmac
import unittest

import pandas as pd

from binance_quant.agent_engine import (
    AgentConfig,
    FeishuNotifier,
    build_agent_market_catalog,
    build_market_snapshot,
    deterministic_signal,
    evaluate_skills,
    validate_signal,
)


def trending_frame(rows: int = 120) -> pd.DataFrame:
    close = [100 + index * 0.18 for index in range(rows)]
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC"),
            "close_time": pd.date_range("2026-01-01 00:14:59", periods=rows, freq="15min", tz="UTC"),
            "open": [value - 0.08 for value in close],
            "high": [value + 0.24 for value in close],
            "low": [value - 0.24 for value in close],
            "close": close,
            "volume": [1000 + index * 4 for index in range(rows)],
        }
    )


class AgentEngineTests(unittest.TestCase):
    def test_market_catalog_separates_crypto_and_stock_perpetuals(self) -> None:
        catalog = build_agent_market_catalog({"symbols": [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL", "underlyingType": "COIN"},
            {"symbol": "SNDKUSDT", "baseAsset": "SNDK", "quoteAsset": "USDT", "status": "TRADING", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "EQUITY"},
            {"symbol": "XAUUSDT", "baseAsset": "XAU", "quoteAsset": "USDT", "status": "TRADING", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "COMMODITY"},
        ]})
        markets = {item["id"]: item for item in catalog}
        self.assertEqual(markets["crypto_futures"]["items"][0]["symbol"], "BTCUSDT")
        self.assertEqual(markets["us_equity_perpetual"]["items"][0]["symbol"], "SNDKUSDT")
        self.assertIn("闪迪", markets["us_equity_perpetual"]["items"][0]["label"])
        self.assertEqual(markets["commodity_perpetual"]["items"][0]["symbol"], "XAUUSDT")

    def test_snapshot_and_skills_share_structured_market_data(self) -> None:
        snapshot = build_market_snapshot(
            trending_frame(),
            "BTCUSDT",
            "15m",
            {"priceChangePercent": "2.4"},
            {"lastFundingRate": "0.0001"},
        )
        assessments = evaluate_skills(snapshot, ["trend_following", "breakout", "risk_guard"])
        trend = next(item for item in assessments if item.skill_id == "trend_following")
        self.assertEqual(snapshot.trend, "UP")
        self.assertEqual(trend.bias, "LONG")
        self.assertGreater(trend.score, 0)

    def test_deterministic_signal_is_checked_by_hard_risk_rules(self) -> None:
        snapshot = build_market_snapshot(trending_frame(), "BTCUSDT", "15m")
        assessments = evaluate_skills(snapshot, ["trend_following", "breakout", "risk_guard"])
        proposal = deterministic_signal(
            snapshot,
            assessments,
            {"trend_following": 1.4, "breakout": 1, "risk_guard": 1},
        )
        result = validate_signal(
            proposal,
            snapshot,
            {
                "account_balance": 1000,
                "risk_per_trade_pct": 1,
                "leverage": 3,
                "max_margin_pct": 20,
                "min_confidence": 50,
                "min_risk_reward": 1.5,
                "max_stop_pct": 3,
                "max_atr_pct": 3.2,
            },
        )
        self.assertEqual(result["action"], "LONG")
        self.assertEqual(result["risk_status"], "PASSED")
        self.assertGreaterEqual(result["risk_reward"], 1.5)
        self.assertLessEqual(result["estimated_margin"], 200)

    def test_invalid_model_levels_are_blocked(self) -> None:
        snapshot = build_market_snapshot(trending_frame(), "BTCUSDT", "15m")
        result = validate_signal(
            {
                "action": "LONG",
                "entry_low": snapshot.price,
                "entry_high": snapshot.price + 1,
                "stop_loss": snapshot.price + 5,
                "take_profit": snapshot.price - 5,
                "confidence": 95,
                "reason": "bad levels",
                "invalid_if": "none",
            },
            snapshot,
            {"min_confidence": 60, "min_risk_reward": 1.5, "max_stop_pct": 3, "max_atr_pct": 3.2},
        )
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["risk_status"], "BLOCKED")

    def test_agent_config_requires_a_directional_skill(self) -> None:
        with self.assertRaisesRegex(ValueError, "方向分析"):
            AgentConfig.from_payload(
                {
                    "watchlist": [{"symbol": "BTCUSDT", "timeframe": "15m"}],
                    "skill_weights": {
                        "trend_following": 0,
                        "breakout": 0,
                        "mean_reversion": 0,
                        "risk_guard": 1,
                    },
                }
            )

    def test_feishu_signature_matches_official_algorithm(self) -> None:
        timestamp = 1_599_360_473
        secret = "test-secret"
        expected = base64.b64encode(
            hmac.new(f"{timestamp}\n{secret}".encode(), digestmod=hashlib.sha256).digest()
        ).decode()
        self.assertEqual(FeishuNotifier.sign(timestamp, secret), expected)


if __name__ == "__main__":
    unittest.main()
