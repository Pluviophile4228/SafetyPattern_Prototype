# Native modeling projects

| File | Contents confirmed during packaging |
|---|---|
| `caseA.sml2` | Case A flight-control command chain, including `RTA_FCC_A`, `SR_FCC` and `PSC_ACU` |
| `CaseB.sml2` | Case B navigation/display chain, including `MN_Sensor`, `CC_Nav`, `IM_Display_L` and `IM_Display_R` |
| `SafetyPattern.sml2` | SRP template/definition and local-failure modeling example |

Preserve the filenames and capitalization, particularly `caseA.sml2` and `CaseB.sml2`.

Each file is a native project container containing `config.json`, `project.db` and an embedded `config.sml2`. The latter contains its own configuration manifest and database. The three embedded configuration files are byte-identical and identify the configuration project as `pConfigProject`; their SHA-256 is `e39c8aa51940ba281da82fa4d8e41af6f664c919b701591298a771a5c9849e7e`. The recorded project-use dependency refers to that configuration project.

All six outer/embedded containers and databases passed read/integrity checks during packaging on 2026-11-12. The author reports that the projects were prepared using a trial edition of M-Design V2. The exact application build has not been confirmed. The manifest fields `version=1.0.0.17` and `clientVersion=1.1.0.0` are preserved as recorded fields, not substituted for a confirmed application version.

## Opening and portability

The author cannot currently open the projects because a usable M-Design V2 environment is no longer available. Native-application opening after relocation has therefore not been accepted. The project manifests and internal project/dependency records retain local absolute paths from the original machine; archive/database readability does not replace the pending application-level opening check.

The original `.sml2` bytes have been preserved. If a usable M-Design V2 environment becomes available, open working copies, resolve the supplied embedded configuration using the application, and verify the required views after relocation. Prepare any relocated or sanitized copy through the application rather than editing compressed databases directly, then refresh provenance and checksums. The embedded configuration's redistribution terms remain an owner-confirmation item.

## Relation to the executable inputs

The Python prototype executes `../data/caseA_valid.yaml` and the layered inputs derived from it, plus `../data/caseB_parallel_valid.yaml` and its parent `caseB_valid.yaml`. It does not parse these native files. The supplied `SafetyPattern.sml2` is an SRP example; the six executable pattern definitions are in the original Python source, as indexed in [Pattern specifications](../docs/pattern-specifications.md).

See [Architecture descriptions and formal mapping](../docs/model-inputs-and-mapping.md) for the observed name matches. Four Case A name correspondences and the historical model/YAML preparation order could not be recovered by the author. The native files are retained as architecture-representation material; the supplied YAML is the authoritative executable input for these prototype experiments.
