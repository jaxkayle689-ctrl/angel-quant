// @vitest-environment jsdom
import { beforeEach, afterEach, test, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react'
import { App } from '../src/App'
import { AgentWorkbench } from '../src/components/AgentWorkbench'
const asset = (id: string) => ({id, symbol: id, name: id, exchange: 'NASDAQ', currency: 'USD'})
const report = (id: string, value = 100) => ({asset: asset(id), generated_at: '2026-09-09T01:00:00Z', quote: {price: value, change_pct: -1.23, as_of: '2026-09-09T00:59:00Z'}, strategy: {direction: '观望', direction_code: 'WAIT', entry_low: null, entry_high: null, tp1: null, tp2: null, tp3: null, stop_loss: null, condition: '等待结构确认'}, summary: {upper_liquidity: '价格结构估算'}, modules: [{title: '价格结构流动性代理', status: 'estimated', summary: '价格结构估算', details: ['价格结构依据']}], sources: [], warnings: []})
let assets, library, reports, appearance, api
beforeEach(() => {
 history.replaceState({}, '', '/#daily')
 assets = [asset('SNDK'), asset('MRVL')]
 library = [{id:'ema', name:'EMA策略', version:'1.0', description:'策略详情说明', capabilities:['long']}]
 reports = {SNDK: report('SNDK'), MRVL: report('MRVL')}
 appearance = {}
 HTMLElement.prototype.scrollTo = vi.fn()
 HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
 HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
 api = {
   agent_contract_catalog: vi.fn(async()=>({ok:true,data:{verified:true,count:2,source:'Binance',quote_asset:'USDT',groups:[{id:'equity',name:'股票永续',items:[{symbol:'SNDKUSDT',base_asset:'SNDK',label:'闪迪'},{symbol:'BTCUSDT',base_asset:'BTC',label:'比特币'}]}]}})),
   workspace_bootstrap: vi.fn(async (...args) => { expect(args).toEqual([]); return {ok:true, data:{strategies:library, daily_strategy_assets:assets, workspace_settings:{...appearance, reports}}} }),
   generate_daily_strategy: vi.fn(async ({asset_id}) => ({ok:true,data:report(asset_id, 105)})),
   add_daily_asset: vi.fn(async ({symbol}) => { if(symbol.includes('!')) return {ok:false,error:'代码无效'}; if (!assets.some(a=>a.id===symbol)) assets=[...assets,asset(symbol)]; return {ok:true,data:assets} }),
   edit_library_strategy: vi.fn(async ({id,action,name}) => { library=action==='delete'?library.filter(s=>s.id!==id):library.map(s=>s.id===id?{...s,name}:s);return {ok:true,data:library} }),
   save_appearance: vi.fn(async ({kind,data_url}) => {appearance={...appearance,[kind]:data_url};return {ok:true,data:appearance}}),
   knowledge_status: vi.fn(async () => ({ok:true,data:{state:'ready',source_count:1,chunk_count:24,segment_count:100,query_count:0,source:{id:'video',title:'缠论教程',url:'https://youtube.com/watch?v=x',language:'zh-CN'}}})),
   knowledge_query: vi.fn(async ({question}) => ({ok:true,data:{question,answer:'根据视频中命中的内容：\n\n1. 顶分型中间K线高点最高。',confidence:'high',citations:[{id:'c1',title:'缠论教程',text:'顶分型中间K线高点最高。',timestamp:'12:30',start_seconds:750,end_seconds:760,url:'https://youtube.com/watch?v=x&t=750s',score:.82,source_id:'video'}],retrieval:{method:'local-hybrid-v1',returned:1},notice:'仅依据视频字幕'}})),
   rebuild_knowledge_index: vi.fn(async () => ({ok:true,data:{state:'ready',source_count:1,chunk_count:24,segment_count:100,query_count:0}})),
   macro_calendar: vi.fn(async()=>({ok:true,data:{generated_at:'2026-09-16T00:00:00Z',timezone:'Asia/Shanghai',errors:[],notice:'情景分析',sources:[{name:'CPI 官方发布时间',url:'https://www.bls.gov/schedule/news_release/cpi.htm',official:true}],next_high:{id:'fomc',kind:'FOMC',title:'FOMC Statement',scheduled_at:'2026-09-16T18:00:00Z',local_time:'2026-09-17T02:00:00+08:00',local_date:'2026-09-17',impact:'high',forecast:null,previous:null,actual:null,source_type:'weekly',status:'upcoming',countdown_minutes:1080,analysis:{tone:'risk',headline:'政策路径风险',impact:'偏鹰通常利空成长股与加密资产，偏鸽通常相反。'}},events:[{id:'cpi',kind:'CPI',title:'CPI y/y',scheduled_at:'2026-10-14T12:30:00Z',local_time:'2026-10-14T20:30:00+08:00',local_date:'2026-10-14',impact:'high',forecast:'3.1%',previous:'3.0%',actual:null,source_type:'official',official_url:'https://www.bls.gov/schedule/news_release/cpi.htm',status:'upcoming',countdown_minutes:40950,analysis:{tone:'risk',headline:'通胀事件风险',impact:'高于预期通常推升利率预期并压制成长股；低于预期通常利好纳指。'}}]}})),
 }
 const config = {provider:'deepseek',model:'deepseek-chat',strategy_mode:'comprehensive',poll_seconds:30,push_enabled:false,api_key_configured:false,feishu_configured:false,watchlist:[{symbol:'BTCUSDT',timeframe:'15m'}],risk:{account_balance:1000,risk_per_trade_pct:1,leverage:3,max_margin_pct:20,min_confidence:60,min_risk_reward:1.5,max_stop_pct:3,max_atr_pct:3.2}}
 api.agent_status=vi.fn(async()=>({ok:true,data:{running:false,config,history:[],logs:[]}}))
 api.configure_agent=vi.fn(async payload=>{Object.assign(config,payload);return {ok:true,data:{config}}})
 window.pywebview={api}
})
afterEach(cleanup)
test('daily merges research into two card agents and disables generation without a key', async()=>{
 render(<App/>); await screen.findByRole('heading',{name:'合约策略卡片'})
 expect(screen.queryByRole('button',{name:'股票研究'})).toBeNull()
 expect(await screen.findByRole('heading',{name:'流动性扫荡'})).toBeTruthy()
 expect(screen.getByRole('heading',{name:'缠论体系'})).toBeTruthy()
 expect((screen.getByRole('button',{name:'全部生成策略'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByRole('link',{name:/CoinGlass/}).getAttribute('href')).toContain('coin=BTC')
 fireEvent.click(screen.getByRole('button',{name:'Agent 与推送设置'}))
 expect(screen.queryByLabelText('单笔风险 %')).toBeNull()
 expect(screen.queryByLabelText('最低盈亏比')).toBeNull()
 expect(api.generate_daily_strategy).not.toHaveBeenCalled()
})
test('adds only Binance catalog selections to the agent watchlist',async()=>{
 render(<App/>);await screen.findByRole('heading',{name:'合约策略卡片'})
 await waitFor(()=>expect((screen.getByRole('button',{name:'添加合约'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'添加合约'}))
 fireEvent.change(screen.getByLabelText('搜索合约 1'),{target:{value:'SNDK'}})
 fireEvent.change(screen.getByLabelText('Binance USDT 永续合约 1'),{target:{value:'SNDKUSDT'}})
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'添加',exact:true}))
 await waitFor(()=>expect(api.configure_agent).toHaveBeenCalledWith({watchlist:[{symbol:'BTCUSDT',timeframe:'15m'},{symbol:'SNDKUSDT',timeframe:'15m'}]}))
 expect(api.add_daily_asset).not.toHaveBeenCalled()
})
test('paired model cards show three targets and execution evidence',async()=>{
 const initial=(await api.agent_status()).data; initial.config.api_key_configured=true
 api.agent_status.mockImplementation(async()=>({ok:true,data:initial}))
 api.analyze_daily_agents=vi.fn(async()=>{
 initial.history=['comprehensive','chanlun'].map((mode,i)=>({id:String(i),agent_version:'agent-v2',analysis_status:'completed',strategy_mode:mode,strategy_name:'策略'+(i+1),model:'deepseek-chat',created_at:new Date().toISOString(),snapshot:{symbol:'BTCUSDT',timeframe:'15m',candle_time:new Date().toISOString()},signal:{action:'LONG',execution:'CONDITIONAL',trigger:'收盘突破101后回踩入场',entry_low:100,entry_high:101,stop_loss:98,tp1:105,tp2:108,tp3:112,confidence:85,risk_status:'PASSED',reason:'模型结构分析依据',invalid_if:'跌破98',validation_notes:[]},trace:[{stage:'review',status:'completed',summary:'证据核查通过'}],push:{sent:false,message:'手动生成不推送'}}))
 return {ok:true,data:{results:initial.history}}
 })
 render(<App/>);await screen.findByRole('heading',{name:'合约策略卡片'})
 await waitFor(()=>expect((screen.getByRole('button',{name:'生成两套策略'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'生成两套策略'}))
 await screen.findAllByText('112')
 expect(api.analyze_daily_agents).toHaveBeenCalledWith({watch_item:{symbol:'BTCUSDT',timeframe:'15m'}})
 expect(screen.getAllByText('做多')).toHaveLength(2)
 expect(screen.getAllByText('条件策略 · 触发后执行')).toHaveLength(2)
 fireEvent.click(screen.getAllByRole('button',{name:'查看 Agent 依据与执行记录'})[0])
 expect(await screen.findByText('证据核查通过')).toBeTruthy()
})
test('agent config preserves blank keys, separates modes and previews without start', async () => {
 const config = {provider:'deepseek',model:'deepseek-chat',strategy_mode:'comprehensive',poll_seconds:30,push_enabled:false,api_key_configured:true,feishu_configured:false,watchlist:[{symbol:'BTCUSDT',timeframe:'15m'}],risk:{account_balance:1000,risk_per_trade_pct:1,leverage:3,max_margin_pct:20,min_confidence:60,min_risk_reward:1.5,max_stop_pct:3,max_atr_pct:3.2}}
 const status = {running:false,config,history:[],logs:[]}
 api.agent_status = vi.fn(async()=>({ok:true,data:status}))
 api.configure_agent = vi.fn(async payload=>{Object.assign(config,payload);return {ok:true,data:status}})
 api.test_agent_model = vi.fn(async payload=>{Object.assign(config,payload);return {ok:true,data:{message:'真实连接成功'}}})
 render(<AgentWorkbench />)
 await screen.findByRole('heading',{name:'当日策略 Agent'})
 fireEvent.click(screen.getByRole('button',{name:/02.*缠论体系/}))
 fireEvent.click(screen.getByRole('button',{name:'保存配置'}))
 await waitFor(()=>expect(api.configure_agent).toHaveBeenCalled())
 expect(api.configure_agent.mock.calls[0][0].strategy_mode).toBe('chanlun')
 expect(api.configure_agent.mock.calls[0][0]).not.toHaveProperty('api_key')
 await screen.findByText(/配置已保存；/)
 fireEvent.change(screen.getByLabelText('API Key'),{target:{value:'test-secret'}})
 expect(screen.getByLabelText('API Key').getAttribute('type')).toBe('password')
 fireEvent.click(screen.getByRole('button',{name:'测试模型连接（一次 API 调用）'}))
 await screen.findByText('真实连接成功')
 expect(api.test_agent_model.mock.calls[0][0].api_key).toBe('test-secret')
 expect((screen.getByLabelText('API Key') as HTMLInputElement).value).toBe('')
})
async function ready() { render(<App/>); await screen.findByRole('heading',{name:'合约策略卡片'}) }
async function nav(name: string) { fireEvent.click(within(screen.getByRole('navigation')).getByRole('button',{name})); await waitFor(()=>expect(location.hash).toContain(name==='策略库'?'library':name==='设置'?'settings':'research')) }
test('knowledge base answers with timestamped evidence', async () => {
 await ready(); fireEvent.click(within(screen.getByRole('navigation')).getByRole('button',{name:'缠论知识库'}))
 expect(await screen.findByText('索引健康')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('向知识库提问'),{target:{value:'顶分型是什么'}})
 fireEvent.click(screen.getByRole('button',{name:'查询'}))
 expect(await screen.findByText('证据充分')).toBeTruthy()
 expect(screen.getByRole('link',{name:/12:30/}).getAttribute('href')).toContain('t=750s')
})
test('macro calendar shows Beijing time, values and market risk scenarios', async()=>{
 await ready(); fireEvent.click(within(screen.getByRole('navigation')).getByRole('button',{name:'宏观日历'}))
 expect(await screen.findByRole('heading',{name:'美国宏观与财报日历'})).toBeTruthy()
 expect(screen.getByText('CPI 消费者通胀')).toBeTruthy()
 expect(screen.getByText('3.1%')).toBeTruthy()
 expect(screen.getByText(/高于预期通常推升利率预期/)).toBeTruthy()
 expect(screen.getByRole('link',{name:/CPI 官方发布时间/}).getAttribute('href')).toContain('bls.gov')
})
test('library details, rename and confirmed deletion update visible list', async () => {
 await ready(); await nav('策略库')
 fireEvent.click(screen.getByLabelText('EMA策略 更多操作'))
 fireEvent.click(screen.getByRole('button',{name:'详细信息'}))
 expect(await screen.findByText('策略详情说明')).toBeTruthy()
 fireEvent.click(screen.getAllByRole('button',{name:'关闭'})[0])
 fireEvent.click(screen.getByRole('button',{name:'重命名 EMA策略'}))
 fireEvent.change(screen.getByLabelText('策略名称'),{target:{value:'新策略名'}})
 fireEvent.click(screen.getByRole('button',{name:'保存'}))
 expect(await screen.findByRole('heading',{name:'新策略名'})).toBeTruthy()
 fireEvent.click(screen.getByLabelText('新策略名 更多操作'))
 fireEvent.click(screen.getByRole('button',{name:'删除',exact:true}))
 fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'删除',exact:true}))
 expect(await screen.findByText('策略库为空')).toBeTruthy()
})
test('appearance upload changes brand and restores the requested default', async () => {
 await ready(); await nav('设置')
 const input = document.querySelector('input[type=file]')!
 fireEvent.change(input,{target:{files:[new File(['test-image'],'icon.png',{type:'image/png'})]}})
 await screen.findByText('已保存，重新打开后仍会保留')
 expect(document.querySelector('.brand img')?.getAttribute('src')).toContain('data:image/png;base64,')
 fireEvent.click(screen.getAllByRole('button',{name:'恢复默认'})[0])
 await waitFor(()=>expect(document.querySelector('.brand img')?.getAttribute('src')).toBe('assets/custom-icon.jpg'))
})
