"""Retained QF-LRA with shared departure hulls, never Band posterior logic."""

from fractions import Fraction
from shared_scale_band_posterior_v1 import DepartureEnvelopes
from shared_scale_smt_reference_v1 import rational


def closed_theta_projection(planes):
    """Safe closure projection by 2D Fourier-Motzkin; strictness stays in SMT."""
    rows = [tuple(map(rational, p[:3])) for p in planes] + [(Fraction(0), Fraction(-1), Fraction(0))]
    lower = [(a, b, c) for a, b, c in rows if b < 0]
    upper = [(a, b, c) for a, b, c in rows if b > 0]
    projected = [(a, c) for a, b, c in rows if b == 0] + [(Fraction(-1), Fraction(0))]
    projected += [(ap/bp-am/bm, cp/bp-cm/bm) for am, bm, cm in lower for ap, bp, cp in upper]
    left, right = Fraction(0), None
    for a, c in projected:
        if a > 0:
            right = c/a if right is None else min(right, c/a)
        elif a < 0:
            left = max(left, c/a)
        elif c < 0:
            return None
    if right is not None and left > right:
        return None
    if right is None:
        raise ValueError("A finite closed theta projection is required for hull pruning.")
    return left, right


class EnvelopeSMT:
    """Original halfplane prior + flat max-plus clauses + one retained solver."""

    def __init__(self, jobs, prior_cells, timeout_ms=1000):
        if type(timeout_ms) is not int or timeout_ms < 1:
            raise ValueError("Finite positive solver timeout required.")
        import z3
        self.z3 = z3
        self.theta, self.delta = z3.Reals("theta delta")
        self.solver = z3.SolverFor("QF_LRA")
        self.solver.set(timeout=timeout_ms)
        self.solver.add(self.theta > 0, self.delta >= 0)
        self.jobs = [(rational(j["t"]), rational(j["p"])) for j in jobs]
        if any(t < 0 or p <= 0 for t, p in self.jobs) or any(self.jobs[i][0] <= self.jobs[i-1][0] for i in range(1, len(self.jobs))):
            raise ValueError("Increasing nonnegative submissions and positive work required.")
        self.envelopes = DepartureEnvelopes([t for t, _ in self.jobs], [p for _, p in self.jobs])
        clauses, projections = [], []
        for cell in prior_cells:
            planes, inequalities = [], []
            for row in cell["halfplanes"]:
                if len(row) != 4 or type(row[3]) is not bool:
                    raise ValueError("Exact halfplanes and Boolean strict flags required.")
                a, b, c = map(rational, row[:3])
                planes.append((a, b, c, row[3]))
                lhs = self.real(a)*self.theta + self.real(b)*self.delta
                inequalities.append(lhs < self.real(c) if row[3] else lhs <= self.real(c))
            clauses.append(z3.And(*inequalities))
            projection = closed_theta_projection(planes)
            if projection is not None:
                projections.append(projection)
        self.solver.add(z3.Or(*clauses))
        self.theta_scope = (min(p[0] for p in projections), max(p[1] for p in projections)) if projections else None
        self.compiled, self.reports, self.sat_queries = {}, [], 0

    def real(self, value):
        value = rational(value)
        return self.z3.RealVal(f"{value.numerator}/{value.denominator}")

    def _flat(self, count):
        if count not in self.compiled:
            if self.theta_scope is None:
                terms = []
            else:
                curve = self.envelopes.curve(count, *self.theta_scope)
                terms = [self.real(curve.atom)] if curve.atom is not None else [
                    self.real(line.slope)*self.theta + self.real(line.intercept)
                    for line in dict.fromkeys(piece.line for piece in curve.pieces)]
            self.compiled[count] = terms
        return self.compiled[count]

    def add_report(self, completed, timestamp):
        if type(completed) is not int or not 0 <= completed <= len(self.jobs):
            raise ValueError("Completed prefix is outside the public ledger.")
        timestamp = rational(timestamp)
        if timestamp < 0:
            raise ValueError("Report timestamp is nonnegative.")
        tau = self.real(timestamp)
        if completed:
            self.solver.add(self.z3.And(*(self.delta+term <= tau for term in self._flat(completed))))
        if completed < len(self.jobs):
            self.solver.add(self.z3.Or(*(self.delta+term > tau for term in self._flat(completed+1))))
        self.reports.append((completed, timestamp))

    def conditions(self, now, new_work, threshold):
        now, new_work, threshold = map(rational, (now, new_work, threshold))
        if now < 0 or new_work <= 0 or (self.jobs and now < self.jobs[-1][0]):
            raise ValueError("New submission must follow known jobs and have positive work.")
        if any(timestamp > now for _, timestamp in self.reports):
            raise ValueError("A future completed-prefix report is not available.")
        terms = [self.real(now)] + (self._flat(len(self.jobs)) if self.jobs else [])
        work, bound = self.theta*self.real(new_work), self.real(threshold)
        return (self.z3.And(*(self.delta+term+work <= bound for term in terms)),
                self.z3.Or(*(self.delta+term+work > bound for term in terms)))
