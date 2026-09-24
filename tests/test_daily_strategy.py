from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional

from binance_quant.daily_strategy import DailyStrategyService, UNAVAILABLE, catalog


NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


PRICES: Dict[str, tuple] = {
    "SNDK": (100.0, 98.0),
    "MRVL": (80.0, 79.0),
    "SOXL": (45.0, 44.0),
    "NBIS": (60.0, 59.0),
    "0100.HK": (120.0, 118.0),
    "^SOX": (101.0, 100.0),
    "^IXIC": (102.0, 101.0),
    "^HSI": (100.5, 100.0),
    "MU": (103.0, 102.0),
    "WDC": (99.0, 98.0),
    "NVDA": (110.0, 109.0),
    "AVGO": (105.0, 104.0),
    "AMD": (90.0, 89.0),
    "SOXX": (102.0, 101.0),
    "SMH": (104.0, 103.0),
    "MSFT": (101.0, 100.0),
    "CRWV": (55.0, 54.0),
    "0700.HK": (101.0, 100.0),
    "9988.HK": (102.0, 101.0),
    "^VIX": (16.0, 16.2),
    "^TNX": (4.2, 4.19),
    "DX-Y.NYB": (98.0, 98.1),
    "CL=F": (70.0, 70.2),
    "NQ=F": (20000.0, 19950.0),
}


def yahoo_payload(symbol: str, interval: str) -> Mapping[str, Any]:
    price, previous = PRICES.get(symbol, (100.0, 99.0))
    if interval == "15m":
        timestamps = [
            int(datetime(2026, 9, 3, 13, 30, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 3, 13, 45, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc).timestamp()),
        ]
        closes = [price - 0.8, price - 0.3, price]
    else:
        timestamps = [
            int(datetime(2026, 8, 31, 16, 0, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc).timestamp()),
            int(datetime(2026, 9, 3, 16, 0, tzinfo=timezone.utc).timestamp()),
        ]
        closes = [previous - 3.0, previous - 1.0, previous, price]
    highs = [value + 2.0 for value in closes]
    lows = [value - 2.0 for value in closes]
    opens = [value - 0.4 for value in closes]
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "regularMarketPrice": price,
                        "chartPreviousClose": previous,
                        "regularMarketTime": timestamps[-1],
                        "exchangeTimezoneName": "America/New_York",
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": [1000, 1200, 1400, 1600][: len(closes)],
                            }
                        ]
                    },
                }
            ],
        }
    }


def option_row(option_type: str, strike: int, **values: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "option": f"SNDK260904{option_type}{strike * 1000:08d}",
        "bid": 1.0,
        "ask": 1.2,
        "last_trade_price": 1.18,
        "volume": 10,
        "open_interest": 100,
        "iv": 0.5,
        "gamma": 0.03,
    }
    row.update(values)
    return row


def cboe_payload() -> Mapping[str, Any]:
    return {
        "timestamp": "2026-09-03T13:45:00Z",
        "data": {
            "options": [
                option_row("C", 95, bid=6.0, ask=6.4, last_trade_price=6.35, volume=20, open_interest=300),
                option_row("P", 95, bid=0.7, ask=1.0, last_trade_price=0.72, volume=80, open_interest=1500),
                option_row("C", 100, bid=3.0, ask=3.2, last_trade_price=3.18, volume=250, open_interest=500),
                option_row("P", 100, bid=2.8, ask=3.0, last_trade_price=2.81, volume=200, open_interest=500),
                option_row("C", 105, bid=1.1, ask=1.3, last_trade_price=1.29, volume=500, open_interest=1800),
                option_row("P", 105, bid=6.0, ask=6.4, last_trade_price=6.02, volume=30, open_interest=200),
                option_row("C", 110, bid=0.4, ask=0.6, last_trade_price=0.59, volume=50, open_interest=400),
                option_row("P", 90, bid=0.3, ask=0.5, last_trade_price=0.31, volume=20, open_interest=300),
            ]
        },
    }


