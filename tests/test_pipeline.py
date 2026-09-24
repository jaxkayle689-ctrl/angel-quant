from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

from binance_quant.pipeline.cards import build_card
from binance_quant.pipeline.channels import (
    suggest_channel,
    run_deep_channel,
    run_fast_channel,
    run_standard_channel,
)
from binance_quant.pipeline.contract import (
    Direction,
    GateResult,
    GateRuleResult,
    OrderTicket,
    OrderType,
    Rating,
    TakeProfit,
)
from binance_quant.pipeline.debate import run_debate, judge
from binance_quant.pipeline.hardgate import GateConfig, HardGate
from binance_quant.pipeline.llm import RuleFallbackLLM
from binance_quant.pipeline.memory import DecisionMemory
from binance_quant.pipeline.ordergen import OrderPlanConfig, PaperExecutor, build_order_ticket
from binance_quant.pipeline.registry import StrategyRegistry, StrategySignal
from binance_quant.pipeline.snapshot import build_snapshot


def _frame(pnls: list[float], start: float = 100.0, step_minutes: int = 15) -> pd.DataFrame:
    closes = [start]
    for p in pnls:
        closes.append(closes[-1] * (1 + p))
    idx = pd.date_range("2026-09-20 09:30", periods=len(closes), freq=f"{step_minutes}min")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.002 for c in closes],
            "low": [c * 0.998 for c in closes],
            "close": closes,
            "volume": [1000 + i * 3 for i in range(len(closes))],
        },
        index=idx,
    )


def _uptrend_frame() -> pd.DataFrame:
    pnls = [0.004] * 159
    return _frame(pnls, step_minutes=1)


def _downtrend_frame() -> pd.DataFrame:
    pnls = [-0.004] * 159
    return _frame(pnls, step_minutes=1)


class TestSnapshot(unittest.TestCase):
    def test_deterministic_same_input_same_output(self) -> None:
        frame = _uptrend_frame()
        first = build_snapshot("BTCUSDT", "1m", frame)
        second = build_snapshot("BTCUSDT", "1m", frame.copy())
        self.assertEqual(first.snapshot_hash, second.snapshot_hash)
        self.assertEqual(first.trend, "up")
        self.assertGreater(first.ema7, first.ema25)
        self.assertGreater(first.close, first.vwap - first.atr14)

    def test_downtrend_detected(self) -> None:
        snap = build_snapshot("BTCUSDT", "1m", _downtrend_frame())
        self.assertEqual(snap.trend, "down")
        self.assertLess(snap.ema7, snap.ema100)

    def test_short_frame_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_snapshot("BTCUSDT", "1m", _uptrend_frame().tail(50))

    def test_evidence_text_has_hash(self) -> None:
        snap = build_snapshot("BTCUSDT", "1m", _uptrend_frame())
        self.assertIn("快照哈希", snap.evidence_text())
        self.assertIn("EMA7", snap.evidence_text())


class TestContract(unittest.TestCase):
    def _ticket(self, tp_prices: list[float] | None = None) -> OrderTicket:
        prices = tp_prices or [52.0, 55.0, 60.0]
        return OrderTicket(
            symbol="SNDKUSDT",
            direction=Direction.LONG,
            order_type=OrderType.MARKET,
            entry=50.0,
            stop_loss=48.0,
            tp=[TakeProfit(price=p, fraction=0.33) for p in prices],
            size=100.0,
            leverage=5.0,
        )

    def test_risk_reward(self) -> None:
        ticket = self._ticket()
        self.assertAlmostEqual(ticket.risk_per_unit(), 2.0)
        self.assertAlmostEqual(ticket.reward_per_unit(), 2.0)

    def test_from_dict_roundtrip(self) -> None:
        ticket = self._ticket()
        rebuilt = OrderTicket.from_dict(ticket.to_dict())
        self.assertEqual(rebuilt.direction, Direction.LONG)
        self.assertEqual(len(rebuilt.tp), 3)
        self.assertAlmostEqual(rebuilt.entry, 50.0)

    def test_rating_parse(self) -> None:
        self.assertEqual(Rating.parse("buy"), Rating.BUY)
        self.assertEqual(Rating.parse("  OverWeight "), Rating.OVERWEIGHT)
        self.assertIsNone(Rating.parse("nonsense"))
        self.assertTrue(Rating.BUY.bullish())
        self.assertEqual(Rating.OVERWEIGHT.to_direction(), Direction.LONG)
        self.assertIsNone(Rating.HOLD.to_direction())


