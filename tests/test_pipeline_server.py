from __future__ import annotations

import time
import unittest

import pandas as pd
from fastapi.testclient import TestClient

from binance_quant.pipeline import chanlun_lite
from binance_quant.pipeline.cards import build_card
from binance_quant.pipeline.contract import (
    Direction,
    OrderTicket,
    OrderType,
    Rating,
    TakeProfit,
)
from binance_quant.pipeline.liquidation import (
    TruthFeed,
    build_profile,
    estimate_clusters,
    merge_truth,
)
from binance_quant.pipeline.notifier import build_feishu_card
from binance_quant.pipeline.server import RuntimeConfig, create_app


class TestTruthFeed(unittest.TestCase):
    def test_ingest_and_total(self) -> None:
        feed = TruthFeed()
        feed.ingest("LONG", 100.0, 500.0)
        feed.ingest("SHORT", 100.5, 300.0)
        self.assertAlmostEqual(feed.total("LONG"), 500.0)
        self.assertAlmostEqual(feed.total(), 800.0)
        self.assertEqual(len(feed.window()), 2)

    def test_invalid_side_rejected(self) -> None:
        feed = TruthFeed()
        with self.assertRaises(ValueError):
            feed.ingest("WEIRD", 1.0, 1.0)

    def test_trim_24h(self) -> None:
        feed = TruthFeed()
        old = time.time() - 25 * 3600
        feed.ingest("LONG", 100.0, 100.0, ts=old)
        feed.ingest("LONG", 100.0, 50.0)
        self.assertAlmostEqual(feed.total(), 50.0)

    def test_parse_force_order_payload(self) -> None:
        payload = {"o": {"side": "SELL", "p": "100", "ap": "100.5", "q": "2", "T": 1_700_000_000_000}}
        event = TruthFeed.parse_force_order(payload)
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.side, "LONG")
        self.assertAlmostEqual(event.amount_usdt, 201.0)


class TestEstimateClusters(unittest.TestCase):
    def test_longs_below_shorts_above(self) -> None:
        clusters = estimate_clusters(
            100.0, 1_000_000.0, swing_high=110.0, swing_low=90.0
        )
        self.assertTrue(clusters)
        sides = {c.side for c in clusters}
        self.assertIn("LONG", sides)
        self.assertIn("SHORT", sides)
        for c in clusters:
            if c.side == "LONG":
                self.assertLessEqual(c.price, 100.0 * 1.001)
            else:
                self.assertGreaterEqual(c.price, 100.0 * 0.999)

    def test_merge_truth_upgrades_driver(self) -> None:
        clusters = estimate_clusters(100.0, 1_000_000.0,
                                     swing_high=110.0, swing_low=90.0)
        feed = TruthFeed()
        target = clusters[0]
        feed.ingest(target.side, target.price, target.estimated_usdt * 3)
        merged = merge_truth(clusters, feed, mark_price=100.0)
        self.assertIn("truth", {c.driver for c in merged})

    def test_profile_evidence_text(self) -> None:
        feed = TruthFeed()
        feed.ingest("LONG", 99.0, 1000.0)
        profile = build_profile("BTCUSDT", 100.0, 2_000_000.0,
                                swing_high=110.0, swing_low=90.0, feed=feed)
        text = profile.evidence_text()
        self.assertIn("估算模型", text)
        self.assertIn("真实强平", text)
        self.assertIn("BTCUSDT", text)


class TestNotifier(unittest.TestCase):
    def test_card_json_structure(self) -> None:
        ticket = OrderTicket(
            symbol="BTCUSDT", direction=Direction.LONG, order_type=OrderType.LIMIT,
            entry=98_000.0, stop_loss=96_500.0,
            tp=[TakeProfit(100_000.0, 0.5), TakeProfit(102_000.0, 0.5)],
            size=500.0, leverage=3.0,
        )
        card = build_card("BTCUSDT", Rating.BUY, ticket=ticket, gate=None,
                          channel="deep", evidence_lines=["三线共振放量突破"],
                          risk_notes=["接近 ATR 上限"])
        payload = build_feishu_card(card)
        self.assertEqual(payload["header"]["title"]["content"], "策略卡片 · BTCUSDT")
        self.assertEqual(payload["header"]["template"], "green")
        texts = json_flatten(payload)
        self.assertTrue("98000" in texts or "98,000" in texts)
        self.assertIn("三线共振放量突破", texts)
        self.assertIn("不构成投资建议", texts)

    def test_hold_card_grey(self) -> None:
        card = build_card("BTCUSDT", Rating.HOLD, ticket=None, gate=None, channel="standard")
        payload = build_feishu_card(card)
        self.assertEqual(payload["header"]["template"], "grey")
        self.assertIn("观望", json_flatten(payload))


def json_flatten(node, acc=None) -> str:
    acc = acc if acc is not None else []
    if isinstance(node, dict):
        for value in node.values():
            json_flatten(value, acc)
    elif isinstance(node, list):
        for value in node:
            json_flatten(value, acc)
    elif isinstance(node, str):
        acc.append(node)
    return "".join(acc)


