"""Independent exact rational interval/arrangement checker, with no solver calls."""

from dataclasses import dataclass
from fractions import Fraction as F
from itertools import combinations


def atom(relation, a, b, c):
    if relation not in ("lt", "le", "gt", "ge", "eq"):
        raise ValueError("Unsupported comparison")
    return ("atom", relation, F(a), F(b), F(c))


def plane(a, b, rhs, strict=False):
    return atom("lt" if strict else "le", a, b, -F(rhs))


def boolean(operation, *parts):
    if operation not in ("and", "or"):
        raise ValueError("Unsupported Boolean operation")
    flat = []
    for part in parts:
        if type(part) is bool:
            if part != (operation == "and"):
                return part
            continue
        if part[0] == operation:
            flat.extend(part[1])
        else:
            flat.append(part)
    if not flat:
        return operation == "and"
    if len(flat) == 1:
        return flat[0]
    return (operation, tuple(flat))


def compare(value, relation):
    return {"lt": value < 0, "le": value <= 0, "gt": value > 0,
            "ge": value >= 0, "eq": value == 0}[relation]


@dataclass(frozen=True)
class Interval:
    low: F
    high: F
    low_closed: bool = True
    high_closed: bool = True

    @property
    def nonempty(self):
        return self.low < self.high or (self.low == self.high and self.low_closed and self.high_closed)


def normalize(intervals):
    ordered = sorted((row for row in intervals if row.nonempty),
                     key=lambda row: (row.low, not row.low_closed, row.high, not row.high_closed))
    result = []
    for row in ordered:
        if not result:
            result.append(row)
            continue
        previous = result[-1]
        connected = row.low < previous.high or (row.low == previous.high and (row.low_closed or previous.high_closed))
        if not connected:
            result.append(row)
            continue
        low_closed = previous.low_closed or (row.low == previous.low and row.low_closed)
        if row.high > previous.high:
            high, high_closed = row.high, row.high_closed
        elif row.high < previous.high:
            high, high_closed = previous.high, previous.high_closed
        else:
            high, high_closed = previous.high, previous.high_closed or row.high_closed
        result[-1] = Interval(previous.low, high, low_closed, high_closed)
    return tuple(result)


def intersection(first, second):
    result, i, j = [], 0, 0
    while i < len(first) and j < len(second):
        a, b = first[i], second[j]
        low, high = max(a.low, b.low), min(a.high, b.high)
        lc = (a.low_closed if a.low == low else True) and (b.low_closed if b.low == low else True)
        hc = (a.high_closed if a.high == high else True) and (b.high_closed if b.high == high else True)
        candidate = Interval(low, high, lc, hc)
        if candidate.nonempty:
            result.append(candidate)
        if a.high < b.high:
            i += 1
        elif a.high > b.high:
            j += 1
        else:
            i += 1
            j += 1
    return normalize(result)


def atomic_slice(expression, theta, box):
    _, relation, a, b, c = expression
    constant = a * theta + c
    if b == 0:
        return (box,) if compare(constant, relation) else ()
    boundary = -constant / b
    if relation == "eq":
        return intersection((Interval(boundary, boundary),), (box,))
    lower = (relation in ("ge", "gt")) == (b > 0)
    closed = relation in ("ge", "le")
    if lower:
        if boundary > box.high:
            return ()
        if boundary < box.low:
            return (box,)
        row = Interval(boundary, box.high, closed and (box.low_closed if boundary == box.low else True), box.high_closed)
    else:
        if boundary < box.low:
            return ()
        if boundary > box.high:
            return (box,)
        row = Interval(box.low, boundary, box.low_closed, closed and (box.high_closed if boundary == box.high else True))
    return (row,) if row.nonempty else ()


def formula_slice(expression, theta, box):
    if type(expression) is bool:
        return (box,) if expression else ()
    if expression[0] == "atom":
        return atomic_slice(expression, theta, box)
    if expression[0] == "or":
        return normalize(row for part in expression[1] for row in formula_slice(part, theta, box))
    result = (box,)
    for part in expression[1]:
        result = intersection(result, formula_slice(part, theta, box))
        if not result:
            break
    return result


def atoms(expression):
    if type(expression) is bool:
        return ()
    if expression[0] == "atom":
        return (expression,)
    return tuple(item for part in expression[1] for item in atoms(part))


