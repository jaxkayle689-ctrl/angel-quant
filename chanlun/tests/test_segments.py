"""Numerical fixtures for the documented conservative segment definition.

These tests are an independent Python execution of the structure rules, not a
Pine compiler. Endpoints are hand-specified and expected answers are explicit.
Feature-tail freezing deliberately adds one opposing-stroke interval of delay.
"""
from dataclasses import dataclass
import unittest


@dataclass(frozen=True)
class Stroke:
    id: int
    start: float
    end: float

    @property
    def direction(self):
        return 1 if self.end > self.start else -1

    @property
    def high(self):
        return max(self.start, self.end)

    @property
    def low(self):
        return min(self.start, self.end)


@dataclass
class Feature:
    high: float
    low: float
    high_source: int
    low_source: int
    count: int = 1
    frozen: bool = False


class Features:
    def __init__(self, owner):
        self.owner = owner
        self.direction = 0
        self.items = []
        self.last_id = 0
        self.boundary = self.boundary_broken = False
        self.boundary_first_end = None
        self.processed = 0
        self.boundary = False
        self.boundary_first_end = None
        self.boundary_broken = False

    def add(self, stroke):
        if stroke.direction != -self.owner or stroke.id <= self.last_id:
            return None
        self.last_id = stroke.id
        new = Feature(stroke.high, stroke.low, stroke.id, stroke.id)
        if not self.items:
            self.items.append(new)
            return None
        tail = self.items[-1]
        contained = ((tail.high >= new.high and tail.low <= new.low)
                     or (new.high >= tail.high and new.low <= tail.low))
        if contained:
            direction = self.direction or self.owner
            if (new.high - tail.high) * direction > 0:
                tail.high, tail.high_source = new.high, new.high_source
            if (new.low - tail.low) * direction > 0:
                tail.low, tail.low_source = new.low, new.low_source
            tail.count += 1
            return None
        self.direction = 1 if new.high > tail.high else -1
        tail.frozen = True
        self.items.append(new)
        if len(self.items) < 4:
            return None
        a, b, c = self.items[-4:-1]
        top = b.high > max(a.high, c.high) and b.low > max(a.low, c.low)
        bottom = b.high < min(a.high, c.high) and b.low < min(a.low, c.low)
        if (top and self.owner == 1) or (bottom and self.owner == -1):
            return a, b, c
        return None


def seed_ok(a, b, c):
    return (a.direction == c.direction == -b.direction
            and min(a.high, b.high, c.high) > max(a.low, b.low, c.low)
            and (c.end - a.start) * a.direction > 0)


@dataclass(frozen=True)
class Segment:
    first: int
    last: int
    start: float
    end: float
    count: int
    gap: bool
    confirmed_on: int


