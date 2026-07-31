from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from .model import Architecture, CRITICAL_RESOURCE_KINDS, PatternInstance
from .smt_backend import (
    AssignedValue,
    check_all_distinct,
    check_all_equal,
    check_equal_to_required,
)


DAL_ORDER = {
    "A": 0,
    "B": 1,
    "C": 2,
    "D": 3,
    "E": 4,
}


CASEB_RESOURCE_KINDS = ("PWR", "CLK", "CPU")


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    rule_id: str
    message: str = ""
    rule_family: str = ""
    involved_elements: str = ""
    conflict_attribute: str = ""
    conflict_value: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    family: str
    description: str
    check_fn: Callable[[Architecture], RuleResult]

    def check(self, arch: Architecture) -> RuleResult:
        result = self.check_fn(arch)
        if result.rule_family:
            return result
        return replace(result, rule_family=self.family)


def ok(rule_id: str) -> RuleResult:
    return RuleResult(passed=True, rule_id=rule_id)


def fail(
    rule_id: str,
    message: str,
    involved_elements: str = "",
    conflict_attribute: str = "",
    conflict_value: str = "",
) -> RuleResult:
    return RuleResult(
        passed=False,
        rule_id=rule_id,
        message=message,
        involved_elements=involved_elements,
        conflict_attribute=conflict_attribute,
        conflict_value=conflict_value,
    )


def dal_at_least(actual: str | None, required: str) -> bool:
    if actual is None:
        return False
    return DAL_ORDER.get(actual, 999) <= DAL_ORDER[required]


def _valid_resource(value: str | None) -> bool:
    return value not in (None, "", "None", "null")


def _required_role(pattern: PatternInstance, role_name: str) -> str:
    value = pattern.roles.get(role_name)
    if not isinstance(value, str):
        raise ValueError(f"{pattern.id}.{role_name} must be a component or signal name")
    return value


def _role_list(pattern: PatternInstance, role_name: str) -> list[str]:
    value = pattern.roles.get(role_name, [])
    if not isinstance(value, list):
        raise ValueError(f"{pattern.id}.{role_name} must be a list")
    return [str(item) for item in value]

def _pattern_by_id(arch: Architecture, pattern_id: str) -> PatternInstance | None:
    for pattern in arch.patterns:
        if pattern.id == pattern_id:
            return pattern
    return None


def _split_endpoint(endpoint: str) -> tuple[str, str]:
    if "." not in endpoint:
        raise ValueError(f"Invalid endpoint: {endpoint}")

    pattern_id, role_name = endpoint.split(".", 1)
    return pattern_id, role_name


def _endpoint_signal(arch: Architecture, endpoint: str) -> str:
    pattern_id, role_name = _split_endpoint(endpoint)
    pattern = _pattern_by_id(arch, pattern_id)

    if pattern is None:
        raise ValueError(f"Unknown pattern endpoint: {endpoint}")

    return _required_role(pattern, role_name)


def _has_interface_declaration(
    arch: Architecture,
    signal: str,
    owner: str,
    port: str,
) -> bool:
    return any(
        decl.signal == signal and decl.owner == owner and decl.port == port
        for decl in arch.interfaces
    )


def _expected_sequence_relations(arch: Architecture) -> list[tuple[str, str]]:
    """
    Keep this lightweight. Existing declared sequence relations are checked,
    and Case A / Case B expected sequence links are also checked so that
    accidental deletion of the sequence relation can be detected.
    """
    expected: list[tuple[str, str]] = []

    for relation in arch.relations:
        if relation.kind == "sequence":
            source = relation.attributes.get("source")
            target = relation.attributes.get("target")
            if isinstance(source, str) and isinstance(target, str):
                expected.append((source, target))

    pattern_ids = {pattern.id for pattern in arch.patterns}

    if {"SR_FCC", "PSC_ACU"}.issubset(pattern_ids):
        expected.append(("SR_FCC.output", "PSC_ACU.input"))

    if {"MN_Sensor", "CC_Nav"}.issubset(pattern_ids):
        expected.append(("MN_Sensor.output", "CC_Nav.input"))

    if {"CC_Nav", "IM_Display"}.issubset(pattern_ids):
        expected.append(("CC_Nav.output", "IM_Display.input"))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in expected:
        if item not in seen:
            deduped.append(item)
            seen.add(item)

    return deduped

