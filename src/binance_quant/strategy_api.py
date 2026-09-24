from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategyParameter:
    key: str
    label: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["choices"] = list(self.choices)
        return payload


@dataclass(frozen=True)
class ChartSeries:
    key: str
    label: str
    color: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyContext:
    """Closed market frames and execution estimates supplied to a strategy."""

    frames: dict[str, pd.DataFrame]
    execution_interval: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def frame(self) -> pd.DataFrame:
        try:
            return self.frames[self.execution_interval]
        except KeyError as exc:
            raise ValueError(f"Missing {self.execution_interval} strategy frame.") from exc


class Strategy(ABC):
    """Contract shared by the CLI, backtester, and desktop application."""

    strategy_id: str
    name: str
    description: str
    parameters: tuple[StrategyParameter, ...] = ()
    chart_series: tuple[ChartSeries, ...] = ()
    primary_interval: str | None = None
    required_intervals: tuple[str, ...] = ()
    history_limit: int = 240
    automation_defaults: dict[str, Any] = {}
    version: str = "1.0.0"
    market_types: tuple[str, ...] = ("crypto_futures",)
    capabilities: tuple[str, ...] = ("long", "short")
    backtest_adapter: dict[str, Any] = {"engine": "native"}

    @abstractmethod
    def generate(self, frame: pd.DataFrame, parameters: dict[str, Any]) -> pd.DataFrame:
        """Return a frame containing a numeric signal column in {-1, 0, 1}."""

    def execution_interval(self, selected_interval: str) -> str:
        return self.primary_interval or selected_interval

    def market_intervals(self, selected_interval: str) -> tuple[str, ...]:
        execution_interval = self.execution_interval(selected_interval)
        return tuple(dict.fromkeys((execution_interval, *self.required_intervals)))

    def generate_with_context(
        self,
        context: StrategyContext,
        parameters: dict[str, Any],
    ) -> pd.DataFrame:
        return self.generate(context.frame, parameters)

    def execution_policy(self, parameters: dict[str, Any]) -> dict[str, Any]:
        self.normalized_parameters(parameters)
        return {}

    def normalized_parameters(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        supplied = values or {}
        normalized: dict[str, Any] = {}
        for parameter in self.parameters:
            value = supplied.get(parameter.key, parameter.default)
            if parameter.kind == "integer":
                value = int(value)
            elif parameter.kind == "number":
                value = float(value)
            elif parameter.kind == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "on"}
            elif parameter.kind == "choice":
                value = str(value)
                if value not in parameter.choices:
                    raise ValueError(f"{parameter.label} must be one of {', '.join(parameter.choices)}.")

            if parameter.minimum is not None and value < parameter.minimum:
                raise ValueError(f"{parameter.label} must be at least {parameter.minimum}.")
            if parameter.maximum is not None and value > parameter.maximum:
                raise ValueError(f"{parameter.label} must be at most {parameter.maximum}.")
            normalized[parameter.key] = value
        return normalized

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "chart_series": [series.to_dict() for series in self.chart_series],
            "primary_interval": self.primary_interval,
            "required_intervals": list(self.required_intervals),
            "automation_defaults": dict(self.automation_defaults),
            "version": self.version,
            "market_types": list(self.market_types),
            "capabilities": list(self.capabilities),
            "backtest_adapter": dict(self.backtest_adapter),
        }


def validate_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if "signal" not in frame.columns:
        raise ValueError("Strategy output must contain a signal column.")
    result = frame.copy()
    result["signal"] = pd.to_numeric(result["signal"], errors="coerce").fillna(0).clip(-1, 1).astype(int)
    return result
