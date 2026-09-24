import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from test_agent_dual_strategy import frame
from binance_quant.agent_runtime import run_agent, validate_decision
from binance_quant.agent_engine import AgentService


def decision(evidence='liquidity-20'):
    return dict(action='LONG',execution='CONDITIONAL',trigger='15m收盘站回116，回踩115–116后入场；跌破113取消',entry_low=115,entry_high=116,stop_loss=113,tp1=121,tp2=124,tp3=128,
                confidence=85,reason='扫荡收回后确认，目标来自结构。',invalid_if='跌破113',evidence_ids=[evidence])

class AgentRuntimeTests(unittest.TestCase):
    def test_both_agents_require_three_calls_and_preserve_model_targets(self):
        with tempfile.TemporaryDirectory() as root, patch('binance_quant.agent_engine.fetch_klines',return_value=frame()):
            client=Mock()
            client.exchange_info.return_value={'symbols':[dict(symbol='BTCUSDT',status='TRADING',quoteAsset='USDT',marginAsset='USDT',contractType='PERPETUAL')]}
            client.ticker_24h.return_value={};client.mark_price.return_value={}
            service=AgentService(Path(root),lambda:client)
            service.configure(dict(provider='deepseek',api_key='test-key',risk={'min_confidence':99,'min_risk_reward':10,'max_stop_pct':0.1,'max_atr_pct':0.2}))
            service._knowledge=Mock()
            service._knowledge.search.return_value=[dict(id='video-1',text='缠论原文',score=.9)]
            service._gateway.ask_json=Mock(side_effect=[dict(focus='扫荡检查',questions=[]),decision(),dict(approved=True,reason='通过'),dict(focus='缠论检查',questions=['分型确认']),decision('video-1'),dict(approved=True,reason='通过')])
            service._notifier.send_signal=Mock()
            records=service.analyze_daily_agents({})['results']
            self.assertEqual(service._gateway.ask_json.call_count,6)
            self.assertEqual([r['strategy_mode'] for r in records],['comprehensive','chanlun'])
            for r in records:
                self.assertEqual(r['analysis_status'],'completed')
                self.assertEqual(r['signal']['action'],'LONG')
                self.assertEqual(r['signal']['execution'],'CONDITIONAL')
                self.assertIn('116',r['signal']['trigger'])
                self.assertIsNone(r['signal']['quantity'])
                self.assertEqual([r['signal'][k] for k in ('tp1','tp2','tp3')],[121,124,128])
                self.assertEqual([t['stage'] for t in r['trace']],['plan','tools','analysis','review','risk'])
            service._knowledge.search.assert_called_with('分型确认',3)
            service._notifier.send_signal.assert_not_called()
            before=service._gateway.ask_json.call_count
            service._analyze('BTCUSDT','15m',False,'chanlun')
            self.assertEqual(service._gateway.ask_json.call_count,before)
            service.configure({'api_key':'replacement'})
            self.assertFalse(service._last_candles)

    def test_reviewer_can_reject_and_unknown_evidence_never_reaches_reviewer(self):
        ask=Mock(side_effect=[dict(focus='核查',questions=[]),decision(),dict(approved=False,reason='缺乏确认')])
        collect=lambda p:dict(evidence=[dict(id='liquidity-20',text='市场数据')])
        _,_,review=run_agent(ask,'comprehensive',{}, {}, collect,[])
        self.assertFalse(review['approved'])
        ask=Mock(side_effect=[dict(focus='核查',questions=[]),decision('invented')])
        with self.assertRaisesRegex(ValueError,'不存在'):
            run_agent(ask,'comprehensive',{}, {},collect,[])
        self.assertEqual(ask.call_count,2)

    def test_invalid_targets_and_wait_with_prices_rejected(self):
        for change in [dict(tp3=120),dict(tp2=float('nan')),dict(stop_loss=True),dict(action='WAIT')]:
            with self.assertRaises(ValueError): validate_decision({**decision(),**change})

    @patch('binance_quant.agent_engine.fetch_klines',return_value=frame())
    def test_no_key_no_rule_fallback_and_rejected_review_clears_all_prices(self,fetch):
        with tempfile.TemporaryDirectory() as root:
            client=Mock();client.exchange_info.return_value={'symbols':[dict(symbol='BTCUSDT',status='TRADING',quoteAsset='USDT',marginAsset='USDT',contractType='PERPETUAL')]}
            client.ticker_24h.return_value={};client.mark_price.return_value={}
            service=AgentService(Path(root),lambda:client)
            service._gateway.ask_json=Mock()
            no_key=service._analyze('BTCUSDT','15m',True,'comprehensive')
            self.assertEqual(no_key['analysis_status'],'not_configured')
            self.assertEqual(no_key['source'],'NONE')
            service._gateway.ask_json.assert_not_called()
            service.configure(dict(provider='deepseek',api_key='test-key'))
            service._gateway.ask_json.side_effect=[dict(focus='检查',questions=[]),decision(),dict(approved=False,reason='无确认')]
            service._notifier.send_signal=Mock()
            record=service._analyze('BTCUSDT','15m',False,'comprehensive')
            self.assertEqual(record['analysis_status'],'review_rejected')
            self.assertEqual(record['signal']['action'],'WAIT')
            for k in ('entry_low','entry_high','stop_loss','tp1','tp2','tp3'): self.assertIsNone(record['signal'][k])
            service._notifier.send_signal.assert_not_called()
