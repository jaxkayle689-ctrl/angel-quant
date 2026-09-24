import { useEffect, useState } from 'react'
import { call, errorMessage } from '../lib/bridge'
import { ContractPicker } from './ContractPicker'
import type { ContractCatalog } from './ContractPicker'

type Config = {
 provider: string; model: string; strategy_mode: string; poll_seconds: number; push_enabled: boolean;
 api_key_configured: boolean; feishu_configured: boolean;
 watchlist: {symbol: string; timeframe: string}[]; risk: Record<string, number>;
}
type Evidence = {id: string; text: string; timestamp: string; url: string}
type SignalRecord = {id: string; created_at: string; strategy_mode?: string; strategy_name?: string; source: string; model: string; model_error: string;
 snapshot: {symbol: string; timeframe: string}; signal: {action: string; confidence: number; reason: string; invalid_if: string; entry_low: number | null; entry_high: number | null; stop_loss: number | null; take_profit: number | null; risk_status: string};
 push: {sent: boolean; message: string}; context?: {evidence?: Evidence[]; structure?: {processed_count: number; fractals: unknown[]; confirmed_strokes: unknown[]; scope: string}; liquidity?: {sell_side_sweep: boolean; buy_side_sweep: boolean; definition: string}}}
type Status = {running: boolean; config: Config; history: SignalRecord[]; logs: string[]}
const names = {comprehensive: '综合策略', chanlun: '缠论体系'}
const periods = ['1m','3m','5m','15m','30m','1h','2h','4h','6h','12h','1d']
const riskNames: Record<string, string> = {account_balance:'计算用账户余额（USDT）', risk_per_trade_pct:'单笔风险 %', leverage:'计算用杠杆', max_margin_pct:'最大保证金占比 %', min_confidence:'最低模型评分', min_risk_reward:'最低盈亏比', max_stop_pct:'最大止损距离 %', max_atr_pct:'最大 ATR %'}

