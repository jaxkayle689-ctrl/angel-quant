# 社区策略接口（v0.12.0）

2026-09-23 下载的上游文件随应用固定打包，启动不联网下载代码。
来源：https://github.com/ceyhanmolla/freqtrade-strategies
上游未声明许可证；当前仅本机研究使用，重新分发需确认许可。

| 策略 ID | Freqtrade 类 | 周期 |
| --- | --- | --- |
| community_genetic | AngelGenetic | 5m，400根预热 |
| community_trend | AngelTrend | 5m + 已收盘1h |
| community_ewo | AngelEwo | 5m |

三者均为 Binance USDT 永续做多适配，与上游现货收益不可直接比较。
遗传策略改用过去200根的滚动归一化，修复上游全样本极值泄漏。
保留原版指标默认参数、ROI与止损逻辑；当前指标参数固定，传入非空参数返回明确错误。
组合中支持首仓、预算和杠杆，默认1倍；资金不足最小订单时返回0跳过入场。

桌面桥接口：
- `workspace_bootstrap()`：策略元数据，含来源、版本、能力与适配器。
- `save_portfolio(payload)`：保存组合。
- `start_portfolio_backtest(payload)`：异步历史验证。
- `start_portfolio_dry_run(payload)`：异步模拟盘。
- `research_status()` / `freqtrade_status()`：进度与结果。
- `stop_freqtrade_dry_run()`：停止模拟盘。

组合 payload 示例：
```json
{"portfolio_id":"community_btc","name":"社区策略 BTC","strategy_id":"community_genetic","initial_capital":1000,"run_days":30,"max_concurrent_positions":1,"account_stop_pct":12,"strategy_parameters":{},"projects":[{"project_id":"btc","symbol":"BTCUSDT","budget":1000,"initial_stake":50,"leverage":1,"market":"crypto_futures","enabled":true}]}
```

账户回撤警戒线沿用原系统语义；不代表保证最大回撤。接口不自动启动实盘。
原生图表信号接口不执行这些策略，会提示改用策略验证或模拟盘。
当前只完成接入、信号与配置检查，尚无本地样本外收益结论。

财报接口 `macro_calendar({refresh:true})` 返回事件和24家公司关注名单。
覆盖过去7天、未来45天工作日，日数据缓存1小时；单日失败不会丢弃其他日期。
`time_precision=session` 表示只知道美东盘前/盘后，内部排序时间不是确认的发布时间；前端显示待确认。
`company_ir` 为已核验电话会议时间，与财报新闻稿发布时刻可能不同。
`earnings_watchlist.status=pending` 表示窗口内未取得下一次日期，也可能是源不可用；不得据此断言公司尚未公告。
