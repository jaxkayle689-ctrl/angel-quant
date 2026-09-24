import { useEffect, useState } from 'react'
import { call, errorMessage } from '../lib/bridge'

export function PipelineWorkbench() {
 const [url, setUrl] = useState(''), [error, setError] = useState('')
 async function open() {
   setError('')
   try { setUrl((await call<{url: string}>('pipeline_open')).url) }
   catch (e) { setError(errorMessage(e)) }
 }
 useEffect(() => { void open() }, [])
 return <section>{error ? <p role="alert" className="error">{error} <button onClick={() => void open()}>重试</button></p> : !url ? <p>正在启动策略工作台…</p> : <iframe title="智能策略工作台" src={url} style={{width:'100%', height:'calc(100vh - 150px)', minHeight:650, border:0, borderRadius:16}} />}</section>
}
