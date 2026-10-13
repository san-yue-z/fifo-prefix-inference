"""Expose the complete checker interface; no mathematical change from v2."""

from fifo_rational_arrangement_checker_v1 import formula_slice
from fifo_rational_arrangement_checker_v2 import (
    Interval, all_branches, arrangement_points, atom, band_formula, boolean,
    canonical, compare, dominance_intervals, encoded_intervals, original_prior,
    plane, planar_formula, query_sides, smt_affine, smt_boolean,
    specification_slice, verify_prior_closures, verify_smt_history,
)
