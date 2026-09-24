import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ExternalLink, RefreshCw } from 'lucide-react'
import { call, errorMessage } from '../lib/bridge'

type Event = {
 id:string;kind:string;title:string;scheduled_at:string;local_time:string;local_date:string;
 impact:'high'|'medium';forecast:string|null;previous:string|null;actual:string|null;
 source_type:'weekly'|'official'|'nasdaq'|'company_ir';official_url?:string;status:'upcoming'|'released';countdown_minutes:number;
 symbol?:string;fiscal_quarter?:string;session?:string;time_precision?:string;time_note?:string;
 analysis:{tone:'risk'|'positive'|'mixed'|'neutral';headline:string;impact:string}
}
type Calendar = {earnings_watchlist?:{symbol:string;name:string;status:string;url:string}[];generated_at:string;timezone:string;events:Event[];next_high:Event|null;errors:string[];notice:string;sources:{name:string;url:string;official:boolean}[]}

const kindNames:Record<string,string>={CPI:'CPI 消费者通胀',PPI:'PPI 生产端通胀',PCE:'PCE 美联储偏好通胀',NFP:'就业数据',FOMC:'美联储决议',RETAIL:'零售销售',GDP:'GDP',EARNINGS:'公司财报',OTHER:'其他宏观事件'}
const zhTitle=(e:Event)=> e.kind==='OTHER'?e.title:(kindNames[e.kind]||e.title)+(e.title.toUpperCase().includes('CORE')?' · 核心':'')
const clock=(value:string)=>new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false})
const countdown=(minutes:number)=>minutes<0?'已公布':minutes<60?`${minutes} 分钟后`:minutes<1440?`${Math.floor(minutes/60)} 小时后`:`${Math.floor(minutes/1440)} 天后`

export function MacroCalendar(){
 const [data,setData]=useState<Calendar>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[filter,setFilter]=useState<'upcoming'|'released'|'all'>('upcoming')
 async function load(refresh=false){setBusy(true);setError('');try{setData(await call<Calendar>('macro_calendar',{refresh}))}catch(e){setError(errorMessage(e))}finally{setBusy(false)}}
 useEffect(()=>{void load()},[])
 const events=useMemo(()=>data?.events.filter(e=>filter==='all'||e.status===filter)||[],[data,filter])
 const groups=useMemo(()=>events.reduce<Record<string,Event[]>>((out,e)=>{(out[e.local_date]??=[]).push(e);return out},{}),[events])
 return <section className="macro-calendar">
  <div className="section-head"><div><h2>美国宏观与财报日历</h2><small>北京时间 · CPI / PPI / PCE / 非农 / FOMC / 重点公司财报</small></div><button disabled={busy} onClick={()=>void load(true)}><RefreshCw size={16} className={busy?'spin':''}/>{busy?'刷新中…':'刷新日历'}</button></div>
  {data?.next_high&&<article className="macro-alert"><AlertTriangle size={24}/><div><small>下一个高影响事件 · {countdown(data.next_high.countdown_minutes)}</small><h3>{data.next_high.kind==='EARNINGS'?data.next_high.title:zhTitle(data.next_high)}</h3><p>{data.next_high.time_precision==='session'?data.next_high.local_date+' · '+data.next_high.time_note:clock(data.next_high.local_time)} · {data.next_high.analysis.impact}</p></div></article>}
  <div className="calendar-legend"><span><i className="impact high"/>高影响</span><span><i className="impact medium"/>中影响</span><span>所有时间已换算为北京时间</span></div>
  <div className="calendar-tabs" role="group" aria-label="日历范围">{([['upcoming','即将公布'],['released','已公布'],['all','全部']] as const).map(([id,label])=><button key={id} className={filter===id?'active':''} aria-pressed={filter===id} onClick={()=>setFilter(id)}>{label}</button>)}</div>
  {error&&<p className="error" role="alert">{error}</p>}{data?.errors.map(item=><p className="agent-notice" key={item}>{item}</p>)}
  {!data&&!error?<div className="empty">正在读取经济与财报日历…</div>:Object.keys(groups).length===0?<div className="empty">当前范围没有事件</div>:<div className="calendar-days">{Object.entries(groups).map(([date,items])=><article className="calendar-day" key={date}><header><strong>{new Date(date+'T12:00:00+08:00').toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})}</strong><small>{items.length} 项事件</small></header><div>{items.map(e=><div className="macro-event" key={e.id}><time>{e.time_precision==='session'?'待确认':new Date(e.local_time).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false})}</time><i className={'impact '+e.impact}/><div className="macro-event-main"><div><h3>{e.kind==='EARNINGS'?e.title:zhTitle(e)}</h3><span className={'scenario '+e.analysis.tone}>{e.analysis.headline}</span></div><dl>{e.kind==='EARNINGS'?<><div><dt>代码</dt><dd>{e.symbol}</dd></div><div><dt>市场预期 EPS</dt><dd>{e.forecast??'—'}</dd></div><div><dt>财季</dt><dd>{e.fiscal_quarter??'—'}</dd></div></>:<><div><dt>前值</dt><dd>{e.previous??'—'}</dd></div><div><dt>预期</dt><dd>{e.forecast??'—'}</dd></div><div><dt>实际</dt><dd>{e.actual??(e.status==='released'?'待官方核验':'—')}</dd></div></>}</dl><p>{e.time_note && <span>{e.time_note} · </span>}{e.analysis.impact}</p><small>{e.status==='upcoming'?countdown(e.countdown_minutes):'已过发布时间'} · {e.source_type==='company_ir'||e.source_type==='official'?'官方排期':e.source_type==='nasdaq'?'Nasdaq 财报日历':'本周市场日历'} {e.official_url&&<a href={e.official_url} target="_blank" rel="noopener noreferrer">核验官方来源 <ExternalLink size={12}/></a>}</small></div></div>)}</div></article>)}</div>}
  {data?.earnings_watchlist&&<details className="calendar-sources" open><summary>重点公司财报 · {data.earnings_watchlist.length} 家 · 未来45天</summary><div>{data.earnings_watchlist.map(c=><a key={c.symbol} href={c.url} target="_blank" rel="noopener noreferrer">{c.name} ({c.symbol}) · {c.status==='scheduled'?'已有排期':'窗口内暂无日期 / 待更新'}</a>)}</div></details>}
  {data&&<footer className="calendar-sources"><p>{data.notice}</p><div>{data.sources.map(source=><a key={source.name} href={source.url} target="_blank" rel="noopener noreferrer">{source.name}<ExternalLink size={12}/></a>)}</div><small>更新时间：{new Date(data.generated_at).toLocaleString('zh-CN',{hour12:false})}</small></footer>}
 </section>
}