export function AgentWorkbench({settingsOnly = false}: {settingsOnly?: boolean}) {
 const [status, setStatus] = useState<Status>(), [config, setConfig] = useState<Config>()
 const [key, setKey] = useState(''), [webhook, setWebhook] = useState(''), [secret, setSecret] = useState('')
 const [busy, setBusy] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
 const [result, setResult] = useState<SignalRecord>(), [filter, setFilter] = useState('all')
 const [catalog, setCatalog] = useState<ContractCatalog>(), [catalogError, setCatalogError] = useState(''), [catalogBusy, setCatalogBusy] = useState(false)
 const [previewIndex, setPreviewIndex] = useState(0), [todayOnly, setTodayOnly] = useState(true)
 async function loadCatalog() {
   setCatalogBusy(true); setCatalogError('')
   try {setCatalog(await call<ContractCatalog>('agent_contract_catalog', {refresh:true}))}
   catch(e) {setCatalog(undefined); setCatalogError(errorMessage(e))}
   finally {setCatalogBusy(false)}
 }
 useEffect(() => {if (!settingsOnly) void loadCatalog()}, [settingsOnly])
 useEffect(() => {
   let alive = true
   const refresh = async () => { try { const next = await call<Status>('agent_status'); if (alive) {setStatus(next); setConfig(old => old || next.config)} } catch(e) {if (alive) setError(errorMessage(e))} }
   void refresh(); const timer = setInterval(() => void refresh(), 10000)
   return () => {alive = false; clearInterval(timer)}
 }, [])
 const patch = (value: Partial<Config>) => setConfig(old => old ? {...old, ...value} : old)
 const payload = () => ({...(settingsOnly ? {provider:config?.provider,model:config?.model} : config), ...(key.trim() ? {api_key:key.trim()} : {}), ...(webhook.trim() ? {feishu_webhook:webhook.trim()} : {}), ...(secret.trim() ? {feishu_secret:secret.trim()} : {})})
 async function run(action: string) {
   setBusy(action); setError(''); setMessage('')
   try {
     if(action === 'test') {
       const data = await call<{message: string}>('test_agent_model', payload()); setMessage(data.message)
     } else if(action === 'analyze') {
       const data = await call<SignalRecord>('analyze_now', {...payload(), watch_item:config?.watchlist[previewIndex]}); setResult(data); setMessage('分析完成。手动预览不发送飞书。')
     } else {
       const method = action === 'start' ? 'start_agent_monitor' : action === 'stop' ? 'stop_agent_monitor' : 'configure_agent'
       await (action === 'stop' ? call(method) : call(method, action === 'clear' ? {...payload(), api_key:''} : payload()))
       setMessage(action === 'start' ? '策略 Agent 已启动' : action === 'stop' ? '已停止策略推送' : action === 'clear' ? 'API Key 已清除' : '配置已保存；密钥仅保存在本次应用进程中')
     }
     setKey(''); setWebhook(''); setSecret('')
     const next = await call<Status>('agent_status'); setStatus(next); setConfig(next.config)
   } catch(e) {setError(errorMessage(e))} finally {setBusy('')}
 }
 if (!config) return <section className="empty"><p>{error || '正在读取模型与策略配置…'}</p></section>
 const disabled = !!busy || !!status?.running
 const available = new Set(catalog?.groups.flatMap(g=>g.items.map(i=>i.symbol)) || [])
 const contractsValid = !!catalog?.verified && !catalogBusy && config.watchlist.every(w=>available.has(w.symbol))
 const history = (status?.history || []).filter(r => (filter === 'all' || (r.strategy_mode || 'comprehensive') === filter) && (!todayOnly || new Date(r.created_at).toDateString() === new Date().toDateString()))
 const selected = result || history[0]
 return <section className="agent-workbench">
 <div className="section-head"><div><h2>{settingsOnly ? '模型 API 接入' : '当日策略 Agent'}</h2><small>{status?.running ? '策略推送运行中 · 停止后可修改配置' : '已停止 · 可先预览策略再启动推送'}</small></div>{status?.running && <button disabled={!!busy} onClick={() => void run('stop')}>停止策略推送</button>}</div>
 {!settingsOnly && <div className="daily-agent-banner"><div><strong>Binance U 本位 · USDT 永续</strong><p>选择合约 → 综合 / 缠论分析 → 硬风控 → 飞书策略推送</p></div><span>{config.watchlist.length} 个盯盘项 · {history.length} 条{todayOnly ? '今日' : ''}记录</span></div>}
 <article className="agent-config"><div className="section-head"><h3>模型连接</h3><span className="badge">{status?.config.api_key_configured ? '已配置密钥 · 未代表连接测试成功' : '待输入 API Key'}</span></div>
 <div className="agent-form-grid">
 <label>模型提供方<select disabled={disabled} value={config.provider} onChange={e => {setKey(''); patch({provider:e.target.value, model:e.target.value === 'deepseek' ? 'deepseek-chat' : e.target.value === 'openai' ? 'gpt-5-mini' : ''})}}><option value="rules">未接入模型（不能生成策略）</option><option value="deepseek">DeepSeek</option><option value="openai">OpenAI</option></select></label>
 <label>模型名称<input disabled={disabled || config.provider === 'rules'} value={config.model} onChange={e => patch({model:e.target.value})} placeholder="填写账户可用的模型 ID" /></label>
 <label className="agent-wide">API Key<input type="password" autoComplete="new-password" disabled={disabled || config.provider === 'rules'} value={key} onChange={e => setKey(e.target.value)} placeholder={status?.config.api_key_configured ? '已配置；留空保留，切换提供方需重新输入' : '在这里输入密钥，界面不会回显已保存值'} /></label>
 </div><p className="muted">密钥只保留在后端内存，不写入配置文件；重启应用后需重新输入。接口使用提供方官方地址。</p>
 <div className="actions"><button className="primary" disabled={disabled} onClick={() => void run('save')}>保存配置</button><button disabled={disabled || config.provider === 'rules'} onClick={() => void run('test')}>{busy === 'test' ? '测试中…' : '测试模型连接（一次 API 调用）'}</button><button disabled={disabled} onClick={() => void run('clear')}>清除密钥</button></div></article>
 {!settingsOnly && <>
 <div className="agent-strategies" role="group" aria-label="策略体系">{Object.entries(names).map(([id,name]) => <button disabled={disabled} key={id} aria-pressed={config.strategy_mode === id} className={config.strategy_mode === id ? 'selected' : ''} onClick={() => {patch({strategy_mode:id}); setResult(undefined)}}><small>{id === 'comprehensive' ? '01 / 多因素共识' : '02 / 视频 RAG 辅助'}</small><h3>{name}</h3><p>{id === 'comprehensive' ? '保留趋势、突破和极值回归；模型同时读取前高低点扫荡证据。' : '合并 K 线、严格分型与笔结构，结合视频原文独立分析，并展示引用。'}</p></button>)}</div>
 {config.strategy_mode === 'chanlun' && <p className="agent-notice">缠论模式需要模型 API。RAG 提供理论依据，行情结构由本地计算；目前本地确认到严格笔，模型的线段、中枢与背驰解释不会冒充 TradingView 已确认的一二三类点。证据不足则观望。</p>}
 <article className="agent-config"><div className="section-head"><h3>Binance 合约与推送计划</h3><button disabled={catalogBusy || disabled} onClick={()=>void loadCatalog()}>{catalogBusy ? '正在核验目录…' : '刷新合约目录'}</button></div>
 <p className="muted">{catalog ? '已核验 ' + catalog.count + ' 个可交易 USDT 永续合约 · Binance 实盘公开行情（无需交易账户密钥）' : '正在读取交易所真实合约目录'}</p>
 {catalogError && <p className="error" role="alert">{catalogError}</p>}
 <div className="agent-watchlist">{config.watchlist.map((item,i) => <div className="contract-row" key={i}><ContractPicker groups={catalog?.groups || []} value={item.symbol} index={i+1} disabled={disabled || catalogBusy || !catalog} change={symbol=>patch({watchlist:config.watchlist.map((w,j)=>j===i?{...w,symbol}:w)})}/><label>周期 {i+1}<select disabled={disabled} value={item.timeframe} onChange={e => patch({watchlist:config.watchlist.map((w,j) => j===i ? {...w,timeframe:e.target.value} : w)})}>{periods.map(p => <option key={p}>{p}</option>)}</select></label><button disabled={disabled || config.watchlist.length===1} onClick={() => {patch({watchlist:config.watchlist.filter((_,j) => i!==j)});setPreviewIndex(0)}}>移除</button></div>)}</div>
 <button disabled={disabled || !contractsValid || config.watchlist.length>=12 || ![...available].some(s=>!config.watchlist.some(w=>w.symbol===s))} onClick={() => {const symbol=[...available].find(s=>!config.watchlist.some(w=>w.symbol===s));if(symbol)patch({watchlist:[...config.watchlist,{symbol,timeframe:'15m'}]})}}>添加合约</button>
 {!catalogBusy && catalog && !contractsValid && <p className="error">列表中有未核验的合约，请从交易所目录重新选择后分析。</p>}
 <div className="agent-form-grid"><label>检查间隔（秒）<input disabled={disabled} type="number" min="10" max="3600" value={config.poll_seconds} onChange={e=>patch({poll_seconds:Number(e.target.value)})}/></label>{Object.entries(riskNames).map(([id,name]) => <label key={id}>{name}<input disabled={disabled} type="number" step="any" value={config.risk[id]} onChange={e=>patch({risk:{...config.risk,[id]:Number(e.target.value)}})}/></label>)}</div>
 <details><summary>飞书推送设置 · {status?.config.feishu_configured ? '通道已配置' : '尚未配置'}</summary><label className="agent-check"><input disabled={disabled} type="checkbox" checked={config.push_enabled} onChange={e=>patch({push_enabled:e.target.checked})}/>自动盯盘时推送通过风控的方向信号</label><label>机器人 Webhook<input disabled={disabled} type="password" autoComplete="new-password" value={webhook} onChange={e=>setWebhook(e.target.value)} placeholder="留空保留现有值"/></label><label>签名密钥<input disabled={disabled} type="password" autoComplete="new-password" value={secret} onChange={e=>setSecret(e.target.value)} placeholder="如机器人启用签名，请填写"/></label></details>
 <p className="muted">每根新收盘 K 分析一次；推送运行时轮流分析全部盯盘合约。结果为策略建议，不会自动下单。</p><label>预览合约<select disabled={disabled} value={previewIndex} onChange={e=>setPreviewIndex(Number(e.target.value))}>{config.watchlist.map((w,i)=><option key={i} value={i}>{w.symbol} · {w.timeframe}</option>)}</select></label><div className="actions"><button disabled={disabled || !contractsValid} onClick={() => void run('analyze')}>{busy === 'analyze' ? '分析中…' : '预览策略（不推送）'}</button><button className="primary" disabled={disabled || !contractsValid || (config.strategy_mode==='chanlun' && config.provider==='rules')} onClick={() => void run('start')}>保存并启动策略推送</button></div></article>
 <div className="section-head"><h3>当日策略与推送记录</h3><label className="agent-check"><input type="checkbox" checked={todayOnly} onChange={e=>{setTodayOnly(e.target.checked);setResult(undefined)}}/>仅看今天</label><label>筛选体系<select value={filter} onChange={e=>{setFilter(e.target.value);setResult(undefined)}}><option value="all">全部体系</option><option value="comprehensive">综合策略</option><option value="chanlun">缠论体系</option></select></label></div>
 <div className="agent-results"><div>{history.length ? history.map(r=><button className="agent-history" key={r.id} onClick={()=>setResult(r)}><b>{r.strategy_name || '综合策略'} · {r.snapshot.symbol}</b><span>{r.signal.action} · {r.source} · {new Date(r.created_at).toLocaleString()}</span></button>) : <p className="muted">暂无该体系分析记录</p>}</div>{selected && <article className="agent-config"><div className="section-head"><h3>{selected.strategy_name || '综合策略'} · {selected.snapshot.symbol}</h3><span className="badge">{selected.signal.action}</span></div><p>{selected.source} / {selected.model} · 模型评分 {selected.signal.confidence}（非胜率） · 风控 {selected.signal.risk_status}</p>{selected.model_error && <p className="error">模型调用失败，本轮不生成方向策略：{selected.model_error}</p>}<p>{selected.signal.reason}</p><dl className="execution-levels"><div><dt>入场</dt><dd>{selected.signal.entry_low ?? '—'} – {selected.signal.entry_high ?? '—'}</dd></div><div><dt>止损</dt><dd>{selected.signal.stop_loss ?? '—'}</dd></div><div><dt>止盈</dt><dd>{selected.signal.take_profit ?? '—'}</dd></div></dl><p>失效条件：{selected.signal.invalid_if}</p><small>推送：{selected.push.sent ? '已发送' : selected.push.message}</small>{selected.context?.liquidity && <p>前低扫荡收回：{selected.context.liquidity.sell_side_sweep?'是':'否'}；前高扫荡收回：{selected.context.liquidity.buy_side_sweep?'是':'否'}。仅为价格结构代理。</p>}{selected.context?.structure && <p>处理 K {selected.context.structure.processed_count} · 分型样本 {selected.context.structure.fractals.length} · 确认笔样本 {selected.context.structure.confirmed_strokes.length}</p>}{selected.context?.evidence?.map(e=><details key={e.id}><summary>视频证据 {e.timestamp} · {e.id}</summary><p>{e.text}</p><a href={e.url} target="_blank" rel="noreferrer">跳转视频原文位置</a></details>)}</article>}</div>
 </>}
 {busy && <p role="status">正在{busy === 'analyze' ? '获取行情并分析，请稍候' : '处理请求'}…</p>}{message && <p role="status" className="success">{message}</p>}{error && <p role="alert" className="error">{error}</p>}
 </section>
}
