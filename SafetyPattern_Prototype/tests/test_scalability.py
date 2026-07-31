from __future__ import annotations

from src.establishment import ArchitectureContext, build_obligations
from src.scalability import generate_mixed_architecture, obligation_counts, timed_mixed_evaluation


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
