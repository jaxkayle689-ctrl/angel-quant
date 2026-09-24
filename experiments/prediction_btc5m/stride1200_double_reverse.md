# 1200 capital, 1.5 base, double reverse

1200 initial only; base1.5 double after loss, fixed opposite side until win. Initial and every ordinary win wait two NEW same-colour selected candles. Withdraw excess over1200 at profit>=100; then wait three NEW same-colour selected candles. Odd UTC sequence, no reserve refill at failure. Ideal .50 all fills zero fee, ties assumed refund.

Each month starts independently, not three months compounded. Daily/week values from first UTC day/first seven days. Month keeps assets after failure, no more orders. Actual Prediction fills and fees unavailable.

|Month|Day PnL|Week PnL|Month PnL|Withdrawn|Risk balance|Final assets|Failure UTC|
|---|---:|---:|---:|---:|---:|---:|---|
|2026-06|36.0|301.5|-172.5|502.5|525.0|1027.5|2026-06-14 22:00:00+00:00|

2026-06: signal UU, losses UUUUUUUUU, held DDDDDDDDD from 2026-06-14 20:30:00+00:00 to 2026-06-14 21:50:00+00:00.

|2026-07|46.5|292.5|-304.5|402.0|493.5|895.5|2026-07-12 08:50:00+00:00|

2026-07: signal UU, losses UUUUUUUUU, held DDDDDDDDD from 2026-07-12 07:20:00+00:00 to 2026-07-12 08:40:00+00:00.

|2026-08|40.5|291.0|-156.0|603.0|441.0|1044.0|2026-08-15 09:10:00+00:00|

2026-08: signal DD, losses DDDDDDDDD, held UUUUUUUUU from 2026-08-15 07:40:00+00:00 to 2026-08-15 09:00:00+00:00.


Nine losses total 1.5*(2^9-1)=766.5; ninth stake384, next768. 1200/300=4 buys only two extra doubling layers (7 to9), not four times as many. All three paths exhausted nine layers. Double signal plus nine continuation losses implies at least eleven selected same colours in these audited paths.

17 targeted tests passed, including 1200 bankroll and withdrawal reset. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_1200`. Full logs stride1200_double_reverse.json. Months repeatedly used for development; results are not future return estimates. No live trades.
