from __future__ import annotations

import math
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

from .agent_engine import AgentService
from .daily_strategy import DailyStrategyService
from .workspace_settings import WorkspaceSettings
from .automation import DEMO_FUTURES_URL, DemoAutomation
from .client import BinanceAPIError, UMFuturesClient
from .data import fetch_klines
from .freqtrade_engine import FREQTRADE_DIR, FreqtradeEngine
from .knowledge_base import KnowledgeBase
from .macro_calendar import MacroCalendarService
from .portfolio import PortfolioConfig, PortfolioStore, default_portfolio
from .sndk_engine import SNDKHybridBacktestEngine
from .strategy_api import StrategyContext, validate_signal_frame
from .strategy_registry import APP_SUPPORT_DIR, USER_STRATEGY_DIR, discover_strategies, get_strategy


FUTURES_URLS = {
    "demo": "https://demo-fapi.binance.com",
    "live": "https://fapi.binance.com",
}
FUTURES_STREAM_URLS = {
    "demo": "wss://fstream.binancefuture.com",
    "live": "wss://fstream.binance.com",
}
POPULAR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
DAY_MS = 24 * 60 * 60 * 1000
MAX_TRADE_WINDOW_MS = 7 * DAY_MS - 1


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else Decimal(default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _quote_asset(symbol: str) -> str:
    return next((asset for asset in ("USDT", "USDC", "FDUSD") if symbol.endswith(asset)), "USDT")


def aggregate_closed_trades(trades: list[dict[str, Any]], display_start_ms: int) -> list[dict[str, Any]]:
    positions: dict[tuple[str, str], dict[str, Any]] = {}
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_closed_fill(
        trade: dict[str, Any],
        direction: str,
        quantity: Decimal,
        entry_price: Decimal,
        exit_price: Decimal,
        realized_pnl: Decimal,
        entry_fee: Decimal,
        exit_fee: Decimal,
        estimated_entry: bool,
    ) -> None:
        close_time = int(_decimal(trade.get("time")))
        if close_time < display_start_ms or quantity <= 0 or entry_price <= 0 or exit_price <= 0:
            return
        order_id = str(trade.get("orderId") or trade.get("id") or close_time)
        symbol = str(trade.get("symbol", ""))
        key = (symbol, direction, order_id)
        group = groups.setdefault(
            key,
            {
                "symbol": symbol,
                "direction": direction,
                "order_id": order_id,
                "close_time": close_time,
                "quantity": Decimal("0"),
                "entry_value": Decimal("0"),
                "exit_value": Decimal("0"),
                "realized_pnl": Decimal("0"),
                "entry_fee": Decimal("0"),
                "exit_fee": Decimal("0"),
                "entry_estimated": False,
            },
        )
        group["close_time"] = max(group["close_time"], close_time)
        group["quantity"] += quantity
        group["entry_value"] += entry_price * quantity
        group["exit_value"] += exit_price * quantity
        group["realized_pnl"] += realized_pnl
        group["entry_fee"] += entry_fee
        group["exit_fee"] += exit_fee
        group["entry_estimated"] = group["entry_estimated"] or estimated_entry

    ordered = sorted(trades, key=lambda item: (int(_decimal(item.get("time"))), int(_decimal(item.get("id")))))
    for trade in ordered:
        symbol = str(trade.get("symbol", "")).upper()
        quantity = abs(_decimal(trade.get("qty")))
        price = _decimal(trade.get("price"))
        if not symbol or quantity <= 0 or price <= 0:
            continue
        side = str(trade.get("side", "")).upper()
        if side not in {"BUY", "SELL"}:
            continue
        position_side = str(trade.get("positionSide") or "BOTH").upper()
        delta = quantity if side == "BUY" else -quantity
        key = (symbol, position_side)
        position = positions.get(key)
        quote_fee = (
            abs(_decimal(trade.get("commission")))
            if str(trade.get("commissionAsset", "")).upper() == _quote_asset(symbol)
            else Decimal("0")
        )
        realized = _decimal(trade.get("realizedPnl"))

        if position is None or _decimal(position.get("quantity")) == 0:
            if realized != 0:
                direction = "LONG" if position_side == "LONG" or (position_side == "BOTH" and side == "SELL") else "SHORT"
                entry = price - realized / quantity if direction == "LONG" else price + realized / quantity
                fee_rate = quote_fee / (price * quantity) if quote_fee > 0 else Decimal("0")
                add_closed_fill(
                    trade,
                    direction,
                    quantity,
                    entry,
                    price,
                    realized,
                    abs(entry * quantity * fee_rate),
                    quote_fee,
                    True,
                )
                continue
            positions[key] = {
                "quantity": delta,
                "entry_price": price,
                "open_fee": quote_fee,
            }
            continue

        current_quantity = _decimal(position["quantity"])
        if current_quantity * delta > 0:
            total_quantity = abs(current_quantity) + quantity
            position["entry_price"] = (
                _decimal(position["entry_price"]) * abs(current_quantity) + price * quantity
            ) / total_quantity
            position["quantity"] = current_quantity + delta
            position["open_fee"] = _decimal(position["open_fee"]) + quote_fee
            continue

        close_quantity = min(abs(current_quantity), quantity)
        entry_price = _decimal(position["entry_price"])
        entry_fee = _decimal(position["open_fee"]) * close_quantity / abs(current_quantity)
        exit_fee = quote_fee * close_quantity / quantity
        direction = "LONG" if current_quantity > 0 else "SHORT"
        add_closed_fill(
            trade,
            direction,
            close_quantity,
            entry_price,
            price,
            realized,
            entry_fee,
            exit_fee,
            False,
        )

        remaining = current_quantity + delta
        if remaining == 0:
            positions.pop(key, None)
        elif remaining * current_quantity > 0:
            position["quantity"] = remaining
            position["open_fee"] = max(Decimal("0"), _decimal(position["open_fee"]) - entry_fee)
        else:
            positions[key] = {
                "quantity": remaining,
                "entry_price": price,
                "open_fee": max(Decimal("0"), quote_fee - exit_fee),
            }

    records: list[dict[str, Any]] = []
    for group in groups.values():
        quantity = _decimal(group["quantity"])
        if quantity <= 0:
            continue
        entry_price = _decimal(group["entry_value"]) / quantity
        exit_price = _decimal(group["exit_value"]) / quantity
        realized_pnl = _decimal(group["realized_pnl"])
        commission = _decimal(group["entry_fee"]) + _decimal(group["exit_fee"])
        direction_sign = Decimal("1") if group["direction"] == "LONG" else Decimal("-1")
        price_return = (exit_price - entry_price) / entry_price * direction_sign * Decimal("100")
        records.append(
            {
                "symbol": group["symbol"],
                "direction": group["direction"],
                "order_id": group["order_id"],
                "close_time": group["close_time"],
                "quantity": float(quantity),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "realized_pnl": float(realized_pnl),
                "commission": float(commission),
                "net_pnl": float(realized_pnl - commission),
                "price_return_pct": float(price_return),
                "entry_estimated": bool(group["entry_estimated"]),
            }
        )
    return sorted(records, key=lambda item: item["close_time"], reverse=True)


def _response(func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"ok": True, "data": func()}
    except BinanceAPIError as exc:
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        message = payload.get("msg") or str(exc.payload)
        return {"ok": False, "error": f"Binance API: {message}", "code": payload.get("code")}
    except requests.RequestException:
        return {"ok": False, "error": "Binance 网络连接暂时中断，已自动重试；请稍后刷新。"}
    except (ValueError, TypeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"Unexpected error: {exc}"}


def _signal_state(current: int, previous: int) -> dict[str, Any]:
    labels = {1: "做多", 0: "空仓", -1: "做空"}
    if current != previous:
        actions = {1: "OPEN_LONG", 0: "CLOSE", -1: "OPEN_SHORT"}
        action = actions[current]
    else:
        action = "HOLD"
    return {"value": current, "label": labels[current], "action": action}


class DashboardAPI:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._client: UMFuturesClient | None = None
        self._environment = "demo"
        self._masked_key = ""
        self._listen_key = ""
        self._automation: DemoAutomation | None = None
        self._freqtrade = FreqtradeEngine()
        self._sndk_engine = SNDKHybridBacktestEngine()
        self._daily_strategy = DailyStrategyService()
        self._macro_calendar = MacroCalendarService()
        self._workspace_settings = WorkspaceSettings(APP_SUPPORT_DIR)
        for asset in self._workspace_settings.read().get('assets', []):
            self._daily_strategy.add_asset(asset)
        self._portfolio_store = PortfolioStore(APP_SUPPORT_DIR / "portfolios.json")
        self._knowledge = KnowledgeBase(APP_SUPPORT_DIR)
        self._agent = AgentService(
            APP_SUPPORT_DIR,
            lambda: UMFuturesClient(base_url=FUTURES_URLS["live"]),
        )
        self._ensure_strategy_workspace()

    @staticmethod
    def _validate_strategy_parameters(strategy_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        strategy = get_strategy(strategy_id)
        return strategy.normalized_parameters(parameters)

    def _portfolio_from_payload(self, payload: dict[str, Any]) -> PortfolioConfig:
        portfolio = PortfolioConfig.from_payload(
            payload,
            strategy_validator=self._validate_strategy_parameters,
        )
        strategy = get_strategy(portfolio.strategy_id)
        adapter = strategy.backtest_adapter
        if not adapter.get("supports_portfolio"):
            raise ValueError(f"{strategy.name}尚未提供组合回测适配器。")
        unsupported = [
            project.market
            for project in portfolio.active_projects
            if project.market not in strategy.market_types
        ]
        if unsupported:
            raise ValueError(f"{strategy.name}不支持所选市场。")
        fixed_symbols = tuple(str(item).upper() for item in adapter.get("fixed_symbols", []))
        selected_symbols = tuple(project.symbol for project in portfolio.active_projects)
        if fixed_symbols and selected_symbols != fixed_symbols:
            raise ValueError(f"{strategy.name}只允许配置：{', '.join(fixed_symbols)}。")
        return portfolio

    def _public_client(self, environment: str | None = None) -> UMFuturesClient:
        selected = environment or self._environment
        if selected not in FUTURES_URLS:
            raise ValueError("环境参数无效。")
        return UMFuturesClient(base_url=FUTURES_URLS[selected])

    def _connected_client(self) -> UMFuturesClient:
        with self._lock:
            if self._client is None:
                raise ValueError("请先连接 Binance 合约账户。")
            return self._client

    def bootstrap(self, environment: str = "demo") -> dict[str, Any]:
        def load() -> dict[str, Any]:
            strategies, strategy_errors = discover_strategies()
            client = self._public_client(environment)
            symbols = POPULAR_SYMBOLS
            exchange_error = ""
            try:
                payload = client.exchange_info()
                candidates = [
                    item["symbol"]
                    for item in payload.get("symbols", [])
                    if item.get("status") == "TRADING"
                    and item.get("contractType") == "PERPETUAL"
                    and item.get("quoteAsset") == "USDT"
                ]
                priority = {symbol: index for index, symbol in enumerate(POPULAR_SYMBOLS)}
                symbols = sorted(set(candidates), key=lambda item: (priority.get(item, 999), item))
            except Exception as exc:
                exchange_error = str(exc)

            return {
                "environment": environment,
                "symbols": symbols,
                "intervals": INTERVALS,
                "strategies": self._library_metadata(),
                "workspace_settings": self._workspace_settings.read(),
                "strategy_errors": strategy_errors,
                "exchange_error": exchange_error,
                "connected": self._client is not None,
                "masked_key": self._masked_key,
                "strategy_directory": str(USER_STRATEGY_DIR),
                "portfolios": self._portfolio_store.list(),
                "portfolio_template": default_portfolio().to_dict(),
                "daily_strategy_assets": self._daily_strategy.catalog(),
                "markets": [
                    {"id": "crypto_futures", "name": "加密货币永续", "status": "ready"},
                    {"id": "equity_perpetual", "name": "Binance股票永续", "status": "validation", "symbols": ["SNDKUSDT"]},
                    {"id": "us_equities", "name": "美股 / ETF", "status": "signal_only", "symbols": ["SNDK", "MRVL", "SOXL", "NBIS"]},
                    {"id": "hk_equities", "name": "港股", "status": "signal_only", "symbols": ["0100.HK"]},
                ],
                "live_automation_locked": True,
                "agent": self._agent.bootstrap(),
            }

        return _response(load)

    def connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        def connect_account() -> dict[str, Any]:
            with self._lock:
                if self._automation:
                    status = self._automation.status()
                    if status["running"] or status["starting"]:
                        raise ValueError("请先紧急停止 Demo 自动执行。")
            api_key = str(payload.get("api_key", "")).strip()
            api_secret = str(payload.get("api_secret", "")).strip()
            environment = str(payload.get("environment", "demo")).lower()
            if environment not in FUTURES_URLS:
                raise ValueError("请选择 Demo 或真实网环境。")
            if not api_key or not api_secret:
                raise ValueError("请输入 USD-M 合约 API Key 和 Secret。")

            client = UMFuturesClient(
                base_url=FUTURES_URLS[environment],
                api_key=api_key,
                api_secret=api_secret,
                credential_hint="USD-M Futures API Key and Secret",
            )
            account = client.account()
            with self._lock:
                self._client = client
                self._environment = environment
                self._masked_key = f"{api_key[:4]}…{api_key[-4:]}" if len(api_key) >= 9 else "已连接"
                self._listen_key = ""
                self._automation = DemoAutomation(client) if environment == "demo" else None
            return {
                "environment": environment,
                "masked_key": self._masked_key,
                "account": self._account_metrics(account),
            }

        return _response(connect_account)

    def disconnect(self) -> dict[str, Any]:
        def clear() -> dict[str, Any]:
            with self._lock:
                if self._automation:
                    status = self._automation.status()
                    if status["running"] or status["starting"] or status["status"] in {"stopping", "error"}:
                        raise ValueError("请先使用“紧急停止并平仓”，再断开账户。")
                client = self._client
                has_stream = bool(self._listen_key)
            if client is not None and has_stream:
                try:
                    client.close_user_data_stream()
                except Exception:
                    pass
            with self._lock:
                self._client = None
                self._masked_key = ""
                self._listen_key = ""
                self._automation = None
            return {"connected": False}

        return _response(clear)

    def start_user_stream(self) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            client = self._connected_client()
            payload = client.start_user_data_stream()
            listen_key = str(payload.get("listenKey", "")).strip()
            if not listen_key:
                raise ValueError("Binance 未返回账户事件流凭证。")
            with self._lock:
                self._listen_key = listen_key
                environment = self._environment
            return {
                "listen_key": listen_key,
                "stream_url": f"{FUTURES_STREAM_URLS[environment]}/private/stream",
            }

        return _response(start)

    def keepalive_user_stream(self) -> dict[str, Any]:
        def keepalive() -> dict[str, Any]:
            client = self._connected_client()
            payload = client.keepalive_user_data_stream()
            listen_key = str(payload.get("listenKey", "")).strip() if isinstance(payload, dict) else ""
            with self._lock:
                if listen_key:
                    self._listen_key = listen_key
            return {"alive": True, "listen_key_changed": bool(listen_key)}

        return _response(keepalive)

    def stop_user_stream(self) -> dict[str, Any]:
        def stop() -> dict[str, Any]:
            client = self._connected_client()
            with self._lock:
                has_stream = bool(self._listen_key)
            if has_stream:
                client.close_user_data_stream()
            with self._lock:
                self._listen_key = ""
            return {"stopped": True}

        return _response(stop)

    def market(self, payload: dict[str, Any]) -> dict[str, Any]:
        def market_data() -> dict[str, Any]:
            symbol = str(payload.get("symbol", "BTCUSDT")).upper()
            selected_interval = str(payload.get("interval", "15m"))
            environment = str(payload.get("environment", self._environment)).lower()
            strategy_id = str(payload.get("strategy_id", "sma_crossover"))
            parameters = payload.get("parameters") or {}
            if selected_interval not in INTERVALS:
                raise ValueError("不支持这个 K 线周期。")

            client = self._public_client(environment)
            strategy = get_strategy(strategy_id)
            interval = strategy.execution_interval(selected_interval)
            now = datetime.now(timezone.utc)
            frames: dict[str, pd.DataFrame] = {}
            for required_interval in strategy.market_intervals(selected_interval):
                frame = fetch_klines(client, symbol, required_interval, strategy.history_limit)
                closed = frame[frame["close_time"] <= now]
                if closed.empty:
                    raise ValueError(f"{required_interval} 暂时没有已收盘 K 线。")
                frames[required_interval] = closed
            defaults = strategy.automation_defaults
            leverage = max(1, int(defaults.get("leverage", 50)))
            target_roi = float(defaults.get("take_profit_pct", 3)) / 100
            estimated_cost = 0.0008
            context = StrategyContext(
                frames=frames,
                execution_interval=interval,
                metadata={"target_price_fraction": target_roi / leverage + estimated_cost},
            )
            generated = validate_signal_frame(strategy.generate_with_context(context, parameters))
            ticker = client.ticker_24h(symbol)
            mark = client.mark_price(symbol)
            rows = generated.tail(180)
            series: list[dict[str, Any]] = []
            for _, row in rows.iterrows():
                point: dict[str, Any] = {
                    "time": row["open_time"].isoformat(),
                    "open": _optional_float(row.get("open")),
                    "high": _optional_float(row.get("high")),
                    "low": _optional_float(row.get("low")),
                    "close": _optional_float(row.get("close")),
                    "volume": _optional_float(row.get("volume")),
                    "signal": int(row["signal"]),
                }
                for item in strategy.chart_series:
                    point[item.key] = _optional_float(row.get(item.key))
                series.append(point)

            ready = generated.dropna(subset=["close"])
            current = int(ready["signal"].iloc[-1]) if not ready.empty else 0
            previous = int(ready["signal"].iloc[-2]) if len(ready) > 1 else current
            return {
                "symbol": symbol,
                "interval": interval,
                "price": _float(mark.get("markPrice") or ticker.get("lastPrice")),
                "last_price": _float(ticker.get("lastPrice")),
                "price_change_pct": _float(ticker.get("priceChangePercent")),
                "high_24h": _float(ticker.get("highPrice")),
                "low_24h": _float(ticker.get("lowPrice")),
                "volume_24h": _float(ticker.get("quoteVolume")),
                "signal": _signal_state(current, previous),
                "chart_series": [item.to_dict() for item in strategy.chart_series],
                "series": series,
            }

        return _response(market_data)

    def account_snapshot(self, symbol: str = "BTCUSDT") -> dict[str, Any]:
        def snapshot() -> dict[str, Any]:
            client = self._connected_client()
            account = client.account()
            position_payload = client.position_risk()
            positions = position_payload if isinstance(position_payload, list) else [position_payload]
            normalized = [self._position(item) for item in positions if _float(item.get("positionAmt")) != 0]
            selected_raw = next((item for item in positions if item.get("symbol") == symbol.upper()), {})
            selected = self._position(selected_raw) if selected_raw else {
                "symbol": symbol.upper(),
                "leverage": 1,
                "margin_type": "cross",
            }
            selected["config_resolved"] = bool(_float(selected_raw.get("leverage"))) if selected_raw else False
            try:
                config_payload = client.symbol_config()
                configs = config_payload if isinstance(config_payload, list) else [config_payload]
                by_symbol = {str(item.get("symbol", "")).upper(): item for item in configs}
                selected_config = by_symbol.get(symbol.upper(), {})
                if selected_config:
                    selected["config_resolved"] = True
                    selected["leverage"] = int(
                        _float(selected_config.get("leverage"), selected["leverage"])
                    )
                    selected["margin_type"] = str(
                        selected_config.get("marginType", selected["margin_type"])
                    ).lower()
                for position in normalized:
                    config = by_symbol.get(position["symbol"], {})
                    if not config:
                        continue
                    actual_leverage = int(_float(config.get("leverage"), position["leverage"]))
                    position["leverage"] = actual_leverage
                    position["margin_type"] = str(
                        config.get("marginType", position["margin_type"])
                    ).lower()
                    initial_margin = abs(position["amount"] * position["entry_price"]) / max(actual_leverage, 1)
                    position["roi_pct"] = (
                        position["unrealized_pnl"] / initial_margin * 100 if initial_margin else 0.0
                    )
            except (BinanceAPIError, requests.RequestException):
                pass
            return {
                "account": self._account_metrics(account),
                "selected_position": selected,
                "positions": normalized,
                "environment": self._environment,
                "masked_key": self._masked_key,
            }

        return _response(snapshot)

    def trade_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        def history() -> dict[str, Any]:
            client = self._connected_client()
            symbol = str(payload.get("symbol", "BTCUSDT")).strip().upper()
            days = int(payload.get("days", 7))
            limit = int(payload.get("limit", 100))
            if not symbol or not symbol.replace("_", "").isalnum():
                raise ValueError("成交历史合约名称无效。")
            if days not in {1, 7, 30, 90}:
                raise ValueError("成交历史仅支持查询 1、7、30 或 90 天。")
            limit = max(20, min(500, limit))

            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            display_start_ms = end_ms - days * DAY_MS
            fetch_start_ms = display_start_ms - 7 * DAY_MS
            trades: list[dict[str, Any]] = []
            truncated = False

            def fetch_window(start_ms: int, window_end_ms: int, depth: int = 0) -> None:
                nonlocal truncated
                rows = client.user_trades(
                    symbol,
                    start_time=start_ms,
                    end_time=window_end_ms,
                    limit=1000,
                )
                items = rows if isinstance(rows, list) else []
                if len(items) < 1000:
                    trades.extend(items)
                    return
                if depth >= 12 or window_end_ms - start_ms <= 60_000:
                    trades.extend(items)
                    truncated = True
                    return
                midpoint = start_ms + (window_end_ms - start_ms) // 2
                fetch_window(start_ms, midpoint, depth + 1)
                fetch_window(midpoint + 1, window_end_ms, depth + 1)

            cursor = fetch_start_ms
            while cursor <= end_ms:
                window_end = min(end_ms, cursor + MAX_TRADE_WINDOW_MS)
                fetch_window(cursor, window_end)
                cursor = window_end + 1

            unique: dict[tuple[str, int], dict[str, Any]] = {}
            for trade in trades:
                trade_id = int(_decimal(trade.get("id"), "-1"))
                unique[(str(trade.get("symbol", symbol)), trade_id)] = trade
            records = aggregate_closed_trades(list(unique.values()), display_start_ms)
            realized_pnl = sum(item["realized_pnl"] for item in records)
            commission = sum(item["commission"] for item in records)
            net_pnl = sum(item["net_pnl"] for item in records)
            wins = sum(1 for item in records if item["net_pnl"] > 0)
            losses = sum(1 for item in records if item["net_pnl"] < 0)
            decided = wins + losses
            return {
                "symbol": symbol,
                "days": days,
                "records": records[:limit],
                "total_count": len(records),
                "truncated": truncated,
                "summary": {
                    "realized_pnl": realized_pnl,
                    "commission": commission,
                    "net_pnl": net_pnl,
                    "wins": wins,
                    "losses": losses,
                    "win_rate_pct": wins / decided * 100 if decided else 0.0,
                },
            }

        return _response(history)

    def apply_risk(self, payload: dict[str, Any]) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            with self._lock:
                if self._automation:
                    status = self._automation.status()
                    if status["running"] or status["starting"]:
                        raise ValueError("自动执行期间不能单独修改合约风险参数。")
            client = self._connected_client()
            symbol = str(payload.get("symbol", "BTCUSDT")).upper()
            leverage = int(payload.get("leverage", 1))
            margin_type = str(payload.get("margin_type", "ISOLATED")).upper()
            if leverage < 1 or leverage > 125:
                raise ValueError("杠杆倍数必须在 1 到 125 之间。")
            if margin_type not in {"ISOLATED", "CROSSED"}:
                raise ValueError("保证金模式无效。")

            try:
                client.change_margin_type(symbol, margin_type)
            except BinanceAPIError as exc:
                code = exc.payload.get("code") if isinstance(exc.payload, dict) else None
                if code != -4046:
                    raise
            leverage_result = client.change_leverage(symbol, leverage)
            return {
                "symbol": symbol,
                "leverage": int(leverage_result.get("leverage", leverage)),
                "margin_type": margin_type,
            }

        return _response(apply)

    def start_automation(self, payload: dict[str, Any]) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            with self._lock:
                client = self._client
                environment = self._environment
                automation = self._automation
            if client is None:
                raise ValueError("请先连接 Binance Demo 合约账户。")
            if environment != "demo" or client.base_url != DEMO_FUTURES_URL or automation is None:
                raise ValueError("自动交易仅支持 Binance Demo，真实网已硬锁。")
            return automation.start(payload)

        return _response(start)

    def automation_status(self) -> dict[str, Any]:
        def status() -> dict[str, Any]:
            with self._lock:
                automation = self._automation
                connected = self._client is not None
                environment = self._environment
            if automation is None:
                return {
                    "running": False,
                    "starting": False,
                    "status": "locked" if environment == "live" else "idle",
                    "reason": "真实网自动交易已硬锁" if environment == "live" else "请先连接 Demo 账户",
                    "demo_only": True,
                    "enabled": connected and environment == "demo",
                    "config": None,
                    "last_candle_time": "",
                    "last_signal": None,
                    "daily_pnl": 0,
                    "daily_pnl_pct": 0,
                    "protection_orders": 0,
                    "logs": [],
                }
            payload = automation.status()
            payload["enabled"] = connected and environment == "demo"
            return payload

        return _response(status)

    def freqtrade_status(self) -> dict[str, Any]:
        return _response(self._freqtrade.status)

    def research_status(self) -> dict[str, Any]:
        def status() -> dict[str, Any]:
            freqtrade = self._freqtrade.status()
            sndk = self._sndk_engine.status()
            if freqtrade.get("running") or freqtrade.get("dry_run", {}).get("running"):
                return freqtrade
            if str(sndk.get("started_at", "")) > str(freqtrade.get("started_at", "")):
                sndk["dry_run"] = freqtrade.get("dry_run", {})
                return sndk
            return freqtrade

        return _response(status)

    def knowledge_status(self) -> dict[str, Any]:
        return _response(self._knowledge.status)

    def macro_calendar(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        refresh = bool((payload or {}).get("refresh", False))
        return _response(lambda: self._macro_calendar.get(refresh=refresh))

    def knowledge_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        question = str((payload or {}).get("question", "")).strip()
        limit = int((payload or {}).get("limit", 6))
        return _response(lambda: self._knowledge.query(question, limit))

    def rebuild_knowledge_index(self) -> dict[str, Any]:
        return _response(lambda: self._knowledge.ensure_index(force=True))

    def start_freqtrade_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._freqtrade.start_backtest(payload))

    def save_portfolio(self, payload: dict[str, Any]) -> dict[str, Any]:
        def save() -> dict[str, Any]:
            portfolio = self._portfolio_from_payload(payload)
            return self._portfolio_store.save(portfolio)

        return _response(save)

    def list_portfolios(self) -> dict[str, Any]:
        return _response(lambda: {"portfolios": self._portfolio_store.list()})

    def delete_portfolio(self, portfolio_id: str) -> dict[str, Any]:
        return _response(lambda: {"deleted": self._portfolio_store.delete(str(portfolio_id))})

    def start_portfolio_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            portfolio = self._portfolio_from_payload(payload)
            strategy = get_strategy(portfolio.strategy_id)
            self._portfolio_store.save(portfolio)
            adapter = strategy.backtest_adapter
            if adapter.get("engine") == "freqtrade":
                strategy_class = str(adapter["strategy_class"])
                return self._freqtrade.start_portfolio_backtest(portfolio, strategy_class)
            if adapter.get("engine") == "sndk_hybrid":
                return self._sndk_engine.start_portfolio_backtest(portfolio, strategy)
            raise ValueError(f"{strategy.name}尚未接入历史验证引擎。")

        return _response(start)

    def start_portfolio_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            portfolio = self._portfolio_from_payload(payload)
            strategy = get_strategy(portfolio.strategy_id)
            adapter = strategy.backtest_adapter
            if adapter.get("engine") != "freqtrade" or adapter.get("supports_dry_run") is False:
                raise ValueError(f"{strategy.name}当前只允许历史验证，不能启动模拟或真实交易。")
            strategy_class = str(adapter["strategy_class"])
            self._portfolio_store.save(portfolio)
            return self._freqtrade.start_portfolio_dry_run(portfolio, strategy_class)

        return _response(start)

    def start_freqtrade_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._freqtrade.start_dry_run(payload))

    def stop_freqtrade_dry_run(self) -> dict[str, Any]:
        return _response(self._freqtrade.stop_dry_run)

    def open_freqtrade_folder(self) -> dict[str, Any]:
        def open_folder() -> dict[str, Any]:
            self._freqtrade.ensure_workspace()
            subprocess.run(["open", str(FREQTRADE_DIR)], check=True)
            return {"path": str(FREQTRADE_DIR)}

        return _response(open_folder)

    def stop_automation(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        def stop() -> dict[str, Any]:
            with self._lock:
                automation = self._automation
                environment = self._environment
            if environment != "demo" or automation is None:
                raise ValueError("当前没有可停止的 Demo 自动交易。")
            close_position = bool((payload or {}).get("close_position", True))
            return automation.stop(close_position=close_position)

        return _response(stop)

    def configure_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.configure(payload))

    def workspace_bootstrap(self) -> dict[str, Any]:
        """Load local research state without account or exchange network requests."""
        return _response(lambda: {
            'strategies': self._library_metadata(),
            'daily_strategy_assets': self._daily_strategy.catalog(),
            'workspace_settings': self._workspace_settings.read(),
        })

    def daily_strategy_catalog(self, payload: Any = None) -> dict[str, Any]:
        return _response(self._daily_strategy.catalog)

    def _library_metadata(self):
        settings = self._workspace_settings.read()
        strategies, _ = discover_strategies()
        result = []
        for strategy in strategies.values():
            if strategy.strategy_id in settings.get('deleted', []):
                continue
            item = strategy.metadata()
            item['name'] = settings.get('names', {}).get(strategy.strategy_id, item['name'])
            result.append(item)
        return result

    def edit_library_strategy(self, payload):
        def edit():
            strategy_id = str(payload.get('id', ''))
            get_strategy(strategy_id)
            settings = self._workspace_settings.read()
            if payload.get('action') == 'delete':
                deleted = list(dict.fromkeys(settings.get('deleted', []) + [strategy_id]))
                self._workspace_settings.update(deleted=deleted)
            elif payload.get('action') == 'rename':
                name = str(payload.get('name', '')).strip()
                if not name or len(name) > 80:
                    raise ValueError('名称应为 1–80 个字符')
                names = settings.get('names', {})
                names[strategy_id] = name
                self._workspace_settings.update(names=names)
            else:
                raise ValueError('操作无效')
            return self._library_metadata()
        return _response(edit)

    def save_appearance(self, payload):
        def save():
            settings = self._workspace_settings.image(payload.get('kind'), payload.get('data_url'))
            if payload.get('kind') == 'icon':
                self.apply_application_icon()
            return settings
        return _response(save)

    def apply_application_icon(self):
        try:
            import base64
            from AppKit import NSApplication, NSImage
            from Foundation import NSData
            icon = self._workspace_settings.read().get('icon')
            if icon:
                raw = base64.b64decode(icon.split(',', 1)[1])
            else:
                raw = resources.files('binance_quant').joinpath('web/assets/custom-icon.jpg').read_bytes()
            data = NSData.dataWithBytes_length_(raw, len(raw))
            image = NSImage.alloc().initWithData_(data)
            NSApplication.sharedApplication().performSelectorOnMainThread_withObject_waitUntilDone_('setApplicationIconImage:', image, False)
        except ImportError:
            pass

    def add_daily_asset(self, payload):
        def add():
            asset = self._daily_strategy.resolve_asset(str(payload.get('symbol', '')))
            settings = self._workspace_settings.read()
            assets = [item for item in settings.get('assets', []) if item['id'] != asset['id']]
            assets.append(asset)
            self._workspace_settings.update(assets=assets)
            self._daily_strategy.add_asset(asset)
            return self._daily_strategy.catalog()
        return _response(add)

    def generate_daily_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        asset_id = str((payload or {}).get("asset_id", "SNDK")).strip()
        force = bool((payload or {}).get("force", False))
        def generate():
            report = self._daily_strategy.generate(asset_id, force=force)
            with self._workspace_settings.lock:
                reports = self._workspace_settings.read().get('reports', {})
                reports[report['asset']['id']] = {key: value for key, value in report.items() if key != 'diagnostics'}
                self._workspace_settings.update(reports=reports)
            return report
        return _response(generate)

    def start_agent_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.start(payload))

    def stop_agent_monitor(self) -> dict[str, Any]:
        return _response(self._agent.stop)

    def agent_status(self) -> dict[str, Any]:
        return _response(self._agent.status)

    def test_agent_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.test_model(payload))

    def agent_contract_catalog(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return _response(lambda: self._agent.contract_catalog(bool((payload or {}).get('refresh', False))))

    def pipeline_open(self) -> dict[str, Any]:
        def start():
            from .pipeline.desktop_service import DesktopPipeline
            with self._lock:
                if not hasattr(self, '_pipeline_service'):
                    self._pipeline_service = DesktopPipeline()
                return self._pipeline_service.start()
        return _response(start)

    def analyze_daily_agents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.analyze_daily_agents(payload))

    def analyze_now(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.analyze_now(payload))

    def test_feishu(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _response(lambda: self._agent.test_feishu(payload))

    def shutdown(self) -> dict[str, Any]:
        def close() -> dict[str, Any]:
            if hasattr(self, '_pipeline_service'):
                self._pipeline_service.stop()
            self._agent.shutdown()
            self._freqtrade.shutdown()
            return {"stopped": True}

        return _response(close)

    def open_strategy_folder(self) -> dict[str, Any]:
        def open_folder() -> dict[str, Any]:
            USER_STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
            readme = USER_STRATEGY_DIR / "README.txt"
            if not readme.exists():
                readme.write_text(
                    "把实现 Strategy 接口的 .py 文件放在这里，App 重启后会自动加载。\n"
                    "每个文件需要导出 STRATEGY 实例或 Strategy 子类。\n",
                    encoding="utf-8",
                )
            subprocess.run(["open", str(USER_STRATEGY_DIR)], check=True)
            return {"path": str(USER_STRATEGY_DIR)}

        return _response(open_folder)

    @staticmethod
    def _ensure_strategy_workspace() -> None:
        USER_STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
        destination = USER_STRATEGY_DIR / "my_strategy.py"
        if destination.exists():
            return
        template = resources.read_text(
            "binance_quant.resources",
            "my_strategy.py.txt",
            encoding="utf-8",
        )
        destination.write_text(template, encoding="utf-8")

    @staticmethod
    def _account_metrics(account: dict[str, Any]) -> dict[str, float]:
        wallet = _float(account.get("totalWalletBalance"))
        unrealized = _float(account.get("totalUnrealizedProfit"))
        margin_balance = _float(account.get("totalMarginBalance"), wallet + unrealized)
        initial_margin = _float(account.get("totalInitialMargin"))
        return {
            "wallet_balance": wallet,
            "unrealized_pnl": unrealized,
            "available_balance": _float(account.get("availableBalance")),
            "margin_balance": margin_balance,
            "margin_usage_pct": initial_margin / margin_balance * 100 if margin_balance else 0.0,
            "return_pct": unrealized / wallet * 100 if wallet else 0.0,
        }

    @staticmethod
    def _position(item: dict[str, Any]) -> dict[str, Any]:
        amount = _float(item.get("positionAmt"))
        unrealized = _float(item.get("unRealizedProfit"))
        initial_margin = _float(item.get("positionInitialMargin"))
        return {
            "symbol": item.get("symbol", ""),
            "side": "LONG" if amount > 0 else "SHORT" if amount < 0 else "FLAT",
            "amount": amount,
            "entry_price": _float(item.get("entryPrice")),
            "mark_price": _float(item.get("markPrice")),
            "leverage": int(_float(item.get("leverage"), 1)),
            "margin_type": str(item.get("marginType", "cross")).lower(),
            "unrealized_pnl": unrealized,
            "roi_pct": unrealized / initial_margin * 100 if initial_margin else 0.0,
            "liquidation_price": _float(item.get("liquidationPrice")),
        }
