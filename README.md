# Safety-pattern establishment prototype

This archive candidate contains the original `SafetyPattern_Prototype` implementation, its Case A/B inputs, and the November 10, 2026 cross-unit resource-independence experiments. The migrated pattern-library implementation is not used.

## Start here

- [Reproduction commands](README-reproduction.md): Case A/B, isolated and chain-independent scalability configurations, and the K=2 shared-CPU comparison.
- [Environment](environment.md): recorded experiment versions and the separately captured current dependency snapshot.
- [Architecture inputs and mapping](docs/model-inputs-and-mapping.md): YAML input, Python architecture objects, and SMT facts.
- [Pattern specifications](docs/pattern-specifications.md): where all six executable pattern definitions and failure mappings are stored.
- [Native models](models/README.md): Case A/B projects, the SRP example, embedded configuration and opening notes.
- [Figure index](figures/README.md): the total-time figure and six stage subfigures with their data fields.
- [Publication checklist](PUBLICATION_CHECKLIST.md): author decisions and material still to be inserted.

Verify the saved archive without running any experiment:

```powershell
python -B tools/verify_archive.py
```

## Contents

| Directory | Contents |
|---|---|
| `src/` | Ten original Python source files, copied without changes |
| `data/` | Nineteen original YAML architecture inputs, including inheritance dependencies |
| `tests/` | Four original test modules and a replacement, project-specific test guide |
| `results/cases/` | Saved layered Case A/B results |
| `results/scalability/` | 140 formal runs, 14 summary groups, configuration, warmups and Origin data workbook |
| `results/cross-unit-k2/` | 20 formal runs for the independent/shared-CPU comparison |
| `provenance/` | Source hashes, normalized historical launch record, logs and current environment snapshot |
| `models/` | `caseA.sml2`, `CaseB.sml2`, `SafetyPattern.sml2`, each with embedded configuration, and a model guide |
| `figures/` | Seven supplied PNGs: one total-time figure and six stage subfigures, plus a data-source index |

The model and figure directories are populated. Their supplied files are included in the source manifest and checksum list. `results/scalability/` uses an undated directory name; its experiment date remains November 10, 2026.

## Reported scalability results

Both configurations are `valid`. The isolated architecture has no cross-unit declarations. The chain-independent architecture adds resource-independence declarations between adjacent left IM instances, using the existing monitor/gate roles and PWR, CPU and CLK resources.

| K=64 | Isolated | Chain-independent |
|---|---:|---:|
| Pattern instances | 448 | 448 |
| Architectural objects | 2304 | 2304 |
| Verification obligations | 1792 | 1855 |
| Median total verification time (ms) | 162212.97509999998 | 168186.6122 |
| Median obligation-check time (ms) | 161026.4365 | 166964.95295 |

Each group used one warmup and ten formal runs. Formal records exclude warmups. The November 6 scalability outputs and old scalability pictures are not included.

## Executable input and modeling material

The prototype reads structured YAML descriptions, or generates the scalability architecture in memory. The supplied `.sml2` projects provide native modeling material; the Python prototype does not directly parse them or SysML v2. See `models/README.md` and `docs/model-inputs-and-mapping.md` for the project contents, YAML correspondence and opening checks.

## Archive preparation status

Original code, YAML and JSON/CSV experiment results retain their source bytes. Publication copies of auxiliary launch/log metadata use relative or anonymized paths. Three workbook source-path cells point to `results/scalability/`; numerical values, formulas and formatting were preserved. Basic identity metadata was removed from the pattern-description DOCX copy. Supplied native models and PNGs are unchanged. Transformations and first-packaging fingerprints are listed in `provenance/source-manifest.json`.

Assembly checks cover file hashes, source preservation, saved-result consistency, input inheritance, workbook values and launcher syntax. The experiments, original regression tests and a clean-environment installation were not rerun while preparing this candidate. Existing regression logs are historical records.

The original experiment records have no Git commit identifier. Their six recorded execution-source hashes are retained and checked. A future GitHub release tag will identify the publication snapshot, not an invented historical commit.

No license has been selected on the author's behalf, and this directory has not been uploaded. Complete `PUBLICATION_CHECKLIST.md` before public release.
