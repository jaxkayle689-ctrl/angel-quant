from __future__ import annotations

"""缠论策略(lite):分型 → 笔 → 笔破坏信号。

与 chanlun/ 的 Pine 实现同一套纪律(见 chanlun/tests 的数值契约):
- 分型:严格局部最高/最低三根分型;
- 笔:相邻异种分型在方向正确且跨度达标时配套;
- 信号:新笔完成(冻结)瞬间,按笔方向给出 ±1;
  向下破坏前笔起点判空、向上破坏前笔起点判多——方向取自**冻结笔的方向**。

这是注册表对接的"最小可信实现",并非 chanlun 全理论;
精度主力版本仍以 TradingView Pine 为准(chanlun_phase1.pine)。
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from binance_quant.strategy_api import Strategy, StrategyParameter


@dataclass(frozen=True)
class Fractal:
    kind: int      # 1 顶分型 / -1 底分型
    index: int
    price: float


def fractals(frame: pd.DataFrame, strict: bool = True) -> list[Fractal]:
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    out: list[Fractal] = []
    for i in range(1, len(frame) - 1):
        h0, h1, h2 = highs[i - 1], highs[i], highs[i + 1]
        l0, l1, l2 = lows[i - 1], lows[i], lows[i + 1]
        if strict:
            top = h1 > h0 and h1 > h2 and l1 > l0 and l1 > l2
            bottom = h1 < h0 and h1 < h2 and l1 < l0 and l1 < l2
        else:
            top = h1 >= h0 and h1 >= h2 and (h1 > h0 or h1 > h2)
            bottom = h1 <= h0 and h1 <= l0 and h1 < l2
        if top and not bottom:
            out.append(Fractal(kind=1, index=i, price=h1))
        elif bottom and not top:
            out.append(Fractal(kind=-1, index=i, price=l1))
    return out


def _valid(a: Fractal, b: Fractal, min_gap: int) -> bool:
    """相邻正反分型可配成笔的同 chanlun 检查。"""
    if a.kind == b.kind:
        return False
    if b.index - a.index < max(4, min_gap - 1):
        return False
    if a.kind == -1:      # 底 → 顶:价格须更高
        return b.price > a.price
    return b.price < a.price


def pens(fractal_list: list[Fractal], min_gap: int = 5) -> list[tuple[Fractal, Fractal]]:
    """笔构造:对分型流走 anchor/tip 状态机,返回全部冻结笔(起点, 终点)。"""
    anchor: Fractal | None = None
    tip: Fractal | None = None
    frozen: list[tuple[Fractal, Fractal]] = []
    for f in fractal_list:
        if anchor is None:
            anchor = f
        elif tip is None:
            if f.kind == anchor.kind:
                if (f.price - anchor.price) * f.kind > 0:
                    anchor = f
            elif _valid(anchor, f, min_gap):
                tip = f
        elif f.kind == tip.kind:
            if (f.price - tip.price) * f.kind > 0 and _valid(anchor, f, min_gap):
                tip = f
        elif _valid(tip, f, min_gap):
            frozen.append((anchor, tip))
            anchor, tip = tip, f
    return frozen


def pen_signals(frame: pd.DataFrame, *, strict: bool = True, min_gap: int = 5) -> list[tuple[int, int, float]]:
    """返回 (bar_idx, signal, price_list)。冻结笔方向即信号方向。"""
    frozen = pens(fractals(frame, strict=strict), min_gap=min_gap)
    out: list[tuple[int, int, float]] = []
    for begin, end in frozen:
        direction = 1 if end.kind == -1 else -1  # 底→顶 = 向上笔
        out.append((end.index, direction, end.price))
    return out


class ChanLunLiteStrategy(Strategy):
    strategy_id = "chanlun_lite"
    name = "缠论 · 分型笔破坏(lite)"
    version = "0.1.0"
    description = (
        "改编自 chanlun/ 的精简实现:分型→笔→新笔方向信号。"
        "完整缠论逻辑请以 TradingView Pine 版本为准。"
    )
    market_types = ("crypto_futures", "stock", "etf", "hk")
    capabilities = ("long", "short")
    primary_interval = "15m"
    required_intervals = ("5m", "1h")
    history_limit = 240
    parameters = (
        StrategyParameter(
            key="strict", label="严格分型", kind="boolean", default=True,
        ),
        StrategyParameter(
            key="min_gap", label="笔最小跨度(根)", kind="integer",
            default=5, minimum=3, maximum=20, step=1,
        ),
    )

    def generate(self, frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
        params = self.normalized_parameters(parameters)
        result = frame.copy()
        result["signal"] = 0
        for idx, direction, _price in pen_signals(
            result, strict=bool(params["strict"]), min_gap=int(params["min_gap"])
        ):
            if 0 <= idx < len(result):
                result.iloc[idx, result.columns.get_loc("signal")] = direction
        return result


STRATEGY = ChanLunLiteStrategy()
