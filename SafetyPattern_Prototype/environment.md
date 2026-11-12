# Software environment

## Recorded November 10 experiment environment

The authoritative records are `results/scalability/scalability_results.json` and `scalability_configuration.json`.

| Item | Recorded value |
|---|---|
| Python | `3.12.14 (main, Aug 25 2026, 14:01:42) [MSC v.1944 64 bit (AMD64)]` |
| Z3 | `4.16.0` |
| Operating system | `Windows-11-10.0.26200-SP0` |
| CPU | Intel Core i5-12600KF |
| Logical processors | 16 |
| Physical memory | 34191212544 bytes |
| Z3 parallel solving | `false` |
| Z3 SMT threads | `1` |
| Git commit | Not recorded (`null`) |

The historical records do not contain a complete dependency freeze. Their Z3 value is the solver's short version, not an independently recorded full wheel-version inventory.

## Current reproduction snapshot

`provenance/environment-current.json` was captured on 2026-11-11 from the currently installed prototype environment. It contains the interpreter build, current full Z3 version and all installed package versions, with no local interpreter/home path.

The current direct package versions are PyYAML 6.0.2, z3-solver 4.16.0.0, pytest 9.0.2 and matplotlib 3.11.0. `requirements-lock.txt` pins these and their runtime/test/plot dependency closure. Other packages present in the shared environment are retained in the JSON inventory but are not made unnecessary prototype installation requirements.

`requirements.txt` is an unchanged copy of the original lower-bound dependency declarations. Use `requirements-lock.txt` for the selected reproduction environment and CPython 3.12.14 for the interpreter. The current snapshot is not labeled as a November 10 historical freeze. A fresh installation using these pins has not been accepted during this packaging task.

PyYAML is used for the case inputs. Z3 is used by verification. pytest is used by tests. matplotlib supports the original optional plotting functions; all documented archive-reproduction commands skip plot generation.

## Solver and launch settings

The reader launcher explicitly sets `parallel.enable=False` and `smt.threads=1` before invoking the unchanged prototype. Historical launch records only show these values as observed by the environment recorder. No CPU-affinity or additional thread-control setting is added to the historical record.

The three supplied `.sml2` project manifests record `version=1.0.0.17` and `clientVersion=1.1.0.0`. These are stored manifest fields, not a recovered installer or an independently confirmed MDesign-V2 application version. Confirm the application version when testing the projects in MDesign-V2. The supplied PNGs have empty software-version metadata; no Origin application version or project file is recorded. See `models/README.md` and `figures/README.md`.
