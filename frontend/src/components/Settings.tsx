import { useRef, useState } from 'react'
import type { Appearance } from '../types'
import { call, errorMessage } from '../lib/bridge'
export function Settings({ appearance, update }: { appearance: Appearance; update: (value: Appearance) => void }) {
 const iconInput = useRef<HTMLInputElement>(null), backgroundInput = useRef<HTMLInputElement>(null)
 const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('')
 async function save(kind: 'icon' | 'background', file?: File) {
   setError(''); setMessage(''); setBusy(true)
   try {
     let data_url: string | null = null
     if (file) {
       if (!['image/jpeg', 'image/png'].includes(file.type)) throw new Error('请选择 PNG 或 JPG 图片')
       if (file.size > 8 * 1024 * 1024) throw new Error('图片不能超过 8 MB')
       data_url = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file) })
     }
     update(await call<Appearance>('save_appearance', {kind, data_url})); setMessage('已保存，重新打开后仍会保留')
   } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
 }
 return <section><div className="appearance-grid">{(['icon', 'background'] as const).map(kind => {
   const input = kind === 'icon' ? iconInput : backgroundInput
   return <article className="appearance-card" key={kind}><h3>{kind === 'icon' ? '应用图标' : '大厅背景'}</h3><div className={'image-preview ' + kind}><img src={appearance[kind] || ('assets/' + (kind === 'icon' ? 'custom-icon.jpg' : 'lobby.jpg'))} alt={kind === 'icon' ? '应用图标预览' : '大厅背景预览'} /></div><p>{kind === 'icon' ? '同步到界面与运行时 Dock 图标' : '同步到大厅背景'} · PNG / JPG，最大 8 MB</p><div className="actions"><button className="primary" disabled={busy} onClick={() => input.current?.click()}>选择图片</button><button disabled={busy} onClick={() => void save(kind)}>恢复默认</button></div><input ref={input} hidden type="file" accept="image/png,image/jpeg" onChange={event => { const file = event.target.files?.[0]; if (file) void save(kind, file); event.target.value = '' }} /></article>
 })}</div>{message && <p role="status" className="success">{message}</p>}{error && <p className="error" role="alert">{error}</p>}</section>
}