class FakeRequester:
    def __init__(self, fail_options: bool = False) -> None:
        self.fail_options = fail_options
        self.urls = []

    def __call__(
        self,
        url: str,
        params: Optional[Mapping[str, Any]] = None,
        **_: Any,
    ) -> FakeResponse:
        self.urls.append(url)
        if "delayed_quotes/options" in url:
            if self.fail_options:
                raise OSError("options unavailable")
            return FakeResponse(cboe_payload())
        if "ff_calendar_thisweek.json" in url:
            return FakeResponse(
                [
                    {
                        "title": "US CPI",
                        "country": "USD",
                        "date": (NOW + timedelta(hours=5)).isoformat(),
                        "impact": "High",
                        "forecast": "2.7%",
                        "previous": "2.6%",
                    },
                    {
                        "title": "Unrelated euro event",
                        "country": "EUR",
                        "date": (NOW + timedelta(hours=1)).isoformat(),
                        "impact": "High",
                    },
                ]
            )
        if "/v1/finance/search" in url:
            return FakeResponse(
                {
                    "news": [
                        {
                            "title": "SanDisk data-center demand update",
                            "publisher": "Test Publisher",
                            "link": "https://example.test/sndk-news",
                            "providerPublishTime": int((NOW - timedelta(hours=1)).timestamp()),
                            "relatedTickers": ["SNDK"],
                        }
                    ]
                }
            )
        symbol = url.rsplit("/", 1)[-1]
        interval = str((params or {}).get("interval") or "1d")
        return FakeResponse(yahoo_payload(symbol, interval))


def empty_official_events(_: Mapping[str, Any], __: datetime) -> Mapping[str, Any]:
    return {
        "source": "Official test calendar",
        "url": "https://example.test/events",
        "official": True,
        "events": [],
    }


def empty_official_news(_: Mapping[str, Any], __: datetime) -> Mapping[str, Any]:
    return {
        "source": "Official test news",
        "url": "https://example.test/news",
        "official": True,
        "items": [],
    }


