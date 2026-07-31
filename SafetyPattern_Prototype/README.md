# Safety-pattern establishment prototype

The original `run_caseA.py` and `run_caseB.py` retain the baseline rule and
cut-set implementation.  The layered workflow is available separately:

```powershell
python run_layered_cases.py
python -m pytest -q
```

`run_layered_cases.py` writes the Case A records used by the paper to
`outputs/caseA_layered_results.json` and the dual-display Case B records to
`outputs/caseB_dual_display_results.json`.  The layered method now ends at
composition establishment and qualitative failure analysis:

- `CONTEXT_CONFLICT`: inconsistent architecture declarations and an UNSAT core;
- `INSTANCE_NOT_ESTABLISHED`: at least one local premise is contradicted or unsupported;
- `COMBINATION_NOT_ESTABLISHED`: a relation premise/obligation fails or is blocked;
- `ANALYSIS_COMPLETED`: every instance and relation is established and all configured
  top events have been expanded.

The variants also include `layered_boundary_flow_failure.yaml`, where all
instances are established but the SR-to-PSC boundary-flow obligation has a
counterexample.  The valid dual-display case runs directly from
`caseB_parallel_valid.yaml`; no system-goal support rule is required.

Dependencies are listed in `requirements.txt` (`pyyaml`, `z3-solver`, and
`pytest`; `matplotlib` remains for the existing project tooling).
