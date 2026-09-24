import { useState } from 'react'
import { Pencil, MoreHorizontal } from 'lucide-react'
import type { LibraryStrategy } from '../types'
import { Dialog } from './Dialog'
import { call, errorMessage } from '../lib/bridge'
export function Library({ items, update }: { items: LibraryStrategy[]; update: (items: LibraryStrategy[]) => void }) {
 const [modal, setModal] = useState<{ item: LibraryStrategy; action: 'info' | 'rename' | 'delete' } | null>(null)
 const [name, setName] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState('')
 const open = (item: LibraryStrategy, action: 'info' | 'rename' | 'delete') => { setName(item.name); setError(''); setModal({item, action}) }
 async function save() {
   if (!modal) return
   setBusy(true); setError('')
   try { update(await call<LibraryStrategy[]>('edit_library_strategy', { id: modal.item.id, action: modal.action, name: name.trim() })); setModal(null) }
   catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
 }
 return <section><div className="section-head"><small>{items.length} 个策略</small></div><div className="library-list">{items.map(item => <article className="library-row" key={item.id}><h3>{item.name}</h3><button className="icon-button row-action" aria-label={'重命名 ' + item.name} title="重命名" onClick={() => open(item, 'rename')}><Pencil size={16} /></button><details className="row-menu"><summary aria-label={item.name + ' 更多操作'}><MoreHorizontal size={22} /></summary><div><button onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); open(item, 'info') }}>详细信息</button><button className="danger-text" onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); open(item, 'delete') }}>删除</button></div></details></article>)}</div>{!items.length && <div className="empty">策略库为空</div>}
 {modal && <Dialog title={modal.action === 'info' ? modal.item.name : modal.action === 'rename' ? '修改策略名称' : '删除策略'} close={() => setModal(null)} busy={busy}>
 {modal.action === 'info' ? <><p>{modal.item.description || '暂无说明'}</p>{modal.item.source_url&&<p><a href={modal.item.source_url} target="_blank" rel="noopener noreferrer">查看上游源码 ↗</a> · {modal.item.validation_status}</p>}{modal.item.license_note&&<small>{modal.item.license_note}</small>}<dl className="facts"><dt>策略 ID</dt><dd>{modal.item.id}</dd><dt>版本</dt><dd>{modal.item.version || '—'}</dd><dt>引擎</dt><dd>{modal.item.backtest_adapter?.engine || '—'}</dd><dt>能力</dt><dd>{modal.item.capabilities?.join(' · ') || '—'}</dd></dl><div className="dialog-actions"><button onClick={() => { setModal(null); location.hash = "validation" }}>进入策略验证</button><button onClick={() => { setModal(null); location.hash = "simulation" }}>进入模拟盘</button><button onClick={() => setModal(null)}>关闭</button></div></> : <form onSubmit={event => { event.preventDefault(); void save() }}>
 {modal.action === 'rename' ? <label>策略名称<input autoFocus required maxLength={80} value={name} onChange={event => setName(event.target.value)} /></label> : <p>从策略库移除「{modal.item.name}」？策略原文件和已有组合会保留。</p>}
 {error && <p role="alert" className="error">{error}</p>}<div className="dialog-actions"><button type="button" disabled={busy} onClick={() => setModal(null)}>取消</button><button className={modal.action === 'delete' ? 'danger' : 'primary'} disabled={busy || (modal.action === 'rename' && !name.trim())}>{busy ? '保存中…' : modal.action === 'delete' ? '删除' : '保存'}</button></div></form>}</Dialog>}
 </section>
}