def _find_shared_resource(
    arch: Architecture,
    node_names: list[str],
    resource_kind: str,
) -> tuple[str, list[str]] | None:
    nodes_by_resource: dict[str, list[str]] = {}

    for node_name in node_names:
        value = arch.component(node_name).resource(resource_kind)
        if not _valid_resource(value):
            continue

        nodes_by_resource.setdefault(str(value), []).append(node_name)

    for value, names in nodes_by_resource.items():
        if len(names) > 1:
            return value, names

    return None


# -----------------------------
# Generic interface rules
# -----------------------------

def check_shared_interface_type_consistency(arch: Architecture) -> RuleResult:
    rule_id = "INTERFACE_TYPE_CONSISTENCY"

    signals = sorted({decl.signal for decl in arch.interfaces})

    for signal in signals:
        declarations = arch.interfaces_for_signal(signal)
        assignments = [
            AssignedValue(f"{decl.owner}_{decl.port}_{signal}_Type", decl.type)
            for decl in declarations
        ]

        if not check_all_equal(assignments):
            type_values = {decl.type for decl in declarations}
            locations = ", ".join(
                f"{decl.owner}.{decl.port}:Type={decl.type}"
                for decl in declarations
            )
            return fail(
                rule_id,
                f"{signal} has inconsistent Type declarations: {locations}",
                involved_elements=signal,
                conflict_attribute="Type",
                conflict_value=";".join(sorted(type_values)),
            )

    return ok(rule_id)

def check_data_path_consistency(arch: Architecture) -> RuleResult:
    rule_id = "DATA_PATH_CONSISTENCY"

    for source_endpoint, target_endpoint in _expected_sequence_relations(arch):
        source_pattern_id, source_role = _split_endpoint(source_endpoint)
        target_pattern_id, target_role = _split_endpoint(target_endpoint)

        source_signal = _endpoint_signal(arch, source_endpoint)
        target_signal = _endpoint_signal(arch, target_endpoint)

        if source_signal != target_signal:
            return fail(
                rule_id,
                f"{source_endpoint} is bound to {source_signal}, but "
                f"{target_endpoint} is bound to {target_signal}",
                involved_elements=f"{source_signal}; {target_endpoint}",
                conflict_attribute="DATA_PATH",
                conflict_value=f"{source_signal}!={target_signal}",
            )

        if not _has_interface_declaration(
            arch,
            source_signal,
            source_pattern_id,
            source_role,
        ):
            return fail(
                rule_id,
                f"Missing interface declaration for {source_pattern_id}.{source_role} "
                f"with signal {source_signal}",
                involved_elements=f"{source_signal}; {source_endpoint}",
                conflict_attribute="DATA_PATH",
                conflict_value="MISSING_SOURCE_INTERFACE",
            )

        if not _has_interface_declaration(
            arch,
            target_signal,
            target_pattern_id,
            target_role,
        ):
            return fail(
                rule_id,
                f"Missing interface declaration for {target_pattern_id}.{target_role} "
                f"with signal {target_signal}",
                involved_elements=f"{source_signal}; {target_endpoint}",
                conflict_attribute="DATA_PATH",
                conflict_value="MISSING_TARGET_INTERFACE",
            )

    return ok(rule_id)


def check_control_path_consistency(arch: Architecture) -> RuleResult:
    rule_id = "CONTROL_PATH_CONSISTENCY"

    for pattern in arch.patterns_by_kind("RTA"):
        source = _required_role(pattern, "safety_monitor")
        target = _required_role(pattern, "command_selector")

        if not arch.has_edge(source, target, "control"):
            return fail(
                rule_id,
                f"{pattern.id}: missing control edge {source} -> {target}",
                involved_elements=f"{source}; {target}",
                conflict_attribute="CONTROL_PATH",
                conflict_value="MISSING_CONTROL_EDGE",
            )

    for pattern in arch.patterns_by_kind("SR"):
        source = _required_role(pattern, "fault_detector")
        target = _required_role(pattern, "switching_unit")

        if not arch.has_edge(source, target, "control"):
            return fail(
                rule_id,
                f"{pattern.id}: missing control edge {source} -> {target}",
                involved_elements=f"{source}; {target}",
                conflict_attribute="CONTROL_PATH",
                conflict_value="MISSING_CONTROL_EDGE",
            )

    for pattern in arch.patterns_by_kind("IM"):
        source = _required_role(pattern, "monitor")
        target = _required_role(pattern, "gate")

        if not arch.has_edge(source, target, "control"):
            return fail(
                rule_id,
                f"{pattern.id}: missing control edge {source} -> {target}",
                involved_elements=f"{source}; {target}",
                conflict_attribute="CONTROL_PATH",
                conflict_value="MISSING_CONTROL_EDGE",
            )

    return ok(rule_id)

