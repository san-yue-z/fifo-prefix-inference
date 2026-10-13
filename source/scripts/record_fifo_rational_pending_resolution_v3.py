"""Record the versioned interface repair and identical full rational resolution."""

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
OUT = ROOT / "artifacts/fifo_rational_pending_resolution_v3"
FILES = (
    "src/chunk_scheduling/fifo_rational_arrangement_checker_v1.py",
    "src/chunk_scheduling/fifo_rational_arrangement_checker_v2.py",
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
    "protocols/fifo_structural_inputs_v2.json", "protocols/fifo_rational_pending_resolution_v1.md",
    "protocols/fifo_rational_pending_resolution_v2.md", "tests/test_fifo_rational_arrangement_checker_v1.py",
    "tests/test_fifo_rational_arrangement_checker_v2.py", "scripts/record_fifo_rational_pending_resolution_v1.py",
    "scripts/record_fifo_rational_pending_resolution_v2.py",
    "artifacts/fifo_structural_comparison_v2/controller_results.json",
    "artifacts/fifo_structural_unpruned_gate_v6/receipt.json",
    "artifacts/fifo_rational_pending_resolution_v1/receipt.json",
    "src/chunk_scheduling/fifo_rational_arrangement_checker_v3.py",
    "protocols/fifo_rational_pending_resolution_v3.md",
    "tests/test_fifo_rational_arrangement_checker_v3.py",
    "scripts/record_fifo_rational_pending_resolution_v3.py",
    "artifacts/fifo_rational_pending_resolution_v2/receipt.json",
)


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="ascii")


