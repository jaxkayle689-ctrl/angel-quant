# Four-reverse loss audit

Official Binance June/August archives re-downloaded, SHA256 matched their official CHECKSUM files, and extracted CSV bytes matched local data. Independent audit recomputed each trade direction, stake, PnL and available balance. Direction phase checked using elapsed selected slots, including refunded flat candles omitted from win/loss trade log. No direction/index/balance error found in these paths.

June 1 UTC: selected outcomes 19:30 through 20:40 are U D U D U D U D (8 candles, 7 transitions); preceding 19:20 is U, following 20:50 is D. Actual seven losing trades are 19:30 through 20:30: held D U D U D U D. At 20:40 order was not placed because 175.5 < 192; that candle later resolved DOWN.

August 1 UTC: selected outcomes 16:50 through 17:50 are D U D U D U D (7 candles, 6 transitions); preceding 16:40 and following 18:00 are both D. Seven losing trades held U D U D U D U. At 18:00 no order because 165 < 192; its eventual DOWN would have won the intended DOWN position, but no affordable fill exists.

Four same-colour results are a one-time initial gate, not required at each new martingale round. Those initial runs occurred many hours before the final losing sequence. Seven layers therefore do not imply ten alternating candles. Seven lost stakes 1.5+3+6+12+24+48+96=190.5; next is 192. This validates the implemented interpretation, not an unconfirmed different user intention. Raw trade records: four_reverse_loss_audit.json. All prices are spot candle proxies, not actual Prediction resolutions or fills.
