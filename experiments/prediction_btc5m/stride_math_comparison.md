# Martingale combination analysis, June-August 2026

18 development candidates, not independent validation. Each month resets to 300. Withdrawal gate always fresh triple. Zero fee, .50 full fills, fixed opposite till win, strict doubling, no reserve reuse.

All candidates: 300 risk capital, base 1.5, strict doubling, fixed opposite side through losses, fresh entry gate after every win, withdraw then fresh triple gate, no reserve refill. Changed only initial/every-win gate length (2/3/4) and withdrawal threshold (15/30/45/60/100/150). These are 18 DEVELOPMENT candidates tested on already explored months; no performance guarantee or independent confirmation. Monthly results are three independent initial 300 accounts, not a 300 account compounded across months.

|Gate|Withdrawal|June PnL|July PnL|August PnL|Sum of independent PnLs|Failures|
|---|---:|---:|---:|---:|---:|---:|
|double_reverse|150|409.5|-10.5|424.5|823.5|3|
|double_reverse|100|66.0|-87.0|357.0|336.0|3|
|double_reverse|60|66.0|-88.5|355.5|333.0|3|
|double_reverse|45|64.5|-90.0|355.5|330.0|3|
|triple_reverse|15|129.0|49.5|129.0|307.5|3|
|triple_reverse|30|129.0|49.5|129.0|307.5|3|
|triple_reverse|45|129.0|49.5|129.0|307.5|3|
|triple_reverse|60|129.0|49.5|129.0|307.5|3|
|triple_reverse|100|129.0|49.5|129.0|307.5|3|
|double_reverse|30|51.0|-90.0|342.0|303.0|3|
|double_reverse|15|51.0|-90.0|325.5|286.5|3|
|triple_reverse|150|129.0|-142.5|129.0|115.5|3|
|four_reverse|15|-13.5|-63.0|-18.0|-94.5|3|
|four_reverse|30|-19.5|-63.0|-21.0|-103.5|3|
|four_reverse|45|-21.0|-63.0|-21.0|-105.0|3|
|four_reverse|60|-22.5|-64.5|-22.5|-109.5|3|
|four_reverse|100|-21.0|-64.5|-24.0|-109.5|3|
|four_reverse|150|-22.5|-256.5|-24.0|-303.0|3|

Mathematics: at .50 no fee, per-dollar expected profit = 2p-1. With 2% of purchased shares deducted, expected profit = 1.96p-1, break-even p=51.0204%. Published provider fee source https://docs.predict.fun/the-basics/predict-fees-and-limits . Maker is zero-fee only if actually executed as maker; selection into fills may change p.

Seven strict-double losses total 1.5*(2^7-1)=190.5, equivalent to 127 completed +1.5 cycles. With independent fair outcomes, seven-loss round probability=1/128. Expected bounded-round profit=(127/128)*1.5-(1/128)*190.5=0. Probability at least one such round in 100 independent rounds=1-(127/128)^100=54.36%. These are illustrative iid mathematics, NOT estimated market probabilities; overlaps, nonstationarity, fees and variable bankroll violate assumptions.

For multiplier r, stake_n=b*r^(n-1); losses through n=b*(r^n-1)/(r-1). Increasing r raises exposure and reduces affordable depth, not predictive edge. With 300 and base 1.5, seven double stakes affordable; eighth (192) needs cumulative 382.5 from initial reserve.

Triple gate thresholds 15 through 100 produce identical total PnL in these three paths. Withdrawal moves cash; it does not create profit or change market probability. Here fresh-triple pause after both ordinary wins and withdrawals is the same, and available-balance thresholds happen not to change final failure point. Not a universal invariance.

Suggested research baseline: triple reverse, fixed side until win, exact 2x under ideal zero-fee assumption, profit threshold 30 as smaller reserve transfers (not an empirically higher-return parameter), every-win fresh triple, no added indicators. Highest development score is double gate / threshold150 but July loses and all three stop: cannot call it optimal. Keep 100 if avoiding unvalidated change.

Next validation requires frozen configuration on untouched periods and actual limit order quote/book/fill replay. NO_FILL, partial fills, queue selection and unsettled cash are unavailable, so actual long-run return and failure probability cannot be estimated here. Strict doubling does not guarantee positive full-cycle PnL after costs.

Reproduce `.venv/bin/python -m binance_quant.prediction_stride_comparison`. Full statistics and candidate details stride_math_comparison.json.