def check_shared_interface_dal_consistency(arch: Architecture) -> RuleResult:
    rule_id = "INTERFACE_DAL_CONSISTENCY"

    signals = sorted({decl.signal for decl in arch.interfaces})

    for signal in signals:
        declarations = arch.interfaces_for_signal(signal)
        assignments = [
            AssignedValue(f"{decl.owner}_{decl.port}_{signal}_DAL", decl.dal)
            for decl in declarations
        ]

        if not check_all_equal(assignments):
            dal_values = {decl.dal for decl in declarations}
            locations = ", ".join(
                f"{decl.owner}.{decl.port}:DAL={decl.dal}"
                for decl in declarations
            )
            return fail(
                rule_id,
                f"{signal} has inconsistent DAL declarations: {locations}",
                involved_elements=signal,
                conflict_attribute="DAL",
                conflict_value=";".join(sorted(dal_values)),
            )

    return ok(rule_id)


# -----------------------------
# Case A patterns: RTA / SR / PSC
# -----------------------------

def check_rta_dal_requirement(arch: Architecture) -> RuleResult:
    rule_id = "RTA_DAL_REQUIREMENT"

    for pattern in arch.patterns_by_kind("RTA"):
        for role_name in ("safety_controller", "safety_monitor", "command_selector"):
            component_name = _required_role(pattern, role_name)
            component = arch.component(component_name)

            if not check_equal_to_required(
                f"{pattern.id}_{component_name}_DAL",
                component.dal,
                "A",
            ):
                return fail(
                    rule_id,
                    f"{pattern.id}.{role_name} maps to {component_name}, "
                    f"whose DAL is {component.dal}; required DAL A",
                    involved_elements=component_name,
                    conflict_attribute="DAL",
                    conflict_value=str(component.dal),
                )

    return ok(rule_id)


def check_rta_resource_independence(arch: Architecture) -> RuleResult:
    rule_id = "RTA_RESOURCE_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("RTA"):
        critical_roles = (
            "advanced_controller",
            "safety_controller",
            "safety_monitor",
        )
        critical_nodes = [_required_role(pattern, role) for role in critical_roles]

        for resource_kind in CRITICAL_RESOURCE_KINDS:
            assignments = [
                AssignedValue(
                    f"{pattern.id}_{node_name}_{resource_kind}",
                    arch.component(node_name).resource(resource_kind),
                )
                for node_name in critical_nodes
            ]

            if not check_all_distinct(assignments):
                shared = _find_shared_resource(arch, critical_nodes, resource_kind)
                if shared is None:
                    return fail(rule_id, f"{pattern.id}: resource conflict detected")

                resource_value, node_names = shared
                involved = ";".join(node_names)

                return fail(
                    rule_id,
                    f"{pattern.id}: RTA critical nodes {involved} share "
                    f"{resource_kind}={resource_value}",
                    involved_elements=involved,
                    conflict_attribute=resource_kind,
                    conflict_value=resource_value,
                )

    return ok(rule_id)


def check_sr_primary_standby_independence(arch: Architecture) -> RuleResult:
    rule_id = "SR_PRIMARY_STANDBY_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("SR"):
        primary_channel = _required_role(pattern, "primary_channel")
        standby_channel = _required_role(pattern, "standby_channel")

        primary_nodes = _role_list(pattern, "primary_critical_nodes")
        standby_nodes = _role_list(pattern, "standby_critical_nodes")

        for primary_name in primary_nodes:
            primary = arch.component(primary_name)

            for standby_name in standby_nodes:
                standby = arch.component(standby_name)

                for resource_kind in CRITICAL_RESOURCE_KINDS:
                    primary_value = primary.resource(resource_kind)
                    standby_value = standby.resource(resource_kind)

                    assignments = [
                        AssignedValue(
                            f"{pattern.id}_{primary_name}_{resource_kind}",
                            primary_value,
                        ),
                        AssignedValue(
                            f"{pattern.id}_{standby_name}_{resource_kind}",
                            standby_value,
                        ),
                    ]

                    if not check_all_distinct(assignments):
                        involved = (
                            f"{primary_channel}({primary_name});"
                            f"{standby_channel}({standby_name})"
                        )
                        return fail(
                            rule_id,
                            f"{primary_channel}({primary_name}) and "
                            f"{standby_channel}({standby_name}) share "
                            f"{resource_kind}={primary_value}",
                            involved_elements=involved,
                            conflict_attribute=resource_kind,
                            conflict_value=str(primary_value),
                        )

    return ok(rule_id)


