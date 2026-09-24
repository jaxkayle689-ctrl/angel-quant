"""Closed-bar evidence for the two agent strategies; no orders or model I/O."""
from __future__ import annotations

import pandas as pd


def liquidity_context(frame: pd.DataFrame) -> dict:
    previous, last = frame.iloc[-21:-1], frame.iloc[-1]
    high, low = float(previous.high.max()), float(previous.low.min())
    return {
        "reference_high": high, "reference_low": low,
        "sell_side_sweep": float(last.low) < low < float(last.close),
        "buy_side_sweep": float(last.high) > high > float(last.close),
        "definition": "最近已收盘K越过此前20根高/低点后收回区间；仅为价格扫荡代理，不是订单流事实",
    }


def chan_context(frame: pd.DataFrame) -> dict:
    """Strict processed-bar fractals and strict strokes, confirmed by reversal.

    Left-boundary inclusion waits for direction. The final merged bar and stroke
    remain candidates. Segment/center/divergence parity with Pine is NOT claimed.
    """
    merged: list[dict] = []
    prefix: list[dict] = []
    direction = 0

    def contains(a, b):
        return (a['high'] >= b['high'] and a['low'] <= b['low']) or (b['high'] >= a['high'] and b['low'] <= a['low'])

    def combine(a, b, d):
        result = dict(a)
        for field in ('high', 'low'):
            if (b[field] > a[field]) if d == 1 else (b[field] < a[field]):
                result[field] = b[field]
                result[field + '_index'] = b[field + '_index']
        result['end'] = b['end']
        return result

    for i, row in enumerate(frame.itertuples()):
        bar = dict(start=i, end=i, high=float(row.high), low=float(row.low), high_index=i, low_index=i)
        if not merged:
            merged.append(bar)
            prefix.append(bar)
            continue
        tail = merged[-1]
        if not direction:
            if contains(tail, bar):
                prefix.append(bar)
                merged[-1] = bar
                continue
            direction = 1 if bar['high'] > tail['high'] else -1
            tail = prefix[0]
            for item in prefix[1:]:
                tail = combine(tail, item, direction)
            merged[-1] = tail
            prefix.clear()
        if contains(tail, bar):
            merged[-1] = combine(tail, bar, direction)
        else:
            direction = 1 if bar['high'] > tail['high'] else -1
            merged[-1]['confirmed_at'] = i
            merged.append(bar)

    fractals = []
    for i in range(1, len(merged) - 2):
        a, b, c = merged[i-1:i+2]
        top = b['high'] > max(a['high'], c['high']) and b['low'] > max(a['low'], c['low'])
        bottom = b['high'] < min(a['high'], c['high']) and b['low'] < min(a['low'], c['low'])
        if top or bottom:
            field = 'high' if top else 'low'
            fractals.append(dict(kind='top' if top else 'bottom', seq=i, price=b[field],
                                 raw_index=b[field + '_index'], confirmed_at=c['confirmed_at']))
    strokes = []
    anchor = tip = None
    for f in fractals:
        if anchor is None:
            anchor = f
        elif tip is None:
            if f['kind'] == anchor['kind']:
                if (f['price'] > anchor['price']) if f['kind'] == 'top' else (f['price'] < anchor['price']):
                    anchor = f
            elif f['seq'] - anchor['seq'] >= 4 and ((f['price'] > anchor['price']) if anchor['kind'] == 'bottom' else (f['price'] < anchor['price'])):
                tip = f
        elif f['kind'] == tip['kind']:
            if (f['price'] > tip['price']) if f['kind'] == 'top' else (f['price'] < tip['price']):
                tip = f
        elif f['seq'] - tip['seq'] >= 4 and ((f['price'] > tip['price']) if tip['kind'] == 'bottom' else (f['price'] < tip['price'])):
            strokes.append(dict(start=anchor, end=tip, confirmed_at=f['confirmed_at']))
            anchor, tip = tip, f
    return {
        'processed_count': len(merged), 'pending_prefix_count': len(prefix),
        'processed_bars': merged[-100:], 'fractals': fractals[-30:],
        'confirmed_strokes': strokes[-20:],
        'candidate_stroke': dict(start=anchor, end=tip) if tip else None,
        'scope': '严格分型与严格笔；未实现与Pine等价的线段/中枢/背驰确认，不得将模型推测称为已确认的一二三类点。',
        'structure_ready': len(strokes) >= 3,
    }
