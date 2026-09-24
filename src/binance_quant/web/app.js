const state = {
  initialized: false,
  desktopReady: false,
  connected: false,
  environment: "demo",
  maskedKey: "",
  symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT"],
  strategies: [],
  portfolios: [],
  selectedStrategies: { simulation: "", validation: "" },
  dialogMode: "validation",
  editingPortfolioId: "",
  freqtrade: null,
  lastCompletedFile: "",
  statusTimer: null,
  agentTimer: null,
  agentBootstrap: null,
  agentStatus: null,
  dailyCatalog: [],
  dailyAssetId: "SNDK",
  dailyResults: {},
  dailyLoading: false,
};

const $ = (id) => document.getElementById(id);
const viewMeta = {
  home: ["工作台 / 总览", "今日概览"],
  daily: ["工作台 / 当日策略", "当日策略"],
  agent: ["工作台 / 智能盯盘", "智能盯盘"],
  simulation: ["工作台 / 模拟盘", "模拟盘"],
  validation: ["工作台 / 策略验证", "验证策略与资金曲线"],
  live: ["工作台 / 实盘账户", "真实账户只读连接"],
  strategies: ["工作台 / 策略库", "策略库"],
  settings: ["工作台 / 设置", "设置"],
};

function isDesktop(method) {
  return Boolean(window.pywebview?.api && typeof window.pywebview.api[method] === "function");
}

function mockStrategies() {
  return [
    {
      id: "strategy_1",
      name: "策略1",
      version: "2.0.0",
      description: "多周期EMA趋势回踩，20倍逐仓，固定净ROI止盈止损，支持组合项目参数。",
      market_types: ["crypto_futures"],
      capabilities: ["long", "short", "portfolio", "conditional_scale_in"],
      backtest_adapter: { engine: "freqtrade", strategy_class: "Strategy1", supports_portfolio: true },
      automation_defaults: { leverage: 20, take_profit_pct: 15, stop_loss_pct: 25 },
      parameters: [],
    },
    {
      id: "sndk_after_close",
      name: "SNDK 盘后动量",
      version: "1.2.0",
      description: "SNDK正股收出大实体日K后，在Binance SNDKUSDT盘后顺势验证。",
      market_types: ["equity_perpetual"],
      capabilities: ["long", "short", "cross_market_signal", "validation_only"],
      backtest_adapter: { engine: "sndk_hybrid", supports_portfolio: true, supports_dry_run: false, fixed_symbols: ["SNDKUSDT"], market: "equity_perpetual", default_capital: 1000, default_budget: 1000, default_initial_stake: 500, default_leverage: 5, max_leverage: 10 },
      automation_defaults: { leverage: 5, allocation_pct: 50, take_profit_price_pct: 1, stop_loss_price_pct: 5 },
      parameters: [
        { key: "large_body_pct", label: "大实体最小涨跌", kind: "number", default: 5, minimum: .5, maximum: 20, step: .5 },
        { key: "min_body_ratio", label: "实体占振幅", kind: "number", default: .5, minimum: .1, maximum: 1, step: .05 },
        { key: "take_profit_pct", label: "价格止盈", kind: "number", default: 1, minimum: .2, maximum: 10, step: .1 },
        { key: "stop_loss_pct", label: "价格止损", kind: "number", default: 5, minimum: .5, maximum: 20, step: .5 },
        { key: "entry_delay_minutes", label: "收盘后延迟", kind: "integer", default: 1, minimum: 1, maximum: 30, step: 1 },
        { key: "wait_for_pullback", label: "等待回撤入场", kind: "boolean", default: false },
        { key: "entry_pullback_pct", label: "回撤/反弹幅度(%)", kind: "number", default: .5, minimum: .1, maximum: 10, step: .1 },
      ],
    },
    {
      id: "sma_crossover",
      name: "SMA交叉",
      version: "1.0.0",
      description: "基础双均线研究策略，用于接口示例和快速信号验证。",
      market_types: ["crypto_futures"],
      capabilities: ["long", "short"],
      backtest_adapter: { engine: "native" },
      parameters: [],
    },
  ];
}

function mockPortfolio() {
  const symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"];
  return {
    portfolio_id: "core_5",
    name: "核心五项目",
    strategy_id: "strategy_1",
    initial_capital: 5000,
    run_days: 30,
    max_concurrent_positions: 5,
    account_stop_pct: 12,
    projects: symbols.map((symbol, index) => ({
      project_id: `project_${index + 1}`,
      name: symbol.replace("USDT", ""),
      symbol,
      budget: 1000,
      initial_stake: 50,
      leverage: 20,
      market: "crypto_futures",
      enabled: true,
      parameters: {},
    })),
  };
}

