import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
export function Dialog({ title, children, close, busy = false }: { title: string; children: ReactNode; close: () => void; busy?: boolean }) {
 const ref = useRef<HTMLDialogElement>(null)
 useEffect(() => { const el = ref.current!; el.showModal(); el.querySelector<HTMLInputElement>('input')?.focus(); return () => el.close() }, [])
 return <dialog ref={ref} className="dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) close() }} onClick={event => { if (event.target === event.currentTarget && !busy) close() }}>
 <div className="dialog-heading"><h2>{title}</h2><button className="icon-button" aria-label="关闭" disabled={busy} onClick={close}><X size={20} /></button></div>{children}</dialog>
}
