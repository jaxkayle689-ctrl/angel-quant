# Frozen 300 USDT strategy: new-month validation

Fixed before testing: initial 300 only; base/recovery target 1.5; first prior DOWN then fixed UD; withdraw 50 over 300; wait four NEW closed UDUD; restart failed account from existing reserves only when 300 available. No parameter search. June and July first used for these tests, August previously used for development. New monthly archives verified against Binance published SHA256 checksums.

All cases still use spot-colour proxies and assume instantaneous fills at .50, immediate settlement, refunded ties, no early exits. Taker fee 2% applied prospectively, not verified historical actual fees. Zero-fee maker case is idealized, NOT evidence that passive orders fill.

|Month|Case|Month-start final assets|PnL|Positive daily starts|Median daily-start PnL|
|---|---|---:|---:|---:|---:|
|2026-06|taker_2pct|144.13|-155.87|0/30|-138.21|
|2026-06|ideal_maker_zero_fee|171.00|-129.00|0/30|-116.25|
|2026-07|taker_2pct|238.38|-61.62|1/31|-110.19|
|2026-07|ideal_maker_zero_fee|265.50|-34.50|0/31|-82.50|
|2026-08|taker_2pct|168.29|-131.71|0/31|-131.71|
|2026-08|ideal_maker_zero_fee|223.50|-76.50|2/31|-120.00|

Daily starts overlap and have different remaining horizons, so these are sensitivity cases, not independent trials or a significance test. Each has its own initial 300; they are not summed as one portfolio. Positive paths must not be selected after seeing the outcome. Tests do not show consistent positive performance under the frozen strategy.

Research next step requires actual market identifiers, resolved outcomes, fee quotes, minimums and order-book collection; do not invent fill probability from OHLC or keep tuning against these months. No live trading or standing scheduled research job started.

Reproduce `.venv/bin/python -m binance_quant.prediction_validation`. Full records: validation300_frozen.json. Source manifests: source_2026-06.json and source_2026-07.json.
