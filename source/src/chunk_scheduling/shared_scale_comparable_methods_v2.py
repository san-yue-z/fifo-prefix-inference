"""Prospective comparable methods; preserve every original measured source."""

from fractions import Fraction as F

from shared_scale_band_posterior_v1 import Affine, BandPosterior, Curve, Piece, q
from shared_scale_planar_reference_v1 import PlanarPosterior, compact, gap
from shared_scale_envelope_smt_v1 import EnvelopeSMT


def validate_query(now, work, local, deadline, submits, reports):
    now, work, local, deadline = map(q, (now, work, local, deadline))
    if now < 0 or deadline < 0 or work <= 0 or local <= 0:
        raise ValueError("Nonnegative clocks and positive work/duration required")
    if submits and now <= submits[-1]:
        raise ValueError("New request must strictly follow the known ledger")
    if any(timestamp > now for _, timestamp in reports):
        raise ValueError("Future as-of report is not available")
    return now, work, local, deadline


def classify(below, above, now, local, deadline, threshold):
    if not below and not above:
        action, mode = "INCONSISTENT_MODEL", "EMPTY"
    elif not above:
        action = mode = "REMOTE"
    else:
        timely = now + local <= deadline
        action = "LOCAL" if timely else "NO_CERTIFIED_ACTION"
        mode = "MIXED" if below else "LOCAL" if timely else "NO_FEASIBLE_MODE"
    return {"status": "EXACT", "action": action, "uniform_mode": mode,
            "threshold": threshold, "at_or_below": bool(below), "above": bool(above)}


class TightBandPosterior(BandPosterior):
    def __init__(self, submits, work, initial_cells, initial_halfplanes=None):
        super().__init__(submits, work, initial_cells, initial_halfplanes)
        if any(value < 0 for value in self.submits):
            raise ValueError("Nonnegative submissions required")
        self.all_completed = not self.work
        self._tighten_scopes()

    def _tighten_scopes(self):
        for component in self.components:
            candidates = []
            if component.bands:
                candidates += [component.bands[0].left, component.bands[-1].right]
            if component.points:
                candidates += [component.points[0].theta, component.points[-1].theta]
            if candidates:
                component.left, component.right = min(candidates), max(candidates)

    def update(self, completed, report_time):
        if q(report_time) < 0:
            raise ValueError("Nonnegative report time required")
        super().update(completed, report_time)
        self.all_completed |= completed == len(self.work)
        self._tighten_scopes()
        return self

    def _remote_curve(self, component, now, new_work):
        if not self.all_completed:
            return super()._remote_curve(component, now, new_work)
        left, right = component.left, component.right
        if left == right:
            return Curve((), now + new_work * left)
        return Curve((Piece(left, right, Affine(new_work, now)),))

    def certificate(self, now, new_work, local_duration, deadline):
        now, work, local, deadline = validate_query(now, new_work, local_duration, deadline, self.submits, self.reports)
        result = super().certificate(now, work, local, deadline)
        result["status"] = "EXACT"
        return result


def clip_fast(cell, plane, strict=False):
    highest = max(gap(plane, point) for point in cell.vertices)
    if highest <= 0 and not strict or highest < 0:
        return cell
    return cell.clip(plane, strict)


