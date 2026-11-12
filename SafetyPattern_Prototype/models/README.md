# Native modeling projects

| File | Contents confirmed during packaging |
|---|---|
| `caseA.sml2` | Case A flight-control command chain, including `RTA_FCC_A`, `SR_FCC` and `PSC_ACU` |
| `CaseB.sml2` | Case B navigation/display chain, including `MN_Sensor`, `CC_Nav`, `IM_Display_L` and `IM_Display_R` |
| `SafetyPattern.sml2` | SRP template/definition and local-failure modeling example |

Preserve the filenames and capitalization, particularly `caseA.sml2` and `CaseB.sml2`.

Each file is a native project container containing `config.json`, `project.db` and an embedded `config.sml2`. The latter contains its own configuration manifest and database. The three embedded configuration files are byte-identical and identify the configuration project as `pConfigProject`; their SHA-256 is `e39c8aa51940ba281da82fa4d8e41af6f664c919b701591298a771a5c9849e7e`. The recorded project-use dependency refers to that configuration project.

All six outer/embedded containers and databases passed read/integrity checks during packaging on 2026-11-12. The supplied project manifests record `version=1.0.0.17` and `clientVersion=1.1.0.0`; confirm the actual MDesign-V2 application version separately.

## Opening and portability

Open working copies with MDesign-V2. The project manifests and internal project/dependency records retain local absolute paths from their original machine. If prompted, resolve the configuration dependency to the supplied embedded configuration using MDesign-V2's own project/library facilities. Confirm that the projects and required views open after moving the archive to another directory. This native-application acceptance step remains with the author.

The original `.sml2` bytes have been preserved. Do not replace paths directly in the compressed databases. Prepare any relocated or sanitized publication copy through the modeling application and then refresh its provenance and checksums. Review the embedded configuration's redistribution terms before public release.

## Relation to the executable inputs

The Python prototype executes `../data/caseA_valid.yaml` and the layered inputs derived from it, plus `../data/caseB_parallel_valid.yaml` and its parent `caseB_valid.yaml`. It does not parse these native files. The supplied `SafetyPattern.sml2` is an SRP example; the six executable pattern definitions are in the original Python source, as indexed in [Pattern specifications](../docs/pattern-specifications.md).

See [Architecture descriptions and formal mapping](../docs/model-inputs-and-mapping.md) for the observed name matches and the four Case A objects whose correspondence requires confirmation. No historical automatic model-to-YAML conversion record has been added.