def module_at(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worker():
    sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
    import fifo_rational_arrangement_checker_v3 as checker
    from shared_scale_comparable_methods_v2 import TightBandPosterior, FacetPlanarPosterior, CompletionEnvelopeSMT
    import z3
    common = module_at("pending_helpers", "scripts/record_fifo_rational_pending_resolution_v1.py")
    suite = unittest.TestSuite()
    for index, relative in enumerate((FILES[10], FILES[11], "tests/test_fifo_rational_arrangement_checker_v3.py")):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module_at(f"rational_controls_{index}", relative)))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (OUT / "unittest_output.txt").write_text(stream.getvalue(), encoding="utf-8")
    if not result.wasSuccessful():
        write(OUT / "receipt.json", {"status": "FAIL_ANALYTIC_CONTROLS", "tests_run": result.testsRun,
                                     "failures": len(result.failures), "errors": len(result.errors)})
        raise SystemExit(1)
    inputs = json.loads((ROOT / "protocols/fifo_structural_inputs_v2.json").read_text(encoding="ascii"))["inputs"]
    earlier = json.loads((ROOT / "artifacts/fifo_structural_unpruned_gate_v6/receipt.json").read_text(encoding="ascii"))
    complete = {row["input_id"] for row in earlier["observations"]}
    selected = [case for case in inputs if case["factors"]["block"] == 2026101301 and case["id"] not in complete]
    if len(selected) != 6 or sum(len(case["stages"]) + 1 for case in selected) != 153:
        raise AssertionError("Wrong prospective selection")
    saved = {row["controller_id"]: row for row in json.loads((ROOT / "artifacts/fifo_structural_comparison_v2/controller_results.json").read_text(encoding="ascii"))}
    counts, observations, cache = Counter(), [], {}
    with (OUT / "slice_transcript.jsonl").open("w", encoding="ascii", buffering=1) as transcript:
        for case in selected:
            scope = (min(F(p[0]) for cell in case["cells"] for p in cell["vertices"]),
                     max(F(p[0]) for cell in case["cells"] for p in cell["vertices"]))
            delta_box = checker.Interval(min(F(p[1]) for cell in case["cells"] for p in cell["vertices"]),
                                         max(F(p[1]) for cell in case["cells"] for p in cell["vertices"]))
            relevant = {len(case["jobs"])}
            for stage in case["stages"]:
                count = stage["report"][0]
                relevant.update(([count] if count else []) + ([count + 1] if count < len(case["jobs"]) else []))
            curves = {}
            for count in relevant:
                key = (tuple(tuple(row) for row in case["jobs"]), count, scope)
                if key not in cache:
                    cache[key] = checker.dominance_intervals(checker.all_branches(case["jobs"], count), *scope)
                    counts["independent_all_pair_departure_certificates"] += 1
                curves[count] = cache[key]
            submits, work = [row[0] for row in case["jobs"]], [row[1] for row in case["jobs"]]
            vertices, planes = [cell["vertices"] for cell in case["cells"]], [cell["halfplanes"] for cell in case["cells"]]
            methods = {"band_v2": TightBandPosterior(submits, work, vertices, planes),
                       "planar_v2": FacetPlanarPosterior(submits, work, vertices, planes),
                       "envelope_smt_v2": CompletionEnvelopeSMT([{"t": t, "p": p} for t, p in case["jobs"]], case["cells"], 1000)}
            prior, reports = checker.original_prior(case), []
            for history_index, stage in enumerate([None] + case["stages"]):
                live = {}
                if stage is not None:
                    count, tau = stage["report"]
                    reports.append((count, F(tau)))
                    for name, method in methods.items():
                        (method.add_report if name == "envelope_smt_v2" else method.update)(count, tau)
                        live[name] = method.certificate(*stage["query"])
                common.bounds_check(methods["band_v2"], methods["planar_v2"], scope, delta_box)
                checker.verify_smt_history(methods["envelope_smt_v2"], case, reports, curves, scope, z3)
                counts["smt_complete_formula_certificates"] += 1
                band, planar = checker.band_formula(methods["band_v2"]), checker.planar_formula(methods["planar_v2"])
                segments = []
                for count, tau in reports:
                    for side in ([count] if count else []) + ([count + 1] if count < len(case["jobs"]) else []):
                        segments.extend((low, high, -a, tau - b) for low, high, a, b in curves[side])
                if stage is not None:
                    now, new_work, local, deadline = map(F, stage["query"])
                    threshold = min(now + local, deadline)
                    segments.append((*scope, -new_work, threshold - now))
                    segments.extend((low, high, -a - new_work, threshold - b) for low, high, a, b in curves[len(case["jobs"])])
                points, event_count, segment_count = checker.arrangement_points([prior, band, planar], segments, scope, delta_box)
                below = above = False
                state_sha = hashlib.sha256()
                for theta in points:
                    expected, departures = checker.specification_slice(case, reports, theta, prior, delta_box)
                    observed = [checker.formula_slice(expression, theta, delta_box) for expression in (band, planar)]
                    if any(value != expected for value in observed):
                        raise AssertionError((case["id"], history_index, str(theta), "exact_slice_difference"))
                    if stage is not None:
                        first, second = checker.query_sides(expected, theta, departures, stage["query"])
                        below |= first
                        above |= second
                    row = {"input_id": case["id"], "history_index": history_index, "theta": str(theta),
                           "specification_and_both_geometric_slices": checker.encoded_intervals(expected)}
                    line = json.dumps(row, separators=(",", ":")) + "\n"
                    transcript.write(line)
                    state_sha.update(line.encode("ascii"))
                    counts["critical_and_open_interval_slices"] += 1
                if stage is not None:
                    expected_query = common.classification(below, above, stage["query"])
                    for name in methods:
                        for label, value in (("live", live[name]), ("saved", saved[case["id"] + ":" + name]["queries"][history_index - 1])):
                            if value["status"] != "EXACT" or any((F(value[key]) if key == "threshold" else value[key]) != target
                                                                   for key, target in expected_query.items()):
                                raise AssertionError((case["id"], history_index, name, label, "query_difference"))
                        counts[name + "_live_and_saved_queries"] += 1
                    counts["query_tuples"] += 1
                observations.append({"input_id": case["id"], "history_index": history_index,
                                     "critical_theta_events": event_count, "boundary_segments": segment_count,
                                     "checked_slices": len(points), "transcript_sha256": state_sha.hexdigest(),
                                     "all_three_complete_sets_equal": True})
                counts["history_states"] += 1
                write(OUT / "progress.json", {"counts": dict(counts), "input_id": case["id"], "history_index": history_index})
            counts["complete_inputs"] += 1
            print(json.dumps({"complete_inputs": counts["complete_inputs"], "selected_inputs": 6,
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
                                 "boundary": "Finite exhaustive rational strata and independently certified retained SMT formulas; not general verification, novelty or timing confirmation"})


def main():
    if sys.argv[1:] == ["--worker"]:
        worker()
        return
    if OUT.exists():
        raise FileExistsError("Preserve every resolution outcome")
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
