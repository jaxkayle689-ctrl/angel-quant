"""Numerical contracts; not a substitute for executing the Pine production code."""
import random
import unittest
from dataclasses import dataclass


def fractal(a, b, c, strict=True):
    if strict:
        top = b[0] > a[0] and b[0] > c[0] and b[1] > a[1] and b[1] > c[1]
        bottom = b[0] < a[0] and b[0] < c[0] and b[1] < a[1] and b[1] < c[1]
    else:
        top = all(x >= y for x, y in zip(b + b, a + c)) and b != a and b != c
        bottom = all(x <= y for x, y in zip(b + b, a + c)) and b != a and b != c
    return 1 if top and not bottom else -1 if bottom and not top else 0


@dataclass(frozen=True)
class F:
    kind: int
    center: int
    index: int
    price: float


def valid(a, b, strict=True, minimum=5):
    return (a.kind != b.kind and b.center - 1 > a.center + 1
            and b.center - a.center >= max(4 if strict else 3, minimum - 1)
            and (b.price > a.price if a.kind == -1 else b.price < a.price)
            and (strict or b.index - a.index + 1 >= 5))


class Pens:
    def __init__(self):
        self.anchor = None
        self.tip = None
        self.frozen = []

    def feed(self, f):
        if self.anchor is None:
            self.anchor = f
        elif self.tip is None:
            if f.kind == self.anchor.kind:
                if (f.price - self.anchor.price) * f.kind > 0:
                    self.anchor = f
            elif valid(self.anchor, f):
                self.tip = f
        elif f.kind == self.tip.kind:
            if (f.price - self.tip.price) * f.kind > 0 and valid(self.anchor, f):
                self.tip = f
        elif valid(self.tip, f):
            self.frozen.append((self.anchor, self.tip))
            self.anchor, self.tip = self.tip, f


class RangeTree:
    def __init__(self, size):
        self.size = size
        self.base = 1
        while self.base < size:
            self.base *= 2
        self.values = [0.0] * (2 * self.base)

    def put(self, slot, value):
        p = self.base + slot
        self.values[p] = value
        p //= 2
        while p >= 1:
            self.values[p] = max(self.values[2*p], self.values[2*p+1])
            p //= 2

    def query(self, first, last):
        left, right, peak = self.base + first, self.base + last, 0.0
        while left <= right:
            if left % 2:
                peak = max(peak, self.values[left])
                left += 1
            if not right % 2:
                peak = max(peak, self.values[right])
                right -= 1
            left //= 2
            right //= 2
        return peak

    def wrapped(self, first, last):
        if first <= last:
            return self.query(first, last)
        return max(self.query(first, self.size-1), self.query(0, last))


class FractalStrokeMomentumTests(unittest.TestCase):
    def test_top_requires_both_high_and_low(self):
        self.assertEqual(fractal((10, 5), (12, 7), (11, 6)), 1)
        self.assertEqual(fractal((10, 5), (12, 4), (11, 6)), 0)

    def test_bottom_requires_both_high_and_low(self):
        self.assertEqual(fractal((12, 7), (10, 5), (11, 6)), -1)
        self.assertEqual(fractal((12, 7), (13, 5), (11, 6)), 0)

    def test_loose_equality_and_no_flat_double_fractal(self):
        self.assertEqual(fractal((10, 5), (10, 6), (9, 5), False), 1)
        self.assertEqual(fractal((10, 5), (10, 6), (9, 5), True), 0)
        self.assertEqual(fractal((10, 5), (10, 5), (10, 5), False), 0)

    def test_shared_processed_bar_rejected(self):
        self.assertFalse(valid(F(-1, 2, 2, 100), F(1, 4, 20, 120), False, 4))

    def test_new_pen_still_requires_raw_span(self):
        self.assertFalse(valid(F(-1, 2, 2, 100), F(1, 5, 5, 120), False, 4))
        self.assertTrue(valid(F(-1, 2, 2, 100), F(1, 5, 6, 120), False, 4))
        self.assertFalse(valid(F(-1, 2, 2, 100), F(1, 5, 6, 120), True, 4))

    def test_same_kind_replaces_only_mutable_tip(self):
        s = Pens()
        for f in [F(-1, 0, 0, 100), F(1, 4, 4, 120), F(1, 8, 8, 125)]:
            s.feed(f)
        self.assertEqual(s.tip.price, 125)
        self.assertEqual(s.frozen, [])
        s.feed(F(-1, 12, 12, 105))
        locked = tuple(s.frozen)
        s.feed(F(-1, 16, 16, 102))
        self.assertEqual(tuple(s.frozen), locked)
        self.assertEqual(s.tip.price, 102)

    def test_pen_direction_and_alternation(self):
        self.assertFalse(valid(F(-1, 0, 0, 100), F(-1, 4, 4, 90)))
        self.assertFalse(valid(F(-1, 0, 0, 100), F(1, 4, 4, 95)))

    def test_ring_tree_wrap_matches_bruteforce(self):
        rng = random.Random(42)
        size = 37
        tree, ring = RangeTree(size), [0.0]*size
        for i in range(1000):
            slot, value = i % size, rng.random()*20
            ring[slot] = value
            tree.put(slot, value)
            first, last = rng.randrange(size), rng.randrange(size)
            sample = ring[first:last+1] if first <= last else ring[first:] + ring[:last+1]
            self.assertEqual(tree.wrapped(first, last), max(sample))

    def test_signed_area_excludes_shared_start_endpoint(self):
        histogram = [10, -3, -2, 8, -1]
        negative_prefix = []
        total = 0
        for h in histogram:
            total += max(-h, 0)
            negative_prefix.append(total)
        self.assertEqual(negative_prefix[4] - negative_prefix[1], 3)


if __name__ == '__main__':
    unittest.main()
