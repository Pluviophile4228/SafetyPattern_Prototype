# Pattern specification locations

The executable definitions used by this prototype are contained in this archive; no migrated pattern library is needed.

| Pattern | Meaning | Structure and contract |
|---|---|---|
| SR | Standby redundancy | `src/pattern_contracts.py`, SR branches |
| MN | Multi-input voting | Same file, MN branches |
| PSC | Protected single channel | Same file, PSC branches |
| CC | Cross-comparison | Same file, CC branches |
| IM | Independent monitoring | Same file, IM branches |
| RTA | Runtime assurance | Same file, RTA branches |

`structure_for()` supplies role types, distinct-role groups and boundary placements. `contract_for()` supplies required roles, assumptions and guarantees. `src/establishment.py` maps the clause kinds and bound roles to local and relational checks.

The architecture-specific failure maps are in `data/*.yaml` under `failure_semantics`. For the mixed architecture they are constructed by `src/scalability.py:_failure_semantics()`. `src/failure_expansion.py` interprets local expressions, transfers, hierarchy substitutions, parallel compositions and top events. `src/cutsets.py` calculates minimal cut sets.

`src/rules.py` and the fixed Case A/B functions in `src/cutsets.py` retain the legacy baseline. The paper's layered flow uses the establishment and architecture-aware expansion path.

The accompanying `6类模式的规约.docx` is an explanatory knowledge document, not a runtime input. Its body is retained; basic author/company metadata is removed only in this publication copy. It includes broader dynamic and quantitative conditions than this static implementation. Before release, the author should reconcile its terminology/references with the executable clauses and add the relevant source bibliography. No independent engineering review or full implementation of every prose clause is asserted by this file.
