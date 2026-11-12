# Reproducing the saved experiments

Run the commands from the extracted `SafetyPattern_Prototype` root. PowerShell is used below. Archived evidence is in `results/`; new executions write only to a fresh directory under `reproduced/` unless an explicit new output directory is supplied.

## 1. Prepare the environment

Install CPython 3.12.14 and create a virtual environment with that exact interpreter. Replace the executable below with the location of that installation:

```powershell
$Python31214 = 'C:\path\to\Python31214\python.exe'
& $Python31214 -B -c "import sys; assert sys.version_info[:3] == (3,12,14), sys.version; print(sys.version)"
& $Python31214 -m venv .venv
$python = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-lock.txt
& $python -m pip check
& $python -B -c "import sys,z3; print(sys.version); print(z3.get_full_version())"
```

The lock file describes the selected current reproduction dependencies, not a recovered November 10 full freeze. See `environment.md`. A fresh-install acceptance run remains to be performed by the author; package preparation did not install packages or rerun experiments.

## 2. Validate the saved results first

```powershell
& $python -B tools/verify_archive.py
```

This reads saved files and checks hashes, input dependencies, source fingerprints, formal-record counts, and CSV/JSON agreement. It does not import or call the experimental checker.

## 3. Case A and Case B

```powershell
.\reproduce.ps1 -Experiment cases -Python $python
```

The launcher calls `run_layered_cases.main()` and changes only its in-memory `OUTPUT_DIR`, so the archived Case A/B evidence is not overwritten. It evaluates the four Case A and two Case B inputs listed in `run_layered_cases.py`, then writes `caseA_layered_results.json` and `caseB_dual_display_results.json` into the new execution directory.

The original `run_caseA.py` and `run_caseB.py` are retained as legacy fixed-rule baselines. They are not the layered paper-case entry point.

## 4. November 10 scalability comparison

The exact K set is `1, 2, 4, 8, 16, 32, 64`. Both resource configurations use `variant=valid`. One warmup and ten formal runs are performed per K/configuration. Models are generated in memory; no external model file or random seed is used by this generator.

For a single serial batch matching the historical grouping:

```powershell
.\reproduce.ps1 -Experiment scalability -Python $python `
  -Sizes 1,2,4,8,16,32,64 -Warmup 1 -Repetitions 10 `
  -ResourceConfigurations isolated,chain_independent
```

This produces 14 warmup and 140 formal records. All warmups are completed before the formal loops. Formal execution order is K, resource configuration, repetition.

To run the configurations separately, producing 7 warmups and 70 formal records each:

```powershell
.\reproduce.ps1 -Experiment scalability -Python $python `
  -Sizes 1,2,4,8,16,32,64 -Warmup 1 -Repetitions 10 `
  -ResourceConfigurations isolated

.\reproduce.ps1 -Experiment scalability -Python $python `
  -Sizes 1,2,4,8,16,32,64 -Warmup 1 -Repetitions 10 `
  -ResourceConfigurations chain_independent
```

The launcher always passes `--variants valid`, `--skip-plots` and an unused output directory. It sets `parallel.enable=False` and `smt.threads=1` explicitly in the same Python process before calling the unmodified entry point. Every launch prints its interpreter, working directory, arguments and output directory.

For clarity, the equivalent direct scalability command after defining `$python` is:

```powershell
$entry = "import runpy,z3; z3.set_param('parallel.enable',False); z3.set_param('smt.threads',1); runpy.run_path('run_scalability_experiment.py',run_name='__main__')"
$out = 'reproduced/comparison-' + [guid]::NewGuid().ToString('N')
& $python -B -u -c $entry `
  --sizes 1 2 4 8 16 32 64 --warmup 1 --repetitions 10 `
  --variants valid --resource-configurations isolated chain_independent `
  --output-dir $out --skip-plots
```

Choose exactly one resource name in that command to run a single configuration. Do not combine the original PSC `controlled_failure` variant with the cross-unit configurations; the original parser rejects that combination.

## 5. K=2 independent/shared-CPU comparison

```powershell
.\reproduce.ps1 -Experiment k2 -Python $python -Warmup 1 -Repetitions 10
```

This selects K=2, `valid`, and `chain_independent chain_shared_cpu`: two warmups and twenty formal records. Both configurations retain 14 established local instances. The independent configuration has 57 proved obligations. The shared-CPU configuration has 56 proved and one failed cross-unit resource obligation, with composition not established.

## 6. Historical command versus reader command

`provenance/historical-run.json` records the November 10 launch. Only its absolute interpreter/output paths have been normalized for publication. Its historical argument sequence was:

```text
.venv/Scripts/python.exe -u run_scalability_experiment.py
  --variants valid
  --resource-configurations isolated chain_independent
  --output-dir <historical-scale-output>
  --skip-plots
```

The historical launch used the parser defaults for K, warmup and repetitions. It did not explicitly set Z3 thread parameters. The saved environment recorded `parallel_enabled=false` and `smt_threads=1`. The reader launcher adds explicit settings; it is not presented as the original terminal command.

## 7. Output and timing fields

Scalability execution writes configuration JSON, separate warmup/progress JSONL, formal-result JSON/CSV and summary CSV. Existing output directories are refused by the entry point. Archived `results/` directories are also protected by the new launcher.

All times are in milliseconds. `total_verification_ms` starts before architecture-context extraction and ends at composition-failure return or completion of failure analysis. Model generation, result serialization and file I/O are outside this interval. `obligation_check_ms` wraps `evaluate_obligations()` and includes local establishment, evidence scheduling and SMT calls. It is not a separate pure-SMT timer. These boundaries match the pre-cross-unit implementation. Structural instantiation checking already belonged to total time; the supplement separately records its timer.

The six `Stage_Time` stages are context extraction, obligation generation, context check, obligation check, combination aggregation and failure expansion. The additional structural-check timer is retained in `Raw_Runs`. Stage medians are calculated independently and need not sum to the total-time median. Summary quartiles use the stored original inclusive-quartile results.

New process scheduling and software installation can affect times. Compare saved output states/counts and the defined timing fields; the same-batch isolated/chain comparison is the reported performance comparison.

## 8. Workbook and optional regression tests

The workbook contains `Total_Time` (7 data rows), `Stage_Time` (84), `Raw_Runs` (140), `Obligation_Data` (14), and `Environment` (66). Error columns are median minus Q1 and Q3 minus median. Long nested raw diagnostics are split across consecutively named columns; their reconstruction rule is in `Environment`.

For a later, separately authorized regression run:

```powershell
& $python -B -m pytest -q -p no:cacheprovider `
  --basetemp ('reproduced/pytest-' + [guid]::NewGuid().ToString('N'))
```

That test suite executes the checker on small inputs. It was not run during archive assembly. `provenance/tests-final.log` is the existing 59-test historical record.

## 9. Native models and figure files

The saved scalability evidence is in `results/scalability/`. Its workbook and result records retain the November 10 experiment date; the directory name does not carry a date suffix.

`models/` includes Case A/B native `.sml2` projects and an SRP modeling example, with their configuration dependency embedded. See [Native modeling projects](models/README.md) for contents and native-application opening notes. The Python reproduction commands above continue to read the structured YAML inputs.

`figures/` includes one total-time PNG and six stage subfigures, forming the manuscript's two scalability figures. See the [Figure index](figures/README.md) for each image's result field and data sources. These supplied images have not been regenerated.
