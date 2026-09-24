# Initial triple reverse, fixed alternate thereafter

Ideal full fills .50 zero fees; actual fills unavailable. Odd UTC candles only; Wait three consecutive selected same-colour results then reverse next selected candle; only initial entry changes. Alternate every selected traded period, including refund ties. Withdraw excess over 300 at >=400 (usually 100.5). Fresh post-withdrawal triple same side then reverse next target. Stop on insufficient risk balance, do not recycle withdrawals.

300 initial, 1.5 strict doubling, profit threshold 100; withdraw excess to restore 300. Selected K1/K3/K5 all closed before targeting K7 reverse; subsequent selected periods alternate regardless of outcome. Profit resets amount only. After withdrawal fresh selected triple required. Stop on unaffordable next bet, no refill.

|Month|Day PnL|Week PnL|Month PnL|Final risk account|Withdrawn|Max level|Stop UTC|
|---|---:|---:|---:|---:|---:|---:|---|
|2026-06|-283.5|-283.5|-283.5|16.5|0.0|8|2026-06-01 20:50:00+00:00|

2026-06: profitable starts 9/30, stopped 29, median PnL -60.75.

|2026-07|103.5|48.0|48.0|147.0|201.0|7|2026-07-03 05:30:00+00:00|

2026-07: profitable starts 12/31, stopped 29, median PnL -30.0.

|2026-08|118.5|118.5|118.5|117.0|301.5|7|2026-08-04 01:10:00+00:00|

2026-08: profitable starts 8/31, stopped 30, median PnL -82.5.


June reached 399 before the final eight losses (1.5+3+6+12+24+48+96+192 = 382.5), leaving 16.5. Thus max level eight does not violate the balance guard: prior accumulated unwithdrawn profit funded it. Next 384 unaffordable.

Ideal full fills .50 zero fees, real Prediction fill rate unavailable. Refunded ties hypothetical. First-day and week values are cumulative window PnL from month start, not rolling average forecasts. Stop retains assets for rest of month. Daily-start cohorts overlap with unequal observation length, not independent estimates of long-run failure. All months have now been repeatedly used for tuning.

Nine targeted tests passed. Reproduce: `.venv/bin/python -m binance_quant.prediction_stride_alternate --initial-signal triple_reverse`. Raw result stride_alternate_triple_reverse.json. Previous reports retained.
