# Scalability figure files

The seven supplied PNGs form two paper figures: one total-time figure and one six-panel stage-time figure. The manuscript assembles panels (a)-(f); a separate combined stage PNG is not required.

All seven PNGs match the files referenced by the current Chinese manuscript, as checked during packaging on 2026-11-12. The PNG files are retained unchanged. No Origin project file (`.opj` or `.opju`) is supplied.

| PNG | Plot content | Summary median field |
|---|---|---|
| `scalability_total_time.png` | Total verification time | `total_verification_ms_median_ms` |
| `a-context-extraction.png` | (a) Context extraction | `context_extraction_ms_median_ms` |
| `b-obligation-generation.png` | (b) Obligation generation | `obligation_generation_ms_median_ms` |
| `c-context-check.png` | (c) Context check | `context_check_ms_median_ms` |
| `d-obligation-check.png` | (d) Obligation check | `obligation_check_ms_median_ms` |
| `e-combination-aggregation.png` | (e) Combination aggregation | `combination_aggregation_ms_median_ms` |
| `f-failure-expansion.png` | (f) Failure expansion | `failure_analysis_ms_median_ms` |

## Data sources

- [Formal result JSON](../results/scalability/scalability_results.json), [raw CSV](../results/scalability/scalability_results.csv) and [summary CSV](../results/scalability/scalability_summary.csv).
- [Origin data workbook](../results/scalability/origin_data_20261110.xlsx): `Total_Time`, `Stage_Time`, `Raw_Runs`, `Obligation_Data`, `Environment`.

The experiment date is November 10, 2026. K is 1, 2, 4, 8, 16, 32, 64. The two configurations are `isolated` and `chain_independent`, both with `variant=valid`; times are in milliseconds. Each group has ten formal runs, with warmups recorded separately.

The data tables supply the median, Q1, Q3 and the separate error magnitudes `median-Q1` and `Q3-median`. The workbook retains its experiment-date filename; the containing directory is simply `results/scalability/`.