class TestChanLunLite(unittest.TestCase):
    def _zigzag_frame(self) -> pd.DataFrame:
        # 明显的顶底交替:上 20 根 → 下 20 根 → 上 20 根 → 下 20 根 → 上 30 根
        closes = []
        for delta in (20, -20, 20, -20, 30):
            base = closes[-1] if closes else 100.0
            step = 1.0 if delta > 0 else -1.0
            for _ in range(abs(delta)):
                base += step
                closes.append(base)
        highs = [c + 0.4 for c in closes]
        lows = [c - 0.4 for c in closes]
        idx = pd.date_range("2026-09-01", periods=len(closes), freq="15min")
        return pd.DataFrame(
            {"open": closes, "high": highs, "low": lows, "close": closes,
             "volume": [1000.0] * len(closes)},
            index=idx,
        )

    def test_fractals_detected_on_zigzag(self) -> None:
        frame = self._zigzag_frame()
        found = chanlun_lite.fractals(frame, strict=False)
        kinds = {f.kind for f in found}
        self.assertEqual(kinds, {1, -1})

    def test_generate_outputs_signals(self) -> None:
        frame = self._zigzag_frame()
        strategy = chanlun_lite.STRATEGY
        result = strategy.generate(frame, strategy.normalized_parameters({}))
        self.assertIn("signal", result.columns)
        nonzero = result[result["signal"] != 0]
        self.assertGreaterEqual(len(nonzero), 1)
        values = set(nonzero["signal"].tolist())
        self.assertTrue(values.issubset({-1, 1}))

    def test_empty_frame_safe(self) -> None:
        frame = self._zigzag_frame().tail(5)
        result = chanlun_lite.STRATEGY.generate(frame, {})
        self.assertEqual(len(result), 5)


class _FakeDataFeed:
    """离线数据源:固定上行 K 线 + 固定 OI。"""

    def klines(self, symbol, interval, limit=240):
        closes = [100.0 + i * 0.1 for i in range(limit)]
        idx = pd.date_range("2026-09-20", periods=limit, freq="15min")
        return pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.001 for c in closes],
                "low": [c * 0.999 for c in closes],
                "close": closes,
                "volume": [1000.0] * limit,
            },
            index=idx,
        )

    def open_interest_usdt(self, symbol):
        return 5_000_000.0


class TestServer(unittest.TestCase):
    def setUp(self) -> None:
        config = RuntimeConfig(
            symbols=("BTCUSDT", "ETHUSDT"),
            default_interval="15m",
            kline_limit=160,
            memory_path=None,
        )
        self.app = create_app(
            config,
            data_feed=_FakeDataFeed(),
            macro_hook=lambda symbol: "22:00 美元指数公布",
        )
        self.client = TestClient(self.app)

    def test_health(self) -> None:
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_catalog(self) -> None:
        body = self.client.get("/api/catalog").json()
        self.assertIn("BTCUSDT", body["symbols"])

    def test_snapshot(self) -> None:
        body = self.client.get("/api/snapshot?symbol=BTCUSDT").json()
        self.assertIn("snapshot_hash", body)
        self.assertIn("ema7", body)
        self.assertEqual(body["symbol"], "BTCUSDT")

    def test_snapshot_unknown_symbol_ok(self) -> None:
        resp = self.client.get("/api/snapshot?symbol=BTC")
        self.assertEqual(resp.status_code, 200)  # fake feed 任何 symbol 都返回数据

    def test_run_auto_channel(self) -> None:
        resp = self.client.post("/api/run", json={"symbol": "BTCUSDT", "channel": "auto"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["symbol"], "BTCUSDT")
        self.assertIn(body["chosen_channel"], ("fast", "standard", "deep"))
        self.assertIn(body["status"], ("accepted", "rejected", "flat"))

    def test_run_then_cards(self) -> None:
        self.client.post("/api/run", json={"symbol": "BTCUSDT", "channel": "fast"})
        cards = self.client.get("/api/cards").json()
        self.assertGreaterEqual(len(cards["cards"]), 1)
        self.assertEqual(cards["cards"][-1]["symbol"], "BTCUSDT")

    def test_run_unknown_symbol_rejected(self) -> None:
        resp = self.client.post("/api/run", json={"symbol": "DOGEUSDT", "channel": "fast"})
        self.assertEqual(resp.status_code, 400)

    def test_executor_fills(self) -> None:
        self.client.post("/api/run", json={"symbol": "BTCUSDT", "channel": "fast"})
        fills = self.client.get("/api/executor/fills").json()
        self.assertIsInstance(fills["fills"], list)

    def test_dashboard_served(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("智能交易工作台", resp.text)

    def test_ws_receives_published_event(self) -> None:
        runtime = self.app.state.runtime
        with self.client.websocket_connect("/ws") as ws:
            from binance_quant.pipeline.server import Event

            runtime.hub.publish(Event(topic="card", data={"symbol": "BTCUSDT"}))
            msg = ws.receive_json()
            self.assertEqual(msg["topic"], "card")
            self.assertEqual(msg["data"]["symbol"], "BTCUSDT")

    def test_hub_fanout_and_unsubscribe(self) -> None:
        from binance_quant.pipeline.server import Event, EventHub

        hub = EventHub()
        q1, q2 = hub.subscribe(), hub.subscribe()
        hub.publish(Event(topic="t", data={"x": 1}))
        self.assertEqual(q1.get_nowait()["data"]["x"], 1)
        self.assertEqual(q2.get_nowait()["data"]["x"], 1)
        hub.unsubscribe(q1)
        self.assertEqual(hub.subscriber_count(), 1)


if __name__ == "__main__":
    unittest.main()
