# BTC 5分钟方向代理研究（非Prediction真实成交回测）

数据：Binance Spot BTCUSDT，2026-08-01至2026-09-01 UTC，8928根连续5分钟K线，93根开收盘相同。来源URL和压缩包SHA256见source.json。没有Prediction实际结算或盘口数据。

用户允许使用K线颜色代替方向。模拟假设每期收盘结果立即可知并可在紧接的一期按固定价格成交；没有延迟、费用或滑点。平盘假设退回本金并保留当前序列，不算输赢；这是模拟口径，并非已验证的平台规则。新序列仅在两个已结束同色K线后反向入场；未盈利前方向保持不变；首次1U，续投按累计亏损加1U目标除以实际假设的盈利率计算，向上取整到分。单轮累计盈利后重置。余额不足停止，不追加资金。

| 情景 | 最终余额 | 净收益 | 首次断链时间（自起点） | 成交次数 |
|---|---:|---:|---:|---:|
| 固定买入0.50、结算支付1或0 | 73U | -27U | 32.92小时 | 197 |
| 固定买入0.60、结算支付1或0 | 35.5367U | -64.4633U | 5.17小时 | 32 |

0.50情景最高余额200U，回撤127U，剩73U时无法投入下一层128U。每日盈亏分布见scenario_report.json中的daily_pnl；停止后其余日期记0。按整月摊薄日均为-0.871U和-2.079U，不代表策略可以连续运行一个月，也不是实际可预期收益。

分别以8月每一天00:00 UTC为独立100U起点，0.50情景31个起点中28个在样本结束前断链，已断链样本中位时间19.96小时；0.60情景31个均断链，中位9.50小时。各起点共享未来行情、并非独立样本；未断链起点受样本截止限制，不能解释为长期存活。不是同一账户重复充值。

UU后DOWN概率51.5296%（2092个条件样本）；DD后UP概率50.8307%（2227个条件样本）。包含平盘作为第三种结果。最长UP 12、DOWN 11；至少8连的最大连续段共28个（UP 15，DOWN 13），每段只计一次。更多3至12连和条件概率见direction_report.json。

90%提前续投、95%退出、实际手续费、真实胜率及真实日收益全部unavailable，K线无法证明其成交。研究结果不足以通过实盘验收，未接通自动下单。prediction_research.py含报价回本金额计算和结束前10秒对手bid>=0.90的信号函数，后者仅为条件判断，不会把未结算头寸写成亏损。

复现（项目根目录）：

```sh
.venv/bin/python -m binance_quant.prediction_research --binance-csv experiments/prediction_btc5m/BTCUSDT-5m-2026-08.csv --output experiments/prediction_btc5m/direction_report.json
.venv/bin/python -m binance_quant.prediction_scenario
.venv/bin/python -m unittest discover -s tests -p test_prediction_research.py -q
```

Binance官方接口核查：
https://developers.binance.com/en/docs/catalog/web3-wallet-prediction-trading/api/rest-api/trade
文档注明MARKET最低约1.5U，LIMIT不适用该限制；保留1U起投意味着必须实际验证LIMIT报价和成交。程序尚无交易适配器、持仓恢复或桌面页面，不能当作已完成实盘集成。
