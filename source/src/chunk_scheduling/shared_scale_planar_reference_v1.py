"""Independent rational NNC-cell FIFO reference; only departure hulls are shared."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction as F

from shared_scale_band_posterior_v1 import DepartureEnvelopes


def rational(value):
    if isinstance(value, F):
        return value
    if type(value) not in (int, str):
        raise TypeError("Exact int, rational string or Fraction required")
    return F(value)


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def unique_sorted(points):
    result = []
    for point in sorted(points):
        if not result or point != result[-1]:
            result.append(point)
    return result


def convex_hull(points):
    points = unique_sorted(points)
    if len(points) < 3:
        return tuple(points)
    lower, upper = [], []
    for point in points:
        while len(lower) > 1 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) > 1 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return tuple(lower[:-1] + upper[:-1])


def area2(vertices):
    if len(vertices) < 3:
        return F(0)
    return sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(vertices, vertices[1:] + vertices[:1]))


def edges(vertices):
    if len(vertices) == 1:
        return ()
    if len(vertices) == 2:
        return ((vertices[0], vertices[1]),)
    return tuple(zip(vertices, vertices[1:] + vertices[:1]))


def midpoint(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def on_segment(point, a, b):
    return cross(a, b, point) == 0 and all(min(a[i], b[i]) <= point[i] <= max(a[i], b[i]) for i in (0, 1))


def in_closure(point, vertices):
    if not vertices:
        return False
    if len(vertices) == 1:
        return point == vertices[0]
    if len(vertices) == 2:
        return on_segment(point, *vertices)
    return all(cross(a, b, point) >= 0 for a, b in edges(vertices))


def in_relative_interior(point, vertices):
    if len(vertices) == 1:
        return point == vertices[0]
    if len(vertices) == 2:
        return point not in vertices and on_segment(point, *vertices)
    return all(cross(a, b, point) > 0 for a, b in edges(vertices))


def normalize_plane(plane):
    a, b, c = plane
    scale = abs(a) if a else abs(b) if b else abs(c) if c else F(1)
    return (a / scale, b / scale, c / scale)


def gap(plane, point):
    return plane[0] * point[0] + plane[1] * point[1] - plane[2]


def clip_closed(vertices, plane):
    if not vertices:
        return ()
    values = [gap(plane, point) for point in vertices]
    if max(values) <= 0:
        return vertices
    if min(values) > 0:
        return ()
    if len(vertices) == 1:
        return ()
    result = []
    boundary = edges(vertices)
    for a, b in boundary:
        ga, gb = gap(plane, a), gap(plane, b)
        if ga <= 0:
            result.append(a)
        if (ga < 0 < gb) or (gb < 0 < ga):
            ratio = ga / (ga - gb)
            result.append((a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])))
        if gb == 0 or (len(vertices) == 2 and gb < 0):
            result.append(b)
    # Clipping preserves cyclic order; canonical hull removes duplicate and
    # collinear closure vertices, including a collapsed line or point.
    return convex_hull(result)


@dataclass(frozen=True)
class Cell:
    vertices: tuple
    strict: tuple

    @classmethod
    def make(cls, vertices, strict=()):
        if not vertices:
            return None
        active = []
        for plane in strict:
            values = [gap(plane, point) for point in vertices]
            if max(values) > 0:
                raise AssertionError("Strict plane does not contain the weak closure")
            if min(values) == 0:
                return None
            if max(values) == 0:
                active.append(normalize_plane(plane))
        return cls(tuple(vertices), tuple(unique_sorted(active)))

    def contains(self, point):
        return in_closure(point, self.vertices) and all(gap(plane, point) < 0 for plane in self.strict)

    @property
    def scope(self):
        return min(p[0] for p in self.vertices), max(p[0] for p in self.vertices)

    def clip(self, plane, strict=False):
        vertices = clip_closed(self.vertices, plane)
        restrictions = self.strict + (normalize_plane(plane),) if strict else self.strict
        return Cell.make(vertices, restrictions)

    def key(self):
        return (self.vertices, tuple(self.contains(p) for p in self.vertices),
                tuple(self.contains(midpoint(a, b)) for a, b in edges(self.vertices)))


def face_samples(a, b, constituent_vertices):
    knots = unique_sorted([a, b] + [p for p in constituent_vertices if on_segment(p, a, b)])
    return knots + [midpoint(x, y) for x, y in zip(knots, knots[1:])]


def boundary_planes(vertices, included_vertices, included_edges):
    strict = []
    if len(vertices) == 2:
        axis = 0 if vertices[0][0] != vertices[1][0] else 1
        for index, included in enumerate(included_vertices):
            if not included:
                coeff = [-F(1), F(0)] if axis == 0 else [F(0), -F(1)]
                if index:
                    coeff = [-x for x in coeff]
                strict.append((coeff[0], coeff[1], coeff[axis] * vertices[index][axis]))
    elif len(vertices) > 2:
        facets = []
        for a, b in edges(vertices):
            dx, dy = b[0] - a[0], b[1] - a[1]
            facets.append(normalize_plane((dy, -dx, dy * a[0] - dx * a[1])))
        for index, included in enumerate(included_edges):
            if not included:
                strict.append(facets[index])
        for index, included in enumerate(included_vertices):
            if not included and included_edges[index - 1] and included_edges[index]:
                strict.append(tuple(a + b for a, b in zip(facets[index - 1], facets[index])))
    return strict


def try_join(left, right):
    if left.scope[1] != right.scope[0]:
        return None
    all_vertices = left.vertices + right.vertices
    hull = convex_hull(all_vertices)
    if area2(hull) != area2(left.vertices) + area2(right.vertices):
        return None
    present = lambda p: left.contains(p) or right.contains(p)
    included_vertices = [present(p) for p in hull]
    included_edges = []
    for a, b in edges(hull):
        samples = [p for p in face_samples(a, b, all_vertices) if p != a and p != b]
        states = [present(p) for p in samples]
        if any(state != states[0] for state in states):
            return None
        included = states[0]
        if not included and (present(a) or present(b)):
            return None
        included_edges.append(included)
    if len(hull) == 2 and (not included_edges or not included_edges[0]):
        return None
    seam = left.scope[1]
    section = clip_closed(clip_closed(hull, (F(1), F(0), seam)), (-F(1), F(0), -seam))
    if len(section) == 1:
        samples = list(section)
    elif len(section) == 2:
        seam_vertices = []
        for cell in (left, right):
            cut = clip_closed(clip_closed(cell.vertices, (F(1), F(0), seam)), (-F(1), F(0), -seam))
            seam_vertices.extend(cut)
        samples = face_samples(*section, seam_vertices)
    else:
        raise AssertionError("Vertical section must be a point or segment")
    if any(in_relative_interior(p, hull) and not present(p) for p in samples):
        return None
    result = Cell.make(hull, boundary_planes(hull, included_vertices, included_edges))
    if result is None:
        return None
    return result


def compact(cells, merge=True):
    result = []
    for cell in cells:
        if result and cell.key() == result[-1].key():
            continue
        result.append(cell)
        if merge:
            while len(result) > 1:
                joined = try_join(result[-2], result[-1])
                if joined is None:
                    break
                result[-2:] = [joined]
    return result


def initial_cell(vertices, halfplanes):
    rows = [tuple(map(rational, p)) for p in vertices]
    if not rows or any(len(p) != 2 for p in rows):
        raise ValueError("Explicit nonempty bounded convex closure required")
    if len(rows) > 1 and rows[0] == rows[-1]:
        rows.pop()
    if len(unique_sorted(rows)) != len(rows):
        raise ValueError("Duplicate nonclosing vertices are not supported")
    if len(rows) > 2 and any(cross(rows[0], rows[1], p) for p in rows):
        if area2(tuple(rows)) < 0:
            rows.reverse()
        if any(cross(a, b, p) < 0 for a, b in edges(tuple(rows)) for p in rows):
            raise ValueError("Closure vertices must be cyclic and convex")
    hull = convex_hull(rows)
    parsed = []
    for a, b, c, strict in halfplanes:
        if type(strict) is not bool:
            raise TypeError("Strict flag must be Boolean")
        plane = tuple(map(rational, (a, b, c)))
        if any(gap(plane, p) > 0 for p in hull):
            raise ValueError("Additional plane must weakly contain the supplied closure")
        parsed.append((plane, strict))
    cell = Cell.make(hull)
    for plane, strict in [((-F(1), F(0), F(0)), True), ((F(0), -F(1), F(0)), False)] + parsed:
        if cell is None:
            break
        cell = cell.clip(plane, strict)
    return cell


class PlanarPosterior:
    """Exact NNC polygon/segment/point unions with ordered report overlays."""

    def __init__(self, submits, work, initial_cells, initial_halfplanes=None, *, merge_cells=True):
        self.submits = tuple(map(rational, submits))
        self.work = tuple(map(rational, work))
        if len(self.submits) != len(self.work) or any(t < 0 for t in self.submits):
            raise ValueError("Known nonnegative submissions and matching work required")
        self.envelopes = DepartureEnvelopes(self.submits, self.work)
        prior = list(initial_cells)
        if not prior:
            raise ValueError("Explicit bounded prior components required")
        extra = [()] * len(prior) if initial_halfplanes is None else list(initial_halfplanes)
        if len(extra) != len(prior):
            raise ValueError("Prior component count mismatch")
        self.groups = []
        for vertices, planes in zip(prior, extra):
            cell = initial_cell(vertices, planes)
            self.groups.append([] if cell is None else [cell])
        self.reports = []
        self.merge_cells = merge_cells

    def _restriction(self, cells, count, tau, unfinished):
        if not cells:
            return []
        left, right = cells[0].scope[0], cells[-1].scope[1]
        curve = self.envelopes.curve(count, left, right)
        if curve.atom is not None:
            planes = [(left, right, F(0), curve.atom)]
        else:
            planes = [(p.left, p.right, p.line.slope, p.line.intercept) for p in curve.pieces]
        result = []
        i = j = 0
        while i < len(cells) and j < len(planes):
            cell = cells[i]
            a, b = cell.scope
            c, d, slope, intercept = planes[j]
            low, high = max(a, c), min(b, d)
            if low <= high:
                clipped = cell.clip((-F(1), F(0), -low))
                if clipped is not None:
                    clipped = clipped.clip((F(1), F(0), high))
                if clipped is not None:
                    plane = (slope, F(1), tau - intercept)
                    if unfinished:
                        plane = tuple(-v for v in plane)
                    clipped = clipped.clip(plane, strict=unfinished)
                    if clipped is not None:
                        result.append(clipped)
            # At a shared endpoint, either continuous departure branch is exact.
            # Advance a cell first on ties so a new cell can retain that point.
            if b <= d:
                i += 1
            else:
                j += 1
        return compact(result, self.merge_cells)

    def update(self, completed, report_time):
        if type(completed) is not int or not 0 <= completed <= len(self.work):
            raise ValueError("Completed prefix must be in [0,n]")
        tau = rational(report_time)
        if tau < 0:
            raise ValueError("Nonnegative report time required")
        groups = []
        for cells in self.groups:
            if completed:
                cells = self._restriction(cells, completed, tau, False)
            if completed < len(self.work):
                cells = self._restriction(cells, completed + 1, tau, True)
            groups.append(cells)
        self.groups = groups
        self.reports.append((completed, tau))
        return self

    def contains(self, point):
        point = tuple(map(rational, point))
        if len(point) != 2:
            raise ValueError("Point is (theta, delta)")
        return any(cell.contains(point) for group in self.groups for cell in group)

    def certificate(self, now, new_work, local_duration, deadline):
        now, work, local, deadline = map(rational, (now, new_work, local_duration, deadline))
        if now < 0 or deadline < 0 or work <= 0 or local <= 0:
            raise ValueError("Nonnegative clocks and positive work/duration required")
        if self.submits and now <= self.submits[-1]:
            raise ValueError("New request must follow the last known submission")
        if any(tau > now for _, tau in self.reports):
            raise ValueError("A future as-of report cannot be used")
        threshold = min(deadline, now + local)
        below = above = False
        for group in self.groups:
            for cell in group:
                if not above:
                    for theta, delta in cell.vertices:
                        ready = max(now, self.envelopes.value(len(self.work), theta)) if self.work else now
                        if delta + ready + theta * work > threshold:
                            above = True
                            break
                if not below:
                    feasible = cell.clip((work, F(1), threshold - now))
                    if feasible is not None and self.work:
                        left, right = cell.scope
                        curve = self.envelopes.curve(len(self.work), left, right)
                        lines = [(F(0), curve.atom)] if curve.atom is not None else [(p.line.slope, p.line.intercept) for p in curve.pieces]
                        for slope, intercept in lines:
                            feasible = feasible.clip((slope + work, F(1), threshold - intercept))
                            if feasible is None:
                                break
                    below = feasible is not None
                if below and above:
                    break
            if below and above:
                break
        if not below and not above:
            action, mode = "INCONSISTENT_MODEL", "EMPTY"
        elif not above:
            action = mode = "REMOTE"
        else:
            timely = now + local <= deadline
            action = "LOCAL" if timely else "NO_CERTIFIED_ACTION"
            mode = "MIXED" if below else "LOCAL" if timely else "NO_FEASIBLE_MODE"
        return {"status": "EXACT", "action": action, "uniform_mode": mode, "threshold": threshold,
                "at_or_below": below, "above": above}

    def representation_counts(self):
        cells = [cell for group in self.groups for cell in group]
        return {"components": len(self.groups), "cells": len(cells),
                "closure_vertices": sum(len(cell.vertices) for cell in cells),
                "active_strict_planes": sum(len(cell.strict) for cell in cells), "reports": len(self.reports)}
