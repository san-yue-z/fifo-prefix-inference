"""Public checker interface and one complete frontend integration control."""

from fractions import Fraction as F
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
import fifo_rational_arrangement_checker_v3 as checker
from shared_scale_comparable_methods_v2 import CompletionEnvelopeSMT, TightBandPosterior, FacetPlanarPosterior
import z3


class RationalInterfaceControls(unittest.TestCase):
    def test_recorder_interface_is_complete(self):
        for name in ("Interval", "all_branches", "arrangement_points", "band_formula", "dominance_intervals",
                     "encoded_intervals", "formula_slice", "original_prior", "planar_formula", "query_sides",
                     "specification_slice", "verify_smt_history"):
            self.assertTrue(callable(getattr(checker, name)))

    def test_frontends_complete_state_and_query(self):
        case = {"jobs": [["0", "1"]], "cells": [{
            "vertices": [["1/2", "0"], ["3/2", "0"], ["3/2", "1"], ["1/2", "1"]],
            "halfplanes": [["1", "0", "3/2", False], ["-1", "0", "-1/2", False],
                           ["0", "1", "1", False], ["0", "-1", "0", True]]}]}
        vertices, planes = [case["cells"][0]["vertices"]], [case["cells"][0]["halfplanes"]]
        band = TightBandPosterior(["0"], ["1"], vertices, planes)
        planar = FacetPlanarPosterior(["0"], ["1"], vertices, planes)
        smt = CompletionEnvelopeSMT([{"t": "0", "p": "1"}], case["cells"], 1000)
        scope, box = (F(1, 2), F(3, 2)), checker.Interval(F(0), F(1))
        curves = {1: checker.dominance_intervals(checker.all_branches(case["jobs"], 1), *scope)}
        reports = []
        prior = checker.original_prior(case)
        for report in (None, (0, F(1, 4)), (1, F(2))):
            if report is not None:
                reports.append(report)
                band.update(*report)
                planar.update(*report)
                smt.add_report(*report)
            checker.verify_smt_history(smt, case, reports, curves, scope, z3)
            formulas = [checker.band_formula(band), checker.planar_formula(planar)]
            segments = [(low, high, -a, tau - b) for count, tau in reports
                        for low, high, a, b in curves[1]]
            query = (F(3), F(1), F(2), F(5))
            segments.append((*scope, -F(1), F(2)))
            segments.extend((low, high, -a - 1, F(5) - b) for low, high, a, b in curves[1])
            points, _, _ = checker.arrangement_points([prior] + formulas, segments, scope, box)
            below = above = False
            for theta in points:
                expected, departures = checker.specification_slice(case, reports, theta, prior, box)
                for formula in formulas:
                    self.assertEqual(checker.formula_slice(formula, theta, box), expected)
                first, second = checker.query_sides(expected, theta, departures, query)
                below |= first
                above |= second
            for method in (band, planar, smt):
                result = method.certificate(*query)
                self.assertEqual(result["status"], "EXACT")
                self.assertEqual((result["at_or_below"], result["above"]), (below, above))


if __name__ == "__main__":
    unittest.main()
