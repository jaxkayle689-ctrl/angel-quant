import unittest
import pandas as pd
from binance_quant.prediction_stride_backtest import simulate
class StrideTests(unittest.TestCase):
    def frame(self, selected):
        close=[]
        for s in selected: close.extend([s,1])
        return pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'),'open':[1]*len(close),'close':close})
    def test_loss_keeps_side_until_win(self):
        r=simulate(self.frame([2,.5,.5,2,2]))
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP']*4)
        self.assertEqual([t['stake'] for t in r['trade_log']],[1.5,3,6,1.5])
        self.assertEqual(r['net_pnl'],3)
    def test_stop_without_reserve_refill(self):
        r=simulate(self.frame([2]+[.5]*9))
        self.assertEqual(r['trades'],7)
        self.assertEqual(r['final_risk_balance'],109.5)
        self.assertEqual(r['failure_count'],1)
    def test_withdraw_waits_new_alternation(self):
        r=simulate(self.frame([2,2,2,.5,2,2]),threshold=1.5)
        self.assertEqual(r['trades'],2)
        self.assertEqual(r['withdrawn'],3)
        self.assertEqual(r['final_risk_balance'],300)
    def test_alternate_on_loss_and_win(self):
        r=simulate(self.frame([2,.5,.5,2,.5]),threshold=100,reentry='triple_reverse',direction_policy='alternate')
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP','DOWN','UP','DOWN'])
        self.assertEqual([t['stake'] for t in r['trade_log']],[1.5,3,1.5,1.5])
    def test_triple_after_withdrawal_reverse_on_next_target(self):
        r=simulate(self.frame([2,2,2,2,2,.5]),threshold=1.5,reentry='triple_reverse',direction_policy='alternate')
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP','DOWN'])
        self.assertEqual(r['withdrawn'],3)
    def test_double_is_not_triple(self):
        r=simulate(self.frame([2,2,2,2,.5]),threshold=1.5,reentry='triple_reverse',direction_policy='alternate')
        self.assertEqual(r['trades'],1)
    def test_two_closed_same_before_reverse_entry(self):
        r=simulate(self.frame([2,.5,2,2,.5,2]),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='double_reverse')
        self.assertEqual([t['direction'] for t in r['trade_log']],['DOWN','UP'])
        self.assertEqual(r['trade_log'][0]['target_open'],'2026-01-01 00:40:00+00:00')
    def test_initial_double_does_not_replace_post_withdrawal_triple(self):
        r=simulate(self.frame([2,2,.5,2,2,.5]),threshold=1.5,reentry='triple_reverse',direction_policy='alternate',initial_signal='double_reverse')
        self.assertEqual(r['trades'],1)
    def test_initial_triple_needs_three_closed_results(self):
        r=simulate(self.frame([2,2,2,.5,2]),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='triple_reverse')
        self.assertEqual([t['direction'] for t in r['trade_log']],['DOWN','UP'])
        self.assertEqual(r['trade_log'][0]['target_open'],'2026-01-01 00:30:00+00:00')
        short=simulate(self.frame([2,2,.5]),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='triple_reverse')
        self.assertEqual(short['trades'],0)
    def test_initial_four_requires_four_closed_results(self):
        kwargs=dict(threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='four_reverse')
        r=simulate(self.frame([2,2,2,2,.5,2]),**kwargs)
        self.assertEqual([t['direction'] for t in r['trade_log']],['DOWN','UP'])
        self.assertEqual(r['trade_log'][0]['target_open'],'2026-01-01 00:40:00+00:00')
        self.assertEqual(simulate(self.frame([2,2,2,.5]),**kwargs)['trades'],0)
    def test_four_entry_retains_three_after_withdrawal(self):
        r=simulate(self.frame([2,2,2,2,.5,2,2,2,.5]),threshold=1.5,reentry='triple_reverse',direction_policy='alternate',initial_signal='four_reverse')
        self.assertEqual(r['trades'],2)
        self.assertEqual(r['withdrawn'],3)
    def test_every_win_requires_fresh_four(self):
        r=simulate(self.frame([2,2,2,2,.5,2,2,2,2,.5]),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='four_reverse',wait_after_win=True)
        self.assertEqual([t['direction'] for t in r['trade_log']],['DOWN','DOWN'])
        self.assertEqual([t['target_open'] for t in r['trade_log']],['2026-01-01 00:40:00+00:00','2026-01-01 01:30:00+00:00'])
    def test_four_same_plus_seven_alternating_can_fail(self):
        r=simulate(self.frame([2]*4+[2,.5,2,.5,2,.5,2,.5]),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal='four_reverse',wait_after_win=True)
        self.assertEqual(r['max_loss_streak'],7)
        self.assertEqual(r['final_risk_balance'],109.5)
        self.assertEqual(r['failure_count'],1)
    def test_three_reverse_holds_side_and_waits_again_after_win(self):
        r=simulate(self.frame([2,2,2,2,2,.5,2,2,2,.5]),threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='triple_reverse',wait_after_win=True)
        self.assertEqual([t['direction'] for t in r['trade_log']],['DOWN']*4)
        self.assertEqual([t['stake'] for t in r['trade_log']],[1.5,3,6,1.5])
        self.assertEqual(r['net_pnl'],3)
    def test_three_reverse_ten_same_breaks_seven_layers(self):
        r=simulate(self.frame([2]*11),threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='triple_reverse',wait_after_win=True)
        self.assertEqual(r['trades'],7)
        self.assertEqual(r['max_loss_streak'],7)
        self.assertEqual(r['final_risk_balance'],109.5)
        self.assertEqual(r['failure_count'],1)
    def test_1200_allows_nine_losses_not_tenth(self):
        r=simulate(self.frame([2]*13),threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='double_reverse',wait_after_win=True,initial_capital=1200)
        self.assertEqual(r['initial'],1200)
        self.assertEqual(r['trades'],9)
        self.assertEqual(r['max_level'],9)
        self.assertEqual(r['final_risk_balance'],433.5)
        self.assertEqual(r['net_pnl'],-766.5)
    def test_1200_withdraw_restores_1200(self):
        r=simulate(self.frame([2,2,.5]),threshold=1.5,reentry='triple_reverse',direction_policy='persistent',initial_signal='double_reverse',wait_after_win=True,initial_capital=1200)
        self.assertEqual(r['final_risk_balance'],1200)
        self.assertEqual(r['withdrawn'],1.5)
    def test_2400_ten_layers_and_eleventh_unaffordable(self):
        r=simulate(self.frame([2]*14),threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='double_reverse',wait_after_win=True,initial_capital=2400)
        self.assertEqual(r['trades'],10)
        self.assertEqual(r['max_level'],10)
        self.assertEqual(r['final_risk_balance'],865.5)
        self.assertEqual(r['failure_count'],1)