def check_sr_interface_type_consistency(arch: Architecture) -> RuleResult:
    rule_id = "SR_INTERFACE_TYPE_CONSISTENCY"

    for pattern in arch.patterns_by_kind("SR"):
        signal_roles = ("primary_output", "standby_output", "output")

        for role_name in signal_roles:
            signal = _required_role(pattern, role_name)
            declarations = arch.interfaces_for_signal(signal)

            if not declarations:
                return fail(
                    rule_id,
                    f"{pattern.id}.{role_name} signal {signal} has no interface declaration",
                    involved_elements=signal,
                    conflict_attribute="Type",
                    conflict_value="MISSING",
                )

            for decl in declarations:
                if decl.type != "FCCCommand":
                    return fail(
                        rule_id,
                        f"{signal} is declared as Type={decl.type} in {decl.owner}.{decl.port}; "
                        f"required FCCCommand",
                        involved_elements=signal,
                        conflict_attribute="Type",
                        conflict_value=decl.type,
                    )

    return ok(rule_id)


def check_psc_single_channel_declaration(arch: Architecture) -> RuleResult:
    rule_id = "PSC_SINGLE_CHANNEL_DECLARATION"

    forbidden_roles = {
        "backup_channel",
        "standby_channel",
        "secondary_channel",
        "alternative_path",
    }

    for pattern in arch.patterns_by_kind("PSC"):
        used_forbidden_roles = sorted(forbidden_roles.intersection(pattern.roles.keys()))
        if used_forbidden_roles:
            return fail(
                rule_id,
                f"{pattern.id} declares alternative execution roles: "
                f"{', '.join(used_forbidden_roles)}",
                involved_elements=pattern.id,
                conflict_attribute="role",
                conflict_value=";".join(used_forbidden_roles),
            )

    return ok(rule_id)


def check_psc_cpu_independence(arch: Architecture) -> RuleResult:
    rule_id = "PSC_CPU_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("PSC"):
        pairs = (
            ("actuator_control_processor", "data_integrity_checker"),
            ("actuator_control_processor", "anomaly_monitor"),
        )

        for left_role, right_role in pairs:
            left_name = _required_role(pattern, left_role)
            right_name = _required_role(pattern, right_role)

            left_cpu = arch.component(left_name).resource("CPU")
            right_cpu = arch.component(right_name).resource("CPU")

            assignments = [
                AssignedValue(f"{pattern.id}_{left_name}_CPU", left_cpu),
                AssignedValue(f"{pattern.id}_{right_name}_CPU", right_cpu),
            ]

            if not check_all_distinct(assignments):
                return fail(
                    rule_id,
                    f"{pattern.id}: {left_name} and {right_name} share CPU={left_cpu}",
                    involved_elements=f"{left_name};{right_name}",
                    conflict_attribute="CPU",
                    conflict_value=str(left_cpu),
                )

    return ok(rule_id)


# -----------------------------
# Case B patterns: MN / CC / IM
# -----------------------------

def check_mn_channel_resource_independence(arch: Architecture) -> RuleResult:
    rule_id = "MN_CHANNEL_RESOURCE_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("MN"):
        channels = _role_list(pattern, "inputChannels")

        for resource_kind in CASEB_RESOURCE_KINDS:
            assignments = [
                AssignedValue(
                    f"{pattern.id}_{node_name}_{resource_kind}",
                    arch.component(node_name).resource(resource_kind),
                )
                for node_name in channels
            ]

            if not check_all_distinct(assignments):
                shared = _find_shared_resource(arch, channels, resource_kind)
                if shared is None:
                    return fail(rule_id, f"{pattern.id}: resource conflict detected")

                value, node_names = shared
                involved = ";".join(node_names)

                return fail(
                    rule_id,
                    f"{pattern.id}: MN input channels {involved} share "
                    f"{resource_kind}={value}",
                    involved_elements=involved,
                    conflict_attribute=resource_kind,
                    conflict_value=value,
                )

    return ok(rule_id)


