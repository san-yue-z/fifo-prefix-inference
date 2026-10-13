# Result Data Dictionary

This file documents all four recorded result CSV tables. It does not grant a licence or assert public deposition.

CPU costs are nanoseconds (ns), except columns explicitly ending in _ms. One millisecond is 1,000,000 ns. Complete cost includes setup, every report update and every full query; recording/import/diagnostic overhead is excluded. Operational acquisition time is separately recorded and must not be substituted for these costs.

The synthetic FIFO clock uses consistent abstract model-time units, not the CPU timer's nanoseconds. Work p has nominal work units; theta scales work into model time; delta, now, local duration, deadlines and report times use model time. Exact inputs and certificate thresholds are rational strings; do not silently round them before inference.

Original blocks are distinct deterministic inputs, not timing repetitions. Follow-up repetitions are six acquisitions of each fixed workflow. The follow-up input selection deliberately uses original outcomes; do not pool the two studies. Min/max whiskers are observed measurement ranges, not confidence intervals. MAD is unscaled median absolute deviation. No empty/missing CSV field is used as a failure imputation.

## all_input_costs.csv

Original fixed-input complete costs; Figure 1a; rows: 192.

Source: `artifacts/fifo_structural_comparison_audit_v2/all_input_costs.csv`

| Column | Unit | Definition |
|---|---|---|
| input_id | identifier | One original locked synthetic input. |
| block | identifier | Deterministic input-generation block, not an identical-input timing repetition. |
| n | jobs | Immutable FIFO ledger length. |
| m | reports | Base planned report count; contradictory histories append one additional report. |
| components | count | Number of original prior components; variants also change prior geometry and information. |
| precision_bits | condition label | Submission-precision design label (8 or 40), not a bound on every stored integer's bit length. |
| family | category | Original consistent or intentionally contradictory history family. |
| band_v2_ns | ns | Sum of setup, every update and every complete query for band_v2. |
| planar_v2_ns | ns | Sum of setup, every update and every complete query for planar_v2. |
| envelope_smt_v2_ns | ns | Sum of setup, every update and every complete query for envelope_smt_v2. |
| planar_over_band | dimensionless | Planar v2 complete cost divided by Band v2 complete cost, paired on the same input/workflow. |
| smt_over_band | dimensionless | EnvelopeSMT v2 complete cost divided by Band v2 complete cost, paired on the same input/workflow. |
| fastest | method identifier | Method with the minimum recorded complete algorithm-call cost for this paired observation. |

## all_strata.csv

Original factor strata; Table B.1; rows: 32.

Source: `artifacts/fifo_structural_comparison_audit_v2/all_strata.csv`

| Column | Unit | Definition |
|---|---|---|
| n | jobs | Immutable FIFO ledger length. |
| m | reports | Base planned report count; contradictory histories append one additional report. |
| components | count | Number of original prior components; variants also change prior geometry and information. |
| precision_bits | condition label | Submission-precision design label (8 or 40), not a bound on every stored integer's bit length. |
| family | category | Original consistent or intentionally contradictory history family. |
| paired_inputs | count | Number of distinct inputs in this original factor stratum. |
| planar_over_band_gmean | dimensionless | descriptive geometric mean of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| planar_over_band_min | dimensionless | min of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| planar_over_band_max | dimensionless | max of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| planar_over_band_band_faster | count | Distinct stratum inputs for which the paired Planar v2/Band ratio exceeds one. |
| smt_over_band_gmean | dimensionless | descriptive geometric mean of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_min | dimensionless | min of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_max | dimensionless | max of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_band_faster | count | Distinct stratum inputs for which the paired EnvelopeSMT v2/Band ratio exceeds one. |
| band_v2_median_ms | ms | Median complete cost across six distinct inputs in the stratum for band_v2. |
| planar_v2_median_ms | ms | Median complete cost across six distinct inputs in the stratum for planar_v2. |
| envelope_smt_v2_median_ms | ms | Median complete cost across six distinct inputs in the stratum for envelope_smt_v2. |

## all_paired_repetitions.csv

All paired fixed-workflow repetitions; Figure 2 source observations; rows: 216.

Source: `artifacts/fifo_stability_demand_audit_v1/all_paired_repetitions.csv`