class FacetPlanarPosterior(PlanarPosterior):
    def __init__(self, submits, work, initial_cells, initial_halfplanes=None):
        super().__init__(submits, work, initial_cells, initial_halfplanes)
        self.all_completed = not self.work

    def _restriction(self, cells, count, tau, unfinished):
        if not cells:
            return []
        if not unfinished:
            curve = self.envelopes.curve(count, cells[0].scope[0], cells[-1].scope[1])
            lines = [(F(0), curve.atom)] if curve.atom is not None else [(p.line.slope, p.line.intercept) for p in curve.pieces]
            result = []
            # A completed maximum is a conjunction of affine halfplanes. It
            # remains convex; do not split and rejoin it unnecessarily.
            for cell in cells:
                for slope, intercept in lines:
                    cell = clip_fast(cell, (slope, F(1), tau - intercept))
                    if cell is None:
                        break
                if cell is not None:
                    result.append(cell)
            return compact(result)
        result, partial = [], []

        def flush():
            if partial:
                result.extend(super(FacetPlanarPosterior, self)._restriction(partial, count, tau, True))
                partial.clear()

        for cell in cells:
            maximum = max(delta + self.envelopes.value(count, theta) for theta, delta in cell.vertices)
            if maximum <= tau:
                continue
            theta_min = cell.scope[0]
            delta_min = min(point[1] for point in cell.vertices)
            lower_bound = delta_min + self.envelopes.value(count, theta_min)
            if lower_bound > tau:
                flush()
                result.append(cell)
            else:
                partial.append(cell)
        flush()
        return compact(result)

    def update(self, completed, report_time):
        super().update(completed, report_time)
        self.all_completed |= completed == len(self.work)
        return self

    def certificate(self, now, new_work, local_duration, deadline):
        now, work, local, deadline = validate_query(now, new_work, local_duration, deadline, self.submits, self.reports)
        threshold = min(deadline, now + local)
        below = above = False
        for group in self.groups:
            for cell in group:
                values = []
                for theta, delta in cell.vertices:
                    ready = now if self.all_completed else max(now, self.envelopes.value(len(self.work), theta))
                    value = delta + ready + theta * work
                    values.append(value)
                    above |= value > threshold
                    below |= value < threshold or (value == threshold and cell.contains((theta, delta)))
                if below and above:
                    return classify(below, above, now, local, deadline, threshold)
                if not below and not (self.all_completed and min(values) > threshold):
                    feasible = clip_fast(cell, (work, F(1), threshold - now))
                    if feasible is not None and not self.all_completed:
                        curve = self.envelopes.curve(len(self.work), *cell.scope)
                        lines = [(F(0), curve.atom)] if curve.atom is not None else [(p.line.slope, p.line.intercept) for p in curve.pieces]
                        for slope, intercept in lines:
                            feasible = clip_fast(feasible, (slope + work, F(1), threshold - intercept))
                            if feasible is None:
                                break
                    below = feasible is not None
                if below and above:
                    return classify(below, above, now, local, deadline, threshold)
        return classify(below, above, now, local, deadline, threshold)


class CompletionEnvelopeSMT(EnvelopeSMT):
    def __init__(self, jobs, prior_cells, timeout_ms=1000):
        super().__init__(jobs, prior_cells, timeout_ms)
        self.all_completed = not self.jobs

    def add_report(self, completed, timestamp):
        super().add_report(completed, timestamp)
        self.all_completed |= completed == len(self.jobs)

    def conditions(self, now, new_work, threshold):
        now, work, threshold = map(q, (now, new_work, threshold))
        validate_query(now, work, F(1), max(F(0), threshold), [job[0] for job in self.jobs], self.reports)
        if not self.all_completed:
            return super().conditions(now, work, threshold)
        completion = self.delta + self.real(now) + self.theta * self.real(work)
        return completion <= self.real(threshold), completion > self.real(threshold)

    def certificate(self, now, new_work, local_duration, deadline):
        now, work, local, deadline = validate_query(now, new_work, local_duration, deadline, [job[0] for job in self.jobs], self.reports)
        threshold = min(deadline, now + local)
        conditions = self.conditions(now, work, threshold)
        statuses = []
        for condition in conditions:
            self.solver.push()
            try:
                self.solver.add(condition)
                self.sat_queries += 1
                status = self.solver.check()
                statuses.append(str(status))
            finally:
                self.solver.pop()
        if "unknown" in statuses:
            return {"status": "UNKNOWN", "action": None, "uniform_mode": None, "threshold": threshold, "sides": statuses}
        return classify(statuses[0] == "sat", statuses[1] == "sat", now, local, deadline, threshold)
