from __future__ import annotations

"""清算流动性层(方案A:不付费的真实数据).

两条数据源:
1. 真实强平事件:Binance 公开 WS `!forceOrder@arr`,按价格分桶累积成
   "事实校准层"(后台线程懒接入,websocket-client 缺失时自动静默降级);
2. 估算模型:持仓量(OI)× 杠杆分层(5/10/25/50/100x)在当前摆动区间内
   估算清算密集价位(明确标注为"模型估算")。

统一输出 LiquidationProfile,evidence_text() 直接喂给证据层分析师。
"""

import json
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

TRUTH_WINDOW_SECONDS = 24 * 3600  # 事实层保留最近 24h 真实强平
LEVERAGE_TIERS = (5.0, 10.0, 25.0, 50.0, 100.0)


@dataclass(frozen=True)
class LiquidationEvent:
    side: str          # LONG 被平(卖) / SHORT 被平(买)
    price: float
    amount_usdt: float
    ts: float


class TruthFeed:
    """真实强平事件收集器(纯内存,后台线程接 Binance WS)。

    fetcher 可注入以便测试/离线:fetcher(callback) -> None,回调收到标准化事件。
    """

    WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"

    def __init__(self, fetcher: Any = None) -> None:
        self._events: deque[LiquidationEvent] = deque()
        self._lock = threading.Lock()
        self._fetcher = fetcher
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.source_label = "binance_ws"

    # ---- 注入事件(离线/测试与线上共用入口) ----
    def ingest(self, side: str, price: float, amount_usdt: float, ts: float | None = None) -> None:
        amount = float(amount_usdt)
        if amount <= 0:
            return
        side = side.upper()
        if side not in ("LONG", "SHORT"):
            raise ValueError(f"非法清算方向 {side}")
        with self._lock:
            self._events.append(
                LiquidationEvent(side=side, price=float(price), amount_usdt=amount,
                                 ts=ts or time.time())
            )
            self._trim_locked()

    def _trim_locked(self, now: float | None = None) -> None:
        cutoff = (now or time.time()) - TRUTH_WINDOW_SECONDS
        while self._events and self._events[0].ts < cutoff:
            self._events.popleft()

    def window(self, since_ts: float | None = None, around: float | None = None,
               band: float = 0.0) -> list[LiquidationEvent]:
        cutoff = since_ts or (time.time() - TRUTH_WINDOW_SECONDS)
        with self._lock:
            self._trim_locked()
            rows = [e for e in self._events if e.ts >= cutoff]
        if around is not None and band > 0:
            low, high = around * (1 - band), around * (1 + band)
            rows = [e for e in rows if low <= e.price <= high]
        return sorted(rows, key=lambda e: e.ts)

    def total(self, side: str | None = None, around: float | None = None,
              band: float = 0.0) -> float:
        return sum(e.amount_usdt for e in self.window(around=around, band=band)
                   if side is None or e.side == side.upper())

    # ---- 线上采集(可选) ----
    @staticmethod
    def parse_force_order(payload: dict[str, Any]) -> LiquidationEvent | None:
        order = payload.get("o") if isinstance(payload, dict) else None
        if not order:
            return None
        side_raw = str(order.get("side", "")).upper()
        amount = 0.0
        price = float(order.get("p") or 0.0)
        qty = float(order.get("q") or order.get("z") or 0.0)
        price_last = float(order.get("ap") or price)
        amount = price_last * qty
        side = "SHORT" if side_raw == "BUY" else "LONG"  # BUY=接强平卖单(平多)
        ts_ms = float(order.get("T") or payload.get("E") or 0.0)
        return LiquidationEvent(side=side, price=price_last, amount_usdt=amount,
                                ts=ts_ms / 1000.0 if ts_ms else time.time())

    def start(self, url: str | None = None) -> None:
        """后台接入真实 WS。websocket-client 不存在时静默关闭(不抛异常)。"""
        if self._thread and self._thread.is_alive():
            return
        try:
            import websocket  # type: ignore
        except ImportError:
            self.source_label = "binance_ws_unavailable"
            return

        url = url or self.WS_URL
        self._stop.clear()

        def _run() -> None:
            def _message(_ws: Any, raw: str) -> None:
                try:
                    event = self.parse_force_order(json.loads(raw))
                except (ValueError, TypeError, json.JSONDecodeError):
                    return
                if event:
                    self.ingest(event.side, event.price, event.amount_usdt, event.ts)

            while not self._stop.is_set():
                try:
                    ws = websocket.create_connection(url, timeout=30)
                    while not self._stop.is_set():
                        _message(ws, ws.recv())
                except Exception:  # noqa: BLE001 — 断线静默重连
                    if self._stop.wait(5.0):
                        break

        self._thread = threading.Thread(target=_run, daemon=True,
                                        name="liquidation-truth-feed")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


@dataclass(frozen=True)
class Cluster:
    price: float
    side: str           # LONG / SHORT 清算密集(多/空燃料)
    estimated_usdt: float
    driver: str         # truth(ws实测) / estimate(模型) / both