class TestHardGate(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = HardGate(GateConfig(max_leverage=10.0, max_size_usdt=200.0))
        self.atr = 1.0

    def _ok(self) -> OrderTicket:
        return OrderTicket(
            symbol="SNDKUSDT", direction=Direction.LONG, order_type=OrderType.MARKET,
            entry=100.0, stop_loss=98.0,
            tp=[TakeProfit(103.0, 0.5), TakeProfit(106.0, 0.5)],
            size=100.0, leverage=5.0,
        )

    def test_valid_ticket_passes(self) -> None:
        result = self.gate.check(self._ok(), atr=self.atr, mark_price=100.5)
        self.assertTrue(result.passed, result.reasons())

    def test_wrong_side_stop_rejected(self) -> None:
        bad = self._ok()
        bad.stop_loss = 102.0  # 多头的止损在上方,非法
        self.assertFalse(self.gate.check(bad, atr=self.atr, mark_price=100.0).passed)

    def test_tp_unordered_rejected(self) -> None:
        bad = self._ok()
        bad.tp = [TakeProfit(98.0, 0.5), TakeProfit(103.0, 0.5)]
        self.assertFalse(self.gate.check(bad, atr=self.atr, mark_price=100.0).passed)

    def test_leverage_cap_rejected(self) -> None:
        bad = self._ok()
        bad.leverage = 50.0
        self.assertFalse(self.gate.check(bad, atr=self.atr, mark_price=100.0).passed)

    def test_rr_too_low_rejected(self) -> None:
        bad = self._ok()  # rr = 1.5 ok;改 tp1 更小
        bad.tp = [TakeProfit(100.5, 1.0)]
        result = self.gate.check(bad, atr=self.atr, mark_price=100.0)
        self.assertFalse(result.passed)
        self.assertIn("盈亏比", result.reasons())

    def test_expired_rejected(self) -> None:
        bad = self._ok()
        bad.valid_until = bad.created_at - 10
        self.assertFalse(self.gate.check(bad, atr=self.atr, mark_price=100.0).passed)


def _fake_signal(name: str, direction: int, confidence: float = 0.8) -> StrategySignal:
    return StrategySignal(strategy_id=name, name=name, direction=direction,
                          confidence=confidence, key_level=100.0)


class TestRegistry(unittest.TestCase):
    def test_consensus_long(self) -> None:
        registry = StrategyRegistry()
        registry.register_source(lambda frame, p: _fake_signal("chan", 1, 0.8))
        registry.register_source(lambda frame, p: _fake_signal("ema", 1, 0.7))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.assertEqual(report.consensus_direction(), 1)
        self.assertFalse(report.conflicts)

    def test_conflict_detected(self) -> None:
        registry = StrategyRegistry()
        registry.register_source(lambda frame, p: _fake_signal("chan", 1, 0.8))
        registry.register_source(lambda frame, p: _fake_signal("revert", -1, 0.6))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.assertTrue(report.conflicts)
        self.assertIn("分歧", report.conflicts[0])

    def test_strategy_error_isolated(self) -> None:
        registry = StrategyRegistry()

        def boom(frame, p):
            raise RuntimeError("数据源炸了")

        registry.register_source(boom)
        registry.register_source(lambda frame, p: _fake_signal("ok", 1, 0.9))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.assertEqual(len(report.signals), 2)
        self.assertEqual(report.consensus_direction(), 1)


class TestOrderGen(unittest.TestCase):
    def test_ticket_from_consensus(self) -> None:
        snap = build_snapshot("BTCUSDT", "1m", _uptrend_frame())
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("a", 1, 0.9))
        registry.register_source(lambda f, p: _fake_signal("b", 1, 0.8))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        ticket = build_order_ticket(snap, report, OrderPlanConfig())
        self.assertIsNotNone(ticket)
        assert ticket is not None
        self.assertEqual(ticket.direction, Direction.LONG)
        self.assertAlmostEqual(ticket.entry, snap.close, places=6)
        self.assertGreater(ticket.tp[0].price, ticket.entry)
        self.assertLess(ticket.stop_loss, ticket.entry)

    def test_no_consensus_returns_none(self) -> None:
        snap = build_snapshot("BTCUSDT", "1m", _uptrend_frame())
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("a", 1, 0.3))
        registry.register_source(lambda f, p: _fake_signal("b", -1, 0.3))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.assertIsNone(build_order_ticket(snap, report))


class TestFastChannel(unittest.TestCase):
    def test_end_to_end(self) -> None:
        snap = build_snapshot("BTCUSDT", "1m", _uptrend_frame())
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("a", 1, 0.9))
        registry.register_source(lambda f, p: _fake_signal("b", 1, 0.8))
        report = registry.evaluate("BTCUSDT", _uptrend_frame())
        executor = PaperExecutor()
        output = run_fast_channel(snap, report, gate=HardGate(), executor=executor)
        self.assertEqual(output.status, "accepted")
        self.assertEqual(len(executor.filled), 1)
        self.assertIsNotNone(output.card)
        assert output.card is not None
        text = output.card.render_text()
        self.assertIn("BTCUSDT", text)
        self.assertIn("TP1", text)


