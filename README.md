# 只想玩天使的量化

本地 macOS 量化研究、策略分析与模拟交易工作台。当前版本为 `v0.12.0`，默认使用 React 前端，包含三通道 Pipeline、缠论知识库、Binance USD-M 行情、组合回测、Freqtrade Dry-run 和 SNDK 跨市场历史验证。

## 从源码启动

需要 Python 3.9–3.12；前端构建建议 Node.js 22.12+。macOS 桌面应用还需要 Xcode Command Line Tools。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
bq-app
```

源码包含已构建的桌面前端，可直接启动。修改 React 后执行 `sh scripts/build_react_frontend.sh`。重新生成 macOS 应用：

```bash
python -m pip install -r requirements-build.txt
sh scripts/build_macos_app.sh
open "dist/只想玩天使的量化.app"
```

独立打开新策略界面：`python -m binance_quant.pipeline.server`，访问 `http://127.0.0.1:8788`。桌面内点击“智能策略工作台”会自动启动内嵌服务。

## 当前 Pipeline 集成状态

- 实时读取 Binance 合约目录，包含美股 / ETF 永续，默认优先选择 SNDKUSDT。
- 支持自动分级、快速、标准和深度通道，展示技术快照、策略信号、策略卡片、硬闸门、模拟成交和决策记忆。
- 原“智能盯盘”入口已替换；“当日策略”和其他原有模块保留。
- 当前桌面 Pipeline 使用规则共识，尚未与原设置页的模型密钥、自动盯盘和飞书推送配置贯通；强平 WS 默认未开启。模块存在不等于这些外部通道已连接。
- Pipeline 订单通过 PaperExecutor 模拟执行，不会向 Binance 发送真实订单。

仓库打包、上传和排除文件说明见 [Git 发布指南](docs/GIT_RELEASE.md)。以下旧功能说明中涉及模型、自动盯盘及飞书的配置属于原 Agent 服务，不代表新 Pipeline 已具备这些连接。

## 界面与个人设置

- 当日策略采用标的卡片总览，点击卡片进入依据详情；支持添加经过市场核验的美股、ETF 和港股代码。
- 策略库默认只显示名称。悬停或键盘聚焦可修改名称，右侧“⋯”提供详细信息和删除。删除移出选择列表，原文件与已有组合引用保留。
- 设置支持更换和恢复图标、大厅背景；使用 PNG/JPG，单图上限 8 MB。图标同步到界面与运行时 Dock；打包应用默认使用项目提供的自定义图标。
- 前端工程位于 `frontend/`，使用 React + TypeScript + Vite。总览、当日策略、策略库、设置为 React 页面；智能盯盘、模拟盘、验证和实盘账户保留原有模块，通过同一桌面接口嵌入，尚未逐页重写为 React。
- 外观、策略名称、删除记录、自选标的和最近生成报告保存在应用支持目录的 `workspace_settings.json`。
- CoinGlass 跳转使用已核验的 SNDK、MRVL、SOXL、NBIS 对应页面。它们是股票永续合约数据，不代表正股订单簿；MiniMax 尚无已核验链接。

## 前端构建与验收

运行 `sh scripts/build_macos_app.sh` 会先用锁定的 npm 依赖构建 React，再将新旧前端一起打包。双击 `dist/只想玩天使的量化.app` 默认进入 React，无需环境变量。需要旧界面时可用 `BINANCE_QUANT_FRONTEND=legacy .venv/bin/python -m binance_quant.desktop`。

前端检查：`cd frontend && npm test && npm run build`。后端检查：`.venv/bin/python -m unittest discover -s tests -q`。

## 缠论知识库

“缠论知识库”以指定公开视频的带时间轴转写为唯一内容源。系统把字幕切成有重叠的语义片段，写入本地 SQLite，并使用中文字符 n-gram 与哈希向量做混合检索。查询结果包含原始字幕、相关度、时间戳和可直接跳转的视频链接；证据较弱时会明确返回“证据不足”。

索引具备来源校验和版本、幂等重建、SQLite WAL、查询哈希审计和本地持久化。数据库位于：

```text
~/Library/Application Support/Binance Quant/knowledge_base/knowledge.db
```

当前回答采用可复核的证据摘录，确保没有配置云模型时也能使用。字幕和查询内容不会发送到第三方模型服务。

启动首先加载本地自选标的、策略名称、图片和保存的报告，不依赖 Binance 网络请求。报告是快照，卡片同时列出行情时间与生成时间；点击“刷新全部”或详情内“刷新策略”获取更新。单标的失败会保留旧报告并显示错误。页面不会自动下单，也不会把缓存报告当作实时行情。

