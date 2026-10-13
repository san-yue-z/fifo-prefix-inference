"""Exact vertical-band inference for the declared constant-scale FIFO model.

This is not a hardware latency model. Explicit convex prior components remain
separate; completion reports can create nonconvex or disconnected support.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction


def q(value):
    if isinstance(value, Fraction):
        return value
    if type(value) not in (int, str):
        raise TypeError("Use exact integers, rational strings or Fraction.")
    return Fraction(value)


@dataclass(frozen=True)
class Affine:
    slope: Fraction
    intercept: Fraction

    def at(self, theta):
        return self.slope * theta + self.intercept


@dataclass(frozen=True)
class Bound:
    line: Affine
    strict: bool = False


@dataclass(frozen=True)
class Level:
    value: Fraction
    strict: bool = False


@dataclass(frozen=True)
class OpenBand:
    left: Fraction
    right: Fraction
    lower: Bound
    upper: Bound


@dataclass(frozen=True)
class PointSlice:
    theta: Fraction
    lower: Level
    upper: Level


@dataclass(frozen=True)
class Endpoint:
    value: Fraction
    attained: bool


@dataclass(frozen=True)
class Piece:
    left: Fraction
    right: Fraction
    line: Affine


@dataclass(frozen=True)
class Curve:
    pieces: tuple[Piece, ...]
    atom: Fraction | None = None

    def values(self, knots):
        index = 0
        for theta in knots:
            if not self.pieces:
                if self.atom is None:
                    raise ValueError("Curve has neither an interval nor an atom.")
                yield self.atom
                continue
            while index + 1 < len(self.pieces) and self.pieces[index].right < theta:
                index += 1
            yield self.pieces[index].line.at(theta)


@dataclass(frozen=True)
class HullNode:
    line: Affine
    right: Fraction | None
    following: HullNode | None
    jumps: tuple[HullNode, ...]


def _node(line, right, following):
    jumps = []
    if following is not None:
        jumps.append(following)
        level = 1
        while len(jumps[-1].jumps) >= level:
            jumps.append(jumps[-1].jumps[level - 1])
            level += 1
    return HullNode(line, right, following, tuple(jumps))


def _seek(node, theta):
    if node is None:
        raise ValueError("An empty departure envelope is undefined.")
    if node.right is None or node.right > theta:
        return node
    for level in range(len(node.jumps) - 1, -1, -1):
        if level < len(node.jumps):
            successor = node.jumps[level]
            if successor.right is not None and successor.right <= theta:
                node = successor
    return node.following if node.right is not None and node.right <= theta else node


class DepartureEnvelopes:
    """Persistent prefix hulls; binary lifting locates a bounded theta range."""

    def __init__(self, submits, work):
        self.submits, self.work = tuple(map(q, submits)), tuple(map(q, work))
        if len(self.submits) != len(self.work):
            raise ValueError("Submission/work lengths differ.")
        if any(p <= 0 for p in self.work) or any(a >= b for a, b in zip(self.submits, self.submits[1:])):
            raise ValueError("Strictly increasing submits and positive work required.")
        self.prefix, self.heads = [Fraction(0)], [None]
        head = None
        for t, p in zip(self.submits, self.work):
            line = Affine(-self.prefix[-1], t)
            while head is not None:
                crossing = (line.intercept - head.line.intercept) / (head.line.slope - line.slope)
                if head.right is None or crossing < head.right:
                    break
                head = head.following
            head = _node(line, crossing if head is not None else None, head)
            self.prefix.append(self.prefix[-1] + p)
            self.heads.append(head)

    def value(self, count, theta):
        if not 1 <= count <= len(self.work):
            raise ValueError("Departure count must be in [1,n].")
        theta = q(theta)
        return _seek(self.heads[count], theta).line.at(theta) + self.prefix[count] * theta

    def curve(self, count, left, right):
        if left == right:
            return Curve((), self.value(count, left))
        node, start, rows = _seek(self.heads[count], left), left, []
        while start < right:
            end = right if node.right is None else min(right, node.right)
            rows.append(Piece(start, end, Affine(node.line.slope + self.prefix[count], node.line.intercept)))
            start, node = end, node.following
        return Curve(tuple(rows))


def _crossing(a, b):
    if a.slope == b.slope:
        return None
    return (b.intercept - a.intercept) / (a.slope - b.slope)


def _push(values, value):
    if not values or values[-1] != value:
        if values and value < values[-1]:
            raise AssertionError("Knot stream must be ordered.")
        values.append(value)


def _merge(a, b):
    left, right, out = 0, 0, []
    while left < len(a) or right < len(b):
        if right == len(b) or (left < len(a) and a[left] <= b[right]):
            _push(out, a[left])
            left += 1
        else:
            _push(out, b[right])
            right += 1
    return out


def _nonempty(lower, upper):
    return lower.value < upper.value or (lower.value == upper.value and not lower.strict and not upper.strict)


def _tight(a, b, theta, lower):
    va, vb = a.line.at(theta), b.line.at(theta)
    if va == vb:
        return Bound(a.line, a.strict or b.strict)
    return a if (va > vb if lower else va < vb) else b


def _tight_level(a, b, lower):
    if a.value == b.value:
        return Level(a.value, a.strict or b.strict)
    return a if (a.value > b.value if lower else a.value < b.value) else b


def _feasible_parts(left, right, lower, upper):
    cut = _crossing(lower.line, upper.line)
    knots = [left] + ([cut] if cut is not None and left < cut < right else []) + [right]
    bands = []
    for a, b in zip(knots, knots[1:]):
        mid = (a + b) / 2
        if _nonempty(Level(lower.line.at(mid), lower.strict), Level(upper.line.at(mid), upper.strict)):
            bands.append(OpenBand(a, b, lower, upper))
    return bands, knots


class VerticalComponent:
    def __init__(self, left, right, bands, points):
        self.left, self.right = left, right
        self.bands, self.points = tuple(bands), tuple(points)
        self._coalesce()

    def _coalesce(self):
        point_map = {p.theta: p for p in self.points}
        rows, removed = [], set()
        for band in self.bands:
            if rows:
                prev = rows[-1]
                atom = point_map.get(band.left)
                if (prev.right == band.left and prev.lower == band.lower and prev.upper == band.upper
                        and atom is not None
                        and atom.lower == Level(band.lower.line.at(band.left), band.lower.strict)
                        and atom.upper == Level(band.upper.line.at(band.left), band.upper.strict)):
                    rows[-1] = OpenBand(prev.left, band.right, band.lower, band.upper)
                    removed.add(band.left)
                    continue
            rows.append(band)
        self.bands = tuple(rows)
        self.points = tuple(p for p in self.points if p.theta not in removed)

    def slices(self, knots):
        points = {p.theta: p for p in self.points}
        index = 0
        for theta in knots:
            if theta in points:
                yield points[theta]
                continue
            while index < len(self.bands) and self.bands[index].right <= theta:
                index += 1
            band = self.bands[index] if index < len(self.bands) else None
            if band is not None and band.left < theta < band.right:
                yield PointSlice(theta, Level(band.lower.line.at(theta), band.lower.strict), Level(band.upper.line.at(theta), band.upper.strict))
            else:
                yield None

    def restrict(self, curve, *, lower, strict):
        rows, knots, index = [], [], 0
        for band in self.bands:
            while index < len(curve.pieces) and curve.pieces[index].right <= band.left:
                index += 1
            current = index
            while current < len(curve.pieces) and curve.pieces[current].left < band.right:
                piece = curve.pieces[current]
                left, right = max(band.left, piece.left), min(band.right, piece.right)
                if left < right:
                    original = band.lower if lower else band.upper
                    added = Bound(piece.line, strict)
                    crossing = _crossing(original.line, added.line)
                    cuts = [left] + ([crossing] if crossing is not None and left < crossing < right else []) + [right]
                    for a, b in zip(cuts, cuts[1:]):
                        active = _tight(original, added, (a + b) / 2, lower)
                        lo, hi = (active, band.upper) if lower else (band.lower, active)
                        kept, candidates = _feasible_parts(a, b, lo, hi)
                        rows.extend(kept)
                        for value in candidates:
                            _push(knots, value)
                current += 1
        knots = _merge(knots, [p.theta for p in self.points])
        points = []
        for old, value in zip(self.slices(knots), curve.values(knots)):
            if old is None:
                continue
            if lower:
                lo, hi = _tight_level(old.lower, Level(value, strict), True), old.upper
            else:
                lo, hi = old.lower, _tight_level(old.upper, Level(value, strict), False)
            if _nonempty(lo, hi):
                points.append(PointSlice(old.theta, lo, hi))
        return VerticalComponent(self.left, self.right, rows, points)

    def contains(self, theta, delta):
        atom = next(self.slices([theta]))
        if atom is None:
            return False
        return ((delta > atom.lower.value if atom.lower.strict else delta >= atom.lower.value)
                and (delta < atom.upper.value if atom.upper.strict else delta <= atom.upper.value))


def _upper_hull(lines):
    ordered = {}
    for line in lines:
        if line.slope not in ordered or line.intercept > ordered[line.slope].intercept:
            ordered[line.slope] = line
    rows, starts = [], []
    for line in (ordered[k] for k in sorted(ordered)):
        while rows:
            crossing = _crossing(rows[-1], line)
            if len(rows) == 1 or crossing > starts[-1]:
                break
            rows.pop()
            starts.pop()
        rows.append(line)
        starts.append(crossing if len(rows) > 1 else None)
    return tuple(rows), tuple(starts)


def _initial_component(vertices, extra_halfplanes=()):
    rows = [tuple(map(q, v)) for v in vertices]
    if not rows or any(len(v) != 2 for v in rows):
        raise ValueError("A nonempty bounded convex prior component is required.")
    if len(rows) > 1 and rows[0] == rows[-1]:
        rows.pop()
    if len(set(rows)) != len(rows):
        raise ValueError("Duplicate nonclosing prior vertices are unsupported.")
    if len(rows) > 2:
        cross = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if all(cross(rows[0], rows[1], v) == 0 for v in rows):
            rows = [min(rows), max(rows)]
        else:
            area = sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(rows, rows[1:] + rows[:1]))
            if area < 0:
                rows.reverse()
            if any(cross(a, b, v) < 0 for a, b in zip(rows, rows[1:] + rows[:1]) for v in rows):
                raise ValueError("Initial component must be convex/cyclic; no union hull is allowed.")
    left, right = min(v[0] for v in rows), max(v[0] for v in rows)
    planes = [(Fraction(-1), Fraction(0), Fraction(0), True), (Fraction(0), Fraction(-1), Fraction(0), False)]
    if len(rows) == 1 or left == right:
        planes += [(Fraction(0), Fraction(-1), -min(v[1] for v in rows), False), (Fraction(0), Fraction(1), max(v[1] for v in rows), False)]
    elif len(rows) == 2:
        slope = (rows[1][1] - rows[0][1]) / (rows[1][0] - rows[0][0])
        intercept = rows[0][1] - slope * rows[0][0]
        planes += [(slope, Fraction(-1), -intercept, False), (-slope, Fraction(1), intercept, False)]
    else:
        for a, b in zip(rows, rows[1:] + rows[:1]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            planes.append((dy, -dx, dy * a[0] - dx * a[1], False))
    for a, b, c, strict in extra_halfplanes:
        if type(strict) is not bool:
            raise TypeError("Strict flag must be bool.")
        plane = (q(a), q(b), q(c), strict)
        if any(plane[0] * x + plane[1] * y > plane[2] for x, y in rows):
            raise ValueError("Public halfplane excludes a supplied closure vertex.")
        planes.append(plane)
    lower, upper, theta_planes = [], [], []
    for a, b, c, strict in planes:
        if b:
            bound = Bound(Affine(-a / b, c / b), strict)
            (lower if b < 0 else upper).append(bound)
        else:
            theta_planes.append((a, c, strict))
    if not upper:
        raise ValueError("A bounded vertical prior is required.")
    low_hull, low_starts = _upper_hull([b.line for b in lower])
    high_hull, high_starts = _upper_hull([Affine(-b.line.slope, -b.line.intercept) for b in upper])
    knots = {left, right}
    knots.update(x for x in low_starts[1:] + high_starts[1:] if left < x < right)
    knots.update(c / a for a, c, _ in theta_planes if a and left < c / a < right)
    knots = sorted(knots)
    bands, candidates = [], []
    def slice_at(theta):
        if any((a * theta >= c if strict else a * theta > c) for a, c, strict in theta_planes):
            return None
        lo = max(b.line.at(theta) for b in lower)
        hi = min(b.line.at(theta) for b in upper)
        low = Level(lo, any(b.strict and b.line.at(theta) == lo for b in lower))
        high = Level(hi, any(b.strict and b.line.at(theta) == hi for b in upper))
        return PointSlice(theta, low, high) if _nonempty(low, high) else None
    for a, b in zip(knots, knots[1:]):
        mid = (a + b) / 2
        if any((aa * mid >= cc if ss else aa * mid > cc) for aa, cc, ss in theta_planes):
            # Retain crossing atoms even when both adjacent open pieces vanish.
            for value in (a, b):
                _push(candidates, value)
            continue
        lo_line = low_hull[bisect_right(low_starts[1:], mid)]
        neg = high_hull[bisect_right(high_starts[1:], mid)]
        hi_line = Affine(-neg.slope, -neg.intercept)
        lo = Bound(lo_line, any(x.line == lo_line and x.strict for x in lower))
        hi = Bound(hi_line, any(x.line == hi_line and x.strict for x in upper))
        kept, xs = _feasible_parts(a, b, lo, hi)
        bands.extend(kept)
        for value in xs:
            _push(candidates, value)
    candidates = _merge(candidates, knots)
    points = [atom for theta in candidates if (atom := slice_at(theta)) is not None]
    return VerticalComponent(left, right, bands, points)


class BandPosterior:
    def __init__(self, submits, work, initial_cells, initial_halfplanes=None):
        self.envelopes = DepartureEnvelopes(submits, work)
        self.submits, self.work = self.envelopes.submits, self.envelopes.work
        cells = list(initial_cells)
        if not cells:
            raise ValueError("Provide explicit bounded convex prior components.")
        extra = [()] * len(cells) if initial_halfplanes is None else list(initial_halfplanes)
        if len(extra) != len(cells):
            raise ValueError("Halfplane component count mismatch.")
        self.components = [_initial_component(v, h) for v, h in zip(cells, extra)]
        self.reports = []

    @classmethod
    def from_case(cls, case):
        posterior = cls([j["t"] for j in case["jobs"]], [j["p"] for j in case["jobs"]], [c["vertices"] for c in case["prior_cells"]], [c.get("halfplanes", ()) for c in case["prior_cells"]])
        for report in case["reports"]:
            posterior.update(report["c"], report["tau"])
        return posterior

    def update(self, completed, report_time):
        if type(completed) is not int or not 0 <= completed <= len(self.work):
            raise ValueError("Completed prefix must be in [0,n].")
        tau = q(report_time)
        result = []
        for component in self.components:
            for count, lower in ((completed, False), (completed + 1, True)):
                if count == 0 or count > len(self.work) or not (component.bands or component.points):
                    continue
                original = self.envelopes.curve(count, component.left, component.right)
                curve = Curve(tuple(Piece(p.left, p.right, Affine(-p.line.slope, tau - p.line.intercept)) for p in original.pieces), tau - original.atom if original.atom is not None else None)
                component = component.restrict(curve, lower=lower, strict=lower)
            result.append(component)
        self.components = result
        self.reports.append((completed, tau))
        return self

    def contains(self, value):
        if len(value) != 2:
            raise ValueError("A point is (theta,delta).")
        theta, delta = map(q, value)
        return any(c.contains(theta, delta) for c in self.components)

    def _query(self, now, new_work):
        now, new_work = q(now), q(new_work)
        if any(tau > now for _, tau in self.reports):
            raise ValueError("A future report cannot be used in a current decision.")
        if new_work <= 0 or (self.submits and now <= self.submits[-1]):
            raise ValueError("Positive new work must follow all known submissions.")
        return now, new_work

    def _remote_curve(self, component, now, new_work):
        left, right = component.left, component.right
        if left == right:
            g = self.envelopes.value(len(self.work), left) if self.work else now
            return Curve((), max(now, g) + new_work * left)
        original = self.envelopes.curve(len(self.work), left, right) if self.work else Curve((Piece(left, right, Affine(Fraction(0), now)),))
        rows, constant = [], Affine(Fraction(0), now)
        for piece in original.pieces:
            cross = _crossing(piece.line, constant)
            knots = [piece.left] + ([cross] if cross is not None and piece.left < cross < piece.right else []) + [piece.right]
            for a, b in zip(knots, knots[1:]):
                line = piece.line if piece.line.at((a + b) / 2) >= now else constant
                rows.append(Piece(a, b, Affine(line.slope + new_work, line.intercept)))
        return Curve(tuple(rows))

    @staticmethod
    def _overlaps(component, curve):
        index = 0
        for band in component.bands:
            while index < len(curve.pieces) and curve.pieces[index].right <= band.left:
                index += 1
            current = index
            while current < len(curve.pieces) and curve.pieces[current].left < band.right:
                piece = curve.pieces[current]
                a, b = max(band.left, piece.left), min(band.right, piece.right)
                if a < b:
                    yield band, piece.line, a, b
                current += 1

    @classmethod
    def _query_slices(cls, component, curve):
        # A new readiness kink may attain an extremum inside an existing band.
        knots = []
        for _, _, left, right in cls._overlaps(component, curve):
            _push(knots, left)
            _push(knots, right)
        knots = _merge(knots, [p.theta for p in component.points])
        for atom, value in zip(component.slices(knots), curve.values(knots)):
            if atom is not None:
                yield atom, value

    def mode_exists(self, now, new_work, threshold):
        now, p = self._query(now, new_work)
        threshold, below, above = q(threshold), False, False
        for component in self.components:
            if not (component.bands or component.points):
                continue
            curve = self._remote_curve(component, now, p)
            for band, line, a, b in self._overlaps(component, curve):
                lower = Affine(band.lower.line.slope + line.slope, band.lower.line.intercept + line.intercept - threshold)
                upper = Affine(band.upper.line.slope + line.slope, band.upper.line.intercept + line.intercept - threshold)
                lv = lower.at(a), lower.at(b)
                below |= min(lv) < 0 or (lv == (0, 0) and not band.lower.strict)
                above |= max(upper.at(a), upper.at(b)) > 0
            for atom, h in self._query_slices(component, curve):
                gap = atom.lower.value + h - threshold
                below |= gap < 0 or (gap == 0 and not atom.lower.strict)
                above |= atom.upper.value + h > threshold
        return {"at_or_below": bool(below), "above": bool(above)}

    def readiness(self, now, new_work):
        now, p = self._query(now, new_work)
        minima, maxima = [], []
        for component in self.components:
            if not (component.bands or component.points):
                continue
            curve = self._remote_curve(component, now, p)
            for band, line, a, b in self._overlaps(component, curve):
                for bound, outputs, minimize in ((band.lower, minima, True), (band.upper, maxima, False)):
                    total = Affine(bound.line.slope + line.slope, bound.line.intercept + line.intercept)
                    values = total.at(a), total.at(b)
                    value = min(values) if minimize else max(values)
                    outputs.append(Endpoint(value, total.slope == 0 and not bound.strict))
            for atom, h in self._query_slices(component, curve):
                minima.append(Endpoint(atom.lower.value + h, not atom.lower.strict))
                maxima.append(Endpoint(atom.upper.value + h, not atom.upper.strict))
        if not minima:
            return None
        low, high = min(e.value for e in minima), max(e.value for e in maxima)
        return (Endpoint(low, any(e.value == low and e.attained for e in minima)), Endpoint(high, any(e.value == high and e.attained for e in maxima)))

    def certificate(self, now, new_work, local_duration, deadline):
        now, p = self._query(now, new_work)
        duration, deadline = q(local_duration), q(deadline)
        if duration <= 0:
            raise ValueError("Local duration must be positive.")
        local = now + duration
        threshold = min(local, deadline)
        exists = self.mode_exists(now, p, threshold)
        if not any(exists.values()):
            action, uniform = "INCONSISTENT_MODEL", "EMPTY"
        elif not exists["above"]:
            action = uniform = "REMOTE"
        else:
            action = "LOCAL" if local <= deadline else "NO_CERTIFIED_ACTION"
            uniform = "MIXED" if exists["at_or_below"] else ("LOCAL" if local <= deadline else "NO_FEASIBLE_MODE")
        return {"action": action, "uniform_mode": uniform, "threshold": threshold, **exists, "scope": "exact_constant_theta_delta_model_only"}

    def support_rows(self):
        def line(bound):
            return {"slope": str(bound.line.slope), "intercept": str(bound.line.intercept), "strict": bound.strict}
        return [{
            "bands": [{"left": str(b.left), "right": str(b.right), "lower": line(b.lower), "upper": line(b.upper)} for b in c.bands],
            "points": [{"theta": str(p.theta), "lower": {"value": str(p.lower.value), "strict": p.lower.strict}, "upper": {"value": str(p.upper.value), "strict": p.upper.strict}} for p in c.points],
        } for c in self.components]
