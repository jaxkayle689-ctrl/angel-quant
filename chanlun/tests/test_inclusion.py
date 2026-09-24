"""Independent numeric specification, NOT a Pine compiler/runtime test.

Run: python3 -m unittest discover -s chanlun/tests -v
The production Pine script has its own assertions that call its actual engine.
"""
import random
import unittest
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Bar:
    high: float
    low: float
    start: int
    end: int
    hi_source: int
    lo_source: int
    seq: int = 0
    direction: int = 0
    confirmed_at: int = -1


def contains(a, b):
    return (a.high >= b.high and a.low <= b.low) or (
        b.high >= a.high and b.low <= a.low
    )


def relation(a, b):
    if b.high > a.high and b.low > a.low:
        return 1
    if b.high < a.high and b.low < a.low:
        return -1
    return 0


class Spec:
    def __init__(self, enabled=True, capacity=2000):
        self.enabled = enabled
        self.capacity = capacity
        self.history = []
        self.tail = None
        self.direction = 0
        self.skipped = 0
        self.index = -1
        self.total = 0
        self.unresolved = []

    def resolve_prefix(self, direction):
        merged = self.unresolved[0]
        choose = max if direction == 1 else min
        for item in self.unresolved[1:]:
            hi, lo = choose(merged.high, item.high), choose(merged.low, item.low)
            merged = replace(
                merged, high=hi, low=lo, end=item.end,
                hi_source=item.hi_source if hi != merged.high else merged.hi_source,
                lo_source=item.lo_source if lo != merged.low else merged.lo_source,
            )
        return merged

    def feed(self, high, low):
        if high < low:
            raise ValueError("invalid range")
        self.index += 1
        i = self.index
        raw = Bar(high, low, i, i, i, i)
        old = self.tail
        if old is None:
            self.tail = raw
            if self.enabled:
                self.unresolved.append(raw)
            return None
        if self.enabled and contains(old, raw):
            if not self.direction:
                self.unresolved.append(raw)
                self.tail = replace(raw, seq=old.seq)
            else:
                choose = max if self.direction == 1 else min
                hi, lo = choose(old.high, high), choose(old.low, low)
                self.tail = replace(
                    old, high=hi, low=lo, end=i,
                    hi_source=i if hi != old.high else old.hi_source,
                    lo_source=i if lo != old.low else old.lo_source,
                )
                self.skipped += 1
            return None
        self.direction = relation(old, raw) or self.direction
        resolving = self.enabled and bool(self.unresolved)
        event = self.resolve_prefix(self.direction) if resolving else old
        if resolving:
            self.skipped += len(self.unresolved) - 1
            self.unresolved.clear()
        if resolving and contains(event, raw):
            choose = max if self.direction == 1 else min
            hi, lo = choose(event.high, high), choose(event.low, low)
            self.tail = replace(event, high=hi, low=lo, end=i, direction=self.direction,
                                hi_source=i if hi != event.high else event.hi_source,
                                lo_source=i if lo != event.low else event.lo_source)
            self.skipped += 1
            return None
        event = replace(event, confirmed_at=i, direction=old.direction or self.direction)
        self.history = (self.history + [event])[-self.capacity:]
        self.total += 1
        self.tail = replace(raw, seq=old.seq + 1, direction=self.direction)
        return event


