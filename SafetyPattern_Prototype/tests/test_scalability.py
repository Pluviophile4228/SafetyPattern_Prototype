from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.establishment import ArchitectureContext, build_obligations
from src.scalability import generate_mixed_architecture, obligation_counts, run_once, summarise, timed_mixed_evaluation


def test_one_mixed_unit_has_six_types_seven_instances_and_isolated_names() -> None:
    arch = generate_mixed_architecture(1)
    assert {item.kind for item in arch.patterns} == {"RTA", "SR", "PSC", "MN", "CC", "IM"}
    assert len(arch.patterns) == 7
    assert len(arch.components) == 36
    assert all(name.endswith("_1") or "_1_" in name for name in arch.components)


def test_k_units_are_deterministic_and_do_not_create_cross_unit_composition() -> None:
    first = generate_mixed_architecture(2)
    second = generate_mixed_architecture(2)
    assert list(first.components) == list(second.components)
    assert [item.id for item in first.patterns] == [item.id for item in second.patterns]
    assert len(first.patterns) == 14
    assert all(
        source.rsplit("_", 1)[1] == target.rsplit("_", 1)[1]
        for relation in first.relations
        if relation.kind == "sequence"
        for source, target in [(relation.attributes["source"].split(".", 1)[0], relation.attributes["target"].split(".", 1)[0])]
    )
    assert all(
        relation["left_instance"].rsplit("_", 1)[1] == relation["right_instance"].rsplit("_", 1)[1]
        for relation in first.parallel_relations
    )


def test_obligation_structure_reuses_all_contract_and_composition_kinds() -> None:
    arch = generate_mixed_architecture(2)
    obligations = build_obligations(ArchitectureContext(arch))
    assert obligation_counts(obligations) == {
        "local_obligation_count": 36,
        "boundary_obligation_count": 8,
        "refinement_obligation_count": 2,
        "overlap_obligation_count": 8,
        "composition_obligation_count": 2,
        "total_obligation_count": 56,
    }
    assert all("_1" in item.id or "_2" in item.id for item in obligations)
    assert all(
        item.trace.target_pattern is None
        or item.trace.source_pattern.rsplit("_", 1)[1] == item.trace.target_pattern.rsplit("_", 1)[1]
        for item in obligations
    )
    second_obligations = build_obligations(ArchitectureContext(generate_mixed_architecture(2)))
    assert [item.id for item in obligations] == [item.id for item in second_obligations]


def test_valid_mixed_architecture_establishes_combination_and_expands_failures() -> None:
    report, timing = timed_mixed_evaluation(generate_mixed_architecture(2))
    assert report.status == "ANALYSIS_COMPLETED"
    assert report.combination_status == "ESTABLISHED"
    assert all(
        item.instance_status == "ESTABLISHED"
        for item in report.instance_results
    )
    assert all(item.status == "PROVED" for item in report.obligation_results)
    assert report.failure_analysis is not None and len(report.failure_analysis) == 8
    assert sum(len(item["minimal_cut_sets"]) for item in report.failure_analysis.values()) == 44
    trace_kinds = {
        substitution["kind"]
        for item in report.failure_analysis.values()
        for substitution in item["expansion_trace"]["substitutions"]
    }
    assert {"local_pattern_formula", "boundary_transfer", "hierarchy_substitution", "parallel_composition"} <= trace_kinds
    assert timing["total_obligation_count"] == 56
    assert timing["smt_query_count"] == 113
    assert timing["combination_aggregation_ms"] >= 0
    assert timing["failure_analysis_skipped"] is False
    assert not any("goal" in key for key in timing)


def test_controlled_failure_is_only_last_psc_cpu_independence_and_skips_later_stages() -> None:
    report, timing = timed_mixed_evaluation(generate_mixed_architecture(2, "controlled_failure"))
    expected = "PSC_ACU_2:CPU_INDEPENDENCE"
    assert report.status == "COMBINATION_NOT_ESTABLISHED"
    assert report.combination_status == "NOT_ESTABLISHED"
    assert report.failed_obligation is not None and report.failed_obligation.id == expected
    failures = [
        item.obligation.id
        for item in report.obligation_results
        if item.status == "PREMISE_CONTRADICTED"
    ]
    assert failures == [expected]
    assert len(report.obligation_results) == 56
    assert report.counterexample is None
    assert report.failure_analysis is None
    assert timing["failure_analysis_skipped"] is True
    assert timing["combination_aggregation_ms"] >= 0
    assert not any("goal" in key for key in timing)


