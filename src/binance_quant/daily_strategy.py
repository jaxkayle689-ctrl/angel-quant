from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests


YAHOO_CHART_ROOT = "https://query1.finance.yahoo.com/v8/finance/chart"
CBOE_OPTIONS_ROOT = "https://cdn.cboe.com/api/global/delayed_quotes/options"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
FAIR_ECONOMY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UNAVAILABLE = "数据不可验证，因此不参与本次判断"
METHODOLOGY_VERSION = "daily-strategy-v1"


_ASSETS: Tuple[Dict[str, Any], ...] = (
    {
        "id": "SNDK",
        "symbol": "SNDK",
        "name": "SanDisk",
        "display_name": "SNDK · 闪迪",
        "exchange": "NASDAQ",
        "currency": "USD",
        "market": "US equity",
        "options_supported": True,
        "benchmark": "^SOX",
        "benchmark_name": "费城半导体指数",
        "benchmark_beta": 1.0,
        "peers": ("MU", "WDC", "NVDA", "AVGO"),
        "news_keywords": ("sandisk", "sndk"),
        "focus": "NAND、企业级 SSD、AI 服务器存储与数据中心需求",
    },
    {
        "id": "MRVL",
        "symbol": "MRVL",
        "name": "Marvell Technology",
        "display_name": "MRVL · 迈威尔科技",
        "exchange": "NASDAQ",
        "currency": "USD",
        "market": "US equity",
        "options_supported": True,
        "benchmark": "^SOX",
        "benchmark_name": "费城半导体指数",
        "benchmark_beta": 1.0,
        "peers": ("AVGO", "NVDA", "AMD"),
        "news_keywords": ("marvell", "mrvl"),
        "focus": "数据中心互连、定制芯片、光通信与网络芯片",
    },
    {
        "id": "SOXL",
        "symbol": "SOXL",
        "name": "Direxion Daily Semiconductor Bull 3X Shares",
        "display_name": "SOXL · 半导体三倍做多 ETF",
        "exchange": "NYSE Arca",
        "currency": "USD",
        "market": "US leveraged ETF",
        "options_supported": True,
        "benchmark": "^SOX",
        "benchmark_name": "费城半导体指数",
        "benchmark_beta": 3.0,
        "peers": ("SOXX", "SMH", "NVDA"),
        "news_keywords": ("soxl", "direxion daily semiconductor"),
        "focus": "半导体板块整体表现；三倍日收益目标与路径依赖",
    },
    {
        "id": "NBIS",
        "symbol": "NBIS",
        "name": "Nebius Group",
        "display_name": "NBIS · Nebius",
        "exchange": "NASDAQ",
        "currency": "USD",
        "market": "US equity",
        "options_supported": True,
        "benchmark": "^IXIC",
        "benchmark_name": "纳斯达克综合指数",
        "benchmark_beta": 1.0,
        "peers": ("NVDA", "MSFT", "CRWV"),
        "news_keywords": ("nebius", "nbis"),
        "focus": "AI 云基础设施、GPU 容量、资本开支与客户合同",
    },
    {
        "id": "MINIMAX",
        "symbol": "0100.HK",
        "name": "MiniMax",
        "display_name": "0100.HK · MiniMax",
        "exchange": "HKEX",
        "currency": "HKD",
        "market": "Hong Kong equity",
        "options_supported": False,
        "benchmark": "^HSI",
        "benchmark_name": "恒生指数",
        "benchmark_beta": 1.0,
        "peers": ("0700.HK", "9988.HK"),
        "news_keywords": ("minimax", "0100.hk"),
        "focus": "生成式 AI 模型、商业化、算力成本与监管变化",
    },
)


_ASSET_BY_ID = {item["id"]: item for item in _ASSETS}
_ASSET_ALIASES = {
    "0100.HK": "MINIMAX",
    "0100": "MINIMAX",
    "MINIMAX": "MINIMAX",
}

_MACRO_SYMBOLS: Tuple[Tuple[str, str], ...] = (
    ("vix", "^VIX"),
    ("us_10y", "^TNX"),
    ("dxy", "DX-Y.NYB"),
    ("oil", "CL=F"),
    ("nasdaq_futures", "NQ=F"),
)

_TIER_ONE_TERMS = (
    "NFP",
    "NONFARM",
    "NON-FARM",
    "非农",
    "CPI",
    "PCE",
    "FOMC",
    "FEDERAL FUNDS",
    "RATE DECISION",
    "利率决议",
    "POWELL",
    "鲍威尔",
)


def _asset_public(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": item["id"],
        "symbol": item["symbol"],
        "name": item["name"],
        "display_name": item["display_name"],
        "exchange": item["exchange"],
        "currency": item["currency"],
        "market": item["market"],
        "options_supported": bool(item["options_supported"]),
        "benchmark": item["benchmark"],
        "focus": item["focus"],
    }


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _positive(value: Any, allow_zero: bool = False) -> Optional[float]:
    result = _number(value)
    if result is None or result < 0 or (not allow_zero and result == 0):
        return None
    return result


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _round_price(value: float) -> float:
    absolute = abs(value)
    if absolute >= 1000:
        digits = 1
    elif absolute >= 1:
        digits = 2
    else:
        digits = 4
    return round(value, digits)


def _format_price(value: Optional[float]) -> str:
    if value is None:
        return UNAVAILABLE
    if abs(value) >= 1000:
        return f"{value:,.1f}"
    if abs(value) >= 1:
        return f"{value:,.2f}"
    return f"{value:,.4f}"


def _format_range(value: Optional[Sequence[float]]) -> str:
    if not value or len(value) != 2:
        return UNAVAILABLE
    return f"{_format_price(value[0])}–{_format_price(value[1])}"


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)


def _status_score(status: str) -> float:
    return {"available": 1.0, "partial": 0.5}.get(status, 0.0)