class InclusionTests(unittest.TestCase):
    def build(self, pairs, **kwargs):
        model = Spec(**kwargs)
        for hi, lo in pairs:
            model.feed(hi, lo)
        return model

    def test_upward_recursive_inclusion_and_mapping(self):
        s = self.build([(10, 5), (12, 7), (11, 8), (13, 6)])
        self.assertEqual((s.tail.high, s.tail.low), (13, 8))
        self.assertEqual((s.tail.start, s.tail.end), (1, 3))
        self.assertEqual((s.tail.hi_source, s.tail.lo_source), (3, 2))
        self.assertEqual(s.total, 1)

    def test_downward_recursive_inclusion_and_mapping(self):
        s = self.build([(15, 10), (13, 8), (12, 9), (14, 7)])
        self.assertEqual((s.tail.high, s.tail.low), (12, 7))
        self.assertEqual((s.tail.hi_source, s.tail.lo_source), (2, 3))

    def test_confirmation_waits_for_non_containing_successor(self):
        s = self.build([(10, 5), (12, 7), (11, 8), (13, 6)])
        event = s.feed(14, 9)
        self.assertEqual((event.start, event.end, event.confirmed_at), (1, 3, 4))
        snapshot = tuple(s.history)
        s.feed(15, 8)
        self.assertEqual(tuple(s.history), snapshot)
        self.assertEqual((event.high, event.low), (13, 8))

    def test_equal_ranges_are_inclusion_and_sources_remain_first(self):
        s = self.build([(10, 5), (12, 7), (12, 7), (12, 8)])
        self.assertEqual((s.tail.high, s.tail.low), (12, 8))
        self.assertEqual((s.tail.hi_source, s.tail.lo_source), (1, 3))

    def test_same_low_is_inclusion(self):
        s = self.build([(10, 5), (12, 7), (13, 7)])
        self.assertEqual((s.total, s.tail.high, s.tail.low), (1, 13, 7))

    def test_reversal_updates_direction_before_next_merge(self):
        s = self.build([(10, 5), (12, 7), (10, 4), (11, 3)])
        self.assertEqual(s.direction, -1)
        self.assertEqual((s.tail.high, s.tail.low), (10, 3))

    def test_startup_does_not_invent_direction(self):
        s = self.build([(10, 0), (9, 1), (8, 2)])
        self.assertEqual((s.skipped, s.direction, s.total), (0, 0, 0))
        self.assertIsNone(s.feed(9, 3))
        event = s.feed(11, 4)
        self.assertEqual((event.start, event.end, event.high, event.low), (0, 3, 10, 3))
        self.assertEqual((event.hi_source, event.lo_source), (0, 3))
        self.assertEqual(s.skipped, 3)
        self.assertEqual(s.direction, 1)

    def test_disable_is_one_to_one_even_for_included_bars(self):
        s = self.build([(10, 0), (9, 1), (8, 2)], enabled=False)
        self.assertEqual((s.total, s.skipped), (2, 0))
        self.assertTrue(all(b.start == b.end for b in s.history + [s.tail]))

    def test_cache_truncation_keeps_stable_ids(self):
        s = self.build([(10 + i, 5 + i) for i in range(20)], capacity=3)
        self.assertEqual([b.seq for b in s.history], [16, 17, 18])
        self.assertEqual((s.tail.seq, s.total), (19, 19))

    def test_all_equal_has_no_confirmed_output(self):
        s = self.build([(10, 10)] * 5000)
        self.assertEqual((s.total, s.skipped, s.direction), (0, 0, 0))
        self.assertEqual(len(s.unresolved), 5000)

    def test_price_gap_is_not_inclusion(self):
        s = self.build([(10, 5), (30, 25), (15, 10)])
        self.assertEqual(s.total, 2)
        self.assertEqual(s.direction, -1)

    def test_zero_negative_prices_and_invalid_range(self):
        s = self.build([(-5, -10), (0, -8), (-1, -7)])
        self.assertEqual((s.tail.high, s.tail.low), (0, -7))
        with self.assertRaises(ValueError):
            s.feed(0, 1)

    def test_prefix_replay_is_identical(self):
        rng = random.Random(72)
        bars = []
        for _ in range(120):
            lo = rng.randint(-10, 100)
            bars.append((lo + rng.randint(0, 40), lo))
        live = Spec()
        for n, pair in enumerate(bars, 1):
            live.feed(*pair)
            replay = self.build(bars[:n])
            self.assertEqual((live.history, live.tail, live.direction),
                             (replay.history, replay.tail, replay.direction))

    def test_randomized_invariants_and_original_extrema_sources(self):
        # 100 seeds, 300 bars each: includes negative, equal and disjoint ranges.
        for seed in range(100):
            rng = random.Random(seed)
            s = Spec(capacity=500)
            raw = []
            for _ in range(300):
                lo = rng.randint(-30, 100)
                hi = lo + rng.randint(0, 40)
                raw.append((hi, lo))
                frozen_prefix = tuple(s.history)
                event = s.feed(hi, lo)
                self.assertEqual(tuple(s.history[:len(frozen_prefix)]), frozen_prefix)
                values = s.history + [s.tail]
                represented = len(s.unresolved) if s.unresolved else len(s.history) + 1
                self.assertEqual(s.skipped + represented, len(raw))
                self.assertLessEqual(s.tail.low, s.tail.high)
                self.assertEqual(s.tail.high, raw[s.tail.hi_source][0])
                self.assertEqual(s.tail.low, raw[s.tail.lo_source][1])
                if len(values) > 1:
                    self.assertFalse(contains(values[-2], values[-1]))
                    self.assertEqual(values[-2].end + 1, values[-1].start)
                if event:
                    self.assertGreater(event.confirmed_at, event.end)


if __name__ == "__main__":
    unittest.main()
