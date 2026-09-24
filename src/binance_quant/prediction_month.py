"""Monthly proxy replay with explicitly accounted external capital replenishments."""
import argparse
import json
from decimal import Decimal as D
from pathlib import Path
import pandas as pd
from .prediction_scenario import simulate


def run_month(frame, recycle_only=False, ask=D(".5"), buy_fee_rate=D("0"), initial_capital=D("100"), base_bet=D(".5"), withdraw_profit=D("50"), multiplier=None):
    if frame.empty or not frame.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all():
        raise ValueError('Need contiguous five-minute candles')
    initial_capital=D(str(initial_capital))
    offset=0
    sessions=[]
    reserve=D(0)
    stopped=None
    while offset < len(frame):
        seed=[]
        if offset:
            prev=frame.iloc[offset-1]
            seed=['UP' if prev.close>prev.open else 'DOWN' if prev.close<prev.open else 'TIE']
        r=simulate(frame.iloc[offset:].reset_index(drop=True),ask,mode='ud_after_down',base_bet=base_bet,withdraw_profit=withdraw_profit,restart_policy='udud',initial_history=seed,buy_fee_rate=buy_fee_rate,initial_capital=initial_capital,multiplier=multiplier)
        r['funded_at']=str(frame.time.iloc[offset]); r['session_id']=len(sessions)+1
        sessions.append(r)
        reserve += D(str(r['withdrawn']))
        r['reserve_after_withdrawals'] = float(reserve)
        if r['failure'] is None:
            break
        if recycle_only:
            reserve += D(str(r['final_balance']))
            r['reserve_after_failure'] = float(reserve)
            if reserve < initial_capital:
                stopped = r['failure']
                break
            reserve -= initial_capital
            r['reserve_after_restart_allocation'] = float(reserve)
        next_offset=int(frame.index[frame.time==pd.Timestamp(r['failure'])][0])
        if next_offset<=offset:
            raise RuntimeError('Restart made no progress')
        offset=next_offset  # Failed order was NOT filled: this candle can be traded by new account.
    invested=initial_capital if recycle_only else initial_capital*len(sessions)
    withdrawn=sum((D(str(r['withdrawn'])) for r in sessions),D(0))
    residual=sum((D(str(r['final_balance'])) for r in sessions if r['failure']),D(0))
    active=sum((D(str(r['final_balance'])) for r in sessions if not r['failure']),D(0))
    total_assets=reserve+active if recycle_only else withdrawn+residual+active
    pnl=total_assets-invested
    logs=[{**t,'session_id':r['session_id']} for r in sessions for t in r['trade_log']]
    if len({t['time'] for t in logs})!=len(logs): raise AssertionError('Duplicate candle traded')
    if abs(sum((D(str(t['pnl'])) for t in logs),D(0)) - pnl) > D('0.000001'): raise AssertionError('Ledger mismatch')
    daily={str(day):D(0) for day in frame.time.dt.date.unique()}
    for t in logs: daily[t['time'][:10]]+=D(str(t['pnl']))
    return {'label':'REAL_SPOT_COLOURS_WITH_HYPOTHETICAL_EXECUTION',
        'assumptions':sessions[0]['assumptions'],
        'funding_policy':'recycle_only' if recycle_only else 'external_refill',
        'reserve_balance':float(reserve) if recycle_only else None,'stopped_insufficient_total_funds_at':stopped,
        'completed_month':stopped is None,
        'restart_rule':'Pool withdrawals and residual; allocate initial capital only if available; no external additions; reset stake and phase, wait previous DOWN.' if recycle_only else 'At failure add NEW external initial capital, segregate old residual; reset stake and UD phase, wait previous closed DOWN. No withdrawal money recycled.',
        'start':str(frame.time.iloc[0]),'end':str(frame.time.iloc[-1]+pd.Timedelta(minutes=5)),
        'capital_injections':1 if recycle_only else len(sessions),'additional_injections':0 if recycle_only else len(sessions)-1,'account_sessions':len(sessions),'internal_restarts':len(sessions)-1 if recycle_only else 0,'total_invested':float(invested),
        'failures':sum(bool(r['failure']) for r in sessions),'withdrawal_count':sum(r['withdrawal_count'] for r in sessions),
        'withdrawn':float(withdrawn),'withdrawn_definition':'cumulative transfers; may have been reused, not current reserve','segregated_residual':None if recycle_only else float(residual),'active_balance':float(active),
        'total_assets':float(total_assets),'net_pnl':float(pnl),
        'return_on_total_injected_pct':float(pnl/invested*100),'mean_daily_pnl':float(pnl/len(daily)),
        'daily_pnl':{k:float(v) for k,v in daily.items()},'trades':len(logs),'sessions':sessions}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recycle-only',action='store_true')
    args=parser.parse_args()
    root=Path('experiments/prediction_btc5m')
    raw=pd.read_csv(root/'BTCUSDT-5m-2026-08.csv',header=None)
    frame=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
    result=run_month(frame,recycle_only=args.recycle_only)
    (root/('monthly_recycle_udud.json' if args.recycle_only else 'monthly_refill_udud.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['sessions','daily_pnl','assumptions']},indent=2))

if __name__=='__main__': main()