class DailyStrategyService:
    """Generate a source-labelled, non-executing intraday strategy snapshot.

    ``request_get`` is intentionally injectable. It follows ``requests.get``'s
    calling convention and makes the network boundary deterministic in tests.
    Event and news providers are optional callables accepting ``(asset, now)``.
    A provider must identify its source and whether it is official in its result.
    """

    def __init__(
        self,
        request_get: Optional[Callable[..., Any]] = None,
        event_provider: Optional[Callable[[Mapping[str, Any], datetime], Any]] = None,
        news_provider: Optional[Callable[[Mapping[str, Any], datetime], Any]] = None,
        now_provider: Optional[Callable[[], datetime]] = None,
        timeout: float = 12.0,
        cache_seconds: float = 120.0,
    ) -> None:
        self._request_get = request_get
        self._event_provider = event_provider
        self._news_provider = news_provider
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._timeout = timeout
        self._cache_seconds = max(0.0, float(cache_seconds))
        self._cache_lock = threading.RLock()
        self._json_cache: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], Tuple[float, Any]] = {}
        self._assets = dict(_ASSET_BY_ID)

    def catalog(self) -> List[Dict[str, Any]]:
        return [_asset_public(item) for item in self._assets.values()]

    def add_asset(self, asset):
        self._assets[asset['id']] = dict(asset)

    def resolve_asset(self, symbol):
        symbol = symbol.strip().upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}', symbol):
            raise ValueError('请输入有效股票代码，例如 AAPL、MU 或 0700.HK')
        symbol = _ASSET_ALIASES.get(symbol, symbol)
        if symbol in self._assets:
            return dict(self._assets[symbol])
        payload = self._request_json(YAHOO_SEARCH_URL, {'q': symbol, 'quotesCount': 10, 'newsCount': 0})
        match = next((item for item in payload.get('quotes', []) if str(item.get('symbol', '')).upper() == symbol), None)
        if not match or match.get('quoteType') not in ('EQUITY', 'ETF'):
            raise ValueError('未找到对应股票或 ETF，请检查完整代码')
        exchange = str(match.get('exchange', ''))
        hk = symbol.endswith('.HK')
        if not hk and exchange not in ('NMS', 'NGM', 'NCM', 'NYQ', 'PCX', 'ASE', 'BTS'):
            raise ValueError('目前支持美股、ETF 和港股')
        name = str(match.get('shortname') or match.get('longname') or symbol)
        return {'id': symbol, 'symbol': symbol, 'name': name, 'display_name': f'{symbol} · {name}',
                'exchange': 'HKEX' if hk else str(match.get('exchDisp') or exchange),
                'currency': 'HKD' if hk else 'USD', 'market': 'Hong Kong equity' if hk else 'US equity',
                'options_supported': not hk, 'benchmark': '^HSI' if hk else '^IXIC',
                'benchmark_name': '恒生指数' if hk else '纳斯达克综合指数', 'benchmark_beta': 1.0,
                'peers': [], 'news_keywords': [symbol.lower(), name.lower()], 'focus': '公司消息、市场相对强弱与期权结构'}

    def _request_json(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        normalized_params = tuple(sorted((str(key), str(value)) for key, value in (params or {}).items()))
        cache_key = (url, normalized_params)
        if self._cache_seconds > 0:
            with self._cache_lock:
                cached = self._json_cache.get(cache_key)
                if cached and time.monotonic() - cached[0] <= self._cache_seconds:
                    return cached[1]
        getter = self._request_get or requests.get
        response = getter(
            url,
            params=dict(params or {}),
            headers={
                "User-Agent": "AngelQuant/0.9 daily-strategy research",
                "Accept": "application/json",
            },
            timeout=self._timeout,
        )
        if isinstance(response, Mapping):
            payload = response
        else:
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, (Mapping, list)):
            raise ValueError("JSON response is not an object or list")
        if self._cache_seconds > 0:
            with self._cache_lock:
                self._json_cache[cache_key] = (time.monotonic(), payload)
        return payload

    @staticmethod
    def _source(
        name: str,
        url: str,
        now: datetime,
        status: str,
        note: str = "",
        source_as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = {
            "name": name,
            "url": url,
            "as_of": source_as_of or _iso(now),
            "status": status,
        }
        if note:
            result["note"] = note
        return result

    def _fetch_yahoo_chart(
        self,
        symbol: str,
        interval: str,
        range_name: str,
        now: datetime,
        include_prepost: bool = True,
    ) -> Dict[str, Any]:
        url = f"{YAHOO_CHART_ROOT}/{symbol}"
        source = self._source(
            "Yahoo Finance chart",
            url,
            now,
            "unavailable",
            "第三方行情；报价可能延迟",
        )
        try:
            payload = self._request_json(
                url,
                {
                    "interval": interval,
                    "range": range_name,
                    "includePrePost": "true" if include_prepost else "false",
                    "events": "div,splits",
                },
            )
            chart = payload.get("chart")
            if not isinstance(chart, Mapping):
                raise ValueError("missing chart")
            if chart.get("error"):
                raise ValueError(str(chart.get("error")))
            results = chart.get("result")
            if not isinstance(results, list) or not results:
                raise ValueError("empty chart result")
            result = results[0]
            if not isinstance(result, Mapping):
                raise ValueError("invalid chart result")
            meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
            timestamps = result.get("timestamp") if isinstance(result.get("timestamp"), list) else []
            indicators = result.get("indicators") if isinstance(result.get("indicators"), Mapping) else {}
            quote_items = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
            quote = quote_items[0] if quote_items and isinstance(quote_items[0], Mapping) else {}

            def series(name: str) -> List[Any]:
                values = quote.get(name)
                return values if isinstance(values, list) else []

            opens = series("open")
            highs = series("high")
            lows = series("low")
            closes = series("close")
            volumes = series("volume")
            bars: List[Dict[str, Any]] = []
            for index, raw_timestamp in enumerate(timestamps):
                timestamp = _number(raw_timestamp)
                if timestamp is None:
                    continue
                close = _number(closes[index]) if index < len(closes) else None
                if close is None:
                    continue
                bars.append(
                    {
                        "timestamp": int(timestamp),
                        "open": _number(opens[index]) if index < len(opens) else None,
                        "high": _number(highs[index]) if index < len(highs) else None,
                        "low": _number(lows[index]) if index < len(lows) else None,
                        "close": close,
                        "volume": _number(volumes[index]) if index < len(volumes) else None,
                    }
                )
            if not bars and _number(meta.get("regularMarketPrice")) is None:
                raise ValueError("chart contains no usable quote")
            quote_times = [
                _parse_datetime(meta.get("regularMarketTime")),
                _parse_datetime(meta.get("preMarketTime")),
                _parse_datetime(meta.get("postMarketTime")),
            ]
            if bars:
                quote_times.append(datetime.fromtimestamp(bars[-1]["timestamp"], tz=timezone.utc))
            quote_time = max((value for value in quote_times if value is not None), default=None)
            source["status"] = "available"
            if quote_time is not None:
                source["as_of"] = _iso(quote_time)
            return {
                "status": "available",
                "symbol": symbol,
                "meta": dict(meta),
                "bars": bars,
                "source": source,
            }
        except Exception as exc:
            source["note"] = f"第三方行情获取失败：{exc}"
            return {
                "status": "unavailable",
                "symbol": symbol,
                "meta": {},
                "bars": [],
                "reason": UNAVAILABLE,
                "source": source,
            }

    @staticmethod
    def _snapshot(chart: Mapping[str, Any]) -> Dict[str, Any]:
        if chart.get("status") != "available":
            return {"status": "unavailable", "price": None, "change_pct": None}
        meta = chart.get("meta") if isinstance(chart.get("meta"), Mapping) else {}
        bars = chart.get("bars") if isinstance(chart.get("bars"), list) else []
        regular_price = _number(meta.get("regularMarketPrice"))
        regular_time = _number(meta.get("regularMarketTime")) or 0.0
        previous_close = _number(meta.get("chartPreviousClose"))
        if previous_close is None:
            previous_close = _number(meta.get("previousClose"))

        candidates: List[Tuple[float, float, str]] = []
        if regular_price is not None:
            candidates.append((regular_time, regular_price, "regular"))
        for prefix in ("preMarket", "postMarket"):
            candidate_price = _number(meta.get(f"{prefix}Price"))
            candidate_time = _number(meta.get(f"{prefix}Time"))
            if candidate_price is not None and candidate_time is not None:
                candidates.append((candidate_time, candidate_price, "extended"))
        if bars:
            last_bar_price = _number(bars[-1].get("close"))
            last_bar_time = _number(bars[-1].get("timestamp"))
            if last_bar_price is not None and last_bar_time is not None:
                candidates.append((last_bar_time, last_bar_price, "bar"))

        if candidates:
            selected_time, price, selected_kind = max(candidates, key=lambda value: value[0])
        else:
            selected_time, price, selected_kind = 0.0, None, "none"
        if selected_kind in ("extended", "bar") and selected_time > regular_time and regular_price is not None:
            previous = regular_price
        else:
            previous = previous_close
        if previous is None and len(bars) >= 2:
            previous = _number(bars[-2].get("close"))
        change_pct = None
        if price is not None and previous not in (None, 0):
            change_pct = (price / previous - 1.0) * 100.0
        return {
            "status": "available" if price is not None else "unavailable",
            "price": price,
            "previous_close": previous,
            "change_pct": change_pct,
            "timestamp": int(selected_time) if selected_time > 0 else None,
        }

    @staticmethod
    def _market_session(asset: Mapping[str, Any], now: datetime) -> str:
        timezone_name = "America/New_York" if asset["market"].startswith("US") else "Asia/Hong_Kong"
        local = now.astimezone(ZoneInfo(timezone_name))
        if local.weekday() >= 5:
            return "closed"
        minute = local.hour * 60 + local.minute
        if asset["market"].startswith("US"):
            if minute < 4 * 60:
                return "closed"
            if minute < 9 * 60 + 30:
                return "pre_market"
            if minute < 16 * 60:
                return "regular"
            if minute < 20 * 60:
                return "after_hours"
            return "closed"
        if (9 * 60 + 30 <= minute < 12 * 60) or (13 * 60 <= minute < 16 * 60):
            return "regular"
        if 9 * 60 <= minute < 9 * 60 + 30:
            return "pre_market"
        return "closed"

    @staticmethod
    def _structure(
        intraday: Mapping[str, Any],
        daily: Mapping[str, Any],
        spot: Optional[float],
    ) -> Dict[str, Any]:
        if spot is None or daily.get("status") != "available":
            return {"status": "unavailable", "reason": UNAVAILABLE}
        daily_bars = [
            bar
            for bar in daily.get("bars", [])
            if _number(bar.get("high")) is not None and _number(bar.get("low")) is not None
        ]
        if len(daily_bars) < 2:
            return {"status": "unavailable", "reason": UNAVAILABLE}
        previous = daily_bars[-2]
        recent = daily_bars[-6:]
        previous_high = _number(previous.get("high"))
        previous_low = _number(previous.get("low"))
        recent_high = max(_number(bar.get("high")) for bar in recent if _number(bar.get("high")) is not None)
        recent_low = min(_number(bar.get("low")) for bar in recent if _number(bar.get("low")) is not None)
        ranges = [
            _number(bar.get("high")) - _number(bar.get("low"))
            for bar in recent
            if _number(bar.get("high")) is not None and _number(bar.get("low")) is not None
        ]
        average_range = _mean(ranges)

        intraday_bars = intraday.get("bars", []) if intraday.get("status") == "available" else []
        selected_intraday: List[Mapping[str, Any]] = []
        if intraday_bars:
            timezone_name = str(intraday.get("meta", {}).get("exchangeTimezoneName") or "UTC")
            try:
                market_timezone = ZoneInfo(timezone_name)
            except Exception:
                market_timezone = timezone.utc
            last_day = datetime.fromtimestamp(intraday_bars[-1]["timestamp"], tz=timezone.utc).astimezone(
                market_timezone
            ).date()
            selected_intraday = [
                bar
                for bar in intraday_bars
                if datetime.fromtimestamp(bar["timestamp"], tz=timezone.utc).astimezone(market_timezone).date()
                == last_day
            ]
        vwap_numerator = 0.0
        vwap_volume = 0.0
        closes: List[float] = []
        for bar in selected_intraday:
            close = _number(bar.get("close"))
            high = _number(bar.get("high"))
            low = _number(bar.get("low"))
            volume = _positive(bar.get("volume"), allow_zero=True)
            if close is not None:
                closes.append(close)
            if close is not None and high is not None and low is not None and volume is not None and volume > 0:
                vwap_numerator += ((high + low + close) / 3.0) * volume
                vwap_volume += volume
        vwap = vwap_numerator / vwap_volume if vwap_volume > 0 else None
        ema20 = None
        if closes:
            alpha = 2.0 / 21.0
            ema20 = closes[0]
            for close in closes[1:]:
                ema20 = alpha * close + (1.0 - alpha) * ema20
        return {
            "status": "available",
            "previous_high": previous_high,
            "previous_low": previous_low,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "average_daily_range": average_range,
            "vwap": vwap,
            "ema20_15m": ema20,
            "method": "historical_price_structure_proxy",
        }

    @staticmethod
    def _option_identity(row: Mapping[str, Any]) -> Tuple[Optional[date], Optional[str], Optional[float]]:
        expiration: Optional[date] = None
        option_type: Optional[str] = None
        strike = _number(row.get("strike"))
        raw_expiration = row.get("expiration_date") or row.get("expiration") or row.get("expiry")
        if isinstance(raw_expiration, str):
            clean = raw_expiration.strip()
            for format_name in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
                try:
                    expiration = datetime.strptime(clean, format_name).date()
                    break
                except ValueError:
                    continue
        raw_type = str(row.get("option_type") or row.get("type") or "").upper()
        if raw_type in ("C", "CALL"):
            option_type = "C"
        elif raw_type in ("P", "PUT"):
            option_type = "P"
        option_symbol = str(row.get("option") or row.get("symbol") or "").replace(" ", "").upper()
        match = re.search(r"(\d{6})([CP])(\d{8})$", option_symbol)
        if match:
            try:
                expiration = expiration or datetime.strptime(match.group(1), "%y%m%d").date()
            except ValueError:
                pass
            option_type = option_type or match.group(2)
            if strike is None:
                strike = int(match.group(3)) / 1000.0
        return expiration, option_type, strike

    def _fetch_options(
        self,
        asset: Mapping[str, Any],
        spot: Optional[float],
        now: datetime,
    ) -> Dict[str, Any]:
        if not asset["options_supported"]:
            return {
                "status": "unavailable",
                "core_complete": False,
                "reason": "该标的未配置可验证的 Cboe 美股期权链；" + UNAVAILABLE,
                "source": self._source(
                    "Cboe Delayed Options",
                    "",
                    now,
                    "not_applicable",
                    "非美国期权标的",
                ),
            }
        url = f"{CBOE_OPTIONS_ROOT}/{asset['symbol']}.json"
        source = self._source(
            "Cboe Delayed Options",
            url,
            now,
            "unavailable",
            "Cboe 延时期权链；不含逐笔成交方向",
        )
        try:
            payload = self._request_json(url)
            data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
            rows = data.get("options") if isinstance(data, Mapping) else None
            if not isinstance(rows, list) or not rows:
                raise ValueError("empty options chain")
            parsed_rows: List[Dict[str, Any]] = []
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                expiration, option_type, strike = self._option_identity(raw)
                if expiration is None or option_type is None or strike is None or expiration < now.date():
                    continue
                parsed_rows.append(
                    {
                        "expiration": expiration,
                        "type": option_type,
                        "strike": strike,
                        "bid": _positive(raw.get("bid"), allow_zero=True),
                        "ask": _positive(raw.get("ask"), allow_zero=True),
                        "last": _positive(raw.get("last_trade_price") or raw.get("last"), allow_zero=True),
                        "volume": _positive(raw.get("volume"), allow_zero=True),
                        "open_interest": _positive(raw.get("open_interest") or raw.get("oi"), allow_zero=True),
                        "iv": _positive(raw.get("iv") or raw.get("implied_volatility"), allow_zero=True),
                        "gamma": _number(raw.get("gamma")),
                        "option": str(raw.get("option") or raw.get("symbol") or ""),
                    }
                )
            if not parsed_rows:
                raise ValueError("options chain has no parseable contracts")
            source["status"] = "delayed"
            source_timestamp = payload.get("timestamp") or (data.get("timestamp") if isinstance(data, Mapping) else None)
            parsed_source_time = _parse_datetime(source_timestamp)
            if parsed_source_time is not None:
                source["as_of"] = _iso(parsed_source_time)
            result = self._analyse_options(parsed_rows, spot, now)
            result["source"] = source
            return result
        except Exception as exc:
            source["note"] = f"Cboe 延时期权链获取失败：{exc}"
            return {
                "status": "unavailable",
                "core_complete": False,
                "reason": UNAVAILABLE,
                "source": source,
            }

    @staticmethod
    def _mid(row: Mapping[str, Any]) -> Optional[float]:
        bid = _number(row.get("bid"))
        ask = _number(row.get("ask"))
        if bid is None or ask is None or bid < 0 or ask < bid:
            return None
        return (bid + ask) / 2.0

    def _analyse_options(
        self,
        rows: Sequence[Mapping[str, Any]],
        spot: Optional[float],
        now: datetime,
    ) -> Dict[str, Any]:
        if spot is None:
            return {"status": "unavailable", "core_complete": False, "reason": UNAVAILABLE}
        expirations = sorted({row["expiration"] for row in rows})
        nearest_expiration = expirations[0]
        nearest = [row for row in rows if row["expiration"] == nearest_expiration]
        strikes_with_both = sorted(
            {
                row["strike"]
                for row in nearest
                if any(other["strike"] == row["strike"] and other["type"] != row["type"] for other in nearest)
            }
        )
        if not strikes_with_both:
            return {"status": "unavailable", "core_complete": False, "reason": UNAVAILABLE}
        atm_strike = min(strikes_with_both, key=lambda strike: abs(strike - spot))
        atm_call = next((row for row in nearest if row["type"] == "C" and row["strike"] == atm_strike), None)
        atm_put = next((row for row in nearest if row["type"] == "P" and row["strike"] == atm_strike), None)
        call_mid = self._mid(atm_call or {})
        put_mid = self._mid(atm_put or {})
        expected_move = call_mid + put_mid if call_mid is not None and put_mid is not None else None
        theoretical_range = None
        if expected_move is not None and expected_move > 0:
            theoretical_range = [_round_price(max(0.0, spot - expected_move)), _round_price(spot + expected_move)]

        call_oi_rows = [row for row in nearest if row["type"] == "C" and (_number(row.get("open_interest")) or 0) > 0]
        put_oi_rows = [row for row in nearest if row["type"] == "P" and (_number(row.get("open_interest")) or 0) > 0]
        call_wall_row = max(call_oi_rows, key=lambda row: _number(row.get("open_interest")) or 0) if call_oi_rows else None
        put_wall_row = max(put_oi_rows, key=lambda row: _number(row.get("open_interest")) or 0) if put_oi_rows else None
        call_wall = _number(call_wall_row.get("strike")) if call_wall_row else None
        put_wall = _number(put_wall_row.get("strike")) if put_wall_row else None

        max_pain = None
        oi_rows = call_oi_rows + put_oi_rows
        candidate_strikes = sorted({row["strike"] for row in oi_rows})
        if candidate_strikes:
            payouts: List[Tuple[float, float]] = []
            for settlement in candidate_strikes:
                payout = 0.0
                for row in oi_rows:
                    open_interest = _number(row.get("open_interest")) or 0.0
                    if row["type"] == "C":
                        intrinsic = max(0.0, settlement - row["strike"])
                    else:
                        intrinsic = max(0.0, row["strike"] - settlement)
                    payout += intrinsic * open_interest * 100.0
                payouts.append((payout, settlement))
            max_pain = min(payouts)[1]

        core_range = None
        wall_conflict = False
        if theoretical_range:
            lower = put_wall if put_wall is not None and theoretical_range[0] <= put_wall < spot else theoretical_range[0]
            upper = call_wall if call_wall is not None and spot < call_wall <= theoretical_range[1] else theoretical_range[1]
            if lower < spot < upper:
                core_range = [_round_price(lower), _round_price(upper)]
            else:
                wall_conflict = True
        if call_wall is not None and put_wall is not None and call_wall <= put_wall:
            wall_conflict = True

        flow = self._estimate_option_flow(nearest, spot)
        term_structure: List[Dict[str, Any]] = []
        for expiration in expirations[:4]:
            expiry_rows = [row for row in rows if row["expiration"] == expiration]
            expiry_strikes = sorted({row["strike"] for row in expiry_rows})
            if not expiry_strikes:
                continue
            expiry_atm = min(expiry_strikes, key=lambda strike: abs(strike - spot))
            ivs = [
                _number(row.get("iv"))
                for row in expiry_rows
                if row["strike"] == expiry_atm and _number(row.get("iv")) is not None
            ]
            term_structure.append(
                {
                    "expiration": expiration.isoformat(),
                    "atm_strike": expiry_atm,
                    "atm_iv": _round_price(_mean(ivs)) if _mean(ivs) is not None else None,
                }
            )

        gamma_values = [
            abs(_number(row.get("gamma"))) * (_number(row.get("open_interest")) or 0.0) * 100.0
            for row in nearest
            if _number(row.get("gamma")) is not None
        ]
        gamma_proxy = sum(gamma_values) if gamma_values else None
        next_call_strike = min(
            (row["strike"] for row in call_oi_rows if call_wall is not None and row["strike"] > call_wall),
            default=None,
        )
        next_put_strike = max(
            (row["strike"] for row in put_oi_rows if put_wall is not None and row["strike"] < put_wall),
            default=None,
        )
        core_complete = bool(theoretical_range and core_range and flow.get("status") == "available" and not wall_conflict)
        status = "available" if core_complete and call_wall is not None and put_wall is not None else "partial"
        return {
            "status": status,
            "core_complete": core_complete,
            "nearest_expiration": nearest_expiration.isoformat(),
            "atm_strike": atm_strike,
            "atm_call_mid": _round_price(call_mid) if call_mid is not None else None,
            "atm_put_mid": _round_price(put_mid) if put_mid is not None else None,
            "atm_straddle": _round_price(expected_move) if expected_move is not None else None,
            "expected_move": _round_price(expected_move) if expected_move is not None else None,
            "expected_move_method": "nearest-expiry ATM call mid + ATM put mid",
            "theoretical_range": theoretical_range,
            "core_range": core_range,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_pain": max_pain,
            "wall_conflict": wall_conflict,
            "next_call_oi_strike": next_call_strike,
            "next_put_oi_strike": next_put_strike,
            "term_structure": term_structure,
            "gamma_oi_proxy": _round_price(gamma_proxy) if gamma_proxy is not None else None,
            "gamma_note": "合约 gamma×OI 的绝对值代理，不代表做市商净 Gamma 方向",
            "flow": flow,
            "next_day_oi_confirmation": None,
            "block_sweep": None,
            "limitations": [
                "Cboe 延时期权链不是逐笔成交源。",
                "last 相对 bid/ask 的方向分类仅为估算，不能识别开平仓、价差或对冲。",
                "次日 OI 确认与 Sweep/Block 数据不可验证，因此不参与本次判断。",
            ],
        }

    @staticmethod
    def _estimate_option_flow(rows: Sequence[Mapping[str, Any]], spot: float) -> Dict[str, Any]:
        bullish = 0.0
        bearish = 0.0
        classified = 0
        call_ask_by_strike: Dict[float, float] = {}
        put_ask_by_strike: Dict[float, float] = {}
        call_bid_by_strike: Dict[float, float] = {}
        put_bid_by_strike: Dict[float, float] = {}
        unusual_volume_oi: List[Dict[str, Any]] = []
        for row in rows:
            bid = _number(row.get("bid"))
            ask = _number(row.get("ask"))
            last = _number(row.get("last"))
            volume = _number(row.get("volume"))
            open_interest = _number(row.get("open_interest"))
            if (
                volume is not None
                and volume >= 10
                and open_interest is not None
                and open_interest > 0
                and volume > open_interest
            ):
                unusual_volume_oi.append(
                    {
                        "type": row.get("type"),
                        "strike": row.get("strike"),
                        "volume": round(volume),
                        "open_interest": round(open_interest),
                        "volume_oi_ratio": round(volume / open_interest, 2),
                        "estimated_premium": round((last or 0.0) * volume * 100.0, 2),
                    }
                )
            if bid is None or ask is None or last is None or volume is None or volume <= 0 or ask < bid:
                continue
            ask_distance = abs(last - ask)
            bid_distance = abs(last - bid)
            if math.isclose(ask_distance, bid_distance, rel_tol=1e-9, abs_tol=1e-9):
                continue
            side = "ask" if ask_distance < bid_distance else "bid"
            premium = last * volume * 100.0
            moneyness = abs(row["strike"] / spot - 1.0)
            weight = 1.0 if moneyness <= 0.03 else (0.6 if moneyness <= 0.08 else 0.2)
            weighted = premium * weight
            classified += 1
            target: Dict[float, float]
            if row["type"] == "C" and side == "ask":
                bullish += weighted
                target = call_ask_by_strike
            elif row["type"] == "C":
                bearish += weighted
                target = call_bid_by_strike
            elif side == "ask":
                bearish += weighted
                target = put_ask_by_strike
            else:
                bullish += weighted
                target = put_bid_by_strike
            target[row["strike"]] = target.get(row["strike"], 0.0) + premium
        total = bullish + bearish
        if classified == 0 or total <= 0:
            return {
                "status": "unavailable",
                "direction": None,
                "label": UNAVAILABLE,
                "estimated": True,
                "reason": UNAVAILABLE,
            }
        score = (bullish - bearish) / total
        if score >= 0.35:
            direction, label = "strong_bullish", "明显偏多"
        elif score >= 0.12:
            direction, label = "bullish", "偏多"
        elif score <= -0.35:
            direction, label = "strong_bearish", "明显偏空"
        elif score <= -0.12:
            direction, label = "bearish", "偏空"
        else:
            direction, label = "neutral", "中性"

        def largest(values: Mapping[float, float]) -> Optional[float]:
            return max(values, key=values.get) if values else None

        unusual_volume_oi.sort(
            key=lambda item: (item["volume_oi_ratio"], item["estimated_premium"]),
            reverse=True,
        )

        return {
            "status": "available",
            "direction": direction,
            "label": label,
            "estimated": True,
            "score": round(score, 4),
            "estimated_bullish_premium": round(bullish, 2),
            "estimated_bearish_premium": round(bearish, 2),
            "major_call_buy_strike": largest(call_ask_by_strike),
            "major_put_buy_strike": largest(put_ask_by_strike),
            "major_call_sell_strike": largest(call_bid_by_strike),
            "major_put_sell_strike": largest(put_bid_by_strike),
            "classified_contracts": classified,
            "unusual_volume_oi": unusual_volume_oi[:5],
            "method": "estimated from aggregate last proximity to bid/ask; premium=last×volume×100",
        }

    @staticmethod
    def _liquidity_proxy(
        spot: Optional[float],
        structure: Mapping[str, Any],
        options: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if spot is None or structure.get("status") != "available":
            return {"status": "unavailable", "reason": UNAVAILABLE}
        average_range = _number(structure.get("average_daily_range")) or spot * 0.02
        buffer_size = max(spot * 0.002, average_range * 0.05)
        if spot >= 200:
            round_step = 10.0
        elif spot >= 50:
            round_step = 5.0
        elif spot >= 10:
            round_step = 1.0
        elif spot >= 1:
            round_step = 0.5
        else:
            round_step = 0.05
        round_above = (math.floor(spot / round_step) + 1) * round_step
        round_below = math.floor(spot / round_step) * round_step
        if math.isclose(round_below, spot):
            round_below -= round_step
        labelled_levels = [
            ("前一交易日高点", _number(structure.get("previous_high"))),
            ("前一交易日低点", _number(structure.get("previous_low"))),
            ("近期高点", _number(structure.get("recent_high"))),
            ("近期低点", _number(structure.get("recent_low"))),
            ("整数关口", round_above),
            ("整数关口", round_below),
            ("Call OI wall", _number(options.get("call_wall"))),
            ("Put OI wall", _number(options.get("put_wall"))),
        ]
        upper_candidates = [(label, value) for label, value in labelled_levels if value is not None and value > spot]
        lower_candidates = [(label, value) for label, value in labelled_levels if value is not None and value < spot]
        if not upper_candidates or not lower_candidates:
            return {"status": "unavailable", "reason": UNAVAILABLE}
        upper_anchor = min(value for _, value in upper_candidates)
        lower_anchor = max(value for _, value in lower_candidates)
        upper_evidence = [label for label, value in upper_candidates if abs(value - upper_anchor) <= buffer_size * 2]
        lower_evidence = [label for label, value in lower_candidates if abs(value - lower_anchor) <= buffer_size * 2]
        upper_range = [_round_price(max(spot, upper_anchor - buffer_size)), _round_price(upper_anchor + buffer_size)]
        lower_range = [_round_price(max(0.0, lower_anchor - buffer_size)), _round_price(min(spot, lower_anchor + buffer_size))]
        upper_distance = max(0.0, upper_anchor - spot)
        lower_distance = max(0.0, spot - lower_anchor)
        if upper_distance < lower_distance * 0.75:
            sweep = "upper"
            sweep_label = "更可能优先扫上方"
        elif lower_distance < upper_distance * 0.75:
            sweep = "lower"
            sweep_label = "更可能优先扫下方"
        else:
            sweep = "none"
            sweep_label = "暂无明显优势"
        return {
            "status": "available",
            "method": "historical_price_structure_proxy_not_order_book",
            "disclosure": "价格结构流动性代理，非订单簿、非流动性热图",
            "upper_pool": upper_range,
            "lower_pool": lower_range,
            "upper_evidence": upper_evidence,
            "lower_evidence": lower_evidence,
            "sweep": sweep,
            "sweep_label": sweep_label,
            "buffer": _round_price(buffer_size),
        }

    def _fetch_comparison_charts(
        self,
        symbols: Iterable[str],
        now: datetime,
    ) -> Dict[str, Dict[str, Any]]:
        unique = sorted(set(symbols))
        charts: Dict[str, Dict[str, Any]] = {}
        if not unique:
            return charts
        with ThreadPoolExecutor(max_workers=min(8, len(unique))) as executor:
            futures = {
                executor.submit(self._fetch_yahoo_chart, symbol, "1d", "5d", now, False): symbol
                for symbol in unique
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    charts[symbol] = future.result()
                except Exception:
                    charts[symbol] = {
                        "status": "unavailable",
                        "symbol": symbol,
                        "source": self._source(
                            "Yahoo Finance chart",
                            f"{YAHOO_CHART_ROOT}/{symbol}",
                            now,
                            "unavailable",
                            UNAVAILABLE,
                        ),
                    }
        return charts

    @staticmethod
    def _relative_strength(
        asset: Mapping[str, Any],
        asset_snapshot: Mapping[str, Any],
        charts: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Any]:
        benchmark_symbol = str(asset["benchmark"])
        benchmark = DailyStrategyService._snapshot(charts.get(benchmark_symbol, {}))
        asset_change = _number(asset_snapshot.get("change_pct"))
        benchmark_change = _number(benchmark.get("change_pct"))
        peers: List[Dict[str, Any]] = []
        for symbol in asset["peers"]:
            snapshot = DailyStrategyService._snapshot(charts.get(symbol, {}))
            peers.append({"symbol": symbol, "change_pct": snapshot.get("change_pct"), "status": snapshot["status"]})
        if benchmark_change is None or asset_change is None:
            return {
                "status": "unavailable",
                "benchmark_direction": None,
                "relative_strength": None,
                "reason": UNAVAILABLE,
                "peers": peers,
            }
        if benchmark_change >= 0.35:
            benchmark_direction = "bullish"
            benchmark_label = "偏多"
        elif benchmark_change <= -0.35:
            benchmark_direction = "bearish"
            benchmark_label = "偏空"
        else:
            benchmark_direction = "neutral"
            benchmark_label = "中性"
        adjusted_benchmark = benchmark_change * float(asset.get("benchmark_beta", 1.0))
        spread = asset_change - adjusted_benchmark
        if spread >= 1.0:
            relative = "strong"
            relative_label = "强"
        elif spread <= -1.0:
            relative = "weak"
            relative_label = "弱"
        else:
            relative = "neutral"
            relative_label = "中性"
        return {
            "status": "available",
            "benchmark": benchmark_symbol,
            "benchmark_name": asset["benchmark_name"],
            "benchmark_change_pct": round(benchmark_change, 3),
            "benchmark_direction": benchmark_direction,
            "benchmark_label": benchmark_label,
            "asset_change_pct": round(asset_change, 3),
            "relative_spread_pct": round(spread, 3),
            "relative_strength": relative,
            "relative_label": relative_label,
            "peers": peers,
        }

    @staticmethod
    def _systemic_risk(charts: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        values: Dict[str, Dict[str, Any]] = {}
        for key, symbol in _MACRO_SYMBOLS:
            snapshot = DailyStrategyService._snapshot(charts.get(symbol, {}))
            values[key] = {
                "symbol": symbol,
                "price": snapshot.get("price"),
                "change_pct": snapshot.get("change_pct"),
                "status": snapshot.get("status"),
            }
        vix = values["vix"]
        nasdaq = values["nasdaq_futures"]
        if vix["status"] != "available" and nasdaq["status"] != "available":
            return {"status": "unavailable", "level": None, "label": UNAVAILABLE, "values": values}
        score = 0
        reasons: List[str] = []
        vix_price = _number(vix.get("price"))
        vix_change = _number(vix.get("change_pct"))
        nasdaq_change = _number(nasdaq.get("change_pct"))
        ten_year_change = _number(values["us_10y"].get("change_pct"))
        if vix_price is not None and vix_price >= 25:
            score += 2
            reasons.append("VIX≥25")
        elif vix_price is not None and vix_price >= 20:
            score += 1
            reasons.append("VIX≥20")
        if vix_change is not None and vix_change >= 10:
            score += 1
            reasons.append("VIX快速上升")
        if nasdaq_change is not None and nasdaq_change <= -1.5:
            score += 2
            reasons.append("纳指期货显著下跌")
        elif nasdaq_change is not None and nasdaq_change <= -0.7:
            score += 1
            reasons.append("纳指期货走弱")
        if ten_year_change is not None and ten_year_change >= 2.0:
            score += 1
            reasons.append("10年期收益率快速上升")
        if score >= 3:
            level, label = "high", "高"
        elif score >= 1:
            level, label = "medium", "中"
        else:
            level, label = "low", "低"
        status = "available" if all(item["status"] == "available" for item in values.values()) else "partial"
        return {
            "status": status,
            "level": level,
            "label": label,
            "score": score,
            "reasons": reasons,
            "values": values,
        }

    def _events(self, asset: Mapping[str, Any], now: datetime) -> Dict[str, Any]:
        try:
            if self._event_provider is None:
                calendar_payload = self._request_json(FAIR_ECONOMY_CALENDAR_URL)
                if not isinstance(calendar_payload, list):
                    raise ValueError("weekly calendar is not a list")
                raw_events = []
                for calendar_item in calendar_payload:
                    if not isinstance(calendar_item, Mapping):
                        continue
                    country = str(calendar_item.get("country") or "").upper()
                    impact = str(calendar_item.get("impact") or "").lower()
                    if country != "USD" and not (country == "ALL" and impact == "high"):
                        continue
                    raw_events.append(
                        {
                            "name": calendar_item.get("title"),
                            "scheduled_at": calendar_item.get("date"),
                            "impact": calendar_item.get("impact"),
                            "forecast": calendar_item.get("forecast"),
                            "previous": calendar_item.get("previous"),
                            # Fair Economy's weekly JSON has no trustworthy actual field.
                            "actual": None,
                        }
                    )
                source_name = "Fair Economy / Forex Factory weekly calendar"
                source_url = FAIR_ECONOMY_CALENDAR_URL
                official = False
            else:
                raw = self._event_provider(asset, now)
                if isinstance(raw, Mapping):
                    raw_events = raw.get("events", [])
                    source_name = str(raw.get("source") or "Injected event calendar")
                    source_url = str(raw.get("url") or "")
                    official = bool(raw.get("official", False))
                else:
                    raw_events = raw
                    source_name = "Injected event calendar"
                    source_url = ""
                    official = False
            if not isinstance(raw_events, list):
                raise ValueError("events must be a list")
            events: List[Dict[str, Any]] = []
            tier_one_near = False
            for item in raw_events:
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("name") or item.get("event") or "未命名事件")
                scheduled = _parse_datetime(item.get("scheduled_at") or item.get("time"))
                if scheduled is not None:
                    seconds_from_now = (scheduled - now).total_seconds()
                    if seconds_from_now < -24 * 60 * 60 or seconds_from_now > 36 * 60 * 60:
                        continue
                explicit_status = item.get("status")
                status = str(explicit_status).lower() if explicit_status else (
                    "pending" if scheduled is None or scheduled >= now else "released_unverified"
                )
                explicit_tier = str(item.get("tier") or item.get("impact") or "").lower()
                tier_one = explicit_tier in ("1", "tier1", "tier_one", "high") or any(
                    term in name.upper() for term in _TIER_ONE_TERMS
                )
                near = False
                if tier_one and scheduled is not None:
                    minutes = (scheduled - now).total_seconds() / 60.0
                    near = -30 <= minutes <= 120
                    tier_one_near = tier_one_near or near
                actual = item.get("actual")
                if actual in (None, "", "N/A", "n/a"):
                    actual = None
                    actual_note = "实际值未核验"
                    direction = None
                else:
                    actual_note = ""
                    direction = item.get("direction")
                events.append(
                    {
                        "name": name,
                        "scheduled_at": _iso(scheduled) if scheduled else None,
                        "status": status,
                        "tier_one": tier_one,
                        "near": near,
                        "actual": actual,
                        "actual_note": actual_note,
                        "forecast": item.get("forecast") or item.get("expected"),
                        "previous": item.get("previous"),
                        "direction": direction,
                        "volatility": item.get("volatility") or item.get("impact"),
                    }
                )
            events.sort(
                key=lambda item: abs(
                    ((_parse_datetime(item.get("scheduled_at")) or now) - now).total_seconds()
                )
            )
            note = "官方来源" if official else "非官方/第三方事件源，必须复核公布时间与数值"
            return {
                "status": "available",
                "events": events,
                "tier_one_near": tier_one_near,
                "official": official,
                "source": self._source(source_name, source_url, now, "available", note),
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "events": [],
                "tier_one_near": False,
                "reason": UNAVAILABLE,
                "source": self._source(
                    "Fair Economy / Forex Factory weekly calendar"
                    if self._event_provider is None
                    else "Economic event calendar",
                    FAIR_ECONOMY_CALENDAR_URL if self._event_provider is None else "",
                    now,
                    "unavailable",
                    f"事件源失败：{exc}",
                ),
            }

    @staticmethod
    def _news_matches_asset(asset: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
        related_raw = item.get("related_tickers") or item.get("relatedTickers") or []
        if isinstance(related_raw, str):
            related = {related_raw.upper()}
        elif isinstance(related_raw, list):
            related = {str(value).upper() for value in related_raw}
        else:
            related = set()
        direct_symbols = {str(asset["symbol"]).upper(), str(asset["id"]).upper()}
        if related.intersection(direct_symbols):
            return True
        title = str(item.get("title") or "").lower()
        keywords = tuple(str(value).lower() for value in asset.get("news_keywords", ()))
        if not any(keyword in title for keyword in keywords):
            return False
        if asset["id"] != "MINIMAX":
            return True
        # "minimax" is also a generic algorithm/game-theory term. Require
        # company/listing context unless Yahoo directly tags ticker 0100.HK.
        company_context = (
            " ai ",
            "artificial intelligence",
            "large language model",
            "model",
            "hong kong",
            "hkex",
            "ipo",
            "0100",
            "tech company",
            "人工智能",
            "大模型",
            "港股",
        )
        padded_title = f" {title} "
        return any(context in padded_title for context in company_context)

    def _news(self, asset: Mapping[str, Any], now: datetime) -> Dict[str, Any]:
        try:
            if self._news_provider is None:
                query = "MiniMax 0100.HK" if asset["id"] == "MINIMAX" else str(asset["symbol"])
                search_payload = self._request_json(
                    YAHOO_SEARCH_URL,
                    {
                        "q": query,
                        "quotesCount": 1,
                        "newsCount": 12,
                        "enableFuzzyQuery": "false",
                    },
                )
                if not isinstance(search_payload, Mapping):
                    raise ValueError("Yahoo search response is not an object")
                yahoo_items = search_payload.get("news")
                if not isinstance(yahoo_items, list):
                    raise ValueError("Yahoo search contains no news list")
                raw_items = []
                cutoff = now - timedelta(hours=24)
                for yahoo_item in yahoo_items:
                    if not isinstance(yahoo_item, Mapping):
                        continue
                    published = _parse_datetime(yahoo_item.get("providerPublishTime"))
                    if published is None or published < cutoff or published > now + timedelta(minutes=10):
                        continue
                    normalized_item = {
                        "title": yahoo_item.get("title"),
                        "published_at": _iso(published),
                        "publisher": yahoo_item.get("publisher"),
                        "url": yahoo_item.get("link"),
                        "related_tickers": yahoo_item.get("relatedTickers"),
                        "direction": None,
                        "volatility": None,
                        "verification": "headline_only",
                    }
                    if self._news_matches_asset(asset, normalized_item):
                        raw_items.append(normalized_item)
                source_name = "Yahoo Finance search news"
                source_url = (
                    f"{YAHOO_SEARCH_URL}?q={quote_plus(query)}&quotesCount=1&newsCount=12"
                )
                official = False
            else:
                raw = self._news_provider(asset, now)
                if isinstance(raw, Mapping):
                    raw_items = raw.get("items", raw.get("news", []))
                    source_name = str(raw.get("source") or "Injected news provider")
                    source_url = str(raw.get("url") or "")
                    official = bool(raw.get("official", False))
                else:
                    raw_items = raw
                    source_name = "Injected news provider"
                    source_url = ""
                    official = False
            if not isinstance(raw_items, list):
                raise ValueError("news items must be a list")
            items = []
            for item in raw_items:
                if not isinstance(item, Mapping) or item.get("material") is False:
                    continue
                items.append(
                    {
                        "title": str(item.get("title") or "未命名消息"),
                        "published_at": item.get("published_at"),
                        "direction": item.get("direction"),
                        "volatility": item.get("volatility"),
                        "url": item.get("url"),
                        "publisher": item.get("publisher"),
                        "related_tickers": item.get("related_tickers"),
                        "verification": item.get("verification"),
                    }
                )
            note = "官方来源" if official else "第三方新闻源，重大消息需回看公司公告"
            return {
                "status": "available",
                "items": items,
                "message": "已检索到直接相关新闻" if items else "未检索到直接相关新闻",
                "official": official,
                "source": self._source(source_name, source_url, now, "available", note),
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "items": [],
                "reason": UNAVAILABLE,
                "source": self._source(
                    "Yahoo Finance search news" if self._news_provider is None else "Company and industry news",
                    YAHOO_SEARCH_URL if self._news_provider is None else "",
                    now,
                    "unavailable",
                    f"新闻源失败：{exc}",
                ),
            }

    @staticmethod
    def _conflict_reason(
        options: Mapping[str, Any],
        relative: Mapping[str, Any],
    ) -> Optional[str]:
        flow = options.get("flow") if isinstance(options.get("flow"), Mapping) else {}
        flow_direction = flow.get("direction")
        if flow_direction == "neutral":
            return "期权估算资金方向中性，核心方向信号不足"
        if relative.get("status") != "available":
            return None
        relative_value = relative.get("relative_strength")
        benchmark = relative.get("benchmark_direction")
        if flow_direction in ("bullish", "strong_bullish") and relative_value == "weak" and benchmark == "bearish":
            return "期权偏多，但标的相对弱且板块偏空"
        if flow_direction in ("bearish", "strong_bearish") and relative_value == "strong" and benchmark == "bullish":
            return "期权偏空，但标的相对强且板块偏多"
        return None

    @staticmethod
    def _strategy_levels(
        direction: str,
        spot: float,
        structure: Mapping[str, Any],
        options: Mapping[str, Any],
        liquidity: Mapping[str, Any],
    ) -> Dict[str, Any]:
        expected_move = _number(options.get("expected_move"))
        core_range = options.get("core_range")
        theoretical = options.get("theoretical_range")
        if expected_move is None or not core_range or not theoretical or liquidity.get("status") != "available":
            raise ValueError(UNAVAILABLE)
        buffer_size = _number(liquidity.get("buffer")) or max(spot * 0.002, expected_move * 0.05)
        if direction == "LONG":
            pool = liquidity["lower_pool"]
            entry_low = pool[1]
            entry_high = entry_low + max(buffer_size, expected_move * 0.04)
            stop = pool[0] - max(buffer_size, expected_move * 0.05)
            tp2 = max(core_range[1], entry_high + expected_move * 0.6)
            internal_candidates = [
                value
                for value in (
                    spot,
                    _number(structure.get("vwap")),
                    _number(structure.get("ema20_15m")),
                    liquidity["upper_pool"][0],
                )
                if value is not None and value > entry_high + buffer_size
            ]
            tp1 = min(internal_candidates) if internal_candidates else entry_high + expected_move * 0.3
            tp1 = min(tp1, tp2 - max(buffer_size, expected_move * 0.08))
            if tp1 <= entry_high:
                tp1 = entry_high + max(buffer_size, expected_move * 0.12)
            tp2 = max(tp2, tp1 + max(buffer_size, expected_move * 0.12))
            next_oi = _number(options.get("next_call_oi_strike"))
            tp3_candidates = [theoretical[1], next_oi]
            tp3 = min(value for value in tp3_candidates if value is not None and value > tp2) if any(
                value is not None and value > tp2 for value in tp3_candidates
            ) else tp2 + expected_move * 0.35
            condition = "等待下方价格结构流动性代理区被测试，并重新收回区间上沿/VWAP后做多"
        else:
            pool = liquidity["upper_pool"]
            entry_high = pool[0]
            entry_low = entry_high - max(buffer_size, expected_move * 0.04)
            stop = pool[1] + max(buffer_size, expected_move * 0.05)
            tp2 = min(core_range[0], entry_low - expected_move * 0.6)
            internal_candidates = [
                value
                for value in (
                    spot,
                    _number(structure.get("vwap")),
                    _number(structure.get("ema20_15m")),
                    liquidity["lower_pool"][1],
                )
                if value is not None and value < entry_low - buffer_size
            ]
            tp1 = max(internal_candidates) if internal_candidates else entry_low - expected_move * 0.3
            tp1 = max(tp1, tp2 + max(buffer_size, expected_move * 0.08))
            if tp1 >= entry_low:
                tp1 = entry_low - max(buffer_size, expected_move * 0.12)
            tp2 = min(tp2, tp1 - max(buffer_size, expected_move * 0.12))
            next_oi = _number(options.get("next_put_oi_strike"))
            tp3_candidates = [theoretical[0], next_oi]
            tp3 = max(value for value in tp3_candidates if value is not None and value < tp2) if any(
                value is not None and value < tp2 for value in tp3_candidates
            ) else max(0.0, tp2 - expected_move * 0.35)
            condition = "等待上方价格结构流动性代理区被测试，并重新跌回区间下沿/VWAP后做空"
        return {
            "entry_low": _round_price(max(0.0, entry_low)),
            "entry_high": _round_price(max(0.0, entry_high)),
            "tp1": _round_price(max(0.0, tp1)),
            "tp2": _round_price(max(0.0, tp2)),
            "tp3": _round_price(max(0.0, tp3)),
            "stop_loss": _round_price(max(0.0, stop)),
            "condition": condition,
        }

    @staticmethod
    def _deduplicate_sources(sources: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        selected: Dict[Tuple[str, str], Dict[str, Any]] = {}
        rank = {"available": 3, "delayed": 2, "not_applicable": 1, "unavailable": 0}
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            key = (str(source.get("name") or ""), str(source.get("url") or ""))
            item = dict(source)
            previous = selected.get(key)
            if previous is None or rank.get(str(item.get("status")), 0) >= rank.get(str(previous.get("status")), 0):
                selected[key] = item
        return sorted(selected.values(), key=lambda item: (item.get("name", ""), item.get("url", "")))

    @staticmethod
    def _event_summary(events: Mapping[str, Any], news: Mapping[str, Any]) -> str:
        pieces: List[str] = []
        if events.get("status") == "available":
            event_items = events.get("events", [])
            if event_items:
                event_labels = []
                for item in event_items[:3]:
                    actual = item.get("actual")
                    actual_label = f"实际 {actual}" if actual not in (None, "") else str(
                        item.get("actual_note") or "实际值未核验"
                    )
                    forecast = item.get("forecast")
                    previous = item.get("previous")
                    values = [actual_label]
                    if forecast not in (None, ""):
                        values.append(f"预期 {forecast}")
                    if previous not in (None, ""):
                        values.append(f"前值 {previous}")
                    event_labels.append(f"{item.get('name')}（{'，'.join(values)}）")
                pieces.append("；".join(event_labels))
            else:
                pieces.append("已接入事件源暂无重大事件")
        else:
            pieces.append(str(events.get("reason") or UNAVAILABLE))
        if news.get("status") == "available":
            news_items = news.get("items", [])
            if news_items:
                pieces.append("；".join(str(item.get("title")) for item in news_items[:2]))
            else:
                pieces.append(str(news.get("message") or "未检索到直接相关新闻"))
        else:
            pieces.append(str(news.get("reason") or UNAVAILABLE))
        return "｜".join(pieces)

    def generate(self, asset_id: str, force: bool = False) -> Dict[str, Any]:
        normalized = str(asset_id or "").strip().upper()
        normalized = _ASSET_ALIASES.get(normalized, normalized)
        if normalized not in self._assets:
            raise ValueError(f"不支持的当日策略标的：{asset_id}")
        if force:
            with self._cache_lock:
                self._json_cache.clear()
        asset = self._assets[normalized]
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        intraday = self._fetch_yahoo_chart(asset["symbol"], "15m", "5d", now, True)
        daily = self._fetch_yahoo_chart(asset["symbol"], "1d", "1mo", now, False)
        asset_snapshot = self._snapshot(intraday if intraday.get("status") == "available" else daily)
        spot = _number(asset_snapshot.get("price"))
        structure = self._structure(intraday, daily, spot)
        options = self._fetch_options(asset, spot, now)

        comparison_symbols = [symbol for _, symbol in _MACRO_SYMBOLS]
        comparison_symbols.extend([asset["benchmark"]])
        comparison_symbols.extend(asset["peers"])
        charts = self._fetch_comparison_charts(comparison_symbols, now)
        relative = self._relative_strength(asset, asset_snapshot, charts)
        systemic = self._systemic_risk(charts)
        liquidity = self._liquidity_proxy(spot, structure, options)
        events = self._events(asset, now)
        news = self._news(asset, now)

        gate_reasons: List[str] = []
        warnings: List[str] = []
        if spot is None:
            gate_reasons.append("当前报价不可验证")
        if events.get("tier_one_near"):
            gate_reasons.append("一级宏观事件将在120分钟内公布或刚公布，等待事件后确认")
        if not options.get("core_complete"):
            gate_reasons.append("核心期权波动或资金数据缺失")
        if options.get("wall_conflict"):
            gate_reasons.append("Call/Put OI wall 结构冲突")
        conflict = self._conflict_reason(options, relative)
        if conflict:
            gate_reasons.append(conflict)
        if liquidity.get("status") != "available":
            gate_reasons.append("价格结构流动性代理不可用")

        if events.get("status") != "available":
            warnings.append("事件日历未验证；交易前必须人工核对 NFP、CPI、PCE、FOMC 与鲍威尔讲话。")
        elif not events.get("official", False):
            warnings.append("事件日历来自非官方/第三方源，公布时间和数值必须复核。")
        if news.get("status") != "available":
            warnings.append("公司与产业消息未验证，因此未参与方向判断。")
        elif not news.get("official", False):
            warnings.append("近期新闻来自 Yahoo Finance 第三方标题聚合，需打开原文并回看公司公告复核。")
        if options.get("status") in ("available", "partial"):
            warnings.append("期权资金方向仅由聚合 last 相对 bid/ask 估算，不等同于逐笔主动买卖。")
        warnings.append("流动性区域仅为历史价格结构代理，不是订单簿或流动性热图。")
        if asset["id"] == "SOXL":
            warnings.append("SOXL 为三倍杠杆 ETF，存在日内复利、路径依赖、波动损耗和隔夜跳空风险。")

        flow = options.get("flow") if isinstance(options.get("flow"), Mapping) else {}
        flow_direction = flow.get("direction")
        direction_code = "WAIT"
        if not gate_reasons:
            if flow_direction in ("bullish", "strong_bullish"):
                direction_code = "LONG"
            elif flow_direction in ("bearish", "strong_bearish"):
                direction_code = "SHORT"
            else:
                gate_reasons.append("期权方向不可验证或中性")
        direction_label = {"LONG": "做多", "SHORT": "做空", "WAIT": "观望"}[direction_code]

        module_statuses = {
            "quote": "available" if spot is not None else "unavailable",
            "events": str(events.get("status") or "unavailable"),
            "news": str(news.get("status") or "unavailable"),
            "options": str(options.get("status") or "unavailable"),
            "liquidity": str(liquidity.get("status") or "unavailable"),
            "relative_strength": str(relative.get("status") or "unavailable"),
            "systemic_risk": str(systemic.get("status") or "unavailable"),
        }
        total_modules = len(module_statuses)
        score = round(sum(_status_score(status) for status in module_statuses.values()) / total_modules * 100)
        verified = sum(1 for status in module_statuses.values() if status == "available")
        if score >= 85:
            completeness_label = "较完整"
        elif score >= 55:
            completeness_label = "部分可用"
        else:
            completeness_label = "数据不足"

        confidence_score = 0
        if direction_code != "WAIT":
            confidence_score = 70
            if relative.get("status") != "available":
                confidence_score -= 10
            elif direction_code == "LONG" and relative.get("relative_strength") == "strong":
                confidence_score += 8
            elif direction_code == "SHORT" and relative.get("relative_strength") == "weak":
                confidence_score += 8
            if systemic.get("level") == "medium":
                confidence_score -= 10
            if systemic.get("level") == "high":
                confidence_score -= 20
            if events.get("status") != "available" or news.get("status") != "available":
                confidence_score -= 10
            confidence_score = max(10, min(90, confidence_score))
        confidence_label = "低" if confidence_score < 50 else ("中" if confidence_score < 75 else "高")

        if events.get("tier_one_near"):
            timing_code = "AFTER_EVENT"
            timing_label = "等待一级事件公布后"
        elif direction_code == "WAIT":
            timing_code = "WAIT_CONFIRMATION"
            timing_label = "等待数据与方向确认"
        else:
            timing_code = "CONDITIONAL_ENTRY"
            timing_label = "仅在价格条件确认后入场"

        strategy: Dict[str, Any] = {
            "direction": direction_label,
            "direction_code": direction_code,
            "entry_low": None,
            "entry_high": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "stop_loss": None,
            "condition": "；".join(gate_reasons) if gate_reasons else "",
            "confidence": confidence_score,
            "confidence_label": confidence_label,
            "timing": timing_label,
        }
        if direction_code in ("LONG", "SHORT") and spot is not None:
            try:
                strategy.update(self._strategy_levels(direction_code, spot, structure, options, liquidity))
                strategy["condition"] += "；TP3 仅在主要 OI wall 有效突破后启用"
            except ValueError:
                direction_code = "WAIT"
                direction_label = "观望"
                timing_code = "WAIT_CONFIRMATION"
                timing_label = "等待数据与方向确认"
                gate_reasons.append("无法基于可验证结构生成完整价位")
                strategy.update(
                    {
                        "direction": direction_label,
                        "direction_code": direction_code,
                        "condition": "；".join(gate_reasons),
                        "confidence": 0,
                        "confidence_label": "低",
                        "timing": "等待数据与方向确认",
                    }
                )

        theoretical_range = options.get("theoretical_range")
        core_range = options.get("core_range")
        implied_summary = UNAVAILABLE
        if theoretical_range:
            implied_summary = (
                f"{_format_range(theoretical_range)}（ATM Straddle ±{_format_price(options.get('expected_move'))}，"
                f"{options.get('nearest_expiration')} 到期）"
            )
        core_summary = _format_range(core_range)
        option_flow_summary = UNAVAILABLE
        if flow.get("status") == "available":
            option_flow_summary = f"{flow.get('label')}（估算；last 相对 bid/ask）"
        strike_summary = UNAVAILABLE
        if flow.get("status") == "available":
            strike_summary = (
                f"Call主动买入估算 {_format_price(flow.get('major_call_buy_strike'))} / "
                f"Put主动买入估算 {_format_price(flow.get('major_put_buy_strike'))}"
            )
        upper_summary = UNAVAILABLE
        lower_summary = UNAVAILABLE
        sweep_summary = UNAVAILABLE
        if liquidity.get("status") == "available":
            upper_summary = _format_range(liquidity.get("upper_pool")) + "（价格结构代理，非订单簿）"
            lower_summary = _format_range(liquidity.get("lower_pool")) + "（价格结构代理，非订单簿）"
            sweep_summary = str(liquidity.get("sweep_label"))
        relative_summary = UNAVAILABLE
        if relative.get("status") == "available":
            relative_summary = (
                f"{relative.get('benchmark_name')} {relative.get('benchmark_label')} / "
                f"{asset['id']} 相对强弱 {relative.get('relative_label')}"
            )
        risk_summary = UNAVAILABLE
        if systemic.get("status") in ("available", "partial"):
            vix_price = _number((systemic.get("values") or {}).get("vix", {}).get("price"))
            vix_label = _format_price(vix_price) if vix_price is not None else UNAVAILABLE
            risk_summary = f"VIX {vix_label} / 系统性风险 {systemic.get('label')}"

        summary = {
            "events": self._event_summary(events, news),
            "implied_range": implied_summary,
            "core_range": core_summary,
            "option_flow": option_flow_summary,
            "strikes": strike_summary,
            "upper_liquidity": upper_summary,
            "lower_liquidity": lower_summary,
            "sweep": sweep_summary,
            "relative_strength": relative_summary,
            "systemic_risk": risk_summary,
        }

        event_status_labels = {
            "pending": "待公布",
            "scheduled": "待公布",
            "released": "已公布",
            "released_unverified": "已公布·实际值未核验",
        }
        event_details: List[str] = []
        for event in events.get("events", []):
            if not isinstance(event, Mapping):
                continue
            actual = event.get("actual") if event.get("actual") not in (None, "") else event.get("actual_note") or "未核验"
            direction = event.get("direction") or "未根据未核验实际值推断"
            event_details.append(
                f"{event.get('name')} | 时间 {event.get('scheduled_at') or '未核验'} | "
                f"实际 {actual} | 预期 {event.get('forecast') or '未核验'} | "
                f"前值 {event.get('previous') or '未核验'} | 方向 {direction} | "
                f"波动 {event.get('volatility') or '未核验'} | "
                f"状态 {event_status_labels.get(str(event.get('status')), event.get('status') or '未核验')}"
            )
        if not event_details:
            event_details.append("未检索到当前窗口内的重要事件；交易前仍需复核官方日历。")
        event_details.append("传导链：美联储利率预期 → 美债收益率 → Nasdaq/SOX → 标的。")
        news_details = [
            f"{item.get('title')} | {item.get('publisher') or '来源未标注'} | {item.get('published_at') or '时间未验证'}"
            for item in news.get("items", [])
            if isinstance(item, Mapping)
        ] or [str(news.get("message") or news.get("reason") or UNAVAILABLE)]
        macro_details: List[str] = []
        for key, item in (systemic.get("values") or {}).items():
            if not isinstance(item, Mapping):
                continue
            macro_details.append(
                f"{item.get('symbol') or key}: {_format_price(_number(item.get('price')))} / "
                f"变动 {item.get('change_pct') if item.get('change_pct') is not None else '未验证'}%"
            )
        macro_details.extend(list(systemic.get("reasons") or ["VIX 只用于风险过滤，不单独决定方向。"]))
        term_details = [
            f"{item.get('expiration')} ATM { _format_price(_number(item.get('atm_strike'))) } / IV原始值 {item.get('atm_iv') if item.get('atm_iv') is not None else '未验证'}"
            for item in options.get("term_structure", [])
            if isinstance(item, Mapping)
        ]
        unusual_flow_details = [
            f"{item.get('type')} { _format_price(_number(item.get('strike'))) }: Volume {item.get('volume')} / OI {item.get('open_interest')} / 比值 {item.get('volume_oi_ratio')}"
            for item in flow.get("unusual_volume_oi", [])
            if isinstance(item, Mapping)
        ]

        modules = [
            {
                "title": "重大消息 / 今晚事件",
                "status": events.get("status"),
                "summary": summary["events"],
                "details": event_details,
            },
            {
                "title": "公司 / 产业消息",
                "status": news.get("status"),
                "summary": str(news.get("message") or news.get("reason") or UNAVAILABLE),
                "details": news_details,
            },
            {
                "title": "期权波动结构",
                "status": options.get("status"),
                "summary": summary["implied_range"],
                "details": [
                    f"核心博弈区间：{summary['core_range']}",
                    f"ATM Strike {_format_price(options.get('atm_strike'))} / Call Mid {_format_price(options.get('atm_call_mid'))} / Put Mid {_format_price(options.get('atm_put_mid'))} / Straddle {_format_price(options.get('atm_straddle'))}",
                    f"突破上沿后的扩展目标：{_format_price(options.get('next_call_oi_strike'))}",
                    f"跌破下沿后的扩展目标：{_format_price(options.get('next_put_oi_strike'))}",
                    f"Gamma×OI 绝对值代理：{_format_price(options.get('gamma_oi_proxy'))}；{options.get('gamma_note') or UNAVAILABLE}",
                    *(term_details or ["ATM IV / IV Term Structure 当前不可验证。"]),
                    f"计算方法：{options.get('expected_move_method') or UNAVAILABLE}",
                    "IV 仅定义波动率与期限结构，不单独判断方向。",
                ],
            },
            {
                "title": "期权资金方向",
                "status": flow.get("status", "unavailable"),
                "summary": summary["option_flow"],
                "details": [
                    f"{summary['strikes']}",
                    f"Call Wall {_format_price(options.get('call_wall'))} / Put Wall {_format_price(options.get('put_wall'))} / Max Pain {_format_price(options.get('max_pain'))}",
                    f"估算偏多 Premium {_format_price(_number(flow.get('estimated_bullish_premium')))} / 偏空 Premium {_format_price(_number(flow.get('estimated_bearish_premium')))}",
                    f"主动卖 Call 估算 Strike {_format_price(_number(flow.get('major_call_sell_strike')))} / 主动卖 Put 估算 Strike {_format_price(_number(flow.get('major_put_sell_strike')))}",
                    *(unusual_flow_details or ["未检出可验证的 Volume > OI 异常合约。"]),
                    "该分类为聚合报价估算，不是逐笔主动成交事实。",
                    "次日 OI、Sweep 与 Block 当前不可验证。",
                ],
            },
            {
                "title": "价格结构流动性代理",
                "status": liquidity.get("status"),
                "summary": f"上方 {upper_summary}；下方 {lower_summary}",
                "details": [
                    "仅使用前高前低、近期高低点、整数关口与 OI wall。",
                    "这不是订单簿，也不是流动性热力图，不能断言必然扫荡。",
                ],
            },
            {
                "title": "板块与相对强弱",
                "status": relative.get("status"),
                "summary": relative_summary,
                "details": [
                    f"比较基准：{asset['benchmark']}；SOXL 按 3 倍基准日变动归一化。"
                    if asset["id"] == "SOXL"
                    else f"比较基准：{asset['benchmark']}。"
                ],
            },
            {
                "title": "VIX / 宏观风险过滤",
                "status": systemic.get("status"),
                "summary": risk_summary,
                "details": macro_details,
            },
        ]

        sources: List[Mapping[str, Any]] = [
            intraday.get("source", {}),
            daily.get("source", {}),
            options.get("source", {}),
            events.get("source", {}),
            news.get("source", {}),
        ]
        sources.extend(chart.get("source", {}) for chart in charts.values())
        for news_item in news.get("items", []):
            if isinstance(news_item, Mapping) and news_item.get("url"):
                sources.append(
                    self._source(
                        str(news_item.get("publisher") or news_item.get("title") or "新闻原文"),
                        str(news_item.get("url")),
                        now,
                        "available",
                        "标题级验证；重大结论应回看原文/公告",
                        str(news_item.get("published_at") or _iso(now)),
                    )
                )
        warnings.extend(
            [
                "Expected Move 是期权隐含的概率性波动参考，不是价格保证。",
                "止损可能发生滑点或跳空，实际成交价不保证。",
                "本模块只提供研究与决策支持，不发送订单；重大事件前不得默认使用高杠杆。",
            ]
        )
        quote_as_of = intraday.get("source", {}).get("as_of") if spot is not None else None
        result = {
            "asset": _asset_public(asset),
            "quote": {
                "price": _round_price(spot) if spot is not None else None,
                "change_pct": round(asset_snapshot["change_pct"], 3)
                if _number(asset_snapshot.get("change_pct")) is not None
                else None,
                "session": self._market_session(asset, now),
                "as_of": quote_as_of,
            },
            "generated_at": _iso(now),
            "completeness": {
                "score": score,
                "label": completeness_label,
                "verified": verified,
                "total": total_modules,
                "modules": module_statuses,
            },
            "timing": {
                "code": timing_code,
                "label": timing_label,
                "tier_one_event_near": bool(events.get("tier_one_near")),
            },
            "summary": summary,
            "strategy": strategy,
            "sources": self._deduplicate_sources(sources),
            "warnings": list(dict.fromkeys(warnings)),
            "modules": modules,
            "methodology_version": METHODOLOGY_VERSION,
            "diagnostics": {
                "gate_reasons": gate_reasons,
                "structure": structure,
                "options": options,
                "liquidity": liquidity,
                "relative_strength": relative,
                "systemic_risk": systemic,
                "events": events,
                "news": news,
            },
        }
        return result


_DEFAULT_SERVICE = DailyStrategyService()


def catalog() -> List[Dict[str, Any]]:
    """Return selectable assets for the independent daily-strategy UI."""

    return _DEFAULT_SERVICE.catalog()


def generate(asset_id: str) -> Dict[str, Any]:
    """Generate one non-executing strategy snapshot for ``asset_id``."""

    return _DEFAULT_SERVICE.generate(asset_id)


__all__ = ["DailyStrategyService", "catalog", "generate", "UNAVAILABLE"]
