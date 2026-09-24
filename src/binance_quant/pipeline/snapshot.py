from __future__ import annotations

"""技术分析快照引擎。

确定性计算:同一份输入恒同一份输出。LLM 与规则通道消费同一份快照,
保证「规则与 LLM 看到的是同一个世界」。
"""

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = frame["high"], frame["low"], frame["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False).mean()


def _round(value: float, digits: int = 8) -> float:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return 0.0
    return round(float(value), digits)


@dataclass(frozen=True)
class TechnicalSnapshot:
    """单标的单周期的确定性技术快照。"""

    symbol: str
    interval: str
    as_of: str
    close: float
    ema7: float
    ema25: float
    ema100: float
    rsi14: float
    atr14: float
    bb_mid: float
    bb_upper: float
    bb_lower: float
    bb_percent_b: float
    vwap: float
    volume_ratio: float
    swing_high: float
    swing_low: float
    trend: str          # up / down / flat
    trend_age_bars: int
    roc12_pct: float
    source_bars: int
    multi: dict[str, dict[str, Any]] = field(default_factory=dict)
    snapshot_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "as_of": self.as_of,
            "close": self.close,
            "ema7": self.ema7,
            "ema25": self.ema25,
            "ema100": self.ema100,
            "rsi14": self.rsi14,
            "atr14": self.atr14,
            "bb_mid": self.bb_mid,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "bb_percent_b": self.bb_percent_b,
            "vwap": self.vwap,
            "volume_ratio": self.volume_ratio,
            "swing_high": self.swing_high,
            "swing_low": self.swing_low,
            "trend": self.trend,
            "trend_age_bars": self.trend_age_bars,
            "roc12_pct": self.roc12_pct,
            "source_bars": self.source_bars,
            "multi": self.multi,
            "snapshot_hash": self.snapshot_hash,
        }

    def evidence_text(self) -> str:
        """供 LLM 消费的确定性证据文本(LLM 只解释,不计算)。"""
        lines = [
            f"标的:{self.symbol} 周期:{self.interval} 数据时间:{self.as_of} 快照哈希:{self.snapshot_hash[:12]}",
            f"现价 {self.close} | EMA7 {self.ema7} | EMA25 {self.ema25} | EMA100 {self.ema100}",
            f"RSI14 {self.rsi14} | ATR14 {self.atr14} | 布林带 中{self.bb_mid} 上{self.bb_upper} 下{self.bb_lower} %B {self.bb_percent_b}",
            f"VWAP {self.vwap} | 量比(5/20) {self.volume_ratio} | ROC12 {self.roc12_pct}%",
            f"近期区间:高 {self.swing_high} 低 {self.swing_low} | 趋势:{self.trend}(已持续 {self.trend_age_bars} 根)",
        ]
        for interval, summary in self.multi.items():
            lines.append(
                f"级联[{interval}] EMA7 {summary.get('ema7')} EMA25 {summary.get('ema25')} "
                f"EMA100 {summary.get('ema100')} trend {summary.get('trend')}"
            )
        return "\n".join(lines)


def _trend_and_age(frame: pd.DataFrame) -> tuple[str, int]:
    close = frame["close"]
    if len(close) < 2:
        return "flat", 0
    ema25 = _ema(close, 25)
    ema100 = _ema(close, 100)
    diff = (ema25 - ema100).dropna()
    if diff.empty:
        return "flat", 0
    sign = (diff > 0).astype(int)
    trend = "up" if sign.iloc[-1] == 1 else "down"
    age = 0
    for value in reversed(sign.tolist()):
        if int(value) == int(sign.iloc[-1]):
            age += 1
        else:
            break
    if abs(diff.iloc[-1]) < 1e-12:
        return "flat", age
    return trend, age


