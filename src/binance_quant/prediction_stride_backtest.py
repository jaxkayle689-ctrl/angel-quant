"""Ideal-fill mathematical scenarios; never actual Prediction execution."""
import json
from decimal import Decimal as D
from pathlib import Path
import pandas as pd


def simulate(frame, threshold=15, reentry='alternating', direction_policy='persistent', initial_signal='previous', wait_after_win=False, initial_capital=300):
    initial_capital=D(str(initial_capital))
    if not initial_capital.is_finite() or initial_capital<=0: raise ValueError('Invalid capital')
    if initial_signal not in ('previous','double_reverse','triple_reverse','four_reverse'): raise ValueError('Unknown initial signal')
    if direction_policy not in ('persistent','alternate'): raise ValueError('Unknown direction policy')
    if reentry not in ('alternating','mixed','triple_reverse'): raise ValueError('Unknown reentry')
    selected=frame.iloc[::2]
    cash=initial_capital; withdrawn=D(0); stake=D('1.5'); held=None
    history=[]; waiting=False; failures=0; max_failures=0; max_level=0; peak=initial_capital; dd=D(0)
    trades=[]; withdrawals=[]; stopped=None; ties=0
    for row in selected.itertuples():
        side='UP' if row.close>row.open else 'DOWN' if row.close<row.open else 'TIE'
        if waiting:
            tail=history[-3:]
            valid=len(tail)==3 and 'TIE' not in tail and (tail in [['UP','DOWN','UP'],['DOWN','UP','DOWN']] if reentry=='alternating' else len(set(tail))==1 if reentry=='triple_reverse' else len(set(tail))>1)
            if valid:
                waiting=False
                held=('DOWN' if history[-1]=='UP' else 'UP') if reentry=='triple_reverse' else history[-1]
        elif held is None and history and history[-1]!='TIE':
            if initial_signal=='previous': held=history[-1]
            else:
                needed={'double_reverse':2,'triple_reverse':3,'four_reverse':4}[initial_signal]
                if len(history)>=needed and len(set(history[-needed:]))==1:
                    held='DOWN' if history[-1]=='UP' else 'UP'
        if held is not None and not waiting:
            if stake>cash:
                stopped=str(row.time); break
            if side=='TIE':
                ties+=1 # explicit refund assumption; amount unchanged
                if direction_policy=='alternate': held='DOWN' if held=='UP' else 'UP'
            else:
                bet_side=held
                win=side==held; pnl=stake if win else -stake
                cash+=pnl; max_level=max(max_level,failures+1)
                peak=max(peak,cash+withdrawn); dd=max(dd,peak-cash-withdrawn)
                trades.append({'target_open':str(row.time),'direction':held,'outcome_proxy':side,'stake':float(stake),'pnl':float(pnl),'balance_after':float(cash)})
                if win: stake=D('1.5'); held=None; failures=0
                else: stake*=2; failures+=1; max_failures=max(max_failures,failures)
                if direction_policy=='alternate' and not (win and wait_after_win): held='DOWN' if bet_side=='UP' else 'UP'
                if cash>=initial_capital+D(threshold):
                    amount=cash-initial_capital; withdrawn+=amount; cash=initial_capital
                    withdrawals.append({'time':str(row.time+pd.Timedelta(minutes=5)),'amount':float(amount)})
                    waiting=True; held=None; history=[]
                    # Restart observation starts AFTER withdrawal candle.
                    continue
                if win and wait_after_win:
                    history=[]
                    continue
        history.append(side)
    duration=(frame.time.iloc[-1]-frame.time.iloc[0]+pd.Timedelta(minutes=5)).total_seconds()/86400
    return {'initial':float(initial_capital),'final_risk_balance':float(cash),'withdrawn':float(withdrawn),'total_assets':float(cash+withdrawn),'net_pnl':float(cash+withdrawn-initial_capital),'daily_pnl_over_entire_window':float((cash+withdrawn-initial_capital)/D(str(duration))), 'trades':len(trades),'trades_per_day':len(trades)/duration,'withdrawal_count':len(withdrawals),'max_loss_streak':max_failures,'max_level':max_level,'max_total_asset_drawdown':float(dd),'failure_count':int(stopped is not None),'stopped_at':stopped,'ties_assumed_refunded':ties,'trade_log':trades,'withdrawal_log':withdrawals}


def main():
    root=Path('experiments/prediction_btc5m'); output={'label':'IDEAL FULL FILL .50 ZERO FEE; actual fills/fees unavailable','assumptions':'Single odd UTC sequence; same direction after loss until win; after win new direction from latest closed selected candle. No reserve recycling after failure. Ties refunded. Reentry rules are unconfirmed alternatives.','scenarios':{}}
    for month in ['2026-06','2026-07','2026-08']:
        raw=pd.read_csv(root/f'BTCUSDT-5m-{month}.csv',header=None)
        f=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
        if not f.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all(): raise ValueError('Gaps')
        for rule in ['alternating','mixed']:
            for threshold in [15,30,45,60]:
                key=f'{month}_{rule}_{threshold}'; results={}
                for name,days in [('day',1),('week',7),('month',len(f)/288)]:
                    r=simulate(f.iloc[:int(days*288)],threshold,rule); results[name]=r
                output['scenarios'][key]=results
                print(key,[(name,r['net_pnl'],r['stopped_at']) for name,r in results.items()])
    (root/'stride_persistent_direction.json').write_text(json.dumps(output,indent=2)+'\n')

if __name__=='__main__': main()
