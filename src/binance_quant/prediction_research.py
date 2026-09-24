"""BTC direction research only: never infer Prediction fills from OHLC."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

import pandas as pd


def recovery_amount(loss: Decimal, ask: Decimal, fee_per_usdt: Decimal,
                    target: Decimal = Decimal('1'), exit_price: Decimal = Decimal('.95')) -> Decimal:
    """Indicative budget, not a quote. fee_per_usdt includes both legs.

    Caller must obtain actual depth/fees and check available balance before ordering.
    """
    if loss < 0 or not 0 < ask < 1 or not 0 < exit_price <= 1 or fee_per_usdt < 0 or target <= 0:
        raise ValueError('Invalid sizing inputs')
    margin = exit_price / ask - 1 - fee_per_usdt
    if margin <= 0:
        raise ValueError('No positive recovery margin')
    return ((loss + target) / margin).quantize(Decimal('.01'), rounding=ROUND_CEILING)


def early_rollover_due(seconds_left: float, opponent_bid: Decimal) -> bool:
    """Signal only; pending positions must not be booked as losses."""
    return 0 < seconds_left <= 10 and Decimal('.90') <= opponent_bid <= 1


def analyze(frame: pd.DataFrame) -> dict:
    frame = frame.sort_values('open_time').reset_index(drop=True)
    if frame.empty or frame.open_time.duplicated().any():
        raise ValueError('Empty or duplicate candles')
    if not frame[['open', 'close']].apply(lambda c: c.gt(0) & c.lt(float('inf'))).all().all():
        raise ValueError('Invalid prices')
    directions = ['UP' if c > o else 'DOWN' if c < o else 'TIE'
                  for o, c in zip(frame.open, frame.close)]
    runs = {'UP': Counter(), 'DOWN': Counter()}
    opportunities = {s: {k: Counter() for k in range(2, 9)} for s in runs}
    previous, length, gaps = None, 0, 0
    for i, side in enumerate(directions):
        gap = i > 0 and frame.open_time.iloc[i] - frame.open_time.iloc[i-1] != pd.Timedelta(minutes=5)
        if gap:
            gaps += 1
        if gap or side == 'TIE' or side != previous:
            if previous in runs:
                runs[previous][length] += 1
            previous, length = (None, 0) if side == 'TIE' else (side, 1)
        else:
            length += 1
        if side in runs and i + 1 < len(directions) and frame.open_time.iloc[i+1] - frame.open_time.iloc[i] == pd.Timedelta(minutes=5):
            # At least k consecutive results; overlapping eligible windows included.
            for k in range(2, min(length, 8) + 1):
                opportunities[side][k][directions[i+1]] += 1
    if previous in runs:
        runs[previous][length] += 1
    conditional = {}
    for side, by_k in opportunities.items():
        conditional[side] = {}
        for k, counts in by_k.items():
            n = sum(counts.values())
            opposite = 'DOWN' if side == 'UP' else 'UP'
            conditional[side][str(k)] = {'samples': n, 'continue': counts[side]/n if n else None,
                'reverse': counts[opposite]/n if n else None, 'tie': counts['TIE']/n if n else None}
    unavailable = ['final_balance','total_pnl','return_pct','daily_pnl','daily_trade_count',
        'trade_count','win_rate','completed_martingale_rounds','average_round_profit',
        'max_martingale_level','max_round_loss','max_drawdown','max_drawdown_duration',
        'longest_losing_streak','insufficient_balance_count','strategy_failure',
        'take_profit_triggers','take_profit_fills','take_profit_pnl','settlement_pnl',
        'survival_duration','daily_return_distribution']
    return {'data_kind':'BTC_SPOT_OHLC_PROXY_NOT_PREDICTION', 'candles':len(frame),
        'start':str(frame.open_time.iloc[0]), 'end':str(frame.open_time.iloc[-1]+pd.Timedelta(minutes=5)),
        'gaps':gaps,'ties':directions.count('TIE'), 'initial_budget_usdt':100,
        'streak_count_definition':'maximal runs; sample boundaries may censor runs; at_least counts each run once',
        'streaks': {s: {'longest':max(c, default=0),
            'exact':{str(k):c[k] for k in range(3,13)},
            'at_least':{str(k):sum(n for length,n in c.items() if length>=k) for k in range(3,13)}} for s,c in runs.items()},
        'conditional_at_least_k':conditional,
        'prediction_backtest': {k:'unavailable' for k in unavailable},
        'reason':'Prediction settlements, executable historical quotes/depth and fees unavailable. No PnL simulation performed.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binance-csv',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    raw=pd.read_csv(args.binance_csv,header=None)
    unit='us' if int(raw.iloc[0,0])>10**14 else 'ms'
    frame=pd.DataFrame({'open_time':pd.to_datetime(raw[0],unit=unit,utc=True),
                        'open':pd.to_numeric(raw[1]),'close':pd.to_numeric(raw[4])})
    if (frame.open_time+pd.Timedelta(minutes=5)>pd.Timestamp.now(tz='UTC')).any():
        raise ValueError('Unclosed candles')
    output=Path(args.output); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(analyze(frame),indent=2,ensure_ascii=False)+'\n')
    print(output)


if __name__=='__main__':
    main()
