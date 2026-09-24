import { useEffect, useState } from 'react'
import { BookOpenCheck, Clock3, ExternalLink, RefreshCw, Search, ShieldCheck } from 'lucide-react'
import { call, errorMessage } from '../lib/bridge'
import type { KnowledgeAnswer, KnowledgeStatus } from '../types'

const examples = ['什么是顶底分型？', '一笔成立需要满足哪些条件？', '中枢是怎么形成的？', '背驰与买卖点有什么关系？']
const confidence = { high: '证据充分', medium: '证据一般', low: '证据不足' }

export function KnowledgeBase() {
 const [status, setStatus] = useState<KnowledgeStatus | null>(null), [question, setQuestion] = useState(''), [answer, setAnswer] = useState<KnowledgeAnswer | null>(null)
 const [busy, setBusy] = useState(false), [rebuilding, setRebuilding] = useState(false), [error, setError] = useState('')
 const load = async () => { try { setStatus(await call<KnowledgeStatus>('knowledge_status')) } catch (e) { setError(errorMessage(e)) } }
 useEffect(() => { void load() }, [])
 async function ask(value = question) { const query = value.trim(); if (query.length < 2 || busy) return; setQuestion(query); setBusy(true); setError(''); try { setAnswer(await call<KnowledgeAnswer>('knowledge_query', {question: query, limit: 6})); void load() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) } }
 async function rebuild() { setRebuilding(true); setError(''); try { setStatus(await call<KnowledgeStatus>('rebuild_knowledge_index')); setAnswer(null) } catch (e) { setError(errorMessage(e)) } finally { setRebuilding(false) } }
 return <section className="knowledge-page">
  <div className="knowledge-hero"><div><small>企业级本地 RAG · 来源可追溯</small><h2>缠论视频知识库</h2><p>从视频时间轴检索原始证据，每条回答都能跳回对应片段核验。</p></div><div className="kb-health"><ShieldCheck size={25}/><span><b>{status?.state === 'ready' ? '索引健康' : '等待索引'}</b><small>{status?.chunk_count || 0} 个知识片段 · {status?.query_count || 0} 次查询</small></span><button className="icon-button" aria-label="重建知识索引" title="重建知识索引" disabled={rebuilding} onClick={() => void rebuild()}><RefreshCw className={rebuilding ? 'spin' : ''} size={18}/></button></div></div>
  <form className="kb-search" onSubmit={event => {event.preventDefault(); void ask()}}><Search size={21}/><input aria-label="向知识库提问" value={question} onChange={event => setQuestion(event.target.value)} placeholder="输入缠论问题，例如：第三类买点如何确认？"/><button className="primary" disabled={busy || question.trim().length < 2}>{busy ? '检索中…' : '查询'}</button></form>
  <div className="kb-examples">{examples.map(item => <button key={item} onClick={() => void ask(item)}>{item}</button>)}</div>
  {error && <p className="error" role="alert">{error}</p>}
  {status?.state !== 'ready' && !error && <div className="empty"><h2>知识源正在准备</h2><p>{status?.message || '完成视频转写后即可查询。'}</p></div>}
  {answer && <div className="kb-results"><article className="kb-answer"><div className="kb-answer-head"><BookOpenCheck size={22}/><span>基于视频证据的回答</span><em className={'confidence ' + answer.confidence}>{confidence[answer.confidence]}</em></div><div className="answer-copy">{answer.answer.split('\n').map((line,index)=><p key={index}>{line}</p>)}</div><small>{answer.notice}</small></article><aside className="kb-citations"><div className="section-head"><div><h3>引用证据</h3><small>{answer.retrieval.returned} 条 · 本地混合检索</small></div></div>{answer.citations.map((item,index)=><article key={item.id}><div><span>证据 {index + 1}</span><b>{Math.round(item.score * 100)}%</b></div><p>{item.text}</p><a href={item.url} target="_blank" rel="noreferrer"><Clock3 size={14}/>{item.timestamp}<ExternalLink size={13}/></a></article>)}</aside></div>}
  {!answer && status?.state === 'ready' && <div className="kb-about"><div><strong>{status.source_count}</strong><span>已验证来源</span></div><div><strong>{status.segment_count}</strong><span>字幕时间段</span></div><div><strong>{status.chunk_count}</strong><span>可检索片段</span></div><div><strong>100%</strong><span>本地持久化</span></div></div>}
 </section>
}
