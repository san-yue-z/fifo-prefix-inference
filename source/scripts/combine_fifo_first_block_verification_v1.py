"""Deduplicate complete input histories across two different finite proof gates."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/fifo_first_block_combined_verification_v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="ascii"))


def main():
    if OUT.exists():
        raise FileExistsError("Preserve the first combined coverage record")
    old_path = ROOT / "artifacts/fifo_structural_unpruned_gate_v6/receipt.json"
    new_path = ROOT / "artifacts/fifo_rational_pending_resolution_v3/receipt.json"
    old, new = read(old_path), read(new_path)
    if old["status"] != "FAIL_OR_INCOMPLETE" or new["status"] != "PASS_ALL_SIX_PENDING_RATIONAL_HISTORIES":
        raise AssertionError("Unexpected source gate status")
    for receipt in (old, new):
        if not receipt["sources_unchanged"]:
            raise AssertionError("Source changed during a gate")
        for name, expected in receipt["source_sha256"].items():
            if sha(ROOT / name) != expected:
                raise AssertionError("Current gate dependency differs: " + name)
    transcript_path = ROOT / "artifacts/fifo_rational_pending_resolution_v3/slice_transcript.jsonl"
    if sha(transcript_path) != new["slice_transcript_sha256"]:
        raise AssertionError("Changed rational transcript")
    inputs = read(ROOT / "protocols/fifo_structural_inputs_v2.json")["inputs"]
    selected = {case["id"]: case for case in inputs if case["factors"]["block"] == 2026101301}
    old_complete = {row["input_id"]: row for row in old["observations"]}
    new_ids = set(new["selected_input_ids"])
    if len(old_complete) != 26 or len(new_ids) != 6 or set(old_complete) & new_ids:
        raise AssertionError("Duplicated or incomplete complete-input inventory")
    if set(old_complete) | new_ids != set(selected):
        raise AssertionError("Not all first-block inputs are covered")
    records = []
    for input_id, case in selected.items():
        expected_states, expected_queries = len(case["stages"]) + 1, len(case["stages"])
        if input_id in old_complete:
            row = old_complete[input_id]
            if row["history_states"] != expected_states or row["query_tuples"] != expected_queries:
                raise AssertionError("Old complete input has missing coverage")
            gate = "unpruned_QF_LRA_v6_complete_input"
        else:
            rows = [row for row in new["observations"] if row["input_id"] == input_id]
            if sorted(row["history_index"] for row in rows) != list(range(expected_states)):
                raise AssertionError("Missing rational state")
            if not all(row["all_three_complete_sets_equal"] for row in rows):
                raise AssertionError("Nonmatching rational state")
            gate = "rational_arrangement_v3_complete_input"
        records.append({"input_id": input_id, "complete_history_states": expected_states,
                        "complete_query_tuples": expected_queries, "gate": gate})
    states = sum(row["complete_history_states"] for row in records)
    queries = sum(row["complete_query_tuples"] for row in records)
    if (states, queries) != (688, 656):
        raise AssertionError("Wrong deduplicated coverage")
    OUT.mkdir()
    receipt = {"status": "PASS_FINITE_FIRST_BLOCK_COVERAGE_BY_TWO_ORACLES", "complete_inputs": 32,
               "complete_history_states": states, "query_tuples": queries, "observations": records,
               "complete_old_gate_inputs": 26, "complete_rational_gate_inputs": 6,
               "old_gate_partial_states_not_double_counted": True,
               "old_gate_status_unchanged": old["status"], "new_gate_status": new["status"],
               "source_receipts_sha256": {"unpruned_v6": sha(old_path), "rational_v3": sha(new_path)},
               "combiner_sha256": sha(Path(__file__).resolve()), "actor_calls": 0, "solver_calls": 0,
               "performance_timing_samples": 0,
               "boundary": "All states/queries for the 32 fixed first-block inputs; not all 192 performance inputs, general verification or novelty clearance"}
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(json.dumps({key: receipt[key] for key in ("status", "complete_inputs", "complete_history_states", "query_tuples",
                                                    "complete_old_gate_inputs", "complete_rational_gate_inputs")}))


if __name__ == "__main__":
    main()
