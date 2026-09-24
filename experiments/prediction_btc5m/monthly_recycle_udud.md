# Monthly replay: only initial 100 USDT, internal recycling

August 2026 real BTCUSDT spot 5-minute candle colours. Assumed price 0.50, no fees, ties refunded, instant settlement and restart; no actual Prediction execution, 90% rollover or 95% exit. Base stake 0.5. First entry after previous DOWN, fixed UD cycle. Withdraw each 50 profit, retain 100, wait four new closed UDUD candles before next UP entry. On failure pool residual with reserves, allocate 100 only if available; otherwise stop. No new external funds.

Completed all 31 days. External capital 100, additional external funds 0. 14 failures, 14 internal restarts, 15 account sessions. Closing reserve 986; active account 145.5; total assets 1131.5; net profit 1031.5. Mean daily simulated PnL 33.27. Cumulative withdrawals 1800 are transfer volume, NOT money still untouched: 1400 was internally allocated to restarts and 586 residual returned to reserve (1800 + 586 - 1400 = 986).

Minimum pooled funds at a failure before allocating the next 100: 191.00. Every restart funded from assets already available at that time, never future profits.

|Session|Failure UTC|Pooled funds before restart|Reserve after allocation|
|---|---|---:|---:|
|1|2026-08-03 07:50:00+00:00|191.00|91.00|
|2|2026-08-05 22:00:00+00:00|287.50|187.50|
|3|2026-08-06 20:20:00+00:00|287.00|187.00|
|4|2026-08-09 02:40:00+00:00|379.00|279.00|
|5|2026-08-10 06:15:00+00:00|390.00|290.00|
|6|2026-08-11 22:35:00+00:00|444.50|344.50|
|7|2026-08-12 17:20:00+00:00|431.00|331.00|
|8|2026-08-15 11:25:00+00:00|483.50|383.50|
|9|2026-08-18 01:40:00+00:00|596.00|496.00|
|10|2026-08-18 05:30:00+00:00|542.00|442.00|
|11|2026-08-22 03:45:00+00:00|735.50|635.50|
|12|2026-08-23 10:55:00+00:00|694.50|594.50|
|13|2026-08-25 02:00:00+00:00|731.50|631.50|
|14|2026-08-27 11:35:00+00:00|836.00|736.00|

Net trading PnL matches the external-refill scenario because reserves sufficed for every restart, so the trade sequence is identical. Ending assets differ by 1400, exactly the external funds no longer injected. This agreement is specific to this path, not a general claim that external and internal funding are equivalent.

Each traded candle is unique; sum of trade PnLs reconciles with closing assets minus 100. No reserve or withdrawal double counting. This month has repeatedly informed rule selection, so it is development data rather than an independent validation. Do not extrapolate its average daily result to future profits.

Reproduce: `.venv/bin/python -m binance_quant.prediction_month --recycle-only`. 23 tests passed. Full ledger: monthly_recycle_udud.json.
