import unittest
from decimal import Decimal as D
import pandas as pd
from binance_quant.prediction_research import analyze, recovery_amount, early_rollover_due

class PredictionResearchTests(unittest.TestCase):
    def test_streaks_and_no_fabricated_returns(self):
        frame=pd.DataFrame({'open_time':pd.date_range('2026-01-01',periods=12,freq='5min',tz='UTC'),
                            'open':[1]*12,'close':[2]*8+[.5]*4})
        r=analyze(frame)
        self.assertEqual(r['streaks']['UP']['longest'],8)
        self.assertEqual(r['streaks']['DOWN']['exact']['4'],1)
        self.assertEqual(r['conditional_at_least_k']['UP']['2']['reverse'],1/7)
        self.assertEqual(r['prediction_backtest']['final_balance'],'unavailable')
    def test_gap_breaks_signal(self):
        frame=pd.DataFrame({'open_time':pd.to_datetime(['2026-01-01 00:00Z','2026-01-01 00:10Z']), 'open':[1,1],'close':[2,2]})
        self.assertEqual(analyze(frame)['streaks']['UP']['longest'],1)
    def test_sizing_and_early_signal(self):
        self.assertEqual(recovery_amount(D('1'),D('.6'),D('0')),D('3.43'))
        self.assertTrue(early_rollover_due(10,D('.90')))
        self.assertFalse(early_rollover_due(11,D('.99')))
        self.assertFalse(early_rollover_due(0,D('.99')))
        with self.assertRaises(ValueError): recovery_amount(D('1'),D('.96'),D('0'))

