from __future__ import annotations

"""三通道运行器:快速(0 LLM)/ 标准(风控辩论关)/ 深度(全链路)。

- fast:     快照+策略信号 → 规则订单生成器 → 硬闸门 → 执行端
- standard: + 证据包 → 多空辩论 → 裁判 → 交易员 → 硬闸门 → 执行端
- deep:     standard + 三方风控辩论 → PM 终审(+决策记忆回注)→ 卡片推送
"""

from dataclasses import dataclass
from typing import Any

from .cards import StrategyCard, build_card
from .contract import GateResult, OrderTicket, Rating
from .debate import (
    build_evidence,
    judge,
    rule_based_ticket,
    run_debate,
    run_pm,
    run_risk_debate,
    run_trader,
)
from .hardgate import HardGate
from .llm import LLMProvider
from .memory import DecisionMemory
from .ordergen import OrderPlanConfig, PaperExecutor, run_fast_cycle
from .registry import StrategyReport
from .snapshot import TechnicalSnapshot

CHANNEL_FAST = "fast"
CHANNEL_STANDARD = "standard"
CHANNEL_DEEP = "deep"


@dataclass(frozen=True)
class ChannelOutput:
    channel: str
    status: str                       # accepted / rejected / flat / aborted
    card: StrategyCard | None
    extras: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "status": self.status,
            "card": self.card.to_dict() if self.card else None,
            "extras": self.extras,
        }


def run_fast_channel(
    snapshot: TechnicalSnapshot,
    report: StrategyReport,
    *,
    gate: HardGate,
    executor: PaperExecutor,
    plan_config: OrderPlanConfig | None = None,
) -> ChannelOutput:
    result = run_fast_cycle(snapshot, report, gate=gate, executor=executor, plan_config=plan_config)
    ticket = None
    if result["ticket"]:
        from .contract import OrderTicket as _OT
        ticket = _OT.from_dict(result["ticket"])
    rating = Rating.HOLD
    if ticket is not None:
        rating = Rating.BUY if ticket.direction.value == "long" else Rating.SELL
    gate_result = gate.check(ticket, atr=snapshot.atr14, mark_price=snapshot.close) if ticket else None
    card = build_card(
        snapshot.symbol, rating,
        ticket=ticket, gate=gate_result, channel=CHANNEL_FAST,
        evidence_lines=[result["reason"]],
    )
    return ChannelOutput(
        channel=CHANNEL_FAST,
        status=result["status"],
        card=card,
        extras={"cycle": result},
    )


def _judge_to_card(
    snapshot: TechnicalSnapshot,
    judgement_rating: Rating,
    ticket: OrderTicket | None,
    gate_result: GateResult | None,
    channel: str,
    evidence_summary: list[str],
    risk_notes: list[str] | None = None,
) -> StrategyCard:
    return build_card(
        snapshot.symbol, judgement_rating,
        ticket=ticket, gate=gate_result, channel=channel,
        evidence_lines=evidence_summary,
        risk_notes=risk_notes,
    )


def run_standard_channel(
    snapshot: TechnicalSnapshot,
    report: StrategyReport,
    *,
    llm: LLMProvider,
    gate: HardGate,
    executor: PaperExecutor,
    memory: DecisionMemory | None = None,
    debate_rounds: int = 1,
    evidence_extras: dict[str, str] | None = None,
) -> ChannelOutput:
    """标准通道:辩论 + 交易员 + 硬闸门(风控辩论关闭)。"""
    extras = dict(evidence_extras or {})
    evidence = build_evidence(
        snapshot, report,
        options_evidence=extras.get("options", "未提供"),
        macro_evidence=extras.get("macro", "未提供"),
        liquidation_evidence=extras.get("liquidation", "未提供"),
    )
    debate = run_debate(llm, snapshot, evidence, rounds=debate_rounds)
    verdict = judge(llm, debate, evidence)

    if verdict.rating is Rating.HOLD:
        card = _judge_to_card(
            snapshot, Rating.HOLD, None, None, CHANNEL_STANDARD,
            ["多方/空方证据权衡后仍均衡,放弃入场"], [],
        )
        if memory:
            memory.record({
                "symbol": snapshot.symbol, "channel": CHANNEL_STANDARD,
                "rating": Rating.HOLD.value, "ticket": None,
                "snapshot_hash": snapshot.snapshot_hash,
            })
        return ChannelOutput(CHANNEL_STANDARD, "flat", card,
                             {"debate": [t.__dict__ for t in debate.turns],
                              "rationale": verdict.rationale})

    ticket = run_trader(llm, snapshot, verdict) or rule_based_ticket(snapshot, verdict)
    if ticket is None:
        card = _judge_to_card(snapshot, verdict.rating, None, None,
                              CHANNEL_STANDARD, ["交易员未产出合法订单票,放弃"], [])
        return ChannelOutput(CHANNEL_STANDARD, "aborted", card,
                             {"rationale": verdict.rationale})

    gate_result = gate.check(ticket, atr=snapshot.atr14, mark_price=snapshot.close)
    if not gate_result.passed:
        card = _judge_to_card(snapshot, verdict.rating, ticket, gate_result,
                              CHANNEL_STANDARD, [verdict.rationale[:120]], [])
        if memory:
            memory.record({"symbol": snapshot.symbol, "channel": CHANNEL_STANDARD,
                           "rating": verdict.rating.value, "ticket": ticket.to_dict(),
                           "gate": gate_result.to_dict(),
                           "snapshot_hash": snapshot.snapshot_hash})
        return ChannelOutput(CHANNEL_STANDARD, "rejected", card,
                             {"gate": gate_result.to_dict()})

    execution = executor.submit(ticket)
    card = _judge_to_card(snapshot, verdict.rating, ticket, gate_result,
                          CHANNEL_STANDARD,
                          [verdict.rationale[:120]],
                          list(gate_result.degraded))
    if memory:
        memory.record({"symbol": snapshot.symbol, "channel": CHANNEL_STANDARD,
                       "rating": verdict.rating.value, "ticket": ticket.to_dict(),
                       "gate": gate_result.to_dict(),
                       "snapshot_hash": snapshot.snapshot_hash})
    return ChannelOutput(CHANNEL_STANDARD, "accepted", card,
                         {"debate": [t.__dict__ for t in debate.turns],
                          "rationale": verdict.rationale,
                          "execution": {"accepted": execution.accepted,
                                        "detail": execution.detail}})


