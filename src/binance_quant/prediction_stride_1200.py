"""1200 capital, fresh double reverse, fixed side until win, withdrawal100."""
import argparse
import json
from pathlib import Path
import pandas as pd
from .prediction_stride_backtest import simulate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--capital',type=int,default=1200)
    args=parser.parse_args()
    root=Path('experiments/prediction_btc5m');out={'assumptions':'1200 initial only; base1.5 double after loss, fixed opposite side until win. Initial and every ordinary win wait two NEW same-colour selected candles. Withdraw excess over1200 at profit>=100; then wait three NEW same-colour selected candles. Odd UTC sequence, no reserve refill at failure. Ideal .50 all fills zero fee, ties assumed refund.', 'months':{}}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        f=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        if not f.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all(): raise ValueError('Gaps')
        def run(frame):
            return simulate(frame,threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='double_reverse',wait_after_win=True,initial_capital=args.capital)
        windows={n:run(f.iloc[:k]) for n,k in [('day',288),('week',2016),('month',len(f))]}
        cohorts=[]
        for day in sorted(f.time.dt.date.unique()):
            r=run(f[f.time.dt.date>=day].reset_index(drop=True));cohorts.append({'start':str(day),**{k:r[k] for k in ['net_pnl','failure_count','stopped_at']}})
        out['months'][month]={'windows':windows,'daily_start_cohorts':cohorts}
        print(month,{n:{k:r[k] for k in ['net_pnl','total_assets','withdrawn','final_risk_balance','withdrawal_count','max_level','max_loss_streak','stopped_at']} for n,r in windows.items()})
    out['assumptions']=out['assumptions'].replace('1200',str(args.capital))
    (root/f'stride{args.capital}_double_reverse.json').write_text(json.dumps(out,indent=2)+'\n')

if __name__=='__main__':main()
