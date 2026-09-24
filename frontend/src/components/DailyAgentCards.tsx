import { useEffect, useState } from 'react'
import { call, errorMessage } from '../lib/bridge'
import { Dialog } from './Dialog'
import { AgentWorkbench } from './AgentWorkbench'
import { ContractPicker } from './ContractPicker'
import type { ContractCatalog } from './ContractPicker'

type Watch = {symbol:string; timeframe:string}
type Config = {provider:string;model:string;api_key_configured:boolean;push_enabled:boolean;feishu_configured:boolean;watchlist:Watch[];risk:Record<string,number>;poll_seconds:number}
type RecordItem = {id:string;agent_version:string;analysis_status:string;strategy_mode:string;strategy_name:string;model:string;source:string;created_at:string;model_error:string;
 snapshot:Watch & {candle_time:string;price:number};signal:{execution?:string;trigger?:string;action:string;entry_low:number|null;entry_high:number|null;stop_loss:number|null;tp1:number|null;tp2:number|null;tp3:number|null;reason:string;invalid_if:string;confidence:number;risk_status:string;validation_notes:string[]};
 trace:{stage:string;status:string;summary:string}[];context?:{evidence?:{id:string;text:unknown;timestamp?:string;url?:string}[]};push:{sent:boolean;message:string}}
type Status = {config:Config;running:boolean;history:RecordItem[]}
type MacroSummary = {next_high:null|{title:string;local_time:string;countdown_minutes:number;analysis:{impact:string}}}
const labels:Record<string,string>={not_configured:'待接入模型',failed:'分析失败',review_rejected:'复核未通过',completed:'分析完成'}

const stages:Record<string,string>={plan:'规划 Agent',tools:'证据工具',analysis:'分析 Agent',review:'复核 Agent',risk:'点位校验'}
const price=(n:number|null|undefined)=>n==null?'—':n.toLocaleString(undefined,{maximumFractionDigits:6})

