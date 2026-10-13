"""Proof-oriented rational verification of all six pending input histories."""

from collections import Counter
from fractions import Fraction as F
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/fifo_rational_pending_resolution_v1"
FILES = (
    "src/chunk_scheduling/fifo_rational_arrangement_checker_v1.py",
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
    "protocols/fifo_structural_inputs_v2.json", "protocols/fifo_rational_pending_resolution_v1.md",
    "tests/test_fifo_rational_arrangement_checker_v1.py", "scripts/record_fifo_rational_pending_resolution_v1.py",
    "artifacts/fifo_structural_comparison_v2/controller_results.json",
    "artifacts/fifo_structural_unpruned_gate_v6/receipt.json",
)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="ascii")


def bounds_check(band, planar, scope, delta_box):
    coordinates = []
    for component in band.components:
        for row in component.bands:
            if row.left >= row.right:
                raise AssertionError("Invalid band scope")
            for theta in (row.left, row.right):
                coordinates.extend((theta, bound.line.at(theta)) for bound in (row.lower, row.upper))
        coordinates.extend((point.theta, value) for point in component.points
                           for value in (point.lower.value, point.upper.value))
    coordinates.extend(point for group in planar.groups for cell in group for point in cell.vertices)
    if any(not (scope[0] <= theta <= scope[1] and delta_box.low <= delta <= delta_box.high) for theta, delta in coordinates):
        raise AssertionError("Exposed representation extends outside the original prior bounding box")


def classification(below, above, query):
    now, _, local, deadline = map(F, query)
    if not below and not above:
        action, mode = "INCONSISTENT_MODEL", "EMPTY"
    elif not above:
        action = mode = "REMOTE"
    else:
        action = "LOCAL" if now + local <= deadline else "NO_CERTIFIED_ACTION"
        mode = "MIXED" if below else "LOCAL" if now + local <= deadline else "NO_FEASIBLE_MODE"
    return {"action": action, "uniform_mode": mode, "at_or_below": below, "above": above,
            "threshold": min(now + local, deadline)}


