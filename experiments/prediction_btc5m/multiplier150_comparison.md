# Withdrawal target 150; multiplier comparison

Initial 300, base 1.5, fixed UD after prior DOWN, fee 2% deducted as shares, assumed .50 fills. Withdraw excess above 300 at 450; wait new UDUD. Recycle only own funds. Each month independently starts with 300. All variants reset only after cumulative round net profit >0. Fixed 2 or 2.5 multiplies prior stake and rounds upward to cents; recovery variant computes loss plus 1.5 profit target using net payout.

|Month|Sizing|Final assets|Net PnL|Failures|Stopped UTC|
|---|---|---:|---:|---:|---|
|2026-06|fee_recovery|149.89|-150.11|1|2026-06-01 07:15:00+00:00|
|2026-06|fixed_2|170.64|-129.36|1|2026-06-01 07:15:00+00:00|
|2026-06|fixed_2p5|175.77|-124.23|1|2026-06-01 07:10:00+00:00|
|2026-07|fee_recovery|208.53|-91.47|3|2026-07-03 19:45:00+00:00|
|2026-07|fixed_2|240.96|-59.04|1|2026-07-01 08:20:00+00:00|
|2026-07|fixed_2p5|118.53|-181.47|1|2026-07-01 03:50:00+00:00|
|2026-08|fee_recovery|178.58|-121.42|11|2026-08-12 17:20:00+00:00|
|2026-08|fixed_2|130.98|-169.02|4|2026-08-03 03:55:00+00:00|
|2026-08|fixed_2p5|142.51|-157.49|5|2026-08-03 07:45:00+00:00|

No case establishes profitability. Fixed 2.5 exhausts bankroll layers sooner, although a recovery win yields a larger surplus. Not an improvement to prediction probability. Different timing and reserves prevent a monotonic relationship between multiplier and final assets. All months now development samples; no independent selection claim. Real execution/95% exit/90% rollover unavailable.

Illustrative stakes with upward-cent rounding:
2: 1.5, 3.00, 6.00, 12.00, 24.00, 48.00, 96.00; losses 190.50; remaining 109.50; next 192.00 unaffordable.
2.5: 1.5, 3.75, 9.38, 23.45, 58.63, 146.58; losses 243.29; remaining 56.71; next 366.45 unaffordable.

26 tests passed. Full logs: multiplier150_comparison.json. Reproduce with run_month(frame,recycle_only=True,ask=Decimal(".5"),buy_fee_rate=Decimal(".02"),initial_capital=Decimal("300"),base_bet=Decimal("1.5"),withdraw_profit=Decimal("150"),multiplier=Decimal("2.5")); use None for recovery or Decimal("2") for doubling. Previous reports retained.