@pytest.mark.parametrize("size, extra", [(1, 0), (2, 1), (4, 3), (8, 7), (16, 15), (32, 31), (64, 63)])
def test_cross_unit_chain_preserves_objects_bindings_and_internal_relations(size, extra) -> None:
    baseline = generate_mixed_architecture(size)
    chain = generate_mixed_architecture(size, resource_configuration="chain_independent")
    assert chain.components == baseline.components
    assert chain.patterns == baseline.patterns
    assert chain.interfaces == baseline.interfaces
    assert chain.relations == baseline.relations
    assert chain.edges == baseline.edges
    assert chain.failure_semantics == baseline.failure_semantics
    assert len(chain.patterns) == 7 * size
    assert len(chain.components) == 36 * size
    assert chain.parallel_relations[:size] == baseline.parallel_relations
    assert chain.parallel_relations[size:] == [
        {"left_instance": f"IM_Display_L_{unit}", "right_instance": f"IM_Display_L_{unit + 1}",
         "constrained_resources": ["PWR", "CPU", "CLK"], "resource_roles": ["monitor", "gate"]}
        for unit in range(1, size)
    ]
    assert len(build_obligations(ArchitectureContext(chain))) == 28 * size + extra


def test_shared_cpu_changes_only_last_adjacent_monitors_cpu_value() -> None:
    valid = asdict(generate_mixed_architecture(4, resource_configuration="chain_independent"))
    failure = asdict(generate_mixed_architecture(4, resource_configuration="chain_shared_cpu"))
    valid.pop("case_name")
    failure.pop("case_name")
    valid_components = valid.pop("components")
    failure_components = failure.pop("components")
    assert valid == failure
    assert [key for key in valid_components if valid_components[key] != failure_components[key]] == ["IndependentMonitor_L_4"]
    expected = valid_components["IndependentMonitor_L_4"]
    expected["resources"]["CPU"] = valid_components["IndependentMonitor_L_3"]["resources"]["CPU"]
    assert failure_components["IndependentMonitor_L_4"] == expected


@pytest.mark.parametrize("configuration, status", [
    ("chain_independent", "PROVED"), ("chain_shared_cpu", "OBLIGATION_FAILED"),
])
def test_k2_cross_unit_obligation_has_local_evidence_and_resource_trace(configuration, status) -> None:
    report, timing = timed_mixed_evaluation(generate_mixed_architecture(2, resource_configuration=configuration))
    assert len(report.instance_results) == 14
    assert all(item.instance_status == "ESTABLISHED" for item in report.instance_results)
    cross = next(item for item in report.obligation_results
                 if item.obligation.id == "PARALLEL:IM_Display_L_1<->IM_Display_L_2:RESOURCE_INDEPENDENCE")
    assert cross.status == status
    assert cross.obligation.dependencies == ("instance:IM_Display_L_1:ESTABLISHED", "instance:IM_Display_L_2:ESTABLISHED")
    assert cross.obligation.trace.source_pattern == "IM_Display_L_1"
    assert cross.obligation.trace.target_pattern == "IM_Display_L_2"
    assert cross.obligation.trace.resource_types == ("PWR", "CPU", "CLK")
    assert cross.obligation.trace.related_objects == ("IndependentMonitor_L_1", "DisplayGate_L_1", "IndependentMonitor_L_2", "DisplayGate_L_2")
    assert timing["total_obligation_count"] == 57
    assert timing["instantiation_check_ms"] >= 0
    failures = [item for item in report.obligation_results if item.status != "PROVED"]
    if status == "PROVED":
        assert report.combination_status == "ESTABLISHED"
        assert failures == []
        assert report.failure_analysis is not None
    else:
        assert report.combination_status == "NOT_ESTABLISHED"
        assert failures == [cross]
        assert report.failure_analysis is None
        assert cross.counterexample["component.IndependentMonitor_L_1.resource.CPU"] == cross.counterexample["component.IndependentMonitor_L_2.resource.CPU"]


