"""Independent all-branch FIFO formulas, without any shared hull or pruning."""

from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import test_fifo_structural_literal_gate_v4 as helpers
import test_fifo_structural_literal_gate_v5 as prior_helpers

z3 = helpers.z3
CHECKS = Counter()
OBSERVATIONS = []


def all_departure_branches(jobs, theta, delta):
    departures = []
    for count in range(1, len(jobs) + 1):
        suffix, terms = F(0), []
        for t, work in reversed(jobs[:count]):
            suffix += F(work)
            terms.append(helpers.base.real(t) + delta + theta * helpers.base.real(suffix))
        departures.append(tuple(terms))
    return departures


def require_unsat(expression, label):
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(expression)
    status = solver.check()
    CHECKS["set_checks"] += 1
    if status != z3.unsat:
        detail = str(solver.model()) if status == z3.sat else solver.reason_unknown()
        raise AssertionError((label, str(status), detail))


def exists(specification, condition):
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(specification, condition)
    status = solver.check()
    CHECKS["literal_unpruned_query_checks"] += 1
    if status == z3.unknown:
        raise AssertionError(solver.reason_unknown())
    return status == z3.sat


class UnprunedGate(unittest.TestCase):
    def test_first_block_all_cells_all_states(self):
        priors = {}
        for components in (1, 4):
            case = next(case for case in helpers.SELECTED if case["factors"]["components"] == components)
            priors[components] = (case["cells"], prior_helpers.eliminated_prior(case))
        CHECKS.update(prior_helpers.CHECKS)
        self.assertEqual(len(helpers.SELECTED), 32)
        for case in helpers.SELECTED:
            with self.subTest(input_id=case["id"]):
                cells, prior = priors[case["factors"]["components"]]
                self.assertEqual(case["cells"], cells)
                theta, delta = z3.Reals("theta delta")
                departures = all_departure_branches(case["jobs"], theta, delta)
                methods = helpers.methods_for(case)
                predicates = [prior]
                for history_index, stage in enumerate([None] + case["stages"]):
                    if stage is not None:
                        count, tau = stage["report"]
                        for method in methods.values():
                            helpers.apply_report(method, stage["report"])
                        if count:
                            predicates.append(z3.And(*(term <= helpers.base.real(tau) for term in departures[count - 1])))
                        if count < len(departures):
                            predicates.append(z3.Or(*(term > helpers.base.real(tau) for term in departures[count])))
                    specification = z3.And(*predicates)
                    for name, method in methods.items():
                        require_unsat(z3.Xor(specification, helpers.method_formula(name, method, theta, delta)),
                                      (case["id"], history_index, name))
                        CHECKS[name + "_full_set_xor_unsat"] += 1
                    CHECKS["history_states"] += 1
                    if stage is None:
                        continue
                    now, work, local, deadline = map(F, stage["query"])
                    threshold = min(now + local, deadline)
                    remote_terms = [helpers.base.real(now) + delta + theta * helpers.base.real(work)] + [
                        term + theta * helpers.base.real(work) for term in departures[-1]]
                    expected = (exists(specification, z3.And(*(term <= helpers.base.real(threshold) for term in remote_terms))),
                                exists(specification, z3.Or(*(term > helpers.base.real(threshold) for term in remote_terms))))
                    for name, method in methods.items():
                        live = method.certificate(*stage["query"])
                        saved = helpers.SAVED[case["id"] + ":" + name]["queries"][history_index - 1]
                        for label, result in (("live", live), ("saved", saved)):
                            self.assertEqual(result["status"], "EXACT")
                            self.assertEqual((result["at_or_below"], result["above"]), expected,
                                             (case["id"], history_index, name, label))
                            self.assertEqual(F(result["threshold"]), threshold)
                        CHECKS[name + "_live_and_saved_queries"] += 1
                    CHECKS["query_tuples"] += 1
                CHECKS["inputs"] += 1
                OBSERVATIONS.append({"input_id": case["id"], "history_states": len(case["stages"]) + 1,
                                     "query_tuples": len(case["stages"]), "all_checks_passed": True})
        self.assertEqual(CHECKS["history_states"], 688)
        self.assertEqual(CHECKS["query_tuples"], 656)

    def test_unpruned_conversion_on_original_small_cases(self):
        for case in helpers.base.CORPUS["cases"]:
            _, theta, delta, nested = helpers.base.literal_model(case)
            branches = all_departure_branches(case["jobs"], theta, delta)
            for count, (departure, terms) in enumerate(zip(nested, branches), start=1):
                equality_to_max = z3.And(*(departure >= term for term in terms),
                                         z3.Or(*(departure == term for term in terms)))
                require_unsat(z3.Not(equality_to_max), (case["id"], count, "nested_to_all_branches"))
                CHECKS["small_case_universal_departure_identities"] += 1


if __name__ == "__main__":
    unittest.main()
