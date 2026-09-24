from __future__ import annotations

"""LLM provider 抽象与规则共识兜底。

任何通道都不直接依赖具体模型实现:辩论链、交易员、风控都只认
LLMProvider 协议。无模型 Key / 模型不可用时自动切规则共识兜底,
行为与现有 README 的"模型不可用回退本地规则共识"一致。
"""

from typing import Any, Protocol

from .registry import StrategyReport
from .snapshot import TechnicalSnapshot


class LLMProvider(Protocol):
    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        """role 仅用于日志与成本归因(如 bull / bear / judge / trader / pm)。"""
        ...


class RuleFallbackLLM:
    """规则共识兜底:无模型时,用确定性规则扮演辩论链。

    不真正"辩论":bull/bear 各自从证据里抽取利多/利空句,
    裁判按策略共识 + 趋势 + RSI 给五档评级。全程 0 次外部调用。
    """

    def __init__(self, snapshot: TechnicalSnapshot, report: StrategyReport | None = None) -> None:
        self.snapshot = snapshot
        self.report = report

    def _bullish_points(self) -> list[str]:
        s = self.snapshot
        points: list[str] = []
        if s.ema7 > s.ema25 > s.ema100:
            points.append("均线多头排列 EMA7>EMA25>EMA100")
        if s.trend == "up":
            points.append(f"趋势向上且已持续 {s.trend_age_bars} 根")
        if s.rsi14 > 55:
            points.append(f"RSI {s.rsi14:g} 处于强势区")
        if s.volume_ratio > 1.2:
            points.append(f"量比 {s.volume_ratio:g} 放量配合")
        if s.close > s.vwap:
            points.append("价格位于 VWAP 之上")
        return points or ["暂无明显多头证据,维持观望立场"]

    def _bearish_points(self) -> list[str]:
        s = self.snapshot
        points: list[str] = []
        if s.ema7 < s.ema25 < s.ema100:
            points.append("均线空头排列 EMA7<EMA25<EMA100")
        if s.trend == "down":
            points.append(f"趋势向下且已持续 {s.trend_age_bars} 根")
        if s.rsi14 < 45:
            points.append(f"RSI {s.rsi14:g} 处于弱势区")
        if s.close < s.vwap:
            points.append("价格位于 VWAP 之下")
        if s.bb_percent_b > 0.9:
            points.append(f"%B {s.bb_percent_b:g} 接近布林上轨,有回落风险")
        if s.bb_percent_b < 0.1:
            points.append(f"%B {s.bb_percent_b:g} 接近布林下轨,弱势延续")
        return points or ["暂无明显空头证据,维持观望立场"]

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        role = role.lower()
        if role.startswith("bull"):
            points = self._bullish_points()
            return "多方观点:" + ";".join(points) + "。基于上述证据主张看多。"
        if role.startswith("bear"):
            points = self._bearish_points()
            return "空方观点:" + ";".join(points) + "。基于上述风险主张看空。"
        if role.startswith("judge"):
            return self._judge()
        if role.startswith("aggressive"):
            return "激进派:若方向有趋势与量价共振,应接受正常波动换取 1.5R+ 预期收益空间。"
        if role.startswith("conservative"):
            return "保守派:严格止损与仓位纪律优先,任何接近硬闸门红线的提案都应降级。"
        if role.startswith("neutral"):
            return "均衡派:接受趋势证据,但要求止损如实落地、仓位不超过上限。"
        if role.startswith("pm"):
            return self._judge(pm=True)
        return "规则共识无该角色输出。"

    def _judge(self, pm: bool = False) -> str:
        s = self.snapshot
        direction = 0
        confidence = 0.0
        if self.report is not None:
            direction = self.report.consensus_direction()
            confidence = self.report.consensus_confidence()
        trend_push = 0.5 if s.trend == "up" else (-0.5 if s.trend == "down" else 0.0)
        score = direction * confidence + trend_push
        if score >= 0.8:
            rating = "Buy"
        elif score >= 0.4:
            rating = "Overweight"
        elif score <= -0.8:
            rating = "Sell"
        elif score <= -0.4:
            rating = "Underweight"
        else:
            rating = "Hold"
        prefix = "PM 终审" if pm else "裁判"
        return (
            f"Rating: {rating}\n"
            f"{prefix}:规则共识分 {score:+.2f}(策略共识 {direction}×{confidence:.0%} "
            f"+ 趋势项 {trend_push:+.1f}),给出 {rating}。"
        )


class ModelGatewayLLM:
    """接入现有 agent_engine.ModelGateway 的适配器(DeepSeek / OpenAI)。

    构造:ModelGatewayLLM(gateway, provider="deepseek", api_key=..., model="deepseek-chat")
    密钥只存在于该实例内存,不落盘(沿用现有项目约定)。
    """

    def __init__(self, gateway: Any, provider: str, api_key: str, model: str) -> None:
        self.gateway = gateway
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> str:
        prompt = system_prompt + "\n\n" + user_prompt if system_prompt else user_prompt
        result = self.gateway.complete(self.provider, self.api_key, self.model, prompt)
        if isinstance(result, dict):
            content = result.get("content") or result.get("text") or ""
            return str(content)
        return str(result)
