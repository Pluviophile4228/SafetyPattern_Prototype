from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml

from .establishment import LayeredReport, evaluate_architecture
from .model import Architecture, architecture_from_dict
from .rules import Rule, RuleResult, all_rules


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject YAML mappings whose later key would silently overwrite a value."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(
                f"Duplicate YAML key {key!r} at line "
                f"{key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass
class CheckReport:
    case_name: str
    status: str
    rule_results: list[RuleResult]

    @property
    def violations(self) -> list[RuleResult]:
        return [result for result in self.rule_results if not result.passed]


def _merge_architecture_dict(base: dict, override: dict) -> dict:
    """Merge a small YAML variant onto its base architecture declaration."""

    merged = dict(base)
    for key, value in override.items():
        if key in {"extends", "remove_components"}:
            continue
        # These blocks describe complete semantic models.  Merging their
        # nested event maps would retain stale definitions from a base case.
        if key in {"failure_semantics", "parallel_relations"}:
            merged[key] = value
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_architecture_dict(merged[key], value)
        else:
            merged[key] = value
    # Variants may explicitly remove inherited architecture objects.  This is
    # needed when a clean replacement topology should not retain unused base
    # components in the finite SMT context.
    for component_name in override.get("remove_components", []):
        merged.get("components", {}).pop(str(component_name), None)
    return merged


def _load_architecture_dict(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.load(f, Loader=_UniqueKeyLoader)

    if raw is None:
        raise ValueError(f"YAML file is empty: {path}")
    if not isinstance(raw, dict):
        raise ValueError(f"YAML architecture must be a mapping: {path}")

    parent = raw.get("extends")
    if parent is None:
        return raw
    parent_path = path.parent / str(parent)
    if not parent_path.exists():
        raise ValueError(f"Base architecture does not exist: {parent_path}")
    return _merge_architecture_dict(_load_architecture_dict(parent_path), raw)


def load_architecture(path: Path) -> Architecture:
    raw = _load_architecture_dict(path)

    return architecture_from_dict(raw)


def run_consistency_check(
    arch: Architecture,
    rules: list[Rule] | None = None,
) -> CheckReport:
    results: list[RuleResult] = []
    selected_rules = rules if rules is not None else all_rules()

    for rule in selected_rules:
        results.append(rule.check(arch))

    status = "SAT" if all(result.passed for result in results) else "UNSAT"

    return CheckReport(
        case_name=arch.case_name,
        status=status,
        rule_results=results,
    )


def run_layered_check(arch: Architecture) -> LayeredReport:
    """Layered establishment and failure-analysis workflow."""

    return evaluate_architecture(arch)


def write_consistency_csv(
    reports: list[CheckReport],
    output_path: Path,
    expected_status_by_case: dict[str, str] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    expected_status_by_case = expected_status_by_case or {}

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case",
                "expected_status",
                "observed_status",
                "pass",
                "violated_rule",
                "rule_family",
                "involved_elements",
                "conflict_attribute",
                "conflict_value",
                "message",
            ],
        )
        writer.writeheader()

        for report in reports:
            expected_status = expected_status_by_case.get(report.case_name, "")
            status_pass = (
                str(expected_status == report.status).lower()
                if expected_status
                else ""
            )

            if report.status == "SAT":
                writer.writerow(
                    {
                        "case": report.case_name,
                        "expected_status": expected_status,
                        "observed_status": report.status,
                        "pass": status_pass,
                        "violated_rule": "",
                        "rule_family": "",
                        "involved_elements": "",
                        "conflict_attribute": "",
                        "conflict_value": "",
                        "message": "",
                    }
                )
                continue

            for violation in report.violations:
                writer.writerow(
                    {
                        "case": report.case_name,
                        "expected_status": expected_status,
                        "observed_status": report.status,
                        "pass": status_pass,
                        "violated_rule": violation.rule_id,
                        "rule_family": violation.rule_family,
                        "involved_elements": violation.involved_elements,
                        "conflict_attribute": violation.conflict_attribute,
                        "conflict_value": violation.conflict_value,
                        "message": violation.message,
                    }
                )


def write_rule_coverage_csv(reports: list[CheckReport], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    case_names = [report.case_name for report in reports]
    rule_ids = []
    rule_family_by_id = {}

    for report in reports:
        for result in report.rule_results:
            if result.rule_id not in rule_ids:
                rule_ids.append(result.rule_id)
            rule_family_by_id[result.rule_id] = result.rule_family

    result_by_case_and_rule = {
        (report.case_name, result.rule_id): result
        for report in reports
        for result in report.rule_results
    }

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["rule_id", "rule_family", *case_names],
        )
        writer.writeheader()

        for rule_id in rule_ids:
            row = {
                "rule_id": rule_id,
                "rule_family": rule_family_by_id.get(rule_id, ""),
            }

            for case_name in case_names:
                result = result_by_case_and_rule[(case_name, rule_id)]
                row[case_name] = "PASS" if result.passed else "FAIL"

            writer.writerow(row)