@pytest.mark.parametrize("size, variant, configuration", [
    (2, "valid", "unknown"),
    (1, "valid", "chain_shared_cpu"),
    (2, "controlled_failure", "chain_independent"),
    (2, "controlled_failure", "chain_shared_cpu"),
])
def test_invalid_or_mixed_error_configurations_are_rejected(size, variant, configuration) -> None:
    with pytest.raises(ValueError):
        generate_mixed_architecture(size, variant, resource_configuration=configuration)


def test_default_and_explicit_isolated_architectures_match() -> None:
    assert generate_mixed_architecture(2) == generate_mixed_architecture(2, resource_configuration="isolated")


def test_records_export_full_cross_unit_evidence_and_count_actual_obligations() -> None:
    record = run_once(2, "valid", resource_configuration="chain_shared_cpu")
    assert record["pattern_instance_count"] == 14
    assert record["architecture_object_count"] == 72
    assert record["combination_declaration_count"] == 13
    assert record["parallel_relation_count"] == 3
    assert record["cross_unit_relation_count"] == 1
    assert record["cross_unit_obligation_count"] == 1
    assert record["total_obligation_count"] == 57
    assert record["composition_obligation_count"] == 3
    assert record["resource_configuration"] == "chain_shared_cpu"
    assert record["all_instances_established"] is True
    assert record["obligation_status_counts"] == {"PROVED": 56, "OBLIGATION_FAILED": 1}
    assert len(record["non_proved_obligations"]) == 1
    obligation, = record["cross_unit_obligations"]
    assert obligation["status"] == "OBLIGATION_FAILED"
    assert obligation["trace"]["resource_types"] == ["PWR", "CPU", "CLK"]
    assert len(obligation["dependencies"]) == 2
    assert obligation["counterexample"]["component.IndependentMonitor_L_1.resource.CPU"] == obligation["counterexample"]["component.IndependentMonitor_L_2.resource.CPU"]
    assert record["counterexample"] is not None


def test_summary_keeps_configurations_separate_and_checks_counts() -> None:
    isolated = run_once(2, "valid")
    chain = run_once(2, "valid", resource_configuration="chain_independent")
    rows = summarise([isolated, chain])
    assert len(rows) == 2
    by_configuration = {row["resource_configuration"]: row for row in rows}
    assert by_configuration["isolated"]["formula_expected_total"] == 56
    assert by_configuration["chain_independent"]["formula_expected_total"] == 57
    assert all(row["formula_matches_actual"] for row in rows)
    broken = dict(chain, total_obligation_count=999)
    assert summarise([broken])[0]["formula_matches_actual"] is False
    with pytest.raises(ValueError, match="inconsistent"):
        summarise([chain, broken])


def _run_cli(*arguments):
    prototype = Path(__file__).resolve().parents[1]
    return subprocess.run([sys.executable, str(prototype / "run_scalability_experiment.py"), *map(str, arguments)],
                          cwd=prototype, capture_output=True, text=True)


def test_cli_records_configuration_and_refuses_overwriting_outputs(tmp_path) -> None:
    output = tmp_path / "paired"
    args = ("--sizes", 2, "--variants", "valid", "--resource-configurations", "chain_independent", "chain_shared_cpu",
            "--warmup", 0, "--repetitions", 1, "--skip-plots", "--output-dir", output)
    first = _run_cli(*args)
    assert first.returncode == 0, first.stderr
    destination = output / "scalability_results.json"
    before = destination.read_bytes()
    payload = json.loads(before)
    assert payload["configuration"]["resource_configurations"] == ["chain_independent", "chain_shared_cpu"]
    assert len(payload["raw_runs"]) == 2
    assert [item["cross_unit_obligations"][0]["status"] for item in payload["raw_runs"]] == ["PROVED", "OBLIGATION_FAILED"]
    assert len((output / "scalability_progress.jsonl").read_text().splitlines()) == 2
    assert _run_cli(*args).returncode != 0
    assert destination.read_bytes() == before


@pytest.mark.parametrize("arguments", [
    ("--sizes", "1", "--resource-configurations", "chain_shared_cpu", "--variants", "valid"),
    ("--sizes", "2", "--resource-configurations", "chain_independent"),
    ("--sizes", "2", "--variants", "valid", "--repetitions", "0"),
])
def test_cli_rejects_invalid_configs_before_creating_results(arguments, tmp_path) -> None:
    output = tmp_path / "invalid"
    result = _run_cli(*arguments, "--output-dir", output, "--skip-plots")
    assert result.returncode != 0
    assert not output.exists()