def _summarize(frame: pd.DataFrame) -> dict[str, Any]:
    close = frame["close"]
    trend, _age = _trend_and_age(frame)
    return {
        "close": _round(close.iloc[-1]),
        "ema7": _round(_ema(close, 7).iloc[-1]),
        "ema25": _round(_ema(close, 25).iloc[-1]),
        "ema100": _round(_ema(close, 100).iloc[-1]),
        "trend": trend,
    }


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """标准化 K 线列名(open/high/low/close/volume 小写),按索引排序。"""
    lowered = {c: c.lower() for c in frame.columns}
    frame = frame.rename(columns=lowered)
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"K线缺少列: {missing}")
    frame = frame[[*REQUIRED_COLUMNS]].dropna()
    if not isinstance(frame.index, pd.DatetimeIndex):
        try:
            frame.index = pd.to_datetime(frame.index)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("K线索引无法解析为时间。") from exc
    return frame.sort_index()


def build_snapshot(
    symbol: str,
    interval: str,
    frame: pd.DataFrame,
    *,
    frames: dict[str, pd.DataFrame] | None = None,
    min_bars: int = 120,
) -> TechnicalSnapshot:
    """由已收盘 K 线构建确定性快照。frames 传入多周期时写入级联摘要。"""
    frame = normalize_frame(frame)
    if len(frame) < min_bars:
        raise ValueError(f"K线数量不足:{len(frame)} < {min_bars}(需要完整历史构建快照)")

    close = frame["close"]
    ema7 = _ema(close, 7)
    ema25 = _ema(close, 25)
    ema100 = _ema(close, 100)

    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    upper = mid + 2.0 * std
    lower = mid - 2.0 * std
    percent_b = (close - lower) / (upper - lower)

    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    volume = frame["volume"].replace(0.0, pd.NA)
    vwap = (typical * frame["volume"]).rolling(20).sum() / volume.rolling(20).sum()
    vma_fast = frame["volume"].rolling(5).mean()
    vma_slow = frame["volume"].rolling(20).mean()
    ratio = vma_fast / vma_slow

    last_close = float(close.iloc[-1])
    mid_v = float(mid.iloc[-1]) if not math.isnan(float(mid.iloc[-1])) else last_close
    upper_v = float(upper.iloc[-1]) if not math.isnan(float(upper.iloc[-1])) else last_close
    lower_v = float(lower.iloc[-1]) if not math.isnan(float(lower.iloc[-1])) else last_close
    span = (upper_v - lower_v) or 1.0

    window = frame.tail(60)
    trend, age = _trend_and_age(frame)

    multi: dict[str, dict[str, Any]] = {}
    if frames:
        for key, aux in frames.items():
            if key == interval:
                continue
            try:
                multi[key] = _summarize(normalize_frame(aux))
            except ValueError:
                continue

    as_of = frame.index[-1].isoformat()
    payload = {
        "symbol": symbol,
        "interval": interval,
        "as_of": as_of,
        "close": _round(last_close),
        "ema7": _round(ema7.iloc[-1]),
        "ema25": _round(ema25.iloc[-1]),
        "ema100": _round(ema100.iloc[-1]),
        "rsi14": _round(_rsi(close).iloc[-1], 4),
        "atr14": _round(_atr(frame).iloc[-1]),
        "bb_mid": _round(mid_v),
        "bb_upper": _round(upper_v),
        "bb_lower": _round(lower_v),
        "bb_percent_b": _round((last_close - lower_v) / span, 4),
        "vwap": _round(float(vwap.iloc[-1]) if not math.isnan(float(vwap.iloc[-1])) else last_close),
        "volume_ratio": _round(float(ratio.iloc[-1]) if not math.isnan(float(ratio.iloc[-1])) else 1.0, 4),
        "swing_high": _round(window["high"].max()),
        "swing_low": _round(window["low"].min()),
        "trend": trend,
        "trend_age_bars": age,
        "roc12_pct": _round((last_close / float(close.iloc[-13]) - 1.0) * 100.0, 4) if len(close) > 12 else 0.0,
        "source_bars": len(frame),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return TechnicalSnapshot(
        snapshot_hash=digest, multi=multi, **payload
    )
