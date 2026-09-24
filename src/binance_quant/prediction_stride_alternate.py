"""Requested alternate stride strategy, withdrawal 100 and triple-reverse restart."""
import argparse
import json
from pathlib import Path
import pandas as pd
from .prediction_stride_backtest import simulate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--initial-signal',choices=['previous','double_reverse','triple_reverse','four_reverse'],default='previous')
    parser.add_argument('--wait-after-win',action='store_true')
    args=parser.parse_args()
    root=Path('experiments/prediction_btc5m')
    out={'assumptions':'Ideal full fills .50 zero fees; actual fills unavailable. Odd UTC candles only; K1 sets first side for K3. Alternate every selected traded period, including refund ties. Withdraw excess over 300 at >=400 (usually 100.5). Fresh post-withdrawal triple same side then reverse next target. Stop on insufficient risk balance, do not recycle withdrawals.', 'months':{}}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        f=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        if not f.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all(): raise ValueError('Gaps')
        windows={}
        for name,n in [('day',288),('week',2016),('month',len(f))]:
            windows[name]=simulate(f.iloc[:n],threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal=args.initial_signal,wait_after_win=args.wait_after_win)
        cohorts=[]
        for day in sorted(f.time.dt.date.unique()):
            r=simulate(f[f.time.dt.date>=day].reset_index(drop=True),threshold=100,reentry='triple_reverse',direction_policy='alternate',initial_signal=args.initial_signal,wait_after_win=args.wait_after_win)
            cohorts.append({'start':str(day),**{k:r[k] for k in ['net_pnl','failure_count','stopped_at']}})
        out['months'][month]={'windows':windows,'daily_start_cohorts':cohorts}
        print(month,{name:{k:r[k] for k in ['net_pnl','total_assets','withdrawn','withdrawal_count','max_level','max_loss_streak','stopped_at']} for name,r in windows.items()})
    out['initial_signal']=args.initial_signal
    if args.initial_signal=='double_reverse':
        out['assumptions']=out['assumptions'].replace('K1 sets first side for K3.', 'Wait two consecutive selected same-colour results then reverse next selected candle; only initial entry changes.')
    if args.initial_signal=='triple_reverse':
        out['assumptions']=out['assumptions'].replace('K1 sets first side for K3.', 'Wait three consecutive selected same-colour results then reverse next selected candle; only initial entry changes.')
    if args.initial_signal=='four_reverse':
        out['assumptions']=out['assumptions'].replace('K1 sets first side for K3.', 'Wait four consecutive selected same-colour results then reverse next selected candle; withdrawal restart still requires three.')
    if args.wait_after_win:
        out['assumptions'] += ' CORRECTION: every win waits for a NEW initial-signal pattern, ignoring all candles up to and including winning candle; withdrawals override with fresh triple.'
    (root/('stride_four_every_win.json' if args.wait_after_win else 'stride_alternate_four_reverse.json' if args.initial_signal=='four_reverse' else 'stride_alternate_triple_reverse.json' if args.initial_signal=='triple_reverse' else 'stride_alternate_double_reverse.json' if args.initial_signal=='double_reverse' else 'stride_alternate_withdraw100.json')).write_text(json.dumps(out,indent=2)+'\n')

if __name__=='__main__': main()
