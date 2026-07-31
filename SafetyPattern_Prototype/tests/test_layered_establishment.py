from __future__ import annotations

from pathlib import Path

import pytest
from z3 import Bool, BoolVal

from src.checker import load_architecture, run_layered_check
from src.establishment import (
    ArchitectureContext,
    ObligationTrace,
    Predicate,
    VerificationObligation,
    build_obligations,
    check_instantiations,
    evaluate_local_premise,
    evaluate_relation_obligations,
)
from src.failure_expansion import expand_failure_semantics
from src.model import PatternInstance


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def layered_report(filename: str):
    return run_layered_check(load_architecture(DATA_DIR / filename))


def relation_obligation(
    identifier: str,
    premise,
    conclusion,
    *,
    dependencies: tuple[str, ...] = (),
    evidence: str | None = None,
) -> VerificationObligation:
    return VerificationObligation(
        id=identifier,
        premise=Predicate(f"premise({identifier})", premise),
        conclusion=Predicate(f"conclusion({identifier})", conclusion),
        trace=ObligationTrace("source", "target", (), "boundary_connection"),
        dependencies=dependencies,
        conclusion_evidence=evidence,
    )


def test_instantiation_failure_is_explicit() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    original = arch.patterns[0]
    broken_roles = dict(original.roles)
    broken_roles.pop("safety_monitor")
    arch.patterns[0] = PatternInstance(
        original.id,
        original.kind,
        broken_roles,
    )

    report = run_layered_check(arch)

    assert report.status == "INSTANTIATION_FAILED"
    assert report.stage == "instantiation"
    assert report.combination_status == "NOT_ESTABLISHED"
    instance = report.instance_results[0]
    assert instance.type_status == "TYPE_ERROR"
    assert instance.embedding_status == "NOT_EVALUATED_TYPE_ERROR"
    assert instance.instantiation_status == "INVALID"
    assert "missing_role:safety_monitor" in instance.instantiation_diagnostics
    assert instance.instance_status == "NOT_ESTABLISHED"
    assert report.failure_analysis is None


@pytest.mark.parametrize(
    "filename",
    ["caseA_valid.yaml", "caseB_parallel_valid.yaml"],
)
def test_valid_pattern_bindings_are_type_correct_and_embedded(
    filename: str,
) -> None:
    checks = check_instantiations(load_architecture(DATA_DIR / filename))

    assert checks
    assert all(item.type_status == "TYPE_OK" for item in checks.values())
    assert all(
        item.embedding_status == "EMBEDDED"
        for item in checks.values()
    )
    assert all(
        item.instantiation_status == "VALID"
        for item in checks.values()
    )


def test_embedding_rejects_non_injective_template_node_mapping() -> None:
    arch = load_architecture(DATA_DIR / "caseB_parallel_valid.yaml")
    index = next(
        index
        for index, pattern in enumerate(arch.patterns)
        if pattern.id == "CC_Nav"
    )
    original = arch.patterns[index]
    broken_roles = dict(original.roles)
    broken_roles["channelB"] = broken_roles["channelA"]
    arch.patterns[index] = PatternInstance(
        original.id,
        original.kind,
        broken_roles,
    )

    check = check_instantiations(arch)["CC_Nav"]

    assert check.type_status == "TYPE_OK"
    assert check.embedding_status == "EMBEDDING_INVALID"
    assert check.instantiation_status == "INVALID"
    assert (
        "non_injective_binding:channelA,channelB:NavProcessor_A"
        in check.embedding_diagnostics
    )


def test_embedding_rejects_boundary_at_wrong_instance_position() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    original = arch.patterns[0]
    broken_roles = dict(original.roles)
    broken_roles["output"] = "SelectedFCCCommand"
    arch.patterns[0] = PatternInstance(
        original.id,
        original.kind,
        broken_roles,
    )

    report = run_layered_check(arch)
    instance = report.instance_results[0]

    assert report.status == "INSTANTIATION_FAILED"
    assert instance.type_status == "TYPE_OK"
    assert instance.embedding_status == "EMBEDDING_INVALID"
    assert (
        "boundary_position_missing:"
        "output:SelectedFCCCommand:output"
        in instance.embedding_diagnostics
    )
    assert instance.instance_status == "NOT_ESTABLISHED"


