import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, BookOpen, CalendarDays, Database, FlaskConical, LayoutDashboard, Settings as SettingsIcon, Wallet, Layers } from 'lucide-react'
import { call, errorMessage } from './lib/bridge'
import type { Appearance, Bootstrap, LibraryStrategy } from './types'
import { Library } from './components/Library'
import { Settings } from './components/Settings'
import { KnowledgeBase } from './components/KnowledgeBase'
import { DailyAgentCards } from './components/DailyAgentCards'
import { AgentWorkbench } from './components/AgentWorkbench'
import { MacroCalendar } from './components/MacroCalendar'
import { PipelineWorkbench } from './components/PipelineWorkbench'

const nav = [
 { id: 'home', label: '总览', icon: LayoutDashboard },
 { id: 'daily', label: '当日策略', icon: Layers },
 { id: 'agent', label: '智能策略工作台', icon: Layers },
 { id: 'calendar', label: '宏观日历', icon: CalendarDays },
 { id: 'simulation', label: '模拟盘', icon: Wallet },
 { id: 'validation', label: '策略验证', icon: FlaskConical },
 { id: 'live', label: '实盘账户', icon: Wallet },
 { id: 'library', label: '策略库', icon: BookOpen },
 { id: 'knowledge', label: '缠论知识库', icon: Database },
 { id: 'settings', label: '设置', icon: SettingsIcon },
]
type Route = { view: string; asset?: string }
function readRoute(): Route { const [rawView, asset] = location.hash.slice(1).split('/'); const view = rawView === 'research' ? 'daily' : rawView; return {view: nav.some(item => item.id === view) ? view : 'home', asset: asset ? decodeURIComponent(asset) : undefined} }
const legacyViews = new Set(['simulation', 'validation', 'live'])
export function App() {
 const [route, setRoute] = useState(readRoute), [library, setLibrary] = useState<LibraryStrategy[]>([])
 const [appearance, setAppearance] = useState<Appearance>({})
 const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading'), [error, setError] = useState('')
 const boot = useRef<Promise<Bootstrap> | null>(null)
 const content = useRef<HTMLElement>(null)
 const navigate = (view: string, asset?: string) => { location.hash = view + (asset ? '/' + encodeURIComponent(asset) : '') }
 const initialize = useCallback(async () => {
   setState('loading'); setError('')
   try {
     if (!boot.current) boot.current = call<Bootstrap>('workspace_bootstrap')
     const data = await boot.current
     setLibrary(data.strategies); setAppearance(data.workspace_settings)
     setState('ready')
   } catch (e) { boot.current = null; setState('error'); setError(errorMessage(e)) }
 }, [])
 useEffect(() => { void initialize(); const change = () => setRoute(readRoute()); window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change) }, [initialize])
 useEffect(() => { content.current?.scrollTo(0, 0) }, [route.view, route.asset])
 useEffect(() => { const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]'); if (icon) icon.href = appearance.icon || 'assets/custom-icon.jpg' }, [appearance.icon])
 useEffect(() => { const close = (e: MouseEvent) => document.querySelectorAll('details.row-menu[open]').forEach(el => { if (!el.contains(e.target as Node)) el.removeAttribute('open') }); document.addEventListener('click', close); return () => document.removeEventListener('click', close) }, [])
 const background = appearance.background || 'assets/lobby.jpg'
 return <div className="shell">
 <aside className="sidebar"><button className="brand" onClick={() => navigate('home')} aria-label="返回大厅"><img src={appearance.icon || 'assets/custom-icon.jpg'} alt="" /><span><b>只想玩天使</b><small>量化工作台</small></span></button><nav aria-label="主要导航">{nav.map(item => <button key={item.id} title={item.label} aria-label={item.label} aria-current={route.view === item.id ? 'page' : undefined} className={route.view === item.id ? 'active' : ''} onClick={() => navigate(item.id)}><item.icon size={18} /><span>{item.label}</span></button>)}</nav><div className="sidebar-foot"><span className={'connection ' + state}><i />{state === 'ready' ? '本地已连接' : state === 'loading' ? '连接中' : '未连接'}</span><small>v0.12.0</small></div></aside>
 <main className="content" ref={content}><header className="topbar"><div><small>工作台 / {nav.find(item => item.id === route.view)?.label}</small><h1>{nav.find(item => item.id === route.view)?.label}</h1></div></header>
 {state !== 'ready' ? <section className="empty"><h2>{state === 'loading' ? '正在连接工作台…' : '连接未完成'}</h2>{error && <p className="error" role="alert">{error}</p>}{state === 'error' && <button onClick={() => void initialize()}>重试连接</button>}</section> : <>
 {route.view === 'home' && <section className="home"><div className="hero" style={{backgroundImage: 'linear-gradient(90deg,rgba(18,36,28,.65),rgba(18,36,28,.08)),url(' + JSON.stringify(background) + ')'}}><div><small>只想玩天使的量化</small><h2>你的交易工作台</h2><button onClick={() => navigate('daily')}>当日策略 <ArrowUpRight size={18} /></button></div></div><div className="home-metrics"><div><strong>2</strong><span>独立策略 Agent</span></div><div><strong>{library.length}</strong><span>策略库条目</span></div><div><strong>USDT</strong><span>Binance 永续合约</span></div></div><div className="home-links">{nav.filter(item => !['home', 'settings'].includes(item.id)).map(item => <button key={item.id} onClick={() => navigate(item.id)}><item.icon size={21} /><span>{item.label}</span><ArrowUpRight size={18} /></button>)}</div></section>}
 {route.view === 'library' && <Library items={library} update={setLibrary} />}
 {route.view === 'knowledge' && <KnowledgeBase />}
 {route.view === 'daily' && <DailyAgentCards />}
 {route.view === 'agent' && <PipelineWorkbench />}
 {route.view === 'calendar' && <MacroCalendar />}
 {route.view === 'settings' && <><AgentWorkbench settingsOnly /><Settings appearance={appearance} update={setAppearance} /></>}
 {legacyViews.has(route.view) && <section className="legacy-panel"><p>此模块沿用现有交易工作台，账户连接和运行配置在模块内管理。</p><iframe title={nav.find(item => item.id === route.view)?.label} src={'../web/index.html#embedded=' + route.view} onLoad={event => { const frame = event.currentTarget; if (frame.contentWindow) { frame.contentWindow.pywebview = window.pywebview; frame.contentWindow.dispatchEvent(new Event('pywebviewready')) } }} /></section>}
 </>}

 </main></div>
}
