"""Whole-set parity on fixed controls, after eliminating prior generator weights."""

from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_shared_scale_planar_reference_v1 as base

z3 = base.z3
CHECKS = Counter()
OBSERVATIONS = []


def free_constant_names(expression):
    result = set()
    pending = [expression]
    while pending:
        node = pending.pop()
        if z3.is_quantifier(node):
            raise AssertionError("Residual quantifier after exact prior elimination")
        if z3.is_const(node) and node.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            result.add(str(node.decl().name()))
        pending.extend(node.children())
    return result


def band_formula(theta, delta, band):
    cells = []
    for component in band.components:
        for piece in component.bands:
            low = base.real(piece.lower.line.slope) * theta + base.real(piece.lower.line.intercept)
            high = base.real(piece.upper.line.slope) * theta + base.real(piece.upper.line.intercept)
            cells.append(z3.And(theta > base.real(piece.left), theta < base.real(piece.right),
                                delta > low if piece.lower.strict else delta >= low,
                                delta < high if piece.upper.strict else delta <= high))
        for point in component.points:
            cells.append(z3.And(theta == base.real(point.theta),
                                delta > base.real(point.lower.value) if point.lower.strict else delta >= base.real(point.lower.value),
                                delta < base.real(point.upper.value) if point.upper.strict else delta <= base.real(point.upper.value)))
    return z3.Or(*cells)


class ContinuousSetControls(unittest.TestCase):
    def test_every_fixed_history_state(self):
        for case in base.CORPUS["cases"]:
            with self.subTest(case=case["id"]):
                submits = [row[0] for row in case["jobs"]]
                work = [row[1] for row in case["jobs"]]
                vertices = [cell["vertices"] for cell in case["cells"]]
                planes = [cell["halfplanes"] for cell in case["cells"]]
                planar = base.PlanarPosterior(submits, work, vertices, planes)
                unmerged = base.PlanarPosterior(submits, work, vertices, planes, merge_cells=False)
                band = base.BandPosterior(submits, work, vertices, planes)
                literal, theta, delta, departures = base.literal_model(case)
                weights = [z3.Real(f"lambda_{index}_{j}") for index, cell in enumerate(case["cells"])
                           for j in range(len(cell["vertices"]))]
                quantified_prior = z3.Exists(weights, z3.And(*literal.assertions()))
                eliminated = z3.TryFor(z3.Tactic("qe"), 1000)(quantified_prior).as_expr()
                self.assertLessEqual(free_constant_names(eliminated), {"theta", "delta"})
                CHECKS["exact_prior_eliminations"] += 1
                predicates = [eliminated]
                for history_index, report in enumerate([None] + case["reports"]):
                    if report is not None:
                        count, tau = report
                        for method in (planar, unmerged, band):
                            method.update(count, tau)
                        if count:
                            predicates.append(departures[count - 1] <= base.real(tau))
                        if count < len(departures):
                            predicates.append(departures[count] > base.real(tau))
                    specification = z3.And(*predicates)
                    expressions = {
                        "planar": z3.Or(*(base.geometric_formula(theta, delta, cell) for group in planar.groups for cell in group)),
                        "planar_no_merge": z3.Or(*(base.geometric_formula(theta, delta, cell) for group in unmerged.groups for cell in group)),
                        "band": band_formula(theta, delta, band),
                    }
                    for name, expression in expressions.items():
                        solver = z3.SolverFor("QF_LRA")
                        solver.set(timeout=1000)
                        solver.add(z3.Xor(specification, expression))
                        status = solver.check()
                        CHECKS["set_xor_checks"] += 1
                        self.assertEqual(status, z3.unsat,
                                         (case["id"], history_index, name, str(status),
                                          str(solver.model()) if status == z3.sat else solver.reason_unknown() if status == z3.unknown else ""))
                        CHECKS[name + "_xor_unsat"] += 1
                    CHECKS["history_states"] += 1
                    OBSERVATIONS.append({"id": case["id"], "history_index": history_index,
                                         "all_three_full_set_xor_unsat": True,
                                         "planar_counts": planar.representation_counts()})


if __name__ == "__main__":
    unittest.main()