def check_mn_voter_dal_consistency(arch: Architecture) -> RuleResult:
    rule_id = "MN_VOTER_DAL_CONSISTENCY"

    for pattern in arch.patterns_by_kind("MN"):
        voter_name = _required_role(pattern, "voter")
        output_name = _required_role(pattern, "output")

        voter = arch.component(voter_name)
        output = arch.component(output_name)

        if not check_equal_to_required(f"{pattern.id}_{voter_name}_DAL", voter.dal, "A"):
            return fail(
                rule_id,
                f"{pattern.id}: {voter_name}.DAL={voter.dal}; required DAL A",
                involved_elements=voter_name,
                conflict_attribute="DAL",
                conflict_value=str(voter.dal),
            )

        if not check_equal_to_required(f"{pattern.id}_{output_name}_DAL", output.dal, "A"):
            return fail(
                rule_id,
                f"{pattern.id}: {output_name}.DAL={output.dal}; required DAL A",
                involved_elements=output_name,
                conflict_attribute="DAL",
                conflict_value=str(output.dal),
            )

    return ok(rule_id)


def check_cc_comparator_independence(arch: Architecture) -> RuleResult:
    rule_id = "CC_COMPARATOR_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("CC"):
        channel_a_name = _required_role(pattern, "channelA")
        channel_b_name = _required_role(pattern, "channelB")
        comparator_name = _required_role(pattern, "comparator")

        channel_a = arch.component(channel_a_name)
        channel_b = arch.component(channel_b_name)
        comparator = arch.component(comparator_name)

        for resource_kind in CASEB_RESOURCE_KINDS:
            value_a = channel_a.resource(resource_kind)
            value_b = channel_b.resource(resource_kind)

            assignments = [
                AssignedValue(f"{pattern.id}_{channel_a_name}_{resource_kind}", value_a),
                AssignedValue(f"{pattern.id}_{channel_b_name}_{resource_kind}", value_b),
            ]

            if not check_all_distinct(assignments):
                return fail(
                    rule_id,
                    f"{pattern.id}: {channel_a_name} and {channel_b_name} share "
                    f"{resource_kind}={value_a}",
                    involved_elements=f"{channel_a_name};{channel_b_name}",
                    conflict_attribute=resource_kind,
                    conflict_value=str(value_a),
                )

        for node_name, node in (
            (channel_a_name, channel_a),
            (channel_b_name, channel_b),
        ):
            node_cpu = node.resource("CPU")
            comparator_cpu = comparator.resource("CPU")

            assignments = [
                AssignedValue(f"{pattern.id}_{node_name}_CPU", node_cpu),
                AssignedValue(f"{pattern.id}_{comparator_name}_CPU", comparator_cpu),
            ]

            if not check_all_distinct(assignments):
                return fail(
                    rule_id,
                    f"{pattern.id}: {comparator_name} and {node_name} share CPU={node_cpu}",
                    involved_elements=f"{comparator_name};{node_name}",
                    conflict_attribute="CPU",
                    conflict_value=str(node_cpu),
                )

    return ok(rule_id)


def check_im_monitor_independence(arch: Architecture) -> RuleResult:
    rule_id = "IM_MONITOR_INDEPENDENCE"

    for pattern in arch.patterns_by_kind("IM"):
        monitor_name = _required_role(pattern, "monitor")
        upstream_nodes = _role_list(pattern, "upstream_critical_nodes")

        monitor = arch.component(monitor_name)

        for upstream_name in upstream_nodes:
            upstream = arch.component(upstream_name)

            for resource_kind in CASEB_RESOURCE_KINDS:
                monitor_value = monitor.resource(resource_kind)
                upstream_value = upstream.resource(resource_kind)

                assignments = [
                    AssignedValue(f"{pattern.id}_{monitor_name}_{resource_kind}", monitor_value),
                    AssignedValue(f"{pattern.id}_{upstream_name}_{resource_kind}", upstream_value),
                ]

                if not check_all_distinct(assignments):
                    return fail(
                        rule_id,
                        f"{pattern.id}: {monitor_name} and upstream node {upstream_name} "
                        f"share {resource_kind}={monitor_value}",
                        involved_elements=f"{monitor_name};{upstream_name}",
                        conflict_attribute=resource_kind,
                        conflict_value=str(monitor_value),
                    )

    return ok(rule_id)


