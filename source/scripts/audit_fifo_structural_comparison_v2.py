"""Read-only record audit and descriptive comparison; imports no measured actor."""

from collections import Counter, defaultdict
import csv
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/fifo_structural_comparison_v2"
OUTPUT = ROOT / "artifacts/fifo_structural_comparison_audit_v2"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")
FACTORS = ("n", "m", "components", "precision_bits", "family")


def demand(condition, message):
    if not condition:
        raise AssertionError(message)


def load_json(path):
    return json.loads(path.read_text(encoding="ascii"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def planned(case):
    return ["setup"] + [f"{operation}_{index}" for index in range(len(case["stages"]))
                         for operation in ("update", "query")]


def semantic_result(query, now, local, deadline):
    demand(query["status"] == "EXACT", "Nonexact query")
    below, above = query["at_or_below"], query["above"]
    demand(type(below) is bool and type(above) is bool, "Nonboolean sides")
    if not below and not above:
        action, mode = "INCONSISTENT_MODEL", "EMPTY"
    elif not above:
        action = mode = "REMOTE"
    else:
        action = "LOCAL" if now + local <= deadline else "NO_CERTIFIED_ACTION"
        mode = "MIXED" if below else "LOCAL" if now + local <= deadline else "NO_FEASIBLE_MODE"
    demand(query["action"] == action and query["uniform_mode"] == mode, "Wrong action classification")
    demand(F(query["threshold"]) == min(now + local, deadline), "Wrong exact threshold")
    return action, mode, F(query["threshold"]), below, above


def verify_records(cases, results, events, inventory):
    demand(len(cases) == 192 and len({case["id"] for case in cases}) == 192, "Missing/duplicate inputs")
    expected_ids = [case["id"] + ":" + name for case in cases for name in case["method_order"]]
    demand(len(results) == 576 and [row["controller_id"] for row in results] == expected_ids, "Controller order or count")
    starts = [event["controller_id"] for event in events if event["event"] == "controller_start"]
    demand(starts == expected_ids, "Raw controller-start order")
    raw = defaultdict(list)
    for event in events:
        raw[event["controller_id"]].append(event)
    rows = {row["controller_id"]: row for row in results}
    inv = {row["controller_id"]: row for row in inventory}
    demand(len(inventory) == 576 and set(inv) == set(expected_ids), "Inventory completeness")
    counts = Counter()
    factorial_orders = defaultdict(set)
    previous_controller_end = -1
    for case in cases:
        factorial_orders[tuple(case["factors"][key] for key in FACTORS)].add(tuple(case["method_order"]))
        semantics = defaultdict(list)
        for name in case["method_order"]:
            cid = case["id"] + ":" + name
            row, sequence = rows[cid], raw[cid]
            demand(row["status"] == inv[cid]["status"] == "COMPLETE", "Incomplete controller")
            demand(not row["not_run_stages"] and not inv[cid]["not_run_stages"], "Unrecorded stages")
            demand(row["factors"] == case["factors"] and row["method_order"] == case["method_order"], "Factor correspondence")
            demand(sequence[0]["event"] == "controller_start" and sequence[-1]["event"] == "controller_end", "Missing endpoints")
            begin, end = sequence[0]["operational_start_ns"], sequence[-1]["operational_end_ns"]
            demand(begin >= previous_controller_end and end >= begin, "Overlapping controllers")
            previous_controller_end = end
            stages = [event for event in sequence if event["event"] == "stage"]
            demand([event["stage_id"] for event in stages] == planned(case), "Missing/out-of-order raw stages")
            demand(list(row["stage_cost_ns"]) == planned(case), "Result-stage order")
            last_end = begin
            for event in stages:
                elapsed = event["elapsed_ns"]
                demand(type(elapsed) is int and elapsed > 0, "Invalid timer sample")
                demand(begin <= last_end <= event["start_ns"] < event["end_ns"] <= end, "Invalid timer endpoints")
                demand(elapsed == event["end_ns"] - event["start_ns"] == row["stage_cost_ns"][event["stage_id"]], "Timer/result mismatch")
                demand(event["status"] == ("EXACT" if event["operation"] == "query" else "OK"), "Failed stage")
                last_end = event["end_ns"]
                counts["stages"] += 1
            total = sum(event["elapsed_ns"] for event in stages)
            demand(total == row["full_algorithm_call_ns"] == sequence[-1]["full_algorithm_call_ns"], "Full cost mismatch")
            demand(row["operational_elapsed_ns"] == end - begin >= total, "Operational interval mismatch")
            query_events = [event for event in stages if event["operation"] == "query"]
            demand(len(row["queries"]) == len(case["stages"]), "Missing query results")
            for index, (query, event, stage) in enumerate(zip(row["queries"], query_events, case["stages"])):
                demand(query["stage_id"] == f"query_{index}", "Query index mismatch")
                demand({key: value for key, value in query.items() if key != "stage_id"} == event["result"], "Raw semantic mismatch")
                now, work, local, deadline = map(F, stage["query"])
                demand(now > F(case["jobs"][-1][0]) and work > 0 and local > 0 and deadline >= 0, "Physical query contract")
                demand(all(F(past["report"][1]) <= now for past in case["stages"][:index + 1]), "Future as-of evidence")
                value = semantic_result(query, now, local, deadline)
                if stage.get("intentional_contradiction"):
                    demand(value[1] == "EMPTY", "Contradiction failed to empty set")
                semantics[index].append(value)
                counts[name + "_mode_" + value[1]] += 1
                counts[name + "_action_" + value[0]] += 1
                counts[name + "_deadline_binding_queries"] += deadline < now + local
            counts["controllers"] += 1
        for values in semantics.values():
            demand(len(values) == 3 and len(set(values)) == 1, "Three-method disagreement")
            counts["three_method_query_agreements"] += 1
        counts["eligible_inputs"] += 1
    demand(len(factorial_orders) == 32 and all(len(orders) == 6 for orders in factorial_orders.values()), "Order balance")
    demand(counts["stages"] == 24192 and counts["three_method_query_agreements"] == 3936, "Planned denominators")
    return counts


def gmean(values):
    return math.exp(statistics.mean(math.log(value) for value in values))


def comparison(cases, results):
    rows = {row["controller_id"]: row for row in results}
    table = []
    for case in cases:
        cost = {name: rows[case["id"] + ":" + name]["full_algorithm_call_ns"] for name in METHODS}
        table.append({"input_id": case["id"], **case["factors"],
                      **{name + "_ns": value for name, value in cost.items()},
                      "planar_over_band": cost["planar_v2"] / cost["band_v2"],
                      "smt_over_band": cost["envelope_smt_v2"] / cost["band_v2"],
                      "fastest": min(cost, key=cost.get)})
    strata = defaultdict(list)
    for row in table:
        strata[tuple(row[key] for key in FACTORS)].append(row)
    stratified = []
    for key, values in sorted(strata.items()):
        record = {**dict(zip(FACTORS, key)), "paired_inputs": len(values)}
        for metric in ("planar_over_band", "smt_over_band"):
            ratios = [row[metric] for row in values]
            record.update({metric + "_gmean": gmean(ratios), metric + "_min": min(ratios),
                           metric + "_max": max(ratios), metric + "_band_faster": sum(value > 1 for value in ratios)})
        for name in METHODS:
            record[name + "_median_ms"] = statistics.median(row[name + "_ns"] for row in values) / 1e6
        stratified.append(record)
    summary = {"fastest_counts": dict(Counter(row["fastest"] for row in table)),
               "stratified_cells": len(stratified), "inputs_per_cell": 6}
    for metric in ("planar_over_band", "smt_over_band"):
        values = [row[metric] for row in table]
        summary[metric] = {"min": min(values), "max": max(values), "gmean_descriptive": gmean(values),
                           "band_faster_inputs": sum(value > 1 for value in values),
                           "min_input": min(table, key=lambda row: row[metric])["input_id"],
                           "max_input": max(table, key=lambda row: row[metric])["input_id"]}
    for name in METHODS:
        method_rows = [row for row in results if row["method"] == name]
        totals = {operation: sum(cost for row in method_rows for key, cost in row["stage_cost_ns"].items()
                                if key.startswith(operation)) / 1e9 for operation in ("setup", "update", "query")}
        summary[name] = {"aggregate_algorithm_seconds": sum(totals.values()), "stage_seconds": totals,
                         "full_cost_min_ms": min(row["full_algorithm_call_ns"] for row in method_rows) / 1e6,
                         "full_cost_max_ms": max(row["full_algorithm_call_ns"] for row in method_rows) / 1e6,
                         "stored_diagnostic_maxima": {key: max(diag.get(key, 0) for row in method_rows for diag in row["diagnostics"])
                                                      for key in set().union(*(diag.keys() for row in method_rows for diag in row["diagnostics"]))
                                                      if key != "after"}}
    return table, stratified, summary


def write_csv(path, rows):
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    if OUTPUT.exists():
        raise FileExistsError("Preserve this audit outcome")
    OUTPUT.mkdir()
    manifest = load_json(SOURCE / "manifest.json")
    for name, expected in manifest["source_sha256"].items():
        demand(sha(ROOT / name) == expected, "Changed acquired source: " + name)
    for name, expected in manifest["record_sha256"].items():
        demand(sha(SOURCE / name) == expected, "Changed raw recording: " + name)
    cases = load_json(ROOT / "protocols/fifo_structural_inputs_v2.json")["inputs"]
    results = load_json(SOURCE / "controller_results.json")
    events = [json.loads(line) for line in (SOURCE / "raw_events.jsonl").read_text(encoding="ascii").splitlines()]
    inventory = load_json(SOURCE / "expected_not_run_inventory.json")
    counts = verify_records(cases, results, events, inventory)
    table, strata, summary = comparison(cases, results)
    write_csv(OUTPUT / "all_input_costs.csv", table)
    write_csv(OUTPUT / "all_strata.csv", strata)
    receipt = {"status": "PASS_SAVED_RECORD_AUDIT", "counts": dict(counts), "descriptive_summary": summary,
               "raw_manifest_sha256": sha(SOURCE / "manifest.json"),
               "auditor_sha256": sha(Path(__file__).resolve()),
               "table_sha256": {name: sha(OUTPUT / name) for name in ("all_input_costs.csv", "all_strata.csv")},
               "actor_calls": 0, "new_timing_samples": 0,
               "boundary": "Record correspondence, exact classification and input-specific descriptive costs; not full geometry, runtime proof, physical validation or novelty"}
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(json.dumps({"status": receipt["status"], "counts": dict(counts), "summary": summary}))


if __name__ == "__main__":
    main()
