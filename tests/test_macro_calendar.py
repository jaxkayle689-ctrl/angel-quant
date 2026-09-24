from datetime import datetime, timezone
import unittest

from binance_quant.macro_calendar import MacroCalendarService


class MacroCalendarTests(unittest.TestCase):
    def test_dates_are_shanghai_time_and_official_core_events_are_present(self):
        rows = [{"title":"Core Retail Sales m/m","country":"USD","date":"2026-09-16T08:30:00-04:00",
                 "impact":"Medium","forecast":"0.6%","previous":"-0.3%"}]
        result = MacroCalendarService(lambda: rows).get(now=datetime(2026,9,16,0,tzinfo=timezone.utc))
        retail = next(item for item in result["events"] if item["kind"] == "RETAIL")
        self.assertEqual(retail["local_time"], "2026-09-16T20:30:00+08:00")
        self.assertEqual(retail["analysis"]["tone"], "mixed")
        kinds = {item["kind"] for item in result["events"]}
        self.assertTrue({"CPI","PPI","PCE","NFP","FOMC"}.issubset(kinds))

    def test_actual_surprise_changes_risk_scenario(self):
        rows = [{"title":"CPI y/y","country":"USD","date":"2026-09-16T08:30:00-04:00",
                 "impact":"High","forecast":"3.1%","previous":"3.0%","actual":"3.6%"}]
        result = MacroCalendarService(lambda: rows).get(now=datetime(2026,9,16,13,tzinfo=timezone.utc))
        event = next(item for item in result["events"] if item["title"] == "CPI y/y")
        self.assertEqual(event["status"], "released")
        self.assertEqual(event["analysis"]["headline"], "通胀高于预期")
        self.assertEqual(event["analysis"]["tone"], "risk")
        self.assertIn("成长股", event["analysis"]["impact"])

    def test_feed_failure_keeps_official_schedule(self):
        def fail():
            raise RuntimeError("offline")
        result = MacroCalendarService(fail).get(now=datetime(2026,9,16,tzinfo=timezone.utc))
        self.assertTrue(result["events"])
        self.assertIn("暂不可用", result["errors"][0])

    def test_large_cap_and_watched_earnings_are_added(self):
        def earnings(day):
            if day.date().isoformat() != "2026-09-23":
                return []
            return [
                {"symbol":"MU","name":"Micron Technology, Inc.","marketCap":"$100,000,000,000",
                 "time":"time-after-hours","epsForecast":"$2.10","fiscalQuarterEnding":"Aug/2026"},
                {"symbol":"TINY","name":"Tiny Corp","marketCap":"$5,000,000",
                 "time":"time-after-hours","epsForecast":"$0.01","fiscalQuarterEnding":"Jun/2026"},
            ]
        result = MacroCalendarService(lambda: [], earnings).get(now=datetime(2026,9,23,tzinfo=timezone.utc))
        micron = next(item for item in result["events"] if item.get("symbol") == "MU")
        self.assertEqual(micron["kind"], "EARNINGS")
        self.assertEqual(micron["forecast"], "$2.10")
        self.assertEqual(micron["local_time"], "2026-09-24T04:30:00+08:00")
        self.assertFalse(any(item.get("symbol") == "TINY" for item in result["events"]))


if __name__ == "__main__":
    unittest.main()
