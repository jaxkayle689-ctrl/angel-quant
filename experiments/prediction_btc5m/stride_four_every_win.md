# Corrected: fresh four same after EVERY win

Supersedes the previous initial-gate-only interpretation. 300 initial, base 1.5, strict doubling after loss with opposite next bet; each win resets stake and waits four NEW selected same-colour candles, then reverse. Winning candle excluded from fresh observation. Withdrawal at profit >=100 retains 300 and overrides gate with three NEW same colours. Ideal .50 full fill zero fee, ties refund and advance alternate phase. Stop without reserve reuse.

|Month|First day PnL|First week PnL|Month PnL|Withdrawn|Risk balance|Max level|Stop UTC|
|---|---:|---:|---:|---:|---:|---:|---|
|2026-06|12.0|76.5|-94.5|201.0|4.5|8|2026-06-23 22:10:00+00:00|

2026-06: prior selected colours DDDD; losing-period colours DUDUDUDU; bets UDUDUDUD; loss count 8; interval 2026-06-23 20:50:00+00:00 to 2026-06-23 22:00:00+00:00.

|2026-07|13.5|82.5|-46.5|100.5|153.0|7|2026-07-13 18:40:00+00:00|

2026-07: prior selected colours DDDD; losing-period colours DUDUDUD; bets UDUDUDU; loss count 7; interval 2026-07-13 17:30:00+00:00 to 2026-07-13 18:30:00+00:00.

|2026-08|9.0|73.5|142.5|301.5|141.0|7|2026-08-30 12:10:00+00:00|

2026-08: prior selected colours UUUU; losing-period colours UDUDUDU; bets DUDUDUD; loss count 7; interval 2026-08-30 11:00:00+00:00 to 2026-08-30 12:00:00+00:00.


Four signal candles plus seven losing outcomes = eleven observed selected candles, NOT eleven alternating candles. Example UUUU | UDUDUDU. First losing outcome continues the four-colour streak; the next outcomes alternate against alternating bets. Post-withdrawal gate is only three, so eleven is not a universal minimum.

These are first-day/first-week/month-start paths, not future daily earnings forecasts. All three paths eventually fail, including profitable August because withdrawals survive. No actual Prediction fills/fees or verified flat payout. Thirteen targeted tests passed including a synthetic four-same plus seven-loss example. Reproduce `.venv/bin/python -m binance_quant.prediction_stride_alternate --initial-signal four_reverse --wait-after-win`. Full records stride_four_every_win.json.