function mockAgentBootstrap() {
  return {
    config: {
      provider: "rules", model: "deepseek-chat", poll_seconds: 30,
      watchlist: [{ symbol: "BTCUSDT", timeframe: "15m" }, { symbol: "ETHUSDT", timeframe: "1h" }],
      skill_weights: { trend_following: 1.2, breakout: 1, mean_reversion: .7, risk_guard: 1.3 },
      risk: { account_balance: 1000, risk_per_trade_pct: 1, leverage: 3, max_margin_pct: 20, min_confidence: 60, min_risk_reward: 1.5, max_stop_pct: 3, max_atr_pct: 3.2 },
      push_enabled: true, api_key_configured: false, feishu_configured: false,
    },
    skills: [
      { id: "trend_following", name: "趋势跟随", description: "用 EMA20/EMA60、价格位置与多周期动量识别顺势机会。", default_weight: 1.2 },
      { id: "breakout", name: "放量突破", description: "检查近 20 根 K 线边界、成交量放大与突破延续性。", default_weight: 1 },
      { id: "mean_reversion", name: "极值回归", description: "结合 RSI 与布林带识别过度延伸后的反转候选。", default_weight: .7 },
      { id: "risk_guard", name: "波动与拥挤风控", description: "检查 ATR 波动、资金费率和量价异常。", default_weight: 1.3 },
    ],
    markets: [
      { id: "crypto_futures", name: "加密永续", items: ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"].map((symbol) => ({ symbol, base_asset: symbol.replace("USDT", ""), label: symbol.replace("USDT", "") })) },
      { id: "us_equity_perpetual", name: "美股 / ETF 永续", items: [
        ["SNDKUSDT", "SNDK · 闪迪"], ["NVDAUSDT", "NVDA · 英伟达"], ["TSLAUSDT", "TSLA · 特斯拉"],
        ["MUUSDT", "MU · 美光"], ["WDCUSDT", "WDC · 西部数据"], ["AAPLUSDT", "AAPL · 苹果"],
        ["MSFTUSDT", "MSFT · 微软"], ["AMZNUSDT", "AMZN · 亚马逊"], ["GOOGLUSDT", "GOOGL · 谷歌"],
        ["METAUSDT", "META"], ["AMDUSDT", "AMD"], ["MSTRUSDT", "MSTR · Strategy"],
      ].map(([symbol, label]) => ({ symbol, base_asset: symbol.replace("USDT", ""), label })) },
    ],
    providers: [{ id: "rules", name: "规则共识" }, { id: "deepseek", name: "DeepSeek" }, { id: "openai", name: "OpenAI" }],
  };
}

function mockAgentRecord() {
  const now = Date.now();
  const candles = Array.from({ length: 72 }, (_, index) => {
    const base = 63620 + index * 8 + Math.sin(index / 4) * 95;
    const open = base + Math.sin(index * 1.7) * 24;
    const close = base + Math.cos(index * 1.3) * 28;
    return { time: new Date(now - (72 - index) * 900000).toISOString(), open, close, high: Math.max(open, close) + 38, low: Math.min(open, close) - 34 };
  });
  return {
    id: "preview001", created_at: new Date().toISOString(), source: "RULES", model: "本地规则共识", model_error: "",
    snapshot: { symbol: "BTCUSDT", timeframe: "15m", candle_time: new Date(now - 900000).toISOString(), price: candles.at(-1).close, change_24h_pct: 2.34, ema20: 64108.3, ema60: 63742.8, rsi14: 61.8, atr14: 188.4, atr_pct: .29, volume_ratio: 1.46, momentum_3_pct: .41, momentum_12_pct: 1.24, support: 63480, resistance: 64230, bb_upper: 64412, bb_lower: 63324, funding_rate_pct: .01, trend: "UP", regime: "TRENDING" },
    assessments: [
      { skill_id: "trend_following", name: "趋势跟随", bias: "LONG", score: 75, evidence: ["价格位于 EMA20 上方且 EMA20 高于 EMA60", "近 3 根动量 +0.41%"] },
      { skill_id: "breakout", name: "放量突破", bias: "LONG", score: 70, evidence: ["价格触及近 20 根前高区域", "成交量为 20 根均量的 1.46 倍"] },
      { skill_id: "mean_reversion", name: "极值回归", bias: "WAIT", score: 0, evidence: ["RSI 61.8，未形成极值共振"] },
      { skill_id: "risk_guard", name: "波动与拥挤风控", bias: "WAIT", score: 0, evidence: ["波动率与资金费率未触发风险阈值"] },
    ],
    signal: { action: "LONG", entry_low: 64120.2, entry_high: 64158.0, stop_loss: 63852.4, take_profit: 64712.1, confidence: 82, risk_reward: 2.05, quantity: .036, notional: 2309.0, estimated_margin: 200, risk_status: "PASSED", validation_notes: ["仓位已按最大保证金占比缩小"], reason: "均线结构向上；突破区域获得成交量确认", invalid_if: "收盘跌破止损位或 EMA20 下穿 EMA60。" },
    push: { sent: false, message: "飞书未配置" }, candles,
  };
}

function mockDailyCatalog() {
  return [
    { id: "SNDK", symbol: "SNDK", name: "闪迪", display_name: "SNDK · 闪迪", exchange: "NASDAQ", currency: "USD", market: "美股", options_supported: true },
    { id: "MRVL", symbol: "MRVL", name: "迈威尔科技", display_name: "MRVL · 迈威尔", exchange: "NASDAQ", currency: "USD", market: "美股", options_supported: true },
    { id: "SOXL", symbol: "SOXL", name: "半导体三倍做多 ETF", display_name: "SOXL · 3倍半导体", exchange: "NYSE Arca", currency: "USD", market: "美股 ETF", options_supported: true, leveraged_etf: true },
    { id: "NBIS", symbol: "NBIS", name: "Nebius", display_name: "NBIS · Nebius", exchange: "NASDAQ", currency: "USD", market: "美股", options_supported: true },
    { id: "MINIMAX", symbol: "0100.HK", name: "MiniMax", display_name: "0100.HK · MiniMax", exchange: "HKEX", currency: "HKD", market: "港股", options_supported: false },
  ];
}

function mockDailyResult(assetId = "SNDK") {
  const asset = mockDailyCatalog().find((item) => item.id === assetId) || mockDailyCatalog()[0];
  const limited = asset.id === "MINIMAX";
  const priceMap = { SNDK: 1546.11, MRVL: 206.68, SOXL: 106.35, NBIS: 203.85, MINIMAX: 349.40 };
  const price = priceMap[asset.id];
  const move = limited ? null : price * (asset.id === "SOXL" ? .062 : .035);
  const low = move ? price - move : null;
  const high = move ? price + move : null;
  return {
    asset,
    quote: { price, change_pct: asset.id === "MRVL" ? -1.86 : 1.08, session: "盘前", as_of: new Date().toISOString() },
    generated_at: new Date().toISOString(),
    completeness: { score: limited ? 52 : 86, label: limited ? "受限" : "良好", verified: limited ? 4 : 7, total: 8 },
    timing: limited ? "观望" : "等待美股开盘后确认",
    summary: {
      events: "今晚无已核验的一级事件",
      implied_range: move ? `${money(low)} – ${money(high)}` : null,
      core_range: move ? `${money(price - move * .72)} – ${money(price + move * .72)}` : null,
      option_flow: limited ? null : "中性（延时成交估算）",
      strikes: limited ? null : `Call ${money(price + move * .6, 0)} / Put ${money(price - move * .6, 0)}`,
      upper_liquidity: `${money(price * 1.012)} – ${money(price * 1.016)}`,
      lower_liquidity: `${money(price * .984)} – ${money(price * .989)}`,
      sweep: "暂无明显优势",
      relative_strength: limited ? "恒指参照 / 中性" : "SOX 偏多 / 标的中性",
      systemic_risk: "VIX 18.4 / 中等",
    },
    strategy: {
      direction: limited ? "观望" : "观望", direction_code: "WAIT", entry_low: null, entry_high: null,
      tp1: null, tp2: null, tp3: null, stop_loss: null,
      condition: limited ? "核心期权资金数据不可验证" : "期权资金与结构方向未共振，等待开盘确认",
      confidence: limited ? 35 : 58, confidence_label: limited ? "低" : "中等", timing: limited ? "观望" : "数据后",
    },
    sources: [
      { name: "Yahoo Finance Chart", url: `https://finance.yahoo.com/quote/${asset.symbol}`, as_of: new Date().toISOString(), status: "verified" },
      ...(limited ? [] : [{ name: "Cboe Delayed Options", url: `https://www.cboe.com/delayed_quotes/${asset.symbol}/quote_table`, as_of: new Date().toISOString(), status: "verified" }]),
    ],
    warnings: [
      "Expected Move 基于最近到期 ATM Straddle，不是价格保证。",
      "Bid/Ask 一侧成交金额为延时快照估算，不能完全识别开平仓。",
      ...(asset.leveraged_etf ? ["SOXL 为每日 3 倍杠杆 ETF，存在路径依赖和隔夜跳空风险。"] : []),
      ...(limited ? ["MiniMax 为港交所 0100.HK，无可用的同等期权资金数据，核心方法不完整。"] : []),
      "本功能只生成研究策略，不会自动下单。",
    ],
    modules: [
      { title: "期权波动", status: limited ? "unavailable" : "verified", summary: limited ? "数据不可验证，不参与判断" : "采用最近到期 ATM Call + Put 的中间价。", details: [] },
      { title: "流动性", status: "limited", summary: "仅使用前高低点、VWAP、15分钟 EMA 和期权墙的价格结构代理；非订单簿热力图。", details: [] },
    ],
    preview: true,
  };
}

async function callApi(method, ...args) {
  if (isDesktop(method)) return window.pywebview.api[method](...args);
  if (method === "bootstrap") {
    return { ok: true, data: { symbols: state.symbols, strategies: mockStrategies(), portfolios: [], portfolio_template: mockPortfolio(), connected: false, live_automation_locked: true, agent: mockAgentBootstrap(), daily_strategy_assets: mockDailyCatalog() } };
  }
  if (method === "daily_strategy_catalog") return { ok: true, data: mockDailyCatalog() };
  if (method === "generate_daily_strategy") return { ok: true, data: mockDailyResult(args[0]?.asset_id || "SNDK") };
  if (method === "agent_status") {
    if (!state.agentStatus) {
      const preview = mockAgentRecord();
      state.agentStatus = { running: false, config: state.agentBootstrap?.config || mockAgentBootstrap().config, latest: [preview], history: [preview], logs: ["[09:30:00] 浏览器预览已载入规则共识信号。"] };
    }
    return { ok: true, data: state.agentStatus };
  }
  if (method === "configure_agent") {
    state.agentStatus = state.agentStatus || { running: false, latest: [], history: [], logs: [] };
    state.agentStatus.config = { ...(state.agentStatus.config || mockAgentBootstrap().config), ...args[0], risk: { ...(state.agentStatus.config?.risk || {}), ...(args[0]?.risk || {}) } };
    return { ok: true, data: state.agentStatus };
  }
  if (method === "start_agent_monitor" || method === "stop_agent_monitor") {
    state.agentStatus = state.agentStatus || { config: mockAgentBootstrap().config, latest: [], history: [], logs: [] };
    state.agentStatus.running = method === "start_agent_monitor";
    state.agentStatus.logs = [...(state.agentStatus.logs || []), method === "start_agent_monitor" ? "[09:31:00] 智能盯盘已启动。" : "[09:32:00] 智能盯盘已停止。"];
    return { ok: true, data: state.agentStatus };
  }
  if (method === "analyze_now") {
    const record = mockAgentRecord();
    const item = args[0]?.watch_item;
    if (item) Object.assign(record.snapshot, { symbol: item.symbol, timeframe: item.timeframe });
    state.agentStatus = state.agentStatus || { running: false, config: mockAgentBootstrap().config, latest: [], history: [], logs: [] };
    state.agentStatus.latest = [record, ...(state.agentStatus.latest || []).filter((entry) => entry.snapshot.symbol !== record.snapshot.symbol || entry.snapshot.timeframe !== record.snapshot.timeframe)];
    state.agentStatus.history = [record, ...(state.agentStatus.history || [])].slice(0, 50);
    return { ok: true, data: record };
  }
  if (method === "test_feishu") return { ok: true, data: { sent: true, message: "飞书已接收消息。" } };
  if (["freqtrade_status", "research_status"].includes(method)) {
    if (state.freqtrade) return { ok: true, data: state.freqtrade };
    return { ok: true, data: { available: true, status: "idle", reason: "浏览器预览", running: false, result: null, logs: [], dry_run: { running: false, status: "stopped", reason: "未启动", logs: [] } } };
  }
  if (["save_portfolio", "start_portfolio_backtest", "start_portfolio_dry_run"].includes(method)) {
    return { ok: true, data: method === "save_portfolio" ? args[0] : await mockRunResult(args[0], method) };
  }
  if (method === "connect") return { ok: true, data: { environment: args[0]?.environment || "demo", masked_key: "DEMO…VIEW", account: { wallet_balance: 5000, available_balance: 5000, unrealized_pnl: 0, margin_usage_pct: 0 } } };
  if (method === "account_snapshot") return { ok: true, data: { account: { wallet_balance: 5000, available_balance: 5000, unrealized_pnl: 0, margin_usage_pct: 0 }, positions: [] } };
  return { ok: true, data: {} };
}

async function mockRunResult(portfolio, method) {
  if (method === "start_portfolio_dry_run") {
    return { available: true, status: "idle", reason: "准备就绪", running: false, dry_run: { running: true, status: "running", reason: "组合模拟实测运行中", deadline: new Date(Date.now() + portfolio.run_days * 86400000).toISOString(), portfolio, logs: ["Dry-run preview started"] } };
  }
  const profits = [8, -3, 12, 6, -4, 15, 10, -8, 13, 17, -5, 21];
  let balance = portfolio.initial_capital;
  const equity = profits.map((profit, index) => {
    balance += profit;
    return { date: `2026-07-${String(index + 1).padStart(2, "0")}`, balance, profit };
  });
  const symbols = portfolio.projects.map((item) => item.symbol);
  return { available: true, running: false, status: "completed", reason: "组合回测完成", logs: [], dry_run: { running: false, status: "stopped", logs: [] }, result: {
    symbol: "PORTFOLIO", symbols, days: portfolio.run_days, initial_capital: portfolio.initial_capital, total_trades: 84, wins: 55, win_rate_pct: 65.48, profit_pct: 1.64, profit_abs: 82, max_drawdown_pct: 1.82, profit_factor: 1.19, payoff_ratio: .64, estimated_fees: 83.6, average_trade_pct: .98, result_file: "preview.json", portfolio, equity_curve: equity,
    long: { trades: 26, profit_abs: -12, profit_pct: -.24 }, short: { trades: 58, profit_abs: 94, profit_pct: 1.88 },
    per_pair: symbols.map((symbol, index) => ({ symbol, trades: 12 + index * 2, win_rate_pct: 61 + index, profit_abs: [-28, 45, 31, 22, 12][index] || 0, profit_pct: [-.56, .9, .62, .44, .24][index] || 0, profit_factor: [.82, 1.42, 1.27, 1.18, 1.09][index] || 1, max_drawdown_pct: 1 + index * .2 })),
    exit_reasons: [{ reason: "roi", trades: 55, profit_abs: 405, profit_pct: 8.1 }, { reason: "stop_loss", trades: 29, profit_abs: -323, profit_pct: -6.46 }],
  } };
}

function showToast(message, type = "") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`.trim();
  toast.textContent = message;
  $("toastStack").appendChild(toast);
  window.setTimeout(() => toast.remove(), 3800);
}

function setBusy(button, busy, busyLabel, idleLabel) {
  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
}

function money(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value, suffix = "") {
  const number = Number(value) || 0;
  return `${number >= 0 ? "+" : ""}${money(number)}${suffix}`;
}

function resultClass(value) {
  return Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "";
}

function strategyById(id) {
  return state.strategies.find((strategy) => strategy.id === id);
}

function strategySupportsPortfolio(strategy, context = "validation") {
  const adapter = strategy?.backtest_adapter || {};
  if (!adapter.supports_portfolio) return false;
  if (context === "simulation") return adapter.engine === "freqtrade" && adapter.supports_dry_run !== false;
  return ["freqtrade", "sndk_hybrid"].includes(adapter.engine);
}

async function initialize() {
  const desktopReady = isDesktop("bootstrap");
  if (location.hash.startsWith('#embedded=') && !desktopReady) return;
  if (state.initialized && (!desktopReady || state.desktopReady)) return;
  if (!state.initialized) {
    state.initialized = true;
    bindEvents();
  }
  const result = await callApi("bootstrap", "demo");
  if (!result.ok) {
    showToast(result.error || "初始化失败", "error");
    return;
  }
  const data = result.data;
  state.symbols = data.symbols?.length ? data.symbols : state.symbols;
  state.strategies = Array.isArray(data.strategies) ? data.strategies : mockStrategies();
  state.portfolios = data.portfolios || [];
  state.portfolioTemplate = data.portfolio_template || mockPortfolio();
  state.agentBootstrap = data.agent || mockAgentBootstrap();
  state.dailyCatalog = data.daily_strategy_assets?.length ? data.daily_strategy_assets : mockDailyCatalog();
  if (!state.dailyCatalog.some((asset) => asset.id === state.dailyAssetId)) state.dailyAssetId = state.dailyCatalog[0]?.id || "SNDK";
  state.connected = Boolean(data.connected);
  state.maskedKey = data.masked_key || "";
  state.desktopReady = desktopReady;
  hydrateWorkspace(data.workspace_settings || {});
  renderAll();
  const embeddedView = new URLSearchParams(location.hash.slice(1)).get('embedded');
  if (['agent', 'simulation', 'validation', 'live'].includes(embeddedView)) {
    document.body.classList.add('embedded-workspace');
    enterApplication();
    showView(embeddedView);
  }
  await refreshFreqtradeStatus();
  await refreshAgentStatus();
  if (state.statusTimer) window.clearInterval(state.statusTimer);
  state.statusTimer = window.setInterval(refreshFreqtradeStatus, 2000);
  if (state.agentTimer) window.clearInterval(state.agentTimer);
  state.agentTimer = window.setInterval(refreshAgentStatus, 5000);
}

function renderAll() {
  $("strategyCount").textContent = state.strategies.length;
  $("portfolioCount").textContent = state.portfolios.length;
  renderConnection();
  renderStrategyPickers();
  renderStrategyLibrary();
  renderPortfolios();
  renderAgentSettings();
  renderDailyAssetPicker();
  renderDailyCards();
}

function enterApplication() {
  $("entryScreen").classList.add("is-hidden");
  $("appShell").classList.remove("is-hidden");
  showView("home");
}

function showEntry() {
  $("appShell").classList.add("is-hidden");
  $("entryScreen").classList.remove("is-hidden");
}

function showView(name) {
  Object.keys(viewMeta).forEach((view) => {
    $(`${view}View`).classList.toggle("active", view === name);
  });
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  $("breadcrumb").textContent = viewMeta[name][0];
  $("viewTitle").textContent = viewMeta[name][1];
  $("newPortfolioTop").classList.toggle("is-hidden", !["home", "simulation", "validation"].includes(name));
  $("workspace")?.scrollTo?.({ top: 0, behavior: "smooth" });
  if (name === "agent") {
    const target = $('agentView');
    Array.from(target.children).forEach(child => { if(child.id !== 'pipelineFrame') child.style.display='none'; });
    if (!document.getElementById('pipelineFrame')) {
      const frame=document.createElement('iframe');frame.id='pipelineFrame';frame.title='智能策略工作台';
      frame.style.cssText='width:100%;height:85vh;border:0';target.appendChild(frame);
      window.pywebview.api.pipeline_open().then(result=>{if(!result.ok)throw Error(result.error);frame.src=result.data.url}).catch(error=>{frame.remove();showToast(String(error),'error')});
    }
  }
  if (name === "daily") showDailyOverview();
}

function dailyAsset() {
  return state.dailyCatalog.find((asset) => asset.id === state.dailyAssetId) || state.dailyCatalog[0] || mockDailyCatalog()[0];
}

function renderDailyAssetPicker() {
  const target = $("dailyAssetPicker");
  if (!target) return;
  target.innerHTML = state.dailyCatalog.map((asset) => {
    const active = asset.id === state.dailyAssetId;
    const displaySuffix = String(asset.display_name || "").split("·").slice(1).join("·").trim();
    const shortName = displaySuffix || asset.name || asset.symbol;
    return `<button class="${active ? "active" : ""}" data-daily-asset="${escapeHtml(asset.id)}" type="button" role="option" aria-selected="${active}">${escapeHtml(asset.symbol)}<small>${escapeHtml(shortName)}</small></button>`;
  }).join("");
  target.querySelectorAll("[data-daily-asset]").forEach((button) => button.addEventListener("click", () => selectDailyAsset(button.dataset.dailyAsset)));
  if (!state.dailyResults[state.dailyAssetId]) renderDailyEmpty(dailyAsset());
}

function selectDailyAsset(assetId) {
  if (!state.dailyCatalog.some((asset) => asset.id === assetId) || state.dailyLoading) return;
  state.dailyAssetId = assetId;
  renderDailyAssetPicker();
  const cached = state.dailyResults[assetId];
  if (cached) renderDailyStrategy(cached);
  else loadDailyStrategy();
}

function dailyUnavailable() {
  return "数据不可验证，不参与判断";
}

function dailyValue(value, fallback = null) {
  if (value === null || value === undefined || value === "") return fallback || dailyUnavailable();
  return String(value);
}

function dailyPrice(value) {
  return value === null || value === undefined || !Number.isFinite(Number(value)) ? "等待确认" : money(value);
}

function dailyRange(low, high) {
  if (![low, high].every((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))) return "等待确认";
  return `${money(low)} – ${money(high)}`;
}

function dailyTime(value) {
  if (!value) return "时间未验证";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function dailySessionLabel(value) {
  return ({ pre_market: "盘前", regular: "盘中", after_hours: "盘后", closed: "休市" })[value] || dailyValue(value, "市场状态未知");
}

function dailyStatus(value) {
  const status = String(value || "unavailable").toLowerCase();
  return {
    available: { className: "verified", label: "已验证" },
    verified: { className: "verified", label: "已验证" },
    delayed: { className: "delayed", label: "延时" },
    partial: { className: "partial", label: "部分可用" },
    limited: { className: "partial", label: "受限" },
    stale: { className: "stale", label: "已过期" },
    not_applicable: { className: "not-applicable", label: "不适用" },
    unavailable: { className: "unavailable", label: "不可用" },
  }[status] || { className: "unavailable", label: status };
}

function safeWebUrl(value) {
  try {
    const url = new URL(String(value));
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_) {
    return "";
  }
}

function renderDailyEmpty(asset) {
  $('dailySummaryGrid').innerHTML = '<p class="empty-state">等待当前标的数据</p>';
  $('dailySources').textContent = '等待生成';
  $('dailyWarnings').innerHTML = '';
  $('dailyEvidenceModules').innerHTML = '';
  if ($('researchLinks')) $('researchLinks').remove();
  $("dailyAssetName").textContent = asset.display_name || `${asset.symbol} · ${asset.name}`;
  $("dailyMarket").textContent = `${asset.exchange || "--"} · ${asset.currency || "--"}`;
  $("dailyPrice").textContent = "--";
  $("dailyChange").textContent = "--";
  $("dailyChange").className = "";
  $("dailyCompleteness").textContent = "--";
  $("dailyTiming").textContent = "--";
  $("dailySession").textContent = "等待生成";
  $("dailyAsOf").textContent = "尚无数据";
  $("dailyFreshness").textContent = "未生成";
  $("dailyFreshness").className = "daily-freshness";
  $("dailyDecision").className = "daily-decision is-empty";
  $("dailyDirection").className = "daily-direction";
  $("dailyDirection").innerHTML = `<small>方向</small><strong>--</strong><span>等待最新数据</span>`;
  $("dailyConfidence").textContent = "等待最新数据";
  $("dailyEntry").textContent = "--";
  $("dailyCondition").textContent = "入场为条件触发，不是市价指令";
  ["dailyTp1", "dailyTp2", "dailyTp3", "dailySl"].forEach((id) => { $(id).textContent = "--"; });
}

async function loadDailyStrategy(force = false) {
  if (state.dailyLoading) return;
  state.dailyLoading = true;
  const button = $("refreshDailyStrategy");
  setBusy(button, true, "正在核验数据…", "刷新策略");
  $("dailySession").textContent = "正在获取行情与期权";
  $("dailyAsOf").textContent = dailyAsset().display_name || dailyAsset().symbol;
  try {
    const result = await callApi("generate_daily_strategy", { asset_id: state.dailyAssetId, force });
    if (!result.ok) {
      renderDailyError(result.error || "当日策略生成失败");
      return;
    }
    state.dailyResults[state.dailyAssetId] = result.data;
    renderDailyStrategy(result.data);
    renderDailyCards();
  } catch (error) {
    renderDailyError(error?.message || "当日策略生成失败");
  } finally {
    state.dailyLoading = false;
    setBusy(button, false, "正在核验数据…", "刷新策略");
  }
}

function renderDailyError(message) {
  renderDailyEmpty(dailyAsset());
  $("dailySession").textContent = "生成失败";
  $("dailyAsOf").textContent = String(message);
  $("dailyFreshness").textContent = "不可用";
  $("dailyFreshness").className = "daily-freshness error";
  $("dailyDecision").className = "daily-decision is-empty has-error";
  $("dailyDirection").innerHTML = `<small>方向</small><strong>--</strong><span>${escapeHtml(message)}</span>`;
  showToast(message, "error");
}

function renderDailyStrategy(report) {
  const asset = report.asset || dailyAsset();
  const quote = report.quote || {};
  const completeness = report.completeness || {};
  const strategy = report.strategy || {};
  const summary = report.summary || {};
  const directionCode = String(strategy.direction_code || strategy.action || "WAIT").toUpperCase();
  const direction = strategy.direction || ({ LONG: "做多", SHORT: "做空", WAIT: "观望" })[directionCode] || "观望";
  const generatedAt = report.generated_at || quote.as_of;

  $("dailyAssetName").textContent = asset.display_name || `${asset.symbol || "--"} · ${asset.name || "--"}`;
  $("dailyMarket").textContent = `${asset.exchange || asset.market || "--"} · ${asset.currency || "--"}`;
  $("dailyPrice").textContent = quote.price == null ? "--" : money(quote.price);
  $("dailyChange").textContent = quote.change_pct == null ? "--" : signed(quote.change_pct, "%");
  $("dailyChange").className = resultClass(quote.change_pct);
  $("dailyCompleteness").textContent = completeness.score == null ? dailyValue(completeness.label, "--") : `${money(completeness.score, 0)}% · ${dailyValue(completeness.label, "")}`.replace(/ · $/, "");
  $("dailyTiming").textContent = dailyValue(strategy.timing || report.timing, "--");
  $("dailySession").textContent = dailySessionLabel(quote.session);
  $("dailyAsOf").textContent = `数据 ${dailyTime(quote.as_of || generatedAt)}`;
  $("dailyFreshness").textContent = report.preview ? "浏览器预览" : (report.freshness?.label || "已生成");
  $("dailyFreshness").className = `daily-freshness ${report.freshness?.status || (report.preview ? "preview" : "ready")}`;

  $("dailyDecision").className = `daily-decision ${directionCode.toLowerCase()}`;
  $("dailyDirection").className = `daily-direction ${directionCode.toLowerCase()}`;
  $("dailyDirection").innerHTML = `<small>方向</small><strong>${escapeHtml(direction)}</strong><span>${escapeHtml(strategy.timing || report.timing || "等待确认")}</span>`;
  const confidenceText = strategy.confidence == null ? "信心度未评估" : `信心度 ${money(strategy.confidence, 0)}%${strategy.confidence_label ? ` · ${strategy.confidence_label}` : ""}`;
  $("dailyConfidence").textContent = confidenceText;
  $("dailyEntry").textContent = dailyRange(strategy.entry_low, strategy.entry_high);
  $("dailyCondition").textContent = dailyValue(strategy.condition, "等待结构确认");
  $("dailyTp1").textContent = dailyPrice(strategy.tp1);
  $("dailyTp2").textContent = dailyPrice(strategy.tp2);
  $("dailyTp3").textContent = dailyPrice(strategy.tp3);
  $("dailySl").textContent = dailyPrice(strategy.stop_loss ?? strategy.sl);

  const summaryItems = [
    ["重大消息 / 今晚事件", summary.events],
    ["期权理论隐含区间", summary.implied_range],
    ["期权核心博弈区间", summary.core_range],
    ["期权资金方向", summary.option_flow],
    ["主要 Call / Put Strike", summary.strikes],
    ["上方流动性池", summary.upper_liquidity],
    ["下方流动性池", summary.lower_liquidity],
    ["预计优先插针", summary.sweep],
    ["板块 / 标的相对强弱", summary.relative_strength],
    ["VIX / 系统性风险", summary.systemic_risk],
  ];
  $("dailySummaryGrid").innerHTML = summaryItems.map(([label, value], index) => `<article class="${value == null ? "unavailable" : ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(dailyValue(value))}</strong><em>${String(index + 1).padStart(2, "0")}</em></article>`).join("");

  const sources = Array.isArray(report.sources) ? report.sources : [];
  $("dailySources").innerHTML = sources.length ? sources.map((source) => {
    const url = safeWebUrl(source.url);
    const status = dailyStatus(source.status);
    const label = `${source.name || "未命名数据源"}${source.as_of ? ` · ${dailyTime(source.as_of)}` : ""}`;
    return `<div class="daily-source"><span class="source-state ${status.className}" title="${escapeHtml(status.label)}"></span>${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>` : `<span>${escapeHtml(label)}</span>`}</div>`;
  }).join("") : `<p>${dailyUnavailable()}</p>`;
  const warnings = Array.isArray(report.warnings) ? report.warnings : [];
  $("dailyWarnings").innerHTML = warnings.length ? warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") : `<li>本功能只生成研究策略，不会自动下单。</li>`;
  const modules = Array.isArray(report.modules) ? report.modules : [];
  $("dailyEvidenceModules").innerHTML = modules.length ? modules.map((module) => {
    const status = dailyStatus(module.status);
    return `<article><header><strong>${escapeHtml(module.title || "未命名模块")}</strong><span class="module-state ${status.className}">${escapeHtml(status.label)}</span></header><p>${escapeHtml(dailyValue(module.summary))}</p>${Array.isArray(module.details) && module.details.length ? `<ul>${module.details.map((detail) => `<li>${escapeHtml(detail)}</li>`).join("")}</ul>` : ""}</article>`;
  }).join("") : `<p>${dailyUnavailable()}</p>`;
  renderResearchLinks(report);
}

function renderConnection() {
  const chip = $("connectionChip");
  chip.classList.toggle("connected", state.connected);
  chip.querySelector("strong").textContent = state.connected ? `${state.environment === "live" ? "真实网" : "Demo"} · ${state.maskedKey}` : "访客模式";
}

function strategyCard(strategy, context) {
  const selected = state.selectedStrategies[context] === strategy.id;
  const supported = strategySupportsPortfolio(strategy, context);
  const capabilities = (strategy.capabilities || []).slice(0, 4).map((item) => `<span>${capabilityLabel(item)}</span>`).join("");
  return `<button class="strategy-option ${selected ? "selected" : ""}" data-strategy-id="${strategy.id}" data-context="${context}" type="button" ${supported ? "" : "disabled"}>
    <header><h4>${escapeHtml(strategy.name)}</h4><span class="version">v${escapeHtml(strategy.version || "1.0.0")}</span></header>
    <p>${escapeHtml(strategy.description || "")}</p>
    <div class="capability-list">${capabilities}${supported ? "" : `<span>${context === "simulation" && strategy.backtest_adapter?.engine === "sndk_hybrid" ? "仅历史验证" : "待接适配器"}</span>`}</div>
  </button>`;
}

function capabilityLabel(value) {
  return ({ long: "做多", short: "做空", portfolio: "组合", conditional_scale_in: "条件补仓", fixed_position: "固定仓位", cross_market_signal: "跨市场信号", validation_only: "仅验证" })[value] || value;
}

function renderStrategyPickers() {
  for (const context of ["simulation", "validation"]) {
    const target = $(`${context}StrategyPicker`);
    target.innerHTML = state.strategies.map((strategy) => strategyCard(strategy, context)).join("");
    target.querySelectorAll(".strategy-option:not(:disabled)").forEach((button) => {
      button.addEventListener("click", () => selectStrategy(context, button.dataset.strategyId));
    });
  }
}

function selectStrategy(context, strategyId) {
  state.selectedStrategies[context] = strategyId;
  const strategy = strategyById(strategyId);
  $(`${context}Selection`).textContent = `${strategy.name} · v${strategy.version || "1.0.0"}`;
  $(`configure${context[0].toUpperCase()}${context.slice(1)}`).disabled = false;
  renderStrategyPickers();
}

function renderStrategyLibrary() {
  renderCompactLibrary();
}

function renderPortfolios() {
  const target = $("recentPortfolioList");
  if (!state.portfolios.length) {
    target.innerHTML = `<div class="portfolio-empty">尚未保存组合。新建组合后会显示在这里。</div>`;
    return;
  }
  target.innerHTML = state.portfolios.slice(-6).reverse().map((portfolio) => `<article class="portfolio-item" data-portfolio-id="${escapeHtml(portfolio.portfolio_id)}">
    <div><h4>${escapeHtml(portfolio.name)}</h4><p>${escapeHtml(strategyById(portfolio.strategy_id)?.name || portfolio.strategy_id)} · ${portfolio.projects?.length || 0} 个项目</p></div>
    <footer><span>${money(portfolio.initial_capital, 0)} U</span><span>${portfolio.run_days} DAYS</span></footer>
  </article>`).join("");
  target.querySelectorAll(".portfolio-item").forEach((item) => item.addEventListener("click", () => {
    const portfolio = state.portfolios.find((entry) => entry.portfolio_id === item.dataset.portfolioId);
    if (!portfolio) return;
    state.selectedStrategies.validation = portfolio.strategy_id;
    showView("validation");
    openPortfolioDialog("validation", portfolio);
  }));
}

function openPortfolioDialog(mode, portfolio = null) {
  const strategyId = portfolio?.strategy_id || state.selectedStrategies[mode] || state.selectedStrategies.validation || "strategy_1";
  const strategy = strategyById(strategyId);
  if (!strategySupportsPortfolio(strategy, mode)) {
    showToast(mode === "simulation" ? "该策略当前只允许历史验证。" : "该策略尚未提供组合运行适配器。", "error");
    return;
  }
  const adapter = strategy.backtest_adapter || {};
  const fixedSymbols = adapter.fixed_symbols || [];
  state.dialogMode = mode;
  state.editingPortfolioId = portfolio?.portfolio_id || "";
  $("dialogModeLabel").textContent = mode === "validation" ? "STRATEGY VALIDATION" : "PAPER OPERATIONS";
  $("dialogStrategyName").textContent = `${strategy.name} · v${strategy.version || "1.0.0"}`;
  $("runPortfolioButton").textContent = mode === "validation" ? "运行历史验证" : "启动模拟实测";
  const source = portfolio || (fixedSymbols.length ? {
    name: "SNDK盘后项目",
    initial_capital: adapter.default_capital || 1000,
    run_days: 30,
    max_concurrent_positions: 1,
    account_stop_pct: 20,
    strategy_parameters: {},
    projects: fixedSymbols.map((symbol, index) => ({
      project_id: `project_${index + 1}`,
      name: "SNDK",
      symbol,
      budget: adapter.default_budget || 1000,
      initial_stake: adapter.default_initial_stake || 500,
      leverage: adapter.default_leverage || 5,
      market: adapter.market || "equity_perpetual",
      enabled: true,
    })),
  } : state.portfolioTemplate || mockPortfolio());
  $("portfolioName").value = source.name || "核心项目组合";
  $("portfolioCapital").value = source.initial_capital || 5000;
  $("portfolioDays").value = source.run_days || 30;
  const count = Math.max(1, Math.min(12, source.projects?.length || 5));
  $("projectCount").value = String(count);
  $("projectCount").disabled = Boolean(fixedSymbols.length);
  $("maxConcurrent").value = Math.min(source.max_concurrent_positions || count, count);
  $("maxConcurrent").max = count;
  $("accountStop").value = source.account_stop_pct || 12;
  renderStrategyParameters(strategy, source.strategy_parameters || {});
  renderProjectRows(count, (source.projects || []).map(project => !portfolio && adapter.default_leverage ? {...project, leverage: adapter.default_leverage} : project), strategy);
  updateAllocation();
  $("portfolioDialog").showModal();
}

function renderStrategyParameters(strategy, values = {}) {
  const parameters = strategy?.parameters || [];
  const section = $("strategyParameterSection");
  section.classList.toggle("is-hidden", !parameters.length);
  $("strategyParameterFields").innerHTML = parameters.map((parameter) => {
    const value = values[parameter.key] ?? parameter.default;
    const common = `data-parameter-key="${escapeHtml(parameter.key)}" data-parameter-kind="${escapeHtml(parameter.kind)}"`;
    if (parameter.kind === "choice") {
      const options = (parameter.choices || []).map((choice) => `<option value="${escapeHtml(choice)}" ${choice === value ? "selected" : ""}>${escapeHtml(choice)}</option>`).join("");
      return `<label><span>${escapeHtml(parameter.label)}</span><select ${common}>${options}</select></label>`;
    }
    if (parameter.kind === "boolean") {
      return `<label><span>${escapeHtml(parameter.label)}</span><span class="parameter-boolean"><small>${value ? "启用" : "关闭"}</small><input type="checkbox" ${common} ${value ? "checked" : ""} /></span></label>`;
    }
    const type = parameter.kind === "integer" || parameter.kind === "number" ? "number" : "text";
    const constraints = `${parameter.minimum != null ? `min="${parameter.minimum}"` : ""} ${parameter.maximum != null ? `max="${parameter.maximum}"` : ""} ${parameter.step != null ? `step="${parameter.step}"` : ""}`;
    return `<label><span>${escapeHtml(parameter.label)}</span><input type="${type}" value="${escapeHtml(value)}" ${common} ${constraints} /></label>`;
  }).join("");
  $("strategyParameterFields").querySelectorAll("input[type='checkbox']").forEach((input) => input.addEventListener("change", () => {
    input.closest(".parameter-boolean").querySelector("small").textContent = input.checked ? "启用" : "关闭";
  }));
}

function collectStrategyParameters() {
  const values = {};
  $("strategyParameterFields").querySelectorAll("[data-parameter-key]").forEach((field) => {
    const kind = field.dataset.parameterKind;
    if (kind === "boolean") values[field.dataset.parameterKey] = field.checked;
    else if (kind === "integer") values[field.dataset.parameterKey] = Number.parseInt(field.value, 10);
    else if (kind === "number") values[field.dataset.parameterKey] = Number.parseFloat(field.value);
    else values[field.dataset.parameterKey] = field.value;
  });
  return values;
}

function renderProjectRows(count, existing = [], strategy = null) {
  const adapter = strategy?.backtest_adapter || {};
  const fixedSymbols = adapter.fixed_symbols || [];
  const defaults = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT", "LTCUSDT", "BCHUSDT"];
  const capital = Number($("portfolioCapital").value) || 5000;
  const equalBudget = Math.floor((capital / count) * 100) / 100;
  $("projectRows").innerHTML = Array.from({ length: count }, (_, index) => {
    const project = existing[index] || {};
    const symbol = project.symbol || fixedSymbols[index] || defaults[index] || state.symbols[index] || state.symbols[0];
    const availableSymbols = fixedSymbols.length ? fixedSymbols : [...new Set([...defaults, ...state.symbols, symbol])];
    const options = availableSymbols.map((item) => `<option value="${item}" ${item === symbol ? "selected" : ""}>${item}</option>`).join("");
    const market = project.market || adapter.market || "crypto_futures";
    const leverage = project.leverage || adapter.default_leverage || 20;
    const initialStake = project.initial_stake || adapter.default_initial_stake || 50;
    return `<div class="project-row" data-index="${index}" data-market="${escapeHtml(market)}">
      <div class="project-name"><span class="project-number">${String(index + 1).padStart(2, "0")}</span><input class="project-label" type="text" maxlength="40" value="${escapeHtml(project.name || symbol.replace("USDT", ""))}" /></div>
      <select class="project-symbol" ${fixedSymbols.length ? "disabled" : ""}>${options}</select>
      <div class="input-unit"><input class="project-budget" type="number" min="50" step="50" value="${project.budget || equalBudget}" /><em>U</em></div>
      <div class="input-unit"><input class="project-stake" type="number" min="5" step="5" value="${initialStake}" /><em>U</em></div>
      <div class="input-unit"><input class="project-leverage" type="number" min="1" max="${adapter.max_leverage || 125}" value="${leverage}" /><em>x</em></div>
    </div>`;
  }).join("");
  $("projectRows").querySelectorAll("input, select").forEach((element) => element.addEventListener("input", updateAllocation));
}

function projectRowsPayload() {
  return [...$("projectRows").querySelectorAll(".project-row")].map((row, index) => ({
    project_id: `project_${index + 1}`,
    name: row.querySelector(".project-label").value.trim() || `项目 ${index + 1}`,
    symbol: row.querySelector(".project-symbol").value,
    budget: Number(row.querySelector(".project-budget").value),
    initial_stake: Number(row.querySelector(".project-stake").value),
    leverage: Number(row.querySelector(".project-leverage").value),
    market: row.dataset.market || "crypto_futures",
    enabled: true,
    parameters: {},
  }));
}

function portfolioPayload() {
  const mode = state.dialogMode;
  const strategyId = state.selectedStrategies[mode] || state.selectedStrategies.validation || "strategy_1";
  return {
    portfolio_id: state.editingPortfolioId || `portfolio_${Date.now()}`,
    name: $("portfolioName").value.trim() || "我的投资组合",
    strategy_id: strategyId,
    initial_capital: Number($("portfolioCapital").value),
    run_days: Number($("portfolioDays").value),
    max_concurrent_positions: Number($("maxConcurrent").value),
    account_stop_pct: Number($("accountStop").value),
    strategy_parameters: collectStrategyParameters(),
    projects: projectRowsPayload(),
  };
}

function validatePortfolio(payload) {
  const total = payload.projects.reduce((sum, project) => sum + (Number(project.budget) || 0), 0);
  const symbols = payload.projects.map((project) => project.symbol);
  if (!payload.name) return "请输入组合名称。";
  if (payload.initial_capital < 100) return "组合本金不能低于100 USDT。";
  if (payload.run_days < 2 || payload.run_days > 365) return "运行时间必须在2至365天之间。";
  if (total > payload.initial_capital + .0001) return "项目预算之和超过组合本金。";
  if (new Set(symbols).size !== symbols.length) return "同一组合不能重复配置相同标的。";
  if (payload.projects.some((project) => project.initial_stake > project.budget)) return "首次投入不能超过项目预算。";
  if (payload.max_concurrent_positions < 1 || payload.max_concurrent_positions > payload.projects.length) return "最大并发仓位超出项目数量。";
  return "";
}

function updateAllocation() {
  const capital = Number($("portfolioCapital").value) || 0;
  const rows = projectRowsPayload();
  const allocated = rows.reduce((sum, project) => sum + (project.budget || 0), 0);
  const reserve = capital - allocated;
  $("capitalSummary").textContent = `${money(capital, 0)} U`;
  $("allocatedSummary").textContent = `${money(allocated, 0)} U`;
  $("reserveSummary").textContent = `${money(reserve, 0)} U`;
  $("reserveSummary").className = reserve < 0 ? "negative" : reserve > 0 ? "positive" : "";
  const ratio = capital > 0 ? Math.min(100, allocated / capital * 100) : 0;
  $("allocationBar").style.width = `${ratio}%`;
  $("allocationBar").style.background = allocated > capital ? "var(--danger)" : "var(--mint)";
  const error = validatePortfolio(portfolioPayload());
  $("portfolioError").textContent = error || `${rows.length}个项目，预算利用率${money(ratio, 1)}%。`;
  $("portfolioError").classList.toggle("error", Boolean(error));
  $("runPortfolioButton").disabled = Boolean(error);
  $("savePortfolioButton").disabled = Boolean(error);
}

async function savePortfolio(closeAfter = false) {
  const payload = portfolioPayload();
  const error = validatePortfolio(payload);
  if (error) return showToast(error, "error");
  const result = await callApi("save_portfolio", payload);
  if (!result.ok) return showToast(result.error || "保存失败", "error");
  const record = result.data || payload;
  state.editingPortfolioId = record.portfolio_id;
  state.portfolios = state.portfolios.filter((item) => item.portfolio_id !== record.portfolio_id);
  state.portfolios.push(record);
  renderPortfolios();
  $("portfolioCount").textContent = state.portfolios.length;
  showToast("项目组合已保存", "success");
  if (closeAfter) $("portfolioDialog").close();
}

async function runPortfolio() {
  const payload = portfolioPayload();
  const error = validatePortfolio(payload);
  if (error) return showToast(error, "error");
  const button = $("runPortfolioButton");
  const validation = state.dialogMode === "validation";
  setBusy(button, true, validation ? "正在启动…" : "正在启动…", validation ? "运行历史验证" : "启动模拟实测");
  const method = validation ? "start_portfolio_backtest" : "start_portfolio_dry_run";
  try {
    const result = await callApi(method, payload);
    if (!result.ok) {
      const message = result.error || "启动失败";
      $("portfolioError").textContent = message;
      $("portfolioError").classList.add("error");
      return showToast(message, "error");
    }
    state.freqtrade = result.data;
    await savePortfolio(false);
    $("portfolioDialog").close();
    if (validation) {
      if (result.data.status === "completed" && result.data.result) {
        state.lastCompletedFile = result.data.result.result_file || `preview-${Date.now()}`;
        renderBacktestResult(result.data.result);
      } else {
        $("validationSetup").classList.remove("is-hidden");
        $("backtestResults").classList.add("is-hidden");
      }
      showToast("组合历史验证已启动", "success");
    } else {
      showToast("组合模拟实测已启动", "success");
      renderDryRun(result.data.dry_run || {});
    }
  } finally {
    setBusy(button, false, "正在启动…", validation ? "运行历史验证" : "启动模拟实测");
  }
}

async function refreshFreqtradeStatus() {
  const result = await callApi("research_status");
  if (!result.ok) return;
  state.freqtrade = result.data;
  const available = Boolean(result.data.available);
  $("engineDot").classList.toggle("ready", available);
  $("engineLabel").textContent = available ? (result.data.running ? "运行中" : "就绪") : "不可用";
  renderDryRun(result.data.dry_run || {});
  const completed = result.data.status === "completed" && result.data.result;
  const file = result.data.result?.result_file || "";
  if (completed && file !== state.lastCompletedFile) {
    state.lastCompletedFile = file;
    renderBacktestResult(result.data.result);
    showView("validation");
    showToast("组合回测完成", "success");
  }
  if (result.data.status === "error" && result.data.last_error) {
    $("engineLabel").textContent = "错误";
  }
}

function renderDryRun(dryRun) {
  const running = Boolean(dryRun.running);
  $("dryRunLight").classList.toggle("running", running);
  $("dryRunStatus").textContent = dryRun.reason || (running ? "运行中" : "未启动");
  $("dryRunPortfolio").textContent = dryRun.portfolio?.name || "--";
  $("dryRunDeadline").textContent = dryRun.deadline ? new Date(dryRun.deadline).toLocaleString("zh-CN", { hour12: false }) : "--";
  $("stopDryRunButton").disabled = !running;
  $("dryRunLog").textContent = dryRun.logs?.length ? dryRun.logs.join("\n") : "暂无运行记录";
}

async function stopDryRun() {
  if (!window.confirm("确认停止组合模拟实测？模拟数据库中的持仓记录会保留，便于下次继续核对。")) return;
  const result = await callApi("stop_freqtrade_dry_run");
  if (!result.ok) return showToast(result.error || "停止失败", "error");
  renderDryRun(result.data.dry_run || {});
  showToast("模拟实测正在停止", "success");
}

function renderBacktestResult(result) {
  $("validationSetup").classList.add("is-hidden");
  $("backtestResults").classList.remove("is-hidden");
  $("resultName").textContent = result.portfolio?.name || "组合回测结果";
  $("resultScope").textContent = `${(result.symbols || [result.symbol]).join(" · ")} · ${result.days}天 · ${money(result.initial_capital, 0)} USDT`;
  const metrics = [
    ["总收益", signed(result.profit_pct, "%"), result.profit_pct],
    ["净利润", signed(result.profit_abs, " U"), result.profit_abs],
    ["最大回撤", `${money(result.max_drawdown_pct)}%`, -Math.abs(result.max_drawdown_pct)],
    ["胜率", `${money(result.win_rate_pct)}%`, 0],
    ["盈亏比", money(result.payoff_ratio, 3), result.payoff_ratio - 1],
    ["Profit Factor", money(result.profit_factor, 3), result.profit_factor - 1],
    ["交易次数", money(result.total_trades, 0), 0],
  ];
  $("metricRibbon").innerHTML = metrics.map(([label, value, polarity]) => `<div class="metric-cell"><span>${label}</span><strong class="${resultClass(polarity)}">${value}</strong></div>`).join("");
  $("directionStats").innerHTML = [
    ["多单", result.long || {}], ["空单", result.short || {}],
  ].map(([label, item]) => `<div class="direction-row"><header><span>${label}</span><strong class="${resultClass(item.profit_abs)}">${signed(item.profit_abs, " U")}</strong></header><footer><span>${item.trades || 0} 笔交易</span><span>${signed(item.profit_pct, "%")}</span></footer></div>`).join("");
  $("pairResults").innerHTML = (result.per_pair || []).map((item) => `<tr><td>${escapeHtml(item.symbol)}</td><td>${item.trades}</td><td>${money(item.win_rate_pct)}%</td><td class="${resultClass(item.profit_pct)}">${signed(item.profit_pct, "%")}</td><td class="${resultClass(item.profit_abs)}">${signed(item.profit_abs, " U")}</td><td>${money(item.profit_factor, 3)}</td><td>${money(item.max_drawdown_pct)}%</td></tr>`).join("") || `<tr><td colspan="7">暂无项目明细</td></tr>`;
  const funding = result.funding_pnl == null ? "" : ` · 资金费 ${signed(result.funding_pnl, " U")}`;
  const slippage = result.estimated_slippage == null ? "" : ` · 估算滑点 ${money(result.estimated_slippage)} U`;
  $("feeSummary").textContent = `手续费 ${money(result.estimated_fees)} USDT${funding}${slippage}`;
  $("exitReasons").innerHTML = (result.exit_reasons || []).map((item) => `<div class="exit-reason"><span>${escapeHtml(item.reason)} · ${item.trades}笔</span><strong class="${resultClass(item.profit_abs)}">${signed(item.profit_abs, " U")}</strong></div>`).join("");
  drawEquityCurve(result.equity_curve || [], result.initial_capital);
}

function drawEquityCurve(points, initialCapital) {
  const canvas = $("equityChart");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(600, Math.floor(rect.width * ratio));
  canvas.height = Math.floor(300 * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = canvas.width / ratio;
  const height = canvas.height / ratio;
  ctx.clearRect(0, 0, width, height);
  if (!points.length) {
    ctx.fillStyle = "#68736c";
    ctx.font = "11px sans-serif";
    ctx.fillText("暂无资金曲线", 20, 36);
    return;
  }
  const values = [Number(initialCapital), ...points.map((point) => Number(point.balance))];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = { left: 58, right: 18, top: 24, bottom: 34 };
  const range = Math.max(1, maximum - minimum);
  ctx.strokeStyle = "#dce2d6";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#68736c";
  ctx.font = "9px SFMono-Regular, monospace";
  for (let line = 0; line <= 4; line += 1) {
    const y = padding.top + (height - padding.top - padding.bottom) * line / 4;
    const value = maximum - range * line / 4;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    ctx.fillText(money(value, 0), 9, y + 3);
  }
  const chartPoints = values.map((value, index) => ({
    x: padding.left + (width - padding.left - padding.right) * index / Math.max(1, values.length - 1),
    y: padding.top + (maximum - value) / range * (height - padding.top - padding.bottom),
  }));
  ctx.beginPath();
  chartPoints.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.lineTo(chartPoints.at(-1).x, height - padding.bottom);
  ctx.lineTo(chartPoints[0].x, height - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = "rgba(100, 211, 170, .10)";
  ctx.fill();
  ctx.beginPath();
  chartPoints.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
  ctx.strokeStyle = "#3b7050";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function currentAgentConfig() {
  return state.agentStatus?.config || state.agentBootstrap?.config || mockAgentBootstrap().config;
}

function agentMarkets() {
  return state.agentBootstrap?.markets?.length ? state.agentBootstrap.markets : mockAgentBootstrap().markets;
}

function agentMarketForSymbol(symbol) {
  return agentMarkets().find((market) => market.items?.some((item) => item.symbol === symbol));
}

function renderAgentQuickSymbols(marketId, selectedSymbol = "") {
  const market = agentMarkets().find((item) => item.id === marketId) || agentMarkets()[0];
  const items = market?.items || [];
  $("agentQuickSymbol").innerHTML = items.map((item) => `<option value="${escapeHtml(item.symbol)}">${escapeHtml(item.label)} · ${escapeHtml(item.symbol)}</option>`).join("");
  $("agentQuickSymbol").value = items.some((item) => item.symbol === selectedSymbol) ? selectedSymbol : items[0]?.symbol || "BTCUSDT";
}

function renderAgentSettings() {
  const config = currentAgentConfig();
  const selectedSymbol = $("agentQuickSymbol").value || config.watchlist?.[0]?.symbol || "BTCUSDT";
  const selectedMarket = agentMarketForSymbol(selectedSymbol) || agentMarkets()[0];
  $("agentQuickMarket").innerHTML = agentMarkets().map((market) => `<option value="${escapeHtml(market.id)}">${escapeHtml(market.name)} · ${market.items?.length || 0}</option>`).join("");
  $("agentQuickMarket").value = selectedMarket?.id || "crypto_futures";
  renderAgentQuickSymbols($("agentQuickMarket").value, selectedSymbol);
  $("agentSymbolCatalog").innerHTML = agentMarkets().flatMap((market) => (market.items || []).map((item) => `<option value="${escapeHtml(item.symbol)}">${escapeHtml(market.name)} · ${escapeHtml(item.label)}</option>`)).join("");
  $("agentQuickTimeframe").value = config.watchlist?.[0]?.timeframe || "15m";
  fillAgentSettings(config);
}

function fillAgentSettings(config) {
  const provider = config.provider || "rules";
  const radio = document.querySelector(`input[name="agentProvider"][value="${provider}"]`);
  if (radio) radio.checked = true;
  $("agentModelInput").value = config.model || (provider === "openai" ? "gpt-5-mini" : "deepseek-chat");
  $("agentApiKey").value = "";
  $("agentApiKey").placeholder = config.api_key_configured ? `已配置 ${config.api_key_masked || ""}` : "仅当前进程";
  $("riskBalance").value = config.risk?.account_balance ?? 1000;
  $("riskPerTrade").value = config.risk?.risk_per_trade_pct ?? 1;
  $("riskLeverage").value = config.risk?.leverage ?? 3;
  $("riskMaxMargin").value = config.risk?.max_margin_pct ?? 20;
  $("riskConfidence").value = config.risk?.min_confidence ?? 60;
  $("riskReward").value = config.risk?.min_risk_reward ?? 1.5;
  $("riskMaxStop").value = config.risk?.max_stop_pct ?? 3;
  $("agentPollSeconds").value = config.poll_seconds ?? 30;
  $("agentPushEnabled").checked = config.push_enabled !== false;
  $("feishuWebhook").value = "";
  $("feishuWebhook").placeholder = config.feishu_configured ? `已配置 ${config.feishu_webhook_masked || ""}` : "https://open.feishu.cn/open-apis/bot/v2/hook/...";
  $("feishuSecret").value = "";
  $("feishuSecret").placeholder = config.feishu_secret_configured ? "签名密钥已配置" : "可选，建议启用";
  renderAgentWatchEditor(config.watchlist || []);
  renderAgentSkillSettings(config.skill_weights || {});
  syncAgentProviderFields();
}

function renderAgentWatchEditor(watchlist) {
  const list = watchlist.length ? watchlist : [{ symbol: "BTCUSDT", timeframe: "15m" }];
  $("agentWatchEditor").innerHTML = list.map((item, index) => `<div class="watch-edit-row" data-watch-index="${index}">
    <input class="watch-symbol" type="text" list="agentSymbolCatalog" value="${escapeHtml(item.symbol)}" maxlength="24" aria-label="监控标的" />
    <select class="watch-timeframe" aria-label="K线周期">${["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"].map((timeframe) => `<option ${timeframe === item.timeframe ? "selected" : ""}>${timeframe}</option>`).join("")}</select>
    <button class="watch-remove" type="button" aria-label="删除标的" title="删除标的">−</button>
  </div>`).join("");
  $("agentWatchEditor").querySelectorAll(".watch-remove").forEach((button) => button.addEventListener("click", () => {
    if ($("agentWatchEditor").children.length <= 1) return showToast("至少保留一个监控标的。", "error");
    button.closest(".watch-edit-row").remove();
  }));
}

function renderAgentSkillSettings(weights) {
  const skills = state.agentBootstrap?.skills || mockAgentBootstrap().skills;
  $("agentSkillSettings").innerHTML = skills.map((skill) => {
    const weight = Number(weights[skill.id] ?? skill.default_weight ?? 1);
    const enabled = weight > 0;
    const rangeValue = enabled ? weight : skill.default_weight || 1;
    return `<div class="skill-setting" data-skill-id="${escapeHtml(skill.id)}">
      <input class="skill-enabled" type="checkbox" ${enabled ? "checked" : ""} aria-label="启用${escapeHtml(skill.name)}" />
      <div><strong>${escapeHtml(skill.name)}</strong><small>${escapeHtml(skill.description)}</small></div>
      <div class="skill-weight"><input type="range" min="0.1" max="2" step="0.1" value="${rangeValue}" /><output>${Number(rangeValue).toFixed(1)}x</output></div>
    </div>`;
  }).join("");
  $("agentSkillSettings").querySelectorAll("input[type='range']").forEach((input) => input.addEventListener("input", () => {
    input.parentElement.querySelector("output").textContent = `${Number(input.value).toFixed(1)}x`;
  }));
}

function syncAgentProviderFields() {
  const provider = document.querySelector("input[name='agentProvider']:checked")?.value || "rules";
  const rules = provider === "rules";
  $("agentModelInput").disabled = rules;
  $("agentApiKey").disabled = rules;
  if (!rules && !$("agentModelInput").value.trim()) $("agentModelInput").value = provider === "openai" ? "gpt-5-mini" : "deepseek-chat";
}

function collectAgentPayload() {
  const watchlist = [...$("agentWatchEditor").querySelectorAll(".watch-edit-row")].map((row) => ({
    symbol: row.querySelector(".watch-symbol").value.trim().toUpperCase(),
    timeframe: row.querySelector(".watch-timeframe").value,
  })).filter((item) => item.symbol);
  const skillWeights = {};
  $("agentSkillSettings").querySelectorAll(".skill-setting").forEach((row) => {
    skillWeights[row.dataset.skillId] = row.querySelector(".skill-enabled").checked ? Number(row.querySelector("input[type='range']").value) : 0;
  });
  const provider = document.querySelector("input[name='agentProvider']:checked")?.value || "rules";
  const payload = {
    provider,
    model: $("agentModelInput").value.trim() || (provider === "openai" ? "gpt-5-mini" : "deepseek-chat"),
    poll_seconds: Number($("agentPollSeconds").value),
    watchlist,
    skill_weights: skillWeights,
    push_enabled: $("agentPushEnabled").checked,
    risk: {
      account_balance: Number($("riskBalance").value), risk_per_trade_pct: Number($("riskPerTrade").value),
      leverage: Number($("riskLeverage").value), max_margin_pct: Number($("riskMaxMargin").value),
      min_confidence: Number($("riskConfidence").value), min_risk_reward: Number($("riskReward").value),
      max_stop_pct: Number($("riskMaxStop").value), max_atr_pct: currentAgentConfig().risk?.max_atr_pct || 3.2,
    },
  };
  const apiKey = $("agentApiKey").value.trim();
  const webhook = $("feishuWebhook").value.trim();
  const secret = $("feishuSecret").value.trim();
  if (apiKey) payload.api_key = apiKey;
  if (webhook) payload.feishu_webhook = webhook;
  if (secret) payload.feishu_secret = secret;
  return payload;
}

async function saveAgentSettings(event) {
  event.preventDefault();
  const button = $("saveAgentSettings");
  setBusy(button, true, "保存中…", "保存设置");
  const result = await callApi("configure_agent", collectAgentPayload());
  setBusy(button, false, "保存中…", "保存设置");
  if (!result.ok) {
    $("agentSettingsError").textContent = result.error || "设置保存失败";
    $("agentSettingsError").classList.add("error");
    return;
  }
  state.agentStatus = result.data;
  $("agentSettingsDialog").close();
  renderAgentStatus(result.data);
  showToast("智能体设置已保存", "success");
}

async function testFeishu() {
  const button = $("testFeishuButton");
  setBusy(button, true, "发送中…", "发送测试消息");
  const result = await callApi("test_feishu", collectAgentPayload());
  setBusy(button, false, "发送中…", "发送测试消息");
  showToast(result.ok ? result.data?.message || "飞书测试成功" : result.error || "飞书测试失败", result.ok ? "success" : "error");
}

async function toggleAgentMonitor() {
  const running = Boolean(state.agentStatus?.running);
  const button = $("toggleAgentButton");
  setBusy(button, true, running ? "停止中…" : "启动中…", running ? "停止盯盘" : "启动盯盘");
  const result = running ? await callApi("stop_agent_monitor") : await callApi("start_agent_monitor", currentAgentConfig());
  setBusy(button, false, "", "");
  if (!result.ok) {
    showToast(result.error || "盯盘状态切换失败", "error");
    if (!running && /API Key/.test(result.error || "")) $("agentSettingsDialog").showModal();
    renderAgentStatus(state.agentStatus || { running: false, config: currentAgentConfig(), latest: [], history: [], logs: [] });
    return;
  }
  state.agentStatus = result.data;
  renderAgentStatus(result.data);
  showToast(running ? "智能盯盘已停止" : "智能盯盘已启动", "success");
}

async function analyzeAgentNow() {
  const button = $("analyzeNowButton");
  setBusy(button, true, "分析中…", "立即分析");
  const watchItem = { symbol: $("agentQuickSymbol").value, timeframe: $("agentQuickTimeframe").value };
  const result = await callApi("analyze_now", { watch_item: watchItem });
  setBusy(button, false, "分析中…", "立即分析");
  if (!result.ok) return showToast(result.error || "分析失败", "error");
  await refreshAgentStatus();
  showToast(`${watchItem.symbol} ${watchItem.timeframe} 分析完成`, "success");
}

async function refreshAgentStatus() {
  const result = await callApi("agent_status");
  if (!result.ok) return;
  state.agentStatus = result.data;
  renderAgentStatus(result.data);
}

function renderAgentStatus(status) {
  const config = status.config || currentAgentConfig();
  const running = Boolean(status.running);
  $("agentRunLight").classList.toggle("running", running);
  $("agentRunLabel").textContent = running ? "持续监控中" : "未启动";
  $("toggleAgentButton").textContent = running ? "停止盯盘" : "启动盯盘";
  $("toggleAgentButton").classList.toggle("danger", running);
  $("toggleAgentButton").classList.toggle("primary", !running);
  $("agentWatchCount").textContent = `${config.watchlist?.length || 0} 个`;
  $("agentPushState").textContent = config.feishu_configured ? "飞书已配置" : "飞书未配置";
  $("agentMeta").innerHTML = [
    ["判断引擎", config.provider === "rules" ? "规则共识" : `${config.provider === "deepseek" ? "DeepSeek" : "OpenAI"} · ${config.model}`],
    ["风险阈值", `${money(config.risk?.min_confidence, 0)}%`],
    ["最小盈亏比", money(config.risk?.min_risk_reward, 1)],
    ["单笔风险", `${money(config.risk?.risk_per_trade_pct, 1)}%`],
  ].map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  renderAgentWatchList(config.watchlist || [], status.latest || []);
  renderAgentHistory(status.history || []);
  $("agentLog").textContent = status.logs?.length ? status.logs.slice(-30).join("\n") : "暂无运行记录";
  $("agentLog").scrollTop = $("agentLog").scrollHeight;
  $("agentSignalCount").textContent = status.history?.length || 0;
  const symbol = $("agentQuickSymbol").value;
  const timeframe = $("agentQuickTimeframe").value;
  const latest = (status.latest || []).find((item) => item.snapshot?.symbol === symbol && item.snapshot?.timeframe === timeframe);
  renderAgentRecord(latest);
}

function renderAgentWatchList(watchlist, latest) {
  const latestMap = new Map(latest.map((item) => [`${item.snapshot?.symbol}:${item.snapshot?.timeframe}`, item]));
  $("agentWatchList").innerHTML = watchlist.map((item) => {
    const record = latestMap.get(`${item.symbol}:${item.timeframe}`);
    const action = record?.signal?.action || "WAIT";
    return `<button class="watch-row" type="button" data-symbol="${escapeHtml(item.symbol)}" data-timeframe="${escapeHtml(item.timeframe)}"><div><strong>${escapeHtml(item.symbol)}</strong><small>${record ? `${money(record.snapshot.price)} · ${record.signal.confidence}%` : "等待首轮分析"}</small></div><span>${escapeHtml(item.timeframe)} · ${escapeHtml(action)}</span></button>`;
  }).join("");
  $("agentWatchList").querySelectorAll(".watch-row").forEach((button) => button.addEventListener("click", () => {
    const market = agentMarketForSymbol(button.dataset.symbol);
    if (market) $("agentQuickMarket").value = market.id;
    renderAgentQuickSymbols($("agentQuickMarket").value, button.dataset.symbol);
    $("agentQuickSymbol").value = button.dataset.symbol;
    $("agentQuickTimeframe").value = button.dataset.timeframe;
    const record = latestMap.get(`${button.dataset.symbol}:${button.dataset.timeframe}`);
    renderAgentRecord(record);
  }));
}

function renderAgentRecord(record) {
  if (!record) {
    $("agentMarketScope").textContent = `${$("agentQuickSymbol").value || "BTCUSDT"} · ${$("agentQuickTimeframe").value || "15m"}`;
    $("agentPrice").textContent = "--";
    $("agentChange").textContent = "--";
    $("agentChange").className = "";
    $("agentTrend").textContent = "趋势 --";
    $("agentRegime").textContent = "环境 --";
    $("agentCandleTime").textContent = "等待行情";
    $("agentIndicators").innerHTML = ["EMA 20", "EMA 60", "RSI 14", "ATR", "量比"].map((label) => `<div><span>${label}</span><strong>--</strong></div>`).join("");
    $("agentModelLabel").textContent = "等待分析";
    $("agentVerdict").className = "signal-verdict wait";
    $("agentVerdict").innerHTML = `<small>方向</small><strong>WAIT</strong><span>等待当前标的分析</span>`;
    $("agentLevels").innerHTML = [["入场区间", "--"], ["止损", "--"], ["止盈", "--"], ["盈亏比", "--"], ["建议保证金", "--"]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
    $("agentReason").textContent = "点击“立即分析”生成当前标的策略。";
    $("agentInvalidation").textContent = "--";
    $("agentSkillAssessments").innerHTML = `<div class="empty-state">等待当前标的分析</div>`;
    drawAgentKlines([]);
    return;
  }
  const snapshot = record.snapshot;
  const signal = record.signal;
  $("agentMarketScope").textContent = `${snapshot.symbol} · ${snapshot.timeframe}`;
  $("agentPrice").textContent = money(snapshot.price);
  $("agentChange").textContent = signed(snapshot.change_24h_pct, "%");
  $("agentChange").className = resultClass(snapshot.change_24h_pct);
  $("agentTrend").textContent = `趋势 ${({ UP: "上行", DOWN: "下行", MIXED: "混合" })[snapshot.trend] || snapshot.trend}`;
  $("agentRegime").textContent = `环境 ${({ TRENDING: "趋势", RANGING: "震荡", HIGH_VOLATILITY: "高波动" })[snapshot.regime] || snapshot.regime}`;
  $("agentCandleTime").textContent = new Date(snapshot.candle_time).toLocaleString("zh-CN", { hour12: false });
  const indicators = [["EMA 20", snapshot.ema20], ["EMA 60", snapshot.ema60], ["RSI 14", snapshot.rsi14], ["ATR", `${money(snapshot.atr14)} · ${money(snapshot.atr_pct)}%`], ["量比", `${money(snapshot.volume_ratio)}x`]];
  $("agentIndicators").innerHTML = indicators.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${typeof value === "number" ? money(value) : escapeHtml(value)}</strong></div>`).join("");
  $("agentModelLabel").textContent = `${record.model} · ${signal.risk_status}`;
  const verdict = $("agentVerdict");
  verdict.className = `signal-verdict ${signal.action.toLowerCase()}`;
  verdict.innerHTML = `<small>方向</small><strong>${escapeHtml(signal.action)}</strong><span>${signal.confidence}% 置信度</span>`;
  const entry = signal.entry_low != null ? `${money(signal.entry_low)} - ${money(signal.entry_high)}` : "--";
  $("agentLevels").innerHTML = [
    ["入场区间", entry], ["止损", signal.stop_loss == null ? "--" : money(signal.stop_loss)],
    ["止盈", signal.take_profit == null ? "--" : money(signal.take_profit)], ["盈亏比", signal.risk_reward == null ? "--" : `1 : ${money(signal.risk_reward)}`],
    ["建议保证金", signal.estimated_margin == null ? "--" : `${money(signal.estimated_margin)} U`],
  ].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("");
  $("agentReason").textContent = signal.reason || "暂无判断依据。";
  $("agentInvalidation").textContent = signal.invalid_if || (signal.validation_notes || []).join("；") || "--";
  $("agentSkillAssessments").innerHTML = record.assessments?.length ? record.assessments.map((item) => `<article class="skill-assessment"><div><h5>${escapeHtml(item.name)}</h5><p>${escapeHtml((item.evidence || []).join("；"))}</p></div><div class="skill-score ${item.bias.toLowerCase()}"><strong>${item.score > 0 ? "+" : ""}${item.score}</strong><span>${escapeHtml(item.bias)}</span></div></article>`).join("") : `<div class="empty-state">暂无 Skill 证据</div>`;
  drawAgentKlines(record.candles || []);
}

