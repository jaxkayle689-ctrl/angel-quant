# Monthly replay: external 100 USDT after failure

August 2026 BTCUSDT spot 5-minute candle colours. Assumed entry price 0.50, zero fees, ties refunded, immediate settlement/restart. No 90% rollover or 95% exit simulation. First entry follows a closed DOWN; alternate UD, base stake and recovery target 0.5 USDT. Withdraw 50 profit, retain 100, wait for four NEW closed UDUD candles, then restart UP. No two-hour pause. At failure segregate residual, add NEW external 100, reset and wait previous DOWN. No recycled withdrawals.

15 injections total = 1500 USDT (initial 100 plus 14 additional injections). 14 failures. 36 withdrawals = 1800 USDT. Segregated residual = 586. Active closing balance = 145.5. Total assets = 2531.5. Net PnL after ALL injections = 1031.5. Mean daily PnL over 31 days = 33.27. Return on cumulative injected capital = 68.77%; this is not a return on only 100 USDT.

Daily PnL median 58.50; minimum -64.00; maximum 74.00; profitable days 27. Days assigned by entry candle UTC date, consistent with prior reports.

|Session|Funded UTC|Failure UTC|Withdrawn|Residual/active|
|---|---|---|---:|---:|
|1|2026-08-01 00:00:00+00:00|2026-08-03 07:50:00+00:00|150.00|41.00|
|2|2026-08-03 07:50:00+00:00|2026-08-05 22:00:00+00:00|150.00|46.50|
|3|2026-08-05 22:00:00+00:00|2026-08-06 20:20:00+00:00|50.00|49.50|
|4|2026-08-06 20:20:00+00:00|2026-08-09 02:40:00+00:00|150.00|42.00|
|5|2026-08-09 02:40:00+00:00|2026-08-10 06:15:00+00:00|50.00|61.00|
|6|2026-08-10 06:15:00+00:00|2026-08-11 22:35:00+00:00|100.00|54.50|
|7|2026-08-11 22:35:00+00:00|2026-08-12 17:20:00+00:00|50.00|36.50|
|8|2026-08-12 17:20:00+00:00|2026-08-15 11:25:00+00:00|150.00|2.50|
|9|2026-08-15 11:25:00+00:00|2026-08-18 01:40:00+00:00|150.00|62.50|
|10|2026-08-18 01:40:00+00:00|2026-08-18 05:30:00+00:00|0.00|46.00|
|11|2026-08-18 05:30:00+00:00|2026-08-22 03:45:00+00:00|250.00|43.50|
|12|2026-08-22 03:45:00+00:00|2026-08-23 10:55:00+00:00|50.00|9.00|
|13|2026-08-23 10:55:00+00:00|2026-08-25 02:00:00+00:00|100.00|37.00|
|14|2026-08-25 02:00:00+00:00|2026-08-27 11:35:00+00:00|150.00|54.50|
|15|2026-08-27 11:35:00+00:00|Active at month end|250.00|145.50|

Capital inflows excluded from profits. Sum of all trade PnLs reconciles to 1031.5. No duplicate traded candles. Residuals neither discarded nor reused. Restart assumes zero latency and may use the failed/unfilled candle. This month has repeatedly been used to select rules and is development data, not an independent validation. Actual market prices/fees, minimum order execution and early exits remain unavailable. No real trades or transfers made.

Reproduce: `.venv/bin/python -m binance_quant.prediction_month`. 22 relevant tests passed. Full daily/session/trade/withdrawal ledger: monthly_refill_udud.json.
