"""Complete-set and literal-query checks on every cell of one fixed block."""

from collections import Counter
from fractions import Fraction as F
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_shared_scale_planar_reference_v1 as base
from test_shared_scale_comparable_methods_v3 import method_formula, apply_report
from test_shared_scale_planar_continuous_set_v2 import free_constant_names
from shared_scale_comparable_methods_v2 import CompletionEnvelopeSMT, FacetPlanarPosterior, TightBandPosterior

z3 = base.z3
INPUTS = json.loads((ROOT / "protocols/fifo_structural_inputs_v2.json").read_text(encoding="ascii"))["inputs"]
SELECTED = [case for case in INPUTS if case["factors"]["block"] == 2026101301]
SAVED = {row["controller_id"]: row for row in json.loads(
    (ROOT / "artifacts/fifo_structural_comparison_v2/controller_results.json").read_text(encoding="ascii"))}
CHECKS = Counter()
OBSERVATIONS = []


def methods_for(case):
    vertices = [cell["vertices"] for cell in case["cells"]]
    planes = [cell["halfplanes"] for cell in case["cells"]]
    submits = [row[0] for row in case["jobs"]]
    work = [row[1] for row in case["jobs"]]
    return {"band_v2": TightBandPosterior(submits, work, vertices, planes),
            "planar_v2": FacetPlanarPosterior(submits, work, vertices, planes),
            "envelope_smt_v2": CompletionEnvelopeSMT(
                [{"t": t, "p": p} for t, p in case["jobs"]], case["cells"], 1000)}


def check(expression, expected, label):
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(expression)
    status = solver.check()
    CHECKS["oracle_checks"] += 1
    if status != expected:
        detail = str(solver.model()) if status == z3.sat else solver.reason_unknown() if status == z3.unknown else ""
        raise AssertionError((label, str(status), detail))


def query_exists(specification, condition):
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(specification, condition)
    status = solver.check()
    CHECKS["literal_query_checks"] += 1
    if status == z3.unknown:
        raise AssertionError(solver.reason_unknown())
    return status == z3.sat


class LargeHistoryLiteralGate(unittest.TestCase):
    def test_first_block_all_cells_all_states(self):
        self.assertEqual(len(SELECTED), 32)
        priors = {}
        for components in (1, 4):
            representative = next(case for case in SELECTED if case["factors"]["components"] == components)
            initial, _, _, _ = base.literal_model(representative)
            weights = [z3.Real(f"lambda_{index}_{j}")
                       for index, cell in enumerate(representative["cells"])
                       for j in range(len(cell["vertices"]))]
            eliminated = z3.TryFor(z3.Tactic("qe"), 1000)(
                z3.Exists(weights, z3.And(*initial.assertions()))).as_expr()
            self.assertLessEqual(free_constant_names(eliminated), {"theta", "delta"})
            priors[components] = (representative["cells"], eliminated)
            CHECKS["exact_prior_eliminations"] += 1
        for case in SELECTED:
            with self.subTest(input_id=case["id"]):
                cells, prior = priors[case["factors"]["components"]]
                self.assertEqual(case["cells"], cells)
                _, theta, delta, departures = base.literal_model(case)
                methods = methods_for(case)
                predicates = [prior]
                for history_index, stage in enumerate([None] + case["stages"]):
                    if stage is not None:
                        count, tau = stage["report"]
                        for method in methods.values():
                            apply_report(method, stage["report"])
                        if count:
                            predicates.append(departures[count - 1] <= base.real(tau))
                        if count < len(departures):
                            predicates.append(departures[count] > base.real(tau))
                    specification = z3.And(*predicates)
                    for name, method in methods.items():
                        check(z3.Xor(specification, method_formula(name, method, theta, delta)), z3.unsat,
                              (case["id"], history_index, name))
                        CHECKS[name + "_full_set_xor_unsat"] += 1
                    CHECKS["history_states"] += 1
                    if stage is None:
                        continue
                    now, work, local, deadline = map(F, stage["query"])
                    arrival = base.real(now) + delta
                    start = z3.If(departures[-1] >= arrival, departures[-1], arrival)
                    remote = start + theta * base.real(work)
                    threshold = min(now + local, deadline)
                    expected = (query_exists(specification, remote <= base.real(threshold)),
                                query_exists(specification, remote > base.real(threshold)))
                    for name, method in methods.items():
                        result = method.certificate(*stage["query"])
                        self.assertEqual(result["status"], "EXACT")
                        self.assertEqual((result["at_or_below"], result["above"]), expected,
                                         (case["id"], history_index, name, "live"))
                        saved = SAVED[case["id"] + ":" + name]["queries"][history_index - 1]
                        self.assertEqual((saved["at_or_below"], saved["above"]), expected,
                                         (case["id"], history_index, name, "saved"))
                        self.assertEqual(F(saved["threshold"]), threshold)
                        CHECKS[name + "_live_and_saved_queries"] += 1
                    CHECKS["query_tuples"] += 1
                CHECKS["inputs"] += 1
                OBSERVATIONS.append({"input_id": case["id"], "history_states": len(case["stages"]) + 1,
                                     "query_tuples": len(case["stages"]), "all_checks_passed": True})
        self.assertEqual(CHECKS["history_states"], 688)
        self.assertEqual(CHECKS["query_tuples"], 656)


if __name__ == "__main__":
    unittest.main()