class ScenarioTests(unittest.TestCase):
    def test_eight_up_breaks_without_fake_fill(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=10,freq='5min',tz='UTC'), 'open':[1]*10,'close':[2]*10})
        result=simulate(frame,D('.5'))
        self.assertEqual(result['final_balance'],37)
        self.assertEqual(result['trades'],6)
        self.assertEqual([t['stake'] for t in result['trade_log']],[1,2,4,8,16,32])
        self.assertIsNotNone(result['failure'])
    def test_reversal_resets(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=5,freq='5min',tz='UTC'), 'open':[1]*5,'close':[2,2,2,.5,.5]})
        result=simulate(frame,D('.5'))
        self.assertEqual(result['final_balance'],101)
        self.assertEqual(result['completed_rounds'],1)
        self.assertEqual(result['trades'],2)
    def test_three_requires_third_closed_candle(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=6,freq='5min',tz='UTC'), 'open':[1]*6,'close':[2,2,.5,.5,.5,2]})
        result=simulate(frame,D('.5'),entry_streak=3)
        self.assertEqual(result['trades'],1)
        self.assertEqual(result['trade_log'][0]['time'],str(frame.time.iloc[5]))
        self.assertEqual(result['final_balance'],101)

    def test_three_streak_delays_failure_one_candle(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=11,freq='5min',tz='UTC'), 'open':[1]*11,'close':[2]*11})
        two=simulate(frame,D('.5'),2)
        three=simulate(frame,D('.5'),3)
        self.assertEqual(three['final_balance'],37)
        self.assertEqual(three['trades'],6)
        self.assertEqual(pd.Timestamp(three['failure'])-pd.Timestamp(two['failure']),pd.Timedelta(minutes=5))

    def test_alternate_direction_ignores_results_and_reset(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=4,freq='5min',tz='UTC'), 'open':[1]*4,'close':[.5,.5,2,.5]})
        r=simulate(frame,D('.5'),mode='alternate')
        self.assertEqual([x['direction'] for x in r['trade_log']],['UP','DOWN','UP','DOWN'])
        self.assertEqual([x['stake'] for x in r['trade_log']],[1,2,1,1])
        self.assertEqual(r['final_balance'],103)

    def test_alternate_stops_at_insufficient_balance(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=8,freq='5min',tz='UTC'), 'open':[1]*8,'close':[.5,2]*4})
        r=simulate(frame,D('.5'),mode='alternate')
        self.assertEqual(r['final_balance'],37)
        self.assertEqual(r['trades'],6)
        self.assertEqual(r['failure'],str(frame.time.iloc[6]))

    def test_alternate_tie_still_advances_direction(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=3,freq='5min',tz='UTC'), 'open':[1]*3,'close':[.5,1,2]})
        r=simulate(frame,D('.5'),mode='alternate')
        self.assertEqual([x['direction'] for x in r['trade_log']],['UP','UP'])
        self.assertEqual([x['stake'] for x in r['trade_log']],[1,2])
        self.assertEqual(r['final_balance'],101)

    def test_alternate_can_start_down(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=2,freq='5min',tz='UTC'), 'open':[1]*2,'close':[.5,2]})
        r=simulate(frame,D('.5'),mode='alternate',first_side='DOWN')
        self.assertEqual([x['direction'] for x in r['trade_log']],['DOWN','UP'])
        self.assertEqual(r['final_balance'],102)

    def test_uudd_waits_for_closed_up_and_keeps_phase_after_win(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=8,freq='5min',tz='UTC'), 'open':[1]*8,'close':[.5,.5,2,2,2,.5,.5,2]})
        r=simulate(frame,D('.5'),mode='uudd_after_up')
        self.assertEqual([x['direction'] for x in r['trade_log']],['UP','UP','DOWN','DOWN','UP'])
        self.assertEqual(r['trade_log'][0]['time'],str(frame.time.iloc[3]))
        self.assertEqual([x['stake'] for x in r['trade_log']],[1]*5)
        self.assertEqual(r['final_balance'],105)

    def test_uudd_no_signal_no_trade(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=4,freq='5min',tz='UTC'), 'open':[1]*4,'close':[.5,.5,.5,2]})
        self.assertEqual(simulate(frame,D('.5'),mode='uudd_after_up')['trades'],0)

    def test_uudd_losses_and_tie_do_not_restart_phase(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=6,freq='5min',tz='UTC'), 'open':[1]*6,'close':[2,.5,1,2,.5,2]})
        r=simulate(frame,D('.5'),mode='uudd_after_up')
        self.assertEqual([x['direction'] for x in r['trade_log']],['UP','DOWN','DOWN','UP'])
        self.assertEqual([x['stake'] for x in r['trade_log']],[1,2,4,1])
        self.assertEqual(r['final_balance'],102)

    def test_down_trigger_half_unit_reset_and_fixed_phase(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=6,freq='5min',tz='UTC'), 'open':[1]*6,'close':[2,.5,.5,.5,2,.5]})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'))
        self.assertEqual(r['trade_log'][0]['time'],str(frame.time.iloc[2]))
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP','DOWN','UP','DOWN'])
        self.assertEqual([t['stake'] for t in r['trade_log']],[.5,1,.5,.5])
        self.assertEqual(r['final_balance'],101.5)

    def test_half_unit_seven_losses_and_no_unaffordable_fill(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=10,freq='5min',tz='UTC'), 'open':[1]*10,'close':[.5]+[.5,2]*4+[.5]})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'))
        self.assertEqual([t['stake'] for t in r['trade_log']],[.5,1,2,4,8,16,32])
        self.assertEqual(r['final_balance'],36.5)
        self.assertIsNotNone(r['failure'])

    def test_down_trigger_requires_previous_not_current_candle(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=3,freq='5min',tz='UTC'), 'open':[1]*3,'close':[2,2,.5]})
        self.assertEqual(simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'))['trades'],0)

    def test_withdrawal_cooldown_and_no_double_count(self):
        from binance_quant.prediction_scenario import simulate
        # Win at 00:05, settled 00:10: no next entry before 02:10.
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=28,freq='5min',tz='UTC'), 'open':[1]*28,'close':[.5,2]+[.5]*24+[2,.5]})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'),withdraw_profit=D('.5'))
        self.assertEqual([t['time'] for t in r['trade_log']],[str(frame.time.iloc[1]),str(frame.time.iloc[26])])
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP','UP'])
        self.assertEqual(r['withdrawn'],1)
        self.assertEqual(r['final_balance'],100)
        self.assertEqual(r['total_assets'],101)
        self.assertEqual(r['total_pnl'],sum(t['pnl'] for t in r['trade_log']))
        self.assertEqual(r['max_total_asset_drawdown'],0)

    def test_withdrawn_money_cannot_fund_losing_sequence(self):
        from binance_quant.prediction_scenario import simulate
        close=[.5,2]+[.5]*24+[.5,2]*5
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'), 'open':[1]*len(close),'close':close})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'),withdraw_profit=D('.5'))
        self.assertEqual(r['withdrawn'],.5)
        self.assertEqual(r['final_balance'],36.5)
        self.assertEqual(r['total_assets'],37)
        self.assertEqual(r['trades'],8)
        self.assertIsNotNone(r['failure'])

    def test_udud_restart_requires_four_new_closed_candles(self):
        from binance_quant.prediction_scenario import simulate
        close=[.5,2,2,.5,2,.5,2]
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'), 'open':[1]*len(close),'close':close})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'),withdraw_profit=D('.5'),restart_policy='udud')
        self.assertEqual([t['time'] for t in r['trade_log']],[str(frame.time.iloc[1]),str(frame.time.iloc[6])])
        self.assertEqual([t['direction'] for t in r['trade_log']],['UP','UP'])
        self.assertEqual(r['withdrawn'],1)
        self.assertEqual(r['total_assets'],101)
        self.assertEqual(r['assumptions']['cooldown_hours'],0)

    def test_udud_tie_breaks_restart_signal(self):
        from binance_quant.prediction_scenario import simulate
        close=[.5,2,2,.5,1,2,.5]
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'), 'open':[1]*len(close),'close':close})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('.5'),withdraw_profit=D('.5'),restart_policy='udud')
        self.assertEqual(r['trades'],1)
        self.assertEqual(r['final_balance'],100)

    def test_month_refill_ledger_and_no_duplicate_trade(self):
        from binance_quant.prediction_month import run_month
        close=[.5]+[.5,2]*12
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'), 'open':[1]*len(close),'close':close})
        r=run_month(frame)
        self.assertGreater(r['capital_injections'],1)
        self.assertEqual(r['total_invested'],100*r['capital_injections'])
        self.assertAlmostEqual(r['net_pnl'],r['total_assets']-r['total_invested'])
        self.assertEqual(r['sessions'][1]['trade_log'][0]['stake'],.5)
        self.assertEqual(r['sessions'][1]['trade_log'][0]['direction'],'UP')

    def test_recycle_only_stops_without_external_topup(self):
        from binance_quant.prediction_month import run_month
        close=[.5]+[.5,2]*12
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=len(close),freq='5min',tz='UTC'), 'open':[1]*len(close),'close':close})
        r=run_month(frame,recycle_only=True)
        self.assertEqual(r['total_invested'],100)
        self.assertEqual(r['additional_injections'],0)
        self.assertEqual(r['account_sessions'],1)
        self.assertEqual(r['reserve_balance'],36.5)
        self.assertEqual(r['total_assets'],36.5)
        self.assertEqual(r['net_pnl'],-63.5)
        self.assertFalse(r['completed_month'])

    def test_buy_fee_reduces_shares_and_increases_recovery(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=3,freq='5min',tz='UTC'), 'open':[1]*3,'close':[.5,2,2]})
        r=simulate(frame,D('.5'),mode='alternate',base_bet=D('.5'),buy_fee_rate=D('.02'))
        self.assertEqual([t['stake'] for t in r['trade_log']],[.5,1.05,2.14])
        self.assertAlmostEqual(r['trade_log'][0]['net_shares'],.98)
        self.assertAlmostEqual(r['trade_log'][0]['assumed_fees'],.01)
        self.assertAlmostEqual(r['final_balance'],100.5044)

    def test_300_capital_is_not_hidden_100_reset(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=2,freq='5min',tz='UTC'), 'open':[1]*2,'close':[.5,2]})
        r=simulate(frame,D('.5'),mode='ud_after_down',base_bet=D('1.5'),withdraw_profit=D('1.5'),restart_policy='udud',initial_capital=D('300'))
        self.assertEqual(r['initial_balance'],300)
        self.assertEqual(r['final_balance'],300)
        self.assertEqual(r['withdrawn'],1.5)
        self.assertEqual(r['total_assets'],301.5)
        self.assertEqual(r['return_pct'],.5)

    def test_fixed_2p5_multiplier_balance_and_reset(self):
        from binance_quant.prediction_scenario import simulate
        frame=pd.DataFrame({'time':pd.date_range('2026-01-01',periods=4,freq='5min',tz='UTC'), 'open':[1]*4,'close':[.5,2,2,.5]})
        r=simulate(frame,D('.5'),mode='alternate',base_bet=D('1.5'),initial_capital=D('300'),buy_fee_rate=D('.02'),multiplier=D('2.5'))
        self.assertEqual([t['stake'] for t in r['trade_log']],[1.5,3.75,9.38,1.5])
        self.assertEqual(r['completed_rounds'],2)
