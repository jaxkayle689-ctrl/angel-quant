# 300 USDT candidate assessment

Research only, no live orders or deposits. Preserve UD after prior DOWN, progressive recovery, positive round reset, withdrawal followed by four new closed UDUD, internal reserve recycling only.

New capital parameter: 300. Base stake: 1.5. Prospective taker fee 2% at assumed price 0.50. Same August spot-colour proxy, immediate fills/settlement, ties refunded. 1.5 is only an approximate API MARKET minimum, not guaranteed executable. Current fee schedule is not verified historical account fees.

| Withdrawal profit threshold | Final assets | Net PnL | Failures | Stopped UTC |
|---|---:|---:|---:|---|
| 50 | 168.2924 | -131.7076 | 2 | 2026-08-02 17:30 |
| 150 | 178.5764 | -121.4236 | 11 | 2026-08-12 17:20 |

Both fail to maintain a 300 restart account; this is not evidence for selecting 150 on profit. Capital/base stake ratio is still 200, same as 100/0.5. Raising both threefold is not an increase in available martingale depth.

Proposed implementation upgrades, not yet evidence of profitability:

1. Parameterize capital/base stake (implemented and tested); recovery already uses net fee-adjusted shares. At p=.50 and 2% fee, unit win profit=.96, so recovery stake=(round losses+1.5)/.96 rounded up. No fixed arbitrary increment.
2. Add actual quote/minimum/depth checks before orders. Do not auto-round minimum upward without budget check. Prefer a price ceiling at .50 if user prioritizes price; unmatched order expiry/cancel and partial-fill handling required. Maker status must be verified, not inferred from LIMIT. Skipping unfilled periods changes phase/execution and needs explicit policy in paper replay.
3. Do not count pending settlement as available money. Separate spendable, locked, reserve and transferable balances. Do not recycle a pending payout. Forecast affordable next layers including fees before ordering, without silently adding stop-loss rules.
4. Keep 50 withdrawal threshold as current baseline; 150 is a comparison only. UDUD re-entry remains user's heuristic, not a validated signal. Do not optimize it on August again.
5. Gather verified market IDs, resolution rules, quotes and fills. Validate June/July or another preselected untouched period for direction proxy, then prospective actual-book paper trading. No OHLC-fabricated 95% exits.

No RSI/MACD/EMA, trend filters, stop-loss or new prediction model added. No recommendation to fund real orders. Same August was repeatedly used for development; results do not establish out-of-sample performance. Existing scenario and reserve tests passed; added 300-capital reset test, total 25 tests.

Data: upgrade300_candidates.json. Reproduce via binance_quant.prediction_month.run_month(frame, recycle_only=True, ask=Decimal('.5'), buy_fee_rate=Decimal('.02'), initial_capital=Decimal('300'), base_bet=Decimal('1.5'), withdraw_profit=Decimal('50')) and threshold 150 for the second candidate. Source cost details and URLs remain in cost_review.md.
