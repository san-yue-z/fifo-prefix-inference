"""Negative controls for the saved-record follow-up auditor, no actor calls."""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_fifo_stability_demand_v1 import verify


@contextmanager
def changed(mapping, key, value):
    old = mapping[key]
    mapping[key] = value
    try:
        yield
    finally:
        mapping[key] = old


class AuditControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = ROOT / "artifacts/fifo_stability_demand_v1"
        cls.data = json.loads((ROOT / "protocols/fifo_stability_demand_inputs_v1.json").read_text(encoding="ascii"))
        cls.rows = [json.loads(line) for line in (folder / "controller_results.jsonl").read_text(encoding="ascii").splitlines()]
        cls.events = [json.loads(line) for line in (folder / "raw_events.jsonl").read_text(encoding="ascii").splitlines()]
        cls.inventory = json.loads((folder / "expected_not_run_inventory.json").read_text(encoding="ascii"))
        cls.stage = next(e for e in cls.events if e["event"] == "stage")
        cls.query = next(e for e in cls.events if e.get("operation") == "query")

    def rejects(self):
        with self.assertRaises(AssertionError):
            verify(self.data, self.rows, self.events, self.inventory)

    def test_reversed_timer(self):
        with changed(self.stage, "end_ns", self.stage["start_ns"]):
            self.rejects()

    def test_cost_not_timer_difference(self):
        with changed(self.stage, "elapsed_ns", self.stage["elapsed_ns"] + 1):
            self.rejects()

    def test_wrong_complete_cost(self):
        with changed(self.rows[0], "full_algorithm_call_ns", self.rows[0]["full_algorithm_call_ns"] + 1):
            self.rejects()

    def test_wrong_threshold_even_if_raw_matches(self):
        result = self.query["result"]
        query = self.rows[0]["queries"][0]
        with changed(result, "threshold", "0"), changed(query, "threshold", "0"):
            self.rejects()

    def test_unrun_stage_not_ignored(self):
        with changed(self.inventory[0], "not_run_stages", ["setup"]):
            self.rejects()

    def test_method_order_not_ignored(self):
        with changed(self.rows[0], "method_order", list(reversed(self.rows[0]["method_order"]))):
            self.rejects()

    def test_complete_saved_record(self):
        counts = verify(self.data, self.rows, self.events, self.inventory)
        self.assertEqual(counts["paired_query_tuples"], 29610)


if __name__ == "__main__":
    unittest.main()
