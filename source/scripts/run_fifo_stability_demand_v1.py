"""One preserved follow-up acquisition with fresh actors and balanced orders."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/fifo_stability_demand_v1"
INPUT = ROOT / "protocols/fifo_stability_demand_inputs_v1.json"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")
ACTORS = (
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
)
SOURCES = ACTORS + (
    "protocols/fifo_measurement_stability_demand_v1.md",
    "protocols/fifo_stability_demand_inputs_v1.json",
    "scripts/freeze_fifo_stability_demand_inputs_v1.py",
    "scripts/run_fifo_stability_demand_v1.py",
    "scripts/run_fifo_structural_comparison_v2.py",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="ascii")


def stage_ids(cell):
    keys = ["setup"]
    for i, stage in enumerate(cell["stages"]):
        keys.append(f"update_{i}")
        keys.extend(f"query_{i}_{k}" for k in range(len(stage["queries"])))
    return keys


def cid(run, method):
    return run["cell_id"] + f":r{run['repetition']}:" + method


def environment():
    commands = {
        "processor": "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress",
        "memory": "Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory | ConvertTo-Json -Compress",
        "power_scheme": "powercfg /getactivescheme",
    }
    values = {"platform": platform.platform(), "python": sys.version, "executable": sys.executable,
              "observed_at_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "affinity_control": False, "temperature_frequency_trace": False,
              "dedicated_idle_machine": False, "scope": "Observed for this new campaign only"}
    for label, command in commands.items():
        try:
            done = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            values[label] = {"returncode": done.returncode, "stdout": done.stdout.strip(),
                             "stderr": done.stderr.strip()}
        except Exception as error:
            values[label] = {"unavailable": type(error).__name__ + ": " + str(error)}
    return values


def acquire():
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src/chunk_scheduling"))
    import z3
    import shared_scale_comparable_methods_v2
    from run_fifo_structural_comparison_v2 import diagnostics, make_actor
    del shared_scale_comparable_methods_v2
    data = json.loads(INPUT.read_text(encoding="ascii"))
    cells = {cell["id"]: cell for cell in data["cells"]}
    with (OUT / "raw_events.jsonl").open("w", encoding="ascii", buffering=1) as events, \
            (OUT / "controller_results.jsonl").open("w", encoding="ascii", buffering=1) as results:
        def emit(value):
            events.write(json.dumps(value, default=str) + "\n")

        for run_index, run in enumerate(data["runs"]):
            cell = cells[run["cell_id"]]
            for method in run["method_order"]:
                controller_id = cid(run, method)
                start = time.perf_counter_ns()
                emit({"event": "controller_start", "controller_id": controller_id,
                      "operational_start_ns": start})
                row = {"controller_id": controller_id, "cell_id": cell["id"], "method": method,
                       "repetition": run["repetition"], "method_order": run["method_order"],
                       "status": "COMPLETE", "stage_cost_ns": {}, "queries": [], "diagnostics": []}

                def measured(key, operation, call):
                    begin = time.perf_counter_ns()
                    try:
                        value = call()
                    except Exception as error:
                        end = time.perf_counter_ns()
                        record = {"event": "stage", "controller_id": controller_id, "stage_id": key,
                                  "operation": operation, "start_ns": begin, "end_ns": end,
                                  "elapsed_ns": end - begin, "status": "ERROR",
                                  "error": type(error).__name__ + ": " + str(error)}
                        emit(record)
                        row["stage_cost_ns"][key] = end - begin
                        row["status"], row["error"] = "ERROR", record["error"]
                        return None, False
                    end = time.perf_counter_ns()
                    status = value.get("status", "ERROR") if operation == "query" else "OK"
                    record = {"event": "stage", "controller_id": controller_id, "stage_id": key,
                              "operation": operation, "start_ns": begin, "end_ns": end,
                              "elapsed_ns": end - begin, "status": status}
                    if operation == "query":
                        record["result"] = value
                    emit(record)
                    row["stage_cost_ns"][key] = end - begin
                    if operation == "query" and status != "EXACT":
                        row["status"] = status
                        return value, False
                    return value, True

                actor, ok = measured("setup", "setup", lambda: make_actor(method, cell))
                if ok:
                    row["diagnostics"].append({"after": "setup", **diagnostics(method, actor)})
                    for i, stage in enumerate(cell["stages"]):
                        update = actor.add_report if method == "envelope_smt_v2" else actor.update
                        _, ok = measured(f"update_{i}", "update", lambda: update(*stage["report"]))
                        if not ok:
                            break
                        row["diagnostics"].append({"after": f"update_{i}", **diagnostics(method, actor)})
                        for k, query in enumerate(stage["queries"]):
                            value, ok = measured(f"query_{i}_{k}", "query", lambda: actor.certificate(*query))
                            if value is not None:
                                row["queries"].append({"stage_id": f"query_{i}_{k}", **value})
                            if not ok:
                                break
                        if not ok:
                            break
                end = time.perf_counter_ns()
                row["full_algorithm_call_ns"] = sum(row["stage_cost_ns"].values())
                row["operational_elapsed_ns"] = end - start
                row["not_run_stages"] = [key for key in stage_ids(cell) if key not in row["stage_cost_ns"]]
                if row["not_run_stages"] and row["status"] == "COMPLETE":
                    row["status"] = "INCOMPLETE"
                emit({"event": "controller_end", "controller_id": controller_id, "operational_end_ns": end,
                      "full_algorithm_call_ns": row["full_algorithm_call_ns"], "status": row["status"]})
                results.write(json.dumps(row, default=str) + "\n")
            if (run_index + 1) % 36 == 0:
                print(json.dumps({"paired_workflows_done": run_index + 1, "planned": len(data["runs"])}), flush=True)
    dump(OUT / "acquisition_completion.json", {"status": "TERMINAL", "z3_version": z3.get_version_string()})


def main():
    if sys.argv[1:] == ["--acquire"]:
        acquire()
        return
    if OUT.exists():
        raise FileExistsError("Preserve acquisition; no automatic retry")
    sys.path.insert(0, str(ROOT / "scripts"))
    from freeze_fifo_stability_demand_inputs_v1 import generate
    data = json.loads(INPUT.read_text(encoding="ascii"))
    if data != generate():
        raise AssertionError("Locked workflow generation mismatch")
    gate = json.loads((ROOT / "artifacts/fifo_comparable_correctness_v3/receipt.json").read_text(encoding="ascii"))
    hashes = {name: sha(ROOT / name) for name in SOURCES}
    if gate["status"] != "PASS_FIXED_SET_AND_QUERY_PARITY" or not gate["sources_unchanged"]:
        raise AssertionError("Missing correctness gate")
    if any(hashes[name] != gate["source_sha256"][name] for name in ACTORS):
        raise AssertionError("Measured actor source changed")
    OUT.mkdir()
    dump(OUT / "environment_before.json", environment())
    before = {"source_sha256": hashes, "planned_cells": 36, "planned_paired_workflows": 216,
              "planned_controllers": 648, "planned_query_tuples": data["planned_query_tuples"],
              "hard_wall_cap_seconds": 900, "solver_timeout_ms_per_check": 1000,
              "timing_resampling": False, "original_acquisition_overwritten": False}
    dump(OUT / "preflight.json", before)
    start = time.perf_counter_ns()
    timeout = False
    with (OUT / "stdout.txt").open("w", encoding="ascii") as stdout, (OUT / "stderr.txt").open("w", encoding="ascii") as stderr:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--acquire"],
                                 cwd=ROOT, stdout=stdout, stderr=stderr)
        dump(OUT / "process.json", {"pid": child.pid, "start_ns": start, "hard_wall_cap_seconds": 900})
        try:
            code = child.wait(timeout=900)
        except subprocess.TimeoutExpired:
            timeout = True
            child.kill()
            code = child.wait()
    elapsed = time.perf_counter_ns() - start
    dump(OUT / "environment_after.json", environment())
    cells = {cell["id"]: cell for cell in data["cells"]}
    result_path = OUT / "controller_results.jsonl"
    rows = [json.loads(line) for line in result_path.read_text(encoding="ascii").splitlines()] if result_path.exists() else []
    by_id = {row["controller_id"]: row for row in rows}
    observed = defaultdict(set)
    if (OUT / "raw_events.jsonl").exists():
        for line in (OUT / "raw_events.jsonl").read_text(encoding="ascii").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "stage":
                observed[event["controller_id"]].add(event["stage_id"])
    inventory = []
    for run in data["runs"]:
        for method in run["method_order"]:
            key = cid(run, method)
            inventory.append({"controller_id": key, "status": by_id[key]["status"] if key in by_id else
                              "PARTIAL" if observed[key] else "NOT_RUN",
                              "not_run_stages": [stage for stage in stage_ids(cells[run["cell_id"]]) if stage not in observed[key]]})
    dump(OUT / "expected_not_run_inventory.json", inventory)
    statuses = Counter(row["status"] for row in inventory)
    eligible = mismatches = 0
    for run in data["runs"]:
        group = [by_id.get(cid(run, method)) for method in METHODS]
        if not all(row is not None and row["status"] == "COMPLETE" for row in group):
            continue
        eligible += 1
        for queries in zip(*(row["queries"] for row in group)):
            semantics = [tuple(query[key] for key in ("stage_id", "at_or_below", "above", "threshold", "action", "uniform_mode"))
                         for query in queries]
            mismatches += len(set(semantics)) != 1
    unchanged = hashes == {name: sha(ROOT / name) for name in SOURCES}
    manifest = {**before, "controller_statuses": dict(statuses), "child_exit_code": code,
                "hard_timeout_reached": timeout, "operational_acquisition_seconds": elapsed / 1e9,
                "source_unchanged": unchanged, "eligible_paired_workflows": eligible,
                "query_mismatches": mismatches,
                "status": "COMPLETE" if code == 0 and statuses == {"COMPLETE": 648} and eligible == 216
                and mismatches == 0 and unchanged else "INCOMPLETE_OR_FAILED",
                "record_sha256": {name: sha(OUT / name) for name in
                                  ("controller_results.jsonl", "raw_events.jsonl", "expected_not_run_inventory.json")
                                  if (OUT / name).exists()},
                "scope": "Separate outcome-selected fixed-instance campaign; not pooled with original timings"}
    dump(OUT / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("status", "controller_statuses", "eligible_paired_workflows",
                                                    "query_mismatches", "operational_acquisition_seconds", "hard_timeout_reached")}))
    if manifest["status"] != "COMPLETE":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
