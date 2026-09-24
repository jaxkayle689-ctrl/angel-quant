from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from typing import Any

from .client import BinanceAPIError, UMFuturesClient
from .data import fetch_klines
from .strategy_api import StrategyContext, validate_signal_frame
from .strategy_registry import get_strategy


DEMO_FUTURES_URL = "https://demo-fapi.binance.com"
CLIENT_ID_PREFIX = "bq_"


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else Decimal(default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_string(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


@dataclass(frozen=True)
class AutomationConfig:
    symbol: str
    interval: str
    strategy_id: str
    parameters: dict[str, Any]
    leverage: int = 3
    allocation_pct: float = 5.0
    stop_loss_pct: float = 1.0
    take_profit_pct: float = 2.0
    daily_max_loss_pct: float = 3.0

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AutomationConfig":
        config = cls(
            symbol=str(payload.get("symbol", "BTCUSDT")).strip().upper(),
            interval=str(payload.get("interval", "15m")).strip(),
            strategy_id=str(payload.get("strategy_id", "sma_crossover")).strip(),
            parameters=dict(payload.get("parameters") or {}),
            leverage=int(payload.get("leverage", 3)),
            allocation_pct=float(payload.get("allocation_pct", 5)),
            stop_loss_pct=float(payload.get("stop_loss_pct", 1)),
            take_profit_pct=float(payload.get("take_profit_pct", 2)),
            daily_max_loss_pct=float(payload.get("daily_max_loss_pct", 3)),
        )
        if not config.symbol or not config.strategy_id:
            raise ValueError("合约和策略不能为空。")
        if config.leverage < 1 or config.leverage > 125:
            raise ValueError("Demo 自动交易杠杆限制为 1 到 125 倍。")
        ranges = (
            ("仓位占比", config.allocation_pct, 1, 20),
            ("止损", config.stop_loss_pct, 0.1, 50),
            ("止盈", config.take_profit_pct, 0.1, 20),
            ("当日最大亏损", config.daily_max_loss_pct, 0.1, 20),
        )
        for label, value, minimum, maximum in ranges:
            if not math.isfinite(value) or value < minimum or value > maximum:
                raise ValueError(f"{label}必须在 {minimum} 到 {maximum} 之间。")
        strategy = get_strategy(config.strategy_id)
        policy = strategy.execution_policy(config.parameters)
        minimum_leverage = int(policy.get("minimum_leverage", 1))
        if config.leverage < minimum_leverage:
            raise ValueError(f"{strategy.name} 要求至少 {minimum_leverage} 倍杠杆。")
        return config

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SymbolRules:
    quantity_step: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    price_tick: Decimal

    @classmethod
    def from_exchange_info(cls, payload: dict[str, Any], symbol: str) -> "SymbolRules":
        symbols = payload.get("symbols") or []
        item = next((entry for entry in symbols if entry.get("symbol") == symbol), None)
        if not item:
            raise ValueError(f"Binance Demo 中未找到合约 {symbol}。")
        filters = {entry.get("filterType"): entry for entry in item.get("filters") or []}
        quantity_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
        if _decimal(quantity_filter.get("stepSize")) <= 0:
            quantity_filter = filters.get("LOT_SIZE") or quantity_filter
        notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
        price_filter = filters.get("PRICE_FILTER") or {}
        rules = cls(
            quantity_step=_decimal(quantity_filter.get("stepSize")),
            min_quantity=_decimal(quantity_filter.get("minQty")),
            max_quantity=_decimal(quantity_filter.get("maxQty"), "999999999"),
            min_notional=_decimal(notional_filter.get("notional") or notional_filter.get("minNotional")),
            price_tick=_decimal(price_filter.get("tickSize")),
        )
        if rules.quantity_step <= 0 or rules.min_quantity <= 0:
            raise ValueError(f"{symbol} 的市价单数量规则无效。")
        return rules

    def quantity_for(
        self,
        available_balance: Decimal,
        allocation_pct: float,
        leverage: int,
        mark_price: Decimal,
    ) -> Decimal:
        if available_balance <= 0 or mark_price <= 0:
            raise ValueError("可用余额或标记价格无效。")
        notional = available_balance * _decimal(allocation_pct) / Decimal("100") * Decimal(leverage)
        quantity = floor_to_step(notional / mark_price, self.quantity_step)
        if quantity < self.min_quantity:
            raise ValueError("按当前仓位占比计算的数量低于该合约最小下单量。")
        if self.max_quantity > 0 and quantity > self.max_quantity:
            quantity = floor_to_step(self.max_quantity, self.quantity_step)
        if self.min_notional > 0 and quantity * mark_price < self.min_notional:
            raise ValueError("按当前仓位占比计算的金额低于该合约最小名义价值。")
        return quantity

    def price(self, value: Decimal, rounding: str = "down") -> Decimal:
        rounded = ceil_to_step(value, self.price_tick) if rounding == "up" else floor_to_step(value, self.price_tick)
        if rounded <= 0:
            raise ValueError("保护单触发价格无效。")
        return rounded


class DemoAutomation:
    def __init__(self, client: UMFuturesClient, poll_seconds: float = 5.0) -> None:
        self.client = client
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._execution_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._config: AutomationConfig | None = None
        self._rules: SymbolRules | None = None
        self._running = False
        self._starting = False
        self._status = "idle"
        self._reason = "尚未启动"
        self._started_at = ""
        self._last_candle_time = ""
        self._last_signal: int | None = None
        self._last_error = ""
        self._baseline_balance = Decimal("0")
        self._current_balance = Decimal("0")
        self._baseline_date = ""
        self._protection_orders = 0
        self._managed_direction = 0
        self._blocked_signal = 0
        self._policy: dict[str, Any] = {}
        self._maker_rate = Decimal("0.0002")
        self._taker_rate = Decimal("0.0005")
        self._fee_source = "保守默认值"
        self._active_stop_price = Decimal("0")
        self._active_take_price = Decimal("0")
        self._entry_wallet_balance = Decimal("0")
        self._consecutive_losses = 0
        self._cooldown_candles = 0
        self._pause_until: datetime | None = None
        self._trade_times: deque[datetime] = deque()
        self._logs: deque[dict[str, str]] = deque(maxlen=100)

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("confirmation", "")) != "DEMO_ONLY":
            raise ValueError("请先确认只使用 Demo 虚拟资金。")
        config = AutomationConfig.from_payload(payload)
        strategy = get_strategy(config.strategy_id)
        policy = strategy.execution_policy(config.parameters)
        with self._lock:
            if self._running or self._starting:
                raise ValueError("Demo 自动交易已经在运行。")
            self._starting = True
            self._status = "starting"
            self._reason = "正在检查账户"

        try:
            if self.client.base_url != DEMO_FUTURES_URL:
                raise ValueError("自动交易已硬锁为 Binance Demo，真实网不可启动。")
            position_mode = self.client.position_mode()
            if bool(position_mode.get("dualSidePosition")):
                raise ValueError("请先在 Binance Demo 合约设置中切换为单向持仓模式。")

            positions_payload = self.client.position_risk()
            positions = positions_payload if isinstance(positions_payload, list) else [positions_payload]
            if any(_decimal(item.get("positionAmt")) != 0 for item in positions):
                raise ValueError("启动前必须先清空 Demo 账户的全部持仓。")

            exchange_info = self.client.exchange_info(config.symbol)
            rules = SymbolRules.from_exchange_info(exchange_info, config.symbol)
            self._cancel_owned_algo_orders(config.symbol)
            self._cancel_owned_regular_orders(config.symbol)
            regular_orders = self.client.current_open_orders(config.symbol) or []
            algo_orders = self.client.current_algo_open_orders(config.symbol) or []
            if regular_orders or algo_orders:
                raise ValueError("该合约存在非本 App 挂单，请先在 Binance Demo 撤单。")

            try:
                self.client.change_margin_type(config.symbol, "ISOLATED")
            except BinanceAPIError as exc:
                code = exc.payload.get("code") if isinstance(exc.payload, dict) else None
                if code != -4046:
                    raise
            leverage_result = self.client.change_leverage(config.symbol, config.leverage)
            applied_leverage = int(leverage_result.get("leverage", config.leverage))
            if applied_leverage != config.leverage:
                raise ValueError(
                    f"{config.symbol} 实际只应用了 {applied_leverage}x，无法按 {config.leverage}x 启动。"
                )

            maker_rate, taker_rate, fee_source = self._load_commission_rates(config.symbol)

            account = self.client.account()
            balance = self._margin_balance(account)
            if balance <= 0:
                raise ValueError("Demo 账户保证金余额不足。")
            last_closed = self._latest_closed_frame(config, strategy)
            last_candle_time = last_closed["close_time"].iloc[-1].isoformat()
            now = datetime.now(timezone.utc)

            with self._lock:
                self._config = config
                self._rules = rules
                self._baseline_balance = balance
                self._current_balance = balance
                self._baseline_date = now.date().isoformat()
                self._last_candle_time = last_candle_time
                self._last_signal = None
                self._last_error = ""
                self._protection_orders = 0
                self._managed_direction = 0
                self._blocked_signal = 0
                self._policy = policy
                self._maker_rate = maker_rate
                self._taker_rate = taker_rate
                self._fee_source = fee_source
                self._active_stop_price = Decimal("0")
                self._active_take_price = Decimal("0")
                self._entry_wallet_balance = Decimal("0")
                self._consecutive_losses = 0
                self._cooldown_candles = 0
                self._pause_until = None
                self._trade_times.clear()
                self._stop_event.clear()
                self._running = True
                self._starting = False
                self._status = "running"
                self._reason = "等待下一根 K 线收盘"
                self._started_at = now.isoformat()
                self._logs.clear()
                self._log_locked("info", "START", f"{config.symbol} 自动交易已启动，{config.leverage}x 逐仓")
                self._log_locked(
                    "info",
                    "FEE",
                    f"费率 Maker {float(maker_rate) * 100:.4f}% / Taker {float(taker_rate) * 100:.4f}%（{fee_source}）",
                )
                self._log_locked("info", "WAIT", "从下一根收盘 K 线开始执行信号")
                self._thread = threading.Thread(target=self._run, name="bq-demo-automation", daemon=True)
                self._thread.start()
            return self.status()
        except Exception:
            with self._lock:
                self._starting = False
                self._running = False
                self._status = "idle"
                self._reason = "启动检查未通过"
            raise

    def stop(self, close_position: bool = True) -> dict[str, Any]:
        with self._lock:
            config = self._config
            was_active = self._running or self._starting
            self._stop_event.set()
            thread = self._thread
            self._running = False
            self._starting = False
            self._status = "stopping" if close_position and config else "stopped"
            self._reason = "紧急停止中" if close_position and config else "已停止"
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, self.poll_seconds + 1.0))
        if close_position and config:
            try:
                with self._execution_lock:
                    self._flatten(config.symbol, "EMERGENCY")
                with self._lock:
                    self._status = "stopped"
                    self._reason = "已停止并平仓"
                    self._log_locked("warning", "STOP", "紧急停止完成，持仓与 App 保护单已清理")
            except Exception as exc:
                with self._lock:
                    self._status = "error"
                    self._reason = "紧急停止失败"
                    self._last_error = str(exc)
                    self._log_locked("error", "STOP_ERROR", f"紧急停止失败：{exc}")
                raise
        elif was_active:
            with self._lock:
                self._log_locked("warning", "STOP", "自动执行已停止，未主动平仓")
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            daily_pnl = self._current_balance - self._baseline_balance
            daily_pnl_pct = (
                daily_pnl / self._baseline_balance * Decimal("100")
                if self._baseline_balance
                else Decimal("0")
            )
            return {
                "running": self._running,
                "starting": self._starting,
                "status": self._status,
                "reason": self._reason,
                "demo_only": True,
                "config": self._config.public_dict() if self._config else None,
                "started_at": self._started_at,
                "last_candle_time": self._last_candle_time,
                "last_signal": self._last_signal,
                "last_error": self._last_error,
                "baseline_balance": float(self._baseline_balance),
                "current_balance": float(self._current_balance),
                "daily_pnl": float(daily_pnl),
                "daily_pnl_pct": float(daily_pnl_pct),
                "protection_orders": self._protection_orders,
                "maker_fee_pct": float(self._maker_rate * Decimal("100")),
                "taker_fee_pct": float(self._taker_rate * Decimal("100")),
                "fee_source": self._fee_source,
                "consecutive_losses": self._consecutive_losses,
                "cooldown_candles": self._cooldown_candles,
                "pause_until": self._pause_until.isoformat() if self._pause_until else "",
                "active_stop_price": float(self._active_stop_price),
                "active_take_price": float(self._active_take_price),
                "logs": list(self._logs),
            }

    def _run(self) -> None:
        consecutive_errors = 0
        while not self._stop_event.wait(self.poll_seconds):
            try:
                with self._execution_lock:
                    self._tick()
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                with self._lock:
                    self._last_error = str(exc)
                    self._reason = f"接口异常，正在重试（{consecutive_errors}）"
                    self._log_locked("error", "RETRY", f"{exc}")
        with self._lock:
            if self._status == "running":
                self._status = "stopped"
                self._reason = "已停止"
            self._running = False

    def _tick(self) -> None:
        if self._stop_event.is_set():
            return
        with self._lock:
            config = self._config
        if config is None:
            return

        account = self.client.account()
        balance = self._margin_balance(account)
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            if today != self._baseline_date:
                self._baseline_date = today
                self._baseline_balance = balance
                self._log_locked("info", "DAILY_RESET", "UTC 跨日，已重置当日亏损基准")
            self._current_balance = balance
            max_loss = self._baseline_balance * _decimal(config.daily_max_loss_pct) / Decimal("100")
            loss_reached = self._baseline_balance - balance >= max_loss

        if loss_reached:
            self._log("error", "LOSS_LIMIT", "达到当日最大亏损，正在平仓并停止")
            self._flatten(config.symbol, "LOSS_LIMIT")
            with self._lock:
                self._running = False
                self._status = "halted"
                self._reason = "达到当日最大亏损，已平仓"
                self._stop_event.set()
            return

        positions_payload = self.client.position_risk()
        positions = positions_payload if isinstance(positions_payload, list) else [positions_payload]
        external_positions = [
            item
            for item in positions
            if item.get("symbol") != config.symbol and _decimal(item.get("positionAmt")) != 0
        ]
        if external_positions:
            self._log("error", "OTHER_POSITION", "检测到其它合约持仓，正在停止当前自动策略")
            self._flatten(config.symbol, "OTHER_POSITION")
            with self._lock:
                self._running = False
                self._status = "halted"
                self._reason = "检测到其它合约持仓，已停止"
                self._stop_event.set()
            return
        selected = next((item for item in positions if item.get("symbol") == config.symbol), {})
        amount = _decimal(selected.get("positionAmt"))
        if amount == 0:
            self._cancel_owned_regular_orders(config.symbol)
        current_direction = 1 if amount > 0 else -1 if amount < 0 else 0
        if amount != 0 and self._managed_direction and current_direction != self._managed_direction:
            self._log("error", "POSITION_CHANGED", "策略持仓方向被外部修改，正在平仓并停止")
            self._flatten(config.symbol, "POSITION_CHANGED")
            with self._lock:
                self._running = False
                self._status = "halted"
                self._reason = "持仓方向被外部修改，已平仓"
                self._stop_event.set()
            return
        if amount != 0 and not self._managed_direction:
            self._log("error", "UNMANAGED_POSITION", "检测到非自动策略持仓，正在安全平仓并停止")
            self._flatten(config.symbol, "UNMANAGED_POSITION")
            with self._lock:
                self._running = False
                self._status = "halted"
                self._reason = "检测到非策略持仓，已平仓"
                self._stop_event.set()
            return
        if amount == 0 and self._managed_direction:
            self._blocked_signal = (
                0 if self._policy.get("reenter_same_signal", False) else self._managed_direction
            )
            self._managed_direction = 0
            self._cancel_owned_algo_orders(config.symbol)
            self._record_trade_exit(account)
            self._active_stop_price = Decimal("0")
            self._active_take_price = Decimal("0")
            self._log("warning", "PROTECTED_EXIT", "保护单已平仓，进入冷却期")
        self._protection_orders = self._owned_algo_order_count(config.symbol)
        if amount != 0 and self._managed_direction and self._protection_orders < 2:
            payload = self.client.position_risk(config.symbol)
            positions = payload if isinstance(payload, list) else [payload]
            position = next((item for item in positions if item.get("symbol") == config.symbol), {})
            entry = _decimal(position.get("entryPrice"))
            if entry <= 0:
                raise ValueError("持仓保护单缺失，且无法读取开仓价格。")
            self._cancel_owned_algo_orders(config.symbol)
            self._place_protection(
                config,
                self._managed_direction,
                entry,
                self._active_stop_price if self._active_stop_price > 0 else None,
            )
            self._log("warning", "PROTECT_REPAIR", "检测到保护单缺失，已重新挂单")

        strategy = get_strategy(config.strategy_id)
        frame = self._latest_closed_frame(config, strategy)
        candle_time = frame["close_time"].iloc[-1].isoformat()
        with self._lock:
            if candle_time <= self._last_candle_time:
                self._reason = "运行中，等待 K 线收盘"
                return

        context = self._latest_closed_context(config, strategy, frame)
        generated = validate_signal_frame(strategy.generate_with_context(context, config.parameters))
        signal = int(generated["signal"].iloc[-1])
        signal_row = generated.iloc[-1].to_dict()
        with self._lock:
            self._last_candle_time = candle_time
            self._last_signal = signal
            self._reason = f"已处理 {candle_time}"
        trend_state = str(signal_row.get("trend_state") or "")
        trend_note = {"UP": "上涨趋势", "DOWN": "下降趋势", "NEUTRAL": "趋势未确认"}.get(trend_state, "")
        suffix = f"，{trend_note}" if trend_note else ""
        self._log("info", "SIGNAL", f"收盘信号：{self._signal_label(signal)}{suffix}")

        now = datetime.now(timezone.utc)
        if self._pause_until:
            if now < self._pause_until:
                self._reason = f"连续亏损暂停至 {self._pause_until.strftime('%H:%M:%S')} UTC"
                self._log("warning", "PAUSE", "连续亏损风控暂停中，本根 K 线不入场")
                return
            self._pause_until = None
            self._consecutive_losses = 0
            self._log("info", "RESUME", "连续亏损暂停结束，恢复观察")
        if self._cooldown_candles > 0:
            self._cooldown_candles -= 1
            self._reason = f"退出后冷却，剩余 {self._cooldown_candles} 根"
            self._log("info", "COOLDOWN", "退出后冷却，本根 K 线不入场")
            return

        if self._blocked_signal and signal == self._blocked_signal:
            self._log("info", "COOLDOWN", "保护单退出后信号未改变，本根 K 线不重入")
            return
        if signal != self._blocked_signal:
            self._blocked_signal = 0
        self._execute_target(config, signal, amount, signal_row)

    def _execute_target(
        self,
        config: AutomationConfig,
        signal: int,
        amount: Decimal,
        signal_row: dict[str, Any] | None = None,
    ) -> None:
        if self._stop_event.is_set():
            return
        current = 1 if amount > 0 else -1 if amount < 0 else 0
        if current == signal:
            self._log("info", "HOLD", f"仓位已是{self._signal_label(signal)}")
            return
        if current and not self._policy.get("reverse_on_signal_change", False):
            self._log("info", "HOLD", "当前持仓由止盈/止损保护，本根信号不改仓")
            return
        self._cancel_owned_algo_orders(config.symbol)
        if amount != 0:
            side = "SELL" if amount > 0 else "BUY"
            self.client.new_order(
                config.symbol,
                side,
                order_type="MARKET",
                quantity=_decimal_string(abs(amount)),
                position_side="BOTH",
                reduce_only=True,
                client_order_id=self._client_id("close"),
                new_order_resp_type="RESULT",
                test=False,
            )
            self._managed_direction = 0
            self._log("warning", "CLOSE", "原方向仓位已市价平仓")
            self._wait_for_flat(config.symbol)
        if signal == 0:
            return
        if self._stop_event.is_set():
            return

        now = datetime.now(timezone.utc)
        while self._trade_times and now - self._trade_times[0] >= timedelta(hours=1):
            self._trade_times.popleft()
        max_trades = int(self._policy.get("max_trades_per_hour", 0))
        if max_trades and len(self._trade_times) >= max_trades:
            self._log("warning", "RATE_LIMIT", f"最近一小时已开仓 {max_trades} 次，本次跳过")
            return

        account = self.client.account()
        available = _decimal(account.get("availableBalance"))
        mark = _decimal(self.client.mark_price(config.symbol).get("markPrice"))
        rules = self._rules
        if rules is None:
            raise ValueError("合约下单规则尚未加载。")
        quantity = rules.quantity_for(available, config.allocation_pct, config.leverage, mark)
        side = "BUY" if signal > 0 else "SELL"
        stop_reference = _decimal((signal_row or {}).get("stop_price"))
        expected_entry = mark
        client_order_id = self._client_id("open")

        if self._policy.get("entry_order") == "MAKER_GTX":
            book = self.client.book_ticker(config.symbol)
            bid = _decimal(book.get("bidPrice"))
            ask = _decimal(book.get("askPrice"))
            if bid <= 0 or ask <= bid:
                self._log("warning", "SKIP", "买一/卖一价格无效，本次不入场")
                return
            spread_bps = (ask - bid) / ((ask + bid) / Decimal("2")) * Decimal("10000")
            max_spread = _decimal(self._policy.get("max_spread_bps"), "2")
            if spread_bps > max_spread:
                self._log(
                    "warning",
                    "SPREAD",
                    f"点差 {float(spread_bps):.2f} bps 超过 {float(max_spread):.2f} bps，本次跳过",
                )
                return
            expected_entry = rules.price(bid, "down") if signal > 0 else rules.price(ask, "up")
            try:
                self._trade_plan(config, signal, expected_entry, stop_reference, signal_row)
            except ValueError as exc:
                self._log("warning", "SKIP", str(exc))
                return
            self.client.new_order(
                config.symbol,
                side,
                order_type="LIMIT",
                quantity=_decimal_string(quantity),
                price=_decimal_string(expected_entry),
                time_in_force="GTX",
                position_side="BOTH",
                client_order_id=client_order_id,
                new_order_resp_type="ACK",
                test=False,
            )
            timeout = float(self._policy.get("entry_timeout_seconds", 4.0))
            position = self._wait_for_position_optional(config.symbol, signal, timeout)
            self._cancel_regular_order(config.symbol, client_order_id)
            if not position:
                self._log("info", "NO_FILL", f"Maker 挂单 {timeout:.0f} 秒未成交，已撤单且不追价")
                return
        else:
            try:
                self.client.new_order(
                    config.symbol,
                    side,
                    order_type="MARKET",
                    quantity=_decimal_string(quantity),
                    position_side="BOTH",
                    client_order_id=client_order_id,
                    new_order_resp_type="RESULT",
                    test=False,
                )
                position = self._wait_for_position(config.symbol, signal)
            except Exception as exc:
                try:
                    self._flatten(config.symbol, "OPEN_CONFIRMATION_FAILED")
                except Exception as flatten_error:
                    raise ValueError(
                        f"开仓确认失败，且安全平仓失败：{flatten_error}"
                    ) from exc
                raise

        self._managed_direction = signal
        self._entry_wallet_balance = self._wallet_balance(account)
        self._trade_times.append(datetime.now(timezone.utc))
        entry = _decimal(position.get("entryPrice"))
        if entry <= 0:
            entry = expected_entry
        self._log(
            "success",
            "OPEN",
            f"已{self._signal_label(signal)}，数量 {_decimal_string(quantity)}，成交价 {_decimal_string(entry)}",
        )
        try:
            self._place_protection(config, signal, entry, stop_reference, signal_row)
        except Exception:
            self._cancel_owned_algo_orders(config.symbol)
            self._flatten(config.symbol, "PROTECTION_FAILED")
            raise

    def _place_protection(
        self,
        config: AutomationConfig,
        signal: int,
        entry: Decimal,
        stop_reference: Decimal | None = None,
        signal_row: dict[str, Any] | None = None,
    ) -> None:
        rules = self._rules
        if rules is None:
            raise ValueError("合约下单规则尚未加载。")
        protection_mode = self._policy.get("protection_mode")
        if protection_mode == "NET_ROI_STRUCTURAL":
            stop_price, take_price, expected_stop_roi = self._trade_plan(
                config,
                signal,
                entry,
                stop_reference or Decimal("0"),
                signal_row,
            )
        elif protection_mode == "NET_ROI_FIXED":
            stop_price, take_price, expected_stop_roi = self._fixed_roi_plan(config, signal, entry)
        else:
            stop_rate = _decimal(config.stop_loss_pct) / Decimal("100")
            take_rate = _decimal(config.take_profit_pct) / Decimal("100")
            if signal > 0:
                stop_price = rules.price(entry * (Decimal("1") - stop_rate))
                take_price = rules.price(entry * (Decimal("1") + take_rate), "up")
            else:
                stop_price = rules.price(entry * (Decimal("1") + stop_rate), "up")
                take_price = rules.price(entry * (Decimal("1") - take_rate))
            expected_stop_roi = -config.stop_loss_pct * config.leverage
        expected_take_roi = float(self._net_roi_pct(config, signal, entry, take_price))
        exit_side = "SELL" if signal > 0 else "BUY"
        self.client.new_algo_order(
            config.symbol,
            exit_side,
            "STOP_MARKET",
            _decimal_string(stop_price),
            position_side="BOTH",
            close_position=True,
            working_type="MARK_PRICE",
            client_algo_id=self._client_id("sl"),
        )
        self.client.new_algo_order(
            config.symbol,
            exit_side,
            "TAKE_PROFIT_MARKET",
            _decimal_string(take_price),
            position_side="BOTH",
            close_position=True,
            working_type="MARK_PRICE",
            client_algo_id=self._client_id("tp"),
        )
        self._protection_orders = 2
        self._active_stop_price = stop_price
        self._active_take_price = take_price
        self._log(
            "success",
            "PROTECT",
            (
                f"交易所保护单已挂：止损 {_decimal_string(stop_price)}"
                f"（预计净 ROI {expected_stop_roi:.2f}%） / 止盈 {_decimal_string(take_price)}"
                f"（预计净 ROI {expected_take_roi:.2f}%）"
            ),
        )

    def _flatten(self, symbol: str, action: str) -> None:
        self._cancel_owned_algo_orders(symbol)
        self._cancel_owned_regular_orders(symbol)
        amount = self._position_amount(symbol)
        if amount != 0:
            self.client.new_order(
                symbol,
                "SELL" if amount > 0 else "BUY",
                order_type="MARKET",
                quantity=_decimal_string(abs(amount)),
                position_side="BOTH",
                reduce_only=True,
                client_order_id=self._client_id("emergency"),
                new_order_resp_type="RESULT",
                test=False,
            )
            self._wait_for_flat(symbol)
            self._log("warning", action, "Demo 持仓已市价平仓")
        self._cancel_owned_algo_orders(symbol)
        self._cancel_owned_regular_orders(symbol)
        self._managed_direction = 0
        self._protection_orders = 0
        self._active_stop_price = Decimal("0")
        self._active_take_price = Decimal("0")
        self._entry_wallet_balance = Decimal("0")

    def _latest_closed_frame(self, config: AutomationConfig, strategy=None):
        selected_strategy = strategy or get_strategy(config.strategy_id)
        interval = selected_strategy.execution_interval(config.interval)
        frame = fetch_klines(self.client, config.symbol, interval, selected_strategy.history_limit)
        now = datetime.now(timezone.utc)
        closed = frame[frame["close_time"] <= now]
        if closed.empty:
            raise ValueError("暂时没有已收盘 K 线。")
        return closed

    def _latest_closed_context(
        self,
        config: AutomationConfig,
        strategy,
        execution_frame=None,
    ) -> StrategyContext:
        now = datetime.now(timezone.utc)
        execution_interval = strategy.execution_interval(config.interval)
        frames = {execution_interval: execution_frame} if execution_frame is not None else {}
        for interval in strategy.market_intervals(config.interval):
            if interval in frames:
                continue
            frame = fetch_klines(self.client, config.symbol, interval, strategy.history_limit)
            closed = frame[frame["close_time"] <= now]
            if closed.empty:
                raise ValueError(f"{interval} 暂时没有已收盘 K 线。")
            frames[interval] = closed
        long_ratio = self._target_price_ratio(config, 1)
        short_ratio = self._target_price_ratio(config, -1)
        target_fraction = max(long_ratio - Decimal("1"), Decimal("1") - short_ratio)
        return StrategyContext(
            frames=frames,
            execution_interval=execution_interval,
            metadata={"target_price_fraction": float(target_fraction)},
        )

    def _trade_plan(
        self,
        config: AutomationConfig,
        signal: int,
        entry: Decimal,
        stop_reference: Decimal,
        signal_row: dict[str, Any] | None = None,
    ) -> tuple[Decimal, Decimal, float]:
        rules = self._rules
        if rules is None:
            raise ValueError("合约下单规则尚未加载。")
        if entry <= 0 or stop_reference <= 0:
            raise ValueError("策略没有给出有效的结构止损，本次不入场。")
        if signal > 0:
            if stop_reference >= entry:
                raise ValueError("多单结构止损不在入场价下方，本次不入场。")
            stop_price = rules.price(stop_reference, "down")
            take_price = rules.price(entry * self._target_price_ratio(config, signal), "up")
        else:
            if stop_reference <= entry:
                raise ValueError("空单结构止损不在入场价上方，本次不入场。")
            stop_price = rules.price(stop_reference, "up")
            take_price = rules.price(entry * self._target_price_ratio(config, signal), "down")

        stop_roi = self._net_roi_pct(config, signal, entry, stop_price)
        if stop_roi < -_decimal(config.stop_loss_pct):
            raise ValueError(
                f"结构止损预计净 ROI {float(stop_roi):.2f}%，超过 -{config.stop_loss_pct:.1f}% 上限，本次不入场。"
            )

        row = signal_row or {}
        if signal > 0:
            resistance = _decimal(row.get("resistance_level"))
            if resistance > entry and take_price >= resistance:
                raise ValueError("上方压力位不足以覆盖净止盈目标，本次不入场。")
        else:
            support = _decimal(row.get("support_level"))
            if Decimal("0") < support < entry and take_price <= support:
                raise ValueError("下方支撑位不足以覆盖净止盈目标，本次不入场。")
        return stop_price, take_price, float(stop_roi)

    def _fixed_roi_plan(
        self,
        config: AutomationConfig,
        signal: int,
        entry: Decimal,
    ) -> tuple[Decimal, Decimal, float]:
        rules = self._rules
        if rules is None:
            raise ValueError("合约下单规则尚未加载。")
        stop_ratio = self._price_ratio_for_roi(config, signal, -_decimal(config.stop_loss_pct))
        take_ratio = self._price_ratio_for_roi(config, signal, _decimal(config.take_profit_pct))
        if signal > 0:
            stop_price = rules.price(entry * stop_ratio, "up")
            take_price = rules.price(entry * take_ratio, "up")
            if stop_price >= entry or take_price <= entry:
                raise ValueError("净 ROI 保护价格无效，本次不入场。")
        else:
            stop_price = rules.price(entry * stop_ratio, "down")
            take_price = rules.price(entry * take_ratio, "down")
            if stop_price <= entry or take_price >= entry:
                raise ValueError("净 ROI 保护价格无效，本次不入场。")
        return stop_price, take_price, float(self._net_roi_pct(config, signal, entry, stop_price))

    def _target_price_ratio(self, config: AutomationConfig, signal: int) -> Decimal:
        return self._price_ratio_for_roi(config, signal, _decimal(config.take_profit_pct))

    def _price_ratio_for_roi(
        self,
        config: AutomationConfig,
        signal: int,
        target_roi_pct: Decimal,
    ) -> Decimal:
        target_per_notional = target_roi_pct / Decimal("100") / Decimal(config.leverage)
        entry_fee = self._maker_rate if self._policy.get("entry_order") == "MAKER_GTX" else self._taker_rate
        exit_fee = self._taker_rate
        slippage = _decimal(self._policy.get("exit_slippage_bps")) / Decimal("10000")
        if signal > 0:
            return (Decimal("1") + entry_fee + slippage + target_per_notional) / (
                Decimal("1") - exit_fee
            )
        return (Decimal("1") - entry_fee - slippage - target_per_notional) / (
            Decimal("1") + exit_fee
        )

    def _net_roi_pct(
        self,
        config: AutomationConfig,
        signal: int,
        entry: Decimal,
        exit_price: Decimal,
    ) -> Decimal:
        ratio = exit_price / entry
        entry_fee = self._maker_rate if self._policy.get("entry_order") == "MAKER_GTX" else self._taker_rate
        exit_fee = self._taker_rate
        slippage = _decimal(self._policy.get("exit_slippage_bps")) / Decimal("10000")
        if signal > 0:
            net_notional_return = ratio - Decimal("1") - entry_fee - exit_fee * ratio - slippage
        else:
            net_notional_return = Decimal("1") - ratio - entry_fee - exit_fee * ratio - slippage
        return net_notional_return * Decimal(config.leverage) * Decimal("100")

    def _load_commission_rates(self, symbol: str) -> tuple[Decimal, Decimal, str]:
        try:
            payload = self.client.commission_rate(symbol)
            maker = _decimal(payload.get("makerCommissionRate"), "0.0002")
            taker = _decimal(payload.get("takerCommissionRate"), "0.0005")
            if abs(maker) >= Decimal("0.01") or taker < 0 or taker >= Decimal("0.01"):
                raise ValueError("账户费率返回值无效。")
            return maker, taker, "账户实际费率"
        except Exception:
            return Decimal("0.0002"), Decimal("0.0005"), "保守默认值"

    def _position_amount(self, symbol: str) -> Decimal:
        payload = self.client.position_risk(symbol)
        positions = payload if isinstance(payload, list) else [payload]
        item = next((entry for entry in positions if entry.get("symbol") == symbol), {})
        return _decimal(item.get("positionAmt"))

    def _wait_for_position(self, symbol: str, signal: int) -> dict[str, Any]:
        for _ in range(6):
            payload = self.client.position_risk(symbol)
            positions = payload if isinstance(payload, list) else [payload]
            item = next((entry for entry in positions if entry.get("symbol") == symbol), {})
            amount = _decimal(item.get("positionAmt"))
            if (signal > 0 and amount > 0) or (signal < 0 and amount < 0):
                return item
            time.sleep(0.35)
        raise ValueError("市价开仓后未能确认持仓，已触发安全平仓。")

    def _wait_for_position_optional(
        self,
        symbol: str,
        signal: int,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.25, timeout_seconds)
        while time.monotonic() < deadline:
            payload = self.client.position_risk(symbol)
            positions = payload if isinstance(payload, list) else [payload]
            item = next((entry for entry in positions if entry.get("symbol") == symbol), {})
            amount = _decimal(item.get("positionAmt"))
            if (signal > 0 and amount > 0) or (signal < 0 and amount < 0):
                return item
            time.sleep(0.25)
        return None

    def _wait_for_flat(self, symbol: str) -> None:
        for _ in range(6):
            if self._position_amount(symbol) == 0:
                return
            time.sleep(0.35)
        raise ValueError("市价平仓后仍检测到持仓，请立即在 Binance Demo 检查。")

    def _cancel_owned_algo_orders(self, symbol: str) -> None:
        orders = self.client.current_algo_open_orders(symbol) or []
        for order in orders:
            client_id = str(order.get("clientAlgoId") or "")
            if not client_id.startswith(CLIENT_ID_PREFIX):
                continue
            try:
                algo_id = order.get("algoId")
                if algo_id is not None:
                    self.client.cancel_algo_order(algo_id=algo_id)
                else:
                    self.client.cancel_algo_order(client_algo_id=client_id)
            except BinanceAPIError as exc:
                code = exc.payload.get("code") if isinstance(exc.payload, dict) else None
                if code not in {-2011, -2013}:
                    raise
        self._protection_orders = 0

    def _cancel_regular_order(self, symbol: str, client_order_id: str) -> None:
        try:
            self.client.cancel_order(symbol, client_order_id=client_order_id)
        except BinanceAPIError as exc:
            code = exc.payload.get("code") if isinstance(exc.payload, dict) else None
            if code not in {-2011, -2013}:
                raise

    def _cancel_owned_regular_orders(self, symbol: str) -> None:
        orders = self.client.current_open_orders(symbol) or []
        for order in orders:
            client_id = str(order.get("clientOrderId") or order.get("origClientOrderId") or "")
            if not client_id.startswith(CLIENT_ID_PREFIX):
                continue
            try:
                order_id = order.get("orderId")
                if order_id is not None:
                    self.client.cancel_order(symbol, order_id=order_id)
                else:
                    self.client.cancel_order(symbol, client_order_id=client_id)
            except BinanceAPIError as exc:
                code = exc.payload.get("code") if isinstance(exc.payload, dict) else None
                if code not in {-2011, -2013}:
                    raise

    def _record_trade_exit(self, account: dict[str, Any]) -> None:
        wallet = self._wallet_balance(account)
        pnl = wallet - self._entry_wallet_balance if self._entry_wallet_balance else Decimal("0")
        if self._entry_wallet_balance and pnl < 0:
            self._consecutive_losses += 1
            self._log(
                "warning",
                "LOSS",
                f"本笔已实现 {float(pnl):+.4f} USDT，连续亏损 {self._consecutive_losses} 次",
            )
        elif self._entry_wallet_balance:
            self._consecutive_losses = 0
            self._log("success", "WIN", f"本笔已实现 {float(pnl):+.4f} USDT")
        self._entry_wallet_balance = Decimal("0")
        self._cooldown_candles = int(self._policy.get("cooldown_candles", 0))
        maximum_losses = int(self._policy.get("max_consecutive_losses", 0))
        if maximum_losses and self._consecutive_losses >= maximum_losses:
            minutes = int(self._policy.get("loss_pause_minutes", 30))
            self._pause_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            self._log("error", "LOSS_PAUSE", f"连续亏损 {maximum_losses} 次，暂停 {minutes} 分钟")

    def _owned_algo_order_count(self, symbol: str) -> int:
        orders = self.client.current_algo_open_orders(symbol) or []
        return sum(
            1
            for order in orders
            if str(order.get("clientAlgoId") or "").startswith(CLIENT_ID_PREFIX)
        )

    @staticmethod
    def _margin_balance(account: dict[str, Any]) -> Decimal:
        return _decimal(account.get("totalMarginBalance") or account.get("totalWalletBalance"))

    @staticmethod
    def _wallet_balance(account: dict[str, Any]) -> Decimal:
        return _decimal(account.get("totalWalletBalance") or account.get("totalMarginBalance"))

    @staticmethod
    def _client_id(label: str) -> str:
        return f"{CLIENT_ID_PREFIX}{int(time.time() * 1000)}_{label}"[:36]

    @staticmethod
    def _signal_label(signal: int) -> str:
        return {1: "做多", 0: "空仓", -1: "做空"}.get(signal, "未知")

    def _log(self, level: str, action: str, message: str) -> None:
        with self._lock:
            self._log_locked(level, action, message)

    def _log_locked(self, level: str, action: str, message: str) -> None:
        self._logs.appendleft(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "action": action,
                "message": message,
            }
        )