function renderAgentHistory(history) {
  if (!history.length) {
    $("agentHistoryRows").innerHTML = `<tr><td colspan="8">暂无信号</td></tr>`;
    return;
  }
  $("agentHistoryRows").innerHTML = history.slice(0, 50).map((record) => {
    const signal = record.signal || {};
    const snapshot = record.snapshot || {};
    return `<tr><td>${escapeHtml(new Date(record.created_at).toLocaleString("zh-CN", { hour12: false }))}</td><td>${escapeHtml(snapshot.symbol)}</td><td>${escapeHtml(snapshot.timeframe)}</td><td class="direction-${String(signal.action || "WAIT").toLowerCase()}">${escapeHtml(signal.action || "WAIT")}</td><td>${money(signal.confidence, 0)}%</td><td>${escapeHtml(signal.risk_status || "--")}</td><td>${escapeHtml(record.source || "--")}</td><td>${record.push?.sent ? "已送达" : "--"}</td></tr>`;
  }).join("");
}

function drawAgentKlines(candles) {
  const canvas = $("agentKlineChart");
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.floor(rect.width || 800));
  const height = Math.max(240, Math.floor(rect.height || 330));
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fffefa";
  ctx.fillRect(0, 0, width, height);
  if (!candles.length) {
    ctx.fillStyle = "#68736c";
    ctx.font = "11px sans-serif";
    ctx.fillText("等待已收盘 K 线", 18, 28);
    return;
  }
  const padding = { top: 18, right: 68, bottom: 26, left: 16 };
  const high = Math.max(...candles.map((item) => Number(item.high)));
  const low = Math.min(...candles.map((item) => Number(item.low)));
  const range = Math.max(high - low, 1e-9);
  const y = (value) => padding.top + (high - value) / range * (height - padding.top - padding.bottom);
  ctx.strokeStyle = "#dce2d6";
  ctx.lineWidth = 1;
  ctx.font = "9px SFMono-Regular, monospace";
  ctx.fillStyle = "#68736c";
  for (let index = 0; index <= 4; index += 1) {
    const py = padding.top + (height - padding.top - padding.bottom) * index / 4;
    ctx.beginPath(); ctx.moveTo(padding.left, py); ctx.lineTo(width - padding.right, py); ctx.stroke();
    ctx.fillText(money(high - range * index / 4), width - padding.right + 8, py + 3);
  }
  const plotWidth = width - padding.left - padding.right;
  const step = plotWidth / candles.length;
  const bodyWidth = Math.max(2, Math.min(8, step * .58));
  candles.forEach((item, index) => {
    const center = padding.left + step * index + step / 2;
    const open = Number(item.open), close = Number(item.close);
    const color = close >= open ? "#3b7050" : "#b65647";
    ctx.strokeStyle = color;
    ctx.beginPath(); ctx.moveTo(center, y(Number(item.high))); ctx.lineTo(center, y(Number(item.low))); ctx.stroke();
    ctx.fillStyle = color;
    const top = y(Math.max(open, close));
    const bodyHeight = Math.max(1.5, Math.abs(y(open) - y(close)));
    ctx.fillRect(center - bodyWidth / 2, top, bodyWidth, bodyHeight);
  });
}

