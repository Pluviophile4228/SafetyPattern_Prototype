"""Reusable safety-pattern contracts for the layered establishment checker.

The legacy :mod:`src.rules` module is intentionally retained as the baseline.
This module gives the same pattern kinds an explicit assumption/guarantee
split, so a bound pattern can be checked in an architecture context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractClause:
    """One semantic clause, parameterised by pattern-role names."""

    id: str
    kind: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class PatternContract:
    """Instantiation roles and local premises for one pattern kind."""

    required_roles: tuple[str, ...]
    assumptions: tuple[ContractClause, ...]
    guarantees: tuple[ContractClause, ...]


@dataclass(frozen=True)
class PatternStructure:
    """Static structure that a role binding must embed into the architecture.

    ``role_types`` belongs to TypeOK.  ``distinct_role_groups`` and
    ``boundary_ports`` belong to Emb: they describe the identity and boundary
    placement of nodes inside one pattern instance.  Cross-instance
    connections, containment/refinement, overlap, and parallel independence
    deliberately do not appear here; those are relation obligations.
    """

    role_types: dict[str, tuple[str, ...]]
    distinct_role_groups: tuple[tuple[str, ...], ...]
    boundary_ports: dict[str, tuple[str, ...]]
    terminal_boundary_roles: tuple[str, ...] = ()


def structure_for(kind: str) -> PatternStructure:
    """Return the type and intra-instance embedding template for ``kind``."""

    if kind == "RTA":
        role_types = {
            "input": ("Input",),
            "feature_extractor": ("Processor",),
            "advanced_controller": ("Controller",),
            "primary_output": ("Output",),
            "safe_input_processor": ("Processor",),
            "safety_controller": ("Controller",),
            "safety_output": ("Output",),
            "safety_monitor": ("Monitor",),
            "command_selector": ("Selector",),
            "output": ("FCCCommand",),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={"output": ("output",)},
        )
    if kind == "SR":
        role_types = {
            "primary_channel": ("PrimaryChannel",),
            "standby_channel": ("StandbyChannel",),
            "fault_detector": ("FaultDetector",),
            "switching_unit": ("SwitchingUnit",),
            "primary_output": ("FCCCommand",),
            "standby_output": ("FCCCommand",),
            "output": ("FCCCommand",),
            "primary_critical_nodes": (
                "Controller",
                "Monitor",
                "Selector",
            ),
            "standby_critical_nodes": ("Controller",),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={
                "primary_output": ("primaryChannel.output",),
                "standby_output": ("standbyChannel.output",),
                "output": ("output",),
            },
        )
    if kind == "PSC":
        role_types = {
            "input": ("FCCCommand",),
            "acu_input": ("Input",),
            "actuator_control_processor": ("Processor",),
            "data_integrity_checker": ("Checker",),
            "anomaly_monitor": ("Monitor",),
            "output": ("ActuatorCommand",),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={"input": ("input",), "output": ("output",)},
            terminal_boundary_roles=("input", "output"),
        )
    if kind == "MN":
        role_types = {
            "inputChannels": ("Sensor",),
            "voter": ("Voter",),
            "output": ("FlightParameter",),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={"output": ("output",)},
        )
    if kind == "CC":
        role_types = {
            "input": ("FlightParameter",),
            "channelA": ("NavProcessor",),
            "channelB": ("NavProcessor",),
            "comparator": ("Comparator",),
            "output": ("CheckedParameter",),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={"input": ("input",), "output": ("output",)},
        )
    if kind == "IM":
        role_types = {
            "input": ("CheckedParameter",),
            "monitor": ("IndependentMonitor",),
            "gate": ("Gate",),
            "output": ("DisplayOutput",),
            "upstream_critical_nodes": ("NavProcessor", "Comparator"),
        }
        return PatternStructure(
            role_types=role_types,
            distinct_role_groups=(tuple(role_types),),
            boundary_ports={"input": ("input",), "output": ("output",)},
            terminal_boundary_roles=("output",),
        )
    return PatternStructure(
        role_types={},
        distinct_role_groups=(),
        boundary_ports={},
    )


def _guarantees() -> tuple[ContractClause, ...]:
    """Evidence released by an established instance.

    System-goal predicates used to be stored beside this boundary evidence.
    Only the boundary declaration remains because sequence and refinement
    obligations consume it.
    """

    return (
        ContractClause(
            id="OUTPUT_BOUNDARY_DECLARED",
            kind="boundary_declared",
            parameters={"role": "output"},
        ),
    )


def contract_for(kind: str) -> PatternContract:
    """Return the contract associated with one existing pattern kind.

    Clauses are role based; no case or concrete component name appears here.
    """

    if kind == "RTA":
        return PatternContract(
            required_roles=(
                "input",
                "feature_extractor",
                "advanced_controller",
                "primary_output",
                "safe_input_processor",
                "safety_controller",
                "safety_output",
                "safety_monitor",
                "command_selector",
                "output",
            ),
            assumptions=(
                ContractClause("DAL_A", "dal_equals", {"roles": ("safety_controller", "safety_monitor", "command_selector"), "value": "A"}),
                ContractClause("RESOURCE_INDEPENDENCE", "all_distinct_resources", {"roles": ("advanced_controller", "safety_controller", "safety_monitor"), "resources": ("PWR", "CLK", "SW", "CPU")}),
                ContractClause("CONTROL_PATH", "required_edge", {"source_role": "safety_monitor", "target_role": "command_selector", "edge_kind": "control"}),
            ),
            guarantees=_guarantees(),
        )
    if kind == "SR":
        return PatternContract(
            required_roles=(
                "primary_channel",
                "standby_channel",
                "fault_detector",
                "switching_unit",
                "primary_output",
                "standby_output",
                "output",
                "primary_critical_nodes",
                "standby_critical_nodes",
            ),
            assumptions=(
                ContractClause("PRIMARY_STANDBY_INDEPENDENCE", "cross_distinct_resources", {"left_role": "primary_critical_nodes", "right_role": "standby_critical_nodes", "resources": ("PWR", "CLK", "SW", "CPU")}),
                ContractClause("COMMAND_TYPE", "signal_type", {"roles": ("primary_output", "standby_output", "output"), "value": "FCCCommand"}),
                ContractClause("CONTROL_PATH", "required_edge", {"source_role": "fault_detector", "target_role": "switching_unit", "edge_kind": "control"}),
            ),
            guarantees=_guarantees(),
        )
    if kind == "PSC":
        return PatternContract(
            required_roles=(
                "input",
                "acu_input",
                "actuator_control_processor",
                "data_integrity_checker",
                "anomaly_monitor",
                "output",
            ),
            assumptions=(
                ContractClause("SINGLE_CHANNEL", "forbidden_roles_absent", {"roles": ("backup_channel", "standby_channel", "secondary_channel", "alternative_path")}),
                ContractClause("CPU_INDEPENDENCE", "cross_distinct_resources", {"left_role": "actuator_control_processor", "right_role": "data_integrity_checker", "resources": ("CPU",)}),
                ContractClause("MONITOR_CPU_INDEPENDENCE", "cross_distinct_resources", {"left_role": "actuator_control_processor", "right_role": "anomaly_monitor", "resources": ("CPU",)}),
            ),
            guarantees=_guarantees(),
        )
    if kind == "MN":
        return PatternContract(
            required_roles=("inputChannels", "voter", "output"),
            assumptions=(
                ContractClause("CHANNEL_INDEPENDENCE", "all_distinct_resources", {"roles": ("inputChannels",), "resources": ("PWR", "CLK", "CPU")}),
                ContractClause("VOTER_DAL", "dal_equals", {"roles": ("voter", "output"), "value": "A"}),
            ),
            guarantees=_guarantees(),
        )
    if kind == "CC":
        return PatternContract(
            required_roles=("input", "channelA", "channelB", "comparator", "output"),
            assumptions=(
                ContractClause("CHANNEL_INDEPENDENCE", "all_distinct_resources", {"roles": ("channelA", "channelB"), "resources": ("PWR", "CLK", "CPU")}),
                ContractClause("COMPARATOR_A_CPU", "cross_distinct_resources", {"left_role": "channelA", "right_role": "comparator", "resources": ("CPU",)}),
                ContractClause("COMPARATOR_B_CPU", "cross_distinct_resources", {"left_role": "channelB", "right_role": "comparator", "resources": ("CPU",)}),
            ),
            guarantees=_guarantees(),
        )
    if kind == "IM":
        return PatternContract(
            required_roles=("input", "monitor", "gate", "output", "upstream_critical_nodes"),
            assumptions=(
                ContractClause("MONITOR_INDEPENDENCE", "cross_distinct_resources", {"left_role": "monitor", "right_role": "upstream_critical_nodes", "resources": ("PWR", "CLK", "CPU")}),
                ContractClause("CONTROL_PATH", "required_edge", {"source_role": "monitor", "target_role": "gate", "edge_kind": "control"}),
            ),
            guarantees=_guarantees(),
        )
    return PatternContract(required_roles=(), assumptions=(), guarantees=())


KNOWN_PATTERN_KINDS = frozenset({"RTA", "SR", "PSC", "MN", "CC", "IM"})