def closure_formula(vertices):
    rows = [tuple(map(F, point)) for point in vertices]
    if len(rows) == 1:
        return boolean("and", atom("eq", 1, 0, -rows[0][0]), atom("eq", 0, 1, -rows[0][1]))
    if len(rows) == 2:
        (x, y), (u, v) = rows
        return boolean("and", atom("eq", v - y, x - u, -(v - y) * x - (x - u) * y),
                       plane(1, 0, max(x, u)), plane(-1, 0, -min(x, u)),
                       plane(0, 1, max(y, v)), plane(0, -1, -min(y, v)))
    if len(rows) < 3:
        return False
    area = sum(x * v - u * y for (x, y), (u, v) in zip(rows, rows[1:] + rows[:1]))
    if area <= 0:
        raise ValueError("Expected nondegenerate CCW polygon")
    return boolean("and", *(plane(v - y, x - u, (v - y) * x + (x - u) * y)
                            for (x, y), (u, v) in zip(rows, rows[1:] + rows[:1])))


def original_prior(case):
    return boolean("and", atom("gt", 1, 0, 0), atom("ge", 0, 1, 0),
                   boolean("or", *(boolean("and", closure_formula(cell["vertices"]),
                                                   *(plane(a, b, c, strict) for a, b, c, strict in cell["halfplanes"]))
                                   for cell in case["cells"])))


def literal_departures(jobs, theta):
    result = []
    for submit, work in jobs:
        arrival = F(submit)
        start = max(arrival, result[-1]) if result else arrival
        result.append(start + theta * F(work))
    return tuple(result)


def all_branches(jobs, count):
    suffix, branches = F(0), []
    for submit, work in reversed(jobs[:count]):
        suffix += F(work)
        branches.append((suffix, F(submit)))
    return tuple(branches)


def dominance_intervals(branches, left, right):
    result = []
    for slope, intercept in branches:
        low, high, possible = left, right, True
        for other_slope, other_intercept in branches:
            difference = slope - other_slope
            rhs = other_intercept - intercept
            if difference > 0:
                low = max(low, rhs / difference)
            elif difference < 0:
                high = min(high, rhs / difference)
            elif rhs > 0:
                possible = False
                break
            if low > high:
                possible = False
                break
        if possible:
            result.append((low, high, slope, intercept))
    coverage = normalize(Interval(low, high) for low, high, _, _ in result)
    if coverage != (Interval(left, right),):
        raise AssertionError("Dominance intervals do not cover the complete scope")
    return tuple(result)


def band_formula(method):
    pieces = []
    for component in method.components:
        for point in component.points:
            if any(row.left < point.theta < row.right for row in component.bands):
                raise AssertionError("Redundant point inside a coalesced band")
        for row in component.bands:
            pieces.append(boolean("and", atom("gt", 1, 0, -row.left), atom("lt", 1, 0, -row.right),
                                  atom("gt" if row.lower.strict else "ge", -row.lower.line.slope, 1, -row.lower.line.intercept),
                                  atom("lt" if row.upper.strict else "le", -row.upper.line.slope, 1, -row.upper.line.intercept)))
        for point in component.points:
            pieces.append(boolean("and", atom("eq", 1, 0, -point.theta),
                                  atom("gt" if point.lower.strict else "ge", 0, 1, -point.lower.value),
                                  atom("lt" if point.upper.strict else "le", 0, 1, -point.upper.value)))
    return boolean("or", *pieces)


def planar_formula(method):
    return boolean("or", *(boolean("and", closure_formula(cell.vertices),
                                   *(plane(a, b, c, True) for a, b, c in cell.strict))
                            for group in method.groups for cell in group))


def normalize_plane_coefficients(row):
    a, b, c = map(F, row)
    scale = abs(a) if a else abs(b) if b else abs(c) if c else F(1)
    return a / scale, b / scale, c / scale


def verify_prior_closures(case):
    for cell in case["cells"]:
        if len(cell["vertices"]) < 3:
            raise ValueError("This SMT bounding certificate expects polygon priors")
        expected = {normalize_plane_coefficients(item[2:]) for item in atoms(closure_formula(cell["vertices"]))}
        given = {normalize_plane_coefficients((a, b, -F(c))) for a, b, c, _ in cell["halfplanes"]}
        if expected != given:
            raise AssertionError("Original halfplanes do not describe the declared weak polygon closure")


