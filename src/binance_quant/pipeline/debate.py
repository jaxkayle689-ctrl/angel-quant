from __future__ import annotations

"""决策链:多空辩论 → 裁判 → 交易员(订单票) → 风控辩论(可选) → PM 终审。

关键纪律(来自 TradingAgents 源码的教训,全部落实):
1. 冲突不是 Hold 的理由——裁判必须在证据冲突时选边;
   Hold 只用于"权衡后证据仍然均衡"或"证据太薄"。
2. 交易员输出绝对价格,禁止百分比。
3. 交易员要回看技术快照的价格结构(964 号坑:计划里丢了价位)。
4. 辩论双方拿到对方最新一条发言,必须逐条回应,不能罗列数据。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .contract import Direction, OrderTicket, OrderType, Rating, TakeProfit
from .llm import LLMProvider
from .registry import StrategyReport
from .snapshot import TechnicalSnapshot

RATING_PATTERN = re.compile(r"(?:Rating|评级)\s*[:：]\s*(Buy|Overweight|Hold|Underweight|Sell)", re.I)


@dataclass(frozen=True)
class DebateTurn:
    speaker: str
    text: str


@dataclass(frozen=True)
class Debate:
    turns: list[DebateTurn]
    rounds: int

    def render(self) -> str:
        return "\n".join(f"[{t.speaker}] {t.text}" for t in self.turns)


@dataclass(frozen=True)
class Judgement:
    rating: Rating
    rationale: str
    actions: str = ""


@dataclass(frozen=True)
class PortfolioDecision:
    rating: Rating
    summary: str
    risk_notes: list[str] = field(default_factory=list)


def build_evidence(
    snapshot: TechnicalSnapshot,
    report: StrategyReport | None = None,
    *,
    options_evidence: str = "未提供(期权结构分析师未启用/标的不适用)",
    macro_evidence: str = "未提供(宏观日历数据缺失)",
    liquidation_evidence: str = "未提供(CoinGlass 数据缺失)",
) -> str:
    """拼装四分析师证据文本。缺失数据显式标注,不参与编造。"""
    lines = [
        "=== 技术分析报告(确定性快照)===",
        snapshot.evidence_text(),
        "",
        "=== 期权结构报告 ===",
        options_evidence,
        "",
        "=== 宏观事件报告 ===",
        macro_evidence,
        "",
        "=== 清算流动性报告 ===",
        liquidation_evidence,
    ]
    if report is not None:
        lines += [
            "",
            "=== 策略信号汇总(注册表)===",
            json.dumps(report.to_dict()["signals"], ensure_ascii=False, indent=1),
            f"共识方向:{report.consensus_direction()} 共识置信度:{report.consensus_confidence():.0%}",
        ]
        for conflict in report.conflicts:
            lines.append(f"!! {conflict}")
    return "\n".join(lines)


_NO_LISTING = "逐条回应对方最新观点,不要罗列数据;证据缺失处明确说『无证据』而不是编造。"


def run_debate(
    llm: LLMProvider,
    snapshot: TechnicalSnapshot,
    evidence: str,
    *,
    rounds: int = 1,
) -> Debate:
    """多空对抗辩论。rounds 为每方发言次数。"""
    turns: list[DebateTurn] = []
    last_opponent = "对方尚未发言,请先立论。"
    for _ in range(max(1, rounds)):
        bull_text = llm.complete(
            "bull",
            "你是多方研究员。只许寻找做多证据并构建最大多头论据。",
            f"证据包:\n{evidence}\n\n对方(空方)最新观点:{last_opponent}\n{_NO_LISTING}",
        )
        turns.append(DebateTurn(speaker="bull", text=bull_text.strip()))
        bear_text = llm.complete(
            "bear",
            "你是空方研究员。只许寻找做空证据并逐条攻击多方论证中最薄弱处。",
            f"证据包:\n{evidence}\n\n对方(多方)最新观点:{bull_text}\n{_NO_LISTING}",
        )
        turns.append(DebateTurn(speaker="bear", text=bear_text.strip()))
        last_opponent = bear_text.strip()
    return Debate(turns=turns, rounds=rounds)


def judge(llm: LLMProvider, debate: Debate, evidence: str) -> Judgement:
    text = llm.complete(
        "judge",
        "你是研究经理(裁判)。铁律:辩论永远存在冲突证据,冲突本身不是 Hold 的理由;"
        "权衡两边证据强弱后必须站队,按优势方优势程度给 Buy/Overweight/Hold/Underweight/Sell 五档之一;"
        "只在证据确实均衡或太薄时给 Hold。",
        f"证据包:\n{evidence}\n\n辩论记录:\n{debate.render()}\n\n"
        "输出格式:第一行『Rating: <五档之一>』,随后是裁决理由(哪些论证决定了结果)和对交易员的具体指示。",
    )
    match = RATING_PATTERN.search(text)
    rating = Rating.parse(match.group(1)) if match else None
    return Judgement(
        rating=rating or Rating.HOLD,
        rationale=text.strip(),
    )


def _parse_json_block(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def make_trader_prompt(snapshot: TechnicalSnapshot, judgement: Judgement) -> str:
    return (
        f"技术快照(价格结构基准):\n{snapshot.evidence_text()}\n\n"
        f"裁判裁决:Rating={judgement.rating.value}\n{judgement.rationale}\n\n"
        "请输出一张订单票的 JSON(且仅输出 JSON),字段:"
        "direction: long|short;order_type: market|limit;entry: 绝对价格;"
        "stop_loss: 绝对价格;tp: [{\"price\": 绝对价格,\"fraction\": 0~1},...] 最多 3 档;"
        "size: 名义仓位 USDT;leverage: 杠杆倍数;\n"
        "硬性要求:全部价格必须是绝对价格数字,禁止写百分比、区间或文字;"
        "止损方向必须与持仓方向一致;多空多头取 TP1<TP2<TP3 递增,空头反之;"
        "若判断不应入场,输出 {\"direction\": null}。"
    )


def run_trader(
    llm: LLMProvider,
    snapshot: TechnicalSnapshot,
    judgement: Judgement,
) -> OrderTicket | None:
    if judgement.rating in (Rating.HOLD,):
        return None
    text = llm.complete(
        "trader",
        "你是交易员:把裁决翻译成可执行订单票,不做方向分析。",
        make_trader_prompt(snapshot, judgement),
    )
    payload = _parse_json_block(text) or {}
    if not payload or payload.get("direction") in (None, "null"):
        return None
    payload.setdefault("symbol", snapshot.symbol)
    payload.setdefault("order_type", "market")
    payload.setdefault("size", 100.0)
    payload.setdefault("leverage", 5.0)
    payload["source"] = "trader"
    payload.setdefault("reason", f"裁判 {judgement.rating.value} 落地")
    try:
        return OrderTicket.from_dict(payload)
    except (KeyError, ValueError, TypeError):
        return None


def run_risk_debate(
    llm: LLMProvider,
    ticket: OrderTicket,
    snapshot: TechnicalSnapshot,
    judgement: Judgement,
    *,
    rounds: int = 1,
) -> Debate:
    """三方风控辩论:激进/保守/均衡就同一张订单票互评。"""
    base = (
        f"订单票:{json.dumps(ticket.to_dict(), ensure_ascii=False)}\n"
        f"价格结构:现价 {snapshot.close} ATR {snapshot.atr14} "
        f"区间高低 {snapshot.swing_high}/{snapshot.swing_low}\n"
        f"裁判:Rating={judgement.rating.value}"
    )
    turns: list[DebateTurn] = []
    for _ in range(max(1, rounds)):
        agg = llm.complete(
            "aggressive",
            "你是激进风控官:为这张订单票的收益潜力辩护,指出保守评估会错过的机会。",
            f"{base}\n{_NO_LISTING}",
        )
        turns.append(DebateTurn(speaker="aggressive", text=agg.strip()))
        con = llm.complete(
            "conservative",
            "你是保守风控官:专门攻击这张订单票的风险点——杠杆、止损距离、流动性、行情配合度。",
            f"{base}\n激进派观点:{agg}\n{_NO_LISTING}",
        )
        turns.append(DebateTurn(speaker="conservative", text=con.strip()))
        neu = llm.complete(
            "neutral",
            "你是均衡风控官:校准双方,给出可执行的风控意见(如缩小仓位/改用限价/放弃)。",
            f"{base}\n激进派:{agg}\n保守派:{con}\n{_NO_LISTING}",
        )
        turns.append(DebateTurn(speaker="neutral", text=neu.strip()))
    return Debate(turns=turns, rounds=rounds)


def run_pm(
    llm: LLMProvider,
    judgement: Judgement,
    ticket: OrderTicket,
    risk_debate: Debate,
    past_context: str,
) -> PortfolioDecision:
    text = llm.complete(
        "pm",
        "你是组合经理(PM):综合裁判、订单票、风控辩论与本标的历史教训,做终审。"
        "可以维持、下调(如 Buy→Hold)或中止整笔交易。",
        f"裁判:\nRating={judgement.rating.value}\n{judgement.rationale}\n\n"
        f"订单票:{json.dumps(ticket.to_dict(), ensure_ascii=False)}\n\n"
        f"风控辩论:\n{risk_debate.render()}\n\n"
        f"历史教训:\n{past_context}\n\n"
        "输出格式:第一行『Rating: <五档之一>』,随后给出终审摘要与主要风险。",
    )
    match = RATING_PATTERN.search(text)
    rating = Rating.parse(match.group(1)) if match else judgement.rating
    notes = [
        line.lstrip("-• ").strip()
        for line in text.splitlines()
        if line.strip().startswith(("-", "•")) and "Rating" not in line
    ][:5]
    return PortfolioDecision(rating=rating or judgement.rating, summary=text.strip(), risk_notes=notes)


def rule_based_ticket(
    snapshot: TechnicalSnapshot,
    judgement: Judgement,
    *,
    stop_atr_mult: float = 1.5,
    tp_multiples: tuple[float, float, float] = (1.5, 2.5, 3.5),
    fractions: tuple[float, float, float] = (0.5, 0.3, 0.2),
    size: float = 100.0,
    leverage: float = 5.0,
) -> OrderTicket | None:
    """交易员规则兜底:LLM 出不了合法 JSON、或 Hold 时的兜底算价。"""
    direction = judgement.rating.to_direction()
    if direction is None:
        return None
    entry = snapshot.close
    sign = 1.0 if direction is Direction.LONG else -1.0
    stop = entry - sign * snapshot.atr14 * stop_atr_mult
    risk = abs(entry - stop)
    tp = [
        TakeProfit(price=round(entry + sign * risk * m, 8), fraction=f)
        for m, f in zip(tp_multiples, fractions)
    ]
    return OrderTicket(
        symbol=snapshot.symbol,
        direction=direction,
        order_type=OrderType.MARKET,
        entry=round(entry, 8),
        stop_loss=round(stop, 8),
        tp=tp,
        size=size,
        leverage=leverage,
        source="trader-rule",
        reason=f"裁判 {judgement.rating.value} 规则兜底算价",
    )
