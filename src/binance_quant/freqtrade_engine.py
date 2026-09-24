from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.request import getproxies

from .portfolio import PortfolioConfig
from .strategy_registry import APP_SUPPORT_DIR


FREQTRADE_DIR = APP_SUPPORT_DIR / "freqtrade"
FREQTRADE_RUNTIME = APP_SUPPORT_DIR / "freqtrade-runtime"


def _subprocess_environment() -> dict[str, str]:
    """Pass macOS system proxy settings to command-line sidecars."""
    environment = os.environ.copy()
    proxies = getproxies()
    for proxy_name, environment_name in (
        ("http", "HTTP_PROXY"),
        ("https", "HTTPS_PROXY"),
        ("all", "ALL_PROXY"),
        ("no", "NO_PROXY"),
    ):
        lower_name = environment_name.lower()
        if environment.get(environment_name) or environment.get(lower_name):
            continue
        value = proxies.get(proxy_name)
        if value:
            environment[environment_name] = value
            environment[lower_name] = value
    return environment


def _network_error(logs: list[str]) -> str:
    recent = "\n".join(logs[-60:])
    network_markers = (
        "ExchangeNotAvailable",
        "NetworkError",
        "RequestTimeout",
        "SSLError",
        "Markets were not loaded",
    )
    if "binance.com" in recent and any(marker in recent for marker in network_markers):
        return "无法连接 Binance Futures 公网接口，请检查当前网络或代理后重试。"
    return ""


def _pair_for_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", normalized):
        raise ValueError("回测合约必须是 USDT 永续合约。")
    return f"{normalized[:-4]}/USDT:USDT"


