"""Frozen-rule cross-month proxy checks, no parameter selection."""
import json
from decimal import Decimal as D
from pathlib import Path
import pandas as pd
from .prediction_month import run_month


def main():
    root=Path('experiments/prediction_btc5m')
    results={}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        frame=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        if frame.time.duplicated().any() or not frame.time.is_monotonic_increasing:
            raise ValueError('Duplicate or unordered candles')
        results[month]={'role':'development' if month=='2026-08' else 'new_validation_proxy', 'candles':len(frame),'scenarios':{}}
        for label,fee in [('taker_2pct',D('.02')),('ideal_maker_zero_fee',D('0'))]:
            r=run_month(frame,recycle_only=True,ask=D('.5'),buy_fee_rate=fee,initial_capital=D('300'),base_bet=D('1.5'),withdraw_profit=D('50'))
            r['execution_status']='unavailable; ALL entries assumed filled instantly at .50; maker case not executable evidence'
            cohorts=[]
            for day in sorted(frame.time.dt.date.unique()):
                sub=frame[frame.time.dt.date>=day].reset_index(drop=True)
                c=run_month(sub,recycle_only=True,ask=D('.5'),buy_fee_rate=fee,initial_capital=D('300'),base_bet=D('1.5'),withdraw_profit=D('50'))
                cohorts.append({k:c[k] for k in ['start','net_pnl','total_assets','completed_month','stopped_insufficient_total_funds_at']})
            r['daily_start_cohorts']=cohorts
            results[month]['scenarios'][label]=r
            print(month,label,r['total_assets'],r['net_pnl'],r['stopped_insufficient_total_funds_at'])
    (root/'validation300_frozen.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__': main()
