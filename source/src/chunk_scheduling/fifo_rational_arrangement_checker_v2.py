"""Versioned AST-normalization repair; the original rational checker is preserved."""

from fractions import Fraction as F
from fifo_rational_arrangement_checker_v1 import (
    Interval, all_branches, arrangement_points, atom, band_formula, boolean,
    compare, dominance_intervals, encoded_intervals, original_prior, plane,
    planar_formula, query_sides, smt_affine, smt_boolean, specification_slice,
    verify_prior_closures,
)


def canonical(expression):
    if type(expression) is bool:
        return expression
    if expression[0] != "atom":
        parts = [canonical(part) for part in expression[1]]
        return boolean(expression[0], *sorted(parts, key=repr))
    _, relation, a, b, c = expression
    pivot = next((value for value in (a, b, c) if value), None)
    if pivot is None:
        return compare(F(0), relation)
    if pivot < 0:
        a, b, c = -a, -b, -c
        relation = {"lt": "gt", "le": "ge", "gt": "lt", "ge": "le", "eq": "eq"}[relation]
    scale = abs(pivot)
    return atom(relation, a / scale, b / scale, c / scale)


def verify_smt_history(method, case, reports, curves, scope, z3):
    verify_prior_closures(case)
    expected = [atom("gt", 1, 0, 0), atom("ge", 0, 1, 0),
                boolean("or", *(boolean("and", *(plane(a, b, c, strict) for a, b, c, strict in cell["halfplanes"]))
                                for cell in case["cells"]))]
    certified = {}
    for count, terms in method.compiled.items():
        encoded = tuple(smt_affine(term, z3) for term in terms)
        if any(row[1] != 0 for row in encoded):
            raise AssertionError("Departure term contains delta")
        selected = {(row[0], row[2]) for row in encoded}
        branches = set(all_branches(case["jobs"], count))
        if scope[0] == scope[1]:
            theta = scope[0]
            if max(a * theta + b for a, b in selected) != max(a * theta + b for a, b in branches):
                raise AssertionError("Singleton departure maximum differs")
        else:
            if not selected <= branches:
                raise AssertionError("Cached SMT term is not an original FIFO branch")
            required = {(a, b) for left, right, a, b in curves[count] if left < right}
            if not required <= selected:
                raise AssertionError("Cached SMT terms omit an open-interval active branch")
        certified[count] = encoded
    for count, tau in reports:
        if count:
            expected.append(boolean("and", *(atom("le", a, 1, c - F(tau)) for a, _, c in certified[count])))
        if count < len(case["jobs"]):
            expected.append(boolean("or", *(atom("gt", a, 1, c - F(tau)) for a, _, c in certified[count + 1])))
    actual = tuple(canonical(smt_boolean(item, z3)) for item in method.solver.assertions())
    target = tuple(canonical(item) for item in expected)
    if actual != target:
        raise AssertionError("Retained SMT assertions do not match original prior and reports after exact normalization")
    return len(certified)
