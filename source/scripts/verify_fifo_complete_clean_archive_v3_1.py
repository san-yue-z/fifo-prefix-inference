"""Verify a clean package and reconstruct saved records without inference."""

from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module_from(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_record_line(raw):
    # Recorders hash the generated ASCII line before Windows text-mode
    # translation. Whole-file SHA still checks the original bytes unchanged.
    if raw.endswith(b"\r\n"):
        return raw[:-2] + b"\n"
    if raw.endswith(b"\n"):
        return raw
    raise ValueError("Unterminated transcript record")


def transcript_check():
    folder = ROOT / "artifacts/fifo_rational_pending_resolution_v3"
    receipt = json.loads((folder / "receipt.json").read_text(encoding="ascii"))
    path = folder / "slice_transcript.jsonl"
    assert sha(path) == receipt["slice_transcript_sha256"]
    state_hashes, counts = {}, Counter()
    with path.open("rb") as stream:
        for raw in stream:
            record = json.loads(raw)
            key = record["input_id"], record["history_index"]
            state_hashes.setdefault(key, hashlib.sha256()).update(canonical_record_line(raw))
            counts[key] += 1
            assert "specification_and_both_geometric_slices" in record
    observations = {(r["input_id"], r["history_index"]): r for r in receipt["observations"]}
    assert len(observations) == len(state_hashes) == 153 and set(observations) == set(state_hashes)
    for key, row in observations.items():
        assert state_hashes[key].hexdigest() == row["transcript_sha256"]
        assert counts[key] == row["checked_slices"] and row["all_three_complete_sets_equal"]
    assert sum(counts.values()) == 302369 == receipt["counts"]["critical_and_open_interval_slices"]
    return {"aggregate_hash_matches": True, "state_hashes_checked": 153, "slice_lines_checked": 302369,
            "per_state_hash_encoding": "Generated ASCII record plus LF, before Windows CRLF translation",
            "scope": "Saved transcript integrity and inventory, not rerun geometric inference"}


def main():
    output = ROOT / "CLEAN_VERIFICATION_COMPLETE_V3_1.json"
    if output.exists():
        raise FileExistsError("Preserve clean reconstruction results")
    manifest = json.loads((ROOT / "ARCHIVE_MANIFEST.json").read_text(encoding="ascii"))
    for entry in manifest["files"]:
        path = (ROOT / entry["path"]).resolve()
        path.relative_to(ROOT.resolve())
        assert path.is_file() and path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"], entry["path"]
    original = module_from("clean_factorial_audit", ROOT / "scripts/audit_fifo_structural_comparison_v2.py")
    original.OUTPUT = ROOT / "artifacts/fifo_factorial_cleancheck_v3_1"
    original.main()
    followup = module_from("clean_followup_audit", ROOT / "scripts/audit_fifo_stability_demand_v1.py")
    followup.OUT = ROOT / "artifacts/fifo_stability_cleancheck_v3_1"
    followup.main()
    tables = {}
    for label, actual, expected, names in (
        ("factorial", original.OUTPUT, ROOT / "artifacts/fifo_structural_comparison_audit_v2", ("all_input_costs.csv", "all_strata.csv")),
        ("followup", followup.OUT, ROOT / "artifacts/fifo_stability_demand_audit_v1", ("all_paired_repetitions.csv", "all_fixed_cells.csv")),
    ):
        for name in names:
            tables[label + ":" + name] = sha(actual / name) == sha(expected / name)
    assert all(tables.values())
    transcript = transcript_check()
    report = {"status": "PASS_COMPLETE_CLEAN_LOCAL_RECORD_RECONSTRUCTION", "date": "2026-10-14",
              "archive_files_checked": len(manifest["files"]), "tables_byte_identical": tables,
              "rational_transcript": transcript, "inference_actor_or_solver_calls": 0,
              "new_performance_samples": 0, "public_upload": False,
              "scope": "Package integrity and reproducible saved-record analysis, not scientific or journal clearance"}
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    print(json.dumps(report))


if __name__ == "__main__":
    main()