def worker():
    sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
    import fifo_rational_arrangement_checker_v1 as checker
    from shared_scale_comparable_methods_v2 import TightBandPosterior, FacetPlanarPosterior, CompletionEnvelopeSMT
    import z3
    spec = importlib.util.spec_from_file_location("rational_controls", ROOT / FILES[8])
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
    (OUT / "unittest_output.txt").write_text(stream.getvalue(), encoding="utf-8")
    if not result.wasSuccessful():
        write(OUT / "receipt.json", {"status": "FAIL_ANALYTIC_CONTROLS", "tests_run": result.testsRun,
                                     "failures": len(result.failures), "errors": len(result.errors)})
        raise SystemExit(1)
    inputs = json.loads((ROOT / FILES[6]).read_text(encoding="ascii"))["inputs"]
    earlier = json.loads((ROOT / FILES[-1]).read_text(encoding="ascii"))
    completed = {row["input_id"] for row in earlier["observations"]}
    selected = [case for case in inputs if case["factors"]["block"] == 2026101301 and case["id"] not in completed]
    if len(selected) != 6 or sum(len(case["stages"]) + 1 for case in selected) != 153:
        raise AssertionError("Pending selection differs from the fixed protocol")
    saved = {row["controller_id"]: row for row in json.loads((ROOT / FILES[-2]).read_text(encoding="ascii"))}
    counts, observations, curve_cache = Counter(), [], {}
    with (OUT / "slice_transcript.jsonl").open("w", encoding="ascii", buffering=1) as transcript:
        for case in selected:
            scope = (min(F(point[0]) for cell in case["cells"] for point in cell["vertices"]),
                     max(F(point[0]) for cell in case["cells"] for point in cell["vertices"]))
            delta_box = checker.Interval(min(F(point[1]) for cell in case["cells"] for point in cell["vertices"]),
                                         max(F(point[1]) for cell in case["cells"] for point in cell["vertices"]))
            relevant = {len(case["jobs"])}
            for stage in case["stages"]:
                count = stage["report"][0]
                if count:
                    relevant.add(count)
                if count < len(case["jobs"]):
                    relevant.add(count + 1)
            curves = {}
            for count in relevant:
                key = (tuple(tuple(row) for row in case["jobs"]), count, scope)
                if key not in curve_cache:
                    curve_cache[key] = checker.dominance_intervals(checker.all_branches(case["jobs"], count), *scope)
                    counts["independent_all_pair_departure_certificates"] += 1
                curves[count] = curve_cache[key]
            submits, work = [row[0] for row in case["jobs"]], [row[1] for row in case["jobs"]]
            vertices, planes = [cell["vertices"] for cell in case["cells"]], [cell["halfplanes"] for cell in case["cells"]]
            methods = {"band_v2": TightBandPosterior(submits, work, vertices, planes),
                       "planar_v2": FacetPlanarPosterior(submits, work, vertices, planes),
                       "envelope_smt_v2": CompletionEnvelopeSMT([{"t": t, "p": p} for t, p in case["jobs"]], case["cells"], 1000)}
            prior, reports = checker.original_prior(case), []
            for history_index, stage in enumerate([None] + case["stages"]):
                live_queries = {}
                if stage is not None:
                    count, tau = stage["report"]
                    reports.append((count, F(tau)))
                    for name, method in methods.items():
                        (method.add_report if name == "envelope_smt_v2" else method.update)(count, tau)
                        live_queries[name] = method.certificate(*stage["query"])
                bounds_check(methods["band_v2"], methods["planar_v2"], scope, delta_box)
                checker.verify_smt_history(methods["envelope_smt_v2"], case, reports, curves, scope, z3)
                counts["smt_complete_formula_certificates"] += 1
                band = checker.band_formula(methods["band_v2"])
                planar = checker.planar_formula(methods["planar_v2"])
                segments = []
                for count, tau in reports:
                    for side in ([count] if count else []) + ([count + 1] if count < len(case["jobs"]) else []):
                        segments.extend((low, high, -a, tau - b) for low, high, a, b in curves[side])
                if stage is not None:
                    now, new_work, local, deadline = map(F, stage["query"])
                    threshold = min(now + local, deadline)
                    segments.append((*scope, -new_work, threshold - now))
                    segments.extend((low, high, -a - new_work, threshold - b)
                                    for low, high, a, b in curves[len(case["jobs"])])
                theta_points, event_count, segment_count = checker.arrangement_points([prior, band, planar], segments, scope, delta_box)
                below = above = False
                state_digest = hashlib.sha256()
                for theta in theta_points:
                    expected, departures = checker.specification_slice(case, reports, theta, prior, delta_box)
                    actual_band = checker.formula_slice(band, theta, delta_box)
                    actual_planar = checker.formula_slice(planar, theta, delta_box)
                    if expected != actual_band or expected != actual_planar:
                        raise AssertionError((case["id"], history_index, str(theta), "exact_slice_difference",
                                              checker.encoded_intervals(expected), checker.encoded_intervals(actual_band), checker.encoded_intervals(actual_planar)))
                    if stage is not None:
                        first, second = checker.query_sides(expected, theta, departures, stage["query"])
                        below |= first
                        above |= second
                    row = {"input_id": case["id"], "history_index": history_index,
                           "theta": str(theta), "specification_and_both_geometric_slices": checker.encoded_intervals(expected)}
                    line = json.dumps(row, separators=(",", ":")) + "\n"
                    transcript.write(line)
                    state_digest.update(line.encode("ascii"))
                    counts["critical_and_open_interval_slices"] += 1
                if stage is not None:
                    expected_result = classification(below, above, stage["query"])
                    for name in methods:
                        for label, query in (("live", live_queries[name]),
                                             ("saved", saved[case["id"] + ":" + name]["queries"][history_index - 1])):
                            if query["status"] != "EXACT" or any((F(query[key]) if key == "threshold" else query[key]) != value
                                                                   for key, value in expected_result.items()):
                                raise AssertionError((case["id"], history_index, name, label, "query_difference"))
                        counts[name + "_live_and_saved_queries"] += 1
                    counts["query_tuples"] += 1
                observations.append({"input_id": case["id"], "history_index": history_index,
                                     "critical_theta_events": event_count, "boundary_segments": segment_count,
                                     "checked_slices": len(theta_points), "transcript_sha256": state_digest.hexdigest(),
                                     "all_three_complete_sets_equal": True})
                counts["history_states"] += 1
                write(OUT / "progress.json", {"counts": dict(counts), "input_id": case["id"], "history_index": history_index})
            counts["complete_inputs"] += 1
            print(json.dumps({"complete_inputs": counts["complete_inputs"], "pending_inputs": 6,
                              "history_states": counts["history_states"]}), flush=True)
    if counts["history_states"] != 153 or counts["query_tuples"] != 147:
        raise AssertionError("Incomplete rational coverage")
    write(OUT / "receipt.json", {"status": "PASS_ALL_SIX_PENDING_RATIONAL_HISTORIES",
                                 "analytic_tests_run": result.testsRun, "analytic_failures": 0, "analytic_errors": 0,
                                 "counts": dict(counts), "observations": observations,
                                 "selected_input_ids": [case["id"] for case in selected], "python": sys.version,
                                 "z3_native_version": z3.get_version_string(), "oracle_solver_calls": 0,
                                 "new_performance_timing_samples": 0, "previous_acquisitions_rerun": False,
                                 "slice_transcript_sha256": hashlib.sha256((OUT / "slice_transcript.jsonl").read_bytes()).hexdigest(),
                                 "boundary": "Finite exhaustive rational strata plus independently certified retained SMT formulas; not general program verification, novelty or timing confirmation"})


def main():
    if sys.argv[1:] == ["--worker"]:
        worker()
        return
    if OUT.exists():
        raise FileExistsError("Preserve this resolution outcome")
    before = hashes()
    OUT.mkdir()
    write(OUT / "preflight.json", {"source_sha256": before})
    start = time.perf_counter()
    with (OUT / "stderr.txt").open("w", encoding="ascii") as stderr:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker"], cwd=ROOT, stderr=stderr)
        timed_out = False
        try:
            code = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            code = child.wait()
    after = hashes()
    path = OUT / "receipt.json"
    receipt = json.loads(path.read_text(encoding="ascii")) if path.exists() else {"status": "FAIL_OR_INCOMPLETE"}
    receipt.update({"source_sha256": before, "sources_unchanged": before == after, "child_exit_code": code,
                    "hard_timeout_reached": timed_out, "operational_validation_seconds": time.perf_counter() - start})
    if code or timed_out or before != after:
        receipt["status"] = "FAIL_OR_INCOMPLETE"
    write(path, receipt)
    print(json.dumps({key: receipt.get(key) for key in ("status", "counts", "analytic_tests_run", "sources_unchanged",
                                                       "hard_timeout_reached", "operational_validation_seconds")}))
    if receipt["status"] != "PASS_ALL_SIX_PENDING_RATIONAL_HISTORIES":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
