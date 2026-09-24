from __future__ import annotations

"""策略卡片:深度通道的推送产物(股票日内场景)。

卡片 = 券头(方向/评级)+ 订单票 + 证据摘要 + 硬闸门状态 + 有效期。
同时提供纯文本渲染(飞书/通知中心)与结构化字典(API/前端)。
"""

import time
from dataclasses import dataclass, field
from typing import Any

from .contract import Direction, GateResult, OrderTicket, Rating

CARD_TTL_SECONDS = 30 * 60  # 卡片默认 30 分钟有效


@dataclass(frozen=True)
class StrategyCard:
    symbol: str
    rating: Rating
    ticket: OrderTicket | None
    gate: GateResult | None
    evidence_lines: list[str]
    channel: str
    created_at: float
    valid_until: float
    risk_notes: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.valid_until

    def direction_label(self) -> str:
        if self.ticket is None:
            return "观望"
        return "做多" if self.ticket.direction is Direction.LONG else "做空"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rating": self.rating.value,
            "channel": self.channel,
            "direction": self.direction_label(),
            "created_at": self.created_at,
            "valid_until": self.valid_until,
            "expired": self.is_expired,
            "ticket": self.ticket.to_dict() if self.ticket else None,
            "gate": self.gate.to_dict() if self.gate else None,
            "evidence": list(self.evidence_lines),
            "risk_notes": list(self.risk_notes),
        }

    def render_text(self) -> str:
        lines = [
            f"【策略卡片】{self.symbol} · {self.rating.value} · {self.direction_label()}({self.channel})",
            f"生成 {time.strftime('%H:%M', time.localtime(self.created_at))} · "
            f"有效至 {time.strftime('%H:%M', time.localtime(self.valid_until))}"
            + (" ⚠已过期" if self.is_expired else ""),
        ]
        if self.ticket:
            t = self.ticket
            lines.append(
                f"订单票:{t.order_type.value} 入场 {t.entry} | 止损 {t.stop_loss}"
            )
            tp_text = " / ".join(f"TP{i+1} {p.price}({p.fraction:.0%})" for i, p in enumerate(t.tp))
            lines.append(f"止盈:{tp_text} 仓位 {t.size}U x{t.leverage:g}")
        if self.evidence_lines:
            lines.append("证据:" + " | ".join(self.evidence_lines[:4]))
        if self.gate and not self.gate.passed:
            lines.append(f"硬闸门拦截:{self.gate.reasons()}")
        if self.gate and self.gate.degraded:
            lines.append("降级提醒:" + ";".join(self.gate.degraded))
        for note in self.risk_notes[:3]:
            lines.append(f"风险:{note}")
        return "\n".join(lines)


def build_card(
    symbol: str,
    rating: Rating,
    *,
    ticket: OrderTicket | None,
    gate: GateResult | None,
    channel: str,
    evidence_lines: list[str] | None = None,
    risk_notes: list[str] | None = None,
    ttl_seconds: float = CARD_TTL_SECONDS,
) -> StrategyCard:
    now = time.time()
    return StrategyCard(
        symbol=symbol,
        rating=rating,
        ticket=ticket,
        gate=gate,
        evidence_lines=evidence_lines or [],
        channel=channel,
        created_at=now,
        valid_until=now + ttl_seconds,
        risk_notes=risk_notes or [],
    )