class DailyStrategyTests(unittest.TestCase):
    def service(
        self,
        requester: Optional[FakeRequester] = None,
        event_provider: Any = empty_official_events,
    ) -> DailyStrategyService:
        return DailyStrategyService(
            request_get=requester or FakeRequester(),
            event_provider=event_provider,
            news_provider=empty_official_news,
            now_provider=lambda: NOW,
        )

    def test_catalog_is_config_driven_and_maps_minimax_to_hkex_symbol(self) -> None:
        assets = catalog()
        self.assertEqual([item["id"] for item in assets], ["SNDK", "MRVL", "SOXL", "NBIS", "MINIMAX"])
        minimax = next(item for item in assets if item["id"] == "MINIMAX")
        self.assertEqual(minimax["symbol"], "0100.HK")
        self.assertEqual(minimax["exchange"], "HKEX")
        self.assertFalse(minimax["options_supported"])

    def test_generate_builds_expected_move_walls_and_executable_long_plan(self) -> None:
        result = self.service().generate("SNDK")

        self.assertEqual(result["asset"]["symbol"], "SNDK")
        self.assertEqual(result["quote"]["price"], 100.0)
        self.assertEqual(result["strategy"]["direction_code"], "LONG")
        self.assertEqual(result["strategy"]["direction"], "做多")
        self.assertIsNotNone(result["strategy"]["entry_low"])
        self.assertLess(result["strategy"]["stop_loss"], result["strategy"]["entry_low"])
        self.assertLess(result["strategy"]["entry_high"], result["strategy"]["tp1"])
        self.assertLess(result["strategy"]["tp1"], result["strategy"]["tp2"])
        self.assertLess(result["strategy"]["tp2"], result["strategy"]["tp3"])

        options = result["diagnostics"]["options"]
        self.assertEqual(options["atm_strike"], 100.0)
        self.assertAlmostEqual(options["expected_move"], 6.0)
        self.assertEqual(options["theoretical_range"], [94.0, 106.0])
        self.assertEqual(options["call_wall"], 105.0)
        self.assertEqual(options["put_wall"], 95.0)
        self.assertIn("last 相对 bid/ask", result["summary"]["option_flow"])
        self.assertIn("价格结构代理，非订单簿", result["summary"]["upper_liquidity"])
        self.assertEqual(result["completeness"]["verified"], result["completeness"]["total"])
        self.assertTrue(any(source["status"] == "delayed" for source in result["sources"]))

    def test_snapshot_uses_fresher_extended_hours_bar_and_regular_close_baseline(self) -> None:
        regular_time = int(datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc).timestamp())
        premarket_time = int(datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc).timestamp())
        snapshot = DailyStrategyService._snapshot(
            {
                "status": "available",
                "meta": {
                    "regularMarketPrice": 100.0,
                    "regularMarketTime": regular_time,
                    "chartPreviousClose": 98.0,
                },
                "bars": [{"timestamp": premarket_time, "close": 102.0}],
            }
        )

        self.assertEqual(snapshot["price"], 102.0)
        self.assertEqual(snapshot["previous_close"], 100.0)
        self.assertAlmostEqual(snapshot["change_pct"], 2.0)
        self.assertEqual(snapshot["timestamp"], premarket_time)

    def test_minimax_never_calls_cboe_and_waits_when_core_options_are_missing(self) -> None:
        requester = FakeRequester()
        result = self.service(requester).generate("0100.HK")

        self.assertEqual(result["asset"]["id"], "MINIMAX")
        self.assertEqual(result["asset"]["symbol"], "0100.HK")
        self.assertEqual(result["strategy"]["direction_code"], "WAIT")
        self.assertIsNone(result["strategy"]["entry_low"])
        self.assertIn("核心期权", result["strategy"]["condition"])
        self.assertFalse(any("delayed_quotes/options" in url for url in requester.urls))
        self.assertEqual(result["summary"]["implied_range"], UNAVAILABLE)

    def test_tier_one_event_inside_window_hard_gates_strategy(self) -> None:
        def event_provider(_: Mapping[str, Any], __: datetime) -> Mapping[str, Any]:
            return {
                "source": "Third-party calendar test",
                "url": "https://example.test/calendar",
                "official": False,
                "events": [
                    {
                        "name": "US CPI",
                        "scheduled_at": NOW + timedelta(minutes=45),
                        "status": "pending",
                        "tier": "tier1",
                        "forecast": "2.7%",
                        "previous": "2.6%",
                    }
                ],
            }

        result = self.service(event_provider=event_provider).generate("SNDK")

        self.assertEqual(result["strategy"]["direction_code"], "WAIT")
        self.assertEqual(result["timing"]["code"], "AFTER_EVENT")
        self.assertTrue(result["timing"]["tier_one_event_near"])
        self.assertIn("一级宏观事件", result["strategy"]["condition"])
        self.assertTrue(any("非官方" in warning for warning in result["warnings"]))

    def test_default_service_fetches_traceable_third_party_calendar_and_news(self) -> None:
        requester = FakeRequester()
        service = DailyStrategyService(request_get=requester, now_provider=lambda: NOW)

        result = service.generate("SNDK")

        self.assertTrue(any("ff_calendar_thisweek.json" in url for url in requester.urls))
        self.assertTrue(any("/v1/finance/search" in url for url in requester.urls))
        events = result["diagnostics"]["events"]
        self.assertEqual(events["status"], "available")
        self.assertFalse(events["official"])
        self.assertEqual(len(events["events"]), 1)
        self.assertEqual(events["events"][0]["actual_note"], "实际值未核验")
        self.assertIsNone(events["events"][0]["direction"])
        self.assertIn("实际值未核验", result["summary"]["events"])
        self.assertIn("SanDisk data-center demand update", result["summary"]["events"])
        source_names = {source["name"] for source in result["sources"]}
        self.assertIn("Fair Economy / Forex Factory weekly calendar", source_names)
        self.assertIn("Yahoo Finance search news", source_names)
        self.assertTrue(any("第三方" in warning for warning in result["warnings"]))

    def test_default_news_filters_unrelated_minimax_search_results(self) -> None:
        requester = FakeRequester()
        service = DailyStrategyService(request_get=requester, now_provider=lambda: NOW)

        result = service.generate("MINIMAX")

        self.assertEqual(result["diagnostics"]["news"]["items"], [])
        self.assertIn("未检索到直接相关新闻", result["summary"]["events"])
        self.assertNotIn("SanDisk data-center demand update", result["summary"]["events"])

    def test_failed_cboe_request_is_explicit_and_never_fabricates_levels(self) -> None:
        result = self.service(FakeRequester(fail_options=True)).generate("SNDK")

        self.assertEqual(result["strategy"]["direction_code"], "WAIT")
        self.assertIsNone(result["strategy"]["entry_low"])
        self.assertIsNone(result["strategy"]["tp1"])
        self.assertEqual(result["summary"]["implied_range"], UNAVAILABLE)
        option_sources = [source for source in result["sources"] if source["name"] == "Cboe Delayed Options"]
        self.assertEqual(option_sources[0]["status"], "unavailable")

    def test_unknown_asset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持"):
            self.service().generate("AAPL")


if __name__ == "__main__":
    unittest.main()
