import base64
import tempfile
import unittest
from pathlib import Path

from binance_quant.app_api import DashboardAPI
from binance_quant.daily_strategy import DailyStrategyService
from binance_quant.workspace_settings import WorkspaceSettings


class WorkspaceTests(unittest.TestCase):
    def test_workspace_bootstrap_is_local_and_preserves_cached_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DashboardAPI.__new__(DashboardAPI)
            api._workspace_settings = WorkspaceSettings(Path(directory))
            api._workspace_settings.update(reports={'SNDK': {'generated_at': '2026-09-01'}})
            api._daily_strategy = DailyStrategyService(request_get=lambda *args, **kwargs: self.fail('Unexpected network request'))
            result = api.workspace_bootstrap()
            self.assertTrue(result['ok'])
            self.assertEqual(result['data']['workspace_settings']['reports']['SNDK']['generated_at'], '2026-09-01')
            self.assertEqual(len(result['data']['daily_strategy_assets']), 5)

    def test_names_and_deletion_survive_restart_without_removing_original(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DashboardAPI.__new__(DashboardAPI)
            api._workspace_settings = WorkspaceSettings(Path(directory))
            before = api._library_metadata()
            strategy_id = before[0]['id']
            renamed = api.edit_library_strategy({'id': strategy_id, 'action': 'rename', 'name': '我的策略'})
            self.assertTrue(renamed['ok'])
            api._workspace_settings = WorkspaceSettings(Path(directory))
            self.assertEqual(next(s for s in api._library_metadata() if s['id'] == strategy_id)['name'], '我的策略')
            self.assertTrue(api.edit_library_strategy({'id': strategy_id, 'action': 'delete'})['ok'])
            self.assertNotIn(strategy_id, [s['id'] for s in api._library_metadata()])
            from binance_quant.strategy_registry import get_strategy
            self.assertEqual(get_strategy(strategy_id).strategy_id, strategy_id)

    def test_images_are_persisted_reset_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = WorkspaceSettings(Path(directory))
            image = Path('src/binance_quant/web/assets/custom-icon.jpg').read_bytes()
            data = 'data:image/jpeg;base64,' + base64.b64encode(image).decode()
            settings.image('icon', data)
            self.assertEqual(WorkspaceSettings(Path(directory)).read()['icon'], data)
            settings.image('icon', None)
            self.assertIsNone(settings.read()['icon'])
            with self.assertRaises(ValueError):
                settings.image('icon', 'data:image/png;base64,YmFk')

    def test_custom_asset_is_verified_and_isolated_per_service(self):
        service = DailyStrategyService(request_get=lambda *a, **kw: {'quotes': [
            {'symbol': 'AAPL', 'shortname': 'Apple Inc.', 'exchange': 'NMS', 'quoteType': 'EQUITY'}
        ]})
        asset = service.resolve_asset('aapl')
        service.add_asset(asset)
        self.assertEqual(asset['currency'], 'USD')
        self.assertIn('AAPL', [a['id'] for a in service.catalog()])
        self.assertNotIn('AAPL', [a['id'] for a in DailyStrategyService().catalog()])
        with self.assertRaises(ValueError):
            service.resolve_asset('NOTFOUND')

    def test_add_asset_survives_restart_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            api = DashboardAPI.__new__(DashboardAPI)
            api._workspace_settings = WorkspaceSettings(Path(directory))
            api._daily_strategy = DailyStrategyService(request_get=lambda *a, **kw: {'quotes': [
                {'symbol': 'AAPL', 'shortname': 'Apple Inc.', 'exchange': 'NMS', 'quoteType': 'EQUITY'}
            ]})
            self.assertTrue(api.add_daily_asset({'symbol': 'aapl'})['ok'])
            self.assertTrue(api.add_daily_asset({'symbol': 'AAPL'})['ok'])
            self.assertEqual(sum(a['id'] == 'AAPL' for a in api._daily_strategy.catalog()), 1)
            saved = WorkspaceSettings(Path(directory)).read()['assets']
            self.assertEqual(len(saved), 1)
            restored = DailyStrategyService()
            for asset in saved:
                restored.add_asset(asset)
            self.assertIn('AAPL', [a['id'] for a in restored.catalog()])


if __name__ == '__main__':
    unittest.main()
