"""Full continuous-set and query parity for the strengthened comparable methods."""

from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_shared_scale_planar_reference_v1 as base
from test_shared_scale_planar_continuous_set_v2 import band_formula, free_constant_names
from shared_scale_comparable_methods_v2 import (
    CompletionEnvelopeSMT, FacetPlanarPosterior, TightBandPosterior,
)

z3 = base.z3
CHECKS = Counter()
OBSERVATIONS = []


def weak_halfplanes(raw_vertices):
    vertices = [tuple(map(F, point)) for point in raw_vertices]
    if len(vertices) == 1:
        x, y = vertices[0]
        return [(1, 0, x, False), (-1, 0, -x, False),
                (0, 1, y, False), (0, -1, -y, False)]
    if len(vertices) == 2:
        (x, y), (u, v) = vertices
        a, b, c = v - y, x - u, (v - y) * x + (x - u) * y
        return [(a, b, c, False), (-a, -b, -c, False),
                (1, 0, max(x, u), False), (-1, 0, -min(x, u), False),
                (0, 1, max(y, v), False), (0, -1, -min(y, v), False)]
    signed_area = sum(x * v - u * y for (x, y), (u, v)
                      in zip(vertices, vertices[1:] + vertices[:1]))
    if signed_area <= 0:
        raise AssertionError("Corpus must supply nondegenerate CCW convex polygons")
    return [(v - y, x - u, (v - y) * x + (x - u) * y, False)
            for (x, y), (u, v) in zip(vertices, vertices[1:] + vertices[:1])]


def build_methods(case):
    submits, work = zip(*case["jobs"]) if case["jobs"] else ((), ())
    vertices = [cell["vertices"] for cell in case["cells"]]
    planes = [weak_halfplanes(cell["vertices"]) + cell["halfplanes"]
              for cell in case["cells"]]
    jobs = [{"t": t, "p": p} for t, p in case["jobs"]]
    return {
        "band_v2": TightBandPosterior(submits, work, vertices, planes),
        "planar_v2": FacetPlanarPosterior(submits, work, vertices, planes),
        "envelope_smt_v2": CompletionEnvelopeSMT(
            jobs, [{"halfplanes": rows} for rows in planes], timeout_ms=1000),
    }


def apply_report(method, report):
    if isinstance(method, CompletionEnvelopeSMT):
        method.add_report(*report)
    else:
        method.update(*report)


def method_formula(name, method, theta, delta):
    if name == "band_v2":
        return band_formula(theta, delta, method)
    if name == "planar_v2":
        return z3.Or(*(base.geometric_formula(theta, delta, cell)
                       for group in method.groups for cell in group))
    return z3.substitute(z3.And(*method.solver.assertions()),
                         (method.theta, theta), (method.delta, delta))


def require_unsat(expression, location):
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(expression)
    status = solver.check()
    detail = str(solver.model()) if status == z3.sat else (
        solver.reason_unknown() if status == z3.unknown else "")
    if status != z3.unsat:
        raise AssertionError((location, str(status), detail))
    CHECKS["set_xor_unsat"] += 1


def existence(solver, condition):
    solver.push()
    try:
        solver.add(condition)
        status = solver.check()
        CHECKS["literal_query_checks"] += 1
        if status == z3.unknown:
            raise AssertionError(solver.reason_unknown())
        return status == z3.sat
    finally:
        solver.pop()


class ComparableControls(unittest.TestCase):
    def test_fixed_continuous_sets_and_queries(self):
        for case in base.CORPUS["cases"]:
            with self.subTest(case=case["id"]):
                methods = build_methods(case)
                literal, theta, delta, departures = base.literal_model(case)
                weights = [z3.Real(f"lambda_{index}_{j}")
                           for index, cell in enumerate(case["cells"])
                           for j in range(len(cell["vertices"]))]
                prior = z3.TryFor(z3.Tactic("qe"), 1000)(
                    z3.Exists(weights, z3.And(*literal.assertions()))).as_expr()
                self.assertLessEqual(free_constant_names(prior), {"theta", "delta"})
                CHECKS["exact_prior_eliminations"] += 1
                predicates = [prior]
                for history_index, report in enumerate([None] + case["reports"]):
                    if report is not None:
                        count, tau = report
                        for method in methods.values():
                            apply_report(method, report)
                        if count:
                            predicates.append(departures[count - 1] <= base.real(tau))
                            literal.add(departures[count - 1] <= base.real(tau))
                        if count < len(departures):
                            predicates.append(departures[count] > base.real(tau))
                            literal.add(departures[count] > base.real(tau))
                    specification = z3.And(*predicates)
                    for name, method in methods.items():
                        require_unsat(z3.Xor(specification, method_formula(name, method, theta, delta)),
                                      (case["id"], history_index, name))
                        CHECKS[name + "_full_set_unsat"] += 1
                    CHECKS["history_states"] += 1
                query = case["query"]
                now, pnew, local, deadline = [F(query[key]) for key in
                                              ("now", "pnew", "local_duration", "deadline")]
                arrival = base.real(now) + delta
                start = z3.If(departures[-1] >= arrival, departures[-1], arrival) if departures else arrival
                remote = start + theta * base.real(pnew)
                threshold = min(now + local, deadline)
                expected = (existence(literal, remote <= base.real(threshold)),
                            existence(literal, remote > base.real(threshold)))
                results = []
                for name, method in methods.items():
                    result = method.certificate(now, pnew, local, deadline)
                    self.assertEqual(result["status"], "EXACT", (case["id"], name, result))
                    self.assertEqual((result["at_or_below"], result["above"]), expected,
                                     (case["id"], name, result))
                    self.assertEqual(result["threshold"], threshold)
                    if "expected_mode" in case:
                        self.assertEqual(result["uniform_mode"], case["expected_mode"])
                    if "expected_action" in case:
                        self.assertEqual(result["action"], case["expected_action"])
                    results.append({key: result[key] for key in
                                    ("action", "uniform_mode", "threshold", "at_or_below", "above")})
                    CHECKS[name + "_queries"] += 1
                self.assertEqual(results[0], results[1])
                self.assertEqual(results[0], results[2])
                CHECKS["cases"] += 1
                CHECKS["mode_" + results[0]["uniform_mode"]] += 1
                OBSERVATIONS.append({"id": case["id"], "history_states": 1 + len(case["reports"]),
                                     "sides": expected, "action": results[0]["action"],
                                     "mode": results[0]["uniform_mode"]})

    def test_common_domain_and_availability_guards(self):
        case = {"jobs": [[0, 1]], "cells": [{"vertices": [[1, 0]], "halfplanes": []}]}
        for name, method in build_methods(case).items():
            for query in ((0, 1, 1, 2), (-1, 1, 1, 2), (1, 0, 1, 2),
                          (1, 1, 0, 2), (1, 1, 1, -1)):
                with self.subTest(method=name, query=query):
                    with self.assertRaises(ValueError):
                        method.certificate(*query)
                    CHECKS["guard_checks"] += 1
            for report in ((-1, 1), (2, 1), (True, 1), (0, -1)):
                with self.assertRaises(ValueError):
                    apply_report(method, report)
                CHECKS["guard_checks"] += 1
            apply_report(method, (1, 3))
            with self.assertRaises(ValueError):
                method.certificate(2, 1, 1, 4)
            CHECKS["guard_checks"] += 1
        bad = {"jobs": [[-1, 1]], "cells": case["cells"]}
        with self.assertRaises(ValueError):
            build_methods(bad)
        CHECKS["guard_checks"] += 1


if __name__ == "__main__":
    unittest.main()