async function connectFromEntry(event) {
  event.preventDefault();
  const apiKey = $("entryApiKey").value.trim();
  const apiSecret = $("entryApiSecret").value.trim();
  if (!apiKey || !apiSecret) return showToast("请输入Demo API Key和Secret，或选择跳过登录。", "error");
  const button = $("entryLoginButton");
  setBusy(button, true, "正在验证…", "连接并进入");
  const result = await callApi("connect", { api_key: apiKey, api_secret: apiSecret, environment: "demo" });
  setBusy(button, false, "正在验证…", "连接并进入");
  if (!result.ok) return showToast(result.error || "连接失败", "error");
  state.connected = true;
  state.environment = "demo";
  state.maskedKey = result.data.masked_key || "已连接";
  $("entryApiSecret").value = "";
  renderConnection();
  enterApplication();
}

async function connectLive(event) {
  event.preventDefault();
  const apiKey = $("liveApiKey").value.trim();
  const apiSecret = $("liveApiSecret").value.trim();
  if (!apiKey || !apiSecret) return showToast("请输入真实网API Key和Secret。", "error");
  if (state.connected) await callApi("disconnect");
  const result = await callApi("connect", { api_key: apiKey, api_secret: apiSecret, environment: "live" });
  $("liveApiSecret").value = "";
  if (!result.ok) return showToast(result.error || "真实账户连接失败", "error");
  state.connected = true;
  state.environment = "live";
  state.maskedKey = result.data.masked_key || "已连接";
  renderConnection();
  renderAccount(result.data.account || {});
  $("liveConnectionLabel").textContent = `已连接 · ${state.maskedKey}`;
  showToast("真实账户已只读连接，自动执行仍锁定", "success");
}

