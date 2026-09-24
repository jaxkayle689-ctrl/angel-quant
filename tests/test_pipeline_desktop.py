import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests
from fastapi.testclient import TestClient

from binance_quant.pipeline.desktop_service import DesktopPipeline
from binance_quant.pipeline.server import BinancePublicFeed, RuntimeConfig, create_app


class DesktopIntegrationTests(unittest.TestCase):
    def test_equity_catalog_populates_runtime_and_accepts_sndk(self):
        feed = Mock()
        feed.catalog.return_value = [{'id': 'us_equity_perpetual', 'name': '美股',
                                     'items': [{'symbol': 'SNDKUSDT', 'label': '闪迪'}]}]
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(RuntimeConfig(memory_path=Path(folder) / 'memory.jsonl'), data_feed=feed)
            client = TestClient(app)
            self.assertIn('SNDKUSDT', client.get('/api/catalog').json()['symbols'])
            app.state.runtime.run = Mock(return_value={'symbol': 'SNDKUSDT'})
            self.assertEqual(client.post('/api/run', json={'symbol': 'SNDKUSDT'}).status_code, 200)
            self.assertEqual(client.post('/api/run', json={'symbol': 'FAKEUSDT'}).status_code, 400)

    def test_directory_failure_is_explicit(self):
        feed = Mock()
        feed.catalog.side_effect = RuntimeError('offline')
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(RuntimeConfig(memory_path=Path(folder) / 'memory.jsonl'), data_feed=feed))
            self.assertEqual(client.get('/api/catalog').status_code, 503)

    def test_oi_is_converted_to_usdt(self):
        session = Mock()
        oi, mark = Mock(), Mock()
        oi.json.return_value = {'openInterest': '10'}
        mark.json.return_value = {'markPrice': '250'}
        session.get.side_effect = [oi, mark]
        self.assertEqual(BinancePublicFeed(session).open_interest_usdt('SNDKUSDT'), 2500)

    def test_server_lifecycle_and_idempotent_start(self):
        service = DesktopPipeline()
        try:
            result = service.start()
            self.assertEqual(service.start(), result)
            self.assertTrue(requests.get(result['url'] + '/api/health', timeout=3).json()['ok'])
        finally:
            service.stop()
        self.assertFalse(service.thread.is_alive())
