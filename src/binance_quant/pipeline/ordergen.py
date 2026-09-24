from __future__ import annotations

"""规则订单生成器(快速通道专用,0 次 LLM)。

输入:技术快照 + 策略信号报告;输出:订单票。
定单逻辑保守:方向来自策略共识,入场=现价,止损=ATR 倍数,
TP1/2/3 按 1.5R/2.5R/3.5R 分批 50%/30%/20%。
"""

from dataclasses import dataclass

from .contract import Direction, OrderTicket, OrderType, TakeProfit
from .hardgate import GateResult, HardGate
from .registry import StrategyReport
from .snapshot import TechnicalSnapshot


@dataclass(frozen=True)
class OrderPlanConfig:
    stop_atr_mult: float = 1.5          # 止损 = 1.5 * ATR
    tp_r_multiples: tuple[float, float, float] = (1.5, 2.5, 3.5)
    tp_fractions: tuple[float, float, float] = (0.5, 0.3, 0.2)
    default_size_usdt: float = 100.0
    default_leverage: float = 5.0
    order_type: OrderType = OrderType.MARKET
    valid_seconds: float = 900.0        # 订单票默认 15 分钟过期


def build_order_ticket(
    snapshot: TechnicalSnapshot,
    report: StrategyReport,
    config: OrderPlanConfig | None = None,
) -> OrderTicket | None:
    """依据快照与策略共识生成订单票;无共识方向时返回 None(观望)。"""
    cfg = config or OrderPlanConfig()
    direction_int = report.consensus_direction()
    if direction_int == 0:
        return None

    direction = Direction.LONG if direction_int > 0 else Direction.SHORT
    entry = snapshot.close
    stop_distance = snapshot.atr14 * cfg.stop_atr_mult
    stop = entry - stop_distance if direction is Direction.LONG else entry + stop_distance

    risk = abs(entry - stop)
    sign = 1.0 if direction is Direction.LONG else -1.0
    tp = [
        TakeProfit(price=round(entry + sign * risk * mult, 8), fraction=frac)
        for mult, frac in zip(cfg.tp_r_multiples, cfg.tp_fractions)
    ]
    reason = (
        f"共识方向 {direction.value}(置信度 {report.consensus_confidence():.0%});"
        f"止损 {cfg.stop_atr_mult}*ATR={stop_distance:.6g};"
        f"信号 {len(report.signals)} 个,冲突 {len(report.conflicts)} 条"
    )
    ticket = OrderTicket(
        symbol=snapshot.symbol,
        direction=direction,
        order_type=cfg.order_type,
        entry=round(entry, 8),
        stop_loss=round(stop, 8),
        tp=tp,
        size=cfg.default_size_usdt,
        leverage=cfg.default_leverage,
        source="fast",
        reason=reason,
    )
    ticket.valid_until = ticket.created_at + cfg.valid_seconds
    return ticket


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    detail: str


class PaperExecutor:
    """快速通道的执行端(模拟)。真实 Gateway 接入后,接口形态保持一致。"""

    def __init__(self) -> None:
        self.filled: list[OrderTicket] = []

    def submit(self, ticket: OrderTicket) -> ExecutionResult:
        self.filled.append(ticket)
        return ExecutionResult(accepted=True, detail=f"paper 接收 {ticket.ticket_id}")


def run_fast_cycle(
    snapshot: TechnicalSnapshot,
    report: StrategyReport,
    *,
    gate: HardGate,
    executor: PaperExecutor,
    plan_config: OrderPlanConfig | None = None,
) -> dict:
    """一轮快速通道:快照+信号 → 订单票 → 硬闸门 → (模拟)执行。"""
    ticket = build_order_ticket(snapshot, report, plan_config)
    if ticket is None:
        return {"status": "flat", "ticket": None, "gate": None, "execution": None,
                "reason": "策略共识无方向,观望"}
    gate_result: GateResult = gate.check(ticket, atr=snapshot.atr14, mark_price=snapshot.close)
    if not gate_result.passed:
        return {"status": "rejected", "ticket": ticket.to_dict(), "gate": gate_result.to_dict(),
                "execution": None, "reason": gate_result.reasons()}
    execution = executor.submit(ticket)
    return {"status": "accepted", "ticket": ticket.to_dict(), "gate": gate_result.to_dict(),
            "execution": {"accepted": execution.accepted, "detail": execution.detail},
            "reason": ticket.reason}
