from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SUPPORTED_MARKETS = {"crypto_futures", "equity_perpetual"}
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是数字。") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{label}必须是有效数字。")
    return number


def _integer(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数。") from exc


@dataclass(frozen=True)
class ProjectConfig:
    project_id: str
    name: str
    symbol: str
    budget: float
    initial_stake: float
    leverage: int
    market: str = "crypto_futures"
    enabled: bool = True
    parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], index: int) -> "ProjectConfig":
        symbol = str(payload.get("symbol") or "").strip().upper()
        market = str(payload.get("market") or "crypto_futures").strip().lower()
        project_id = str(payload.get("project_id") or f"project_{index + 1}").strip()
        name = str(payload.get("name") or symbol or f"项目 {index + 1}").strip()
        budget = _number(payload.get("budget", 1000), f"{name}预算")
        initial_stake = _number(payload.get("initial_stake", 50), f"{name}首仓")
        leverage = _integer(payload.get("leverage", 20), f"{name}杠杆")

        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", project_id):
            raise ValueError(f"{name}的项目ID格式无效。")
        if market not in SUPPORTED_MARKETS:
            raise ValueError(f"{name}暂不支持市场类型 {market}。")
        if market == "crypto_futures" and not re.fullmatch(r"[A-Z0-9]{2,20}USDT", symbol):
            raise ValueError(f"{name}必须选择USDT永续合约。")
        if market == "equity_perpetual" and symbol != "SNDKUSDT":
            raise ValueError(f"{name}当前只支持SNDKUSDT股票永续验证。")
        if budget < 50:
            raise ValueError(f"{name}预算不能低于50 USDT。")
        if initial_stake < 5 or initial_stake > budget:
            raise ValueError(f"{name}首仓必须在5 USDT和项目预算之间。")
        if leverage < 1 or leverage > 125:
            raise ValueError(f"{name}杠杆必须在1到125倍之间。")

        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError(f"{name}策略参数格式无效。")
        return cls(
            project_id=project_id,
            name=name[:40],
            symbol=symbol,
            budget=round(budget, 8),
            initial_stake=round(initial_stake, 8),
            leverage=leverage,
            market=market,
            enabled=bool(payload.get("enabled", True)),
            parameters=dict(parameters),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioConfig:
    portfolio_id: str
    name: str
    strategy_id: str
    initial_capital: float
    run_days: int
    max_concurrent_positions: int
    account_stop_pct: float
    projects: tuple[ProjectConfig, ...]
    strategy_parameters: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        strategy_validator: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> "PortfolioConfig":
        portfolio_id = str(payload.get("portfolio_id") or "default_portfolio").strip()
        name = str(payload.get("name") or "我的投资组合").strip()
        strategy_id = str(payload.get("strategy_id") or "strategy_1").strip()
        initial_capital = _number(payload.get("initial_capital", 5000), "组合本金")
        run_days = _integer(payload.get("run_days", 30), "运行时间")
        account_stop_pct = _number(payload.get("account_stop_pct", 12), "回撤警戒线")
        raw_projects = payload.get("projects") or []

        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", portfolio_id):
            raise ValueError("组合ID格式无效。")
        if not strategy_id:
            raise ValueError("请选择策略。")
        if initial_capital < 100 or initial_capital > 10_000_000:
            raise ValueError("组合本金必须在100到10000000 USDT之间。")
        if run_days < 2 or run_days > 365:
            raise ValueError("运行时间必须在2到365天之间。")
        if account_stop_pct <= 0 or account_stop_pct > 100:
            raise ValueError("回撤警戒线必须在0到100%之间。")
        if not isinstance(raw_projects, list) or not 1 <= len(raw_projects) <= 12:
            raise ValueError("投资组合必须包含1到12个项目。")

        projects = tuple(ProjectConfig.from_payload(item, index) for index, item in enumerate(raw_projects))
        active = tuple(project for project in projects if project.enabled)
        if not active:
            raise ValueError("至少启用一个项目。")
        identifiers = [project.project_id for project in projects]
        symbols = [project.symbol for project in active]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("项目ID不能重复。")
        if len(set(symbols)) != len(symbols):
            raise ValueError("同一组合中不能重复配置同一标的。")
        total_budget = sum(project.budget for project in active)
        if total_budget > initial_capital + 1e-8:
            raise ValueError(f"项目预算合计{total_budget:.2f} USDT，超过组合本金{initial_capital:.2f} USDT。")

        max_positions = _integer(payload.get("max_concurrent_positions", len(active)), "最大并发仓位")
        if max_positions < 1 or max_positions > len(active):
            raise ValueError("最大并发仓位必须在1和启用项目数之间。")
        strategy_parameters = payload.get("strategy_parameters") or {}
        if not isinstance(strategy_parameters, dict):
            raise ValueError("策略参数格式无效。")
        if strategy_validator:
            strategy_parameters = strategy_validator(strategy_id, strategy_parameters)

        return cls(
            portfolio_id=portfolio_id,
            name=name[:60],
            strategy_id=strategy_id,
            initial_capital=round(initial_capital, 8),
            run_days=run_days,
            max_concurrent_positions=max_positions,
            account_stop_pct=round(account_stop_pct, 4),
            projects=projects,
            strategy_parameters=dict(strategy_parameters),
        )

    @property
    def active_projects(self) -> tuple[ProjectConfig, ...]:
        return tuple(project for project in self.projects if project.enabled)

    @property
    def allocated_capital(self) -> float:
        return sum(project.budget for project in self.active_projects)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["projects"] = [project.to_dict() for project in self.projects]
        payload["allocated_capital"] = self.allocated_capital
        payload["cash_reserve"] = self.initial_capital - self.allocated_capital
        return payload


def default_portfolio(strategy_id: str = "strategy_1") -> PortfolioConfig:
    projects = [
        {
            "project_id": f"project_{index + 1}",
            "name": symbol.removesuffix("USDT"),
            "symbol": symbol,
            "budget": 1000,
            "initial_stake": 50,
            "leverage": 20,
        }
        for index, symbol in enumerate(DEFAULT_SYMBOLS)
    ]
    return PortfolioConfig.from_payload(
        {
            "portfolio_id": "core_5",
            "name": "核心五项目",
            "strategy_id": strategy_id,
            "initial_capital": 5000,
            "run_days": 30,
            "max_concurrent_positions": 5,
            "account_stop_pct": 12,
            "projects": projects,
        }
    )


class PortfolioStore:
    """Small local JSON store. API credentials and run databases never enter it."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = payload.get("portfolios", []) if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def save(self, portfolio: PortfolioConfig) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        records = self.list()
        record = portfolio.to_dict()
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        records = [item for item in records if item.get("portfolio_id") != portfolio.portfolio_id]
        records.append(record)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "portfolios": records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return record

    def delete(self, portfolio_id: str) -> bool:
        records = self.list()
        retained = [item for item in records if item.get("portfolio_id") != portfolio_id]
        if len(retained) == len(records):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"version": 1, "portfolios": retained}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return True
