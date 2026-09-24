from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Iterable

from .strategy_api import Strategy
from .strategy_plugins.community import CommunityStrategy, SPECS
from .strategy_plugins import EMA7TrendPullbackStrategy, SNDKAfterCloseStrategy, SMACrossoverStrategy


APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Binance Quant"
USER_STRATEGY_DIR = APP_SUPPORT_DIR / "strategies"


def strategy_directories(extra_directories: Iterable[str | Path] | None = None) -> list[Path]:
    candidates = [Path.cwd() / "strategies", USER_STRATEGY_DIR]
    configured = os.getenv("BINANCE_QUANT_STRATEGY_DIR", "").strip()
    if configured:
        candidates.insert(0, Path(configured).expanduser())
    if extra_directories:
        candidates.extend(Path(item).expanduser() for item in extra_directories)

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _load_module(path: Path) -> ModuleType:
    module_name = f"binance_quant_user_strategy_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strategy_from_module(module: ModuleType, path: Path) -> Strategy:
    candidate = getattr(module, "STRATEGY", None)
    if isinstance(candidate, type) and issubclass(candidate, Strategy):
        candidate = candidate()
    if not isinstance(candidate, Strategy):
        raise TypeError(f"{path.name} must export STRATEGY as a Strategy instance or subclass.")
    if not candidate.strategy_id or not candidate.name:
        raise ValueError(f"{path.name} has incomplete strategy metadata.")
    if not candidate.market_types:
        raise ValueError(f"{path.name} must declare at least one market type.")
    adapter = candidate.backtest_adapter
    if not isinstance(adapter, dict) or not adapter.get("engine"):
        raise ValueError(f"{path.name} has an invalid backtest adapter.")
    if adapter.get("engine") == "freqtrade" and not adapter.get("strategy_class"):
        raise ValueError(f"{path.name} must declare a Freqtrade strategy_class.")
    return candidate


def discover_strategies(
    extra_directories: Iterable[str | Path] | None = None,
) -> tuple[dict[str, Strategy], list[str]]:
    strategies: dict[str, Strategy] = {
        "ema7_trend_pullback": EMA7TrendPullbackStrategy(),
        "sndk_after_close": SNDKAfterCloseStrategy(),
        "sma_crossover": SMACrossoverStrategy(),
    }
    errors: list[str] = []
    strategies.update({spec[0]: CommunityStrategy(spec) for spec in SPECS})
    for directory in strategy_directories(extra_directories):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                strategy = _strategy_from_module(_load_module(path), path)
                strategies[strategy.strategy_id] = strategy
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
    return strategies, errors


def get_strategy(strategy_id: str = "sma_crossover") -> Strategy:
    strategies, errors = discover_strategies()
    try:
        return strategies[strategy_id]
    except KeyError as exc:
        available = ", ".join(strategies)
        detail = f" Plugin errors: {'; '.join(errors)}" if errors else ""
        raise ValueError(f"Unknown strategy '{strategy_id}'. Available: {available}.{detail}") from exc
