"""Explicit OHLC-proxy scenarios, not historical Prediction execution."""
import argparse
import json
from decimal import Decimal as D
from pathlib import Path
import pandas as pd
from .prediction_research import recovery_amount


def simulate(frame, ask, entry_streak=2, mode="streak", first_side="UP", base_bet=D("1"), withdraw_profit=None, restart_policy="rest2h", initial_history=None, buy_fee_rate=D("0"), initial_capital=D("100"), multiplier=None):
    if mode not in ("streak", "alternate", "uudd_after_up", "ud_after_down") or first_side not in ("UP", "DOWN"):
        raise ValueError("Invalid direction policy")
    if not isinstance(entry_streak, int) or entry_streak < 2:
        raise ValueError("entry_streak must be an integer >= 2")
    if restart_policy not in ("rest2h", "udud"):
        raise ValueError("Invalid restart policy")
    if multiplier is not None:
        multiplier=D(str(multiplier))
        if not multiplier.is_finite() or multiplier<=1:
            raise ValueError('Multiplier must exceed one')
    base_bet = D(str(base_bet))
    if not base_bet.is_finite() or base_bet <= 0:
        raise ValueError('base_bet must be positive and finite')
    buy_fee_rate = D(str(buy_fee_rate))
    if not buy_fee_rate.is_finite() or not D(0) <= buy_fee_rate < D(1):
        raise ValueError('Invalid buy fee rate')
    effective_ask = ask / (1-buy_fee_rate)
    initial_capital = D(str(initial_capital))
    if not initial_capital.is_finite() or initial_capital <= 0:
        raise ValueError('Invalid initial capital')
    cash, cycle, bet = initial_capital, D('0'), base_bet
    if withdraw_profit is not None:
        withdraw_profit = D(str(withdraw_profit))
        if not withdraw_profit.is_finite() or withdraw_profit <= 0 or mode != 'ud_after_down':
            raise ValueError('Withdrawal requires ud_after_down and positive finite target')
    withdrawn = D('0')
    withdrawals = []
    resume_at = None
    equity_peak = initial_capital
    equity_drawdown = D('0')
    held = None
    history=list(initial_history or []); trades=[]; rounds=[]; peak=initial_capital; drawdown=D('0'); max_level=0; level=1
    failure=None
    pattern_start=None
    signal_from=None
    for index, row in enumerate(frame.itertuples()):
        side='UP' if row.close>row.open else 'DOWN' if row.close<row.open else 'TIE'
        if resume_at is not None and row.time < resume_at:
            history.append(side)
            continue
        if mode in ('uudd_after_up', 'ud_after_down'):
            trigger = 'UP' if mode == 'uudd_after_up' else 'DOWN'
            pattern = ('UP','UP','DOWN','DOWN') if mode == 'uudd_after_up' else ('UP','DOWN')
            signal_ready = bool(history and history[-1] == trigger)
            if signal_from is not None and restart_policy == 'udud':
                signal_ready = len(history)-signal_from >= 4 and history[-4:] == ['UP','DOWN','UP','DOWN']
            if pattern_start is None and signal_ready:
                pattern_start = index
            if pattern_start is not None:
                held = pattern[(index-pattern_start) % len(pattern)]
        if mode == 'alternate':
            held = first_side if index % 2 == 0 else ('DOWN' if first_side == 'UP' else 'UP')
        if mode == 'streak' and held is None and len(history)>=entry_streak and len(set(history[-entry_streak:]))==1 and history[-1]!='TIE':
            held='DOWN' if history[-1]=='UP' else 'UP'
        if held is not None:
            if bet>cash:
                failure=str(row.time); break
            # Explicit neutral/refund scenario for doji, not a claimed platform rule.
            if side=='TIE':
                history.append(side)
                continue
            before=cash
            pnl=(bet*((1-buy_fee_rate)/ask-1)).quantize(D('0.00000001')) if side==held else -bet
            cash+=pnl; cycle+=pnl; max_level=max(max_level,level)
            peak=max(peak,cash); drawdown=max(drawdown,peak-cash)
            equity_peak=max(equity_peak,cash+withdrawn)
            equity_drawdown=max(equity_drawdown,equity_peak-cash-withdrawn)
            trades.append({'time':str(row.time),'direction':held,'proxy_result':side,'level':level,
                           'stake':float(bet),'assumed_entry_price':float(ask),'assumed_fees':float(bet*buy_fee_rate), 'gross_shares':float(bet/ask), 'fee_shares':float(bet/ask*buy_fee_rate), 'net_shares':float(bet/ask*(1-buy_fee_rate)),
                           'pnl':float(pnl),'balance_before':float(before),'balance_after':float(cash)})
            if withdraw_profit is not None and cash >= initial_capital + withdraw_profit:
                amount = cash-initial_capital
                withdrawn += amount
                cash = initial_capital
                settled_at = row.time + pd.Timedelta(minutes=5)
                resume_at = settled_at + pd.Timedelta(hours=2 if restart_policy == 'rest2h' else 0)
                signal_from = len(history) + 1
                withdrawals.append({'time':str(settled_at),'amount':float(amount),'total_withdrawn':float(withdrawn),'resume_not_before':str(resume_at),'balance_after':float(initial_capital)})
                pattern_start = None
            if cycle>0:
                rounds.append(float(cycle)); held=None; cycle=D('0'); level=1; bet=base_bet
            else:
                level+=1
                # Hold-to-settlement scenario: exit payout 1, no assumed 95% exit.
                bet=(bet*multiplier).quantize(D('.01'),rounding='ROUND_CEILING') if multiplier is not None else recovery_amount(-cycle,effective_ask,D('0'),target=base_bet,exit_price=D('1'))
        history.append(side)
    days=(frame.time.iloc[-1]-frame.time.iloc[0]).total_seconds()/86400+5/1440
    daily={str(t.date()):0.0 for t in frame.time}
    for trade in trades: daily[trade['time'][:10]]+=trade['pnl']
    alive_hours=((pd.Timestamp(failure)-frame.time.iloc[0]).total_seconds()/3600 if failure and not failure.startswith('UNAVAILABLE') else None)
    return {'assumptions':{'entry_price':float(ask),'buy_fee_rate':float(buy_fee_rate),'fees':'buy fee deducted in shares; cash budget includes fee' if buy_fee_rate else 0,'exit':'final payout 1 or 0',
                           'signals':'spot candle colour; immediate next candle entry assumed', 'entry_streak':entry_streak if mode=='streak' else None,
                           'withdraw_profit':float(withdraw_profit) if withdraw_profit is not None else None, 'restart_policy':restart_policy if withdraw_profit is not None else None, 'cooldown_hours':2 if withdraw_profit is not None and restart_policy=='rest2h' else 0, 'withdrawal_rule':'withdraw excess over initial capital; no top-ups; udud policy requires four post-withdrawal closed candles UDUD, then restart UP; rest2h policy waits two hours and previous DOWN' if withdraw_profit is not None else None,
                           'multiplier':float(multiplier) if multiplier is not None else None, 'sizing':'fixed multiplier until positive round PnL' if multiplier is not None else 'fee-aware recovery',
                           'direction_policy':mode, 'base_bet':float(base_bet), 'recovery_profit_target':float(base_bet),
                           'activation':'previous closed candle UP, once only; phase advances every period and does not reset on profit' if mode=='uudd_after_up' else 'previous closed candle DOWN, once only; fixed UD phase does not reset on profit' if mode=='ud_after_down' else None, 'first_side':first_side if mode=='alternate' else None,
                           'tie':'assumed refund, no trade counted, retain pending sequence','early_rollover':'unavailable','95_exit':'unavailable'},
            'initial_balance':float(initial_capital),'final_balance':float(cash),'total_pnl':float(cash+withdrawn-initial_capital),
            'return_pct':float((cash+withdrawn-initial_capital)/initial_capital*100),'daily_pnl_full_sample':float(cash+withdrawn-initial_capital)/days,
            'trades':len(trades),'daily_trades_full_sample':len(trades)/days,
            'win_rate':sum(t['pnl']>0 for t in trades)/len(trades) if trades else None,
            'completed_rounds':len(rounds),'average_round_profit':sum(rounds)/len(rounds) if rounds else None,
            'withdrawn':float(withdrawn),'total_assets':float(cash+withdrawn),'withdrawal_count':len(withdrawals),'withdrawals':withdrawals,
            'peak_total_assets':float(equity_peak),'max_total_asset_drawdown':float(equity_drawdown),
            'peak_balance':float(peak), 'max_level':max_level,'max_drawdown_usdt':float(equity_drawdown),
            'failure':failure,'hours_to_failure':alive_hours,'daily_pnl':daily,'trade_log':trades}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry-streak', type=int, default=2)
    parser.add_argument('--mode', choices=['streak','alternate','uudd_after_up','ud_after_down'], default='streak')
    parser.add_argument('--first-side', choices=['UP','DOWN'], default='UP')
    parser.add_argument('--base-bet', type=D, default=D('1'))
    parser.add_argument('--withdraw-profit', type=D)
    parser.add_argument('--restart-policy', choices=['rest2h','udud'], default='rest2h')
    parser.add_argument('--prices', nargs='+', default=['0.5','0.6'])
    args=parser.parse_args()
    root=Path('experiments/prediction_btc5m')
    raw=pd.read_csv(root/'BTCUSDT-5m-2026-08.csv',header=None)
    frame=pd.DataFrame({'time':pd.to_datetime(raw[0],unit='us',utc=True),'open':raw[1],'close':raw[4]})
    if not frame.time.diff().dropna().eq(pd.Timedelta(minutes=5)).all(): raise ValueError('Non-contiguous candles')
    output={'label':'HYPOTHETICAL_EXECUTION_ON_REAL_SPOT_COLOURS_NOT_PREDICTION_PNL','scenarios':{}}
    for price in args.prices:
        result=simulate(frame,D(price),args.entry_streak,args.mode,args.first_side,args.base_bet,args.withdraw_profit,args.restart_policy)
        starts=[]
        for day in sorted(frame.time.dt.date.unique()):
            sample=frame[frame.time.dt.date>=day].reset_index(drop=True)
            r=simulate(sample,D(price),args.entry_streak,args.mode,args.first_side,args.base_bet,args.withdraw_profit,args.restart_policy)
            starts.append({'start':str(day),'final_balance':r['final_balance'],'failure':r['failure'],'hours_to_failure':r['hours_to_failure'],'peak_balance':r['peak_balance'],'withdrawn':r['withdrawn'],'total_assets':r['total_assets'],'total_pnl':r['total_pnl']})
        result['daily_start_cohorts']=starts
        output['scenarios'][price]=result
    if args.mode in ('uudd_after_up', 'ud_after_down'):
        name = f'scenario_report_{args.mode}'
    elif args.mode == 'alternate':
        name = f'scenario_report_alternate_{args.first_side.lower()}'
    else:
        name = 'scenario_report' if args.entry_streak == 2 else f'scenario_report_streak{args.entry_streak}'
    if args.base_bet != D('1'):
        name += '_base' + format(args.base_bet.normalize(), 'f').replace('.', 'p')
    if args.withdraw_profit is not None:
        name += '_withdraw' + format(args.withdraw_profit.normalize(), 'f').replace('.', 'p') + '_' + args.restart_policy
    (root/(name+'.json')).write_text(json.dumps(output,indent=2)+'\n')
    for k,v in output['scenarios'].items(): print(k,{a:b for a,b in v.items() if a not in ['trade_log','daily_pnl','daily_start_cohorts']})

if __name__=='__main__': main()
