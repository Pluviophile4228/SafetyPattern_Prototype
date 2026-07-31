"""Layered safety-pattern establishment and qualitative failure analysis.

This is intentionally separate from ``src.rules``: the latter is the
preserved baseline implementation, while this module implements the new
context -> instance -> composition -> failure-expansion workflow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from z3 import And, Bool, BoolRef, BoolVal, Distinct, Int, Not, Solver, is_true, sat

from .model import Architecture, PatternInstance
from .pattern_contracts import (
    KNOWN_PATTERN_KINDS,
    ContractClause,
    PatternContract,
    contract_for,
    structure_for,
)
from .smt_backend import FiniteDomainEncoder, _safe_var_name
from .failure_expansion import expand_failure_semantics, failure_spec_status


def _valid(value: str | None) -> bool:
    return value not in (None, "", "None", "null")


def _normalise_role(name: str) -> str:
    """Accept legacy camelCase endpoints as well as snake_case role names."""

    return "".join(char.lower() for char in name if char.isalnum())


def _endpoint(endpoint: str) -> tuple[str, str]:
    if "." not in endpoint:
        raise ValueError(f"Invalid pattern endpoint: {endpoint}")
    return tuple(endpoint.split(".", 1))  # type: ignore[return-value]


def _pattern_by_id(arch: Architecture, pattern_id: str) -> PatternInstance | None:
    return next((pattern for pattern in arch.patterns if pattern.id == pattern_id), None)


def _role_value(pattern: PatternInstance, role_name: str) -> Any:
    wanted = _normalise_role(role_name)
    for actual, value in pattern.roles.items():
        if _normalise_role(actual) == wanted:
            return value
    raise KeyError(f"{pattern.id} has no role named {role_name}")


def _as_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


@dataclass(frozen=True)
class NamedFact:
    id: str
    key: str
    value: str
    formula: BoolRef


@dataclass(frozen=True)
class Predicate:
    text: str
    formula: BoolRef


@dataclass(frozen=True)
class ObligationTrace:
    source_pattern: str | None
    target_pattern: str | None
    related_objects: tuple[str, ...]
    trigger: str
    resource_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationObligation:
    id: str
    premise: Predicate
    conclusion: Predicate
    trace: ObligationTrace
    dependencies: tuple[str, ...] = ()
    conclusion_evidence: str | None = None


@dataclass(frozen=True)
class ObligationResult:
    obligation: VerificationObligation
    status: str
    counterexample: dict[str, str] | None = None
    blocked_by: tuple[str, ...] = ()


@dataclass
class InstanceResult:
    pattern_id: str
    type_status: str
    type_diagnostics: list[str]
    embedding_status: str
    embedding_diagnostics: list[str]
    instantiation_status: str
    instantiation_diagnostics: list[str]
    context_status: str
    local_premise_results: list[ObligationResult]
    instance_status: str
    released_evidence: list[str]


@dataclass(frozen=True)
class InstantiationCheck:
    """Separate TypeOK and Emb results for one concrete pattern binding."""

    pattern_id: str
    type_status: str
    type_diagnostics: tuple[str, ...]
    embedding_status: str
    embedding_diagnostics: tuple[str, ...]

    @property
    def instantiation_status(self) -> str:
        if self.type_status == "TYPE_OK" and self.embedding_status == "EMBEDDED":
            return "VALID"
        return "INVALID"

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return self.type_diagnostics + self.embedding_diagnostics


@dataclass
class LayeredReport:
    case_name: str
    status: str
    stage: str
    obligation_count: int
    context_objects: dict[str, list[str]]
    unsat_core: list[str]
    obligation_results: list[ObligationResult]
    instance_results: list[InstanceResult]
    combination_status: str
    failure_spec_status: str | None = None
    smt_query_count: int = 0
    failed_obligation: VerificationObligation | None = None
    counterexample: dict[str, str] | None = None
    available_evidence: list[str] | None = None
    failure_analysis: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        def render_obligation(obligation: VerificationObligation) -> dict[str, Any]:
            return {
                "id": obligation.id,
                "premise": obligation.premise.text,
                "conclusion": obligation.conclusion.text,
                "trace": asdict(obligation.trace),
                "dependencies": list(obligation.dependencies),
                "conclusion_evidence": obligation.conclusion_evidence,
            }

        return {
            "case_name": self.case_name,
            "status": self.status,
            "stage": self.stage,
            "obligation_count": self.obligation_count,
            "context_objects": self.context_objects,
            "unsat_core": self.unsat_core,
            "instance_results": [
                {
                    "pattern_id": item.pattern_id,
                    "type_status": item.type_status,
                    "type_diagnostics": item.type_diagnostics,
                    "embedding_status": item.embedding_status,
                    "embedding_diagnostics": item.embedding_diagnostics,
                    "instantiation_status": item.instantiation_status,
                    "instantiation_diagnostics": item.instantiation_diagnostics,
                    "context_status": item.context_status,
                    "local_premise_results": [
                        {
                            "id": result.obligation.id,
                            "status": result.status,
                            "counterexample": result.counterexample,
                            "blocked_by": list(result.blocked_by),
                        }
                        for result in item.local_premise_results
                    ],
                    "instance_status": item.instance_status,
                    "released_evidence": item.released_evidence,
                }
                for item in self.instance_results
            ],
            "combination_status": self.combination_status,
            "failure_spec_status": self.failure_spec_status,
            "smt_query_count": self.smt_query_count,
            "obligation_results": [
                {
                    **render_obligation(item.obligation),
                    "status": item.status,
                    "counterexample": item.counterexample,
                    "blocked_by": list(item.blocked_by),
                }
                for item in self.obligation_results
            ],
            "failed_obligation": (
                render_obligation(self.failed_obligation)
                if self.failed_obligation is not None
                else None
            ),
            "counterexample": self.counterexample,
            "available_evidence": self.available_evidence,
            "failure_analysis": self.failure_analysis,
        }


class ArchitectureContext:
    """Finite SMT view of the architecture facts relevant to bound patterns."""

    def __init__(self, arch: Architecture) -> None:
        self.arch = arch
        self.encoder = FiniteDomainEncoder()
        self.variables: dict[str, Any] = {}
        self.facts: list[NamedFact] = []
        self._formula_cache: BoolRef | None = None
        self._direct_children = self._containment_children()
        self._add_declared_facts()
        self._add_context_assertions()

    def _variable(self, key: str):
        if key not in self.variables:
            self.variables[key] = Int(_safe_var_name(key))
        return self.variables[key]

    def _add_fact(self, fact_id: str, key: str, value: str | None) -> None:
        if not _valid(value):
            return
        text = str(value)
        var = self._variable(key)
        self.facts.append(
            NamedFact(
                id=fact_id,
                key=key,
                value=text,
                formula=var == self.encoder.value_id(text),
            )
        )

    def _add_declared_facts(self) -> None:
        for component in self.arch.components.values():
            self._add_fact(f"component:{component.name}:type", f"component.{component.name}.type", component.type)
            self._add_fact(f"component:{component.name}:dal", f"component.{component.name}.dal", component.dal)
            for resource, value in component.resources.items():
                self._add_fact(
                    f"component:{component.name}:resource:{resource}",
                    f"component.{component.name}.resource.{resource}",
                    value,
                )
        for index, declaration in enumerate(self.arch.interfaces):
            prefix = f"interface.{index}"
            for attribute in ("signal", "owner", "port", "type", "dal"):
                self._add_fact(
                    f"interface:{index}:{attribute}",
                    f"{prefix}.{attribute}",
                    str(getattr(declaration, attribute)),
                )

    def _add_context_assertions(self) -> None:
        for index, assertion in enumerate(self.arch.context_assertions):
            subject = str(assertion["subject"])
            attribute = str(assertion["attribute"])
            value = str(assertion["value"])
            fact_id = str(assertion.get("id", f"context_assertion:{index}"))
            if attribute.startswith("resource:"):
                resource = attribute.split(":", 1)[1]
                key = f"component.{subject}.resource.{resource}"
            else:
                key = f"component.{subject}.{attribute}"
            self._add_fact(fact_id, key, value)

    def _containment_children(self) -> dict[str, set[str]]:
        children: dict[str, set[str]] = {}
        for relation in self.arch.relations:
            if relation.kind != "contains":
                continue
            parent_endpoint = relation.attributes.get("parent")
            child_pattern_id = relation.attributes.get("child")
            if not isinstance(parent_endpoint, str) or not isinstance(child_pattern_id, str):
                continue
            try:
                parent_pattern_id, parent_role = _endpoint(parent_endpoint)
                parent_pattern = _pattern_by_id(self.arch, parent_pattern_id)
                child_pattern = _pattern_by_id(self.arch, child_pattern_id)
                if parent_pattern is None or child_pattern is None:
                    continue
                parent_values = _as_names(_role_value(parent_pattern, parent_role))
            except (KeyError, ValueError):
                continue
            nested_components = {
                name
                for value in child_pattern.roles.values()
                for name in _as_names(value)
                if name in self.arch.components
            }
            for parent in parent_values:
                if parent in self.arch.components:
                    children.setdefault(parent, set()).update(nested_components)
        return children

    def closure_members(self, component_name: str) -> set[str]:
        result: set[str] = set()
        pending = [component_name]
        while pending:
            current = pending.pop()
            if current in result:
                continue
            result.add(current)
            pending.extend(self._direct_children.get(current, ()))
        return result

    def context_objects(self, pattern: PatternInstance) -> set[str]:
        result: set[str] = set()
        for value in pattern.roles.values():
            for name in _as_names(value):
                result.add(name)
                if name in self.arch.components:
                    result.update(self.closure_members(name))
        return result

    def formula(self) -> BoolRef:
        # Architecture facts are immutable once a context has been built.
        # Reusing this conjunction avoids rebuilding the same large Z3 AST for
        # every local and composition obligation.
        if self._formula_cache is None:
            self._formula_cache = And(*(fact.formula for fact in self.facts)) if self.facts else BoolVal(True)
        return self._formula_cache

    def component_attribute(self, component: str, attribute: str) -> BoolRef:
        key = f"component.{component}.{attribute}"
        return self._variable(key)

    def resource_variables(self, names: list[str], resource: str) -> list[Any]:
        variables: list[Any] = []
        for name in names:
            components = self.closure_members(name) if name in self.arch.components else set()
            for component in sorted(components):
                key = f"component.{component}.resource.{resource}"
                if key in self.variables:
                    variables.append(self.variables[key])
        return variables

    def interface_variables(self, signal: str, attribute: str, owner: str | None = None) -> list[Any]:
        result = []
        for index, declaration in enumerate(self.arch.interfaces):
            if declaration.signal != signal or (owner is not None and declaration.owner != owner):
                continue
            key = f"interface.{index}.{attribute}"
            if key in self.variables:
                result.append(self.variables[key])
        return result

    def has_interface(self, signal: str, owner: str | None = None) -> bool:
        return bool(self.interface_variables(signal, "signal", owner))

    def model_values(self, model) -> dict[str, str]:
        reverse = {value_id: value for value, value_id in self.encoder._value_to_id.items()}
        values: dict[str, str] = {}
        for key, variable in sorted(self.variables.items()):
            result = model.eval(variable, model_completion=True)
            try:
                values[key] = reverse.get(result.as_long(), str(result))
            except AttributeError:
                values[key] = str(result)
        return values


def _all_distinct(variables: list[Any]) -> BoolRef:
    if len(variables) < 2:
        return BoolVal(True)
    return Distinct(*variables)


def _all_equal(variables: list[Any]) -> BoolRef:
    if len(variables) < 2:
        return BoolVal(True)
    first = variables[0]
    return And(*(first == other for other in variables[1:]))


def instance_evidence_id(pattern_id: str) -> str:
    return f"instance:{pattern_id}:ESTABLISHED"


def guarantee_evidence_id(pattern_id: str, guarantee_id: str) -> str:
    return f"guarantee:{pattern_id}:{guarantee_id}"


def obligation_evidence_id(obligation_id: str) -> str:
    return f"conclusion:{obligation_id}"


def _declared_types(arch: Architecture, object_name: str) -> set[str]:
    """Return all architecture types declared for a bound object."""

    result: set[str] = set()
    component = arch.components.get(object_name)
    if component is not None and _valid(component.type):
        result.add(str(component.type))
    result.update(
        declaration.type
        for declaration in arch.interfaces
        if declaration.signal == object_name
    )
    return result


def _has_boundary_placement(
    arch: Architecture,
    pattern: PatternInstance,
    role: str,
    object_name: str,
    expected_ports: tuple[str, ...],
    terminal_roles: tuple[str, ...],
) -> bool:
    if any(
        declaration.signal == object_name
        and declaration.owner == pattern.id
        and declaration.port in expected_ports
        for declaration in arch.interfaces
    ):
        return True
    component = arch.components.get(object_name)
    return (
        role in terminal_roles
        and component is not None
        and component.kind == "signal"
        and not any(
            declaration.signal == object_name
            for declaration in arch.interfaces
        )
    )


def check_instantiations(arch: Architecture) -> dict[str, InstantiationCheck]:
    """Evaluate ``Inst = TypeOK and Emb`` for every pattern instance.

    TypeOK checks the pattern type, total/non-empty role binding, existence,
    and architecture type compatibility.  Emb checks only the static
    intra-instance mapping: template nodes remain distinct and designated
    boundary roles occupy the instance's expected ports.  Inter-instance
    relations remain verification obligations.
    """

    declared_objects = set(arch.components)
    declared_objects.update(item.signal for item in arch.interfaces)
    results: dict[str, InstantiationCheck] = {}
    seen_ids: set[str] = set()
    for pattern in arch.patterns:
        type_diagnostics: list[str] = []
        if pattern.id in seen_ids:
            type_diagnostics.append(f"duplicate_pattern_id:{pattern.id}")
        seen_ids.add(pattern.id)
        if pattern.kind not in KNOWN_PATTERN_KINDS:
            type_diagnostics.append(f"unknown_pattern_kind:{pattern.kind}")
            required_roles: tuple[str, ...] = ()
            structure = None
        else:
            required_roles = contract_for(pattern.kind).required_roles
            structure = structure_for(pattern.kind)
        for role in required_roles:
            if role not in pattern.roles:
                type_diagnostics.append(f"missing_role:{role}")
                continue
            values = _as_names(pattern.roles[role])
            if not values:
                type_diagnostics.append(f"empty_role:{role}")
            for name in values:
                if name not in declared_objects:
                    type_diagnostics.append(f"unknown_binding:{role}:{name}")
                    continue
                if structure is None:
                    continue
                expected_types = structure.role_types.get(role, ())
                actual_types = _declared_types(arch, name)
                if not actual_types:
                    type_diagnostics.append(f"binding_type_missing:{role}:{name}")
                elif expected_types and not actual_types.issubset(
                    set(expected_types)
                ):
                    type_diagnostics.append(
                        "binding_type_mismatch:"
                        f"{role}:{name}:"
                        f"{','.join(sorted(actual_types))}:"
                        f"{','.join(expected_types)}"
                    )

        embedding_diagnostics: list[str] = []
        if type_diagnostics:
            embedding_status = "NOT_EVALUATED_TYPE_ERROR"
        else:
            assert structure is not None
            for role_group in structure.distinct_role_groups:
                occurrences: dict[str, list[str]] = {}
                for role in role_group:
                    for name in _as_names(_role_value(pattern, role)):
                        occurrences.setdefault(name, []).append(role)
                for name, roles in occurrences.items():
                    if len(roles) > 1:
                        embedding_diagnostics.append(
                            "non_injective_binding:"
                            f"{','.join(roles)}:{name}"
                        )
            for role, expected_ports in structure.boundary_ports.items():
                for name in _as_names(_role_value(pattern, role)):
                    if not _has_boundary_placement(
                        arch,
                        pattern,
                        role,
                        name,
                        expected_ports,
                        structure.terminal_boundary_roles,
                    ):
                        embedding_diagnostics.append(
                            "boundary_position_missing:"
                            f"{role}:{name}:{','.join(expected_ports)}"
                        )
            embedding_status = (
                "EMBEDDED"
                if not embedding_diagnostics
                else "EMBEDDING_INVALID"
            )
        results[pattern.id] = InstantiationCheck(
            pattern_id=pattern.id,
            type_status="TYPE_OK" if not type_diagnostics else "TYPE_ERROR",
            type_diagnostics=tuple(type_diagnostics),
            embedding_status=embedding_status,
            embedding_diagnostics=tuple(embedding_diagnostics),
        )
    return results


def _clause_conclusion(
    context: ArchitectureContext,
    pattern: PatternInstance,
    clause: ContractClause,
) -> tuple[BoolRef, tuple[str, ...], str]:
    params = clause.parameters
    if clause.kind == "dal_equals":
        names = [name for role in params["roles"] for name in _as_names(_role_value(pattern, role))]
        formulas = []
        for name in names:
            key = f"component.{name}.dal"
            formulas.append(context.variables[key] == context.encoder.value_id(str(params["value"])) if key in context.variables else BoolVal(False))
        return And(*formulas) if formulas else BoolVal(False), tuple(names), "local_contract"
    if clause.kind == "all_distinct_resources":
        names = [name for role in params["roles"] for name in _as_names(_role_value(pattern, role))]
        formulas = [_all_distinct(context.resource_variables(names, resource)) for resource in params["resources"]]
        return And(*formulas), tuple(names), "local_contract"
    if clause.kind == "cross_distinct_resources":
        left = _as_names(_role_value(pattern, params["left_role"]))
        right = _as_names(_role_value(pattern, params["right_role"]))
        formulas = []
        for resource in params["resources"]:
            left_vars = context.resource_variables(left, resource)
            right_vars = context.resource_variables(right, resource)
            formulas.extend(left_var != right_var for left_var in left_vars for right_var in right_vars)
        return And(*formulas) if formulas else BoolVal(False), tuple(left + right), "local_contract"
    if clause.kind == "forbidden_roles_absent":
        forbidden = {str(role) for role in params["roles"]}
        used = forbidden.intersection(pattern.roles)
        return BoolVal(not used), tuple(sorted(used)), "local_contract"
    if clause.kind == "required_edge":
        source = str(_role_value(pattern, params["source_role"]))
        target = str(_role_value(pattern, params["target_role"]))
        exists = context.arch.has_edge(source, target, str(params["edge_kind"]))
        return BoolVal(exists), (source, target), "local_contract"
    if clause.kind == "signal_type":
        signals = [name for role in params["roles"] for name in _as_names(_role_value(pattern, role))]
        formulas = []
        for signal in signals:
            variables = context.interface_variables(signal, "type")
            formulas.append(And(*(var == context.encoder.value_id(str(params["value"])) for var in variables)) if variables else BoolVal(False))
        return And(*formulas), tuple(signals), "local_contract"
    if clause.kind == "boundary_declared":
        signal = str(_role_value(pattern, str(params["role"])))
        # A boundary can be declared either as an interface or as a terminal
        # signal component.  The latter preserves the legacy case boundary
        # without treating an intentionally external port as an empty promise.
        signal_component = context.arch.components.get(signal)
        declared = context.has_interface(signal, pattern.id) or (
            signal_component is not None and signal_component.kind == "signal"
        )
        return BoolVal(declared), (signal,), "pattern_guarantee"
    raise ValueError(f"Unsupported contract clause: {clause.kind}")


def _local_obligations(context: ArchitectureContext, pattern: PatternInstance, contract: PatternContract) -> list[VerificationObligation]:
    obligations = []
    premise = Predicate("architecture_context", context.formula())
    for clause in contract.assumptions:
        formula, related, trigger = _clause_conclusion(context, pattern, clause)
        obligations.append(
            VerificationObligation(
                id=f"{pattern.id}:{clause.id}",
                premise=premise,
                conclusion=Predicate(f"{pattern.id}.{clause.id}", formula),
                trace=ObligationTrace(pattern.id, None, related, trigger),
            )
        )
    return obligations


def _boundary_guarantee(context: ArchitectureContext, pattern: PatternInstance) -> BoolRef:
    return _clause_conclusion(context, pattern, ContractClause("OUTPUT_BOUNDARY_DECLARED", "boundary_declared", {"role": "output"}))[0]


def _composition_obligations(context: ArchitectureContext) -> list[VerificationObligation]:
    arch = context.arch
    obligations: list[VerificationObligation] = []
    premise_context = context.formula()

    for relation in arch.relations:
        if relation.kind != "sequence":
            continue
        source_endpoint = relation.attributes.get("source")
        target_endpoint = relation.attributes.get("target")
        if not isinstance(source_endpoint, str) or not isinstance(target_endpoint, str):
            continue
        try:
            source_id, source_role = _endpoint(source_endpoint)
            target_id, target_role = _endpoint(target_endpoint)
            source_pattern = _pattern_by_id(arch, source_id)
            target_pattern = _pattern_by_id(arch, target_id)
            if source_pattern is None or target_pattern is None:
                continue
            source_signal = str(_role_value(source_pattern, source_role))
            target_signal = str(_role_value(target_pattern, target_role))
        except (KeyError, ValueError):
            continue
        types = context.interface_variables(source_signal, "type", source_id) + context.interface_variables(target_signal, "type", target_id)
        dals = context.interface_variables(source_signal, "dal", source_id) + context.interface_variables(target_signal, "dal", target_id)
        compatible = BoolVal(source_signal == target_signal)
        compatible = And(compatible, _all_equal(types), _all_equal(dals))
        obligation_id = f"FLOW:{source_endpoint}->{target_endpoint}"
        dependencies = (
            guarantee_evidence_id(source_id, "OUTPUT_BOUNDARY_DECLARED"),
            *tuple(str(item) for item in relation.attributes.get("dependencies", [])),
        )
        obligations.append(
            VerificationObligation(
                id=obligation_id,
                premise=Predicate(
                    f"architecture_context AND {source_id}.output_boundary_declared",
                    And(premise_context, _boundary_guarantee(context, source_pattern)),
                ),
                conclusion=Predicate(f"compatible_boundary({source_endpoint}, {target_endpoint})", compatible),
                trace=ObligationTrace(source_id, target_id, (source_signal, target_signal), "boundary_connection"),
                dependencies=dependencies,
                conclusion_evidence=obligation_evidence_id(obligation_id),
            )
        )

    for relation in arch.relations:
        if relation.kind != "contains":
            continue
        parent = relation.attributes.get("parent")
        child = relation.attributes.get("child")
        if not isinstance(parent, str) or not isinstance(child, str):
            continue
        try:
            parent_id, parent_role = _endpoint(parent)
            parent_pattern = _pattern_by_id(arch, parent_id)
            child_pattern = _pattern_by_id(arch, child)
            if parent_pattern is None or child_pattern is None:
                continue
            refined = _as_names(_role_value(parent_pattern, parent_role))
        except (KeyError, ValueError):
            continue
        conclusion = BoolVal(all(name in arch.components for name in refined))
        obligation_id = f"REFINEMENT:{child}->{parent}"
        dependencies = (
            guarantee_evidence_id(child, "OUTPUT_BOUNDARY_DECLARED"),
            *tuple(str(item) for item in relation.attributes.get("dependencies", [])),
        )
        obligations.append(
            VerificationObligation(
                id=obligation_id,
                premise=Predicate(
                    f"architecture_context AND {child}.output_boundary_declared",
                    And(premise_context, _boundary_guarantee(context, child_pattern)),
                ),
                conclusion=Predicate(f"refines({child}, {parent})", conclusion),
                trace=ObligationTrace(child, parent_id, tuple(refined), "hierarchical_refinement"),
                dependencies=dependencies,
                conclusion_evidence=obligation_evidence_id(obligation_id),
            )
        )

    # Shared-signature obligations are generated from the *instantiated*
    # boundary objects.  A stale interface declaration alone must not make two
    # patterns appear to overlap after a role has been rebound elsewhere.
    bound_objects = {
        pattern.id: context.context_objects(pattern)
        for pattern in arch.patterns
    }
    by_signal: dict[str, list[int]] = {}
    for index, declaration in enumerate(arch.interfaces):
        if declaration.owner not in bound_objects:
            continue
        if declaration.signal not in bound_objects[declaration.owner]:
            continue
        by_signal.setdefault(declaration.signal, []).append(index)
    for signal, indices in by_signal.items():
        if len(indices) < 2:
            continue
        type_vars = [context.variables[f"interface.{index}.type"] for index in indices]
        dal_vars = [context.variables[f"interface.{index}.dal"] for index in indices]
        owners = tuple(arch.interfaces[index].owner for index in indices)
        obligation_id = f"OVERLAP_SIGNATURE:{signal}"
        obligations.append(
            VerificationObligation(
                id=obligation_id,
                premise=Predicate("architecture_context", premise_context),
                conclusion=Predicate(f"compatible_signature({signal})", And(_all_equal(type_vars), _all_equal(dal_vars))),
                trace=ObligationTrace(owners[0], owners[1], (signal, *owners), "context_overlap:shared_boundary"),
                conclusion_evidence=obligation_evidence_id(obligation_id),
            )
        )

    # Parallel independence is generated only from an explicit architecture
    # declaration.  Shared data-boundary objects are therefore permitted; the
    # relation names the execution roles whose recursively propagated PWR/CPU/
    # CLK resources must remain disjoint.
    for relation in arch.parallel_relations:
        left_id = str(relation.get("left_instance", ""))
        right_id = str(relation.get("right_instance", ""))
        left_pattern = _pattern_by_id(arch, left_id)
        right_pattern = _pattern_by_id(arch, right_id)
        if left_pattern is None or right_pattern is None:
            raise ValueError(
                "Parallel relation references unknown pattern instance(s): "
                f"{left_id}, {right_id}"
            )
        resources = tuple(
            str(resource)
            for resource in relation.get("constrained_resources", ("PWR", "CPU", "CLK"))
        )
        roles = tuple(str(role) for role in relation.get("resource_roles", ("monitor", "gate")))
        left_names = [
            name
            for role in roles
            for name in _as_names(_role_value(left_pattern, role))
        ]
        right_names = [
            name
            for role in roles
            for name in _as_names(_role_value(right_pattern, role))
        ]
        comparisons = []
        for resource in resources:
            left_variables = context.resource_variables(left_names, resource)
            right_variables = context.resource_variables(right_names, resource)
            comparisons.extend(
                left_variable != right_variable
                for left_variable in left_variables
                for right_variable in right_variables
            )
        conclusion = And(*comparisons) if comparisons else BoolVal(False)
        obligation_id = (
            f"PARALLEL:{left_id}<->{right_id}:"
            "RESOURCE_INDEPENDENCE"
        )
        dependencies = (
            instance_evidence_id(left_id),
            instance_evidence_id(right_id),
            *tuple(str(item) for item in relation.get("dependencies", [])),
        )
        obligations.append(
            VerificationObligation(
                id=obligation_id,
                premise=Predicate(
                    "architecture_context AND parallel_instances_declared",
                    And(premise_context, BoolVal(True)),
                ),
                conclusion=Predicate(
                    f"independent_resources({left_id}, {right_id}, {list(resources)})",
                    conclusion,
                ),
                trace=ObligationTrace(
                    left_id,
                    right_id,
                    tuple(left_names + right_names),
                    "parallel_composition",
                    resources,
                ),
                dependencies=dependencies,
                conclusion_evidence=obligation_evidence_id(obligation_id),
            )
        )
    return obligations


def build_obligations(context: ArchitectureContext) -> list[VerificationObligation]:
    obligations: list[VerificationObligation] = []
    for pattern in context.arch.patterns:
        obligations.extend(_local_obligations(context, pattern, contract_for(pattern.kind)))
    obligations.extend(_composition_obligations(context))
    return obligations


def released_instance_evidence(
    context: ArchitectureContext,
    established_pattern_ids: set[str],
) -> dict[str, BoolRef]:
    """Return only guarantees released by established instances."""

    evidence: dict[str, BoolRef] = {}
    for pattern in context.arch.patterns:
        if pattern.id not in established_pattern_ids:
            continue
        evidence[instance_evidence_id(pattern.id)] = BoolVal(True)
        for clause in contract_for(pattern.kind).guarantees:
            formula, _, _ = _clause_conclusion(context, pattern, clause)
            if is_true(formula):
                evidence[
                    guarantee_evidence_id(pattern.id, clause.id)
                ] = formula
    return evidence


def _context_consistency(context: ArchitectureContext) -> tuple[bool, list[str]]:
    solver = Solver()
    for index, fact in enumerate(context.facts):
        solver.assert_and_track(fact.formula, Bool(f"fact_{index}_{_safe_var_name(fact.id)}"))
    if solver.check() == sat:
        return True, []
    tracked = {str(item): fact.id for item, fact in zip([Bool(f"fact_{i}_{_safe_var_name(fact.id)}") for i, fact in enumerate(context.facts)], context.facts)}
    return False, [tracked.get(str(item), str(item)) for item in solver.unsat_core()]


def evaluate_local_premise(
    context: ArchitectureContext,
    obligation: VerificationObligation,
) -> tuple[ObligationResult, int]:
    """Apply LAdm and LSup to one local contract formula.

    The existing local contract conclusion is the paper's ``P_lambda``.
    """

    admissibility = Solver()
    admissibility.add(context.formula(), obligation.conclusion.formula)
    if admissibility.check() != sat:
        return ObligationResult(obligation, "PREMISE_CONTRADICTED"), 1

    support = Solver()
    support.add(context.formula(), Not(obligation.conclusion.formula))
    if support.check() == sat:
        return (
            ObligationResult(
                obligation,
                "PREMISE_UNSUPPORTED",
                context.model_values(support.model()),
            ),
            2,
        )
    return ObligationResult(obligation, "PROVED"), 2


def evaluate_relation_obligations(
    context: ArchitectureContext,
    obligations: list[VerificationObligation],
    available_evidence: dict[str, BoolRef] | set[str],
) -> tuple[list[ObligationResult], dict[str, BoolRef], int]:
    """Evaluate relation obligations with a ready-set evidence scheduler."""

    if isinstance(available_evidence, set):
        available_evidence = {
            evidence_id: BoolVal(True)
            for evidence_id in available_evidence
        }
    pending = list(obligations)
    result_by_id: dict[str, ObligationResult] = {}
    query_count = 0
    while pending:
        ready = [
            item
            for item in pending
            if set(item.dependencies).issubset(available_evidence.keys())
        ]
        if not ready:
            for item in pending:
                missing = tuple(
                    dependency
                    for dependency in item.dependencies
                    if dependency not in available_evidence
                )
                result_by_id[item.id] = ObligationResult(
                    item,
                    "BLOCKED_BY_DEPENDENCY",
                    blocked_by=missing,
                )
            break

        for item in ready:
            pending.remove(item)
            dependency_formulas = [
                available_evidence[dependency]
                for dependency in item.dependencies
            ]
            admissibility = Solver()
            admissibility.add(
                context.formula(),
                *dependency_formulas,
                item.premise.formula,
            )
            query_count += 1
            if admissibility.check() != sat:
                result_by_id[item.id] = ObligationResult(
                    item,
                    "PREMISE_UNACCEPTABLE",
                )
                continue

            verification = Solver()
            verification.add(
                context.formula(),
                *dependency_formulas,
                item.premise.formula,
                Not(item.conclusion.formula),
            )
            query_count += 1
            if verification.check() == sat:
                result_by_id[item.id] = ObligationResult(
                    item,
                    "OBLIGATION_FAILED",
                    context.model_values(verification.model()),
                )
                continue

            result_by_id[item.id] = ObligationResult(item, "PROVED")
            if item.conclusion_evidence:
                available_evidence[
                    item.conclusion_evidence
                ] = item.conclusion.formula

    return (
        [result_by_id[item.id] for item in obligations],
        available_evidence,
        query_count,
    )


def evaluate_obligations(
    context: ArchitectureContext,
    obligations: list[VerificationObligation],
    instantiations: dict[str, InstantiationCheck] | None = None,
) -> tuple[
    list[ObligationResult],
    list[InstanceResult],
    dict[str, BoolRef],
    int,
]:
    """Evaluate local premises, establish instances, then schedule relations."""

    instantiations = instantiations or check_instantiations(context.arch)
    local = [item for item in obligations if item.trace.trigger == "local_contract"]
    relations = [item for item in obligations if item.trace.trigger != "local_contract"]
    local_results: list[ObligationResult] = []
    query_count = 0
    for item in local:
        result, used_queries = evaluate_local_premise(context, item)
        local_results.append(result)
        query_count += used_queries

    by_pattern: dict[str, list[ObligationResult]] = {}
    for result in local_results:
        if (
            result.obligation.trace.trigger == "local_contract"
            and result.obligation.trace.source_pattern
        ):
            by_pattern.setdefault(
                result.obligation.trace.source_pattern,
                [],
            ).append(result)

    established_ids = {
        pattern.id
        for pattern in context.arch.patterns
        if pattern.id in instantiations
        and instantiations[pattern.id].instantiation_status == "VALID"
        and all(
            result.status == "PROVED"
            for result in by_pattern.get(pattern.id, [])
        )
    }
    available_evidence = released_instance_evidence(context, established_ids)
    instance_results = [
        InstanceResult(
            pattern_id=pattern.id,
            type_status=instantiations[pattern.id].type_status,
            type_diagnostics=list(instantiations[pattern.id].type_diagnostics),
            embedding_status=instantiations[pattern.id].embedding_status,
            embedding_diagnostics=list(
                instantiations[pattern.id].embedding_diagnostics
            ),
            instantiation_status=(
                instantiations[pattern.id].instantiation_status
            ),
            instantiation_diagnostics=list(
                instantiations[pattern.id].diagnostics
            ),
            context_status="CONSISTENT",
            local_premise_results=by_pattern.get(pattern.id, []),
            instance_status=(
                "ESTABLISHED"
                if pattern.id in established_ids
                else "NOT_ESTABLISHED"
            ),
            released_evidence=sorted(
                evidence
                for evidence in available_evidence
                if f":{pattern.id}:" in evidence
            ),
        )
        for pattern in context.arch.patterns
    ]

    relation_results, available_evidence, relation_queries = (
        evaluate_relation_obligations(
            context,
            relations,
            available_evidence,
        )
    )
    query_count += relation_queries
    result_by_id = {
        result.obligation.id: result
        for result in (*local_results, *relation_results)
    }
    return (
        [result_by_id[item.id] for item in obligations],
        instance_results,
        available_evidence,
        query_count,
    )


def aggregate_combination_status(
    instance_results: list[InstanceResult],
    obligation_results: list[ObligationResult],
) -> str:
    relation_results = [
        result
        for result in obligation_results
        if result.obligation.trace.trigger != "local_contract"
    ]
    if all(item.instance_status == "ESTABLISHED" for item in instance_results) and all(
        item.status == "PROVED"
        for item in relation_results
    ):
        return "ESTABLISHED"
    return "NOT_ESTABLISHED"


def _not_evaluated_instances(
    arch: Architecture,
    instantiations: dict[str, InstantiationCheck],
    context_status: str,
    local_results: list[ObligationResult],
) -> list[InstanceResult]:
    by_pattern: dict[str, list[ObligationResult]] = {}
    for result in local_results:
        if (
            result.obligation.trace.trigger == "local_contract"
            and result.obligation.trace.source_pattern
        ):
            by_pattern.setdefault(
                result.obligation.trace.source_pattern,
                [],
            ).append(result)
    return [
        InstanceResult(
            pattern_id=pattern.id,
            type_status=instantiations[pattern.id].type_status,
            type_diagnostics=list(instantiations[pattern.id].type_diagnostics),
            embedding_status=instantiations[pattern.id].embedding_status,
            embedding_diagnostics=list(
                instantiations[pattern.id].embedding_diagnostics
            ),
            instantiation_status=(
                instantiations[pattern.id].instantiation_status
            ),
            instantiation_diagnostics=list(
                instantiations[pattern.id].diagnostics
            ),
            context_status=context_status,
            local_premise_results=by_pattern.get(pattern.id, []),
            instance_status="NOT_ESTABLISHED",
            released_evidence=[],
        )
        for pattern in arch.patterns
    ]


def _first_diagnostic(
    results: list[ObligationResult],
) -> ObligationResult | None:
    return next(
        (
            result
            for result in results
            if result.status
            in {
                "PREMISE_CONTRADICTED",
                "PREMISE_UNSUPPORTED",
                "PREMISE_UNACCEPTABLE",
                "OBLIGATION_FAILED",
            }
        ),
        None,
    )


def evaluate_architecture(arch: Architecture) -> LayeredReport:
    """Run the complete establishment-to-failure-analysis workflow."""

    context = ArchitectureContext(arch)
    context_objects = {
        pattern.id: sorted(context.context_objects(pattern))
        for pattern in arch.patterns
    }
    instantiations = check_instantiations(arch)
    if any(
        item.instantiation_status != "VALID"
        for item in instantiations.values()
    ):
        instances = _not_evaluated_instances(
            arch,
            instantiations,
            "NOT_CHECKED",
            [],
        )
        return LayeredReport(
            case_name=arch.case_name,
            status="INSTANTIATION_FAILED",
            stage="instantiation",
            obligation_count=0,
            context_objects=context_objects,
            unsat_core=[],
            obligation_results=[],
            instance_results=instances,
            combination_status="NOT_ESTABLISHED",
        )

    obligations = build_obligations(context)
    consistent, core = _context_consistency(context)
    if not consistent:
        not_evaluated = [
            ObligationResult(obligation, "NOT_EVALUATED_CONTEXT_CONFLICT")
            for obligation in obligations
        ]
        instances = _not_evaluated_instances(
            arch,
            instantiations,
            "INCONSISTENT",
            not_evaluated,
        )
        return LayeredReport(
            case_name=arch.case_name,
            status="CONTEXT_CONFLICT",
            stage="context",
            obligation_count=len(obligations),
            context_objects=context_objects,
            unsat_core=core,
            obligation_results=not_evaluated,
            instance_results=instances,
            combination_status="NOT_ESTABLISHED",
            smt_query_count=1,
        )

    obligation_results, instances, evidence, query_count = evaluate_obligations(
        context,
        obligations,
        instantiations,
    )
    combination_status = aggregate_combination_status(
        instances,
        obligation_results,
    )
    if combination_status != "ESTABLISHED":
        diagnostic = _first_diagnostic(obligation_results)
        instance_failure = any(
            item.instance_status != "ESTABLISHED"
            for item in instances
        )
        return LayeredReport(
            case_name=arch.case_name,
            status=(
                "INSTANCE_NOT_ESTABLISHED"
                if instance_failure
                else "COMBINATION_NOT_ESTABLISHED"
            ),
            stage="instance" if instance_failure else "combination",
            obligation_count=len(obligations),
            context_objects=context_objects,
            unsat_core=[],
            obligation_results=obligation_results,
            instance_results=instances,
            combination_status=combination_status,
            smt_query_count=1 + query_count,
            failed_obligation=(
                diagnostic.obligation
                if diagnostic is not None
                else None
            ),
            counterexample=(
                diagnostic.counterexample
                if diagnostic is not None
                else None
            ),
            available_evidence=sorted(evidence),
        )

    spec_status, spec_diagnostics = failure_spec_status(arch)
    if spec_status != "COMPLETE":
        return LayeredReport(
            case_name=arch.case_name,
            status="FAILURE_SPEC_INCOMPLETE",
            stage="failure_spec",
            obligation_count=len(obligations),
            context_objects=context_objects,
            unsat_core=[],
            obligation_results=obligation_results,
            instance_results=instances,
            combination_status=combination_status,
            failure_spec_status=spec_status,
            smt_query_count=1 + query_count,
            available_evidence=sorted(evidence),
            failure_analysis={
                "_spec": {
                    "status": "FAILURE_SPEC_INCOMPLETE",
                    "diagnostics": spec_diagnostics,
                }
            },
        )

    failure_analysis = expand_failure_semantics(arch) or {}
    successful = {
        "EXPANDED",
        "CONDITIONAL_FAILURE_RESULT",
    }
    analysis_complete = all(
        item.get("status") in successful
        for item in failure_analysis.values()
    )
    return LayeredReport(
        case_name=arch.case_name,
        status=(
            "ANALYSIS_COMPLETED"
            if analysis_complete
            else "FAILURE_ANALYSIS_PARTIAL"
        ),
        stage="failure_analysis",
        obligation_count=len(obligations),
        context_objects=context_objects,
        unsat_core=[],
        obligation_results=obligation_results,
        instance_results=instances,
        combination_status=combination_status,
        failure_spec_status=spec_status,
        smt_query_count=1 + query_count,
        available_evidence=sorted(evidence),
        failure_analysis=failure_analysis,
    )
