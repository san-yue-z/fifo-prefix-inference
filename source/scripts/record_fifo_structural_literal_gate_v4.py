"""Bound and preserve the large-history verification process, without timing actors."""

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
OUT = ROOT / "artifacts/fifo_structural_literal_gate_v4"
FILES = (
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
    "protocols/fifo_structural_inputs_v2.json",
    "protocols/fifo_structural_literal_gate_v4.md",
    "tests/test_shared_scale_planar_reference_v1.py",
    "tests/test_shared_scale_planar_continuous_set_v2.py",
    "tests/test_shared_scale_comparable_methods_v3.py",
    "tests/test_fifo_structural_literal_gate_v4.py",
    "scripts/record_fifo_structural_literal_gate_v4.py",
    "artifacts/fifo_structural_comparison_v2/controller_results.json",
)


def fingerprints():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def worker():
    spec = importlib.util.spec_from_file_location("large_literal_gate", ROOT / FILES[-3])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
    (OUT / "unittest_output.txt").write_text(stream.getvalue(), encoding="utf-8")
    receipt = {"status": "PASS_SELECTED_FULL_SETS_AND_QUERIES" if result.wasSuccessful() else "FAIL",
               "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "counts": dict(module.CHECKS), "observations": module.OBSERVATIONS,
               "python": sys.version, "z3_native_version": module.z3.get_version_string(),
               "selection": "First fixed block, all 32 factorial cells, post-acquisition verification",
               "oracle": "Literal nested FIFO with generator weights eliminated for the two fixed priors",
               "timeout_ms_per_oracle_call": 1000, "performance_timing_samples": 0,
               "previous_cost_acquisitions_rerun": False,
               "boundary": "Finite selected-case full-set and query equality; not general verification or performance confirmation"}
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    if not result.wasSuccessful():
        raise SystemExit(1)


def main():
    if sys.argv[1:] == ["--worker"]:
        worker()
        return
    if OUT.exists():
        raise FileExistsError("Preserve the original correctness outcome")
    before = fingerprints()
    OUT.mkdir()
    (OUT / "preflight.json").write_text(json.dumps({"source_sha256": before}, indent=2), encoding="ascii")
    start = time.perf_counter()
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker"], cwd=ROOT)
    timed_out = False
    try:
        code = child.wait(timeout=900)
    except subprocess.TimeoutExpired:
        timed_out = True
        child.kill()
        code = child.wait()
    after = fingerprints()
    receipt_path = OUT / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="ascii")) if receipt_path.exists() else {"status": "INCOMPLETE"}
    receipt.update({"source_sha256": before, "sources_unchanged": before == after, "child_exit_code": code,
                    "hard_timeout_reached": timed_out, "operational_validation_seconds": time.perf_counter() - start})
    if before != after or timed_out or code:
        receipt["status"] = "FAIL_OR_INCOMPLETE"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(json.dumps({key: receipt.get(key) for key in ("status", "counts", "failures", "errors", "sources_unchanged",
                                                       "hard_timeout_reached", "operational_validation_seconds")}))
    if receipt["status"] != "PASS_SELECTED_FULL_SETS_AND_QUERIES":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
