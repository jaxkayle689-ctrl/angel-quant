"""Fresh selected triple then fixed opposite side until win."""
import json
from pathlib import Path
import pandas as pd
from .prediction_stride_backtest import simulate


def main():
    root=Path('experiments/prediction_btc5m')
    out={'assumptions':'300 initial; 1.5 strict doubling; single odd UTC candle sequence. Three NEW same selected colours then opposite side; hold direction after loss until win. Every win waits three NEW colours excluding winning candle; withdrawal also waits three. Withdraw excess over 300 once profit >=100; no reserve refill after failure. Ideal full fills .50, zero fees, ties refunded (fixed direction unchanged). Actual Prediction fills and fees unavailable.', 'months':{}}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        frame=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        if not frame.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all(): raise ValueError('Gaps')
        def run(f):
            return simulate(f,threshold=100,reentry='triple_reverse',direction_policy='persistent',initial_signal='triple_reverse',wait_after_win=True)
        windows={name:run(frame.iloc[:n]) for name,n in [('day',288),('week',2016),('month',len(frame))]}
        cohorts=[]
        for day in sorted(frame.time.dt.date.unique()):
            r=run(frame[frame.time.dt.date>=day].reset_index(drop=True))
            cohorts.append({'start':str(day),**{k:r[k] for k in ['net_pnl','failure_count','stopped_at']}})
        out['months'][month]={'windows':windows,'daily_start_cohorts':cohorts}
        print(month,{name:{k:r[k] for k in ['net_pnl','total_assets','withdrawn','final_risk_balance','max_level','max_loss_streak','stopped_at']} for name,r in windows.items()})
    (root/'stride_three_fixed_reverse.json').write_text(json.dumps(out,indent=2)+'\n')

if __name__=='__main__': main()