def smt_affine(expression, z3):
    if z3.is_rational_value(expression):
        return F(0), F(0), F(expression.numerator_as_long(), expression.denominator_as_long())
    if z3.is_const(expression) and expression.decl().kind() == z3.Z3_OP_UNINTERPRETED:
        name = str(expression.decl().name())
        if name == "theta":
            return F(1), F(0), F(0)
        if name == "delta":
            return F(0), F(1), F(0)
        raise ValueError("Unexpected SMT constant: " + name)
    kind, children = expression.decl().kind(), expression.children()
    coefficients = [smt_affine(child, z3) for child in children]
    if kind == z3.Z3_OP_ADD:
        return tuple(sum(row[index] for row in coefficients) for index in range(3))
    if kind == z3.Z3_OP_UMINUS:
        return tuple(-value for value in coefficients[0])
    if kind == z3.Z3_OP_SUB:
        return tuple(coefficients[0][index] - sum(row[index] for row in coefficients[1:]) for index in range(3))
    if kind == z3.Z3_OP_MUL:
        scalar, nonconstant = F(1), None
        for row in coefficients:
            if row[:2] == (0, 0):
                scalar *= row[2]
            elif nonconstant is None:
                nonconstant = row
            else:
                raise ValueError("Nonlinear SMT term")
        return tuple(scalar * value for value in nonconstant) if nonconstant is not None else (F(0), F(0), scalar)
    if kind == z3.Z3_OP_DIV and coefficients[1][:2] == (0, 0):
        return tuple(value / coefficients[1][2] for value in coefficients[0])
    raise ValueError("Unsupported SMT arithmetic")


def smt_boolean(expression, z3):
    if z3.is_true(expression) or z3.is_false(expression):
        return z3.is_true(expression)
    kind, children = expression.decl().kind(), expression.children()
    if kind in (z3.Z3_OP_AND, z3.Z3_OP_OR):
        return boolean("and" if kind == z3.Z3_OP_AND else "or", *(smt_boolean(child, z3) for child in children))
    relations = {z3.Z3_OP_LT: "lt", z3.Z3_OP_LE: "le", z3.Z3_OP_GT: "gt", z3.Z3_OP_GE: "ge", z3.Z3_OP_EQ: "eq"}
    if kind not in relations or len(children) != 2:
        raise ValueError("Unsupported SMT Boolean term")
    first, second = (smt_affine(child, z3) for child in children)
    return atom(relations[kind], *(a - b for a, b in zip(first, second)))


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
    actual = tuple(smt_boolean(item, z3) for item in method.solver.assertions())
    if actual != tuple(expected):
        raise AssertionError("Retained SMT assertions do not match original prior and report history")
    return len(certified)


def clipped_segment(left, right, slope, intercept, delta_box):
    low, high = left, right
    if slope > 0:
        low = max(low, (delta_box.low - intercept) / slope)
        high = min(high, (delta_box.high - intercept) / slope)
    elif slope < 0:
        low = max(low, (delta_box.high - intercept) / slope)
        high = min(high, (delta_box.low - intercept) / slope)
    elif not delta_box.low <= intercept <= delta_box.high:
        return None
    return (low, high, slope, intercept) if low <= high else None


def arrangement_points(formulas, restricted_segments, scope, delta_box):
    left, right = scope
    events, segments = {left, right}, set()
    for expression in formulas:
        for _, _, a, b, c in atoms(expression):
            if b:
                candidate = clipped_segment(left, right, -a / b, -c / b, delta_box)
                if candidate is not None:
                    segments.add(candidate)
            elif a:
                crossing = -c / a
                if left <= crossing <= right:
                    events.add(crossing)
    for low, high, slope, intercept in restricted_segments:
        events.update((low, high))
        candidate = clipped_segment(low, high, slope, intercept, delta_box)
        if candidate is not None:
            segments.add(candidate)
    for low, high, _, _ in segments:
        events.update((low, high))
    for first, second in combinations(segments, 2):
        low, high = max(first[0], second[0]), min(first[1], second[1])
        difference = first[2] - second[2]
        if low <= high and difference:
            crossing = (second[3] - first[3]) / difference
            if low <= crossing <= high:
                events.add(crossing)
    ordered = sorted(events)
    points = sorted(set(ordered + [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]))
    return tuple(points), len(ordered), len(segments)


def specification_slice(case, reports, theta, prior, delta_box):
    result = formula_slice(prior, theta, delta_box)
    departures = literal_departures(case["jobs"], theta)
    for count, tau in reports:
        if count:
            result = intersection(result, atomic_slice(atom("le", 0, 1, departures[count - 1] - F(tau)), theta, delta_box))
        if count < len(departures):
            result = intersection(result, atomic_slice(atom("gt", 0, 1, departures[count] - F(tau)), theta, delta_box))
        if not result:
            break
    return result, departures


def query_sides(intervals, theta, departures, query):
    now, work, local, deadline = map(F, query)
    readiness = max(now, departures[-1]) if departures else now
    cutoff = min(now + local, deadline) - readiness - work * theta
    below = any(row.low < cutoff or (row.low == cutoff and row.low_closed) for row in intervals)
    above = any(row.high > cutoff for row in intervals)
    return below, above


def encoded_intervals(rows):
    return [[str(row.low), str(row.high), row.low_closed, row.high_closed] for row in rows]