# -----------------------------
# Rule sets
# -----------------------------

def caseA_rules() -> list[Rule]:
    return [
        Rule(
            id="RTA_DAL_REQUIREMENT",
            family="RTA",
            description="SafetyController, SafetyMonitor and CommandSelector shall be DAL A.",
            check_fn=check_rta_dal_requirement,
        ),
        Rule(
            id="RTA_RESOURCE_INDEPENDENCE",
            family="RTA",
            description="RTA critical nodes shall not share PWR, CLK, SW or CPU.",
            check_fn=check_rta_resource_independence,
        ),
        Rule(
            id="SR_PRIMARY_STANDBY_INDEPENDENCE",
            family="SR",
            description="SR primary and standby channels shall be resource independent.",
            check_fn=check_sr_primary_standby_independence,
        ),
        Rule(
            id="SR_INTERFACE_TYPE_CONSISTENCY",
            family="SR",
            description="SR command signals shall keep Type=FCCCommand.",
            check_fn=check_sr_interface_type_consistency,
        ),
        Rule(
            id="PSC_SINGLE_CHANNEL_DECLARATION",
            family="PSC",
            description="PSC shall not declare an alternative execution path.",
            check_fn=check_psc_single_channel_declaration,
        ),
        Rule(
            id="PSC_CPU_INDEPENDENCE",
            family="PSC",
            description="PSC checking and monitoring nodes shall not share CPU with actuator processor.",
            check_fn=check_psc_cpu_independence,
        ),
        Rule(
            id="INTERFACE_TYPE_CONSISTENCY",
            family="Interface",
            description="Shared interfaces shall keep consistent Type declarations.",
            check_fn=check_shared_interface_type_consistency,
        ),
        Rule(
            id="INTERFACE_DAL_CONSISTENCY",
            family="Interface",
            description="Shared interfaces shall keep consistent DAL declarations.",
            check_fn=check_shared_interface_dal_consistency,
        ),
        Rule(
            id="DATA_PATH_CONSISTENCY",
            family="Topology",
            description="Sequentially connected patterns shall share the same output-input interface.",
            check_fn=check_data_path_consistency,
        ),
        Rule(
            id="CONTROL_PATH_CONSISTENCY",
            family="Topology",
            description="Monitor or detector nodes shall drive the corresponding selector, switching or gate node.",
            check_fn=check_control_path_consistency,
        ),
    ]


def caseB_rules() -> list[Rule]:
    return [
        Rule(
            id="MN_CHANNEL_RESOURCE_INDEPENDENCE",
            family="MN",
            description="MN input channels shall not share PWR, CLK or CPU.",
            check_fn=check_mn_channel_resource_independence,
        ),
        Rule(
            id="MN_VOTER_DAL_CONSISTENCY",
            family="MN",
            description="MN voter and voted output shall remain DAL A.",
            check_fn=check_mn_voter_dal_consistency,
        ),
        Rule(
            id="CC_COMPARATOR_INDEPENDENCE",
            family="CC",
            description="CC processing channels shall be independent and comparator shall not share CPU with either channel.",
            check_fn=check_cc_comparator_independence,
        ),
        Rule(
            id="IM_MONITOR_INDEPENDENCE",
            family="IM",
            description="IM monitor shall be resource independent from upstream monitored chain.",
            check_fn=check_im_monitor_independence,
        ),
        Rule(
            id="INTERFACE_TYPE_CONSISTENCY",
            family="Interface",
            description="Shared interfaces shall keep consistent Type declarations.",
            check_fn=check_shared_interface_type_consistency,
        ),
        Rule(
            id="INTERFACE_DAL_CONSISTENCY",
            family="Interface",
            description="Shared interfaces shall keep consistent DAL declarations.",
            check_fn=check_shared_interface_dal_consistency,
        ),
        Rule(
            id="DATA_PATH_CONSISTENCY",
            family="Topology",
            description="Sequentially connected patterns shall share the same output-input interface.",
            check_fn=check_data_path_consistency,
        ),
        Rule(
            id="CONTROL_PATH_CONSISTENCY",
            family="Topology",
            description="Monitor or detector nodes shall drive the corresponding selector, switching or gate node.",
            check_fn=check_control_path_consistency,
        ),
    ]


def all_rules() -> list[Rule]:
    """
    Kept for backward compatibility with the earlier Case A runner.
    """
    return caseA_rules()