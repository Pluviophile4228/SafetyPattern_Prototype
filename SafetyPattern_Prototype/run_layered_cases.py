from __future__ import annotations

import json
from pathlib import Path

from src.checker import load_architecture, run_layered_check


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"

CASE_FILES = (
    "layered_context_conflict.yaml",
    "layered_obligation_failure.yaml",
    "layered_boundary_flow_failure.yaml",
    "caseA_valid.yaml",
    "caseB_parallel_valid.yaml",
    "layered_caseB_parallel_failure.yaml",
)

CASE_A_NAMES = {
    "layered_context_conflict",
    "layered_obligation_failure",
    "layered_boundary_flow_failure",
    "caseA_valid",
}

CASE_B_NAMES = {
    "caseB_parallel_valid",
    "layered_caseB_parallel_failure",
}


def main() -> None:
    reports = []
    for filename in CASE_FILES:
        report = run_layered_check(load_architecture(DATA_DIR / filename))
        reports.append(report)
        print(f"[{report.case_name}] {report.status} (stage={report.stage})")
        if report.unsat_core:
            print(f"  unsat_core={', '.join(report.unsat_core)}")
        if report.failed_obligation is not None:
            trace = report.failed_obligation.trace
            print(f"  obligation={report.failed_obligation.id}")
            print(f"  trace={trace.trigger}: {', '.join(trace.related_objects)}")
        proved = sum(item.status == "PROVED" for item in report.obligation_results)
        failed = sum(
            item.status
            in {
                "PREMISE_CONTRADICTED",
                "PREMISE_UNSUPPORTED",
                "PREMISE_UNACCEPTABLE",
                "OBLIGATION_FAILED",
            }
            for item in report.obligation_results
        )
        blocked = sum(item.status == "BLOCKED_BY_DEPENDENCY" for item in report.obligation_results)
        print(f"  obligations=proved:{proved}, counterexamples:{failed}, blocked:{blocked}")
        print(f"  combination={report.combination_status}")
        if report.counterexample:
            trace = report.failed_obligation.trace if report.failed_obligation else None
            relevant_keys = [
                f"component.{name}.resource.{resource}"
                for name in (trace.related_objects if trace else ())
                for resource in (trace.resource_types if trace else ())
            ]
            sample = [
                (key, report.counterexample[key])
                for key in relevant_keys
                if key in report.counterexample
            ] or list(report.counterexample.items())[:4]
            print("  counterexample=" + ", ".join(f"{key}={value}" for key, value in sample))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    case_a_reports = [
        report.as_dict()
        for report in reports
        if report.case_name in CASE_A_NAMES
    ]
    case_a_output_path = OUTPUT_DIR / "caseA_layered_results.json"
    with case_a_output_path.open("w", encoding="utf-8") as f:
        json.dump(case_a_reports, f, ensure_ascii=False, indent=2)
    print(f"Wrote {case_a_output_path}")

    dual_display_reports = [
        report.as_dict()
        for report in reports
        if report.case_name in CASE_B_NAMES
    ]
    dual_output_path = OUTPUT_DIR / "caseB_dual_display_results.json"
    with dual_output_path.open("w", encoding="utf-8") as f:
        json.dump(dual_display_reports, f, ensure_ascii=False, indent=2)
    print(f"Wrote {dual_output_path}")


if __name__ == "__main__":
    main()
