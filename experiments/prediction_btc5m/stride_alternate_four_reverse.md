# Four selected same colours: reverse initial entry

Ideal full fills .50 zero fees; actual fills unavailable. Odd UTC candles only; Wait four consecutive selected same-colour results then reverse next selected candle; withdrawal restart still requires three. Alternate every selected traded period, including refund ties. Withdraw excess over 300 at >=400 (usually 100.5). Fresh post-withdrawal triple same side then reverse next target. Stop on insufficient risk balance, do not recycle withdrawals.

Only initial gate changed. K1/K3/K5/K7 same -> K9 opposite, then fixed alternation. Withdrawal restart remains three fresh selected same-colour candles. 300 initial, 1.5 strict doubling, withdraw all excess over 300 once profit >=100, stop at insufficient balance without reserve refill. Ideal full .50 fills, zero fee, ties refunded; actual execution unavailable.

|Month|First day PnL|First week PnL|Month PnL|Total assets|Withdrawn|Stopped UTC|
|---|---:|---:|---:|---:|---:|---|
|2026-06|-124.5|-124.5|-124.5|175.5|0.0|2026-06-01 20:40:00+00:00|

2026-06: profitable starts 9/30, stopped 30, median PnL -56.25.

|2026-07|94.5|190.5|190.5|490.5|301.5|2026-07-04 12:00:00+00:00|

2026-07: profitable starts 10/31, stopped 30, median PnL -117.0.

|2026-08|-135.0|-135.0|-135.0|165.0|0.0|2026-08-01 18:00:00+00:00|

2026-08: profitable starts 8/31, stopped 30, median PnL -88.5.


All month-start paths stopped in first week after seven losses; maximum filled level 7 (96), next 192 unaffordable. Week/month equality means no trades after failure, not stable recurring income. Daily starts overlap and have different horizons, not independent probabilities. These months have been repeatedly tuned on.

11 targeted tests passed, including four fully closed selected results and retaining three-result withdrawal restart. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_alternate --initial-signal four_reverse`. Full ledger: stride_alternate_four_reverse.json.
