"""New planar-interface controls with literal FIFO/convex-combination SMT oracle."""

from collections import Counter
from fractions import Fraction as F
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
from shared_scale_planar_reference_v1 import Cell, PlanarPosterior, convex_hull, try_join
from shared_scale_band_posterior_v1 import BandPosterior
import z3

CORPUS = json.loads((ROOT / "protocols/fifo_planar_correctness_controls_v1.json").read_text(encoding="utf-8"))
CHECKS = Counter()
OBSERVATIONS = []


def real(value):
    return z3.RealVal(str(F(value)))


def vertex_hull_formula(theta, delta, vertices, name):
    weights = [z3.Real(f"{name}_{i}") for i in range(len(vertices))]
    return z3.And(*(weight >= 0 for weight in weights), z3.Sum(weights) == 1,
                  theta == z3.Sum([weight * real(point[0]) for weight, point in zip(weights, vertices)]),
                  delta == z3.Sum([weight * real(point[1]) for weight, point in zip(weights, vertices)]))


def cell_formula(theta, delta, cell, name):
    return z3.And(vertex_hull_formula(theta, delta, cell.vertices, name),
                  *(real(a) * theta + real(b) * delta < real(c) for a, b, c in cell.strict))


def check_solver(solver, condition):
    solver.push()
    try:
        solver.add(condition)
        status = solver.check()
        CHECKS["literal_z3_checks"] += 1
        if status == z3.unknown:
            raise AssertionError("UNKNOWN is not an absence answer: " + solver.reason_unknown())
        return status == z3.sat
    finally:
        solver.pop()


def literal_model(case):
    theta, delta = z3.Reals("theta delta")
    prior = []
    for index, cell in enumerate(case["cells"]):
        prior.append(z3.And(vertex_hull_formula(theta, delta, cell["vertices"], f"lambda_{index}"),
                            *[(real(a) * theta + real(b) * delta < real(c) if strict else
                               real(a) * theta + real(b) * delta <= real(c))
                              for a, b, c, strict in cell["halfplanes"]]))
    solver = z3.SolverFor("QF_LRA")
    solver.set(timeout=1000)
    solver.add(theta > 0, delta >= 0, z3.Or(*prior))
    departures = []
    previous = None
    for submit, work in case["jobs"]:
        arrival = real(submit) + delta
        start = arrival if previous is None else z3.If(previous >= arrival, previous, arrival)
        previous = start + theta * real(work)
        departures.append(previous)
    return solver, theta, delta, departures


class PlanarInterfaceControls(unittest.TestCase):
    def test_locked_cases_against_literal_fifo(self):
        for case in CORPUS["cases"]:
            with self.subTest(case=case["id"]):
                submits = [row[0] for row in case["jobs"]]
                work = [row[1] for row in case["jobs"]]
                vertices = [cell["vertices"] for cell in case["cells"]]
                planes = [cell["halfplanes"] for cell in case["cells"]]
                merged = PlanarPosterior(submits, work, vertices, planes)
                unmerged = PlanarPosterior(submits, work, vertices, planes, merge_cells=False)
                band = BandPosterior(submits, work, vertices, planes)
                solver, theta, delta, departures = literal_model(case)
                histories = [None] + case["reports"]
                for history_index, report in enumerate(histories):
                    if report is not None:
                        completed, tau = report
                        for method in (merged, unmerged, band):
                            method.update(completed, tau)
                        if completed:
                            solver.add(departures[completed - 1] <= real(tau))
                        if completed < len(departures):
                            solver.add(departures[completed] > real(tau))
                    for point in case["points"]:
                        expected = check_solver(solver, z3.And(theta == real(point[0]), delta == real(point[1])))
                        for name, method in (("planar", merged), ("planar_no_merge", unmerged), ("band", band)):
                            self.assertEqual(method.contains(point), expected, (case["id"], history_index, point, name))
                        CHECKS["membership_points"] += 1
                query = case["query"]
                now, pnew, local, deadline = (F(query[k]) for k in ("now", "pnew", "local_duration", "deadline"))
                remote_arrival = real(now) + delta
                if departures:
                    remote_start = z3.If(departures[-1] >= remote_arrival, departures[-1], remote_arrival)
                else:
                    remote_start = remote_arrival
                remote = remote_start + theta * real(pnew)
                bound = min(now + local, deadline)
                expected = (check_solver(solver, remote <= real(bound)), check_solver(solver, remote > real(bound)))
                outcomes = []
                for name, method in (("planar", merged), ("planar_no_merge", unmerged), ("band", band)):
                    result = method.certificate(now, pnew, local, deadline)
                    self.assertEqual((result["at_or_below"], result["above"]), expected, (case["id"], name))
                    if "expected_mode" in case:
                        self.assertEqual(result["uniform_mode"], case["expected_mode"], (case["id"], name))
                    if "expected_action" in case:
                        self.assertEqual(result["action"], case["expected_action"], (case["id"], name))
                    outcomes.append((result["action"], result["uniform_mode"], result["threshold"]))
                self.assertEqual(outcomes[0], outcomes[1])
                self.assertEqual(outcomes[0], outcomes[2])
                CHECKS["cases"] += 1
                CHECKS["mode_" + outcomes[0][1]] += 1
                OBSERVATIONS.append({"id": case["id"], "sides": expected,
                                     "action": outcomes[0][0], "mode": outcomes[0][1],
                                     "planar_counts": merged.representation_counts(),
                                     "unmerged_counts": unmerged.representation_counts()})

    def test_domain_guards(self):
        with self.assertRaises(ValueError):
            PlanarPosterior([-1], [1], [[[1, 0]]])
        method = PlanarPosterior([0], [1], [[[1, 0]]])
        for query in ((0, 1, 1, 2), (1, 0, 1, 2), (1, 1, 0, 2), (1, 1, 1, -1)):
            with self.assertRaises(ValueError):
                method.certificate(*query)
        method.update(0, 3)
        with self.assertRaises(ValueError):
            method.certificate(2, 1, 1, 4)


