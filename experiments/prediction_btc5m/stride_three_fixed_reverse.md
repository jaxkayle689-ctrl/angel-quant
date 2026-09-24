# Fresh triple -> fixed opposite until win

300 initial; 1.5 strict doubling; single odd UTC candle sequence. Three NEW same selected colours then opposite side; hold direction after loss until win. Every win waits three NEW colours excluding winning candle; withdrawal also waits three. Withdraw excess over 300 once profit >=100; no reserve refill after failure. Ideal full fills .50, zero fees, ties refunded (fixed direction unchanged). Actual Prediction fills and fees unavailable.

Each month independently starts with 300. First day/week are cumulative returns from month start, not average forecasts. Once failure occurs stop for rest of sample, keeping withdrawn funds.

|Month|Day PnL|Week PnL|Month PnL|Total assets|Withdrawn|Risk balance|Stop UTC|
|---|---:|---:|---:|---:|---:|---:|---|
|2026-06|22.5|148.5|129.0|429.0|301.5|127.5|2026-06-14 21:40:00+00:00|

2026-06: positive daily starts 15/30, failures by sample end 24, median PnL 0.00.


Final loss audit 2026-06: before UUU, during UUUUUUU, held DDDDDDD; from 2026-06-14 20:30:00+00:00 to 2026-06-14 21:30:00+00:00.

|2026-07|24.0|151.5|49.5|349.5|201.0|148.5|2026-07-12 08:40:00+00:00|

2026-07: positive daily starts 12/31, failures by sample end 21, median PnL -66.00.


Final loss audit 2026-07: before UUU, during UUUUUUU, held DDDDDDD; from 2026-07-12 07:30:00+00:00 to 2026-07-12 08:30:00+00:00.

|2026-08|21.0|141.0|129.0|429.0|301.5|127.5|2026-08-15 09:00:00+00:00|

2026-08: positive daily starts 21/31, failures by sample end 15, median PnL 75.00.


Final loss audit 2026-08: before DDD, during DDDDDDD, held UUUUUUU; from 2026-08-15 07:50:00+00:00 to 2026-08-15 08:50:00+00:00.


Profit in these three chosen month-start paths does not imply stability. Each still fails after seven losses and cannot afford next 192. Withdrawal protects some capital but real .50 maker fills, settlement, fees and flat payout remain unverified. Daily starts overlap and have different observation lengths; do not interpret as independent long-run probabilities. Repeatedly tested months are development data.

15 targeted tests passed. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_fixed_reverse`. Full ledger stride_three_fixed_reverse.json.
