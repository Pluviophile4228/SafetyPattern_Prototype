from __future__ import annotations

import json
from pathlib import Path

from src.checker import (
    load_architecture,
    run_consistency_check,
    write_consistency_csv,
    write_rule_coverage_csv,
)
from src.cutsets import (
    caseA_cutset_rows,
    caseA_expression_text,
    write_minimal_cut_sets_csv,
)
from src.rules import caseA_rules


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
LEGACY_OUTPUT_DIR = OUTPUT_DIR / "auxiliary_regression"

CASE_FILES = [
    "caseA_valid.yaml",
    "caseA_invalid_1_rta_shared_power.yaml",
    "caseA_invalid_2_sr_shared_power.yaml",
    "caseA_invalid_3_psc_shared_cpu.yaml",
    "caseA_invalid_4_interface_dal_conflict.yaml",
    "caseA_invalid_5_data_path_broken.yaml",
    "caseA_invalid_6_control_path_missing.yaml",
]

EXPECTED_STATUS = {
    "caseA_valid": "SAT",
    "caseA_invalid_1_rta_shared_power": "UNSAT",
    "caseA_invalid_2_sr_shared_power": "UNSAT",
    "caseA_invalid_3_psc_shared_cpu": "UNSAT",
    "caseA_invalid_4_interface_dal_conflict": "UNSAT",
    "caseA_invalid_5_data_path_broken": "UNSAT",
    "caseA_invalid_6_control_path_missing": "UNSAT",
}


def write_caseA_json(reports, cutset_rows, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "case": "caseA_flight_control_chain",
        "consistency": [],
        "top_events": {
            "expression": caseA_expression_text(),
            "minimal_cut_sets": cutset_rows,
        },
    }

    for report in reports:
        payload["consistency"].append(
            {
                "case": report.case_name,
                "status": report.status,
                "violations": [
                    {
                        "rule_id": violation.rule_id,
                        "rule_family": violation.rule_family,
                        "involved_elements": violation.involved_elements,
                        "conflict_attribute": violation.conflict_attribute,
                        "conflict_value": violation.conflict_value,
                        "message": violation.message,
                    }
                    for violation in report.violations
                ],
            }
        )

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    reports = []
    rules = caseA_rules()

    for filename in CASE_FILES:
        path = DATA_DIR / filename
        arch = load_architecture(path)
        report = run_consistency_check(arch, rules=rules)
        reports.append(report)

        if report.status == "SAT":
            print(f"[{report.case_name}] SAT")
        else:
            violation_text = "; ".join(
                f"{v.rule_id} | elements={v.involved_elements} | "
                f"{v.conflict_attribute}={v.conflict_value}"
                for v in report.violations
            )
            print(f"[{report.case_name}] UNSAT: {violation_text}")

    consistency_path = LEGACY_OUTPUT_DIR / "caseA_consistency_results.csv"
    write_consistency_csv(
        reports,
        consistency_path,
        expected_status_by_case=EXPECTED_STATUS,
    )

    coverage_path = LEGACY_OUTPUT_DIR / "caseA_rule_coverage.csv"
    write_rule_coverage_csv(reports, coverage_path)

    valid_report = next(report for report in reports if report.case_name == "caseA_valid")
    if valid_report.status == "SAT":
        cutset_rows = caseA_cutset_rows(case_name="caseA_valid")
    else:
        cutset_rows = []

    cutset_path = LEGACY_OUTPUT_DIR / "caseA_minimal_cut_sets.csv"
    write_minimal_cut_sets_csv(cutset_rows, cutset_path)

    json_path = LEGACY_OUTPUT_DIR / "caseA_results.json"
    write_caseA_json(reports, cutset_rows, json_path)

    print()
    print("Case A Boolean expressions:")
    print(caseA_expression_text())

    print()
    print("Case A minimal cut sets:")
    for row in cutset_rows:
        print(f"{row['cut_set_id']}: {{{row['events'].replace(';', ', ')}}}")

    print()
    print(f"Wrote {consistency_path}")
    print(f"Wrote {coverage_path}")
    print(f"Wrote {cutset_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
