# Two same selected colours -> reverse initial entry; three -> reverse after withdrawal

Ideal full fills .50 zero fees; actual fills unavailable. Odd UTC candles only; Wait two consecutive selected same-colour results then reverse next selected candle; only initial entry changes. Alternate every selected traded period, including refund ties. Withdraw excess over 300 at >=400 (usually 100.5). Fresh post-withdrawal triple same side then reverse next target. Stop on insufficient risk balance, do not recycle withdrawals.

Only initial entry changes; after entry continue fixed alternation on each selected period, not a fresh two-colour gate before every bet. Winning resets amount only. 300 capital, 1.5 strict doubling, profit withdrawal at >=100, excess withdrawn to retain 300. No reserve recycling on failure. Ideal full .50 fills zero fees, actual execution unavailable.

|Month|First day PnL|First week PnL|Month PnL|Total assets|
|---|---:|---:|---:|---:|
|2026-06|-184.5|-184.5|-184.5|115.5|

2026-06: profitable starts 11/30, failures 30, median PnL -48.0

|2026-07|103.5|48.0|48.0|348.0|

2026-07: profitable starts 9/31, failures 29, median PnL -114.0

|2026-08|-129.0|-129.0|-129.0|171.0|

2026-08: profitable starts 9/31, failures 29, median PnL -115.5


All three month-start runs stop in first week; no future trading profits after stop. Cohorts overlap and end at month boundary, not independent failure probability estimates. Same parity can cause new trigger to join the prior alternating path, explaining similar outcomes. No evidence of improvement from stricter initial trigger in these month-start runs.

Eight targeted tests passed. Reproduce: `.venv/bin/python -m binance_quant.prediction_stride_alternate --initial-signal double_reverse`. Full logs: stride_alternate_double_reverse.json.
