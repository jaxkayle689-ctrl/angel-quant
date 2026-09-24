# Strategy1 Optimization Results

All runs in this report are historical Freqtrade backtests with empty exchange
keys and `dry_run=true`.  No live-trading process was started and the existing
Dry-run database was not used.

## Why the old strategy lost

The old 1m EMA7/EMA25 strategy emitted a position on nearly every candle and
reversed whenever the EMAs crossed.  During sideways markets this created many
short-lived flips, repeated taker fees, false breakouts, and losses larger than
the +3% target.  In the 30-day baseline BTC, ETH, and SOL runs, account drawdown
approached 99%.

Martingale changed the shape of the result rather than fixing the signal.  The
30-day five-pair full ladder reached a 91.5% win rate, but the small number of
fully averaged losing trades erased the frequent wins:

| Variant | Return | Max DD | Win rate | PF | Payoff | Trades | Fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Filtered fixed 50 USDT | -9.65% | 10.64% | 70.5% | 0.78 | 0.325 | 474 | 471.67 |
| One 100 USDT add | -19.21% | 20.57% | 81.2% | 0.75 | 0.173 | 447 | 818.24 |
| Full 50+100+200+400+250 | -56.03% | 57.01% | 91.5% | 0.68 | 0.063 | 377 | 1744.39 |

The full ladder put the largest stake into the trades with the weakest evidence.
It is therefore not enabled in the formal strategy.

## Selected strategy

- 1m execution with 5m and 15m trend context.
- 20x isolated leverage and 50 USDT initial margin.
- 5m EMA7/EMA25/EMA100 alignment and slope filter.
- 15m EMA20/EMA60 alignment, slope, and trend-age limit.
- Actual 1m EMA7 reclaim after a pullback, not continuous EMA direction.
- EMA-distance, ATR-distance, volume, and ADX quality filters.
- Long entries use the stricter ADX thresholds found by ablation: 30 on 5m and 25 on 15m.
- Short entries keep 25 on 5m and 20 on 15m; tightening shorts reduced profit.
- Margin ROI target +15% and net margin ROI loss target approximately -25%.
- Freqtrade uses native `stoploss=-0.23`; at 20x, two 0.05% taker fees bring
  the closed-trade loss close to -25% net ROI.
- No reversal exit and no default position adjustment.

Freqtrade futures `minimal_roi` and `stoploss` are leverage-adjusted trade
returns.  They are margin ROI values, not underlying-price percentages.

## Six-month result

Timerange: `20260210-20260812`; wallet: 5000 USDT; five concurrent pairs:
BTC, ETH, SOL, BNB, XRP.

| Return | Max DD | Win rate | PF | Payoff | Trades | Fees | Long PnL | Short PnL |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| +4.74% | 3.69% | 64.55% | 1.095 | 0.601 | 567 | 563.36 | -12.81 | +249.71 |

Average winner was 7.46 USDT and average loser was 12.40 USDT.  There were 366
ROI exits and 201 native stop-loss exits.  The worst backtested trade was
-26.10% net ROI after fees and candle-level fill simulation.

| Pair | Trades | PnL USDT | Win rate |
| --- | ---: | ---: | ---: |
| BTC | 80 | -138.74 | 53.75% |
| ETH | 129 | +187.02 | 69.77% |
| SOL | 150 | +87.35 | 65.33% |
| BNB | 87 | -86.48 | 57.47% |
| XRP | 121 | +187.76 | 70.25% |

BTC and BNB remain negative and should not be treated as validated profitable
sub-strategies.  The portfolio edge is modest, with PF only 1.095.

## Monthly validation

| Window | Return | Max DD | Trades | Win rate | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-02-10 to 03-10 | -0.67% | 3.69% | 99 | 60.6% | 0.93 |
| 2026-03-10 to 04-10 | +2.10% | 2.11% | 110 | 67.3% | 1.23 |
| 2026-04-10 to 05-10 | +0.40% | 2.35% | 64 | 64.1% | 1.07 |
| 2026-05-10 to 06-10 | +1.37% | 2.96% | 113 | 65.5% | 1.14 |
| 2026-06-10 to 07-10 | -0.32% | 2.71% | 109 | 61.5% | 0.97 |
| 2026-07-10 to 08-12 | +1.60% | 1.48% | 72 | 68.1% | 1.28 |

The controlled one-add candidate, which adds 100 USDT only at -15% ROI while
both higher-timeframe trends remain valid, fired only five times in six months.
Its evidence was too sparse and month-dependent to enable by default.  The code
remains in `strategies/strategy1_candidates.py` for future Dry-run research.

## Consistency and artifacts

The formal desktop and Freqtrade strategies were compared on 50,000 ETH 1m
candles using the same 5m/15m frames.  Both emitted 15 long and 19 short events,
with zero candle-level mismatches.

Formal six-month result:
`formal_calibrated_results/backtest-result-2026-08-12_20-54-37.zip`

Monthly results:
`formal_monthly_results/`

Martingale baseline:
`martingale_results/portfolio5/summary.csv`

Status: formal strategy updated for historical backtest and Dry-run only.  No
real-funds trading was enabled.
