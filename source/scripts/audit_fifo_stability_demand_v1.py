"""Reconcile the separate acquisition and describe fixed-instance dispersion."""

from collections import Counter, defaultdict
import csv
from fractions import Fraction as F
import hashlib
from itertools import permutations
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/fifo_stability_demand_v1"
OUT = ROOT / "artifacts/fifo_stability_demand_audit_v1"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")


def demand(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_stages(cell):
    keys = ["setup"]
    for i, stage in enumerate(cell["stages"]):
        keys.append(f"update_{i}")
        keys += [f"query_{i}_{k}" for k in range(len(stage["queries"]))]
    return keys


def expected_id(run, method):
    return run["cell_id"] + f":r{run['repetition']}:" + method


def semantic(query, args):
    now, work, local, deadline = map(F, args)
    below, above = query["at_or_below"], query["above"]
    demand(query["status"] == "EXACT" and type(below) is bool and type(above) is bool, "Nonexact predicate")
    if not below and not above:
        action, mode = "INCONSISTENT_MODEL", "EMPTY"
    elif not above:
        action = mode = "REMOTE"
    else:
        action = "LOCAL" if now + local <= deadline else "NO_CERTIFIED_ACTION"
        mode = "MIXED" if below else "LOCAL" if now + local <= deadline else "NO_FEASIBLE_MODE"
    threshold = min(deadline, now + local)
    demand((query["action"], query["uniform_mode"], F(query["threshold"])) == (action, mode, threshold),
           "Classification or threshold mismatch")
    return below, above, threshold, action, mode


def verify(data, rows, events, inventory):
    cells = {cell["id"]: cell for cell in data["cells"]}
    demand(len(cells) == 36 and len(data["runs"]) == 216, "Cell/run count")
    planned = [expected_id(run, method) for run in data["runs"] for method in run["method_order"]]
    demand(len(planned) == len(set(planned)) == len(rows) == 648, "Controller count")
    demand([row["controller_id"] for row in rows] == planned, "Result order")
    demand([e["controller_id"] for e in events if e["event"] == "controller_start"] == planned, "Raw order")
    by_id = {row["controller_id"]: row for row in rows}
    inv = {row["controller_id"]: row for row in inventory}
    demand(len(inv) == len(inventory) == 648 and set(inv) == set(planned), "Inventory")
    raw = defaultdict(list)
    for event in events:
        raw[event["controller_id"]].append(event)
    orders = defaultdict(set)
    counts = Counter()
    previous_end = -1
    for run in data["runs"]:
        cell = cells[run["cell_id"]]
        orders[cell["id"]].add(tuple(run["method_order"]))
        semantics = defaultdict(list)
        for method in run["method_order"]:
            key = expected_id(run, method)
            row, sequence = by_id[key], raw[key]
            demand(row["status"] == inv[key]["status"] == "COMPLETE", "Incomplete controller")
            demand(row["repetition"] == run["repetition"] and row["method_order"] == run["method_order"], "Run metadata")
            demand(not row["not_run_stages"] and not inv[key]["not_run_stages"], "Unrun stages")
            demand(sequence[0]["event"] == "controller_start" and sequence[-1]["event"] == "controller_end", "Controller endpoints")
            start, end = sequence[0]["operational_start_ns"], sequence[-1]["operational_end_ns"]
            demand(previous_end <= start < end, "Overlapping controllers")
            previous_end = end
            stages = [e for e in sequence if e["event"] == "stage"]
            expected = expected_stages(cell)
            demand([e["stage_id"] for e in stages] == expected == list(row["stage_cost_ns"]), "Stage order")
            last = start
            for event in stages:
                demand(last <= event["start_ns"] < event["end_ns"] <= end, "Stage endpoints")
                demand(type(event["elapsed_ns"]) is int and event["elapsed_ns"] > 0, "Invalid cost")
                demand(event["elapsed_ns"] == event["end_ns"] - event["start_ns"] == row["stage_cost_ns"][event["stage_id"]], "Timer reconciliation")
                demand(event["status"] == ("EXACT" if event["operation"] == "query" else "OK"), "Stage failure")
                counts[event["operation"]] += 1
                last = event["end_ns"]
            total = sum(e["elapsed_ns"] for e in stages)
            demand(total == row["full_algorithm_call_ns"] == sequence[-1]["full_algorithm_call_ns"], "Full cost")
            demand(row["operational_elapsed_ns"] == end - start >= total, "Operational cost")
            qevents = [e for e in stages if e["operation"] == "query"]
            qargs = [(f"query_{i}_{k}", q) for i, stage in enumerate(cell["stages"]) for k, q in enumerate(stage["queries"])]
            demand(len(row["queries"]) == len(qevents) == len(qargs), "Query count")
            for query, event, (stage_key, args) in zip(row["queries"], qevents, qargs):
                demand(query["stage_id"] == event["stage_id"] == stage_key, "Query index")
                demand({k: v for k, v in query.items() if k != "stage_id"} == event["result"], "Raw query equality")
                semantics[stage_key].append(semantic(query, args))
        demand(all(len(values) == 3 and len(set(values)) == 1 for values in semantics.values()), "Three-method query mismatch")
        counts["paired_query_tuples"] += len(semantics)
    demand(all(orders[key] == set(permutations(METHODS)) for key in cells), "Missing balanced order")
    demand(counts["paired_query_tuples"] == data["planned_query_tuples"], "Planned query denominator")
    return counts


def csv_write(path, rows):
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def describe(data, rows):
    by_id = {row["controller_id"]: row for row in rows}
    cells = {cell["id"]: cell for cell in data["cells"]}
    pair_rows, grouped = [], defaultdict(list)
    for run in data["runs"]:
        group = {method: by_id[expected_id(run, method)] for method in METHODS}
        costs = {method: row["full_algorithm_call_ns"] for method, row in group.items()}
        record = {"cell_id": run["cell_id"], "repetition": run["repetition"],
                  "method_order": ";".join(run["method_order"]), **{key + "_ns": v for key, v in costs.items()},
                  "planar_over_band": costs["planar_v2"] / costs["band_v2"],
                  "smt_over_band": costs["envelope_smt_v2"] / costs["band_v2"],
                  "fastest": min(costs, key=costs.get)}
        pair_rows.append(record)
        grouped[run["cell_id"]].append(record)
    summaries = []
    for cell in data["cells"]:
        samples = grouped[cell["id"]]
        demand(len(samples) == 6, "Replication count")
        fastest = Counter(row["fastest"] for row in samples)
        record = {"cell_id": cell["id"], "original_input_id": cell["original_input_id"],
                  "selection_reason": cell["selection_reason"], "history_pattern": cell["history_pattern"],
                  "queries_per_report": cell["queries_per_report"], "reports": len(cell["stages"]), "repetitions": 6}
        for method in METHODS:
            values = [row[method + "_ns"] for row in samples]
            median = statistics.median(values)
            record.update({method + "_median_ns": median, method + "_min_ns": min(values),
                           method + "_max_ns": max(values),
                           method + "_mad_ns": statistics.median(abs(value - median) for value in values),
                           method + "_fastest_count": fastest[method]})
        for metric in ("planar_over_band", "smt_over_band"):
            values = [row[metric] for row in samples]
            record.update({metric + "_median": statistics.median(values), metric + "_min": min(values),
                           metric + "_max": max(values)})
        summaries.append(record)
    return pair_rows, summaries


def main():
    if OUT.exists():
        raise FileExistsError("Preserve saved-record audits")
    data_path = ROOT / "protocols/fifo_stability_demand_inputs_v1.json"
    data = json.loads(data_path.read_text(encoding="ascii"))
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="ascii"))
    demand(manifest["status"] == "COMPLETE" and manifest["source_unchanged"], "Acquisition incomplete")
    for name, digest in manifest["record_sha256"].items():
        demand(sha(SOURCE / name) == digest, "Record hash changed")
    rows = [json.loads(line) for line in (SOURCE / "controller_results.jsonl").read_text(encoding="ascii").splitlines()]
    events = [json.loads(line) for line in (SOURCE / "raw_events.jsonl").read_text(encoding="ascii").splitlines()]
    inventory = json.loads((SOURCE / "expected_not_run_inventory.json").read_text(encoding="ascii"))
    counts = verify(data, rows, events, inventory)
    pairs, summaries = describe(data, rows)
    OUT.mkdir()
    csv_write(OUT / "all_paired_repetitions.csv", pairs)
    csv_write(OUT / "all_fixed_cells.csv", summaries)
    outcomes = Counter(row["fastest"] for row in pairs)
    receipt = {"status": "PASS_SEPARATE_FIXED_INSTANCE_RECORD_AUDIT", "date": "2026-10-13",
               "cells": 36, "paired_workflows": 216, "controllers": 648, "counts": dict(counts),
               "fastest_repetitions": dict(outcomes),
               "cells_with_changing_fastest_method": sum(max(row[m + "_fastest_count"] for m in METHODS) < 6 for row in summaries),
               "input_sha256": sha(data_path), "acquisition_manifest_sha256": sha(SOURCE / "manifest.json"),
               "auditor_sha256": sha(Path(__file__)),
               "tables_sha256": {name: sha(OUT / name) for name in ("all_paired_repetitions.csv", "all_fixed_cells.csv")},
               "actor_or_solver_calls": 0, "original_timings_pooled": False,
               "scope": "Within-instance descriptive dispersion, no population confidence intervals or p values"}
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
