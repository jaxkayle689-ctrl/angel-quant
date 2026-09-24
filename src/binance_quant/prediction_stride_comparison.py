"""Development-sample comparison, never an optimized live recommendation."""
import json
from pathlib import Path
import pandas as pd
from .prediction_stride_backtest import simulate


def main():
    root=Path('experiments/prediction_btc5m');frames={};stats={}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        f=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]});frames[month]=f
        s=['U' if c>o else 'D' if c<o else 'T' for o,c in zip(f.iloc[::2].open,f.iloc[::2].close)]
        stats[month]={}
        for k in range(2,11):
            stats[month][k]={}
            for side in ['U','D']:
                idx=[i for i in range(k,len(s)) if s[i-k:i]==[side]*k]
                stats[month][k][side]={'n':len(idx),'reverse':sum(s[i] not in [side,'T'] for i in idx),'continue':sum(s[i]==side for i in idx),'tie':sum(s[i]=='T' for i in idx)}
    candidates=[]
    for signal in ['double_reverse','triple_reverse','four_reverse']:
        for threshold in [15,30,45,60,100,150]:
            results={}
            for month,f in frames.items():
                r=simulate(f,threshold=threshold,reentry='triple_reverse',direction_policy='persistent',initial_signal=signal,wait_after_win=True)
                results[month]={k:r[k] for k in ['net_pnl','total_assets','withdrawn','failure_count','stopped_at','max_loss_streak','max_level','max_total_asset_drawdown','trades']}
            candidates.append({'signal':signal,'threshold':threshold,'months':results,'total_pnl_three_independent_accounts':sum(x['net_pnl'] for x in results.values()),'failures':sum(x['failure_count'] for x in results.values()),'worst_month_pnl':min(x['net_pnl'] for x in results.values())})
    output={'label':'18 development candidates, not independent validation. Each month resets to 300. Withdrawal gate always fresh triple. Zero fee, .50 full fills, fixed opposite till win, strict doubling, no reserve reuse.','statistics':stats,'candidates':candidates}
    (root/'stride_math_comparison.json').write_text(json.dumps(output,indent=2)+'\n')
    for c in sorted(candidates,key=lambda x:x['total_pnl_three_independent_accounts'],reverse=True):
        print(c['signal'],c['threshold'],c['total_pnl_three_independent_accounts'],[v['net_pnl'] for v in c['months'].values()],c['failures'])
    for side in ['U','D']:
        print(side,'3-continuation',[(m,stats[m][3][side]) for m in frames])

if __name__=='__main__':main()
