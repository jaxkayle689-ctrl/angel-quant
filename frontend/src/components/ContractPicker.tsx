import { useState } from 'react'

export type ContractGroup = {id: string; name: string; items: {symbol: string; label: string; base_asset: string}[]}
export type ContractCatalog = {groups: ContractGroup[]; count: number; source: string; verified: boolean; quote_asset: string}

export function ContractPicker({groups, value, change, disabled, index}: {groups: ContractGroup[]; value: string; change: (symbol: string) => void; disabled: boolean; index: number}) {
 const [query, setQuery] = useState('')
 const matches = groups.map(group => ({...group, items:group.items.filter(item => (item.symbol + ' ' + item.label).toLowerCase().includes(query.trim().toLowerCase()))})).filter(g=>g.items.length)
 const existing = groups.flatMap(g=>g.items).find(i=>i.symbol===value)
 const visible = matches.some(g=>g.items.some(i=>i.symbol===value))
 return <div className="contract-picker">
 <label>搜索合约 {index}<input disabled={disabled} value={query} onChange={e=>setQuery(e.target.value)} placeholder="例如 SNDK、MINIMAX、BTC 或中文名称" /></label>
 <label>Binance USDT 永续合约 {index}<select disabled={disabled} value={value} onChange={e=>change(e.target.value)}>
 {!visible && <option value={value} disabled={!existing}>{value} · {existing ? '当前选择' : '待核验 / 不可交易'}</option>}
 {matches.map(group=><optgroup key={group.id} label={group.name}>{group.items.map(item=><option key={item.symbol} value={item.symbol}>{item.symbol} · {item.label}</option>)}</optgroup>)}
 </select></label>
 {query && !matches.length && <small role="status">没有匹配的已上市合约，不会自动拼接或替换代码。</small>}
 </div>
}
