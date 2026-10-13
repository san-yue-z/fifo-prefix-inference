"""Export each scientific panel separately from the audited source records."""

import csv
import hashlib
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedFormatter, FixedLocator, NullLocator

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "writing/fifo_cor_submission_v4/artwork/individual_panels"
METHODS = ("band_v2", "planar_v2", "envelope_smt_v2")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def ticks(axis, values):
    axis.set_major_locator(FixedLocator(values))
    axis.set_major_formatter(FixedFormatter([str(x) for x in values]))
    axis.set_minor_locator(NullLocator())


def save(fig, name, record):
    fig.canvas.draw()
    fig.savefig(OUT / (name + ".pdf"))
    fig.savefig(OUT / (name + ".svg"))
    fig.savefig(OUT / (name + ".png"), dpi=1000)
    plt.close(fig)
    return {"name": name, "record": record, "width_mm": 90, "height_mm": 78,
            "sha256": {ext: sha(OUT / (name + "." + ext)) for ext in ("pdf", "svg", "png")}}


def main():
    if OUT.exists():
        raise FileExistsError("Preserve artwork versions")
    original_dir = ROOT / "artifacts/fifo_structural_comparison_audit_v2"
    followup_dir = ROOT / "artifacts/fifo_stability_demand_audit_v1"
    original = json.loads((original_dir / "receipt.json").read_text(encoding="ascii"))
    followup = json.loads((followup_dir / "receipt.json").read_text(encoding="ascii"))
    assert original["status"] == "PASS_SAVED_RECORD_AUDIT"
    assert followup["status"] == "PASS_SEPARATE_FIXED_INSTANCE_RECORD_AUDIT"
    for name, digest in original["table_sha256"].items():
        assert sha(original_dir / name) == digest
    for name, digest in followup["tables_sha256"].items():
        assert sha(followup_dir / name) == digest
    pairs = read_csv(original_dir / "all_input_costs.csv")
    cells = read_csv(followup_dir / "all_fixed_cells.csv")
    data = json.loads((ROOT / "protocols/fifo_stability_demand_inputs_v1.json").read_text(encoding="ascii"))
    records = json.loads((ROOT / "artifacts/fifo_structural_comparison_v2/controller_results.json").read_text(encoding="ascii"))
    OUT.mkdir(parents=True)
    mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Arial", "DejaVu Sans"],
                         "font.size": 7.5, "axes.labelsize": 7.5, "axes.titlesize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": 0.7, "legend.frameon": False,
                         "pdf.fonttype": 42, "svg.fonttype": "none", "savefig.facecolor": "white"})
    exports = []
    fig, axis = plt.subplots(figsize=(90 / 25.4, 78 / 25.4))
    fig.subplots_adjust(left=0.19, right=0.97, bottom=0.17, top=0.76)
    x = [int(row["band_v2_ns"]) / 1e6 for row in pairs]
    for key, label, color, marker in (("planar_v2_ns", "Planar v2", "#4477AA", "o"),
                                      ("envelope_smt_v2_ns", "EnvelopeSMT v2", "#AA6677", "x")):
        y = [int(row[key]) / 1e6 for row in pairs]
        assert len(x) == len(y) == 192 and min(x + y) > 0
        axis.scatter(x, y, s=12, color=color, marker=marker, alpha=0.65, linewidths=0.55, label=label)
    axis.plot([3, 70], [3, 70], "--", color="#555555", linewidth=0.7, zorder=0)
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlim(3, 70)
    axis.set_ylim(3, 600)
    ticks(axis.xaxis, [3, 10, 30, 60])
    ticks(axis.yaxis, [3, 10, 30, 100, 300, 600])
    axis.set_xlabel("Band v2 call cost (ms)")
    axis.set_ylabel("Comparator call cost (ms)")
    axis.set_title("Full algorithm-call cost", loc="left", pad=30)
    axis.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=2, borderaxespad=0,
                handletextpad=0.25, columnspacing=1)
    exports.append(save(fig, "Figure_1a", {"original_inputs": 192, "points": 384, "exclusions": 0}))

    fig, axis = plt.subplots(figsize=(90 / 25.4, 78 / 25.4))
    fig.subplots_adjust(left=0.31, right=0.97, bottom=0.17, top=0.76)
    accumulated = [0.0, 0.0, 0.0]
    sums = {}
    for phase, color in (("setup", "#AFB4BB"), ("update", "#398C87"), ("query", "#B86D5C")):
        values = [sum(value for row in records if row["method"] == method
                      for key, value in row["stage_cost_ns"].items() if key.startswith(phase)) / 1e9
                  for method in METHODS]
        sums[phase] = values
        axis.barh([2, 1, 0], values, left=accumulated, height=0.5, color=color, label=phase.capitalize())
        accumulated = [a + b for a, b in zip(accumulated, values)]
    for position, value in zip([2, 1, 0], accumulated):
        axis.text(value + 0.2, position, f"{value:.2f}", va="center", fontsize=7)
    axis.set_yticks([2, 1, 0], ["Band v2", "Planar v2", "EnvelopeSMT v2"])
    axis.set_xlim(0, 18.3)
    axis.set_xticks([0, 5, 10, 15])
    axis.set_ylim(-0.6, 2.6)
    axis.set_xlabel("Accumulated call time (s)")
    axis.set_title("Cost decomposition", loc="left", pad=30)
    axis.legend(loc="lower left", bbox_to_anchor=(-0.04, 1.02), ncol=3, borderaxespad=0,
                columnspacing=0.7, handletextpad=0.3, handlelength=1)
    exports.append(save(fig, "Figure_1b", {"controllers_per_method": 192, "stage_sums_seconds": sums, "exclusions": 0}))

    titles = ("S1 Planar reversal", "S2 Planar near tie", "S3 SMT reversal",
              "S4 SMT near tie", "S5 Band advantage", "S6 Larger support")
    colors = {"planar_over_band": "#4477AA", "smt_over_band": "#AA6677"}
    patterns = (("original", "original", "-", "o"), ("before_terminal", "prefix", "--", "s"))
    for index, selection in enumerate(data["selection"]):
        fig, axis = plt.subplots(figsize=(90 / 25.4, 78 / 25.4))
        fig.subplots_adjust(left=0.17, right=0.97, bottom=0.17, top=0.70)
        handles = []
        for metric, comparator in (("planar_over_band", "Planar"), ("smt_over_band", "EnvelopeSMT")):
            for pattern, label, style, marker in patterns:
                subset = sorted((row for row in cells if row["original_input_id"] == selection["input_id"]
                                 and row["history_pattern"] == pattern), key=lambda row: int(row["queries_per_report"]))
                assert len(subset) == 3
                x = [int(row["queries_per_report"]) for row in subset]
                med = [float(row[metric + "_median"]) for row in subset]
                low = [float(row[metric + "_min"]) for row in subset]
                high = [float(row[metric + "_max"]) for row in subset]
                assert x == [1, 4, 16] and all(0.5 <= a <= b <= c <= 50 for a, b, c in zip(low, med, high))
                displayed = [v * (0.95 if pattern == "original" else 1.05) for v in x]
                axis.errorbar(displayed, med, yerr=[[m - l for m, l in zip(med, low)], [h - m for h, m in zip(high, med)]],
                              linestyle=style, marker=marker, markersize=3, linewidth=0.85, elinewidth=0.65,
                              capsize=2, color=colors[metric], markerfacecolor=colors[metric] if pattern == "original" else "white")
                handles.append(Line2D([], [], color=colors[metric], marker=marker, linestyle=style,
                                      markersize=3, linewidth=0.85, markerfacecolor=colors[metric] if pattern == "original" else "white",
                                      label=comparator + ", " + label))
        axis.axhline(1, color="#555555", linestyle=":", linewidth=0.7, zorder=0)
        axis.set_xscale("log", base=2)
        axis.set_yscale("log")
        axis.set_xlim(0.7, 22)
        axis.set_ylim(0.5, 50)
        ticks(axis.xaxis, [1, 4, 16])
        ticks(axis.yaxis, [0.5, 1, 2, 5, 10, 20, 50])
        axis.set_xlabel("Queries per report")
        axis.set_ylabel("Comparator/Band call cost")
        axis.set_title(titles[index], loc="left", pad=8)
        fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.53, 0.985), ncol=2,
                   columnspacing=1.0, handletextpad=0.4, handlelength=1.5)
        exports.append(save(fig, "Figure_2" + "abcdef"[index],
                            {"input_id": selection["input_id"], "cells": 6, "repetitions_per_cell": 6,
                             "spread": "Full observed min/max of paired ratios", "exclusions": 0}))
    report = {"status": "INDIVIDUAL_VECTOR_ARTWORK_EXPORTED_PENDING_VISUAL_QA", "date": "2026-10-14",
              "panels": exports, "plotting_assistance": "OpenAI Codex, disclosed in figure captions",
              "backend": "Python/matplotlib", "raster_line_art_dpi": 1000,
              "source_sha256": {"original_cost_table": sha(original_dir / "all_input_costs.csv"),
                                "fixed_cell_table": sha(followup_dir / "all_fixed_cells.csv"), "plot_script": sha(Path(__file__))},
              "new_experiments": False, "multi_panel_alignment": "Not applicable to separate single-panel files; review composites retain previous alignment audit"}
    (OUT / "provenance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="ascii")
    print(json.dumps({"status": report["status"], "panels": len(exports), "excluded_records": 0}))


if __name__ == "__main__":
    main()
