"""Lock a disclosed outcome-stratified follow-up without inference calls."""

from collections import Counter
from fractions import Fraction as F
import hashlib
from itertools import permutations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "protocols/fifo_stability_demand_inputs_v1.json"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate():
    original = ROOT / "protocols/fifo_structural_inputs_v2.json"
    results = ROOT / "artifacts/fifo_structural_comparison_v2/controller_results.json"
    inputs = json.loads(original.read_text(encoding="ascii"))["inputs"]
    rows = json.loads(results.read_text(encoding="ascii"))
    by_id = {case["id"]: case for case in inputs}
    costs, geometry = {}, {}
    for row in rows:
        costs.setdefault(row["input_id"], {})[row["method"]] = row["full_algorithm_call_ns"]
        if row["method"] == "band_v2":
            geometry[row["input_id"]] = max(d["bands"] + d["points"] for d in row["diagnostics"])
    assert len(costs) == 192 and all(set(v) == set(METHODS) for v in costs.values())
    ratios = {key: (F(v["planar_v2"], v["band_v2"]), F(v["envelope_smt_v2"], v["band_v2"]))
              for key, v in costs.items()}
    selections = []
    rules = (
        ("strongest_planar_reversal", lambda key: ratios[key][0]),
        ("nearest_planar_tie", lambda key: abs(ratios[key][0] - 1)),
        ("strongest_smt_reversal", lambda key: ratios[key][1]),
        ("nearest_smt_tie", lambda key: abs(ratios[key][1] - 1)),
        ("largest_joint_band_advantage", lambda key: -min(ratios[key])),
        ("largest_observed_support", lambda key: -geometry[key]),
    )
    selected = set()
    for reason, key_function in rules:
        key = min((key for key in by_id if key not in selected), key=lambda key: (key_function(key), key))
        selected.add(key)
        selections.append({"input_id": key, "selection_reason": reason,
                           "original_planar_over_band": str(ratios[key][0]),
                           "original_smt_over_band": str(ratios[key][1]),
                           "original_max_bands_plus_points": geometry[key]})
    cells = []
    for selection in selections:
        base = by_id[selection["input_id"]]
        for pattern in ("original", "before_terminal"):
            stages = base["stages"]
            if pattern == "before_terminal":
                terminal = next(i for i, stage in enumerate(stages) if stage["report"][0] == len(base["jobs"]))
                stages = stages[:terminal]
            assert stages
            for demand in (1, 4, 16):
                new_stages = []
                for stage in stages:
                    queries = [stage["query"]]
                    now, work, local, deadline = map(F, stage["query"])
                    for k in range(1, demand):
                        work = (F(1, 2), F(3, 4), F(5, 4), F(3, 2))[(k - 1) % 4]
                        queries.append(list(map(str, (now, work, local + F(k % 3, 8), deadline + F(k % 5, 16)))))
                    for query in queries:
                        qnow, qwork, qlocal, qdeadline = map(F, query)
                        assert qnow > F(base["jobs"][-1][0]) and qnow >= F(stage["report"][1])
                        assert qwork > 0 and qlocal > 0 and qdeadline >= 0
                    new_stages.append({"report": stage["report"], "queries": queries})
                cells.append({"id": base["id"] + f":{pattern}:q{demand}",
                              "original_input_id": base["id"], "factors": base["factors"],
                              "selection_reason": selection["selection_reason"],
                              "history_pattern": pattern, "queries_per_report": demand,
                              "jobs": base["jobs"], "cells": base["cells"], "stages": new_stages})
    orders = list(permutations(METHODS))
    runs = []
    for repetition in range(6):
        rotated = cells[repetition * 5:] + cells[:repetition * 5]
        for cell in rotated:
            runs.append({"cell_id": cell["id"], "repetition": repetition,
                         "method_order": list(orders[repetition])})
    assert len(cells) == 36 and len(runs) == 216
    return {"schema": "fifo_stability_demand_inputs_v1", "fixed_date": "2026-10-13",
            "original_input_sha256": sha(original), "original_results_sha256": sha(results),
            "protocol_sha256": sha(ROOT / "protocols/fifo_measurement_stability_demand_v1.md"),
            "selection": selections, "cells": cells, "runs": runs,
            "planned_controllers": 648,
            "planned_query_tuples": sum(sum(len(stage["queries"]) for stage in cell["stages"])
                                         for cell in cells) * 6,
            "scope": "Outcome-selected fixed-instance measurement study, no population inference"}


def main():
    if OUTPUT.exists():
        raise FileExistsError("Never overwrite locked inputs")
    data = generate()
    OUTPUT.write_text(json.dumps(data, indent=2) + "\n", encoding="ascii")
    print(json.dumps({"status": "LOCKED_BEFORE_ACQUISITION", "sha256": sha(OUTPUT),
                      "cells": len(data["cells"]), "paired_workflows": len(data["runs"]),
                      "controllers": data["planned_controllers"], "query_tuples": data["planned_query_tuples"],
                      "selection": data["selection"], "actor_calls": 0}))


if __name__ == "__main__":
    main()
