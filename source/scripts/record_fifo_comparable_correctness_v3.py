"""Record this new gate once, including errors and unchanged-source checks."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/fifo_comparable_correctness_v3"
FILES = (
    "src/chunk_scheduling/shared_scale_comparable_methods_v2.py",
    "src/chunk_scheduling/shared_scale_planar_reference_v1.py",
    "src/chunk_scheduling/shared_scale_band_posterior_v1.py",
    "src/chunk_scheduling/shared_scale_envelope_smt_v1.py",
    "src/chunk_scheduling/shared_scale_smt_reference_v1.py",
    "protocols/fifo_planar_correctness_controls_v1.json",
    "protocols/fifo_comparable_methods_v2_design.md",
    "protocols/fifo_comparable_correctness_gate_v3.md",
    "tests/test_shared_scale_planar_reference_v1.py",
    "tests/test_shared_scale_planar_continuous_set_v2.py",
    "tests/test_shared_scale_comparable_methods_v3.py",
    "scripts/record_fifo_comparable_correctness_v3.py",
)


def fingerprints():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def main():
    if OUT.exists():
        raise FileExistsError("Preserve this gate's original outcome")
    OUT.mkdir()
    before = fingerprints()
    (OUT / "preflight.json").write_text(json.dumps({"sources": before}, indent=2), encoding="ascii")
    spec = importlib.util.spec_from_file_location("comparable_controls", ROOT / FILES[-2])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(module))
    after = fingerprints()
    (OUT / "unittest_output.txt").write_text(stream.getvalue(), encoding="utf-8")
    receipt = {
        "status": "PASS_FIXED_SET_AND_QUERY_PARITY" if result.wasSuccessful() and before == after else "FAIL",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "source_sha256": before, "sources_unchanged": before == after,
        "python": sys.version, "z3_native_version": module.z3.get_version_string(),
        "counts": dict(module.CHECKS), "observations": module.OBSERVATIONS,
        "oracle": "Literal nested FIFO with existentially eliminated convex-combination prior",
        "timeout_ms": 1000, "performance_timing_samples": 0,
        "previous_cost_acquisitions_rerun": False,
        "boundary": "Finite fixed-case full-set and query parity, not a general proof or publication gate",
    }
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="ascii")
    print(json.dumps({key: receipt[key] for key in ("status", "tests_run", "failures", "errors", "counts")}))
    if receipt["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
