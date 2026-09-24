from __future__ import annotations

"""订单票契约与五档评级。

订单票是系统里唯一会变成真实订单的对象,所有通道殊途同归。
入场/止损/止盈一律绝对价格,禁止百分比。
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class Rating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"

    @classmethod
    def parse(cls, text: str) -> "Rating | None":
        normalized = (text or "").strip().lower()
        for item in cls:
            if item.value.lower() == normalized:
                return item
        return None

    def bullish(self) -> bool:
        return self in (Rating.BUY, Rating.OVERWEIGHT)

    def bearish(self) -> bool:
        return self in (Rating.SELL, Rating.UNDERWEIGHT)

    def to_direction(self) -> Direction | None:
        if self.bullish():
            return Direction.LONG
        if self.bearish():
            return Direction.SHORT
        return None


@dataclass(frozen=True)
class TakeProfit:
    price: float
    fraction: float  # 该档止盈的平仓比例 0<f<=1


@dataclass
class OrderTicket:
    """订单票:方向、订单类型、入场、止损、三档止盈、仓位与杠杆。"""

    symbol: str
    direction: Direction
    order_type: OrderType
    entry: float                  # 入场价(限价单即挂单价)
    stop_loss: float
    tp: list[TakeProfit]          # 1~3 档
    size: float                   # 名义仓位 USDT
    leverage: float
    time_in_force: str = "GTC"
    source: str = ""              # 生成通道/角色,如 fast / trader
    reason: str = ""              # 生成理由摘要
    created_at: float = 0.0
    valid_until: float = 0.0      # 过期作废时间戳(0=不过期)
    ticket_id: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()
        if not self.ticket_id:
            self.ticket_id = uuid.uuid4().hex[:16]

    @property
    def is_expired(self) -> bool:
        return bool(self.valid_until) and time.time() > self.valid_until

    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop_loss)

    def reward_per_unit(self) -> float:
        return abs(self.tp[0].price - self.entry) if self.tp else 0.0

    def risk_reward(self) -> float:
        risk = self.risk_per_unit()
        return self.reward_per_unit() / risk if risk > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "order_type": self.order_type.value,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "tp": [{"price": t.price, "fraction": t.fraction} for t in self.tp],
            "size": self.size,
            "leverage": self.leverage,
            "time_in_force": self.time_in_force,
            "source": self.source,
            "reason": self.reason,
            "created_at": self.created_at,
            "valid_until": self.valid_until,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OrderTicket":
        direction = Direction(str(payload["direction"]).lower())
        order_type = OrderType(str(payload.get("order_type", "market")).lower())
        raw_tp = payload.get("tp") or []
        if isinstance(raw_tp, dict):
            raw_tp = [raw_tp[k] for k in sorted(raw_tp)]
        tp: list[TakeProfit] = []
        for item in raw_tp:
            if isinstance(item, dict):
                tp.append(TakeProfit(price=float(item["price"]), fraction=float(item.get("fraction", 0.0))))
            else:
                tp.append(TakeProfit(price=float(item), fraction=0.0))
        return cls(
            symbol=str(payload["symbol"]),
            direction=direction,
            order_type=order_type,
            entry=float(payload["entry"]),
            stop_loss=float(payload["stop_loss"]),
            tp=tp,
            size=float(payload["size"]),
            leverage=float(payload.get("leverage", 1.0)),
            time_in_force=str(payload.get("time_in_force", "GTC")),
            source=str(payload.get("source", "")),
            reason=str(payload.get("reason", "")),
            valid_until=float(payload.get("valid_until", 0.0)),
        )


@dataclass(frozen=True)
class GateRuleResult:
    rule: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    passed: bool
    results: list[GateRuleResult]
    degraded: list[str] = field(default_factory=list)

    def reasons(self) -> str:
        failed = [r for r in self.results if not r.passed]
        if not failed:
            return "全部通过"
        return "; ".join(f"{r.rule}: {r.detail}" for r in failed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "degraded": list(self.degraded),
            "rules": [{"rule": r.rule, "passed": r.passed, "detail": r.detail} for r in self.results],
        }
