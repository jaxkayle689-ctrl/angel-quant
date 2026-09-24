"""US macro calendar with traceable dates and scenario-based market risk notes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import re
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests


WEEKLY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NASDAQ_EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
SHANGHAI = ZoneInfo("Asia/Shanghai")
NEW_YORK = ZoneInfo("America/New_York")

OFFICIAL_SOURCES = {
    "CPI": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "PPI": "https://www.bls.gov/schedule/news_release/ppi.htm",
    "PCE": "https://www.bea.gov/news/schedule",
    "NFP": "https://www.bls.gov/cps/publications/release-calendar.htm",
    "FOMC": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}

EARNINGS_SOURCES = {
    "MU": "https://investors.micron.com/financials/quarterly-results/",
    "SNDK": "https://investor.sandisk.com/news-events/events",
}
WATCHED_COMPANIES = {
    'MU': '美光', 'SNDK': '闪迪', 'NVDA': '英伟达', 'AMD': 'AMD',
    'AVGO': '博通', 'TSM': '台积电', 'INTC': '英特尔', 'MRVL': '迈威尔',
    'QCOM': '高通', 'ASML': '阿斯麦', 'ARM': 'Arm', 'WDC': '西部数据',
    'AAPL': '苹果', 'MSFT': '微软', 'GOOGL': 'Alphabet', 'AMZN': '亚马逊',
    'META': 'Meta', 'TSLA': '特斯拉', 'ORCL': '甲骨文', 'PLTR': 'Palantir',
    'NBIS': 'Nebius', 'COIN': 'Coinbase', 'MSTR': 'Strategy', 'HOOD': 'Robinhood',
}

# Confirmed company-IR dates provide a fallback if the third-party calendar is down.
CONFIRMED_EARNINGS_2026 = (
    ("SNDK", "SanDisk", 8, 5, 16, 30, "2026 Q4", "released"),
    ("MU", "Micron Technology", 9, 30, 16, 30, "2026 Q4", "upcoming"),
)

# Official 2026 dates. The live weekly feed supplies forecasts and nearer events.
OFFICIAL_2026 = (
    ("NFP", "美国非农就业报告 NFP", 10, 2, 8, 30),
    ("CPI", "美国消费者物价指数 CPI", 10, 14, 8, 30),
    ("PPI", "美国生产者物价指数 PPI", 10, 15, 8, 30),
    ("FOMC", "美联储 FOMC 利率决议与声明", 10, 28, 14, 0),
    ("PCE", "美国个人消费支出与核心 PCE", 10, 29, 8, 30),
    ("NFP", "美国非农就业报告 NFP", 11, 6, 8, 30),
    ("CPI", "美国消费者物价指数 CPI", 11, 10, 8, 30),
    ("PPI", "美国生产者物价指数 PPI", 11, 13, 8, 30),
    ("PCE", "美国个人消费支出与核心 PCE", 11, 25, 8, 30),
    ("NFP", "美国非农就业报告 NFP", 12, 4, 8, 30),
    ("FOMC", "美联储 FOMC 利率决议与声明", 12, 9, 14, 0),
    ("CPI", "美国消费者物价指数 CPI", 12, 10, 8, 30),
    ("PPI", "美国生产者物价指数 PPI", 12, 15, 8, 30),
    ("PCE", "美国个人消费支出与核心 PCE", 12, 23, 8, 30),
)


def _number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KMB%]?)", text, re.I)
    if not match:
        return None
    number = float(match.group(1))
    scale = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(match.group(2).upper(), 1)
    return number * scale


def _kind(title: str) -> str:
    name = title.upper()
    if "PPI" in name or "PRODUCER PRICE" in name:
        return "PPI"
    if "PCE" in name or "PERSONAL INCOME" in name or "PERSONAL SPENDING" in name:
        return "PCE"
    if "CPI" in name or "CONSUMER PRICE" in name:
        return "CPI"
    if "FOMC" in name or "FEDERAL FUNDS" in name or "POWELL" in name:
        return "FOMC"
    if "NFP" in name or "NON-FARM" in name or "NONFARM" in name or "UNEMPLOYMENT" in name or "EMPLOYMENT" in name:
        return "NFP"
    if "RETAIL SALES" in name:
        return "RETAIL"
    if "GDP" in name:
        return "GDP"
    if "EARNINGS" in name or "财报" in title:
        return "EARNINGS"
    return "OTHER"


def _guidance(kind: str, actual: Any, forecast: Any) -> dict[str, str]:
    actual_n, forecast_n = _number(actual), _number(forecast)
    inflation = kind in {"CPI", "PPI", "PCE"}
    growth = kind in {"NFP", "RETAIL", "GDP"}
    if actual_n is not None and forecast_n is not None:
        surprise = actual_n - forecast_n
        if abs(surprise) < max(abs(forecast_n) * 0.03, 0.05):
            return {"tone": "neutral", "headline": "结果接近预期",
                    "impact": "第一反应可能有限，继续观察核心分项、修正值和美债收益率。"}
        hotter = surprise > 0
        if inflation:
            return {"tone": "risk" if hotter else "positive",
                    "headline": "通胀高于预期" if hotter else "通胀低于预期",
                    "impact": ("降息预期可能后移，美债收益率和美元易走高，成长股、纳指与加密资产短线承压。"
                               if hotter else "降息预期可能升温，美债收益率易回落，成长股、纳指与加密资产通常受益。")}
        if growth:
            return {"tone": "mixed", "headline": "增长/就业强于预期" if hotter else "增长/就业弱于预期",
                    "impact": ("经济韧性利好周期股，但也可能推迟降息；先看美债收益率是否上行。"
                               if hotter else "若只是温和降温，可能利好降息交易；若明显恶化，则衰退担忧会压制风险资产。")}
    if kind == "FOMC":
        return {"tone": "risk", "headline": "政策路径风险",
                "impact": "重点看利率决定、点阵图和主席表态。偏鹰通常利空成长股与加密资产，偏鸽通常相反。"}
    if inflation:
        return {"tone": "risk", "headline": "通胀事件风险",
                "impact": "高于预期通常推升利率预期并压制成长股；低于预期通常利好纳指与高波动资产。"}
    if growth:
        return {"tone": "mixed", "headline": "增长与就业风险",
                "impact": "强数据可能利好经济预期但推迟降息；弱数据若幅度过大，会转化为衰退风险。"}
    if kind == "EARNINGS":
        return {"tone": "mixed", "headline": "公司财报风险",
                "impact": "关注营收、EPS、业绩指引与数据中心/存储需求；盘后波动可能传导到半导体、纳指及相关代币化合约。"}
    return {"tone": "neutral", "headline": "宏观波动窗口",
            "impact": "公布前后点差和波动可能放大，避免只按单一数据标题判断方向。"}


class MacroCalendarService:
    def __init__(self, requester: Callable[[], list[dict[str, Any]]] | None = None,
                 earnings_requester: Callable[[datetime], list[dict[str, Any]]] | None = None) -> None:
        self._requester = requester or self._fetch_weekly
        self._earnings_requester = earnings_requester or ((lambda _day: []) if requester else self._fetch_earnings_day)
        self._lock = Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at: datetime | None = None
        self._earnings_cache: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}

    def _cached_earnings_day(self, day: datetime, now: datetime) -> list[dict[str, Any]]:
        key = day.strftime('%Y-%m-%d')
        cached = self._earnings_cache.get(key)
        if cached and now - cached[0] < timedelta(hours=1):
            return cached[1]
        rows = self._earnings_requester(day)
        if not isinstance(rows, list):
            raise ValueError('财报数据格式异常')
        self._earnings_cache[key] = (now, rows)
        return rows

    @staticmethod
    def _fetch_weekly() -> list[dict[str, Any]]:
        response = requests.get(WEEKLY_URL, timeout=15, headers={"User-Agent": "AngelQuant/0.11"})
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, list):
            raise ValueError("经济日历返回格式异常")
        return value

    @staticmethod
    def _fetch_earnings_day(day: datetime) -> list[dict[str, Any]]:
        response = requests.get(
            NASDAQ_EARNINGS_URL, params={"date": day.strftime("%Y-%m-%d")}, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 AngelQuant/0.12", "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        return data.get("rows") or []

    def get(self, refresh: bool = False, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if not refresh and self._cached and self._cached_at and now - self._cached_at < timedelta(minutes=5):
                return self._cached
        errors: list[str] = []
        try:
            weekly = self._requester()
        except Exception as exc:
            weekly = []
            errors.append(f"每周预期数据暂不可用：{exc}")
        earnings_rows: list[tuple[datetime, dict[str, Any]]] = []
        calendar_days = [now.astimezone(NEW_YORK) + timedelta(days=offset) for offset in range(-7, 46)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [(day, pool.submit(self._cached_earnings_day, day, now)) for day in calendar_days if day.weekday() < 5]
            failures = 0
            for day, future in futures:
                try:
                    earnings_rows.extend((day, row) for row in future.result() if isinstance(row, dict))
                except Exception:
                    failures += 1
            if failures:
                errors.append(f'财报日历有 {failures} 天暂不可用，已保留其他日期；稍后刷新重试。')
        events: list[dict[str, Any]] = []
        for raw in weekly:
            if str(raw.get("country", "")).upper() != "USD":
                continue
            impact = str(raw.get("impact", "Low")).lower()
            if impact not in {"high", "medium"}:
                continue
            try:
                scheduled = datetime.fromisoformat(str(raw.get("date"))).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            events.append(self._event(str(raw.get("title") or "美国经济数据"), scheduled,
                                      impact, raw.get("forecast"), raw.get("previous"), raw.get("actual"), "weekly"))
        for day, row in earnings_rows:
            symbol = str(row.get("symbol") or "").upper()
            market_cap = _number(str(row.get("marketCap") or "").replace("$", "")) or 0
            if symbol not in WATCHED_COMPANIES and market_cap < 10_000_000_000:
                continue
            session = str(row.get("time") or "")
            hour, minute = (16, 30) if "after" in session else (8, 0) if "pre" in session else (12, 0)
            scheduled = datetime(day.year, day.month, day.day, hour, minute, tzinfo=NEW_YORK).astimezone(timezone.utc)
            events.append(self._earnings_event(symbol, str(row.get("name") or symbol), scheduled,
                                               row.get("epsForecast"), row.get("fiscalQuarterEnding"), session, "nasdaq"))
        for kind, title, month, day, hour, minute in OFFICIAL_2026:
            scheduled = datetime(2026, month, day, hour, minute, tzinfo=NEW_YORK).astimezone(timezone.utc)
            if scheduled < now - timedelta(days=1):
                continue
            if any(abs((datetime.fromisoformat(e["scheduled_at"]) - scheduled).total_seconds()) < 3600 and e["kind"] == kind for e in events):
                continue
            events.append(self._event(title, scheduled, "high", None, None, None, "official"))
        for symbol, company, month, day, hour, minute, quarter, _ in CONFIRMED_EARNINGS_2026:
            scheduled = datetime(2026, month, day, hour, minute, tzinfo=NEW_YORK).astimezone(timezone.utc)
            if scheduled < now - timedelta(days=120):
                continue
            existing = next((e for e in events if e.get('symbol') == symbol and abs((datetime.fromisoformat(e['scheduled_at']) - scheduled).total_seconds()) < 86400), None)
            confirmed = self._earnings_event(symbol, company, scheduled, existing.get('forecast') if existing else None, quarter, 'time-after-hours', 'company_ir')
            if existing:
                events.remove(existing)
            events.append(confirmed)
        events.sort(key=lambda item: item["scheduled_at"])
        for event in events:
            scheduled = datetime.fromisoformat(event["scheduled_at"])
            delta = scheduled - now
            event["status"] = "upcoming" if delta.total_seconds() >= 0 else "released"
            event["countdown_minutes"] = round(delta.total_seconds() / 60)
        next_high = next((e for e in events if e["impact"] == "high" and e["status"] == "upcoming" and e.get('time_precision') != 'session'), None)
        result = {
            "generated_at": now.isoformat(), "timezone": "Asia/Shanghai", "events": events,
            "next_high": next_high, "errors": errors,
            "earnings_watchlist": [{"symbol": symbol, "name": name,
                "status": 'scheduled' if any(e.get('symbol') == symbol and e['status'] == 'upcoming' for e in events) else 'pending',
                "url": EARNINGS_SOURCES.get(symbol, f'https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}/earnings')}
                for symbol, name in WATCHED_COMPANIES.items()],
            "sources": [
                {"name": "本周预期与前值", "url": WEEKLY_URL, "official": False},
                {"name": "Nasdaq 财报日历", "url": "https://www.nasdaq.com/market-activity/earnings", "official": False},
                *[{"name": f"{key} 官方发布时间", "url": url, "official": True} for key, url in OFFICIAL_SOURCES.items()],
                *[{"name": f"{key} 公司投资者关系", "url": url, "official": True} for key, url in EARNINGS_SOURCES.items()],
            ],
            "notice": "影响判断是情景分析，不是确定涨跌。实际值缺失时只展示公布前风险；公布后需以官方结果核验。",
        }
        with self._lock:
            self._cached, self._cached_at = result, now
        return result

    @staticmethod
    def _event(title: str, scheduled: datetime, impact: str, forecast: Any, previous: Any,
               actual: Any, source_type: str) -> dict[str, Any]:
        kind = _kind(title)
        local = scheduled.astimezone(SHANGHAI)
        return {
            "id": f"{kind}-{int(scheduled.timestamp())}-{re.sub(r'[^A-Za-z]', '', title)[:12]}",
            "kind": kind, "title": title, "scheduled_at": scheduled.isoformat(),
            "local_time": local.isoformat(), "local_date": local.strftime("%Y-%m-%d"),
            "impact": impact, "forecast": forecast or None, "previous": previous or None,
            "actual": actual or None, "source_type": source_type,
            "official_url": OFFICIAL_SOURCES.get(kind), "analysis": _guidance(kind, actual, forecast),
        }

    @staticmethod
    def _earnings_event(symbol: str, company: str, scheduled: datetime, eps_forecast: Any,
                        fiscal_quarter: Any, session: str, source_type: str) -> dict[str, Any]:
        event = MacroCalendarService._event(
            f"{company} ({symbol}) 财报", scheduled, "high", eps_forecast, None, None, source_type,
        )
        event.update({"kind": "EARNINGS", "symbol": symbol, "fiscal_quarter": fiscal_quarter or None,
                      "session": session, "official_url": EARNINGS_SOURCES.get(symbol),
                      "time_precision": 'exact' if source_type == 'company_ir' else 'session',
                      "time_note": '官方电话会议时间' if source_type == 'company_ir' else '美东盘后 · 具体时刻待确认' if 'after' in session else '美东盘前 · 具体时刻待确认' if 'pre' in session else '时间待确认',
                      "analysis": _guidance("EARNINGS", None, eps_forecast)})
        if symbol in WATCHED_COMPANIES:
            event['title'] = f'{WATCHED_COMPANIES[symbol]} ({symbol}) 财报'
        event["id"] = f"EARNINGS-{symbol}-{int(scheduled.timestamp())}"
        return event