export function DailyAgentCards(){
 const [status,setStatus]=useState<Status>(),[catalog,setCatalog]=useState<ContractCatalog>(),[error,setError]=useState(''),[notice,setNotice]=useState('')
 const [busy,setBusy]=useState(''),[settings,setSettings]=useState(false),[adding,setAdding]=useState(false),[detail,setDetail]=useState<RecordItem>()
 const [newWatch,setNewWatch]=useState<Watch>({symbol:'',timeframe:'15m'}),[draft,setDraft]=useState<Config>(),[webhook,setWebhook]=useState(''),[secret,setSecret]=useState('')
 const [history,setHistory]=useState<RecordItem[]>([])
 const [macro,setMacro]=useState<MacroSummary>()
 async function refresh(){const data=await call<Status>('agent_status');setStatus(data);setHistory(data.history.filter(r=>r.agent_version==='agent-v2'));return data}
 async function contracts(){try {setCatalog(await call<ContractCatalog>('agent_contract_catalog',{refresh:true}))}catch(e){setError(errorMessage(e))}}
 useEffect(()=>{void refresh().catch(e=>setError(errorMessage(e)));void contracts();void call<MacroSummary>('macro_calendar',{}).then(setMacro).catch(()=>undefined);const timer=setInterval(()=>void refresh().catch(e=>setError(errorMessage(e))),10000);return()=>clearInterval(timer)},[])
 async function analyze(watch?:Watch){
   setError('');setNotice('');setBusy(watch?.symbol||'all')
   try {
     for(const item of watch?[watch]:(status?.config.watchlist||[])){
       await call('analyze_daily_agents',{watch_item:item});await refresh()
     }
     setNotice('两套 Agent 已分别完成本轮处理。手动生成卡片不发送推送。')
   }catch(e){setError(errorMessage(e))}finally{setBusy('')}
 }
 async function saveWatch(items:Watch[]){await call('configure_agent',{watchlist:items});await refresh()}
 async function add(){setBusy('add');setError('');try{if(!catalog?.groups.some(g=>g.items.some(i=>i.symbol===newWatch.symbol)))throw Error('请选择已核验的合约');await saveWatch([...(status?.config.watchlist||[]),newWatch]);setAdding(false)}catch(e){setError(errorMessage(e))}finally{setBusy('')}}
 async function saveSettings(){setBusy('settings');setError('');try{await call('configure_agent',{poll_seconds:draft?.poll_seconds,push_enabled:draft?.push_enabled,...(webhook?{feishu_webhook:webhook}:{}),...(secret?{feishu_secret:secret}:{})});setWebhook('');setSecret('');await refresh();setNotice('推送设置已保存')}catch(e){setError(errorMessage(e))}finally{setBusy('')}}
 async function toggle(){setBusy('monitor');setError('');try{await (status?.running?call('stop_agent_monitor'):call('start_agent_monitor',{}));await refresh()}catch(e){setError(errorMessage(e))}finally{setBusy('')}}
 const config=status?.config, ready=!!config?.api_key_configured && config.provider!=='rules'
 const latest=(w:Watch,mode:string)=>history.find(r=>r.strategy_mode===mode && r.snapshot.symbol===w.symbol && r.snapshot.timeframe===w.timeframe)
 return <section className="daily-cards">
 <div className="section-head"><div><h2>合约策略卡片</h2><small>Binance USDT 永续 · 每个标的独立运行两套 Agent</small></div><div className="actions"><button onClick={()=>{setDraft(config);setSettings(true)}}>Agent 与推送设置</button><button disabled={!!busy||status?.running||!catalog} onClick={()=>{setNewWatch({symbol:catalog?.groups[0]?.items[0]?.symbol||'',timeframe:'15m'});setAdding(true)}}>添加合约</button><button className="primary" disabled={!!busy||!ready||!catalog||status?.running} onClick={()=>void analyze()}>{busy==='all'?'Agent 分析中…':'全部生成策略'}</button></div></div>
 <div className="agent-overview"><div><b>{ready?config?.model:'等待接入模型'}</b><span>{ready?'规划 → 工具取证 → 模型分析 → 模型复核 → 策略卡片':'先在设置中输入 API Key；不使用本地规则生成结论'}</span></div><div><b>{status?.running?'Agent 运行中':'自动 Agent 已停止'}</b><span>{config?.push_enabled?(config.feishu_configured?'飞书通道已配置':'飞书尚未配置'):'飞书推送关闭'}</span></div><button disabled={!!busy||(!status?.running&&!ready)} onClick={()=>void toggle()}>{status?.running?'停止自动 Agent':'启动自动 Agent'}</button></div>
 {macro?.next_high&&<a className="strategy-macro-warning" href="#calendar"><b>宏观风险：{macro.next_high.title}</b><span>{new Date(macro.next_high.local_time).toLocaleString('zh-CN',{hour12:false})} · {macro.next_high.analysis.impact}</span><em>查看日历 →</em></a>}
 {!catalog&&<div className="agent-notice">正在核验 Binance 合约目录；目录不可用时不能生成策略。<button onClick={()=>void contracts()}>重试目录</button></div>}
 {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status" className="success">{notice}</p>}
 {(config?.watchlist||[]).map(w=><article className="daily-contract" key={w.symbol+':'+w.timeframe}><div className="section-head"><div><h2>{w.symbol}<small> · {w.timeframe}</small></h2><small>Binance U 本位合约</small></div><div className="actions"><a className="coinglass-link" href={'https://www.coinglass.com/pro/futures/LiquidationHeatMap?coin='+encodeURIComponent(w.symbol.replace(/USDT$/,''))} target="_blank" rel="noopener noreferrer" title="打开对应标的清算热力图；可用性以 CoinGlass 页面为准">CoinGlass 流动性 ↗</a><button disabled={!!busy||!ready||!catalog||status?.running} onClick={()=>void analyze(w)}>{busy===w.symbol?'Agent 分析中…':'生成两套策略'}</button><button disabled={!!busy||status?.running||config!.watchlist.length===1} onClick={()=>void saveWatch(config!.watchlist.filter(x=>x!==w)).catch(e=>setError(errorMessage(e)))}>移除合约</button></div></div><div className="dual-card-grid">{['comprehensive','chanlun'].map((mode,i)=>{
   const r=latest(w,mode),s=r?.signal, complete=r?.analysis_status==='completed',direction=complete&&s?.risk_status==='PASSED'&&s.action!=='WAIT'
   return <article key={mode} className={'agent-strategy-card '+(direction?s?.action.toLowerCase():'wait')}><div className="section-head"><div><small>策略 {i+1} / AGENT</small><h3>{i===0?'流动性扫荡':'缠论体系'}</h3></div><span className="badge">{r?(complete?(s?.action==='LONG'?'做多':s?.action==='SHORT'?'做空':'暂无法生成'):labels[r.analysis_status]||'未完成'):'待分析'}</span></div><p className="card-method">{i===0?'核查前高低点扫荡、收回与确认，综合量价结构判断。':'读取行情结构与视频 RAG，区分候选结构和已确认依据。'}</p>
   <dl className="agent-card-levels"><div><dt>入场区间</dt><dd>{direction?price(s?.entry_low)+' – '+price(s?.entry_high):'—'}</dd></div><div className="stop"><dt>止损 SL</dt><dd>{direction?price(s?.stop_loss):'—'}</dd></div>{(['tp1','tp2','tp3'] as const).map((k,j)=><div key={k}><dt>止盈 TP{j+1}</dt><dd>{direction?price(s?.[k]):'—'}</dd></div>)}</dl>
   {direction&&<p className="agent-notice"><b>{s?.execution==='READY'?'入场条件已满足':'条件策略 · 触发后执行'}</b><br/>{s?.trigger}</p>}<p className="agent-card-reason">{s?.reason||'等待 Agent 获取证据并分析；不会展示程序兜底的交易结论。'}</p>{r&&<><p className="muted">失效条件：{s?.invalid_if}</p><small>{r.model} · 模型评分 {s?.confidence}（非胜率）<br/>生成：{new Date(r.created_at).toLocaleString()}<br/>行情收盘：{new Date(r.snapshot.candle_time).toLocaleString()}<br/>推送：{r.push.sent?'已发送':r.push.message}</small></>}<button className="agent-detail-button" disabled={!r} onClick={()=>setDetail(r)}>查看 Agent 依据与执行记录</button></article>
 })}</div></article>)}
 {settings&&<Dialog title="Agent 与推送设置" busy={!!busy} close={()=>{setSettings(false);void refresh()}}><div className="agent-settings-scroll">{error&&<p role="alert" className="error">{error}</p>}{notice&&<p className="success">{notice}</p>}<AgentWorkbench settingsOnly/><p>同一合约始终运行策略1和策略2。每套 Agent 正常完成包含3次模型调用；自动运行仅在新收盘 K 出现时分析。</p><h3>推送设置</h3><label>检查间隔（秒）<input disabled={status?.running} type="number" min="10" max="3600" value={draft?.poll_seconds??30} onChange={e=>setDraft(d=>d?{...d,poll_seconds:Number(e.target.value)}:d)}/></label><label className="agent-check"><input disabled={status?.running} type="checkbox" checked={draft?.push_enabled||false} onChange={e=>setDraft(d=>d?{...d,push_enabled:e.target.checked}:d)}/>自动发送 Agent 策略卡片到飞书</label><label>飞书 Webhook<input disabled={status?.running} type="password" autoComplete="new-password" value={webhook} onChange={e=>setWebhook(e.target.value)} placeholder="留空保留"/></label><label>飞书签名密钥<input disabled={status?.running} type="password" autoComplete="new-password" value={secret} onChange={e=>setSecret(e.target.value)} placeholder="留空保留"/></label><button disabled={!!busy||status?.running} onClick={()=>void saveSettings()}>保存推送设置</button></div></Dialog>}
 {adding&&<Dialog title="添加 Binance 合约" busy={!!busy} close={()=>setAdding(false)}>{error&&<p role="alert" className="error">{error}</p>}<ContractPicker groups={catalog?.groups||[]} value={newWatch.symbol} index={1} disabled={!!busy} change={symbol=>setNewWatch(w=>({...w,symbol}))}/><label>分析周期<select value={newWatch.timeframe} onChange={e=>setNewWatch(w=>({...w,timeframe:e.target.value}))}>{['1m','3m','5m','15m','30m','1h','2h','4h','6h','12h','1d'].map(p=><option key={p}>{p}</option>)}</select></label><div className="actions"><button className="primary" disabled={!!busy||(config?.watchlist.length||0)>=12} onClick={()=>void add()}>添加</button></div></Dialog>}
 {detail&&<Dialog title={detail.strategy_name+' · '+detail.snapshot.symbol} close={()=>setDetail(undefined)}><p>{detail.signal.reason}</p>{detail.signal.validation_notes?.map(x=><p className="error" key={x}>{x}</p>)}<ol className="agent-trace">{detail.trace.map((t,i)=><li key={i}><b>{stages[t.stage]||t.stage} · {t.status}</b><p>{t.summary}</p></li>)}</ol>{detail.context?.evidence?.map(e=><details key={e.id}><summary>{e.timestamp||'行情证据'} · {e.id}</summary><p>{typeof e.text==='string'?e.text:JSON.stringify(e.text)}</p>{e.url?.startsWith('https://www.youtube.com/')&&<a target="_blank" rel="noreferrer" href={e.url}>查看视频原文</a>}</details>)}</Dialog>}
 </section>
}
