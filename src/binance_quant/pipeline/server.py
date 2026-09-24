from __future__ import annotations

"""FastAPI + WebSocket 服务层(系统对外唯一出口)。

- 后端是唯一状态源:快照、信号、卡片、执行记录都在这里;
- 事件通过 /ws 单向下推(新卡片、执行、快照刷新);
- React 以外的前端壳(当前:内嵌监控页)只是投影,可随意替换。
"""

import json
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import requests
from binance_quant.agent_engine import build_agent_market_catalog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .cards import StrategyCard
from .channels import (
    CHANNEL_DEEP,
    CHANNEL_FAST,
    CHANNEL_STANDARD,
    ChannelOutput,
    suggest_channel,
    run_deep_channel,
    run_fast_channel,
    run_standard_channel,
)
from .chanlun_lite import STRATEGY as CHANLUN_STRATEGY
from .hardgate import GateConfig, HardGate
from .liquidation import TruthFeed, build_profile
from .llm import LLMProvider, RuleFallbackLLM
from .memory import DecisionMemory
from .ordergen import OrderPlanConfig, PaperExecutor
from .registry import StrategyRegistry, StrategySignal
from .snapshot import TechnicalSnapshot, build_snapshot

BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_OI = "https://fapi.binance.com/fapi/v1/openInterest"

DEFAULT_MEMORY_DIR = (
    Path.home() / "Library" / "Application Support" / "Binance Quant" / "pipeline"
)


# ---------------------------------------------------------------- data feed


class BinancePublicFeed:
    """公开 REST 数据源(K线 + 持仓量);不下载任何私密数据,不需 Key。"""

    def __init__(
        self,
        session: requests.Session | None = None,
        klines_url: str = BINANCE_KLINES,
        oi_url: str = BINANCE_OI,
    ) -> None:
        self.session = session or requests.Session()
        self.klines_url = klines_url
        self.oi_url = oi_url

    def klines(self, symbol: str, interval: str, limit: int = 240) -> pd.DataFrame:
        resp = self.session.get(
            self.klines_url,
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"空K线:{symbol} {interval}")
        frame = pd.DataFrame(
            {
                "open": [float(r[1]) for r in rows],
                "high": [float(r[2]) for r in rows],
                "low": [float(r[3]) for r in rows],
                "close": [float(r[4]) for r in rows],
                "volume": [float(r[5]) for r in rows],
            },
            index=pd.to_datetime([int(r[0]) for r in rows], unit="ms", utc=True),
        )
        return frame

    def open_interest_usdt(self, symbol: str) -> float:
        resp = self.session.get(self.oi_url, params={"symbol": symbol}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        oi = float(payload.get("openInterest") or 0.0)
        mark = None
        try:
            mark = float(payload["lastPrice"])
        except (KeyError, ValueError, TypeError):
            pass
        if mark is None:
            response = self.session.get(self.oi_url.replace('/openInterest', '/premiumIndex'), params={'symbol': symbol}, timeout=10)
            response.raise_for_status()
            mark = float(response.json()['markPrice'])
        return oi * mark

    def catalog(self) -> list[dict[str, Any]]:
        response = self.session.get(self.klines_url.replace('/klines', '/exchangeInfo'), timeout=15)
        response.raise_for_status()
        return build_agent_market_catalog(response.json())


# ---------------------------------------------------------------- event hub


@dataclass
class Event:
    topic: str
    data: dict[str, Any]
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "data": self.data, "ts": self.ts}


class EventHub:
    """线程安全的内存事件总线:core 线程 put,WS 消费。"""

    def __init__(self, maxsize: int = 200) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: Event) -> int:
        payload = event.to_dict()
        dropped = 0
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dropped += 1
        return dropped

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


# ---------------------------------------------------------------- runtime


@dataclass
class RuntimeConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    default_interval: str = "15m"
    kline_limit: int = 240
    llm_provider: LLMProvider | None = None   # 缺省=规则共识兜底
    llm_available: bool = False
    gate: GateConfig = field(default_factory=GateConfig)
    plan: OrderPlanConfig = field(default_factory=OrderPlanConfig)
    memory_path: Path | None = None
    max_cards: int = 50
    fetch_liquidation_truth: bool = False     # 线上才开的 WS 实测源


