# Strategy1 Martingale Experiment

This experiment is historical-backtest only. It has empty exchange keys, `dry_run=true`,
and does not use the application's existing Dry-run database.

## Rules tested

- Five concurrent isolated-margin projects: BTC, ETH, SOL, BNB, XRP.
- 20x leverage and 50 USDT initial margin per project.
- Trend entry: EMA7/EMA25 direction plus EMA200, EMA gap, EMA25 slope, ADX, ATR,
  and three-candle confirmation.
- Whole-trade net margin ROI take-profit: +10%.
- Whole-trade net margin ROI stop: -30%; 300 USDT absolute project-loss backstop.
- Full ladder: 50 + 100 + 200 + 400 + 250 USDT, capped at 1000 USDT.
- Adds require whole-trade ROI <= -20% and at least three minutes since the last fill.

## 30-day five-pair result

Timerange: `20260713-20260812`; wallet: 5000 USDT; max open trades: 5.

| Variant | Profit | Max drawdown | Win rate | Profit factor | Payoff ratio | Trades | Estimated fees |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed 50 USDT | -9.65% | 10.64% | 70.5% | 0.78 | 0.325 | 474 | 471.67 USDT |
| One 100 USDT add | -19.21% | 20.57% | 81.2% | 0.75 | 0.173 | 447 | 818.24 USDT |
| Full martingale | -56.03% | 57.01% | 91.5% | 0.68 | 0.063 | 377 | 1744.39 USDT |

The full ladder made 5862.56 USDT on 345 ROI exits, but lost 8342.20 USDT on only
28 stop exits. High win rate did not compensate for the growing stake on losing trades.

## Reproduce

```bash
cd /Users/xumingda/Desktop/量化
.venv/bin/python experiments/strategy1_optimization/run_martingale_experiment.py
```

Use `--summarize-only` to rebuild the CSV from the latest existing result without rerunning.

Status: candidate only; not copied to the application strategy, not started in Dry-run.
