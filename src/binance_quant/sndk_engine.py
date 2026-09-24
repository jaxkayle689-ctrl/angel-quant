from __future__ import annotations

import io
import json
import math
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .portfolio import PortfolioConfig
from .strategy_api import Strategy
from .strategy_registry import APP_SUPPORT_DIR


BINANCE_ARCHIVE_ROOT = "https://data.binance.vision/data/futures/um/daily/klines"
BINANCE_PUBLIC_ROOT = "https://www.binance.com/fapi/v1"
YAHOO_CHART_ROOT = "https://query1.finance.yahoo.com/v8/finance/chart"
SNDK_EQUITY_SYMBOL = "SNDK"
SNDK_FUTURES_SYMBOL = "SNDKUSDT"
NEW_YORK = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")
CACHE_ROOT = APP_SUPPORT_DIR / "market_data" / "sndk_hybrid"
RESULT_ROOT = APP_SUPPORT_DIR / "backtest_results" / "sndk_hybrid"


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc_series(values: pd.Series) -> pd.Series:
    """Parse cached ISO timestamps independently so mixed fractions remain portable."""

    def normalize(value: Any) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize(timezone.utc)
        return timestamp.tz_convert(timezone.utc)

    return values.map(normalize)


def _stats(trades: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    wins = [trade for trade in trades if trade["net_pnl"] > 0]
    losses = [trade for trade in trades if trade["net_pnl"] < 0]
    profit = sum(trade["net_pnl"] for trade in trades)
    gross_profit = sum(trade["net_pnl"] for trade in wins)
    gross_loss = -sum(trade["net_pnl"] for trade in losses)
    average_win = gross_profit / len(wins) if wins else 0.0
    average_loss = gross_loss / len(losses) if losses else 0.0
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_abs": profit,
        "profit_pct": profit / initial_capital * 100 if initial_capital else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0),
        "payoff_ratio": average_win / average_loss if average_loss else (999.0 if average_win else 0.0),
    }