class PipelineRuntime:
    """把五层架构装配成一个受管对象;测试可注入假数据源。"""

    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        data_feed: Any = None,
        liquidation_feed: TruthFeed | None = None,
        macro_hook: Callable[[str], str] | None = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        self.feed = data_feed or BinancePublicFeed()
        self.macro_hook = macro_hook
        self.hub = EventHub()
        self.gate = HardGate(self.config.gate)
        self.executor = PaperExecutor()
        self.registry = StrategyRegistry()
        self.registry.register_strategy(CHANLUN_STRATEGY)
        self.liquidation_feed = liquidation_feed or TruthFeed()
        if self.config.fetch_liquidation_truth:
            self.liquidation_feed.start()
        memory_path = self.config.memory_path or (DEFAULT_MEMORY_DIR / "decisions.jsonl")
        self.memory = DecisionMemory(memory_path)
        self._cards: list[StrategyCard] = []
        self._lock = threading.Lock()
        self._snapshots: dict[str, TechnicalSnapshot] = {}
        self._mods_lock = threading.Lock()
        self._catalog_groups: list[dict[str, Any]] = []

    def catalog(self, refresh: bool = False) -> dict[str, Any]:
        with self._mods_lock:
            if hasattr(self.feed, 'catalog') and (refresh or not self._catalog_groups):
                groups = self.feed.catalog()
                if not groups:
                    raise ValueError('Binance 合约目录为空，请稍后刷新')
                self._catalog_groups = groups
                self.config.symbols = tuple(item['symbol'] for group in groups for item in group['items'])
            return {'symbols': list(self.config.symbols), 'groups': self._catalog_groups,
                    'default_interval': self.config.default_interval, 'status': self.status()}

    # ---- runtime state helpers ----

    def add_card(self, card: StrategyCard) -> None:
        with self._lock:
            self._cards.append(card)
            self._cards = self._cards[-self.config.max_cards :]
        self.hub.publish(Event(topic="card", data=card.to_dict()))

    def cards(self, limit: int = 20) -> list[StrategyCard]:
        with self._lock:
            return list(self._cards[-limit:])

    def fills(self):
        return list(self.executor.filled)

    def last_snapshot(self, symbol: str) -> TechnicalSnapshot | None:
        return self._snapshots.get(symbol)

    # ---- pipeline ----

    def snapshot(self, symbol: str, interval: Optional[str] = None) -> TechnicalSnapshot:
        interval = interval or self.config.default_interval
        frame = self.feed.klines(symbol, interval, self.config.kline_limit)
        aux: dict[str, pd.DataFrame] = {}
        for other in ("5m", "1h"):
            if other != interval:
                try:
                    aux[other] = self.feed.klines(symbol, other, self.config.kline_limit)
                except Exception:  # noqa: BLE001 — 级联失败不阻塞主周期
                    continue
        self._snapshots[symbol] = build_snapshot(symbol, interval, frame, frames=aux)
        return self._snapshots[symbol]

    def _llm(self, snapshot: TechnicalSnapshot, report) -> LLMProvider:
        return self.config.llm_provider or RuleFallbackLLM(snapshot, report)

    def _strategy_report(self, snapshot: TechnicalSnapshot, frame: pd.DataFrame):
        return self.registry.evaluate(
            snapshot.symbol, frame, key_level=snapshot.swing_high
        )

    def _liquidation_evidence(self, snapshot: TechnicalSnapshot) -> str:
        try:
            oi = self.feed.open_interest_usdt(snapshot.symbol) \
                if hasattr(self.feed, "open_interest_usdt") else 0.0
        except Exception:  # noqa: BLE001
            oi = 0.0
        profile = build_profile(
            snapshot.symbol, snapshot.close, oi,
            swing_high=snapshot.swing_high, swing_low=snapshot.swing_low,
            feed=self.liquidation_feed,
        )
        return profile.evidence_text()

    def _macro_evidence(self, symbol: str) -> str:
        if self.macro_hook:
            try:
                return self.macro_hook(symbol)
            except Exception as exc:  # noqa: BLE001
                return f"宏观数据获取失败:{exc}"
        return "未配置宏观日历数据源(macro_hook 未注入)。"

    def run(self, symbol: str, channel: str = "auto") -> dict[str, Any]:
        frame = self.feed.klines(symbol, self.config.default_interval,
                                 self.config.kline_limit)
        snapshot = self.snapshot(symbol)
        report = self._strategy_report(snapshot, frame)
        llm = self._llm(snapshot, report)
        evidence_extras = {
            "liquidation": self._liquidation_evidence(snapshot),
            "macro": self._macro_evidence(symbol),
        }
        chosen = channel if channel in (CHANNEL_FAST, CHANNEL_STANDARD, CHANNEL_DEEP) \
            else suggest_channel(report, llm_available=self.config.llm_available)

        if chosen == CHANNEL_FAST:
            output = run_fast_channel(snapshot, report, gate=self.gate,
                                      executor=self.executor,
                                      plan_config=self.config.plan)
        elif chosen == CHANNEL_STANDARD:
            output = run_standard_channel(snapshot, report, llm=llm, gate=self.gate,
                                          executor=self.executor, memory=self.memory,
                                          evidence_extras=evidence_extras)
        else:
            output = run_deep_channel(snapshot, report, llm=llm, gate=self.gate,
                                      executor=self.executor, memory=self.memory,
                                      evidence_extras=evidence_extras)
        if output.card is not None:
            self.add_card(output.card)
        payload = output.to_dict()
        payload["symbol"] = symbol
        payload["chosen_channel"] = chosen
        payload['strategy_report'] = report.to_dict()
        return payload

    def status(self) -> dict[str, Any]:
        return {
            "symbols": list(self.config.symbols),
            "subscribers": self.hub.subscriber_count(),
            "filled": len(self.executor.filled),
            "cards": len(self._cards),
            "llm": "provider" if self.config.llm_provider else "rule_fallback",
        }