class ExactJoinControls(unittest.TestCase):
    def cell(self, vertices, strict=()):
        return Cell.make(convex_hull([tuple(map(F, p)) for p in vertices]),
                         tuple(tuple(map(F, plane)) for plane in strict))

    def verify_join(self, left, right, should_join):
        candidate = try_join(left, right)
        self.assertEqual(candidate is not None, should_join)
        theta, delta = z3.Reals("join_theta join_delta")
        original = z3.Or(cell_formula(theta, delta, left, "join_left"), cell_formula(theta, delta, right, "join_right"))
        if candidate is not None:
            # Local generator variables are existential in both formula branches.
            # Exact set difference is tested using halfplanes/point/edge membership
            # formulas, not XOR on independently quantified generator witnesses.
            first = geometric_formula(theta, delta, left)
            second = geometric_formula(theta, delta, right)
            target = geometric_formula(theta, delta, candidate)
            solver = z3.SolverFor("QF_LRA")
            solver.set(timeout=1000)
            self.assertFalse(check_solver(solver, z3.Xor(z3.Or(first, second), target)))
            CHECKS["accepted_join_xor_unsat"] += 1
        CHECKS["join_controls"] += 1

    def test_closed_triangles_form_triangle(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1)]), self.cell([(1, 0), (2, 0), (1, 1)]), True)

    def test_open_half_join_filled_by_other_cell(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1), (0, 1)], [(1, 0, 1)]),
                         self.cell([(1, 0), (2, 0), (2, 1), (1, 1)]), True)

    def test_far_vertex_exclusion_preserved(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1), (0, 1)], [(-1, 1, 1)]),
                         self.cell([(1, 0), (2, 0), (2, 1), (1, 1)]), True)

    def test_missing_boundary_point_not_restored(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1), (0, 1)], [(1, -1, 1)]),
                         self.cell([(1, 0), (2, 0), (2, 1), (1, 1)], [(-1, -1, -1)]), False)

    def test_missing_internal_slice_not_restored(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1), (0, 1)], [(1, 0, 1)]),
                         self.cell([(1, 0), (2, 0), (2, 1), (1, 1)], [(-1, 0, -1)]), False)

    def test_convex_but_not_nnc_point_filled_face_rejected(self):
        self.verify_join(self.cell([(0, 0), (1, 0), (1, 1), (0, 1)], [(1, 0, 1)]), self.cell([(1, F(1, 2))]), False)

    def test_disjoint_vertical_segments_rejected(self):
        self.verify_join(self.cell([(1, 0), (1, 1)]), self.cell([(1, 2), (1, 3)]), False)

    def test_vertical_puncture_rejected(self):
        self.verify_join(self.cell([(1, 0), (1, 1)], [(0, 1, 1)]), self.cell([(1, 1), (1, 2)], [(0, -1, -1)]), False)

    def test_line_endpoint_join(self):
        self.verify_join(self.cell([(1, 0)]), self.cell([(1, 0), (2, 0)]), True)


def geometric_formula(theta, delta, cell):
    vertices = cell.vertices
    if len(vertices) == 1:
        closure = z3.And(theta == real(vertices[0][0]), delta == real(vertices[0][1]))
    elif len(vertices) == 2:
        a, b = vertices
        closure = z3.And((theta - real(a[0])) * real(b[1] - a[1]) == (delta - real(a[1])) * real(b[0] - a[0]),
                         theta >= real(min(a[0], b[0])), theta <= real(max(a[0], b[0])),
                         delta >= real(min(a[1], b[1])), delta <= real(max(a[1], b[1])))
    else:
        planes = []
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            planes.append(real(b[0] - a[0]) * (delta - real(a[1])) - real(b[1] - a[1]) * (theta - real(a[0])) >= 0)
        closure = z3.And(*planes)
    return z3.And(closure, *(real(a) * theta + real(b) * delta < real(c) for a, b, c in cell.strict))


if __name__ == "__main__":
    unittest.main()