| Column | Unit | Definition |
|---|---|---|
| cell_id | identifier | Fixed original-input/history-pattern/query-demand combination. |
| repetition | index | Zero-based identical-workflow repetition index (0 through 5). |
| method_order | ordered category list | Acquisition order of all three methods, separated by semicolons. |
| band_v2_ns | ns | Sum of setup, every update and every complete query for band_v2. |
| planar_v2_ns | ns | Sum of setup, every update and every complete query for planar_v2. |
| envelope_smt_v2_ns | ns | Sum of setup, every update and every complete query for envelope_smt_v2. |
| planar_over_band | dimensionless | Planar v2 complete cost divided by Band v2 complete cost, paired on the same input/workflow. |
| smt_over_band | dimensionless | EnvelopeSMT v2 complete cost divided by Band v2 complete cost, paired on the same input/workflow. |
| fastest | method identifier | Method with the minimum recorded complete algorithm-call cost for this paired observation. |

## all_fixed_cells.csv

Fixed-workflow summaries; Figure 2 and Table D.1; rows: 36.

Source: `artifacts/fifo_stability_demand_audit_v1/all_fixed_cells.csv`

| Column | Unit | Definition |
|---|---|---|
| cell_id | identifier | Fixed original-input/history-pattern/query-demand combination. |
| original_input_id | identifier | Original input from which the follow-up workflow was constructed. |
| selection_reason | category | Outcome-based reason for choosing this input before the new follow-up acquisition. |
| history_pattern | category | original or before_terminal; the latter ends before the first full-completion fact. |
| queries_per_report | count | Number of hypothetical, nondispatching queries after each retained report (1, 4 or 16). |
| reports | count | Actual retained reports in this fixed workflow. |
| repetitions | count | Identical-workflow acquisitions contributing to this summary (six). |
| band_v2_median_ns | ns | median of six fixed-workflow complete costs for band_v2. |
| band_v2_min_ns | ns | min of six fixed-workflow complete costs for band_v2. |
| band_v2_max_ns | ns | max of six fixed-workflow complete costs for band_v2. |
| band_v2_mad_ns | ns | unscaled median absolute deviation about the median of six fixed-workflow complete costs for band_v2. |
| band_v2_fastest_count | count | Repetitions in which band_v2 has minimum complete cost, out of six. |
| planar_v2_median_ns | ns | median of six fixed-workflow complete costs for planar_v2. |
| planar_v2_min_ns | ns | min of six fixed-workflow complete costs for planar_v2. |
| planar_v2_max_ns | ns | max of six fixed-workflow complete costs for planar_v2. |
| planar_v2_mad_ns | ns | unscaled median absolute deviation about the median of six fixed-workflow complete costs for planar_v2. |
| planar_v2_fastest_count | count | Repetitions in which planar_v2 has minimum complete cost, out of six. |
| envelope_smt_v2_median_ns | ns | median of six fixed-workflow complete costs for envelope_smt_v2. |
| envelope_smt_v2_min_ns | ns | min of six fixed-workflow complete costs for envelope_smt_v2. |
| envelope_smt_v2_max_ns | ns | max of six fixed-workflow complete costs for envelope_smt_v2. |
| envelope_smt_v2_mad_ns | ns | unscaled median absolute deviation about the median of six fixed-workflow complete costs for envelope_smt_v2. |
| envelope_smt_v2_fastest_count | count | Repetitions in which envelope_smt_v2 has minimum complete cost, out of six. |
| planar_over_band_median | dimensionless | median of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| planar_over_band_min | dimensionless | min of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| planar_over_band_max | dimensionless | max of paired Planar v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_median | dimensionless | median of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_min | dimensionless | min of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |
| smt_over_band_max | dimensionless | max of paired EnvelopeSMT v2/Band ratios. A median ratio is not a ratio of medians. |

## Raw and Exact-Check Records

raw_events.jsonl records controller start/end and stage timer endpoints. elapsed_ns equals end_ns minus start_ns; stage_cost_ns holds the matching per-stage costs. Integer timer readings are monotonic-counter values, not dates or physical arrival timestamps.

The complete rational slice transcript contains one JSON object per checked critical point or intervening interval witness. specification_and_both_geometric_slices is the normalized shared interval-union result. Each interval is [lower delta, upper delta, lower closed, upper closed]; true means the corresponding endpoint is included. These closure flags are the opposite convention to the strict flags in the geometric representation. Empty lists represent no feasible slice. These are exact symbolic checks for the stated selected inputs, not statistical samples.

Per-state transcript hashing uses the generated ASCII record with an LF terminator before Windows text-mode CRLF translation. The whole-file digest checks original bytes. The supplied newline tests cover this convention without editing the transcript.