class FreqtradeEngine:
    """Local Freqtrade sidecar used for backtesting and isolated dry-run research."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._trade_thread: threading.Thread | None = None
        self._trade_process: subprocess.Popen[str] | None = None
        self._trade_stop_event = threading.Event()
        self._status = "idle"
        self._reason = "准备就绪"
        self._started_at = ""
        self._finished_at = ""
        self._logs: list[str] = []
        self._result: dict[str, Any] | None = None
        self._last_error = ""
        self._trade_status = "stopped"
        self._trade_reason = "独立 Dry-run 未启动"
        self._trade_logs: list[str] = []
        self._trade_error = ""
        self._trade_timer: threading.Timer | None = None
        self._trade_deadline = ""
        self._active_portfolio: dict[str, Any] | None = None
        self._strategy_class = 'Strategy1'
        self.ensure_workspace()

    @property
    def config_path(self) -> Path:
        return FREQTRADE_DIR / "config.json"

    @property
    def strategy_path(self) -> Path:
        return FREQTRADE_DIR / "strategies" / "Strategy1.py"

    @property
    def result_dir(self) -> Path:
        return FREQTRADE_DIR / "backtest_results"

    def executable(self) -> Path | None:
        candidates = [
            os.getenv("FREQTRADE_BIN", "").strip(),
            str(FREQTRADE_RUNTIME / "bin" / "freqtrade"),
            shutil.which("freqtrade") or "",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
                return Path(candidate)
        return None

    def ensure_workspace(self) -> None:
        (FREQTRADE_DIR / "strategies").mkdir(parents=True, exist_ok=True)
        (FREQTRADE_DIR / "data").mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        for name in ('upstream_GeneticEngineV1', 'upstream_TrendFollowingStrategyV2', 'upstream_EwoMomentumV1', 'community_adapters'):
            source = resources.read_text('binance_quant.resources', name + '.py.txt', encoding='utf-8')
            (FREQTRADE_DIR / 'strategies' / (name + '.py')).write_text(source, encoding='utf-8')
        strategy_source = resources.read_text(
            "binance_quant.resources",
            "freqtrade_strategy1.py.txt",
            encoding="utf-8",
        )
        if not self.strategy_path.exists():
            self.strategy_path.write_text(strategy_source, encoding="utf-8")
        if not self.config_path.exists():
            self._write_config("BTCUSDT", 5000.0)

    def _write_config(
        self,
        symbol: str | list[str],
        initial_capital: float,
        *,
        initial_state: str = "stopped",
        max_open_trades: int | None = None,
        projects: list[dict[str, Any]] | None = None,
        strategy_class: str = "Strategy1",
    ) -> None:
        symbols = [symbol] if isinstance(symbol, str) else symbol
        pairs = [_pair_for_symbol(item) for item in symbols]
        project_map = {
            _pair_for_symbol(str(project["symbol"])): {
                "project_id": project.get("project_id", ""),
                "budget": float(project.get("budget", initial_capital)),
                "initial_stake": float(project.get("initial_stake", 50)),
                "leverage": int(project.get("leverage", 20)),
            }
            for project in (projects or [])
        }
        config = {
            "$schema": "https://schema.freqtrade.io/schema.json",
            "max_open_trades": max_open_trades or 1,
            "stake_currency": "USDT",
            "stake_amount": "unlimited",
            "tradable_balance_ratio": 1.0 if projects else 0.05,
            "fiat_display_currency": "USD",
            "dry_run": True,
            "dry_run_wallet": initial_capital,
            "db_url": f"sqlite:///{FREQTRADE_DIR / 'tradesv3.dryrun.sqlite'}",
            "cancel_open_orders_on_exit": True,
            "timeframe": "5m" if strategy_class.startswith('Angel') else "1m",
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "unfilledtimeout": {"entry": 10, "exit": 10, "exit_timeout_count": 0, "unit": "seconds"},
            "entry_pricing": {
                "price_side": "other",
                "use_order_book": True,
                "order_book_top": 1,
                "price_last_balance": 0.0,
                "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
            },
            "exit_pricing": {
                "price_side": "other",
                "use_order_book": True,
                "order_book_top": 1,
                "price_last_balance": 0.0,
            },
            "exchange": {
                "name": "binance",
                "key": "",
                "secret": "",
                "ccxt_config": {
                    "enableRateLimit": True,
                    "trust_env": True,
                    "requests_trust_env": True,
                    "options": {
                        "fetchCurrencies": False,
                        "fetchMarkets": {"types": ["linear"]},
                    },
                },
                "ccxt_async_config": {
                    "enableRateLimit": True,
                    "trust_env": True,
                    "aiohttp_trust_env": True,
                    "options": {
                        "fetchCurrencies": False,
                        "fetchMarkets": {"types": ["linear"]},
                    },
                },
                "pair_whitelist": pairs,
                "pair_blacklist": [],
            },
            "pairlists": [{"method": "StaticPairList"}],
            "telegram": {"enabled": False, "token": "", "chat_id": ""},
            "api_server": {
                "enabled": False,
                "listen_ip_address": "127.0.0.1",
                "listen_port": 8080,
                "verbosity": "error",
                "enable_openapi": False,
                "jwt_secret_key": "local-backtest-only-change-me-123456789",
                "CORS_origins": [],
                "username": "bq",
                "password": "local-backtest-only",
            },
            "bot_name": "Angel Quant Strategy1",
            "initial_state": initial_state,
            "force_entry_enable": False,
            "internals": {"process_throttle_secs": 1},
            "strategy": strategy_class,
            "dataformat_ohlcv": "feather",
            "bq_projects": project_map,
        }
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._strategy_class = strategy_class

    def status(self) -> dict[str, Any]:
        executable = self.executable()
        with self._lock:
            return {
                "available": executable is not None,
                "executable": str(executable) if executable else "",
                "workspace": str(FREQTRADE_DIR),
                "strategy": self._strategy_class,
                "strategy_name": {'AngelGenetic': 'GeneticEngineV1 · 因果修正版', 'AngelTrend': 'TrendFollowingV2 · 趋势跟随', 'AngelEwo': 'EwoMomentumV1 · 动量回调'}.get(self._strategy_class, '策略1'),
                "execution_mode": "DRY_RUN_ONLY",
                "running": self._status in {"downloading", "backtesting"},
                "status": self._status if executable else "unavailable",
                "reason": self._reason if executable else "Freqtrade 本地引擎未安装",
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "last_error": self._last_error,
                "logs": list(self._logs[-30:]),
                "result": dict(self._result) if self._result else None,
                "dry_run": {
                    "running": self._trade_status in {"starting", "running", "stopping"},
                    "status": self._trade_status,
                    "reason": self._trade_reason,
                    "last_error": self._trade_error,
                    "logs": list(self._trade_logs[-30:]),
                    "deadline": self._trade_deadline,
                    "portfolio": dict(self._active_portfolio) if self._active_portfolio else None,
                },
            }

    def start_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            raise ValueError("Freqtrade 本地引擎未安装。")
        symbol = str(payload.get("symbol", "BTCUSDT")).strip().upper()
        days = int(payload.get("days", 30))
        initial_capital = float(payload.get("initial_capital", 5000))
        _pair_for_symbol(symbol)
        if days < 2 or days > 365:
            raise ValueError("回测天数必须在 2 到 365 之间。")
        if initial_capital < 100 or initial_capital > 10_000_000:
            raise ValueError("回测初始资金必须在 100 到 10000000 USDT 之间。")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("Freqtrade 回测正在运行。")
            if self._trade_thread and self._trade_thread.is_alive():
                raise ValueError("请先停止 Freqtrade Dry-run，再运行回测。")
            self._write_config(symbol, initial_capital)
            self._status = "downloading"
            self._reason = "正在下载 Binance 历史 K 线"
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._finished_at = ""
            self._logs = []
            self._result = None
            self._last_error = ""
            self._thread = threading.Thread(
                target=self._run_backtest,
                args=(executable, symbol, days, initial_capital),
                name="bq-freqtrade-backtest",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def start_portfolio_backtest(
        self,
        portfolio: PortfolioConfig,
        strategy_class: str = "Strategy1",
    ) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            raise ValueError("Freqtrade本地引擎未安装。")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", strategy_class):
            raise ValueError("Freqtrade策略类名格式无效。")
        projects = [project.to_dict() for project in portfolio.active_projects]
        symbols = [project.symbol for project in portfolio.active_projects]
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("Freqtrade回测正在运行。")
            if self._trade_thread and self._trade_thread.is_alive():
                raise ValueError("请先停止Freqtrade Dry-run，再运行回测。")
            self._write_config(
                symbols,
                portfolio.initial_capital,
                max_open_trades=portfolio.max_concurrent_positions,
                projects=projects,
                strategy_class=strategy_class,
            )
            self._status = "downloading"
            self._reason = f"正在下载{len(symbols)}个项目的历史K线"
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._finished_at = ""
            self._logs = []
            self._result = None
            self._last_error = ""
            self._thread = threading.Thread(
                target=self._run_portfolio_backtest,
                args=(executable, portfolio, strategy_class),
                name="angel-quant-portfolio-backtest",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def start_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            raise ValueError("Freqtrade 本地引擎未安装。")
        symbol = str(payload.get("symbol", "BTCUSDT")).strip().upper()
        initial_capital = float(payload.get("initial_capital", 5000))
        _pair_for_symbol(symbol)
        if initial_capital < 100 or initial_capital > 10_000_000:
            raise ValueError("Dry-run 初始资金必须在 100 到 10000000 USDT 之间。")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("请等待 Freqtrade 回测结束。")
            if self._trade_thread and self._trade_thread.is_alive():
                raise ValueError("Freqtrade Dry-run 已在运行。")
            self._write_config(symbol, initial_capital, initial_state="running")
            self._trade_status = "starting"
            self._trade_reason = f"正在启动 {symbol} 策略1 Dry-run"
            self._trade_logs = []
            self._trade_error = ""
            self._trade_deadline = ""
            self._active_portfolio = None
            self._trade_stop_event.clear()
            self._trade_thread = threading.Thread(
                target=self._run_dry_run,
                args=(executable,),
                name="bq-freqtrade-dry-run",
                daemon=True,
            )
            self._trade_thread.start()
        return self.status()

    def start_portfolio_dry_run(
        self,
        portfolio: PortfolioConfig,
        strategy_class: str = "Strategy1",
    ) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            raise ValueError("Freqtrade本地引擎未安装。")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", strategy_class):
            raise ValueError("Freqtrade策略类名格式无效。")
        projects = [project.to_dict() for project in portfolio.active_projects]
        symbols = [project.symbol for project in portfolio.active_projects]
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("请等待Freqtrade回测结束。")
            if self._trade_thread and self._trade_thread.is_alive():
                raise ValueError("Freqtrade Dry-run已在运行。")
            self._write_config(
                symbols,
                portfolio.initial_capital,
                initial_state="running",
                max_open_trades=portfolio.max_concurrent_positions,
                projects=projects,
                strategy_class=strategy_class,
            )
            self._trade_status = "starting"
            self._trade_reason = f"正在启动{portfolio.name}模拟实测"
            self._trade_logs = []
            self._trade_error = ""
            self._active_portfolio = portfolio.to_dict()
            deadline = datetime.now(timezone.utc) + timedelta(days=portfolio.run_days)
            self._trade_deadline = deadline.isoformat()
            self._trade_stop_event.clear()
            self._trade_thread = threading.Thread(
                target=self._run_dry_run,
                args=(executable,),
                name="angel-quant-portfolio-dry-run",
                daemon=True,
            )
            self._trade_thread.start()
            self._trade_timer = threading.Timer(portfolio.run_days * 86400, self.stop_dry_run)
            self._trade_timer.daemon = True
            self._trade_timer.start()
        return self.status()

    def stop_dry_run(self) -> dict[str, Any]:
        with self._lock:
            timer = self._trade_timer
            self._trade_timer = None
            if timer:
                timer.cancel()
            process = self._trade_process
            thread = self._trade_thread
            if not thread or not thread.is_alive():
                self._trade_status = "stopped"
                self._trade_reason = "独立 Dry-run 未启动"
                self._trade_deadline = ""
                return self.status()
            self._trade_status = "stopping"
            self._trade_reason = "正在停止 Freqtrade Dry-run"
            self._trade_stop_event.set()
        if process and process.poll() is None:
            process.terminate()
        return self.status()

    def _append_log(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        with self._lock:
            self._logs.append(cleaned[-500:])
            if len(self._logs) > 200:
                del self._logs[:-200]

    def _append_trade_log(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        with self._lock:
            self._trade_logs.append(cleaned[-500:])
            if len(self._trade_logs) > 200:
                del self._trade_logs[:-200]

    def _run_dry_run(self, executable: Path) -> None:
        try:
            strategy_class = str(json.loads(self.config_path.read_text(encoding="utf-8")).get("strategy") or "Strategy1")
        except (OSError, ValueError):
            strategy_class = "Strategy1"
        command = [
            str(executable),
            "trade",
            "--config",
            str(self.config_path),
            "--userdir",
            str(FREQTRADE_DIR),
            "--strategy",
            strategy_class,
            "--dry-run",
        ]
        try:
            if self._trade_stop_event.is_set():
                with self._lock:
                    self._trade_status = "stopped"
                    self._trade_reason = "独立 Dry-run 已停止"
                return
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_subprocess_environment(),
            )
            with self._lock:
                self._trade_process = process
                if self._trade_stop_event.is_set():
                    self._trade_status = "stopping"
                    self._trade_reason = "正在停止 Freqtrade Dry-run"
                else:
                    self._trade_status = "running"
                    self._trade_reason = "策略1 Dry-run 运行中（独立模拟钱包）"
            if self._trade_stop_event.is_set():
                process.terminate()
            assert process.stdout is not None
            for line in process.stdout:
                self._append_trade_log(line)
            return_code = process.wait()
            with self._lock:
                stopping = self._trade_status == "stopping"
                if return_code and not stopping:
                    self._trade_status = "error"
                    self._trade_reason = "Freqtrade Dry-run 异常退出"
                    self._trade_error = (
                        _network_error(self._trade_logs)
                        or (self._trade_logs[-1] if self._trade_logs else f"exit code {return_code}")
                    )
                else:
                    self._trade_status = "stopped"
                    self._trade_reason = "独立 Dry-run 已停止"
        except Exception as exc:
            with self._lock:
                self._trade_status = "error"
                self._trade_reason = "Freqtrade Dry-run 启动失败"
                self._trade_error = str(exc)
        finally:
            with self._lock:
                self._trade_process = None

    def shutdown(self) -> None:
        with self._lock:
            if self._trade_timer:
                self._trade_timer.cancel()
                self._trade_timer = None
            self._trade_stop_event.set()
            if self._trade_process and self._trade_process.poll() is None:
                self._trade_status = "stopping"
            processes = [self._trade_process, self._process]
        for process in processes:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _run_command(self, command: list[str]) -> None:
        with self._lock:
            first_log_index = len(self._logs)
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_subprocess_environment(),
            )
            process = self._process
        assert process.stdout is not None
        for line in process.stdout:
            self._append_log(line)
        return_code = process.wait()
        with self._lock:
            self._process = None
            command_logs = self._logs[first_log_index:]
        fatal_log = next((line for line in reversed(command_logs) if " - ERROR - " in line), "")
        if return_code or fatal_log:
            tail = fatal_log or (command_logs[-1] if command_logs else f"exit code {return_code}")
            network_error = _network_error(command_logs)
            if network_error:
                raise ValueError(network_error)
            raise ValueError(tail)

    def _run_backtest(
        self,
        executable: Path,
        symbol: str,
        days: int,
        initial_capital: float,
    ) -> None:
        pair = _pair_for_symbol(symbol)
        before = set(self.result_dir.glob("*"))
        try:
            self._run_command([
                str(executable),
                "download-data",
                "--config",
                str(self.config_path),
                "--userdir",
                str(FREQTRADE_DIR),
                "--days",
                str(days + 4),
                "--timeframes",
                "1m",
                "5m",
                "15m",
                "--trading-mode",
                "futures",
                "--pairs",
                pair,
            ])
            with self._lock:
                self._status = "backtesting"
                self._reason = "正在运行策略1回测"
            timerange = f"{(datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y%m%d')}-"
            self._run_command([
                str(executable),
                "backtesting",
                "--config",
                str(self.config_path),
                "--userdir",
                str(FREQTRADE_DIR),
                "--strategy",
                "Strategy1",
                "--timeframe",
                "1m",
                "--timerange",
                timerange,
                "--dry-run-wallet",
                str(initial_capital),
                "--export",
                "trades",
                "--backtest-directory",
                str(self.result_dir),
                "--cache",
                "none",
            ])
            created = [path for path in self.result_dir.glob("*") if path not in before]
            candidates = sorted(created or list(self.result_dir.glob("*")), key=lambda path: path.stat().st_mtime)
            result = self._parse_latest_result(candidates, symbol, days, initial_capital)
            with self._lock:
                self._result = result
                self._status = "completed"
                self._reason = "回测完成"
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._reason = "回测失败"
                self._last_error = str(exc)
        finally:
            with self._lock:
                self._finished_at = datetime.now(timezone.utc).isoformat()

    def _run_portfolio_backtest(
        self,
        executable: Path,
        portfolio: PortfolioConfig,
        strategy_class: str,
    ) -> None:
        symbols = [project.symbol for project in portfolio.active_projects]
        pairs = [_pair_for_symbol(symbol) for symbol in symbols]
        before = set(self.result_dir.glob("*"))
        try:
            self._run_command([
                str(executable),
                "download-data",
                "--config",
                str(self.config_path),
                "--userdir",
                str(FREQTRADE_DIR),
                "--days",
                str(portfolio.run_days + 4),
                "--timeframes",
                *(['5m', '1h'] if strategy_class.startswith('Angel') else ['1m', '5m', '15m']),
                "--trading-mode",
                "futures",
                "--pairs",
                *pairs,
            ])
            with self._lock:
                self._status = "backtesting"
                self._reason = f"正在验证{portfolio.name}"
            timerange = f"{(datetime.now(timezone.utc) - timedelta(days=portfolio.run_days)).strftime('%Y%m%d')}-"
            self._run_command([
                str(executable),
                "backtesting",
                "--config",
                str(self.config_path),
                "--userdir",
                str(FREQTRADE_DIR),
                "--strategy",
                strategy_class,
                "--timeframe",
                "5m" if strategy_class.startswith('Angel') else "1m",
                "--timerange",
                timerange,
                "--dry-run-wallet",
                str(portfolio.initial_capital),
                "--export",
                "trades",
                "--backtest-directory",
                str(self.result_dir),
                "--cache",
                "none",
            ])
            created = [path for path in self.result_dir.glob("*") if path not in before]
            candidates = sorted(created or list(self.result_dir.glob("*")), key=lambda path: path.stat().st_mtime)
            result = self._parse_latest_result(
                candidates,
                symbols,
                portfolio.run_days,
                portfolio.initial_capital,
                portfolio=portfolio.to_dict(),
                strategy_class=strategy_class,
            )
            with self._lock:
                self._result = result
                self._status = "completed"
                self._reason = "组合回测完成"
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._reason = "组合回测失败"
                self._last_error = str(exc)
        finally:
            with self._lock:
                self._finished_at = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_result_payload(path: Path) -> dict[str, Any] | None:
        try:
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    names = [name for name in archive.namelist() if name.endswith(".json") and not name.endswith(".meta.json")]
                    if not names:
                        return None
                    return json.loads(archive.read(names[0]).decode("utf-8"))
            if path.suffix == ".json" and not path.name.endswith(".meta.json"):
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, zipfile.BadZipFile):
            return None
        return None

    def _parse_latest_result(
        self,
        candidates: list[Path],
        symbol: str | list[str],
        days: int,
        initial_capital: float,
        portfolio: dict[str, Any] | None = None,
        strategy_class: str = "Strategy1",
    ) -> dict[str, Any]:
        for path in reversed(candidates):
            payload = self._read_result_payload(path)
            strategy = (payload or {}).get("strategy", {}).get(strategy_class)
            if not isinstance(strategy, dict):
                continue
            trades = int(strategy.get("total_trades") or len(strategy.get("trades") or []))
            wins = int(strategy.get("wins") or 0)
            profit_fraction = float(strategy.get("profit_total") or 0)
            drawdown_fraction = float(
                strategy.get("max_drawdown_account")
                or strategy.get("max_drawdown")
                or 0
            )
            raw_trades = strategy.get("trades") or []
            winning_abs = [float(trade.get("profit_abs") or 0) for trade in raw_trades if float(trade.get("profit_abs") or 0) > 0]
            losing_abs = [float(trade.get("profit_abs") or 0) for trade in raw_trades if float(trade.get("profit_abs") or 0) < 0]
            average_win = sum(winning_abs) / len(winning_abs) if winning_abs else 0.0
            average_loss = abs(sum(losing_abs) / len(losing_abs)) if losing_abs else 0.0
            fees = 0.0
            for trade in raw_trades:
                amount = float(trade.get("amount") or 0)
                fees += abs(amount * float(trade.get("open_rate") or 0) * float(trade.get("fee_open") or 0))
                fees += abs(amount * float(trade.get("close_rate") or 0) * float(trade.get("fee_close") or 0))
            daily_profit = strategy.get("daily_profit") or []
            balance = initial_capital
            equity_curve = []
            for item in daily_profit:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                balance += float(item[1] or 0)
                equity_curve.append({"date": str(item[0]), "balance": balance, "profit": float(item[1] or 0)})

            per_pair = []
            for item in strategy.get("results_per_pair") or []:
                if item.get("key") == "TOTAL":
                    continue
                pair_symbol = str(item.get("key", "")).split("/")[0] + "USDT"
                per_pair.append({
                    "symbol": pair_symbol,
                    "trades": int(item.get("trades") or 0),
                    "profit_abs": float(item.get("profit_total_abs") or 0),
                    "profit_pct": float(item.get("profit_total") or 0) * 100,
                    "win_rate_pct": float(item.get("winrate") or 0) * 100,
                    "profit_factor": float(item.get("profit_factor") or 0),
                    "max_drawdown_pct": float(item.get("max_drawdown_account") or 0) * 100,
                })

            exit_reasons = [
                {
                    "reason": str(item.get("key") or ""),
                    "trades": int(item.get("trades") or 0),
                    "profit_abs": float(item.get("profit_total_abs") or 0),
                    "profit_pct": float(item.get("profit_total") or 0) * 100,
                }
                for item in strategy.get("exit_reason_summary") or []
                if item.get("key") != "TOTAL"
            ]
            symbols = [symbol] if isinstance(symbol, str) else symbol
            return {
                "symbol": symbols[0] if len(symbols) == 1 else "PORTFOLIO",
                "symbols": symbols,
                "days": days,
                "initial_capital": initial_capital,
                "total_trades": trades,
                "wins": wins,
                "win_rate_pct": wins / trades * 100 if trades else 0.0,
                "profit_pct": profit_fraction * 100,
                "profit_abs": float(strategy.get("profit_total_abs") or 0),
                "max_drawdown_pct": drawdown_fraction * 100,
                "profit_factor": float(strategy.get("profit_factor") or 0),
                "expectancy": float(strategy.get("expectancy") or 0),
                "average_trade_pct": float(strategy.get("profit_mean") or 0) * 100,
                "average_win_abs": average_win,
                "average_loss_abs": average_loss,
                "payoff_ratio": average_win / average_loss if average_loss else 0.0,
                "estimated_fees": fees,
                "long": {
                    "trades": int(strategy.get("trade_count_long") or 0),
                    "profit_abs": float(strategy.get("profit_total_long_abs") or 0),
                    "profit_pct": float(strategy.get("profit_total_long") or 0) * 100,
                },
                "short": {
                    "trades": int(strategy.get("trade_count_short") or 0),
                    "profit_abs": float(strategy.get("profit_total_short_abs") or 0),
                    "profit_pct": float(strategy.get("profit_total_short") or 0) * 100,
                },
                "per_pair": per_pair,
                "exit_reasons": exit_reasons,
                "equity_curve": equity_curve,
                "portfolio": portfolio,
                "result_file": str(path),
            }
        raise ValueError("Freqtrade 已结束，但未找到可解析的回测结果。")
