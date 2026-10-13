"""One-shot structural comparison with externally enforced timeout and raw events."""

from collections import Counter, defaultdict
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/fifo_structural_comparison_v2"
INPUT = ROOT / "protocols/fifo_structural_inputs_v2.json"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")
SOURCES = (
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
    "protocols/fifo_comparable_correctness_gate_v3.md",
    "protocols/fifo_structural_comparison_v2.md",
    "protocols/fifo_structural_inputs_v2.json",
    "scripts/generate_fifo_structural_inputs_v2.py",
    "scripts/run_fifo_structural_comparison_v2.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="ascii")


def stage_ids(case):
    return ["setup"] + [f"{operation}_{i}" for i in range(len(case["stages"]))
                         for operation in ("update", "query")]


def make_actor(name, case):
    from shared_scale_comparable_methods_v2 import (
        CompletionEnvelopeSMT, FacetPlanarPosterior, TightBandPosterior,
    )
    if name == "envelope_smt_v2":
        return CompletionEnvelopeSMT([{"t": t, "p": p} for t, p in case["jobs"]], case["cells"], 1000)
    constructor = TightBandPosterior if name == "band_v2" else FacetPlanarPosterior
    return constructor([row[0] for row in case["jobs"]], [row[1] for row in case["jobs"]],
                       [cell["vertices"] for cell in case["cells"]],
                       [cell["halfplanes"] for cell in case["cells"]])


def integer_bits(values):
    max_num = max_den = 0
    for value in values:
        rational = F(value)
        max_num = max(max_num, abs(rational.numerator).bit_length())
        max_den = max(max_den, rational.denominator.bit_length())
    return {"max_numerator_bits": max_num, "max_denominator_bits": max_den}


def diagnostics(name, actor):
    if name == "band_v2":
        values = []
        bands = points = 0
        for component in actor.components:
            bands += len(component.bands)
            points += len(component.points)
            for band in component.bands:
                values.extend((band.left, band.right))
                for bound in (band.lower, band.upper):
                    values.extend((bound.line.slope, bound.line.intercept))
            for point in component.points:
                values.extend((point.theta, point.lower.value, point.upper.value))
        return {"bands": bands, "points": points, "components": len(actor.components),
                "reports": len(actor.reports), **integer_bits(values)}
    if name == "planar_v2":
        cells = [cell for group in actor.groups for cell in group]
        values = [value for cell in cells for point in cell.vertices for value in point]
        values += [value for cell in cells for plane in cell.strict for value in plane]
        return {**actor.representation_counts(), **integer_bits(values)}
    return {"reports": len(actor.reports), "cached_departure_counts": len(actor.compiled),
            "cached_affine_terms": sum(len(terms) for terms in actor.compiled.values()),
            "assertions": len(actor.solver.assertions()), "sat_queries": actor.sat_queries}


def acquire():
    sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
    import z3
    import shared_scale_comparable_methods_v2
    del shared_scale_comparable_methods_v2
    cases = json.loads(INPUT.read_text(encoding="ascii"))["inputs"]
    results = []
    with (OUT / "raw_events.jsonl").open("w", encoding="ascii", buffering=1) as events:
        def emit(value):
            events.write(json.dumps(value, default=str) + "\n")

        for case_index, case in enumerate(cases):
            for name in case["method_order"]:
                controller_id = case["id"] + ":" + name
                dump(OUT / "active_controller.json", {"controller_id": controller_id, "case_index": case_index})
                operational_start = time.perf_counter_ns()
                emit({"event": "controller_start", "controller_id": controller_id,
                      "operational_start_ns": operational_start})
                row = {"controller_id": controller_id, "input_id": case["id"], "method": name,
                       "factors": case["factors"], "method_order": case["method_order"],
                       "status": "COMPLETE", "stage_cost_ns": {}, "queries": [], "diagnostics": []}
                actor = None

                def measured(stage_id, operation, call):
                    start = time.perf_counter_ns()
                    try:
                        value = call()
                    except Exception as error:
                        end = time.perf_counter_ns()
                        record = {"event": "stage", "controller_id": controller_id, "stage_id": stage_id,
                                  "operation": operation, "start_ns": start, "end_ns": end,
                                  "elapsed_ns": end - start, "status": "ERROR",
                                  "error": type(error).__name__ + ": " + str(error)}
                        emit(record)
                        row["stage_cost_ns"][stage_id] = end - start
                        row["status"], row["error"] = "ERROR", record["error"]
                        return None, False
                    end = time.perf_counter_ns()
                    status = value.get("status", "ERROR") if operation == "query" else "OK"
                    record = {"event": "stage", "controller_id": controller_id, "stage_id": stage_id,
                              "operation": operation, "start_ns": start, "end_ns": end,
                              "elapsed_ns": end - start, "status": status}
                    if operation == "query":
                        record["result"] = value
                    emit(record)
                    row["stage_cost_ns"][stage_id] = end - start
                    if operation == "query" and status != "EXACT":
                        row["status"] = status
                        return value, False
                    return value, True

                actor, ok = measured("setup", "setup", lambda: make_actor(name, case))
                if ok:
                    row["diagnostics"].append({"after": "setup", **diagnostics(name, actor)})
                    for index, stage in enumerate(case["stages"]):
                        report = stage["report"]
                        update = actor.add_report if name == "envelope_smt_v2" else actor.update
                        _, ok = measured(f"update_{index}", "update", lambda: update(*report))
                        if not ok:
                            break
                        row["diagnostics"].append({"after": f"update_{index}", **diagnostics(name, actor)})
                        value, ok = measured(f"query_{index}", "query", lambda: actor.certificate(*stage["query"]))
                        if value is not None:
                            row["queries"].append({"stage_id": f"query_{index}", **value})
                        if not ok:
                            break
                operational_end = time.perf_counter_ns()
                row["full_algorithm_call_ns"] = sum(row["stage_cost_ns"].values())
                row["operational_elapsed_ns"] = operational_end - operational_start
                row["not_run_stages"] = [key for key in stage_ids(case) if key not in row["stage_cost_ns"]]
                if row["not_run_stages"] and row["status"] == "COMPLETE":
                    row["status"] = "INCOMPLETE"
                emit({"event": "controller_end", "controller_id": controller_id,
                      "operational_end_ns": operational_end, "status": row["status"],
                      "full_algorithm_call_ns": row["full_algorithm_call_ns"]})
                results.append(row)
                dump(OUT / "controller_results.json", results)
            if (case_index + 1) % 16 == 0:
                print(json.dumps({"completed_inputs": case_index + 1, "total_inputs": len(cases)}), flush=True)
    dump(OUT / "acquisition_completion.json", {"status": "TERMINAL", "controllers": len(results),
                                               "z3_native_version": z3.get_version_string()})


def preflight():
    sys.path.insert(0, str(ROOT / "scripts"))
    from generate_fifo_structural_inputs_v2 import generate
    data = json.loads(INPUT.read_text(encoding="ascii"))
    if data != generate():
        raise AssertionError("Locked input differs from prospective deterministic generator")
    source_hashes = {name: digest(ROOT / name) for name in SOURCES}
    gate = json.loads((ROOT / "artifacts/fifo_comparable_correctness_v3/receipt.json").read_text(encoding="ascii"))
    if gate["status"] != "PASS_FIXED_SET_AND_QUERY_PARITY" or not gate["sources_unchanged"]:
        raise AssertionError("Correctness gate has not passed")
    for source in SOURCES[:5]:
        if source_hashes[source] != gate["source_sha256"][source]:
            raise AssertionError("Actor changed since correctness gate: " + source)
    orders = defaultdict(list)
    for case in data["inputs"]:
        key = tuple(case["factors"][field] for field in ("n", "m", "components", "precision_bits", "family"))
        orders[key].append(tuple(case["method_order"]))
    if len(orders) != 32 or any(len(set(rows)) != 6 for rows in orders.values()):
        raise AssertionError("Method orders not completely counterbalanced")
    return data, {"source_sha256": source_hashes, "correctness_receipt_sha256": digest(
        ROOT / "artifacts/fifo_comparable_correctness_v3/receipt.json"),
        "planned_inputs": 192, "planned_controllers": 576,
        "planned_stages": sum(3 * len(stage_ids(case)) for case in data["inputs"]),
        "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
        "hard_wall_cap_seconds": 900, "solver_timeout_ms_per_check": 1000,
        "timing_resampling": False, "previous_acquisitions_rerun": False}


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--acquire":
        acquire()
        return
    if OUT.exists():
        raise FileExistsError("Preserve the one-shot acquisition; no automatic retry")
    data, before = preflight()
    OUT.mkdir()
    dump(OUT / "preflight.json", before)
    start = time.perf_counter_ns()
    timed_out = False
    with (OUT / "stdout.txt").open("w", encoding="ascii") as stdout, (OUT / "stderr.txt").open("w", encoding="ascii") as stderr:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--acquire"],
                                 cwd=ROOT, stdout=stdout, stderr=stderr)
        dump(OUT / "process.json", {"pid": child.pid, "started_perf_counter_ns": start,
                                   "hard_wall_cap_seconds": 900})
        try:
            returncode = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            returncode = child.wait()
    elapsed = time.perf_counter_ns() - start
    results_path = OUT / "controller_results.json"
    results = json.loads(results_path.read_text(encoding="ascii")) if results_path.exists() else []
    by_id = {row["controller_id"]: row for row in results}
    observed_stages = defaultdict(set)
    raw_path = OUT / "raw_events.jsonl"
    if raw_path.exists():
        for line in raw_path.read_text(encoding="ascii").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "stage":
                observed_stages[event["controller_id"]].add(event["stage_id"])
    inventory = []
    for case in data["inputs"]:
        for name in case["method_order"]:
            cid = case["id"] + ":" + name
            inventory.append({"controller_id": cid, "status": by_id[cid]["status"] if cid in by_id else
                              "PARTIAL" if observed_stages[cid] else "NOT_RUN",
                              "not_run_stages": [key for key in stage_ids(case) if key not in observed_stages[cid]]})
    dump(OUT / "expected_not_run_inventory.json", inventory)
    after = {name: digest(ROOT / name) for name in SOURCES}
    statuses = Counter(row["status"] for row in inventory)
    eligible = mismatches = 0
    for case in data["inputs"]:
        rows = [by_id.get(case["id"] + ":" + name) for name in METHODS]
        if not all(row is not None and row["status"] == "COMPLETE" for row in rows):
            continue
        eligible += 1
        for queries in zip(*(row["queries"] for row in rows)):
            semantics = [tuple(query[key] for key in ("action", "uniform_mode", "threshold", "at_or_below", "above"))
                         for query in queries]
            mismatches += len(set(semantics)) != 1
    manifest = {**before, "source_unchanged": before["source_sha256"] == after,
                "child_exit_code": returncode, "hard_timeout_reached": timed_out,
                "operational_acquisition_seconds": elapsed / 1e9, "controller_statuses": dict(statuses),
                "three_method_eligible_inputs": eligible, "query_mismatches": mismatches,
                "status": "COMPLETE" if returncode == 0 and statuses == {"COMPLETE": 576}
                and eligible == 192 and mismatches == 0 and before["source_sha256"] == after else "INCOMPLETE_OR_FAILED",
                "record_sha256": {name: digest(OUT / name) for name in
                                  ("controller_results.json", "raw_events.jsonl", "expected_not_run_inventory.json")
                                  if (OUT / name).exists()},
                "scope": "New synthetic input-specific cost comparison, not novelty or publication clearance"}
    dump(OUT / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("status", "controller_statuses", "three_method_eligible_inputs",
                                                    "query_mismatches", "operational_acquisition_seconds", "hard_timeout_reached")}))
    if manifest["status"] != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