function renderAccount(account) {
  const values = [
    ["钱包余额", `${money(account.wallet_balance)} USDT`, account.wallet_balance],
    ["可用余额", `${money(account.available_balance)} USDT`, 0],
    ["未实现盈亏", `${signed(account.unrealized_pnl, " USDT")}`, account.unrealized_pnl],
    ["保证金占用", `${money(account.margin_usage_pct)}%`, 0],
  ];
  $("liveMetrics").innerHTML = values.map(([label, value, polarity]) => `<div><span>${label}</span><strong class="${resultClass(polarity)}">${value}</strong></div>`).join("");
}

async function returnToEntry() {
  if (state.connected) {
    const result = await callApi("disconnect");
    if (!result.ok) return showToast(result.error || "断开失败", "error");
  }
  state.connected = false;
  state.maskedKey = "";
  state.environment = "demo";
  renderConnection();
  showEntry();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function bindEvents() {
  bindWorkspaceEvents();
  $("loginForm").addEventListener("submit", connectFromEntry);
  $("skipLoginButton").addEventListener("click", enterApplication);
  $("exitAccountButton").addEventListener("click", returnToEntry);
  $("refreshDailyStrategy").addEventListener("click", () => loadDailyStrategy(true));
  $("liveConnectForm").addEventListener("submit", connectLive);
  $("agentSettingsButton").addEventListener("click", () => {
    fillAgentSettings(currentAgentConfig());
    $("agentSettingsError").textContent = "设置保存后可立即运行。";
    $("agentSettingsError").classList.remove("error");
    $("agentSettingsDialog").showModal();
  });
  $("closeAgentSettings").addEventListener("click", () => $("agentSettingsDialog").close());
  $("agentSettingsForm").addEventListener("submit", saveAgentSettings);
  $("testFeishuButton").addEventListener("click", testFeishu);
  $("toggleAgentButton").addEventListener("click", toggleAgentMonitor);
  $("analyzeNowButton").addEventListener("click", analyzeAgentNow);
  $("agentProviderSegments").addEventListener("change", (event) => {
    if (event.target.name !== "agentProvider") return;
    $("agentModelInput").value = event.target.value === "openai" ? "gpt-5-mini" : event.target.value === "deepseek" ? "deepseek-chat" : $("agentModelInput").value;
    syncAgentProviderFields();
  });
  $("addWatchItem").addEventListener("click", () => {
    const rows = [...$("agentWatchEditor").querySelectorAll(".watch-edit-row")].map((row) => ({ symbol: row.querySelector(".watch-symbol").value, timeframe: row.querySelector(".watch-timeframe").value }));
    if (rows.length >= 12) return showToast("最多监控 12 个标的。", "error");
    renderAgentWatchEditor([...rows, { symbol: "ETHUSDT", timeframe: "15m" }]);
  });
  $("agentQuickMarket").addEventListener("change", () => {
    renderAgentQuickSymbols($("agentQuickMarket").value);
    const record = state.agentStatus?.latest?.find((item) => item.snapshot?.symbol === $("agentQuickSymbol").value && item.snapshot?.timeframe === $("agentQuickTimeframe").value);
    renderAgentRecord(record);
  });
  ["agentQuickSymbol", "agentQuickTimeframe"].forEach((id) => $(id).addEventListener("change", () => {
    const record = state.agentStatus?.latest?.find((item) => item.snapshot?.symbol === $("agentQuickSymbol").value && item.snapshot?.timeframe === $("agentQuickTimeframe").value);
    renderAgentRecord(record);
  }));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.view)));
  document.querySelectorAll("[data-open-view]").forEach((button) => button.addEventListener("click", () => showView(button.dataset.openView)));
  $("configureSimulation").addEventListener("click", () => openPortfolioDialog("simulation"));
  $("configureValidation").addEventListener("click", () => openPortfolioDialog("validation"));
  $("newPortfolioTop").addEventListener("click", () => {
    if (!state.selectedStrategies.validation) {
      const first = state.strategies.find((strategy) => strategySupportsPortfolio(strategy, "validation"));
      if (first) state.selectedStrategies.validation = first.id;
    }
    openPortfolioDialog("validation");
  });
  $("newValidationButton").addEventListener("click", () => {
    $("backtestResults").classList.add("is-hidden");
    $("validationSetup").classList.remove("is-hidden");
  });
  $("closePortfolioDialog").addEventListener("click", () => $("portfolioDialog").close());
  $("projectCount").addEventListener("change", () => {
    const count = Math.max(1, Math.min(12, Number($("projectCount").value) || 1));
    $("projectCount").value = count;
    $("maxConcurrent").max = count;
    $("maxConcurrent").value = Math.min(Number($("maxConcurrent").value), count);
    const mode = state.dialogMode;
    const strategy = strategyById(state.selectedStrategies[mode] || state.selectedStrategies.validation || "strategy_1");
    renderProjectRows(count, [], strategy);
    updateAllocation();
  });
  $("portfolioCapital").addEventListener("input", updateAllocation);
  $("portfolioDays").addEventListener("input", updateAllocation);
  $("maxConcurrent").addEventListener("input", updateAllocation);
  $("accountStop").addEventListener("input", updateAllocation);
  $("portfolioName").addEventListener("input", updateAllocation);
  $("savePortfolioButton").addEventListener("click", () => savePortfolio(false));
  $("portfolioForm").addEventListener("submit", (event) => { event.preventDefault(); runPortfolio(); });
  $("stopDryRunButton").addEventListener("click", stopDryRun);
  $("stockMarketButton").addEventListener("click", () => showToast("SNDK正股日线信号与Binance股票永续历史验证已接入；实时模拟和实盘仍锁定。", "success"));
  $("openStrategyFolder").addEventListener("click", async () => {
    const result = await callApi("open_strategy_folder");
    if (!result.ok) showToast(result.error || "无法打开策略目录", "error");
  });
  window.addEventListener("resize", () => {
    const result = state.freqtrade?.result;
    if (result && !$("backtestResults").classList.contains("is-hidden")) drawEquityCurve(result.equity_curve || [], result.initial_capital);
    const agentRecord = state.agentStatus?.latest?.find((item) => item.snapshot?.symbol === $("agentQuickSymbol").value && item.snapshot?.timeframe === $("agentQuickTimeframe").value);
    if (agentRecord) drawAgentKlines(agentRecord.candles || []);
  });
}

function start() {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
  else initialize();
}

window.addEventListener("pywebviewready", initialize, { once: true });
start();
