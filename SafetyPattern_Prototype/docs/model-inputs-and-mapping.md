# Architecture descriptions and formal mapping

## Three separate stages

1. Native modeling project and preparation of the structured case description. The author will provide the project in `models/`. No SysML-to-YAML automatic converter or historical element-mapping log is supplied by this prototype. The actual authoring order and manual preparation steps are to be confirmed by the author below.
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

## Author-supplied modeling preparation

Pending material, to be completed with the native project:

- Actual model/YAML authoring order and manual actions.
- MDesign-V2 version and project/library dependencies.
- View names and the saved versions used for the paper.
- Existing element-ID-to-YAML correspondences, if any. If reconstructed now, label them as a newly prepared correspondence table rather than a historical conversion log.

Do not add an automatic transformation claim unless an actual converter and its execution evidence are supplied.