def run_deep_channel(
    snapshot: TechnicalSnapshot,
    report: StrategyReport,
    *,
    llm: LLMProvider,
    gate: HardGate,
    executor: PaperExecutor,
    memory: DecisionMemory | None = None,
    debate_rounds: int = 1,
    risk_rounds: int = 1,
    evidence_extras: dict[str, str] | None = None,
) -> ChannelOutput:
    """深度通道:标准链路 + 三方风控辩论 + PM 终审 + 记忆回注 + 卡片。"""
    standard = run_standard_channel(
        snapshot, report,
        llm=llm, gate=gate, executor=executor, memory=memory,
        debate_rounds=debate_rounds, evidence_extras=evidence_extras,
    )
    if standard.status in ("flat", "rejected", "aborted"):
        # 无票据时不值得再烧 LLM;直接按标准结果返回,通道标深。
        return ChannelOutput(CHANNEL_DEEP, standard.status, standard.card, standard.extras)

    assert standard.card is not None and standard.card.ticket is not None
    ticket = standard.card.ticket
    verdict_rating = Rating.parse(standard.card.rating.value) or standard.card.rating

    from .debate import Judgement
    judgement = Judgement(
        rating=verdict_rating,
        rationale=str(standard.extras.get("rationale", "")),
    )
    risk = run_risk_debate(llm, ticket, snapshot, judgement, rounds=risk_rounds)
    past = memory.past_context(snapshot.symbol) if memory else "无历史决策记录。"
    decision = run_pm(llm, judgement, ticket, risk, past)

    if decision.rating is Rating.HOLD or not decision.rating.bullish() and not decision.rating.bearish():
        # PM 否决:不下单(已提交到 paper 的先例仅作流程演示;真实执行端中此时应撤单)
        card = _judge_to_card(snapshot, decision.rating, ticket, gate.check(
            ticket, atr=snapshot.atr14, mark_price=snapshot.close),
            CHANNEL_DEEP, [decision.summary[:120]], decision.risk_notes)
        if memory:
            memory.record({"symbol": snapshot.symbol, "channel": CHANNEL_DEEP,
                           "rating": decision.rating.value, "ticket": ticket.to_dict(),
                           "pm": decision.summary[:200],
                           "snapshot_hash": snapshot.snapshot_hash})
        return ChannelOutput(CHANNEL_DEEP, "aborted", card,
                             {"risk_debate": [t.__dict__ for t in risk.turns],
                              "pm": decision.summary})

    card = _judge_to_card(
        snapshot, decision.rating, ticket,
        gate.check(ticket, atr=snapshot.atr14, mark_price=snapshot.close),
        CHANNEL_DEEP,
        [decision.summary[:120]] + [t.text[:80] for t in risk.turns[:2]],
        decision.risk_notes,
    )
    if memory:
        memory.record({"symbol": snapshot.symbol, "channel": CHANNEL_DEEP,
                       "rating": decision.rating.value, "ticket": ticket.to_dict(),
                       "pm": decision.summary[:200],
                       "snapshot_hash": snapshot.snapshot_hash})
    return ChannelOutput(CHANNEL_DEEP, "accepted", card,
                         {"risk_debate": [t.__dict__ for t in risk.turns],
                          "pm": decision.summary,
                          "past_context_used": past})


def suggest_channel(report: StrategyReport, *, llm_available: bool) -> str:
    """通道自动建议:信号一致且置信度高→快速;有分歧→深度;其余→标准。"""
    if not llm_available:
        return CHANNEL_FAST
    if report.conflicts:
        return CHANNEL_DEEP
    if report.consensus_confidence() >= 0.75:
        return CHANNEL_FAST
    return CHANNEL_STANDARD
