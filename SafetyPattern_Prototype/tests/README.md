# Regression tests

The four Python test modules are unchanged copies from the original prototype:

- `test_caseA.py`: legacy Case A rule and cut-set expectations.
- `test_caseB.py`: legacy Case B rule and cut-set expectations.
- `test_layered_establishment.py`: structural/context, local and relational establishment, dependencies and failure expansion.
- `test_scalability.py`: mixed-unit generation, isolated/chain/shared-CPU configuration, counts, traces and CLI safeguards.

Tests read the sibling `data/` directory and execute small checker configurations. They do not require the external modeling application.

Use the regression command in `README-reproduction.md` in a writable execution copy. The supplied `provenance/tests-final.log` is the historical 59-pass record. Archive preparation does not present that log as a newly executed test run.

The unrelated README previously present in the original tests directory is not copied into this archive.
