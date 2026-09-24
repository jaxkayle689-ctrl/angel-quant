from __future__ import annotations

"""硬闸门:所有通道的共同出口,纯规则,不可关闭。

设计文档第 9 章:无论 LLM 出什么漏洞、操作员什么疏忽,
系统都不会飞出预设风险边界。启用=构造一个 HardGate 实例;
不存在 bypass 标志——绕过它的唯一方式是不调用本项目代码下单。
"""

from dataclasses import dataclass

from .contract import Direction, GateResult, GateRuleResult, OrderTicket


@dataclass(frozen=True)
class GateConfig:
    max_leverage: float = 20.0
    max_size_usdt: float = 5000.0
    min_risk_reward: float = 1.5      # TP1 / 止损距离
    max_stop_atr: float = 5.0         # 止损距入场 ≤ 5*ATR(防"没有止损概念"的单据)
    min_stop_atr: float = 0.5         # 止损距入场 ≥ 0.5*ATR(防无意义贴脸止损)
    allow_market: bool = True
    allow_limit: bool = True

    def assert_locked(self) -> None:
        """硬闸门配置不可运行时弱化:任何副本修改必须新建实例。"""
        if self.max_leverage <= 0 or self.max_size_usdt <= 0:
            raise ValueError("闸门配置非法:上限必须为正。")


class HardGate:
    """订单票进入执行端前的强制关卡。"""

    def __init__(self, config: GateConfig | None = None) -> None:
        self.config = config or GateConfig()
        self.config.assert_locked()

    def check(self, ticket: OrderTicket, *, atr: float, mark_price: float) -> GateResult:
        results: list[GateRuleResult] = []
        cfg = self.config
        atr = max(float(atr), 1e-12)

        def add(rule: str, passed: bool, detail: str) -> None:
            results.append(GateRuleResult(rule=rule, passed=passed, detail=detail))

        add("未过期", not ticket.is_expired,
            f"valid_until={ticket.valid_until or '无'}")
        add("价格为正", ticket.entry > 0 and ticket.stop_loss > 0 and all(t.price > 0 for t in ticket.tp),
            f"entry={ticket.entry} sl={ticket.stop_loss}")
        add("档位数量", 1 <= len(ticket.tp) <= 3, f"tp 档数={len(ticket.tp)}")

        stop_distance = ticket.entry - ticket.stop_loss
        direction_consistent = (
            (ticket.direction == Direction.LONG and stop_distance > 0)
            or (ticket.direction == Direction.SHORT and stop_distance < 0)
        )
        add("止损与方向一致", direction_consistent,
            f"direction={ticket.direction.value} stop_distance={stop_distance:.6g}")

        if ticket.tp:
            prices = [t.price for t in ticket.tp]
            ordered = (
                all(prices[i] < prices[i + 1] for i in range(len(prices) - 1))
                if ticket.direction == Direction.LONG
                else all(prices[i] > prices[i + 1] for i in range(len(prices) - 1))
            )
            add("止盈档有序", ordered, f"tp={prices}")
            fractions = [t.fraction for t in ticket.tp]
            add("止盈比例合法", all(0.0 < f <= 1.0 for f in fractions) and sum(fractions) <= 1.0 + 1e-9,
                f"fractions={fractions}")

        stop_atr = abs(stop_distance) / atr
        add("止损距入场≥0.5ATR", stop_atr >= cfg.min_stop_atr - 1e-9, f"{stop_atr:.2f} ATR（下限 {cfg.min_stop_atr}）")
        add("止损距入场≤5ATR", stop_atr <= cfg.max_stop_atr + 1e-9, f"{stop_atr:.2f} ATR（上限 {cfg.max_stop_atr}）")

        rr = ticket.risk_reward()
        add("盈亏比达标", rr >= cfg.min_risk_reward - 1e-9, f"RR={rr:.2f}(下限 {cfg.min_risk_reward})")

        add("杠杆上限", 0 < ticket.leverage <= cfg.max_leverage, f"leverage={ticket.leverage}(上限 {cfg.max_leverage})")
        add("仓位上限", 0 < ticket.size <= cfg.max_size_usdt, f"size={ticket.size}(上限 {cfg.max_size_usdt})")

        add("订单类型放行", (ticket.order_type.value == "market" and cfg.allow_market)
            or (ticket.order_type.value == "limit" and cfg.allow_limit),
            f"order_type={ticket.order_type.value}")

        if mark_price > 0:
            drift = abs(mark_price - ticket.entry) / max(ticket.entry, 1e-12)
            degraded = ["入场价偏离现价>5%,建议改限价或重定价"] if drift > 0.05 else []
        else:
            degraded = []

        passed = all(r.passed for r in results)
        return GateResult(passed=passed, results=results, degraded=degraded)