> 这不是投资建议。实盘自动下单仍由后端硬锁；所有策略应先完成历史验证和长周期模拟实测。

## 当日策略

独立的“当日策略”区域支持切换 `SNDK`、`MRVL`、`SOXL`、`NBIS` 和 MiniMax。MiniMax 按港交所 `0100.HK` 处理，不会套用美股交易时段和期权假设。

每次生成会将已验证数据按固定职责组合：

1. 重大消息和宏观事件决定入场时机。
2. 最近到期 ATM Straddle 定义理论隐含波动区间。
3. 期权 OI、Gamma 集中和延时 bid/ask 估算用于识别博弈区间与资金倾向。
4. 前高低点、VWAP、15 分钟 EMA 和期权墙仅作为价格结构流动性代理。
5. 板块相对强弱确认方向，VIX、10Y、DXY、原油和纳指期货过滤系统风险。
6. 最终只输出方向、入场区间、TP1 / TP2 / TP3 和结构止损。

期权成交主动方只能根据延时聚合快照估算，不等于逐笔订单流事实；流动性区域也不是订单簿热力图。任何关键数据无法核验时，页面会明确显示“数据不可验证，不参与判断”并降低信心或输出观望。该功能不会自动下单。

## 智能盯盘

进入 App 后可以跳过 Binance 账户登录，直接打开“智能盯盘”。公开行情不需要 API Key。

智能盯盘的市场目录独立读取 Binance 真实公开合约列表，并按“加密永续”“美股 / ETF 永续”“亚洲股票永续”“商品永续”等分类。股票永续不依赖 Demo 账户是否提供该合约；例如 `SNDKUSDT` 会显示为“SNDK · 闪迪”。

智能体按以下顺序工作：

1. 从 Binance 获取已收盘 K 线、24 小时行情与资金费率。
2. 生成统一指标快照，包括 EMA、RSI、ATR、布林带、量比、支撑阻力和动量。
3. 趋势跟随、放量突破、极值回归、波动风控 Skills 分别读取同一快照并给出方向、分数和证据。
4. 规则共识或 DeepSeek/OpenAI 读取 Skill 证据，输出结构化策略 JSON。
5. 硬编码风控检查方向点位、止损距离、盈亏比、置信度、ATR 和仓位上限。
6. 通过风控的 LONG/SHORT 信号写入历史记录，并按配置推送到飞书群。

模型不可用时会自动回退到本地规则共识。系统只在新的已收盘 K 线出现时自动分析，手动点击“立即分析”可以随时刷新当前标的。当前版本只生成策略，不会把 Agent 输出直接变成真实订单。

### 模型与密钥

设置中可选择：

- 规则共识：完全本地，不需要模型 Key。
- DeepSeek：默认模型 `deepseek-chat`。
- OpenAI：默认模型 `gpt-5-mini`，使用 Responses API Structured Outputs。

模型 API Key、飞书 Webhook 和签名密钥只保留在当前进程内存中，不写入磁盘。盯盘列表、Skill 权重和非敏感风控参数会保存在：

```text
~/Library/Application Support/Binance Quant/agent_settings.json
```

策略信号记录位于：

```text
~/Library/Application Support/Binance Quant/agent_signals.jsonl
```

### 飞书机器人

在飞书群的机器人设置中添加“自定义机器人”，复制 Webhook；建议同时开启签名校验并复制签名密钥。在智能体设置中填入两项后，先点击“发送测试消息”，成功后再启用盯盘推送。

## 启动与构建

```bash
cd /path/to/angel-quant
source .venv/bin/activate
bq-app
```

```bash
cd /path/to/angel-quant
./scripts/build_macos_app.sh
open "dist/只想玩天使的量化.app"
```

## 产品流程

启动页可连接 Binance Demo API，也可以跳过登录。API Key 和 Secret 只保存在当前进程内存，不写入组合文件、浏览器存储或应用配置。

工作台按职责分为五个功能区：

- 当日策略：为 SNDK、MRVL、SOXL、NBIS 与 MiniMax 生成可核验、带硬闸门的当日研究计划。
- 智能盯盘：持续读取已收盘行情并生成结构化策略信号，可选模型协作与飞书通知。
- 模拟盘实测：使用 Freqtrade 独立模拟钱包和本地 SQLite 交易记录，不连接真实资金。
- 策略验证：下载公开历史 K 线，对整个多项目组合或跨市场策略运行资金线回测。
- 实盘账户：允许连接并读取真实账户，自动执行继续硬锁。