class Segments:
    def __init__(self, strict=True, gap_confirm=True, capacity=1200):
        self.pending = []
        self.primary = None
        self.secondary = None
        self.direction = 0
        self.extreme = None
        self.candidate = None
        self.secondary_ready = False
        self.confirmed = []
        self.anchored = False
        self.blocked = False
        self.strict = strict
        self.gap_confirm = gap_confirm
        self.capacity = capacity
        self.last_id = 0
        self.boundary = self.boundary_broken = False
        self.boundary_first_end = None

    def _replay(self):
        while len(self.pending) >= 3 and self.primary is None:
            if seed_ok(*self.pending[:3]):
                self.direction = self.pending[0].direction
                self.primary = Features(self.direction)
                self.extreme = self.pending[0].end
                self.processed = 0
                for stroke in self.pending:
                    self._ingest(stroke)
            elif self.anchored:
                return
            else:
                self.pending.pop(0)

    def _ingest(self, stroke):
        self.processed += 1
        if (stroke.end - self.extreme) * self.direction > 0:
            self.extreme = stroke.end
        if self.candidate and (stroke.end - self.candidate[1]) * self.direction > 0:
            self.candidate = None
            self.secondary_ready = False
            self.boundary = self.boundary_broken = False
        if (not self.candidate and stroke.direction == -self.direction
                and self.processed >= 4 and self.primary.items
                and stroke.start == self.extreme):
            previous = self.primary.items[-1]
            outside = stroke.high >= previous.high and stroke.low <= previous.low
            broken = stroke.end < previous.low if self.direction > 0 else stroke.end > previous.high
            if outside and broken:
                self.candidate = (self.processed - 2, stroke.start, False)
                self.boundary = True
                self.boundary_broken = False
                self.boundary_first_end = stroke.end
                self.secondary = Features(-self.direction)
        if (self.boundary and stroke.direction == -self.direction
                and (stroke.end - self.boundary_first_end) * self.direction < 0):
            self.boundary_broken = True
        pattern = self.primary.add(stroke)
        if pattern:
            a, b, _ = pattern
            source = b.high_source if self.direction == 1 else b.low_source
            pos = next(i for i, s in enumerate(self.pending) if s.id == source)
            if pos >= 3:
                endpoint = self.pending[pos - 1]
                if ((endpoint.end - self.extreme) * self.direction >= 0
                        and endpoint.direction == self.direction):
                    gap = b.low > a.high or b.high < a.low
                    self.candidate = (pos - 1, endpoint.end, gap)
                    self.boundary = False
                    self.secondary = Features(-self.direction)
                    self.secondary_ready = False
                    for child in self.pending[pos:]:
                        if self.secondary.add(child):
                            self.secondary_ready = True
        if self.candidate and self.secondary.add(stroke):
            self.secondary_ready = True

    def add(self, stroke):
        if self.blocked or stroke.id <= self.last_id:
            return None
        if len(self.pending) >= self.capacity:
            self.blocked = True
            return None
        if self.pending:
            previous = self.pending[-1]
            if previous.direction == stroke.direction or previous.end != stroke.start:
                self.blocked = True
                return None
        self.last_id = stroke.id
        self.pending.append(stroke)
        if self.primary:
            self._ingest(stroke)
        else:
            self._replay()
        if not self.candidate:
            return None
        end_pos, price, gap = self.candidate
        reverse = self.pending[end_pos + 1:end_pos + 4]
        reverse_ready = len(reverse) == 3 and seed_ok(*reverse)
        if (gap and not (self.gap_confirm and self.secondary_ready and reverse_ready)
                or self.strict and not reverse_ready
                or self.boundary and not (reverse_ready and self.boundary_broken)):
            return None
        first, last = self.pending[0], self.pending[end_pos]
        answer = Segment(first.id, last.id, first.start, price, end_pos + 1, gap, stroke.id)
        self.confirmed.append(answer)
        self.pending = self.pending[end_pos + 1:]
        self.primary = self.secondary = self.candidate = None
        self.anchored = True
        self.secondary_ready = False
        self.boundary = self.boundary_broken = False
        self._replay()
        return answer

    def prices(self, values):
        for ident, (a, b) in enumerate(zip(values, values[1:]), 1):
            self.add(Stroke(ident, a, b))
        return self.confirmed