class TestDebateAndChannels(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = build_snapshot("BTCUSDT", "1m", _uptrend_frame())
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("a", 1, 0.9))
        registry.register_source(lambda f, p: _fake_signal("b", 1, 0.8))
        self.report = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.llm = RuleFallbackLLM(self.snap, self.report)

    def test_debate_and_judge(self) -> None:
        from binance_quant.pipeline.debate import build_evidence
        evidence = build_evidence(self.snap, self.report)
        debate = run_debate(self.llm, self.snap, evidence, rounds=2)
        self.assertEqual(len(debate.turns), 4)
        verdict = judge(self.llm, debate, evidence)
        self.assertIsInstance(verdict.rating, Rating)
        self.assertIn(verdict.rating, (Rating.BUY, Rating.OVERWEIGHT))

    def test_standard_channel_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = DecisionMemory(Path(tmp) / "decisions.jsonl")
            executor = PaperExecutor()
            output = run_standard_channel(
                self.snap, self.report, llm=self.llm,
                gate=HardGate(), executor=executor, memory=memory,
            )
            self.assertEqual(output.status, "accepted")
            self.assertIsNotNone(output.card)
            lines = memory.path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)

    def test_deep_channel_pm_with_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = DecisionMemory(Path(tmp) / "decisions.jsonl")
            executor = PaperExecutor()
            memory.record({"symbol": "BTCUSDT", "rating": "Buy", "channel": "standard",
                           "ticket": {"direction": "long"}})
            memory.record_outcome({"symbol": "BTCUSDT", "pnl_pct": 1.2, "note": "趋势单正常止盈"})
            output = run_deep_channel(
                self.snap, self.report, llm=self.llm,
                gate=HardGate(), executor=executor, memory=memory,
            )
            self.assertIn(output.status, ("accepted", "aborted"))
            self.assertIsNotNone(output.card)
            past = memory.past_context("BTCUSDT")
            self.assertIn("近 1 笔已实现盈亏", past)

    def test_hold_when_report_empty(self) -> None:
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("x", 1, 0.2))
        registry.register_source(lambda f, p: _fake_signal("y", -1, 0.2))
        weak_report = registry.evaluate("BTCUSDT", _uptrend_frame())
        llm = RuleFallbackLLM(self.snap, weak_report)
        with tempfile.TemporaryDirectory() as tmp:
            output = run_standard_channel(
                self.snap, weak_report, llm=llm,
                gate=HardGate(), executor=PaperExecutor(),
                memory=DecisionMemory(Path(tmp) / "m.jsonl"),
            )
            self.assertIsNotNone(output.card)


class TestCards(unittest.TestCase):
    def test_card_render_and_expiry(self) -> None:
        ticket = OrderTicket(
            symbol="SNDKUSDT", direction=Direction.SHORT, order_type=OrderType.LIMIT,
            entry=99.0, stop_loss=101.0,
            tp=[TakeProfit(97.0, 0.5), TakeProfit(95.0, 0.5)],
            size=100.0, leverage=3.0,
        )
        card = build_card("SNDKUSDT", Rating.UNDERWEIGHT, ticket=ticket,
                          gate=GateResult(passed=True, results=[]), channel="deep",
                          evidence_lines=["量缩价跌"], ttl_seconds=60.0)
        self.assertFalse(card.is_expired)
        text = card.render_text()
        self.assertIn("做空", text)
        self.assertIn("TP2", text)
        stale = build_card("SNDKUSDT", Rating.BUY, ticket=None, gate=None,
                           channel="deep", ttl_seconds=-1.0)
        self.assertTrue(stale.is_expired)

    def test_gate_display(self) -> None:
        gate = GateResult(
            passed=False,
            results=[GateRuleResult("杠杆上限", False, "50 > 20")],
        )
        self.assertIn("杠杆上限", gate.reasons())


class TestRouter(unittest.TestCase):
    def test_router(self) -> None:
        registry = StrategyRegistry()
        registry.register_source(lambda f, p: _fake_signal("a", 1, 0.9))
        registry.register_source(lambda f, p: _fake_signal("b", 1, 0.9))
        strong = registry.evaluate("BTCUSDT", _uptrend_frame())
        self.assertEqual(suggest_channel(strong, llm_available=True), "fast")

        registry2 = StrategyRegistry()
        registry2.register_source(lambda f, p: _fake_signal("a", 1, 0.9))
        registry2.register_source(lambda f, p: _fake_signal("b", -1, 0.9))
        split = registry2.evaluate("BTCUSDT", _uptrend_frame())
        self.assertEqual(suggest_channel(split, llm_available=True), "deep")
        self.assertEqual(suggest_channel(strong, llm_available=False), "fast")


if __name__ == "__main__":
    unittest.main()
