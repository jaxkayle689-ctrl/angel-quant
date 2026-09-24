from __future__ import annotations

"""策略信号可插拔注册表。

复用 strategy_api.Strategy 契约(generate(frame, parameters) → signal −1/0/1);
新增策略 = 注册表加一条,主结构不动。冲突信号是辩论素材而非噪音。
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

MIN_CONFIDENCE = 0.05


@dataclass(frozen=True)
class StrategySignal:
    strategy_id: str
    name: str
    direction: int          # -1 / 0 / 1
    confidence: float       # 0~1
    key_level: float = 0.0  # 该策略当前关注的关键价位
    note: str = ""
    as_of: float = field(default_factory=time.time)

    def label(self) -> str:
        return {1: "long", -1: "short", 0: "flat"}[self.direction]


@dataclass(frozen=True)
class StrategyReport:
    symbol: str
    signals: list[StrategySignal]
    conflicts: list[str]
    as_of: float = field(default_factory=time.time)

    def consensus_direction(self, min_confidence: float = 0.4) -> int:
        """按置信度加权的方向共识(仅快速通道使用;LLM 通道把冲突当素材)。"""
        score = 0.0
        for signal in self.signals:
            if signal.confidence >= min_confidence:
                score += signal.direction * signal.confidence
        if score > 0:
            return 1
        if score < 0:
            return -1
        return 0

    def consensus_confidence(self) -> float:
        if not self.signals:
            return 0.0
        direction = self.consensus_direction()
        if direction == 0:
            return 0.0
        total = sum(s.confidence for s in self.signals)
        if total <= 0:
            return 0.0
        aligned = sum(s.confidence for s in self.signals if s.direction == direction)
        return round(aligned / total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "consensus_direction": self.consensus_direction(),
            "consensus_confidence": self.consensus_confidence(),
            "conflicts": list(self.conflicts),
            "signals": [
                {
                    "strategy_id": s.strategy_id,
                    "name": s.name,
                    "direction": s.direction,
                    "label": s.label(),
                    "confidence": s.confidence,
                    "key_level": s.key_level,
                    "note": s.note,
                    "as_of": s.as_of,
                }
                for s in self.signals
            ],
        }


SignalSource = Callable[[pd.DataFrame, dict[str, Any]], StrategySignal]


class StrategyRegistry:
    """注册策略对象(strategy_api.Strategy)或原生信号函数。"""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Any, dict[str, Any]]] = {}

    def register_strategy(self, strategy: Any, parameters: dict[str, Any] | None = None, *, enabled: bool = True) -> None:
        """注册 strategy_api 契约对象;parameters 为该策略的启用参数。"""
        strategy_id = getattr(strategy, "strategy_id", None)
        if not strategy_id:
            raise ValueError("策略缺少 strategy_id。")
        self._entries[str(strategy_id)] = (
            (strategy, dict(parameters or {})) if enabled else (None, {})
        )

    def register_source(
        self,
        source: SignalSource,
        parameters: dict[str, Any] | None = None,
        *,
        strategy_id: str | None = None,
    ) -> None:
        """注册轻量信号函数(frame, parameters) → StrategySignal。"""
        key = strategy_id or getattr(source, "strategy_id", None) or f"{source.__name__}#{len(self._entries)}"
        self._entries[str(key)] = (source, dict(parameters or {}))

    def unregister(self, strategy_id: str) -> None:
        self._entries.pop(strategy_id, None)

    def enabled_ids(self) -> list[str]:
        return [key for key, (entry, _) in self._entries.items() if entry is not None]

    def _run_one(self, entry: Any, params: dict[str, Any], frame: pd.DataFrame) -> StrategySignal:
        if hasattr(entry, "generate"):
            output = entry.generate(frame.copy(), params)
            signal_col = output["signal"].tail(10)
            latest = int(signal_col.iloc[-1]) if len(signal_col) else 0
            active = signal_col[signal_col != 0]
            direction = int(active.iloc[-1]) if len(active) else 0
            consistency = float((signal_col == direction).sum() / max(len(signal_col), 1)) if direction else 0.0
            return StrategySignal(
                strategy_id=str(entry.strategy_id),
                name=str(getattr(entry, "name", entry.strategy_id)),
                direction=direction,
                confidence=round(min(0.4 + 0.6 * consistency, 1.0), 4) if direction else 0.0,
                note=f"近 {len(signal_col)} 根同向占比 {consistency:.0%}",
            )
        return entry(frame.copy(), params)

    def evaluate(self, symbol: str, frame: pd.DataFrame, *, key_level: float = 0.0) -> StrategyReport:
        signals: list[StrategySignal] = []
        for strategy_id, (entry, params) in self._entries.items():
            if entry is None:
                continue
            try:
                signal = self._run_one(entry, params, frame)
            except Exception as exc:  # noqa: BLE001 — 单策略失败不拖垮整层
                signals.append(
                    StrategySignal(
                        strategy_id=strategy_id,
                        name=strategy_id,
                        direction=0,
                        confidence=0.0,
                        note=f"error: {exc}",
                    )
                )
                continue
            if key_level and not signal.key_level:
                signal = StrategySignal(
                    strategy_id=signal.strategy_id,
                    name=signal.name,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    key_level=key_level,
                    note=signal.note,
                    as_of=signal.as_of,
                )
            signals.append(signal)

        directions = {s.direction for s in signals if s.confidence >= MIN_CONFIDENCE and s.direction != 0}
        conflicts: list[str] = []
        if 1 in directions and -1 in directions:
            longs = [s.name for s in signals if s.direction == 1 and s.confidence >= MIN_CONFIDENCE]
            shorts = [s.name for s in signals if s.direction == -1 and s.confidence >= MIN_CONFIDENCE]
            conflicts.append(f"分歧:做多[{', '.join(longs)}] vs 做空[{', '.join(shorts)}]")

        return StrategyReport(symbol=symbol, signals=signals, conflicts=conflicts)