class SegmentFixtureTests(unittest.TestCase):
    def test_five_strokes_are_one_extending_candidate(self):
        engine = Segments()
        self.assertEqual(engine.prices([100, 120, 110, 130, 115, 140]), [])
        self.assertEqual(len(engine.pending), 5)
        self.assertEqual(engine.extreme, 140)
        self.assertIsNone(engine.candidate)

    def test_nine_trending_strokes_are_not_three_segments(self):
        engine = Segments()
        self.assertEqual(engine.prices([100, 120, 110, 130, 115, 140, 125, 150, 135, 160]), [])
        self.assertEqual(len(engine.pending), 9)

    def test_no_gap_freezes_only_after_right_feature_freezes(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 115, 125, 105, 120])
        self.assertEqual(engine.confirmed, [])
        answer = engine.add(Stroke(8, 120, 100))
        self.assertEqual(answer, Segment(1, 3, 100, 130, 3, False, 8))
        self.assertEqual(engine.pending[0].start, 130)

    def test_gap_needs_secondary_bottom_not_just_reverse_three(self):
        engine = Segments()
        engine.prices([100, 120, 110, 140, 125, 135, 115, 125, 105, 120, 110, 130, 115])
        self.assertEqual(engine.confirmed, [])
        self.assertEqual(engine.candidate, (2, 140, True))
        answer = engine.add(Stroke(13, 115, 135))
        self.assertEqual(answer, Segment(1, 3, 100, 140, 3, True, 13))

    def test_gap_switch_does_not_bypass_secondary_safety(self):
        engine = Segments(gap_confirm=False)
        engine.prices([100, 120, 110, 140, 125, 135, 115, 125, 105, 120, 110, 130, 115, 135])
        self.assertEqual(engine.confirmed, [])

    def test_original_new_high_invalidates_unconfirmed_gap_endpoint(self):
        engine = Segments()
        engine.prices([100, 120, 110, 140, 125, 135, 115, 125, 105])
        self.assertEqual(engine.candidate, (2, 140, True))
        engine.add(Stroke(9, 105, 145))
        self.assertIsNone(engine.candidate)
        self.assertEqual(engine.confirmed, [])
        self.assertEqual(engine.extreme, 145)

    def test_down_segment_can_contain_five_strokes_and_history_is_frozen(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 115, 125, 105, 120, 100])
        frozen = engine.confirmed[0]
        for ident, a, b in [(9, 100, 115), (10, 115, 106), (11, 106, 120), (12, 120, 110), (13, 110, 125)]:
            engine.add(Stroke(ident, a, b))
        self.assertEqual(engine.confirmed[0], frozen)
        self.assertEqual(engine.confirmed[1], Segment(4, 8, 130, 100, 5, False, 13))

    def test_feature_inclusion_uses_interval_direction_and_keeps_provenance(self):
        stream = Features(1)
        stream.add(Stroke(2, 120, 110))
        stream.add(Stroke(4, 130, 115))
        stream.add(Stroke(6, 128, 117))
        self.assertEqual((stream.items[-1].high, stream.items[-1].low), (130, 117))
        self.assertEqual((stream.items[-1].high_source, stream.items[-1].low_source), (4, 6))
        self.assertEqual(stream.items[-1].count, 2)
        self.assertFalse(stream.items[-1].frozen)

    def test_seed_rejects_no_common_overlap(self):
        self.assertFalse(seed_ok(Stroke(1, 100, 120), Stroke(2, 120, 110), Stroke(3, 110, 90)))
        self.assertFalse(seed_ok(Stroke(1, 100, 110), Stroke(2, 110, 90), Stroke(3, 90, 95)))

    def test_single_destructive_stroke_cannot_confirm_segment(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 50])
        self.assertEqual(engine.confirmed, [])

    def test_boundary_outside_first_stroke_waits_for_reverse_third(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 50, 60])
        self.assertEqual(engine.confirmed, [])
        self.assertTrue(engine.boundary)
        self.assertEqual(engine.add(Stroke(6, 60, 40)), Segment(1, 3, 100, 130, 3, False, 6))

    def test_boundary_inside_third_waits_until_first_endpoint_breaks(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 50, 70, 60, 80])
        self.assertEqual(engine.confirmed, [])
        self.assertEqual(engine.add(Stroke(8, 80, 40)), Segment(1, 3, 100, 130, 3, False, 8))

    def test_boundary_candidate_fails_when_original_direction_resumes(self):
        engine = Segments()
        engine.prices([100, 120, 110, 130, 50, 135])
        self.assertEqual(engine.confirmed, [])
        self.assertIsNone(engine.candidate)
        self.assertFalse(engine.boundary)

    def test_overflow_pauses_instead_of_manufacturing_a_segment(self):
        engine = Segments(capacity=5)
        engine.prices([100, 120, 110, 130, 115, 140, 125])
        self.assertTrue(engine.blocked)
        self.assertEqual(len(engine.pending), 5)
        self.assertEqual(engine.confirmed, [])

    def test_mirror_symmetry(self):
        values = [100, 120, 110, 130, 115, 125, 105, 120, 100]
        up, down = Segments(), Segments()
        up.prices(values)
        down.prices([-x for x in values])
        self.assertEqual((down.confirmed[0].start, down.confirmed[0].end), (-100, -130))
        self.assertEqual(up.confirmed[0].count, down.confirmed[0].count)


if __name__ == "__main__":
    unittest.main()
