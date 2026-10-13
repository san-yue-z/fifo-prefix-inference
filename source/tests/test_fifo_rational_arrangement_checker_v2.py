"""Normalization controls added after the first checker failure."""

from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
import fifo_rational_arrangement_checker_v2 as checker
import z3


class RationalNormalizationControls(unittest.TestCase):
    def test_reversed_direction_and_positive_scale(self):
        theta = z3.Real("theta")
        first = checker.smt_boolean(theta > 0, z3)
        reversed_encoding = checker.smt_boolean(theta > z3.RealVal("0"), z3)
        self.assertEqual(checker.canonical(first), checker.canonical(reversed_encoding))
        self.assertEqual(checker.canonical(checker.atom("lt", -2, -4, 6)),
                         checker.canonical(checker.atom("gt", 1, 2, -3)))
        self.assertEqual(checker.canonical(checker.atom("le", F(1, 2), 1, -F(3, 2))),
                         checker.canonical(checker.atom("le", 1, 2, -3)))

    def test_strictness_is_not_normalized_away(self):
        self.assertNotEqual(checker.canonical(checker.atom("lt", 1, 2, -3)),
                            checker.canonical(checker.atom("le", 1, 2, -3)))
        self.assertNotEqual(checker.canonical(checker.atom("gt", 1, 0, 0)),
                            checker.canonical(checker.atom("ge", 1, 0, 0)))

    def test_boolean_order_is_semantically_irrelevant(self):
        a, b = checker.atom("lt", 1, 0, -1), checker.atom("ge", 0, 1, 0)
        self.assertEqual(checker.canonical(checker.boolean("and", a, b)),
                         checker.canonical(checker.boolean("and", b, a)))


if __name__ == "__main__":
    unittest.main()