# ---------------------------------------------------------------- dashboard


DASH_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>智能交易工作台 · 监控</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e5e8;--fg:#1f2329;--mut:#7a828c;--blue:#185fa5;--green:#1d9e75;--red:#d85a30;--amber:#ba7517}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding:18px;max-width:1200px;margin:0 auto}
h1{font-size:17px;font-weight:600;margin-bottom:14px}
h2{font-size:13px;font-weight:600;color:var(--mut);margin-bottom:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}
.row{display:flex;gap:12px;flex-wrap:wrap}
.row>.card{flex:1;min-width:320px}
button,select{font:inherit;padding:6px 12px;border:1px solid var(--line);background:#fff;border-radius:8px;cursor:pointer}
button.primary{background:var(--blue);color:#fff;border-color:var(--blue)}
button:disabled{opacity:.5;cursor:default}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}
.kv{background:#f8f9fb;border:1px solid var(--line);border-radius:8px;padding:8px}
.kv b{display:block;font-size:11px;color:var(--mut);font-weight:500;margin-bottom:2px}
.kv span{font-size:13px;font-variant-numeric:tabular-nums}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;font-weight:600}
.tag.long{color:var(--green);background:#e1f5ee}
.tag.short{color:var(--red);background:#faece7}
.tag.hold{color:var(--mut);background:#eef0f2}
.tag.gate-ok{color:var(--green);background:#e1f5ee}
.tag.gate-no{color:var(--red);background:#faece7}
.card-item{border-left:3px solid var(--line);padding:10px 12px;margin:8px 0;border-radius:6px;background:#fdfdfe}
.card-item.buy{border-left-color:var(--green)}
.card-item.sell{border-left-color:var(--red)}
.card-item.hold{border-left-color:var(--mut)}
pre{background:#0f1113;color:#d6dce2;font:12px/1.5 ui-monospace,monospace;border-radius:8px;padding:10px;max-height:180px;overflow:auto}
.log{font:12px/1.5 ui-monospace,monospace;color:#4a5058;max-height:220px;overflow:auto}
.log div{padding:2px 0;border-bottom:1px dashed var(--line)}
.mut{color:var(--mut)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{color:var(--mut);text-align:left;font-weight:500;padding:4px;border-bottom:1px solid var(--line)}
td{padding:4px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
</style></head><body>
<h1>智能策略工作台 · 三通道分析</h1>
<p class="mut">Binance USDT 永续（含美股 / ETF 合约） · 模拟执行 · 未配置模型时使用规则共识</p>

<div class="card">
  <h2>运行</h2>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <select id="market" aria-label="市场"></select>
    <select id="symbol" aria-label="合约"></select>
    <button id="catalog">刷新合约目录</button>
    <select id="channel">
      <option value="auto">自动分级</option><option value="fast">快速通道</option>
      <option value="standard">标准通道</option><option value="deep">深度通道</option>
    </select>
    <button id="run" class="primary">执行一轮</button>
    <button id="reload">刷新快照</button>
    <span id="st" class="tag hold">连接中…</span>
  </div>
</div>

<div class="row">
  <div class="card"><h2>技术快照</h2><div id="snap" class="grid"><span class="mut">暂无</span></div></div>
  <div class="card"><h2>策略信号(strategy_report)</h2><div id="signals"><span class="mut">暂无</span></div></div>
</div>

<div class="row">
  <div class="card"><h2>策略卡片流</h2><div id="cards"><span class="mut">暂无</span></div></div>
  <div class="card"><h2>事件日志(WS)</h2><div id="log" class="log"></div></div>
</div>

<div class="card"><h2>执行记录(paper)</h2><div id="fills"><span class="mut">暂无</span></div></div>
<div class="card"><h2>分析详情 / 辩论 / 风控</h2><pre id="details">执行一轮后显示</pre></div>
<div class="card"><h2>决策记忆</h2><pre id="memory">暂无</pre></div>

<script>
const $=s=>document.querySelector(s);
let symbols=[],ws=null;
let groups=[];
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw Error(data.error||`HTTP ${r.status}`);return data}
async function catalog(){
 try{
 const cat=await api('/api/catalog?refresh=true');symbols=cat.symbols;groups=cat.groups;
 if(!groups.length)groups=[{id:'all',name:'合约',items:symbols.map(symbol=>({symbol,label:symbol}))}];
 $('#market').innerHTML=groups.map(g=>`<option value="${esc(g.id)}">${esc(g.name)} (${g.items.length})</option>`).join('');
 if(groups.some(g=>g.id==='us_equity_perpetual'))$('#market').value='us_equity_perpetual';
 pickMarket();
 }catch(e){log(e.message);$('#snap').textContent=e.message}
}
function pickMarket(){const g=groups.find(g=>g.id===$('#market').value);$('#symbol').innerHTML=(g?.items||[]).map(i=>`<option value="${esc(i.symbol)}">${esc(i.label)} · ${esc(i.symbol)}</option>`).join('');if(g?.items.some(i=>i.symbol==='SNDKUSDT'))$('#symbol').value='SNDKUSDT';refresh().catch(e=>log(e.message))}
const fmt=(v,d=4)=>(v===undefined||v===null)?"—":(typeof v==="number"?v.toLocaleString(undefined,{maximumFractionDigits:d}):v);
function tag(dir){return `<span class="tag ${dir==="long"?"long":dir==="short"?"short":"hold"}">${dir==="long"?"做多":dir==="short"?"做空":"观望"}</span>`}
function log(msg){const d=document.createElement("div");d.textContent=`[${new Date().toLocaleTimeString()}] ${msg}`;$("#log").prepend(d)}
async function boot(){
  connect();
  $('#market').onchange=pickMarket;$('#symbol').onchange=()=>refresh().catch(e=>log(e.message));$('#catalog').onclick=catalog;
  $("#run").onclick=run;$("#reload").onclick=()=>refresh().catch(e=>log(e.message));
  await catalog();
}
async function refresh(){
  const sym=$("#symbol").value||symbols[0];
  if(!sym)return;
  const snap=await (await fetch(`/api/snapshot?symbol=${sym}`)).json();
  if(snap.snapshot_hash)renderSnap(snap);else $("#snap").textContent=snap.error||"快照不可用";
  const cards=await api('/api/cards');$('#cards').innerHTML=cards.cards.length?cards.cards.slice().reverse().map(renderCard).join(''):'暂无';
  const memory=await api('/api/decisions?symbol='+encodeURIComponent(sym));$('#memory').textContent=JSON.stringify(memory,null,2);
  const fills=await (await fetch("/api/executor/fills")).json();
  $("#fills").innerHTML=fills.fills.length?("<table><tr><th>时间</th><th>标的</th><th>方向</th><th>入场</th><th>止损</th><th>TP</th><th>仓位</th></tr>"
    +fills.fills.map(f=>`<tr><td>${new Date(f.created_at*1000).toLocaleTimeString()}</td><td>${f.symbol}</td><td>${f.direction}</td><td>${fmt(f.entry)}</td><td>${fmt(f.stop_loss)}</td><td>${f.tp.map(t=>fmt(t.price)).join("/")}</td><td>${fmt(f.size)}U×${f.leverage}</td></tr>`).join("")+"</table>"):'<span class="mut">暂无</span>';
}
function renderSnap(s){
  $("#snap").innerHTML=[
    ["现价",fmt(s.close)],["趋势",s.trend+" ("+s.trend_age_bars+"根)"],
    ["RSI14",fmt(s.rsi14,1)],["ATR14",fmt(s.atr14)],
    ["EMA7",fmt(s.ema7)],["EMA25",fmt(s.ema25)],["EMA100",fmt(s.ema100)],
    ["VWAP",fmt(s.vwap)],["量比",fmt(s.volume_ratio,2)],["%B",fmt(s.bb_percent_b,2)],
    ["摆动高",fmt(s.swing_high)],["摆动低",fmt(s.swing_low)],
  ].map(([k,v])=>`<div class="kv"><b>${k}</b><span>${v}</span></div>`).join("");
}
function renderCard(c){
  const dir=c.ticket?c.ticket.direction:"flat";
  const gate=c.gate?(c.gate.passed?'<span class="tag gate-ok">闸门通过</span>':'<span class="tag gate-no">闸门拦截</span>'):"";
  const tps=c.ticket?c.ticket.tp.map(t=>`${fmt(t.price)}(${Math.round(t.fraction*100)}%)`).join(" / "):"—";
  return `<div class="card-item ${dir==="long"?"buy":dir==="short"?"sell":"hold"}">
    <div><b>${c.symbol}</b> ${tag(dir)} <span class="tag hold">${c.rating}</span> <span class="mut">${c.channel}</span> ${gate}</div>
    <div class="mut" style="font-size:12px;margin:4px 0">${c.ticket?`入场 ${fmt(c.ticket.entry)} · 止损 ${fmt(c.ticket.stop_loss)} · TP ${tps} · ${fmt(c.ticket.size)}U×${c.ticket.leverage}`:"观望"} · 有效至 ${new Date(c.valid_until*1000).toLocaleTimeString()}</div>
    ${c.evidence&&c.evidence.length?`<pre>${esc(c.evidence.join("\\n"))}</pre>`:""}
    ${c.risk_notes?.length?`<pre>${esc(c.risk_notes.join("\\n"))}</pre>`:""}
  </div>`;
}
async function run(){
  const btn=$("#run");btn.disabled=true;
  try{
    const res=await (await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({symbol:$("#symbol").value,channel:$("#channel").value})})).json();
    if(res.error)throw Error(res.error);
    $('#details').textContent=JSON.stringify(res,null,2);
    if(res.strategy_report)$('#signals').textContent=res.strategy_report.signals.map(s=>`${s.name}：${s.label} (${Math.round(s.confidence*100)}%) ${s.note}`).join(' / ');
    log(`run → ${res.chosen_channel}:${res.status}`);
    const cards=await (await fetch("/api/cards")).json();
    $("#cards").innerHTML=cards.cards.length?cards.cards.map(renderCard).join(""):'<span class="mut">暂无</span>';
    if(res.extras&&res.extras.cycle)renderSignals(res.extras.cycle);
    refresh();
  }catch(e){log("run 失败:"+e)}
  finally{btn.disabled=false}
}
function renderSignals(c){/*占位:后续把 signals 面板接入*/}
function connect(){
  const proto=location.protocol==="https:"?"wss":"ws";
  ws=new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen=()=>{$("#st").textContent="本地服务在线";$("#st").className="tag gate-ok"};
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.topic==="card"){log(`卡片 ${m.data.symbol} ${m.data.direction||"观望"}(${m.data.channel})`);run&&refresh()}else log(m.topic)};
  ws.onclose=()=>{$("#st").textContent="WS 断开,重连中";$("#st").className="tag gate-no";setTimeout(connect,2000)};
}
boot();
</script></body></html>
"""


# ---------------------------------------------------------------- app


def create_app(
    config: RuntimeConfig | None = None,
    *,
    data_feed: Any = None,
    macro_hook: Callable[[str], str] | None = None,
    liquidation_feed: TruthFeed | None = None,
) -> FastAPI:
    runtime = PipelineRuntime(config, data_feed=data_feed,
                              macro_hook=macro_hook,
                              liquidation_feed=liquidation_feed)
    app = FastAPI(title="智能交易工作台 Pipeline", version="0.1.0")
    app.state.runtime = runtime

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return DASH_HTML

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True, "ts": time.time(), "status": runtime.status()}

    @app.get("/api/catalog")
    async def catalog(refresh: bool = False) -> JSONResponse:
        try:
            return JSONResponse(await run_in_threadpool(runtime.catalog, refresh))
        except Exception as exc:
            return JSONResponse({'error': '合约目录获取失败：' + str(exc)}, status_code=503)

    @app.get("/api/snapshot")
    async def snapshot(symbol: str, interval: Optional[str] = None) -> JSONResponse:
        try:
            snap = await run_in_threadpool(runtime.snapshot, symbol, interval)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(snap.to_dict())

    @app.post("/api/run")
    async def run(payload: dict) -> JSONResponse:
        symbol = str(payload.get("symbol", "")).upper()
        channel = str(payload.get("channel", "auto"))
        if symbol not in runtime.config.symbols:
            return JSONResponse({"error": f"未知标的 {symbol}"}, status_code=400)
        try:
            result = await run_in_threadpool(runtime.run, symbol, channel)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(result)

    @app.get("/api/cards")
    async def cards(limit: int = 20) -> dict:
        return {"cards": [c.to_dict() for c in runtime.cards(limit)]}

    @app.get("/api/executor/fills")
    async def fills() -> dict:
        return {"fills": [t.to_dict() for t in runtime.fills()]}

    @app.get("/api/decisions")
    async def decisions(symbol: str, limit: int = 5) -> dict:
        return {
            "past_context": runtime.memory.past_context(symbol, limit),
            "recent": runtime.memory.recent(symbol, limit),
            "outcomes": runtime.memory.outcomes(symbol, limit),
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        import asyncio

        await websocket.accept()
        q = runtime.hub.subscribe()
        stop = threading.Event()

        def _blocking_get() -> Any:
            try:
                return q.get(timeout=0.5)
            except queue.Empty:
                return None

        async def _sender() -> None:
            try:
                while not stop.is_set():
                    message = await run_in_threadpool(_blocking_get)
                    if message is None:
                        continue
                    await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                pass

        send_task = asyncio.create_task(_sender())
        try:
            while True:
                # 客户端通常不主动发消息;只在断开时收到异常为止
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            stop.set()
            runtime.hub.unsubscribe(q)
            send_task.cancel()

    return app


def serve(config: RuntimeConfig | None = None, host: str = "127.0.0.1",
          port: int = 8788) -> None:  # pragma: no cover — 线上启动入口
    import uvicorn

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    serve()
