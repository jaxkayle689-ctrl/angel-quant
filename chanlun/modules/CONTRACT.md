# Full indicator module contract

All fragments concatenate into a single Pine v6 script. No imports. Root owns header/types/inputs/common functions, core, render, scheduler. Module authors own their fragment only.

Shared types (root defines before fragments):

```
enum Life
    candidate
    confirmed
    invalidated
type Meta
    int id = 0
    int bar_index = 0
    int timestamp = 0
    float high = na
    float low = na
    int direction = 0
    bool confirmed = false
    int start_index = 0
    int end_index = 0
    int start_time = 0
    int end_time = 0
    int confirmed_at_index = na
    int confirmed_at_time = na
type Momentum
    float area = 0.0
    float peak = 0.0
    float hist_peak = 0.0
    int bars = 0
    bool complete = false
type Leg
    Meta m
    float start_price = na
    float end_price = na
    int first_child = 0
    int last_child = 0
    int count = 1
    Momentum mom
    string reason = ""
type Event
    string kind = ""
    int level = 0
    int side = 0
    int signal_class = 0
    Life state = Life.candidate
    int source_id = 0
    int index = 0
    int ts = 0
    float price = na
    string reason = ""
```

Root common helpers:
- f_meta(id, startIndex, startTime, endIndex, endTime, startPrice, endPrice, confirmed) => Meta; direction +/-1; high/low endpoint range. confirmation time current bar when confirmed.
- f_legCopy(Leg x) => deep value copy (Meta, Momentum copied).
- f_contains(ah,al,bh,bl) => bool.
- f_relation(ah,al,bh,bl) => int +/-1/0.
- f_fractalKind(ah,al,bh,bl,ch,cl,strict) => +1 top / -1 bottom / 0.
- f_overlap3(Leg a, Leg b, Leg c) => [float zd,float zg] (zg>zd required).
- f_emit(array<Event> events, string kind, int level,int side,int cls,Life state,int id,int ix,int ts,float price,string reason) => pushes event.

Inputs available globally:
int maxHistory (500..5000), bool debug, bool strictSegment, bool gapConfirm, bool strictFractal, string strokeMode ("严格笔"/"新笔"), int minBars;
string divAlgorithm ("MACD柱面积"/"DIF峰值"/"综合模式"), float divRatio (0.5..1.0, default .85), int areaWindow; bool enableSignals (full vs Core).

Segment fragment API:
- type SegmentEngine (include Leg preview, string reason, array<FeatureElement> features, etc)
- f_segmentEngine() => SegmentEngine
- method onStroke(SegmentEngine self, Leg frozenStroke, array<Event> events) => Leg newly confirmed segment or na
- pending buffer bounded; fail closed with diagnostic on overflow. Features must derive opposing strokes, with inclusion, fractal, gap second confirmation; never every 3 strokes. Root adds measured Momentum to returned segment and preview.

Pivot/signals fragment API:
- type PivotEngine with int level, ZhongShu active, ZhongShu previous, int trend, string reason, array<ZhongShu> history, array<Signal> signals, array<Divergence> divergences.
- ZhongShu fields must include Meta m, float zd,zg,gg,dd, PivotState state; root uses these, other evidence fields unrestricted.
- Signal fields Meta m, int level, int side (+1 buy,-1 sell), int signal_class, Life state, string reason (plus any evidence fields).
- Divergence fields Meta m, int level, int side (+1 bullish,-1 bearish), Life state, string reason.
- f_pivotEngine(int level) => PivotEngine
- method onLeg(PivotEngine self, Leg frozen, array<Event> events) => void/int; emits new/updated pivot and signal/divergence events. Only frozen input creates confirmed structures.
- method onPreview(PivotEngine self, Leg candidate, array<Event> events) => void/int; candidate lifecycle only, never change confirmed history; can receive na to invalidate candidate.
- Signal/Divergence arrays bounded (e.g. 120 each); active states not accidentally dropped. events ephemeral at root, carry all info to render/alerts. kind values: "signal", "divergence", "leave", "return", "pivot", "segment".

No global scalar mutation in functions. UI is root responsibility. Pine functions defined before use; no recursion. Existing Phase 1 is reference only; full engine may retain initialization policy. Do not claim official compiler validation.
