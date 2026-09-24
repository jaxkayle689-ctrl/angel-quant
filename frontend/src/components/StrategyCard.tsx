import { ArrowUpRight } from 'lucide-react'
import type { Asset, Report } from '../types'
import { price, percent, time } from '../lib/format'
export function StrategyCard({ asset, report, busy, error, open }: { asset: Asset; report?: Report; busy?: boolean; error?: string; open: () => void }) {
 const s = report?.strategy
 return <button className="strategy-card" onClick={open} aria-label={'查看 ' + asset.symbol + ' 策略详情'}>
 <div className="card-top"><div><h2>{asset.symbol}</h2><small>{asset.name}</small></div><span className={'badge ' + (s?.direction_code?.toLowerCase() || 'wait')}>{s?.direction || '待生成'}</span></div>
 <dl className="levels"><div><dt>入场区间</dt><dd>{price(s?.entry_low)}{s?.entry_high != null && ' – ' + price(s.entry_high)}</dd></div><div className="stop"><dt>止损 SL</dt><dd>{price(s?.stop_loss)}</dd></div>{(['tp1', 'tp2', 'tp3'] as const).map((key, i) => <div key={key}><dt>目标 {i + 1}</dt><dd>{price(s?.[key])}</dd></div>)}</dl>
 <div className="card-quote"><span>现价</span><strong>{price(report?.quote.price)}</strong><em className={(report?.quote.change_pct || 0) < 0 ? 'negative' : 'positive'}>{percent(report?.quote.change_pct)}</em></div>
 <p className="card-note">{error || s?.condition || '生成后查看入场条件和判断依据'}</p>
 <div className="card-footer"><span>{busy ? '正在更新…' : report ? '行情 ' + time(report.quote.as_of) : '尚未生成'}<br />{report && '报告 ' + time(report.generated_at)}</span><ArrowUpRight size={17} /></div></button>
}