class SNDKHybridBacktestEngine:
    """Historical-only SNDK cash-close signal and Binance equity-perp executor."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: dict[str, Any] = {
            "available": True,
            "engine": "sndk_hybrid",
            "running": False,
            "status": "idle",
            "reason": "SNDK跨市场验证引擎准备就绪",
            "started_at": "",
            "finished_at": "",
            "last_error": "",
            "logs": [],
            "result": None,
        }
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        RESULT_ROOT.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._status)
            payload["logs"] = list(self._status.get("logs", []))
            payload["dry_run"] = {
                "running": False,
                "status": "unsupported",
                "reason": "SNDK策略当前只允许历史验证",
                "logs": [],
            }
            return payload

    def _log(self, message: str) -> None:
        with self._lock:
            logs = list(self._status.get("logs", []))
            logs.append(message)
            self._status["logs"] = logs[-80:]
            self._status["reason"] = message

    @staticmethod
    def _request(url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "AngelQuant/0.7 historical-research"},
            timeout=30,
        )
        return response

    def _equity_daily(self, start: date, end: date) -> pd.DataFrame:
        cache_path = CACHE_ROOT / "SNDK-equity-daily.csv"
        query_start = start - timedelta(days=35)
        query_end = end + timedelta(days=10)
        period1 = int(datetime.combine(query_start, time(), timezone.utc).timestamp())
        period2 = int(datetime.combine(query_end + timedelta(days=1), time(), timezone.utc).timestamp())
        try:
            response = self._request(
                f"{YAHOO_CHART_ROOT}/{SNDK_EQUITY_SYMBOL}",
                params={
                    "period1": period1,
                    "period2": period2,
                    "interval": "1d",
                    "events": "div,splits",
                },
            )
            response.raise_for_status()
            chart = response.json().get("chart", {})
            errors = chart.get("error")
            results = chart.get("result") or []
            if errors or not results:
                raise ValueError(str(errors or "empty chart result"))
            data = results[0]
            quote = data["indicators"]["quote"][0]
            frame = pd.DataFrame(
                {
                    "open_time": pd.to_datetime(data["timestamp"], unit="s", utc=True),
                    "open": quote["open"],
                    "high": quote["high"],
                    "low": quote["low"],
                    "close": quote["close"],
                    "volume": quote["volume"],
                }
            ).dropna(subset=["open", "high", "low", "close"])
            frame["trading_date"] = frame["open_time"].dt.tz_convert(NEW_YORK).dt.date
            if cache_path.exists():
                cached = pd.read_csv(cache_path)
                cached["open_time"] = _utc_series(cached["open_time"])
                cached["trading_date"] = pd.to_datetime(cached["trading_date"]).dt.date
                frame = pd.concat((cached, frame), ignore_index=True)
            frame = frame.sort_values("open_time").drop_duplicates("trading_date", keep="last")
            frame.to_csv(cache_path, index=False)
        except Exception as exc:
            if not cache_path.exists():
                raise ValueError(f"无法下载SNDK正股日线：{exc}") from exc
            self._log("正股日线网络更新失败，使用本地缓存")
            frame = pd.read_csv(cache_path)
            frame["open_time"] = _utc_series(frame["open_time"])
            frame["trading_date"] = pd.to_datetime(frame["trading_date"]).dt.date

        frame = frame[(frame["trading_date"] >= query_start) & (frame["trading_date"] <= query_end)].copy()
        if frame.empty or max(frame["trading_date"]) < end - timedelta(days=7):
            raise ValueError("SNDK正股日线尚未覆盖所选验证结束日期。")
        return frame.reset_index(drop=True)

    def _futures_day(self, trading_day: date) -> pd.DataFrame:
        day_text = trading_day.isoformat()
        directory = CACHE_ROOT / "binance_vision" / SNDK_FUTURES_SYMBOL / "1m"
        directory.mkdir(parents=True, exist_ok=True)
        cache_path = directory / f"{SNDK_FUTURES_SYMBOL}-1m-{day_text}.zip"
        if not cache_path.exists():
            url = (
                f"{BINANCE_ARCHIVE_ROOT}/{SNDK_FUTURES_SYMBOL}/1m/"
                f"{SNDK_FUTURES_SYMBOL}-1m-{day_text}.zip"
            )
            response = self._request(url)
            if response.status_code == 404:
                raise ValueError(f"Binance官方归档尚无{day_text}的SNDKUSDT 1分钟K线。")
            response.raise_for_status()
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(cache_path)
        try:
            with zipfile.ZipFile(cache_path) as archive:
                names = archive.namelist()
                if len(names) != 1:
                    raise ValueError("archive member count")
                frame = pd.read_csv(io.BytesIO(archive.read(names[0])))
        except Exception as exc:
            raise ValueError(f"SNDKUSDT历史归档损坏：{cache_path.name}") from exc
        frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame[["open_time", "open", "high", "low", "close", "volume"]].dropna()

    def _futures_minutes(self, start: date, end: date) -> pd.DataFrame:
        days = _date_range(start, end)
        with ThreadPoolExecutor(max_workers=min(6, len(days))) as executor:
            frames = list(executor.map(self._futures_day, days))
        frame = pd.concat(frames, ignore_index=True).sort_values("open_time")
        return frame.drop_duplicates("open_time", keep="last").set_index("open_time")

    def _funding_rates(self, start: date, end: date) -> tuple[pd.DataFrame, str]:
        cache_path = CACHE_ROOT / "SNDKUSDT-funding.csv"
        start_ms = int(datetime.combine(start, time(), timezone.utc).timestamp() * 1000)
        end_ms = int(datetime.combine(end + timedelta(days=1), time(), timezone.utc).timestamp() * 1000) - 1
        source = "Binance Futures fundingRate API"
        try:
            response = self._request(
                f"{BINANCE_PUBLIC_ROOT}/fundingRate",
                params={
                    "symbol": SNDK_FUTURES_SYMBOL,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError(str(payload))
            frame = pd.DataFrame(payload)
            if not frame.empty:
                frame = frame.rename(
                    columns={"fundingTime": "funding_time", "fundingRate": "funding_rate", "markPrice": "mark_price"}
                )
                frame["funding_time"] = pd.to_datetime(frame["funding_time"], unit="ms", utc=True)
                frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
                frame["mark_price"] = pd.to_numeric(frame["mark_price"], errors="coerce")
                if cache_path.exists():
                    cached = pd.read_csv(cache_path)
                    cached["funding_time"] = _utc_series(cached["funding_time"])
                    frame = pd.concat((cached, frame), ignore_index=True)
                frame = frame.sort_values("funding_time").drop_duplicates("funding_time", keep="last")
                frame.to_csv(cache_path, index=False)
        except Exception:
            if cache_path.exists():
                source = "本地资金费缓存"
                frame = pd.read_csv(cache_path)
                frame["funding_time"] = _utc_series(frame["funding_time"])
                frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
                frame["mark_price"] = pd.to_numeric(frame["mark_price"], errors="coerce")
            else:
                source = "资金费不可用（按0计）"
                frame = pd.DataFrame(columns=["funding_time", "funding_rate", "mark_price"])
        if not frame.empty:
            start_time = pd.Timestamp(datetime.combine(start, time(), timezone.utc))
            end_time = pd.Timestamp(datetime.combine(end + timedelta(days=1), time(), timezone.utc))
            frame = frame[(frame["funding_time"] >= start_time) & (frame["funding_time"] < end_time)]
            frame = frame.set_index("funding_time").sort_index()
        return frame, source

    @staticmethod
    def _session_close(trading_day: date, delay_minutes: int) -> pd.Timestamp:
        local = datetime.combine(trading_day, time(16, 0), NEW_YORK) + timedelta(minutes=delay_minutes)
        return pd.Timestamp(local.astimezone(timezone.utc))

    @staticmethod
    def _after_hours_cutoff(trading_day: date) -> pd.Timestamp:
        regular_close = datetime.combine(trading_day, time(16, 0), NEW_YORK)
        shanghai_date = regular_close.astimezone(SHANGHAI).date()
        local = datetime.combine(shanghai_date, time(21, 0), SHANGHAI)
        return pd.Timestamp(local.astimezone(timezone.utc))

    def start_portfolio_backtest(self, portfolio: PortfolioConfig, strategy: Strategy) -> dict[str, Any]:
        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "status": "backtesting",
                    "reason": "正在准备SNDK跨市场历史数据",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "finished_at": "",
                    "last_error": "",
                    "logs": [],
                    "result": None,
                }
            )
        try:
            result = self._run(portfolio, strategy)
        except Exception as exc:
            with self._lock:
                self._status.update(
                    {
                        "running": False,
                        "status": "error",
                        "reason": "SNDK历史验证失败",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "last_error": str(exc),
                    }
                )
            raise
        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "status": "completed",
                    "reason": "SNDK跨市场历史验证完成",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": "",
                    "result": result,
                }
            )
        return self.status()

    def _run(self, portfolio: PortfolioConfig, strategy: Strategy) -> dict[str, Any]:
        projects = portfolio.active_projects
        if len(projects) != 1 or projects[0].symbol != SNDK_FUTURES_SYMBOL:
            raise ValueError("SNDK盘后策略只允许一个SNDKUSDT项目。")
        project = projects[0]
        if project.market != "equity_perpetual":
            raise ValueError("SNDK盘后策略必须使用Binance股票永续市场。")
        if project.leverage < 1 or project.leverage > 10:
            raise ValueError("SNDKUSDT当前验证杠杆必须在1到10倍之间。")

        parameters = strategy.normalized_parameters(portfolio.strategy_parameters)
        yesterday_utc = datetime.now(timezone.utc).date() - timedelta(days=1)
        equity_probe_start = yesterday_utc - timedelta(days=portfolio.run_days + 35)
        equity = self._equity_daily(equity_probe_start, yesterday_utc)
        end_date = min(max(equity["trading_date"]), yesterday_utc)
        start_date = end_date - timedelta(days=portfolio.run_days - 1)
        self._log(f"验证区间 {start_date.isoformat()} 至 {end_date.isoformat()}")
        futures = self._futures_minutes(start_date, end_date)
        self._log(f"已载入 {len(futures):,} 根SNDKUSDT 1分钟K线")
        funding, funding_source = self._funding_rates(start_date, end_date)
        signal_frame = strategy.generate(equity, parameters)
        signal_rows = signal_frame[
            (signal_frame["trading_date"] >= start_date)
            & (signal_frame["trading_date"] <= end_date)
            & (signal_frame["signal"] != 0)
        ]

        fee_rate = parameters["taker_fee_bps"] / 10_000
        slippage_rate = parameters["slippage_bps"] / 10_000
        take_profit_rate = parameters["take_profit_pct"] / 100
        stop_loss_rate = parameters["stop_loss_pct"] / 100
        project_balance = project.budget
        cash_reserve = portfolio.initial_capital - project.budget
        allocation_fraction = min(1.0, project.initial_stake / project.budget)
        account_peak = portfolio.initial_capital
        max_drawdown = 0.0
        trades: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for _, signal in signal_rows.iterrows():
            trading_day = signal["trading_date"]
            direction = int(signal["signal"])
            search_start = self._session_close(trading_day, parameters["entry_delay_minutes"])
            boundary = self._after_hours_cutoff(trading_day)
            window = futures[(futures.index >= search_start) & (futures.index < boundary)]
            if window.empty:
                skipped.append({"date": str(trading_day), "reason": "无盘后合约K线"})
                continue

            reference_close = float(signal["close"])
            entry_trigger_price: float | None = None
            if parameters["wait_for_pullback"]:
                pullback_rate = parameters["entry_pullback_pct"] / 100
                entry_trigger_price = reference_close * (1 - direction * pullback_rate)
                hit_mask = (
                    window["low"] <= entry_trigger_price
                    if direction > 0
                    else window["high"] >= entry_trigger_price
                )
                entry_candidates = window[hit_mask]
                if entry_candidates.empty:
                    skipped.append(
                        {
                            "date": str(trading_day),
                            "reason": "未达到回撤入场价",
                            "direction": "long" if direction > 0 else "short",
                            "reference_close": round(reference_close, 8),
                            "entry_trigger_price": round(entry_trigger_price, 8),
                        }
                    )
                    continue
                entry_time = entry_candidates.index[0]
                raw_entry = entry_trigger_price
                trade_window = window[window.index >= entry_time]
            else:
                entry_time = window.index[0]
                raw_entry = float(window.iloc[0]["open"])
                trade_window = window

            entry_price = raw_entry * (1 + direction * slippage_rate)
            target_price = entry_price * (1 + direction * take_profit_rate)
            stop_price = entry_price * (1 - direction * stop_loss_rate)
            margin = project_balance * allocation_fraction
            notional = margin * project.leverage
            quantity = notional / entry_price
            entry_fee = quantity * entry_price * fee_rate
            exit_price = float(trade_window.iloc[-1]["close"]) * (1 - direction * slippage_rate)
            exit_time = boundary
            exit_reason = "北京时间21:00"

            for candle_time, candle in trade_window.iterrows():
                target_hit = candle["high"] >= target_price if direction > 0 else candle["low"] <= target_price
                stop_hit = candle["low"] <= stop_price if direction > 0 else candle["high"] >= stop_price
                if stop_hit:
                    exit_price = stop_price * (1 - direction * slippage_rate)
                    exit_time = candle_time
                    exit_reason = "价格止损"
                    break
                pullback_entry_bar = parameters["wait_for_pullback"] and candle_time == entry_time
                if target_hit and not pullback_entry_bar:
                    exit_price = target_price * (1 - direction * slippage_rate)
                    exit_time = candle_time
                    exit_reason = "价格止盈"
                    break

                marked_equity = cash_reserve + project_balance + direction * quantity * (
                    float(candle["close"]) - entry_price
                ) - entry_fee
                account_peak = max(account_peak, marked_equity)
                if account_peak > 0:
                    max_drawdown = max(max_drawdown, (account_peak - marked_equity) / account_peak)

            cutoff_complete = boundary <= futures.index.max() + timedelta(minutes=1)
            if not cutoff_complete and exit_reason == "北京时间21:00":
                skipped.append({"date": str(trading_day), "reason": "持仓退出窗口尚未完成"})
                continue

            exit_fee = quantity * exit_price * fee_rate
            funding_pnl = 0.0
            funding_events = 0
            if not funding.empty:
                held_funding = funding[(funding.index > entry_time) & (funding.index <= exit_time)]
                for _, event in held_funding.iterrows():
                    event_notional = quantity * _safe_number(event.get("mark_price"), entry_price)
                    funding_pnl -= direction * event_notional * _safe_number(event.get("funding_rate"))
                    funding_events += 1
            price_pnl = direction * quantity * (exit_price - entry_price)
            fees = entry_fee + exit_fee
            net_pnl = price_pnl - fees + funding_pnl
            project_balance = max(0.0, project_balance + net_pnl)
            account_equity = cash_reserve + project_balance
            account_peak = max(account_peak, account_equity)
            if account_peak > 0:
                max_drawdown = max(max_drawdown, (account_peak - account_equity) / account_peak)
            trades.append(
                {
                    "signal_date": str(trading_day),
                    "direction": "long" if direction > 0 else "short",
                    "signal_body_pct": round(float(signal["body_pct"]), 6),
                    "signal_body_ratio": round(float(signal["body_ratio"]), 6),
                    "bull_streak": int(signal["large_bull_streak"]),
                    "entry_mode": "pullback" if parameters["wait_for_pullback"] else "immediate",
                    "reference_close": round(reference_close, 8),
                    "entry_trigger_price": round(entry_trigger_price, 8) if entry_trigger_price is not None else None,
                    "entry_time": entry_time.isoformat(),
                    "exit_time": exit_time.isoformat(),
                    "entry_price": round(entry_price, 8),
                    "exit_price": round(exit_price, 8),
                    "margin": round(margin, 8),
                    "leverage": project.leverage,
                    "exit_reason": exit_reason,
                    "price_pnl": round(price_pnl, 8),
                    "fees": round(fees, 8),
                    "funding_pnl": round(funding_pnl, 8),
                    "funding_events": funding_events,
                    "net_pnl": round(net_pnl, 8),
                    "account_equity": round(account_equity, 8),
                }
            )

        daily_pnl: dict[str, float] = {}
        for trade in trades:
            exit_day = str(pd.Timestamp(trade["exit_time"]).date())
            daily_pnl[exit_day] = daily_pnl.get(exit_day, 0.0) + trade["net_pnl"]
        balance = portfolio.initial_capital
        equity_curve: list[dict[str, Any]] = []
        for trading_day in _date_range(start_date, end_date):
            profit = daily_pnl.get(str(trading_day), 0.0)
            balance += profit
            equity_curve.append(
                {"date": str(trading_day), "balance": round(balance, 8), "profit": round(profit, 8)}
            )

        summary = _stats(trades, portfolio.initial_capital)
        long_stats = _stats([trade for trade in trades if trade["direction"] == "long"], portfolio.initial_capital)
        short_stats = _stats([trade for trade in trades if trade["direction"] == "short"], portfolio.initial_capital)
        exit_reasons: list[dict[str, Any]] = []
        for reason in ("价格止盈", "价格止损", "北京时间21:00"):
            selected = [trade for trade in trades if trade["exit_reason"] == reason]
            if selected:
                stats = _stats(selected, portfolio.initial_capital)
                exit_reasons.append(
                    {
                        "reason": reason,
                        "trades": stats["trades"],
                        "profit_abs": round(stats["profit_abs"], 8),
                        "profit_pct": round(stats["profit_pct"], 8),
                    }
                )

        final_equity = cash_reserve + project_balance
        result: dict[str, Any] = {
            "engine": "sndk_hybrid",
            "symbol": SNDK_FUTURES_SYMBOL,
            "symbols": [SNDK_FUTURES_SYMBOL],
            "days": portfolio.run_days,
            "date_range": {"start": str(start_date), "end": str(end_date)},
            "initial_capital": portfolio.initial_capital,
            "final_equity": round(final_equity, 8),
            "total_trades": summary["trades"],
            "wins": summary["wins"],
            "win_rate_pct": round(summary["win_rate_pct"], 8),
            "profit_pct": round((final_equity / portfolio.initial_capital - 1) * 100, 8),
            "profit_abs": round(final_equity - portfolio.initial_capital, 8),
            "max_drawdown_pct": round(max_drawdown * 100, 8),
            "profit_factor": round(summary["profit_factor"], 8),
            "payoff_ratio": round(summary["payoff_ratio"], 8),
            "average_trade_pct": round(
                sum(trade["net_pnl"] / trade["margin"] * 100 for trade in trades) / len(trades), 8
            ) if trades else 0.0,
            "estimated_fees": round(sum(trade["fees"] for trade in trades), 8),
            "funding_pnl": round(sum(trade["funding_pnl"] for trade in trades), 8),
            "estimated_slippage": round(
                sum(trade["margin"] * trade["leverage"] * slippage_rate * 2 for trade in trades), 8
            ),
            "long": {key: round(value, 8) if isinstance(value, float) else value for key, value in long_stats.items()},
            "short": {key: round(value, 8) if isinstance(value, float) else value for key, value in short_stats.items()},
            "per_pair": [
                {
                    "symbol": SNDK_FUTURES_SYMBOL,
                    "trades": summary["trades"],
                    "win_rate_pct": round(summary["win_rate_pct"], 8),
                    "profit_abs": round(summary["profit_abs"], 8),
                    "profit_pct": round(summary["profit_pct"], 8),
                    "profit_factor": round(summary["profit_factor"], 8),
                    "max_drawdown_pct": round(max_drawdown * 100, 8),
                }
            ],
            "exit_reasons": exit_reasons,
            "equity_curve": equity_curve,
            "trades": trades,
            "skipped_signals": skipped,
            "parameters": parameters,
            "portfolio": portfolio.to_dict(),
            "data_sources": {
                "signal": "SNDK正股日线（Yahoo Finance chart，缓存复核）",
                "execution": "Binance Vision SNDKUSDT 1分钟官方归档",
                "funding": funding_source,
            },
            "assumptions": {
                "entry": (
                    f"美股16:00 ET收盘确认后{parameters['entry_delay_minutes']}分钟开始等待，"
                    f"相对正股收盘价"
                    f"{parameters['entry_pullback_pct']}%的回撤/反弹，触价后按市价并计不利滑点"
                    if parameters["wait_for_pullback"]
                    else f"美股16:00 ET收盘确认后{parameters['entry_delay_minutes']}分钟，按市价并计不利滑点"
                ),
                "time_exit": "未触发止盈止损时，于正股收盘对应的北京时间自然日21:00强制退出",
                "same_bar_collision": "同一分钟同时触及止盈止损时按止损优先",
                "real_trading": False,
            },
        }
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result_path = RESULT_ROOT / f"sndk-after-close-{timestamp}.json"
        result["result_file"] = str(result_path)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._log(f"完成 {summary['trades']} 笔交易，结果已保存")
        return result