def test_duplicate_yaml_key_is_rejected_instead_of_silently_overwritten(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text(
        "case_name: first\ncase_name: second\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate YAML key"):
        load_architecture(path)


def test_context_conflict_returns_named_unsat_core_and_instance_state() -> None:
    report = layered_report("layered_context_conflict.yaml")

    assert report.status == "CONTEXT_CONFLICT"
    assert report.stage == "context"
    assert report.combination_status == "NOT_ESTABLISHED"
    assert "component:AdvancedController:resource:PWR" in report.unsat_core
    assert "CTX_ADVANCED_CONTROLLER_PWR_CONFLICT" in report.unsat_core
    assert all(
        item.context_status == "INCONSISTENT"
        and item.instance_status == "NOT_ESTABLISHED"
        for item in report.instance_results
    )


def test_local_premise_states_cover_contradicted_unsupported_and_proved() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    context = ArchitectureContext(arch)

    def local(identifier: str, formula) -> VerificationObligation:
        return VerificationObligation(
            id=identifier,
            premise=Predicate("architecture_context", context.formula()),
            conclusion=Predicate(identifier, formula),
            trace=ObligationTrace("RTA_FCC_A", None, (), "local_contract"),
        )

    contradicted, contradicted_queries = evaluate_local_premise(
        context,
        local("contradicted", BoolVal(False)),
    )
    unsupported, unsupported_queries = evaluate_local_premise(
        context,
        local("unsupported", Bool("free_local_premise")),
    )
    proved, proved_queries = evaluate_local_premise(
        context,
        local("proved", BoolVal(True)),
    )

    assert contradicted.status == "PREMISE_CONTRADICTED"
    assert contradicted_queries == 1
    assert unsupported.status == "PREMISE_UNSUPPORTED"
    assert unsupported.counterexample is not None
    assert unsupported_queries == 2
    assert proved.status == "PROVED"
    assert proved_queries == 2


def test_local_failure_establishes_other_instances_and_blocks_only_dependency() -> None:
    report = layered_report("layered_obligation_failure.yaml")

    assert report.status == "INSTANCE_NOT_ESTABLISHED"
    assert report.combination_status == "NOT_ESTABLISHED"
    assert report.failed_obligation is not None
    assert report.failed_obligation.id == "RTA_FCC_A:RESOURCE_INDEPENDENCE"
    result = next(
        item
        for item in report.obligation_results
        if item.obligation.id == report.failed_obligation.id
    )
    assert result.status == "PREMISE_CONTRADICTED"
    instance_status = {
        item.pattern_id: item.instance_status
        for item in report.instance_results
    }
    assert instance_status == {
        "RTA_FCC_A": "NOT_ESTABLISHED",
        "SR_FCC": "ESTABLISHED",
        "PSC_ACU": "ESTABLISHED",
    }
    blocked = [
        item
        for item in report.obligation_results
        if item.status == "BLOCKED_BY_DEPENDENCY"
    ]
    assert [item.obligation.id for item in blocked] == [
        "REFINEMENT:RTA_FCC_A->SR_FCC.primaryChannel"
    ]
    assert sum(item.status == "PROVED" for item in report.obligation_results) == 11
    assert report.failure_analysis is None


def test_relation_premise_unacceptable_is_not_vacuously_proved() -> None:
    context = ArchitectureContext(
        load_architecture(DATA_DIR / "caseA_valid.yaml")
    )
    item = relation_obligation(
        "UNACCEPTABLE",
        BoolVal(False),
        BoolVal(True),
    )

    results, evidence, query_count = evaluate_relation_obligations(
        context,
        [item],
        set(),
    )

    assert results[0].status == "PREMISE_UNACCEPTABLE"
    assert evidence == {}
    assert query_count == 1


def test_relation_conclusion_release_triggers_downstream_obligation() -> None:
    context = ArchitectureContext(
        load_architecture(DATA_DIR / "caseA_valid.yaml")
    )
    released_formula = Bool("released_relation_conclusion")
    first = relation_obligation(
        "FIRST",
        released_formula,
        released_formula,
        evidence="evidence:first",
    )
    second = relation_obligation(
        "SECOND",
        BoolVal(True),
        released_formula,
        dependencies=("evidence:first",),
        evidence="evidence:second",
    )

    results, evidence, query_count = evaluate_relation_obligations(
        context,
        [first, second],
        set(),
    )

    assert [item.status for item in results] == ["PROVED", "PROVED"]
    assert {"evidence:first", "evidence:second"} <= evidence.keys()
    assert query_count == 4


def test_failed_relation_blocks_its_chain_but_independent_chain_continues() -> None:
    context = ArchitectureContext(
        load_architecture(DATA_DIR / "caseA_valid.yaml")
    )
    failed = relation_obligation(
        "FAILED",
        BoolVal(True),
        BoolVal(False),
        evidence="evidence:failed",
    )
    blocked = relation_obligation(
        "BLOCKED",
        BoolVal(True),
        BoolVal(True),
        dependencies=("evidence:failed",),
    )
    independent = relation_obligation(
        "INDEPENDENT",
        BoolVal(True),
        BoolVal(True),
        evidence="evidence:independent",
    )
    downstream = relation_obligation(
        "DOWNSTREAM",
        BoolVal(True),
        BoolVal(True),
        dependencies=("evidence:independent",),
    )

    results, evidence, _ = evaluate_relation_obligations(
        context,
        [failed, blocked, independent, downstream],
        set(),
    )
    by_id = {item.obligation.id: item for item in results}

    assert by_id["FAILED"].status == "OBLIGATION_FAILED"
    assert by_id["BLOCKED"].status == "BLOCKED_BY_DEPENDENCY"
    assert by_id["BLOCKED"].blocked_by == ("evidence:failed",)
    assert by_id["INDEPENDENT"].status == "PROVED"
    assert by_id["DOWNSTREAM"].status == "PROVED"
    assert "evidence:independent" in evidence


def test_no_ready_obligation_is_dependency_blocked() -> None:
    context = ArchitectureContext(
        load_architecture(DATA_DIR / "caseA_valid.yaml")
    )
    item = relation_obligation(
        "WAITING",
        BoolVal(True),
        BoolVal(True),
        dependencies=("missing:evidence",),
    )

    results, _, query_count = evaluate_relation_obligations(
        context,
        [item],
        set(),
    )

    assert results[0].status == "BLOCKED_BY_DEPENDENCY"
    assert results[0].blocked_by == ("missing:evidence",)
    assert query_count == 0


def test_cross_pattern_boundary_failure_keeps_instances_established() -> None:
    report = layered_report("layered_boundary_flow_failure.yaml")

    assert report.status == "COMBINATION_NOT_ESTABLISHED"
    assert report.stage == "combination"
    assert report.combination_status == "NOT_ESTABLISHED"
    assert all(
        item.instance_status == "ESTABLISHED"
        for item in report.instance_results
    )
    assert report.failed_obligation is not None
    assert report.failed_obligation.id == "FLOW:SR_FCC.output->PSC_ACU.input"
    failure = next(
        item
        for item in report.obligation_results
        if item.obligation.id == report.failed_obligation.id
    )
    assert failure.status == "OBLIGATION_FAILED"
    assert failure.obligation.trace.related_objects == (
        "SelectedFCCCommand",
        "WrongFCCCommand",
    )
    assert all(
        item.status == "PROVED"
        for item in report.obligation_results
        if item.obligation.trace.trigger == "local_contract"
    )
    assert report.failure_analysis is None


def test_case_a_establishes_combination_and_expands() -> None:
    report = layered_report("caseA_valid.yaml")

    assert report.status == "ANALYSIS_COMPLETED"
    assert report.stage == "failure_analysis"
    assert report.combination_status == "ESTABLISHED"
    assert report.failure_spec_status == "COMPLETE"
    assert all(
        item.instance_status == "ESTABLISHED"
        for item in report.instance_results
    )
    assert all(
        item.status == "PROVED"
        for item in report.obligation_results
    )
    assert report.failure_analysis is not None
    assert report.failure_analysis["LossOfActuatorCommand"]["status"] == "EXPANDED"
    assert report.failure_analysis["LossOfActuatorCommand"]["minimal_cut_sets"] == [
        "F_FCCA_LOF;F_FCCB_LOF",
        "F_FCCA_LOF;F_fd_miss",
        "F_FCCA_LOF;F_sw_fail",
        "F_dp_perm",
        "F_dp_trans;F_recover_fail",
    ]
    assert report.failure_analysis["HazardousActuatorCommand"]["status"] == "EXPANDED"
    assert len(
        report.failure_analysis["HazardousActuatorCommand"]["minimal_cut_sets"]
    ) == 4
    substitutions = report.failure_analysis[
        "HazardousActuatorCommand"
    ]["expansion_trace"]["substitutions"]
    assert any(
        item["kind"] == "hierarchy_substitution"
        for item in substitutions
    )


def test_context_closure_and_composition_obligations_use_actual_relations() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    context = ArchitectureContext(arch)
    sr = next(pattern for pattern in arch.patterns if pattern.id == "SR_FCC")

    assert "AdvancedController" in context.context_objects(sr)

    obligations = build_obligations(context)
    traces = {obligation.trace.trigger for obligation in obligations}
    assert "boundary_connection" in traces
    assert "hierarchical_refinement" in traces
    assert "context_overlap:shared_boundary" in traces
    assert all(
        item.conclusion_evidence
        for item in obligations
        if item.trace.trigger != "local_contract"
    )


def test_parallel_case_b_declares_expected_obligations_and_establishes() -> None:
    arch = load_architecture(DATA_DIR / "caseB_parallel_valid.yaml")
    assert "IndependentMonitor" not in arch.components
    assert "DisplayGate" not in arch.components
    assert "DisplayParameterOutput" not in arch.components
    im_instances = [pattern for pattern in arch.patterns if pattern.kind == "IM"]
    assert [pattern.id for pattern in im_instances] == [
        "IM_Display_L",
        "IM_Display_R",
    ]

    report = run_layered_check(arch)
    assert report.status == "ANALYSIS_COMPLETED"
    assert report.combination_status == "ESTABLISHED"
    assert report.obligation_count == 15
    assert sum(
        item.obligation.trace.trigger == "local_contract"
        for item in report.obligation_results
    ) == 9
    assert sum(
        item.obligation.trace.trigger == "boundary_connection"
        for item in report.obligation_results
    ) == 3
    assert sum(
        item.obligation.trace.trigger == "context_overlap:shared_boundary"
        for item in report.obligation_results
    ) == 2
    parallel = next(
        item
        for item in report.obligation_results
        if item.obligation.trace.trigger == "parallel_composition"
    )
    assert parallel.status == "PROVED"
    assert "CheckedNavParameter" not in parallel.obligation.trace.related_objects
    assert report.failure_analysis is not None
    assert set(report.failure_analysis) == {
        "HazardousParameterDisplayed",
        "LossOfTrustedParameterDisplay",
    }
    assert all(
        item["status"] == "EXPANDED"
        for item in report.failure_analysis.values()
    )
    assert len(
        report.failure_analysis[
            "HazardousParameterDisplayed"
        ]["minimal_cut_sets"]
    ) == 10
    assert report.failure_analysis[
        "LossOfTrustedParameterDisplay"
    ]["minimal_cut_sets"] == [
        "F_mn_output_loss",
        "F_cc_output_loss",
        "F_im_l_unavailable;F_im_r_unavailable",
    ]
    loss_trace = report.failure_analysis[
        "LossOfTrustedParameterDisplay"
    ]["expansion_trace"]["substitutions"]
    assert any(
        item["kind"] == "parallel_composition"
        for item in loss_trace
    )


def test_parallel_obligation_is_not_inferred_without_explicit_relation() -> None:
    arch = load_architecture(DATA_DIR / "caseB_valid.yaml")
    obligations = build_obligations(ArchitectureContext(arch))
    assert not any(
        item.trace.trigger == "parallel_composition"
        for item in obligations
    )


def test_parallel_failure_skips_failure_expansion() -> None:
    report = layered_report("layered_caseB_parallel_failure.yaml")

    assert report.status == "COMBINATION_NOT_ESTABLISHED"
    assert report.combination_status == "NOT_ESTABLISHED"
    assert all(
        item.instance_status == "ESTABLISHED"
        for item in report.instance_results
    )
    assert report.failed_obligation is not None
    assert (
        report.failed_obligation.id
        == "PARALLEL:IM_Display_L<->IM_Display_R:RESOURCE_INDEPENDENCE"
    )
    failures = [
        item
        for item in report.obligation_results
        if item.status == "OBLIGATION_FAILED"
    ]
    assert [item.obligation.id for item in failures] == [
        report.failed_obligation.id
    ]
    assert report.counterexample is not None
    assert (
        report.counterexample[
            "component.IndependentMonitor_L.resource.CPU"
        ]
        == report.counterexample[
            "component.IndependentMonitor_R.resource.CPU"
        ]
    )
    assert report.failure_analysis is None


def test_failure_spec_missing_top_events_is_reported_after_establishment() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    arch.failure_semantics = {"local": {}}

    report = run_layered_check(arch)

    assert report.combination_status == "ESTABLISHED"
    assert report.status == "FAILURE_SPEC_INCOMPLETE"
    assert report.failure_spec_status == "INCOMPLETE"
    assert report.failure_analysis is not None
    assert "top_events_missing" in report.failure_analysis["_spec"]["diagnostics"]


def test_missing_event_does_not_stop_independent_top_event() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    arch.failure_semantics = {
        "local": {},
        "top_events": {
            "Broken": {"ref": "Missing.event"},
            "Good": "F_good",
        },
    }

    report = run_layered_check(arch)
    result = report.failure_analysis

    assert report.combination_status == "ESTABLISHED"
    assert report.status == "FAILURE_ANALYSIS_PARTIAL"
    assert result is not None
    assert result["Broken"]["status"] == "FAILURE_SPEC_INCOMPLETE"
    assert result["Good"]["status"] == "EXPANDED"
    assert result["Good"]["minimal_cut_sets"] == ["F_good"]


def test_conflicting_event_definition_is_reported_per_top_event() -> None:
    arch = load_architecture(DATA_DIR / "caseB_parallel_valid.yaml")
    arch.failure_semantics = {
        "local": {
            "MN_Sensor": {
                "output_hazard": "F_local",
            }
        },
        "boundary_transfers": [
            {
                "connection": {
                    "source": "MN_Sensor.output",
                    "target": "CC_Nav.input",
                },
                "source_event": "MN_Sensor.other_hazard",
                "target_event": "MN_Sensor.output_hazard",
            }
        ],
        "top_events": {
            "Conflict": {"ref": "MN_Sensor.output_hazard"},
            "Good": "F_good",
        },
    }

    result = expand_failure_semantics(arch)

    assert result is not None
    assert result["Conflict"]["status"] == "FAILURE_DEFINITION_CONFLICT"
    assert len(result["Conflict"]["sources"]) == 2
    assert result["Good"]["status"] == "EXPANDED"


def test_failure_dependency_cycle_is_isolated() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    arch.failure_semantics = {
        "local": {
            "RTA_FCC_A": {
                "event_a": {"ref": "RTA_FCC_A.event_b"},
                "event_b": {"ref": "RTA_FCC_A.event_a"},
            }
        },
        "top_events": {
            "Cyclic": {"ref": "RTA_FCC_A.event_a"},
            "Good": "F_good",
        },
    }

    result = expand_failure_semantics(arch)

    assert result is not None
    assert result["Cyclic"]["status"] == "FAILURE_EXPANSION_CYCLIC"
    assert result["Good"]["status"] == "EXPANDED"


def test_original_case_b_single_branch_failure_expansion_is_unchanged() -> None:
    arch = load_architecture(DATA_DIR / "caseB_valid.yaml")
    result = expand_failure_semantics(arch)

    assert result is not None
    event = result["HazardousParameterDisplayed"]
    assert event["status"] == "EXPANDED"
    assert event["minimal_cut_sets"] == [
        "F_s1_err;F_s2_err;F_im_miss",
        "F_s1_err;F_s3_err;F_im_miss",
        "F_s2_err;F_s3_err;F_im_miss",
        "F_voter_err;F_im_miss",
        "F_nav_diff;F_cmp_miss;F_im_miss",
    ]
    substitutions = event["expansion_trace"]["substitutions"]
    assert sum(
        item["kind"] == "boundary_transfer"
        for item in substitutions
    ) == 2
