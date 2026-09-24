# 2400 capital comparison

2400 initial only; base1.5 double after loss, fixed opposite side until win. Initial and every ordinary win wait two NEW same-colour selected candles. Withdraw excess over2400 at profit>=100; then wait three NEW same-colour selected candles. Odd UTC sequence, no reserve refill at failure. Ideal .50 all fills zero fee, ties assumed refund.

Each month independent capital2400; not sequential reinvestment across months. Real spot colours only, ideal full .50 fills zero fee and refunded ties. Actual Prediction fill/fee/settlement data unavailable.

|Month|Day PnL|Week PnL|Month PnL|Withdrawn|Risk balance|Total assets|Stop UTC|
|---|---:|---:|---:|---:|---:|---:|---|
|2026-06|36.0|301.5|1281.0|1206.0|2475.0|3681.0|None|
|2026-07|46.5|292.5|-1072.5|402.0|925.5|1327.5|2026-07-12 09:00:00+00:00|
|2026-08|40.5|291.0|1332.0|1306.5|2425.5|3732.0|None|

Doubling capital1200 to2400 adds one layer: stake10=768, cumulative ten losses1534.5, next stake1536. June/August recover on level10 after nine losses; July loses level10, leaving risk925.5 plus withdrawn402, insufficient next1536 even if pooled (though pooling is disabled). No evidence that future runs cannot exceed ten losses.

18 targeted tests passed. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_1200 --capital 2400`. Full logs stride2400_double_reverse.json. Previous results retained.
