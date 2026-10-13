"""Negative controls for the saved-record auditor, not actor correctness tests."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit", ROOT / "scripts/audit_fifo_structural_comparison_v2.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
SOURCE = ROOT / "artifacts/fifo_structural_comparison_v2"
CASES = audit.load_json(ROOT / "protocols/fifo_structural_inputs_v2.json")["inputs"]
RESULTS = audit.load_json(SOURCE / "controller_results.json")
EVENTS = [json.loads(line) for line in (SOURCE / "raw_events.jsonl").read_text(encoding="ascii").splitlines()]
INVENTORY = audit.load_json(SOURCE / "expected_not_run_inventory.json")


class RecordAuditControls(unittest.TestCase):
    def test_original_record_passes(self):
        counts = audit.verify_records(CASES, RESULTS, EVENTS, INVENTORY)
        self.assertEqual(counts["controllers"], 576)

    def test_wrong_elapsed_rejected(self):
        events = deepcopy(EVENTS)
        next(event for event in events if event["event"] == "stage")["elapsed_ns"] += 1
        with self.assertRaises(AssertionError):
            audit.verify_records(CASES, RESULTS, events, INVENTORY)

    def test_wrong_exact_threshold_rejected(self):
        results = deepcopy(RESULTS)
        results[0]["queries"][0]["threshold"] = "0"
        with self.assertRaises(AssertionError):
            audit.verify_records(CASES, results, EVENTS, INVENTORY)

    def test_missing_controller_rejected(self):
        with self.assertRaises(AssertionError):
            audit.verify_records(CASES, RESULTS[:-1], EVENTS, INVENTORY)

    def test_not_run_inventory_rejected(self):
        inventory = deepcopy(INVENTORY)
        inventory[0]["not_run_stages"] = ["setup"]
        with self.assertRaises(AssertionError):
            audit.verify_records(CASES, RESULTS, EVENTS, inventory)

    def test_wrong_order_rejected(self):
        results = deepcopy(RESULTS)
        results[0], results[1] = results[1], results[0]
        with self.assertRaises(AssertionError):
            audit.verify_records(CASES, results, EVENTS, INVENTORY)


if __name__ == "__main__":
    unittest.main()
