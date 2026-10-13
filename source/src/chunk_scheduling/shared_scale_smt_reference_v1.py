"""Independent incremental QF-LRA reference, using FIFO recurrence, not geometry."""
from fractions import Fraction


def rational(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Use exact integers, Fraction values or rational strings.")
    if not isinstance(value, (int, str, Fraction)):
        raise ValueError("Unsupported exact rational input.")
    return Fraction(value)


class SharedScaleSMT:
    """Retain one solver across completed-prefix updates and push/pop decisions.

    Public prior cells are halfplane conjunctions; their union is disjunctive.
    Cell directions are a*theta+b*delta <= c, or < c when strict=True.
    Boundedness is the experiment's supplied-prior assumption, not inferred here.
    """
    def __init__(self, jobs, prior_cells, timeout_ms=5000):
        if type(timeout_ms) is not int or timeout_ms < 1:
            raise ValueError("Finite positive solver timeout is required.")
        import z3
        self.z3 = z3
        self.theta, self.delta = z3.Reals("theta delta")
        self.solver = z3.SolverFor("QF_LRA")
        self.solver.set(timeout=timeout_ms)
        self.solver.add(self.theta > 0, self.delta >= 0)
        self.jobs = [(rational(j["t"]), rational(j["p"])) for j in jobs]
        if any(p <= 0 or t < 0 for t, p in self.jobs) or any(self.jobs[i][0] <= self.jobs[i-1][0] for i in range(1,len(self.jobs))):
            raise ValueError("Known nonnegative submission times must increase; work is positive.")
        clauses = []
        for cell in prior_cells:
            inequalities = []
            for row in cell["halfplanes"]:
                if len(row) != 4 or type(row[3]) is not bool:
                    raise ValueError("Require exact halfplanes and a Boolean strict flag.")
                a, b, c = [self.real(v) for v in row[:3]]
                lhs = a*self.theta+b*self.delta
                inequalities.append(lhs < c if row[3] else lhs <= c)
            clauses.append(z3.And(*inequalities))
        self.solver.add(z3.Or(*clauses))
        self.departures = []
        for t, p in self.jobs:
            arrival = self.real(t)+self.delta
            ready = arrival if not self.departures else z3.If(self.departures[-1] >= arrival,self.departures[-1],arrival)
            self.departures.append(ready+self.theta*self.real(p))
        self.reports = []
        self.sat_queries = 0

    def real(self, value):
        q = rational(value)
        return self.z3.RealVal(f"{q.numerator}/{q.denominator}")

    def add_report(self, completed, timestamp):
        if type(completed) is not int or not 0 <= completed <= len(self.jobs):
            raise ValueError("Completed prefix is outside the public ledger.")
        timestamp = rational(timestamp)
        if timestamp < 0:
            raise ValueError("Report timestamp is nonnegative.")
        if completed:
            self.solver.add(self.departures[completed-1] <= self.real(timestamp))
        if completed < len(self.jobs):
            self.solver.add(self.departures[completed] > self.real(timestamp))
        self.reports.append((completed,timestamp))

    def readiness(self, now, new_work):
        now, new_work = rational(now), rational(new_work)
        if now < 0 or new_work <= 0 or (self.jobs and now < self.jobs[-1][0]):
            raise ValueError("New submission must follow known jobs and have positive work.")
        if any(timestamp > now for _,timestamp in self.reports):
            raise ValueError("A future completed-prefix report is not available.")
        arrival = self.real(now)+self.delta
        ready = arrival if not self.departures else self.z3.If(self.departures[-1] >= arrival,self.departures[-1],arrival)
        return ready+self.theta*self.real(new_work)

    def feasibility(self, constraint):
        self.solver.push()
        try:
            self.solver.add(constraint)
            self.sat_queries += 1
            status = self.solver.check()
            result = {"status": str(status), "witness": None}
            if status == self.z3.sat:
                model = self.solver.model()
                result["witness"] = {name: str(model.eval(variable,model_completion=True).as_fraction())
                                     for name,variable in (("theta",self.theta),("delta",self.delta))}
            elif status == self.z3.unknown:
                result["reason"] = self.solver.reason_unknown()
            return result
        finally:
            self.solver.pop()

    def decision(self, now, new_work, local_duration, deadline):
        now, duration, deadline = rational(now), rational(local_duration), rational(deadline)
        if duration <= 0 or deadline < 0:
            raise ValueError("Local duration is positive and deadline nonnegative.")
        completion = self.readiness(now,new_work)
        local_finish = now+duration
        threshold = min(local_finish,deadline)
        alternative = "local" if local_finish <= deadline else "reject"
        sides = {"offload":self.feasibility(completion <= self.real(threshold)),
                 alternative:self.feasibility(completion > self.real(threshold))}
        if any(v["status"] == "unknown" for v in sides.values()):
            status, modes, action = "UNKNOWN", [], None
        else:
            modes = sorted(k for k,v in sides.items() if v["status"] == "sat")
            status = "INCONSISTENT" if not modes else "INVARIANT" if len(modes)==1 else "MIXED"
            action = None if not modes else modes[0] if len(modes)==1 else alternative
        return {"status":status,"possible_modes":modes,"conservative_action":action,"threshold":str(threshold),
                "side_feasibility":sides,"solver_queries_this_decision":2,"reports_retained":len(self.reports),
                "information":"public prior+known jobs+completed-prefix timestamps; no future work oracle",
                "global_optimal_control":False}


def reference_for_case(case, timeout_ms=5000):
    """Pure fixture adapter; importing this module does not import Z3."""
    solver = SharedScaleSMT(case["jobs"],case["prior_cells"],timeout_ms)
    for report in case["reports"]:
        solver.add_report(report["c"],report["tau"])
    return solver, solver.decision(case["now"],case["pnew"],case["local_duration"],case["deadline"])
