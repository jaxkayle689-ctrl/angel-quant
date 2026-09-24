# Single stride, hold direction through losses

IDEAL FULL FILL .50 ZERO FEE; actual fills/fees unavailable
Single odd UTC sequence; same direction after loss until win; after win new direction from latest closed selected candle. No reserve recycling after failure. Ties refunded. Reentry rules are unconfirmed alternatives.

All returns below include withdrawn funds minus original 300. Day = first UTC day of month, week = first seven days, month = calendar month. These are not rolling-average estimates. After insufficient balance, stop without reserve refill. Later windows retain unchanged assets. UDU/DUD and mixed reentry are unconfirmed alternatives, not silently selected strategy rules.

|Scenario|Day PnL|Week PnL|Month PnL|Withdrawn at month end|Max level|Stop UTC|
|---|---:|---:|---:|---:|---:|---|
|2026-06_alternating_15|99.0|391.5|391.5|570.0|7|2026-06-07 14:20:00+00:00|
|2026-06_alternating_30|-108.0|-108.0|-108.0|60.0|7|2026-06-01 17:30:00+00:00|
|2026-06_alternating_45|-159.0|-159.0|-159.0|0.0|7|2026-06-01 07:50:00+00:00|
|2026-06_alternating_60|-159.0|-159.0|-159.0|0.0|7|2026-06-01 07:50:00+00:00|
|2026-06_mixed_15|-162.0|-162.0|-162.0|15.0|7|2026-06-01 07:50:00+00:00|
|2026-06_mixed_30|-105.0|-105.0|-105.0|60.0|7|2026-06-01 17:30:00+00:00|
|2026-06_mixed_45|-159.0|-159.0|-159.0|0.0|7|2026-06-01 07:50:00+00:00|
|2026-06_mixed_60|-159.0|-159.0|-159.0|0.0|7|2026-06-01 07:50:00+00:00|
|2026-07_alternating_15|-150.0|-150.0|-150.0|30.0|7|2026-07-01 11:10:00+00:00|
|2026-07_alternating_30|84.0|192.0|192.0|360.0|7|2026-07-05 09:30:00+00:00|
|2026-07_alternating_45|-148.5|-148.5|-148.5|0.0|7|2026-07-01 11:10:00+00:00|
|2026-07_alternating_60|-148.5|-148.5|-148.5|0.0|7|2026-07-01 11:10:00+00:00|
|2026-07_mixed_15|-141.0|-141.0|-141.0|45.0|7|2026-07-01 11:10:00+00:00|
|2026-07_mixed_30|-151.5|-151.5|-151.5|30.0|7|2026-07-01 11:10:00+00:00|
|2026-07_mixed_45|-148.5|-148.5|-148.5|0.0|7|2026-07-01 11:10:00+00:00|
|2026-07_mixed_60|-148.5|-148.5|-148.5|0.0|7|2026-07-01 11:10:00+00:00|
|2026-08_alternating_15|-162.0|-162.0|-162.0|15.0|7|2026-08-01 09:10:00+00:00|
|2026-08_alternating_30|-157.5|-157.5|-157.5|30.0|7|2026-08-01 09:10:00+00:00|
|2026-08_alternating_45|105.0|-51.0|-51.0|135.0|7|2026-08-02 09:10:00+00:00|
|2026-08_alternating_60|112.5|51.0|51.0|240.0|7|2026-08-03 09:50:00+00:00|
|2026-08_mixed_15|-160.5|-160.5|-160.5|30.0|7|2026-08-01 09:10:00+00:00|
|2026-08_mixed_30|105.0|-49.5|-49.5|120.0|7|2026-08-02 09:10:00+00:00|
|2026-08_mixed_45|114.0|-40.5|-40.5|135.0|7|2026-08-02 09:10:00+00:00|
|2026-08_mixed_60|109.5|-43.5|-43.5|120.0|7|2026-08-02 09:10:00+00:00|

All scenarios stopped within the first seven days. This does not establish a long-term failure probability. Real fill rate, NO_FILL outcomes, fees and actual Prediction PnL unavailable. No real order interface implemented. Flat candles assumed refund, not verified market payout rule. Odd sequence anchored at month start 00:00 UTC. Withdrawal observation resets, ignores all preceding candles. Winning round resets amount and uses latest closed selected result for next direction (pending user confirmation).

Reproduce: `.venv/bin/python -m binance_quant.prediction_stride_backtest`. Three targeted tests passed for loss-side persistence, insufficient balance, and post-withdrawal fresh signal. Raw logs: stride_persistent_direction.json. Separate direction statistics: stride_single_statistics.json.
