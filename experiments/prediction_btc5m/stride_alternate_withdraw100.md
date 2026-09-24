# Single-stride alternate / withdraw 100 / triple-reverse restart

Ideal full fills .50 zero fees; actual fills unavailable. Odd UTC candles only; K1 sets first side for K3. Alternate every selected traded period, including refund ties. Withdraw excess over 300 at >=400 (usually 100.5). Fresh post-withdrawal triple same side then reverse next target. Stop on insufficient risk balance, do not recycle withdrawals.

Each month starts independently at 300. Day and week mean first calendar day / first seven days, not expected recurring returns. Withdraw all profit above 300 once >=400; since round profit is 1.5, threshold is typically crossed at 400.5 and withdrawal is 100.5, not an invented exact 100. No real trades or limit fills verified.

|Month|Day PnL|Week PnL|Month PnL|Withdrawn|Risk balance|Stop UTC|
|---|---:|---:|---:|---:|---:|---|
|2026-06|-183.0|-183.0|-183.0|0.0|117.0|2026-06-01 03:30:00+00:00|

2026-06: daily-start scenarios 30, profitable 10, stopped before month end 30, median PnL -58.50.

|2026-07|103.5|48.0|48.0|201.0|147.0|2026-07-03 05:30:00+00:00|

2026-07: daily-start scenarios 31, profitable 8, stopped before month end 30, median PnL -112.50.

|2026-08|-127.5|-127.5|-127.5|0.0|172.5|2026-08-01 18:00:00+00:00|

2026-08: daily-start scenarios 31, profitable 9, stopped before month end 29, median PnL -114.00.


Cohorts overlap and have unequal observation horizons, not independent probability estimates. All three month-start paths reached seven consecutive losses and stopped before eighth stake 192; maximum filled stake 96. Fixed parity remains K1/K3/K5; post-withdrawal triple is on this selected sequence, not adjacent five-minute candles. First trade follows K1 colour at K3; winning resets amount only, subsequent directions alternate regardless of result.

Long-run failure probability, actual fees, actual .50 fill rate, NO_FILL and partial fills remain unavailable. Zero-cost/full-fill proxy cannot establish execution profitability. Six targeted tests passed. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_alternate`. Full logs in stride_alternate_withdraw100.json.
