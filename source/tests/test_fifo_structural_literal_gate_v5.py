"""Same large-history gate with exact per-component prior elimination."""

from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_fifo_structural_literal_gate_v4 as old
from test_shared_scale_planar_continuous_set_v2 import free_constant_names

z3 = old.z3
CHECKS = Counter()
OBSERVATIONS = []


def eliminated_prior(case):
    theta, delta = z3.Reals("theta delta")
    parts = []
    for index, cell in enumerate(case["cells"]):
        vertices = cell["vertices"]
        weights = [z3.Real(f"prior_{index}_{j}") for j in range(len(vertices))]
        generator = old.base.vertex_hull_formula(theta, delta, vertices, f"prior_{index}")
        strict_planes = [(old.base.real(a) * theta + old.base.real(b) * delta < old.base.real(c) if strict else
                          old.base.real(a) * theta + old.base.real(b) * delta <= old.base.real(c))
                         for a, b, c, strict in cell["halfplanes"]]
        expression = z3.TryFor(z3.Tactic("qe"), 1000)(z3.Exists(weights, z3.And(generator, *strict_planes))).as_expr()
        if not free_constant_names(expression) <= {"theta", "delta"}:
            raise AssertionError("Unexpected oracle constant")
        parts.append(expression)
        CHECKS["exact_component_eliminations"] += 1
    return z3.And(theta > 0, delta >= 0, z3.Or(*parts))


class LargeHistoryLiteralGate(unittest.TestCase):
    def test_first_block_all_cells_all_states(self):
        self.assertEqual(len(old.SELECTED), 32)
        priors = {}
        for components in (1, 4):
            case = next(case for case in old.SELECTED if case["factors"]["components"] == components)
            priors[components] = (case["cells"], eliminated_prior(case))
        for case in old.SELECTED:
            with self.subTest(input_id=case["id"]):
                cells, prior = priors[case["factors"]["components"]]
                self.assertEqual(case["cells"], cells)
                _, theta, delta, departures = old.base.literal_model(case)
                methods = old.methods_for(case)
                predicates = [prior]
                for history_index, stage in enumerate([None] + case["stages"]):
                    if stage is not None:
                        count, tau = stage["report"]
                        for method in methods.values():
                            old.apply_report(method, stage["report"])
                        if count:
                            predicates.append(departures[count - 1] <= old.base.real(tau))
                        if count < len(departures):
                            predicates.append(departures[count] > old.base.real(tau))
                    specification = z3.And(*predicates)
                    for name, method in methods.items():
                        old.check(z3.Xor(specification, old.method_formula(name, method, theta, delta)), z3.unsat,
                                  (case["id"], history_index, name))
                        CHECKS[name + "_full_set_xor_unsat"] += 1
                    CHECKS["history_states"] += 1
                    if stage is None:
                        continue
                    now, work, local, deadline = map(F, stage["query"])
                    arrival = old.base.real(now) + delta
                    start = z3.If(departures[-1] >= arrival, departures[-1], arrival)
                    remote = start + theta * old.base.real(work)
                    threshold = min(now + local, deadline)
                    expected = (old.query_exists(specification, remote <= old.base.real(threshold)),
                                old.query_exists(specification, remote > old.base.real(threshold)))
                    for name, method in methods.items():
                        result = method.certificate(*stage["query"])
                        self.assertEqual(result["status"], "EXACT")
                        self.assertEqual((result["at_or_below"], result["above"]), expected,
                                         (case["id"], history_index, name, "live"))
                        saved = old.SAVED[case["id"] + ":" + name]["queries"][history_index - 1]
                        self.assertEqual((saved["at_or_below"], saved["above"]), expected,
                                         (case["id"], history_index, name, "saved"))
                        self.assertEqual(F(saved["threshold"]), threshold)
                        CHECKS[name + "_live_and_saved_queries"] += 1
                    CHECKS["query_tuples"] += 1
                CHECKS["inputs"] += 1
                OBSERVATIONS.append({"input_id": case["id"], "history_states": len(case["stages"]) + 1,
                                     "query_tuples": len(case["stages"]), "all_checks_passed": True})
        CHECKS.update(old.CHECKS)
        self.assertEqual(CHECKS["history_states"], 688)
        self.assertEqual(CHECKS["query_tuples"], 656)


if __name__ == "__main__":
    unittest.main()
