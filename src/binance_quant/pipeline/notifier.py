from __future__ import annotations

"""飞书策略卡片渲染:StrategyCard → 飞书 interactive card JSON。

复用现有 agent_engine.FeishuNotifier 的 _send / sign 通道:
push_card(notifier, card) 一行完成推送;本地构建 JSON 可无网络测试。
"""

from typing import Any

from .cards import StrategyCard
from .contract import Direction

_PALETTE = {
    "Buy": "green",
    "Overweight": "green",
    "Sell": "red",
    "Underweight": "red",
    "Hold": "grey",
}

_DIR_LABELS = {"long": "做多", "short": "做空", None: "观望"}


def _plain(text: str) -> dict:
    return {"tag": "plain_text", "content": text}


def _lark_md(text: str) -> dict:
    return {"tag": "lark_md", "content": text}


def _field(label: str, value: str) -> dict:
    return {"is_short": True, "text": _lark_md(f"**{label}**\n{value}")}


def _headline(card: StrategyCard) -> tuple[str, str]:
    tpl = _PALETTE.get(card.rating.value, "grey")
    return f"策略卡片 · {card.symbol}", tpl


def _price_text(card: StrategyCard) -> str:
    if not card.ticket:
        return "观望 · 不下单"
    t = card.ticket
    tp_txt = " / ".join(f"TP{i+1} {p.price:g}({p.fraction:.0%})" for i, p in enumerate(t.tp))
    return (
        f"{t.order_type.value} 入场 **{t.entry:g}** · 止损 **{t.stop_loss:g}**\n"
        f"止盈 {tp_txt} · 仓位 **{t.size:g}U** ×{t.leverage:g} 杠杆"
    )


def build_feishu_card(card: StrategyCard) -> dict[str, Any]:
    title, theme = _headline(card)
    elements: list[dict] = []

    header_fields = [
        _field("评级", card.rating.value),
        _field("方向", _DIR_LABELS.get(card.ticket.direction.value if card.ticket else None, "观望")),
        _field("通道", card.channel),
        _field("有效期", f"{_fmt_ts(card.valid_until)}（{'已过期' if card.is_expired else '有效'}）"),
    ]
    elements.append(_field_row(header_fields))

    elements.append({
        "tag": "div",
        "fields": [{"is_short": False, "text": _lark_md(f"**订单票**\n{_price_text(card)}")}],
    })

    if card.evidence_lines:
        body = "\n".join(f"• {line}" for line in card.evidence_lines[:6])
        elements.append({
            "tag": "div",
            "fields": [{"is_short": False, "text": _lark_md(f"**证据摘要**\n{body}")}],
        })
    if card.risk_notes:
        body = "\n".join(f"⚠ {n}" for n in card.risk_notes[:4])
        elements.append({
            "tag": "div",
            "fields": [{"is_short": False, "text": _lark_md(f"**风控备注**\n{body}")}],
        })
    if card.gate:
        elements.append({
            "tag": "div",
            "fields": [{"is_short": False, "text": _lark_md(
                "**硬闸门**\n" + ("✅ 通过" if card.gate.passed else f"❌ {card.gate.reasons()}")
            )}],
        })

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [_plain(
            f"生成时间 {_fmt_ts(card.created_at)} · 自动推送,不构成投资建议"
        )],
    })

    return {
        "config": {"wide_screen_mode": True, "enable_forward": True},
        "header": {"title": _plain(title), "template": theme},
        "elements": elements,
    }


def _field_row(fields: list[dict]) -> dict:
    return {"tag": "div", "fields": fields}


def _fmt_ts(ts: float) -> str:
    import time as _time

    return _time.strftime("%m-%d %H:%M:%S", _time.localtime(ts))


def push_card(notifier: Any, card: StrategyCard) -> dict[str, Any]:
    """借现有 FeishuNotifier 的 _send 通道推送卡片。"""
    payload = build_feishu_card(card)
    result = notifier._send(payload)
    return result