`SNDK` 已接入历史验证：正股日线负责生成信号，Binance `SNDKUSDT` 股票永续 1 分钟 K 线负责模拟成交。它当前不能启动 Dry-run 或实盘；`MU`、美股券商行情和正股交易仍未接入。

## 策略、项目与组合

三个概念分层管理：

- 策略：信号、入场、退出和持仓规则。
- 项目：交易标的、项目预算、首次投入和杠杆。
- 投资组合：总本金、运行时间、最大并发仓位和回撤警戒线。

组合回测使用同一条时间线和共享钱包，真实计算同时持仓和资金占用，不把多个单币回测结果简单相加。项目预算是资金隔离约束；当前 Freqtrade 引擎按项目读取首次投入和杠杆，回撤警戒线目前作为报告阈值，不宣称是账户级强制平仓。

## 策略1

策略1使用 1m 收盘 K 线执行，由 5m EMA7/EMA25/EMA100 和 15m EMA20/EMA60 确认主趋势，再等待 1m EMA7 回踩收复事件。信号包含 ADX、EMA 间距、ATR 距离、趋势年龄和成交量过滤。

默认设置：

- 20x 逐仓
- 首次保证金 50 USDT
- 净保证金 ROI +15% 止盈
- 净保证金 ROI 约 -25% 止损
- 固定仓位，不启用马丁或条件补仓
- 不因反向信号立即反手

## SNDK 盘后动量

该策略只允许一个 `SNDKUSDT` 股票永续项目，默认项目本金 `1000 USDT`、每次使用项目权益的 `50%` 作为保证金、`5x` 杠杆。

默认规则：

- SNDK 正股日线实体涨幅达到 `5%` 且实体占全日振幅至少 `50%`，收盘确认一分钟后做多。
- 日线实体跌幅达到 `5%` 且实体占全日振幅至少 `50%`，收盘确认一分钟后做空。
- 第三根及之后的连续大阳线禁止追多；连续大阴线仍允许做空。
- 可选等待回撤入场：以正股收盘价为基准，做多等待合约回撤、做空等待合约反弹，幅度默认 `0.5%`；未触价则放弃该次信号。该选项默认关闭，以保留旧组合的立即入场行为。
- 合约价格上涨或下跌 `1%` 止盈，反向变化 `5%` 止损。
- 若止盈止损均未触发，在正股收盘对应的同一个北京时间自然日 `21:00` 强制退出；21:00后不再开仓，周末不跨日持仓。
- 回测计入双边手续费、可配置不利滑点和实际 Binance 资金费；同一分钟同时触及止盈止损时按止损优先。

历史数据缓存位于：

```text
~/Library/Application Support/Binance Quant/market_data/sndk_hybrid
```

该策略只做历史研究。正股数据源、盘后点差和流动性都可能变化，30 天高胜率不能替代更长区间的样本外验证。

## 策略接口

用户策略目录：

```text
~/Library/Application Support/Binance Quant/strategies
```

一个策略插件需要：

1. 继承 `binance_quant.strategy_api.Strategy`。
2. 声明 `strategy_id`、`name`、`version` 和 `description`。
3. 声明 `market_types`、`capabilities` 和 `parameters`。
4. `generate(frame, parameters)` 返回包含 `signal` 的 DataFrame；信号只能是 `-1/0/1`。
5. 导出 `STRATEGY` 实例或 `Strategy` 子类。
6. 如需组合 Freqtrade 回测，声明：

```python
backtest_adapter = {
    "engine": "freqtrade",
    "strategy_class": "MyFreqtradeStrategy",
    "supports_portfolio": True,
    "supports_dry_run": True,
}
```

对应 Freqtrade 策略类放入：

```text
~/Library/Application Support/Binance Quant/freqtrade/strategies
```

主界面会自动根据 `StrategyParameter` 生成参数输入框，不需要为每个新策略重写前端。统一接口位于 `src/binance_quant/strategy_api.py`，组合领域模型位于 `src/binance_quant/portfolio.py`。

## Freqtrade

安装本地 sidecar：

```bash
cd /path/to/angel-quant
./scripts/install_freqtrade_engine.sh
```

工作区位于：

```text
~/Library/Application Support/Binance Quant/freqtrade
```

App 会继承 macOS 当前系统代理。历史回测不需要 API；Dry-run 使用独立模拟钱包。现有 `tradesv3.dryrun.sqlite` 不会因构建或回测被删除。

## 验证

```bash
cd /path/to/angel-quant
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src
```
