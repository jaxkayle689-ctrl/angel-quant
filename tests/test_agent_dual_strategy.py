import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from binance_quant.agent_context import chan_context, liquidity_context
from binance_quant.agent_engine import AgentConfig, AgentService, ModelGateway, build_market_snapshot


def frame():
    values = [100 + (i % 16 if (i // 16) % 2 == 0 else 16 - i % 16) for i in range(240)]
    times = pd.date_range('2025-01-01', periods=240, freq='15min', tz='UTC')
    return pd.DataFrame(dict(open_time=times, close_time=times + pd.Timedelta(minutes=14),
                             open=values, high=[x+1 for x in values], low=[x-1 for x in values], close=values, volume=[1000]*240))


class DualStrategyTests(unittest.TestCase):
    def test_mode_validation_and_secret_not_persisted(self):
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(Path(root), Mock())
            service.configure({'strategy_mode':'chanlun','provider':'deepseek','api_key':'private-test-key'})
            saved = service._settings_file.read_text()
            self.assertNotIn('private-test-key', saved)
            self.assertEqual(json.loads(saved)['strategy_mode'], 'chanlun')
            service.configure({'provider':'openai'})
            self.assertFalse(service.public_config()['api_key_configured'])
            with self.assertRaises(ValueError): AgentConfig.from_payload({'strategy_mode':'fake'})

    def test_sweep_uses_prior_bars_and_requires_reclaim(self):
        data = frame()
        data.loc[239, ['high','close']] = [200,110]
        self.assertTrue(liquidity_context(data)['buy_side_sweep'])
        data.loc[239,'close'] = 200
        self.assertFalse(liquidity_context(data)['buy_side_sweep'])

    def test_chan_preserves_prefix_and_does_not_confirm_tail(self):
        data = pd.DataFrame({'high':[10,9,8,9,11], 'low':[0,1,2,3,4]})
        structure = chan_context(data)
        first = structure['processed_bars'][0]
        self.assertEqual((first['start'],first['end'],first['high'],first['low']), (0,3,10,3))
        self.assertNotIn('confirmed_at', structure['processed_bars'][-1])
        self.assertFalse(structure['structure_ready'])

    def test_confirmed_strokes_have_later_confirmation(self):
        data = frame()
        full = chan_context(data)
        self.assertGreater(len(full['confirmed_strokes']), 3)
        for end in range(80, 200, 11):
            prefix = chan_context(data.iloc[:end])['confirmed_strokes']
            for stroke in prefix:
                self.assertIn(stroke, full['confirmed_strokes'])
                self.assertGreater(stroke['confirmed_at'], stroke['end']['raw_index'])

    def test_gateway_sends_rag_and_schema(self):
        gateway = ModelGateway()
        gateway._deepseek = Mock(return_value={'action':'WAIT'})
        context = {'strategy':'chanlun','evidence':[{'id':'c1','text':'原文证据'}]}
        gateway.complete('deepseek','key','custom-model',build_market_snapshot(frame(),'BTCUSDT','15m'),[],{},AgentConfig().risk,context)
        payload = json.loads(gateway._deepseek.call_args.args[2])
        self.assertEqual(payload['strategy_context'],context)
        self.assertIn('不得',payload['strategy_instruction'])
        self.assertIn('required',payload['output_schema'])

    @patch('binance_quant.agent_engine.fetch_klines', return_value=frame())
    def test_chan_failure_waits_and_manual_never_pushes(self, fetch):
        with tempfile.TemporaryDirectory() as root:
            client = Mock()
            client.exchange_info.return_value = {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','quoteAsset':'USDT','marginAsset':'USDT','contractType':'PERPETUAL'}]}
            client.ticker_24h.return_value = {}; client.mark_price.return_value = {}
            service = AgentService(Path(root), lambda:client)
            service._knowledge = Mock()
            service._knowledge.search.return_value = [{'id':'c1','score':0.8,'text':'test'}]
            service._gateway.ask_json = Mock(side_effect=ValueError('offline'))
            service._notifier.webhook = 'configured'
            service._notifier.send_signal = Mock()
            service.configure({'strategy_mode':'chanlun','provider':'deepseek','api_key':'key','feishu_webhook':''})
            result = service._analyze('BTCUSDT','15m',True)
            self.assertEqual(result['signal']['action'],'WAIT')
            self.assertEqual(result['strategy_mode'],'chanlun')
            self.assertFalse(result['assessments'])
            service._notifier.send_signal.assert_not_called()
            self.assertIn('offline',result['model_error'])
            service.configure({'strategy_mode':'comprehensive','provider':'rules'})
            other = service._analyze('BTCUSDT','15m',False)
            self.assertNotEqual(result['id'],other['id'])
            self.assertEqual(other['strategy_mode'],'comprehensive')

    def test_connection_test_does_not_create_signal_or_push(self):
        with tempfile.TemporaryDirectory() as root:
            service = AgentService(Path(root), Mock())
            service._gateway._deepseek = Mock(return_value={'connection_test':'ok'})
            service._notifier.send_signal = Mock()
            result = service.test_model({'provider':'deepseek','api_key':'secret'})
            self.assertTrue(result['connected'])
            self.assertFalse(service._history_file.exists())
            service._notifier.send_signal.assert_not_called()

    def test_contract_validation_rejects_stock_and_delisted_before_data_or_model(self):
        with tempfile.TemporaryDirectory() as root:
            client = Mock()
            client.exchange_info.return_value = {'symbols':[
                {'symbol':'SNDKUSDT','status':'TRADING','quoteAsset':'USDT','marginAsset':'USDT','contractType':'TRADIFI_PERPETUAL','underlyingType':'EQUITY'},
                {'symbol':'OLDUSDT','status':'SETTLING','quoteAsset':'USDT','contractType':'PERPETUAL'},
                {'symbol':'BTCUSD_PERP','status':'TRADING','quoteAsset':'USD','marginAsset':'BTC','contractType':'PERPETUAL'},
            ]}
            service = AgentService(Path(root),lambda:client)
            service._validate_contracts([{'symbol':'SNDKUSDT','timeframe':'15m'}])
            for invalid in ('SNDK','0100.HK','OLDUSDT','BTCUSD_PERP'):
                with self.assertRaisesRegex(ValueError,'不是当前可交易'):
                    service._analyze(invalid,'15m',True)
            client.klines.assert_not_called()
            client.exchange_info.side_effect = RuntimeError('offline')
            with self.assertRaisesRegex(ValueError,'无法核验'):
                service.contract_catalog(refresh=True)

if __name__ == '__main__': unittest.main()
