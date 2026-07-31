"""Mixed-architecture scalability experiment for the layered checker.

The experiment is deliberately independent from the paper cases.  A scale
``K`` creates ``K`` isolated mixed units; every unit reuses the existing RTA,
SR, PSC, MN, CC and dual-IM contracts and their real composition relations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter_ns
from typing import Any, Iterable
import csv
import ctypes
import os
import platform
import subprocess
import sys

from z3 import get_param, get_version_string

from .establishment import (
    ArchitectureContext,
    InstanceResult,
    ObligationResult,
    VerificationObligation,
    aggregate_combination_status,
    _context_consistency,
    build_obligations,
    check_instantiations,
    evaluate_obligations,
)
from .failure_expansion import expand_failure_semantics, failure_spec_status
from .model import Architecture, Component, Edge, InterfaceDecl, PatternInstance, Relation


SIZES = (1, 2, 4, 8, 16, 32, 64)
VARIANTS = ("valid", "controlled_failure")


def _ms(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000


def _resources(prefix: str, unit: int, suffix: str = "") -> dict[str, str]:
    postfix = f"_{unit}{suffix}"
    return {kind: f"{kind}_{prefix}{postfix}" for kind in ("PWR", "CLK", "SW", "CPU")}


def _component(
    name: str,
    kind: str,
    component_type: str,
    dal: str = "A",
    resources: dict[str, str] | None = None,
) -> Component:
    return Component(name, kind, component_type, dal, resources or {})


def _add_flight_control_unit(
    unit: int,
    components: dict[str, Component],
    interfaces: list[InterfaceDecl],
    patterns: list[PatternInstance],
    relations: list[Relation],
    edges: list[Edge],
    controlled_failure: bool,
) -> None:
    """Add the Case-A RTA -> SR -> PSC chain with unit-local names."""

    def n(stem: str) -> str:
        return f"{stem}_{unit}"

    specs = [
        ("FCC_A", "composite", "PrimaryChannel", "A"),
        ("FCC_B", "composite", "StandbyChannel", "A"),
        ("RTA_Input", "atomic", "Input", "A"),
        ("FeatureExtractor", "atomic", "Processor", "B"),
        ("AdvancedController", "atomic", "Controller", "B"),
        ("PrimaryOutput", "atomic", "Output", "A"),
        ("SafeInputProcessor", "atomic", "Processor", "A"),
        ("SafetyController", "atomic", "Controller", "A"),
        ("SafetyOutput", "atomic", "Output", "A"),
        ("SafetyMonitor", "atomic", "Monitor", "A"),
        ("CommandSelector", "atomic", "Selector", "A"),
        ("FCCFaultDetector", "atomic", "FaultDetector", "A"),
        ("FCCSwitchingUnit", "atomic", "SwitchingUnit", "A"),
        ("StandbyInput_B", "atomic", "Input", "A"),
        ("StandbyController_B", "atomic", "Controller", "A"),
        ("ACU_Input", "atomic", "Input", "A"),
        ("ActuatorControlProcessor", "atomic", "Processor", "A"),
        ("DataIntegrityChecker", "atomic", "Checker", "A"),
        ("AnomalyMonitor", "atomic", "Monitor", "A"),
    ]
    for stem, kind, component_type, dal in specs:
        components[n(stem)] = _component(n(stem), kind, component_type, dal, _resources(stem.upper(), unit))
    # Case A models PrimaryCommand and SelectedFCCCommand as declared
    # interfaces, not signal components.  Preserve that distinction here.
    for stem, component_type in (
        ("StandbyCommand", "FCCCommand"),
        ("ActuatorCommandOutput", "ActuatorCommand"),
    ):
        components[n(stem)] = _component(n(stem), "signal", component_type)

    if controlled_failure:
        broken = dict(components[n("DataIntegrityChecker")].resources)
        broken["CPU"] = components[n("ActuatorControlProcessor")].resources["CPU"]
        components[n("DataIntegrityChecker")] = _component(
            n("DataIntegrityChecker"), "atomic", "Checker", "A", broken
        )

    rta, sr, psc = n("RTA_FCC"), n("SR_FCC"), n("PSC_ACU")
    primary, standby, selected = n("PrimaryCommand"), n("StandbyCommand"), n("SelectedFCCCommand")
    interfaces.extend(
        [
            InterfaceDecl(primary, rta, "output", "FCCCommand", "A"),
            InterfaceDecl(primary, sr, "primaryChannel.output", "FCCCommand", "A"),
            InterfaceDecl(standby, sr, "standbyChannel.output", "FCCCommand", "A"),
            InterfaceDecl(selected, sr, "output", "FCCCommand", "A"),
            InterfaceDecl(selected, psc, "input", "FCCCommand", "A"),
        ]
    )
    patterns.extend(
        [
            PatternInstance(rta, "RTA", {
                "input": n("RTA_Input"), "feature_extractor": n("FeatureExtractor"),
                "advanced_controller": n("AdvancedController"), "primary_output": n("PrimaryOutput"),
                "safe_input_processor": n("SafeInputProcessor"), "safety_controller": n("SafetyController"),
                "safety_output": n("SafetyOutput"), "safety_monitor": n("SafetyMonitor"),
                "command_selector": n("CommandSelector"), "output": primary,
            }),
            PatternInstance(sr, "SR", {
                "primary_channel": n("FCC_A"), "standby_channel": n("FCC_B"),
                "fault_detector": n("FCCFaultDetector"), "switching_unit": n("FCCSwitchingUnit"),
                "primary_output": primary, "standby_output": standby, "output": selected,
                "primary_critical_nodes": [n(x) for x in ("AdvancedController", "SafetyController", "SafetyMonitor", "CommandSelector")],
                "standby_critical_nodes": [n("StandbyController_B")],
            }),
            PatternInstance(psc, "PSC", {
                "input": selected, "acu_input": n("ACU_Input"),
                "actuator_control_processor": n("ActuatorControlProcessor"),
                "data_integrity_checker": n("DataIntegrityChecker"), "anomaly_monitor": n("AnomalyMonitor"),
                "output": n("ActuatorCommandOutput"),
            }),
        ]
    )
    edges.extend([
        Edge(n("SafetyMonitor"), n("CommandSelector"), "control"),
        Edge(n("FCCFaultDetector"), n("FCCSwitchingUnit"), "control"),
    ])
    relations.extend([
        Relation("contains", {"parent": f"{sr}.primaryChannel", "child": rta}),
        Relation("sequence", {"source": f"{sr}.output", "target": f"{psc}.input"}),
    ])


def _add_display_unit(
    unit: int,
    components: dict[str, Component],
    interfaces: list[InterfaceDecl],
    patterns: list[PatternInstance],
    relations: list[Relation],
    edges: list[Edge],
    parallel_relations: list[dict[str, Any]],
) -> None:
    """Add the existing dual-display Case-B chain with unit-local names."""

    def n(stem: str) -> str:
        return f"{stem}_{unit}"

    for channel in range(1, 4):
        name = f"Sensor_{unit}_{channel}"
        components[name] = _component(name, "atomic", "Sensor", "A", _resources(f"SENSOR_{channel}", unit))
    for stem, component_type in (
        ("Voter", "Voter"), ("NavProcessor_A", "NavProcessor"),
        ("NavProcessor_B", "NavProcessor"), ("CrossComparator", "Comparator"),
    ):
        components[n(stem)] = _component(n(stem), "atomic", component_type, "A", _resources(stem.upper(), unit))
    for side in ("L", "R"):
        components[n(f"IndependentMonitor_{side}")] = _component(
            n(f"IndependentMonitor_{side}"), "atomic", "IndependentMonitor", "A", _resources(f"IM_{side}", unit)
        )
        components[n(f"DisplayGate_{side}")] = _component(
            n(f"DisplayGate_{side}"), "atomic", "Gate", "A", _resources(f"GATE_{side}", unit)
        )
        components[n(f"DisplayParameterOutput_{side}")] = _component(
            n(f"DisplayParameterOutput_{side}"), "signal", "DisplayOutput"
        )
    voted, checked = n("VotedFlightParameter"), n("CheckedNavParameter")
    components[voted] = _component(voted, "signal", "FlightParameter")
    components[checked] = _component(checked, "signal", "CheckedParameter")
    mn, cc, im_l, im_r = n("MN_Sensor"), n("CC_Nav"), n("IM_Display_L"), n("IM_Display_R")
    interfaces.extend([
        InterfaceDecl(voted, mn, "output", "FlightParameter", "A"),
        InterfaceDecl(voted, cc, "input", "FlightParameter", "A"),
        InterfaceDecl(checked, cc, "output", "CheckedParameter", "A"),
        InterfaceDecl(checked, im_l, "input", "CheckedParameter", "A"),
        InterfaceDecl(checked, im_r, "input", "CheckedParameter", "A"),
    ])
    upstream = [n(item) for item in ("NavProcessor_A", "NavProcessor_B", "CrossComparator")]
    patterns.extend([
        PatternInstance(mn, "MN", {
            "inputChannels": [f"Sensor_{unit}_{channel}" for channel in range(1, 4)],
            "voter": n("Voter"), "output": voted,
        }),
        PatternInstance(cc, "CC", {
            "input": voted, "channelA": n("NavProcessor_A"), "channelB": n("NavProcessor_B"),
            "comparator": n("CrossComparator"), "output": checked,
        }),
        *[
            PatternInstance(n(f"IM_Display_{side}"), "IM", {
                "input": checked, "monitor": n(f"IndependentMonitor_{side}"),
                "gate": n(f"DisplayGate_{side}"), "output": n(f"DisplayParameterOutput_{side}"),
                "upstream_critical_nodes": upstream,
            })
            for side in ("L", "R")
        ],
    ])
    edges.extend([Edge(n("IndependentMonitor_L"), n("DisplayGate_L"), "control"), Edge(n("IndependentMonitor_R"), n("DisplayGate_R"), "control")])
    relations.extend([
        Relation("sequence", {"source": f"{mn}.output", "target": f"{cc}.input"}),
        Relation("sequence", {"source": f"{cc}.output", "target": f"{im_l}.input"}),
        Relation("sequence", {"source": f"{cc}.output", "target": f"{im_r}.input"}),
    ])
    parallel_relations.append({
        "left_instance": im_l, "right_instance": im_r,
        "constrained_resources": ["PWR", "CPU", "CLK"], "resource_roles": ["monitor", "gate"],
    })


def _failure_semantics(unit_count: int) -> dict[str, Any]:
    """Clone the established Case-A and dual-display Case-B formulas by unit."""

    local: dict[str, dict[str, Any]] = {}
    transfers: list[dict[str, Any]] = []
    hierarchy: list[dict[str, Any]] = []
    top_events: dict[str, Any] = {}
    parallel_compositions: list[dict[str, Any]] = []
    for unit in range(1, unit_count + 1):
        rta, sr, psc = (f"RTA_FCC_{unit}", f"SR_FCC_{unit}", f"PSC_ACU_{unit}")
        mn, cc, im_l, im_r = (f"MN_Sensor_{unit}", f"CC_Nav_{unit}", f"IM_Display_L_{unit}", f"IM_Display_R_{unit}")
        tag = str(unit)
        local.update({
            sr: {"loss_output": {"and": [f"F_FCCA_LOF_{tag}", {"or": [f"F_FCCB_LOF_{tag}", f"F_fd_miss_{tag}", f"F_sw_fail_{tag}"]}]}},
            rta: {"hazardous_output": {"and": [f"F_adv_vio_{tag}", {"or": [f"F_mon_miss_{tag}", f"F_safe_fail_{tag}", f"F_sel_fail_{tag}"]}]}},
            psc: {
                "loss_output": {"or": [f"F_dp_perm_{tag}", {"and": [f"F_dp_trans_{tag}", f"F_recover_fail_{tag}"]}]},
                "hazardous_output": {"and": [f"F_dp_err_{tag}", f"F_am_miss_{tag}"]},
            },
            mn: {
                "output_hazard": {"or": [
                    {"and": [f"F_s1_err_{tag}", f"F_s2_err_{tag}"]},
                    {"and": [f"F_s1_err_{tag}", f"F_s3_err_{tag}"]},
                    {"and": [f"F_s2_err_{tag}", f"F_s3_err_{tag}"]}, f"F_voter_err_{tag}",
                ]},
                "output_loss": f"F_mn_output_loss_{tag}",
            },
            cc: {
                "output_hazard": {"or": [{"ref": f"{cc}.input_hazard"}, {"and": [f"F_nav_diff_{tag}", f"F_cmp_miss_{tag}"]}]},
                "trusted_output_loss": {"or": [{"ref": f"{cc}.input_loss"}, f"F_cc_output_loss_{tag}"]},
            },
            im_l: {
                "hazardous_display": {"and": [{"ref": f"{im_l}.input_hazard"}, f"F_im_l_miss_{tag}"]},
                "loss_trusted_display": {"or": [{"ref": f"{im_l}.input_loss"}, f"F_im_l_unavailable_{tag}"]},
            },
            im_r: {
                "hazardous_display": {"and": [{"ref": f"{im_r}.input_hazard"}, f"F_im_r_miss_{tag}"]},
                "loss_trusted_display": {"or": [{"ref": f"{im_r}.input_loss"}, f"F_im_r_unavailable_{tag}"]},
            },
        })
        transfers.extend([
            {"connection": {"source": f"{mn}.output", "target": f"{cc}.input"}, "source_event": f"{mn}.output_hazard", "target_event": f"{cc}.input_hazard"},
            {"connection": {"source": f"{mn}.output", "target": f"{cc}.input"}, "source_event": f"{mn}.output_loss", "target_event": f"{cc}.input_loss"},
            *[
                {"connection": {"source": f"{cc}.output", "target": f"{im}.input"}, "source_event": f"{cc}.output_hazard", "target_event": f"{im}.input_hazard"}
                for im in (im_l, im_r)
            ],
            *[
                {"connection": {"source": f"{cc}.output", "target": f"{im}.input"}, "source_event": f"{cc}.trusted_output_loss", "target_event": f"{im}.input_loss"}
                for im in (im_l, im_r)
            ],
        ])
        hierarchy.append({"hierarchy": {"child": rta, "parent": f"{sr}.primaryChannel"}, "source_event": f"{rta}.hazardous_output", "target_event": f"{sr}.primary_channel_hazard"})
        top_events.update({
            f"LossOfActuatorCommand_{unit}": {"or": [{"ref": f"{sr}.loss_output"}, {"ref": f"{psc}.loss_output"}]},
            f"HazardousActuatorCommand_{unit}": {"or": [{"ref": f"{sr}.primary_channel_hazard"}, {"ref": f"{psc}.hazardous_output"}]},
            f"HazardousParameterDisplayed_{unit}": {"or": [{"ref": f"{im_l}.hazardous_display"}, {"ref": f"{im_r}.hazardous_display"}]},
            f"LossOfTrustedParameterDisplay_{unit}": {"and": [{"ref": f"{im_l}.loss_trusted_display"}, {"ref": f"{im_r}.loss_trusted_display"}]},
        })
        parallel_compositions.append({
            "top_event": f"LossOfTrustedParameterDisplay_{unit}", "left_event": f"{im_l}.loss_trusted_display",
            "right_event": f"{im_r}.loss_trusted_display", "operator": "AND", "left_instance": im_l, "right_instance": im_r,
        })
    return {"local": local, "boundary_transfers": transfers, "hierarchy_substitutions": hierarchy, "top_events": top_events, "parallel_compositions": parallel_compositions}


def generate_mixed_architecture(unit_count: int, variant: str = "valid") -> Architecture:
    """Generate a deterministic ``K``-unit heterogeneous architecture in memory."""

    if unit_count < 1:
        raise ValueError("Mixed-unit count must be at least one")
    if variant not in VARIANTS:
        raise ValueError(f"Unknown scalability variant: {variant}")
    components: dict[str, Component] = {}
    interfaces: list[InterfaceDecl] = []
    patterns: list[PatternInstance] = []
    relations: list[Relation] = []
    edges: list[Edge] = []
    parallel_relations: list[dict[str, Any]] = []
    for unit in range(1, unit_count + 1):
        _add_flight_control_unit(unit, components, interfaces, patterns, relations, edges, variant == "controlled_failure" and unit == unit_count)
        _add_display_unit(unit, components, interfaces, patterns, relations, edges, parallel_relations)
    return Architecture(
        case_name=f"scalability_{variant}_K{unit_count}", components=components, interfaces=interfaces,
        patterns=patterns, relations=relations, edges=edges, parallel_relations=parallel_relations,
        failure_semantics=_failure_semantics(unit_count),
    )


def obligation_counts(obligations: Iterable[VerificationObligation]) -> dict[str, int]:
    mapping = {
        "local_contract": "local_obligation_count", "boundary_connection": "boundary_obligation_count",
        "hierarchical_refinement": "refinement_obligation_count", "context_overlap:shared_boundary": "overlap_obligation_count",
        "parallel_composition": "composition_obligation_count",
    }
    counts = {value: 0 for value in mapping.values()}
    obligations = list(obligations)
    for item in obligations:
        key = mapping.get(item.trace.trigger)
        if key is not None:
            counts[key] += 1
    counts["total_obligation_count"] = len(obligations)
    return counts


@dataclass
class MixedReport:
    case_name: str
    status: str
    stage: str
    context_objects: dict[str, list[str]]
    obligation_results: list[ObligationResult]
    instance_results: list[InstanceResult]
    combination_status: str
    failed_obligation: VerificationObligation | None = None
    counterexample: dict[str, str] | None = None
    failure_spec_status: str | None = None
    failure_analysis: dict[str, Any] | None = None


def timed_mixed_evaluation(arch: Architecture) -> tuple[MixedReport, dict[str, Any]]:
    """Run every required query, measuring only algorithmic phase boundaries."""

    total_start = perf_counter_ns()
    start = perf_counter_ns()
    context = ArchitectureContext(arch)
    context_objects = {pattern.id: sorted(context.context_objects(pattern)) for pattern in arch.patterns}
    context_extraction_ms = _ms(start, perf_counter_ns())
    instantiations = check_instantiations(arch)
    if any(
        item.instantiation_status != "VALID"
        for item in instantiations.values()
    ):
        raise AssertionError("Scalability generator produced invalid pattern instances")
    start = perf_counter_ns()
    obligations = build_obligations(context)
    counts = obligation_counts(obligations)
    obligation_generation_ms = _ms(start, perf_counter_ns())
    start = perf_counter_ns()
    consistent, core = _context_consistency(context)
    context_check_ms = _ms(start, perf_counter_ns())
    common_timing = {**counts, "context_extraction_ms": context_extraction_ms, "obligation_generation_ms": obligation_generation_ms, "context_check_ms": context_check_ms}
    if not consistent:
        raise AssertionError(f"Scalability generator produced inconsistent context: {core}")

    start = perf_counter_ns()
    results, instances, evidence, obligation_query_count = evaluate_obligations(
        context,
        obligations,
        instantiations,
    )
    obligation_check_ms = _ms(start, perf_counter_ns())
    start = perf_counter_ns()
    combination_status = aggregate_combination_status(instances, results)
    combination_aggregation_ms = _ms(start, perf_counter_ns())
    if combination_status != "ESTABLISHED":
        failed = next(
            (
                item
                for item in results
                if item.status
                in {
                    "PREMISE_CONTRADICTED",
                    "PREMISE_UNSUPPORTED",
                    "PREMISE_UNACCEPTABLE",
                    "OBLIGATION_FAILED",
                }
            ),
            None,
        )
        return MixedReport(
            arch.case_name,
            "COMBINATION_NOT_ESTABLISHED",
            "combination",
            context_objects,
            results,
            instances,
            combination_status,
            failed.obligation if failed else None,
            failed.counterexample if failed else None,
        ), {
            **common_timing,
            "obligation_check_ms": obligation_check_ms,
            "combination_aggregation_ms": combination_aggregation_ms,
            "failure_analysis_ms": None,
            "failure_analysis_skipped": True,
            "smt_query_count": 1 + obligation_query_count,
            "total_verification_ms": _ms(total_start, perf_counter_ns()),
        }

    spec_status, diagnostics = failure_spec_status(arch)
    start = perf_counter_ns()
    failure_analysis = (
        expand_failure_semantics(arch)
        if spec_status == "COMPLETE"
        else {
            "_spec": {
                "status": "FAILURE_SPEC_INCOMPLETE",
                "diagnostics": diagnostics,
            }
        }
    )
    failure_analysis_ms = _ms(start, perf_counter_ns())
    return MixedReport(
        arch.case_name,
        "ANALYSIS_COMPLETED",
        "failure_analysis",
        context_objects,
        results,
        instances,
        combination_status,
        failure_spec_status=spec_status,
        failure_analysis=failure_analysis,
    ), {
        **common_timing,
        "obligation_check_ms": obligation_check_ms,
        "combination_aggregation_ms": combination_aggregation_ms,
        "failure_analysis_ms": failure_analysis_ms,
        "failure_analysis_skipped": False,
        "smt_query_count": 1 + obligation_query_count,
        "total_verification_ms": _ms(total_start, perf_counter_ns()),
    }


def _memory_bytes() -> int | None:
    if os.name != "nt":
        return None
    try:
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus(); status.dwLength = ctypes.sizeof(MemoryStatus)
        return int(status.ullTotalPhys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else None
    except Exception:
        return None


def _cpu_model() -> str | None:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0])
        except Exception:
            pass
    return platform.processor() or None


def environment_info() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = None
    def parameter(name: str) -> Any:
        try:
            return get_param(name)
        except Exception:
            return None
    return {
        "operating_system": platform.platform() or None, "cpu_model": _cpu_model(), "logical_cpu_count": os.cpu_count(),
        "total_memory": _memory_bytes(), "python_version": sys.version, "z3_version": get_version_string(),
        "parallel_enabled": parameter("parallel.enable"), "smt_threads": parameter("smt.threads"), "project_commit": commit,
    }


def run_once(unit_count: int, variant: str) -> dict[str, Any]:
    start = perf_counter_ns()
    arch = generate_mixed_architecture(unit_count, variant)
    generation_ms = _ms(start, perf_counter_ns())
    report, timing = timed_mixed_evaluation(arch)
    top_events = report.failure_analysis or {}
    return {
        "K": unit_count, "variant": variant, "model_generation_ms": generation_ms, "model_loading_ms": 0.0,
        "architecture_object_count": len(arch.components), "pattern_type_count": len({item.kind for item in arch.patterns}),
        "pattern_instance_count": len(arch.patterns),
        "established_instance_count": sum(
            item.instance_status == "ESTABLISHED"
            for item in report.instance_results
        ),
        "combination_status": report.combination_status,
        "failure_spec_status": report.failure_spec_status,
        "top_event_count": len(top_events), "minimal_cut_set_count": sum(len(item.get("minimal_cut_sets", [])) for item in top_events.values()),
        "final_status": report.status, "failed_obligation_id": report.failed_obligation.id if report.failed_obligation else None,
        "failed_trace": {"trigger": report.failed_obligation.trace.trigger, "related_objects": list(report.failed_obligation.trace.related_objects)} if report.failed_obligation else None,
        **timing,
    }


def _summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if len(ordered) == 1:
        return {"median_ms": ordered[0], "min_ms": ordered[0], "max_ms": ordered[0], "q1_ms": ordered[0], "q3_ms": ordered[0]}
    q1, _, q3 = quantiles(ordered, n=4, method="inclusive")
    return {"median_ms": median(ordered), "min_ms": ordered[0], "max_ms": ordered[-1], "q1_ms": q1, "q3_ms": q3}


def summarise(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault((record["K"], record["variant"]), []).append(record)
    phase_keys = [
        "model_generation_ms",
        "model_loading_ms",
        "context_extraction_ms",
        "obligation_generation_ms",
        "context_check_ms",
        "obligation_check_ms",
        "combination_aggregation_ms",
        "failure_analysis_ms",
        "total_verification_ms",
    ]
    summaries = []
    for (size, variant), items in sorted(groups.items()):
        result = {"K": size, "variant": variant, "formal_run_count": len(items)}
        for key in (
            "architecture_object_count",
            "pattern_type_count",
            "pattern_instance_count",
            "established_instance_count",
            "combination_status",
            "failure_spec_status",
            "top_event_count",
            "minimal_cut_set_count",
            "local_obligation_count",
            "boundary_obligation_count",
            "refinement_obligation_count",
            "overlap_obligation_count",
            "composition_obligation_count",
            "total_obligation_count",
            "smt_query_count",
            "final_status",
            "failure_analysis_skipped",
        ):
            result[key] = items[0][key]
        for key in phase_keys:
            values = [float(item[key]) for item in items if item[key] is not None]
            if values:
                result.update({f"{key}_{stat}": value for stat, value in _summary(values).items()})
            else:
                result[f"{key}_median_ms"] = None
        result["formula_expected_total"] = 28 * size
        result["formula_matches_actual"] = result["formula_expected_total"] == result["total_obligation_count"]
        summaries.append(result)
    return summaries


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def write_plots(summary_rows: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    os.environ.setdefault("MPLCONFIGDIR", str(output_dir / ".matplotlib"))
    (output_dir / ".matplotlib").mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, axis = plt.subplots()
    for variant in VARIANTS:
        rows = [row for row in summary_rows if row["variant"] == variant]
        x = [row["K"] for row in rows]; y = [row["total_verification_ms_median_ms"] for row in rows]
        axis.plot(x, y, marker="o", label=variant)
        axis.fill_between(x, [row["total_verification_ms_q1_ms"] for row in rows], [row["total_verification_ms_q3_ms"] for row in rows], alpha=.2)
    axis.set(xlabel="mixed unit count (K)", ylabel="total verification time (ms)", title="Mixed architecture verification time")
    axis.legend(); axis.grid(True, alpha=.3)
    total_path = output_dir / "scalability_total_time.png"; fig.savefig(total_path, dpi=160, bbox_inches="tight"); plt.close(fig)

    fig, axis = plt.subplots()
    valid = [row for row in summary_rows if row["variant"] == "valid"]
    for field, label in (
        ("context_extraction_ms_median_ms", "context extraction"),
        ("obligation_generation_ms_median_ms", "obligation generation"),
        ("context_check_ms_median_ms", "context check"),
        ("obligation_check_ms_median_ms", "obligation check"),
        ("combination_aggregation_ms_median_ms", "combination aggregation"),
        ("failure_analysis_ms_median_ms", "failure expansion"),
    ):
        axis.plot([row["K"] for row in valid], [row[field] for row in valid], marker="o", label=label)
    axis.set(xlabel="mixed unit count (K)", ylabel="time (ms)", title="Valid configuration stage times")
    axis.legend(); axis.grid(True, alpha=.3)
    stage_path = output_dir / "scalability_stage_time.png"; fig.savefig(stage_path, dpi=160, bbox_inches="tight"); plt.close(fig)

    fig, axis = plt.subplots()
    sample = [row for row in summary_rows if row["variant"] == "valid"]
    for field, label in (("total_obligation_count", "total"), ("local_obligation_count", "local"), ("boundary_obligation_count", "boundary"), ("refinement_obligation_count", "refinement"), ("overlap_obligation_count", "overlap"), ("composition_obligation_count", "explicit composition")):
        axis.plot([row["K"] for row in sample], [row[field] for row in sample], marker="o", label=label)
    axis.set(xlabel="mixed unit count (K)", ylabel="obligation count", title="Verification-obligation growth")
    axis.legend(); axis.grid(True, alpha=.3)
    obligation_path = output_dir / "scalability_obligation_growth.png"; fig.savefig(obligation_path, dpi=160, bbox_inches="tight"); plt.close(fig)
    return [total_path, stage_path, obligation_path]
