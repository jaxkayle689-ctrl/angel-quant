import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from binance_quant.freqtrade_engine import FreqtradeEngine
from binance_quant.strategy_registry import get_strategy


def test_community_adapters_are_registered_and_configured():
    with tempfile.TemporaryDirectory() as directory, patch('binance_quant.freqtrade_engine.FREQTRADE_DIR', Path(directory)):
        engine = FreqtradeEngine()
        for strategy_id in ('community_genetic', 'community_trend', 'community_ewo'):
            strategy = get_strategy(strategy_id)
            assert strategy.backtest_adapter['supports_portfolio']
            assert strategy.backtest_adapter['supports_dry_run']
            engine._write_config('BTCUSDT', 1000, strategy_class=strategy.backtest_adapter['strategy_class'])
            config = json.loads(engine.config_path.read_text())
            assert config['timeframe'] == '5m'
            assert config['dry_run'] is True
            assert config['strategy'] == strategy.backtest_adapter['strategy_class']
        assert (Path(directory) / 'strategies' / 'community_adapters.py').exists()


def test_calendar_partial_failure_keeps_other_dates_and_watchlist():
    from datetime import datetime, timezone
    from binance_quant.macro_calendar import MacroCalendarService
    def fetch(day):
        if day.day == 22:
            raise RuntimeError('rate limited')
        if day.strftime('%Y-%m-%d') == '2026-09-24':
            return [{'symbol': 'NVDA', 'time': 'time-after-hours', 'marketCap': 'N/A'}]
        return []
    result = MacroCalendarService(lambda: [], fetch).get(now=datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
    event = next(e for e in result['events'] if e.get('symbol') == 'NVDA')
    assert event['time_precision'] == 'session'
    assert len(result['earnings_watchlist']) == 24
    assert result['errors']
