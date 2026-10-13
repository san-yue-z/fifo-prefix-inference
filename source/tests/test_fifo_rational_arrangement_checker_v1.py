"""Analytic negative/positive controls for the independent rational checker."""

from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
import fifo_rational_arrangement_checker_v1 as checker
import z3


class RationalCheckerControls(unittest.TestCase):
    def test_open_puncture_is_not_filled(self):
        result = checker.normalize((checker.Interval(F(0), F(1), True, False),
                                    checker.Interval(F(1), F(2), False, True)))
        self.assertEqual(len(result), 2)

    def test_point_fills_puncture(self):
        result = checker.normalize((checker.Interval(F(0), F(1), True, False),
                                    checker.Interval(F(1), F(1)), checker.Interval(F(1), F(2), False, True)))
        self.assertEqual(result, (checker.Interval(F(0), F(2)),))

    def test_intersection_retains_strictness(self):
        result = checker.intersection((checker.Interval(F(0), F(1), True, False),),
                                      (checker.Interval(F(1), F(2)),))
        self.assertEqual(result, ())

    def test_same_endpoints_merge_flags(self):
        result = checker.normalize((checker.Interval(F(0), F(1), False, False),
                                    checker.Interval(F(0), F(1), True, True)))
        self.assertEqual(result, (checker.Interval(F(0), F(1)),))

    def test_upper_lower_and_theta_atoms(self):
        box = checker.Interval(F(0), F(2))
        formula = checker.boolean("and", checker.atom("ge", 0, 1, -F(1, 2)), checker.atom("lt", 0, 1, -1))
        self.assertEqual(checker.formula_slice(formula, F(1), box), (checker.Interval(F(1, 2), F(1), True, False),))
        self.assertEqual(checker.formula_slice(checker.atom("lt", -1, 0, 1), F(1), box), ())

    def test_negative_delta_coefficient(self):
        box = checker.Interval(F(0), F(2))
        self.assertEqual(checker.formula_slice(checker.plane(0, -1, -1, True), F(0), box),
                         (checker.Interval(F(1), F(2), False, True),))

    def test_polygon_segment_point_slices(self):
        box = checker.Interval(F(-2), F(3))
        triangle = checker.closure_formula([(0, 0), (2, 0), (1, 2)])
        self.assertEqual(checker.formula_slice(triangle, F(1), box), (checker.Interval(F(0), F(2)),))
        line = checker.closure_formula([(0, 2), (2, 0)])
        self.assertEqual(checker.formula_slice(line, F(1), box), (checker.Interval(F(1), F(1)),))
        point = checker.closure_formula([(1, 2)])
        self.assertEqual(checker.formula_slice(point, F(1), box), (checker.Interval(F(2), F(2)),))
        self.assertEqual(checker.formula_slice(point, F(0), box), ())

    def test_all_pair_dominance_complete(self):
        branches = ((F(1), F(0)), (F(0), F(1)), (F(-1), F(2)))
        pieces = checker.dominance_intervals(branches, F(0), F(2))
        self.assertEqual(checker.normalize(checker.Interval(a, b) for a, b, _, _ in pieces),
                         (checker.Interval(F(0), F(2)),))
        for theta in (F(0), F(1, 3), F(1), F(3, 2), F(2)):
            active = [a * theta + b for low, high, a, b in pieces if low <= theta <= high]
            self.assertEqual(set(active), {max(a * theta + b for a, b in branches)})

    def test_arrangement_adds_crossing_and_midpoints(self):
        first = checker.atom("le", -1, 1, 0)
        second = checker.atom("le", 1, 1, -2)
        points, events, _ = checker.arrangement_points([first, second], [], (F(0), F(2)), checker.Interval(F(0), F(2)))
        self.assertIn(F(1), points)
        self.assertIn(F(1, 2), points)
        self.assertGreaterEqual(events, 3)

    def test_smt_affine_boolean_conversion(self):
        theta, delta = z3.Reals("theta delta")
        expression = z3.And(delta - theta >= 0, delta < 2)
        parsed = checker.smt_boolean(expression, z3)
        expected = checker.boolean("and", checker.atom("ge", -1, 1, 0), checker.atom("lt", 0, 1, -2))
        self.assertEqual(parsed, expected)
        self.assertEqual(checker.smt_affine(theta / 2 + z3.RealVal("1/3"), z3), (F(1, 2), F(0), F(1, 3)))

    def test_nonlinear_or_hidden_smt_terms_rejected(self):
        theta, delta, hidden = z3.Reals("theta delta hidden")
        for expression in (theta * delta, hidden):
            with self.assertRaises(ValueError):
                checker.smt_affine(expression, z3)

    def test_literal_backwards_identity_at_exact_values(self):
        jobs = [["0", "1/2"], ["3/4", "3/2"], ["5/2", "3/4"]]
        for theta in (F(1, 3), F(1), F(7, 3)):
            literal = checker.literal_departures(jobs, theta)
            for count, departure in enumerate(literal, start=1):
                self.assertEqual(departure, max(a * theta + b for a, b in checker.all_branches(jobs, count)))


if __name__ == "__main__":
    unittest.main()