@dataclass
class LiquidationProfile:
    symbol: str
    mark_price: float
    open_interest: float
    clusters: list[Cluster]
    truth_long_usdt: float
    truth_short_usdt: float
    truth_events: int
    model_note: str
    as_of: float = field(default_factory=time.time)

    def size_sec(self, key: str) -> float:
        return sum(c.estimated_usdt for c in self.clusters if c.side == key)

    def evidence_text(self) -> str:
        lines = [
            f"标的:{self.symbol}",
            f"数据时点 {time.strftime('%Y-%m-%d %H:%M', time.localtime(self.as_of))} · "
            f"现价 {self.mark_price:g} · 持仓量 {self.open_interest:g} USD",
            f"近24h真实强平(WS 实测):多 {self.truth_long_usdt:,.0f} / "
            f"空 {self.truth_short_usdt:,.0f} USD,共 {self.truth_events} 笔",
        ]
        if not self.clusters:
            lines.append("清算密集区:估算模型未识别显著档位。")
        else:
            lines.append("清算密集区(模型估算):")
            for cluster in sorted(self.clusters, key=lambda c: -c.estimated_usdt)[:6]:
                gap = (cluster.price / self.mark_price - 1) * 100 if self.mark_price else 0
                side = "多头燃料(价格下跌引爆)" if cluster.side == "LONG" else "空头燃料(价格上涨引爆)"
                lines.append(
                    f"  {cluster.price:g}({gap:+.1f}%) {side} ~{cluster.estimated_usdt:,.0f} USD [{cluster.driver}]"
                )
        lines.append(f"备注:{self.model_note}")
        return "\n".join(lines)


def _bin_index(price: float, ref: float, step: float) -> int:
    return int(math.floor((price - ref) / step)) if step > 0 else 0


def estimate_clusters(
    mark_price: float,
    open_interest_usdt: float,
    *,
    swing_high: float,
    swing_low: float,
    volume_profile: dict[float, float] | None = None,
    leverage_tiers: tuple[float, ...] = LEVERAGE_TIERS,
    max_clusters: int = 8,
) -> list[Cluster]:
    """估算清算密集价位。

    模型:摆动区间内按(optional)成交量分布摊开放仓,不同杠杆仓位的
    强平价 = 入场价 × (1 ∓ 1/杠杆),ITM 的清算按分桶累加。
    """
    if open_interest_usdt <= 0 or mark_price <= 0:
        return []
    swing_high = max(float(swing_high), mark_price, 1e-12)
    swing_low = max(float(swing_low), 1e-12)
    if swing_high <= swing_low:
        swing_high, swing_low = swing_low * 1.001, swing_high
    span = swing_high - swing_low

    bins = 40
    step = span / bins
    ref = swing_low

    # 价位权重:给成交量分布(若无则统一)
    weights: list[float] = [1.0] * bins
    if volume_profile:
        for i in range(bins):
            anchor = ref + (i + 0.5) * step
            weights[i] = float(volume_profile.get(round(anchor, 6), 0.0)) or 1e-12

    totals: dict[int, float] = {}
    sides: dict[int, str] = {}
    for lev in leverage_tiers:
        move = 1.0 / lev
        for i, weight in enumerate(weights):
            entry = ref + (i + 0.5) * step
            size = open_interest_usdt * weight / sum(weights) / len(leverage_tiers)
            liq_long = entry * (1 - move)     # 多仓清算价(向下)
            liq_short = entry * (1 + move)    # 空仓清算价(向上)
            if liq_long < mark_price <= entry * (1 + 2 * move * 4):  # 只关心近侧
                idx = _bin_index(liq_long, ref, step)
                totals[idx] = totals.get(idx, 0.0) + size
                sides.setdefault(idx, "LONG")
            if liq_short > mark_price:
                idx = _bin_index(liq_short, ref, step)
                totals[idx] = totals.get(idx, 0.0) + size
                sides.setdefault(idx, "SHORT")

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:max_clusters]
    clusters = []
    for idx, size in ranked:
        price = ref + (idx + 0.5) * step
        clusters.append(Cluster(
            price=round(price, 8),
            side=sides.get(idx, "LONG"),
            estimated_usdt=round(size, 2),
            driver="estimate",
        ))
    return clusters


def merge_truth(profile_estimate: list[Cluster], feed: TruthFeed | None,
                *, mark_price: float, band: float = 0.05) -> list[Cluster]:
    """真实强平与模型融合:近测点被实测命中时升级 driver→both/truth。"""
    if feed is None or not feed.window():
        return profile_estimate
    merged: list[Cluster] = []
    for cluster in profile_estimate:
        truth = feed.total(side=cluster.side, around=cluster.price, band=band)
        est = max(cluster.estimated_usdt, truth)
        driver = "both" if truth > 0 else "estimate"
        if truth > cluster.estimated_usdt * 2:
            driver = "truth"
        merged.append(Cluster(price=cluster.price, side=cluster.side,
                              estimated_usdt=round(est, 2), driver=driver))
    return merged


def build_profile(
    symbol: str,
    mark_price: float,
    open_interest_usdt: float,
    *,
    swing_high: float,
    swing_low: float,
    feed: TruthFeed | None = None,
    volume_profile: dict[float, float] | None = None,
) -> LiquidationProfile:
    clusters = estimate_clusters(
        mark_price, open_interest_usdt,
        swing_high=swing_high, swing_low=swing_low,
        volume_profile=volume_profile,
    )
    clusters = merge_truth(clusters, feed, mark_price=mark_price)
    return LiquidationProfile(
        symbol=symbol,
        mark_price=float(mark_price),
        open_interest=open_interest_usdt,
        clusters=clusters,
        truth_long_usdt=feed.total("LONG") if feed else 0.0,
        truth_short_usdt=feed.total("SHORT") if feed else 0.0,
        truth_events=len(feed.window()) if feed else 0,
        model_note=(
            "估算模型基于 OI×杠杆分层,非订单簿真值;"
            f"真实强平数据源:{feed.source_label if feed else '未接入'}"
        ),
    )
