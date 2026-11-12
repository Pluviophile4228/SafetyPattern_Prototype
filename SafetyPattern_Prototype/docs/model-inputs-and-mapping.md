# Architecture descriptions and formal mapping

## Three separate stages

1. Native modeling projects and preparation of the structured case description. `models/caseA.sml2` and `models/CaseB.sml2` contain the Case A/B projects; `models/SafetyPattern.sml2` contains an SRP modeling example. All three include the same embedded `config.sml2` dependency. The structured YAML descriptions are the executable case inputs. The prototype supplies no automatic SysML-to-YAML converter or historical element-mapping log. See `models/README.md` for the supplied project contents and the remaining authoring-process details.
2. YAML to Python architecture objects. `src/checker.py:_load_architecture_dict()` reads YAML and resolves `extends`; `load_architecture()` calls `src/model.py:architecture_from_dict()`.
3. Python architecture objects to facts and checks. `src/establishment.py:ArchitectureContext` creates typed/named fact variables and formulas. Structural relations also participate in Python-level context queries and obligation generation.

The prototype's executable input is a structured description, not a directly parsed SysML v2 model.

## Input fields

| YAML field | Python representation | Use |
|---|---|---|
| `case_name` | `Architecture.case_name` | Report identifier |
| `components` | Name-keyed `Component` objects | Object kind/type, DAL and resource declarations |
| `interfaces` | `InterfaceDecl` list | Signal, owning pattern, port, type and DAL declarations |
| `patterns` | `PatternInstance` list | Pattern ID/kind and abstract-role bindings |
| `relations` | `Relation` list | Sequence and containment/refinement declarations |
| `edges` | `Edge` list | Declared intra-architecture connections such as control paths |
| `parallel_relations` | List of declaration dictionaries | Explicit instance-pair resource independence, roles and resource kinds |
| `context_assertions` | List of assertion dictionaries | Additional named facts about a subject attribute |
| `failure_semantics` | Local maps, event definitions and transfer declarations | Top-event failure expansion after establishment |
| `extends` | YAML loader only | Relative parent input file |
| `remove_components` | Merge control | Removal of selected inherited component entries |

Dataclasses and exact field handling are authoritative in `src/model.py`; this table documents their roles without adding a new input schema.

## Inheritance

Parent filenames are resolved relative to the child YAML. Dictionaries are recursively merged; lists are replaced rather than concatenated. `failure_semantics` and `parallel_relations` are replaced as complete blocks when overridden. Missing parent files, empty/nonmapping YAML and duplicate mapping keys are rejected by the loader.

The layered entry point selects six files, whose dependency closure contains nine files:

| Selected input | Additional parent files |
|---|---|
| `layered_context_conflict.yaml` | `caseA_valid.yaml` |
| `layered_obligation_failure.yaml` | `caseA_invalid_1_rta_shared_power.yaml` |
| `layered_boundary_flow_failure.yaml` | `caseA_invalid_5_data_path_broken.yaml` |
| `caseA_valid.yaml` | None |
| `caseB_parallel_valid.yaml` | `caseB_valid.yaml` |
| `layered_caseB_parallel_failure.yaml` | `caseB_parallel_valid.yaml`, then `caseB_valid.yaml` |

All nineteen existing YAML files are retained to preserve the regression inputs as well.

## Fact construction and traceability

`ArchitectureContext._add_declared_facts()` adds component type, DAL and resource values, and each interface's signal, owner, port, type and DAL. `_add_context_assertions()` adds the supplied named assertions. `FiniteDomainEncoder` maps valid string values to finite integer identifiers. `_add_fact()` binds an integer variable to the encoded value.

Component names are preserved in fact keys such as `component.<name>.resource.CPU`. Interfaces are indexed in fact keys and retain their signal and owner attributes. Patterns, roles, edges and hierarchy are also used by structural/context queries; not every declaration is serialized into an independent SMT fact variable.

`build_obligations()` generates obligations. `ObligationTrace` carries source/target pattern identifiers, related objects, trigger and resource kinds. Reports retain those identifiers and counterexamples. This is traceability from the supplied architecture description to checks and results, not a recorded original SysML-element transformation history.

## Supplied native models and name correspondence

The native project containers, their embedded configuration containers and their SQLite databases were read successfully during the November 12 packaging review. No project was opened or resaved in MDesign-V2 during that review.

The review compared active `notation` records with `ebnf_key=identification` to the YAML object names:

| Native project | Executable YAML | Same-name component entries | Same-name pattern IDs |
|---|---|---:|---:|
| `models/caseA.sml2` | `data/caseA_valid.yaml` | 17 of 21 | 3 of 3 |
| `models/CaseB.sml2` | `data/caseB_parallel_valid.yaml` with its parent `caseB_valid.yaml` | 15 of 15 | 4 of 4 |

For Case A, `RTA_Input`, `StandbyInput_B`, `StandbyController_B` and `StandbyCommand_B` have no exact same-name identification record. The project contains names including `A_input`, `B_input` and `FCC_B_Processor`; assigning these to the four YAML objects requires the author's confirmation of the intended boundaries and bindings. No correspondence has been assigned solely from name similarity.

These are newly prepared name-comparison observations, not a historical model-to-YAML conversion record. The native `require_data_mapping` table contains no records in any of the three supplied projects, and no separate SysML-element-to-YAML correspondence file is supplied.

## Modeling preparation to confirm

- Actual native-model/YAML authoring order and manual actions.
- MDesign-V2 application version, native opening of the supplied projects and resolution of the embedded configuration after relocation.
- View names and saved versions used for the paper.
- The four Case A object correspondences above, and any existing element-ID-to-YAML correspondence records. A table prepared now should be identified as a new correspondence table.

The supplied modeling projects and the existing YAML-to-Python-to-fact implementation document separate parts of the workflow. The executable transformation begins with the structured YAML description.
