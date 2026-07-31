"""Architecture-aware qualitative failure-semantic expansion.

The expander never infers an AND/OR gate from a relation name.  Gates are
declared by local formulas; architecture connections and containment only
provide named substitutions between boundary events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cutsets import AND, OR, And, Atom, Expr, Or, minimal_cut_sets, render_cut_set, collect_atom_order
from .model import Architecture


@dataclass(frozen=True)
class Ref(Expr):
    name: str


@dataclass(frozen=True)
class Neg(Expr):
    term: Expr


class FailureSpecError(ValueError):
    pass


class FailureDefinitionMissing(FailureSpecError):
    pass


class FailureDefinitionConflict(FailureSpecError):
    def __init__(self, event: str, sources: list[dict[str, Any]]) -> None:
        super().__init__(f"Conflicting failure definitions: {event}")
        self.event = event
        self.sources = sources


class FailureDependencyCyclic(FailureSpecError):
    pass


def parse_expr(raw: Any) -> Expr:
    if isinstance(raw, str):
        return Atom(raw)
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid failure expression: {raw!r}")
    if "ref" in raw:
        return Ref(str(raw["ref"]))
    if "and" in raw:
        return AND(*(parse_expr(item) for item in raw["and"]))
    if "or" in raw:
        return OR(*(parse_expr(item) for item in raw["or"]))
    if "not" in raw:
        return Neg(parse_expr(raw["not"]))
    raise ValueError(f"Unknown failure expression operator: {raw!r}")


def is_monotone(expr: Expr) -> bool:
    if isinstance(expr, (Atom, Ref)):
        return True
    if isinstance(expr, Neg):
        return False
    if isinstance(expr, (And, Or)):
        return all(is_monotone(term) for term in expr.terms)
    raise TypeError(f"Unsupported expression node: {expr!r}")


def expr_text(expr: Expr) -> str:
    if isinstance(expr, Atom):
        return expr.name
    if isinstance(expr, Ref):
        return f"ref({expr.name})"
    if isinstance(expr, Neg):
        return f"not ({expr_text(expr.term)})"
    if isinstance(expr, And):
        return "(" + " and ".join(expr_text(term) for term in expr.terms) + ")"
    if isinstance(expr, Or):
        return "(" + " or ".join(expr_text(term) for term in expr.terms) + ")"
    raise TypeError(f"Unsupported expression node: {expr!r}")


def _has_sequence_connection(arch: Architecture, source: str, target: str) -> bool:
    return any(
        relation.kind == "sequence"
        and relation.attributes.get("source") == source
        and relation.attributes.get("target") == target
        for relation in arch.relations
    )


def _has_refinement_connection(arch: Architecture, child: str, parent: str) -> bool:
    return any(
        relation.kind == "contains"
        and relation.attributes.get("child") == child
        and relation.attributes.get("parent") == parent
        for relation in arch.relations
    )


def _has_parallel_relation(arch: Architecture, left: str, right: str) -> bool:
    return any(
        {
            str(relation.get("left_instance", "")),
            str(relation.get("right_instance", "")),
        }
        == {left, right}
        for relation in arch.parallel_relations
    )


def failure_spec_status(arch: Architecture) -> tuple[str, list[str]]:
    """Check only the structural prerequisites for per-top-event expansion."""

    spec = arch.failure_semantics
    diagnostics: list[str] = []
    if not isinstance(spec, dict):
        diagnostics.append("failure_semantics_missing")
    elif not isinstance(spec.get("local", {}), dict):
        diagnostics.append("local_failure_map_invalid")
    elif not isinstance(spec.get("top_events"), dict) or not spec.get("top_events"):
        diagnostics.append("top_events_missing")
    return ("COMPLETE", []) if not diagnostics else ("INCOMPLETE", diagnostics)


def expand_failure_semantics(arch: Architecture) -> dict[str, Any] | None:
    """Expand configured local formulas using explicit architecture mappings.

    The optional ``failure_semantics`` YAML object has ``local``, ``top_events``,
    ``boundary_transfers`` and ``hierarchy_substitutions`` sections.  Each
    transfer is validated against an actual architecture relation before it is
    allowed to replace an event reference.
    """

    spec = arch.failure_semantics
    if spec is None:
        return None
    definitions: dict[str, Expr] = {}
    definition_sources: dict[str, list[dict[str, Any]]] = {}
    definition_conflicts: dict[str, list[dict[str, Any]]] = {}
    definition_errors: dict[str, str] = {}

    def register(
        event_name: str,
        expression: Expr,
        source: dict[str, Any],
    ) -> None:
        if event_name not in definitions:
            definitions[event_name] = expression
            definition_sources[event_name] = [source]
            return
        definition_sources[event_name].append(source)
        if definitions[event_name] != expression:
            definition_conflicts[event_name] = list(
                definition_sources[event_name]
            )

    for pattern_id, events in spec.get("local", {}).items():
        for event, formula in events.items():
            event_name = f"{pattern_id}.{event}"
            source = {
                "kind": "local_pattern_formula",
                "pattern": str(pattern_id),
                "event": event_name,
            }
            try:
                register(event_name, parse_expr(formula), source)
            except ValueError as exc:
                definition_errors[event_name] = str(exc)

    for transfer in spec.get("boundary_transfers", []):
        connection = transfer["connection"]
        target_event = str(transfer["target_event"])
        source = {
            "kind": "boundary_transfer",
            "event": target_event,
            "source_event": str(transfer["source_event"]),
            "connection": dict(connection),
        }
        if not _has_sequence_connection(
            arch,
            connection["source"],
            connection["target"],
        ):
            definition_errors[target_event] = (
                "Failure transfer is not backed by a sequence connection: "
                f"{connection}"
            )
            continue
        register(
            target_event,
            Ref(str(transfer["source_event"])),
            source,
        )

    for substitution in spec.get("hierarchy_substitutions", []):
        hierarchy = substitution["hierarchy"]
        target_event = str(substitution["target_event"])
        source = {
            "kind": "hierarchy_substitution",
            "event": target_event,
            "source_event": str(substitution["source_event"]),
            "hierarchy": dict(hierarchy),
        }
        if not _has_refinement_connection(
            arch,
            hierarchy["child"],
            hierarchy["parent"],
        ):
            definition_errors[target_event] = (
                "Failure substitution is not backed by a containment relation: "
                f"{hierarchy}"
            )
            continue
        register(
            target_event,
            Ref(str(substitution["source_event"])),
            source,
        )

    def expand(
        expr: Expr,
        substitutions: list[dict[str, Any]],
        basic_sources: dict[str, set[str]],
        stack: tuple[str, ...] = (),
        current_event: str | None = None,
    ) -> Expr:
        if isinstance(expr, Atom):
            if current_event is not None:
                basic_sources.setdefault(expr.name, set()).add(current_event)
            return expr
        if isinstance(expr, Neg):
            return Neg(expand(expr.term, substitutions, basic_sources, stack, current_event))
        if isinstance(expr, And):
            return AND(*(expand(term, substitutions, basic_sources, stack, current_event) for term in expr.terms))
        if isinstance(expr, Or):
            return OR(*(expand(term, substitutions, basic_sources, stack, current_event) for term in expr.terms))
        if isinstance(expr, Ref):
            if expr.name in stack:
                raise FailureDependencyCyclic(
                    "Cyclic failure dependency: "
                    + " -> ".join((*stack, expr.name))
                )
            if expr.name in definition_conflicts:
                raise FailureDefinitionConflict(
                    expr.name,
                    definition_conflicts[expr.name],
                )
            if expr.name in definition_errors:
                raise FailureDefinitionMissing(
                    f"{expr.name}: {definition_errors[expr.name]}"
                )
            if expr.name not in definitions:
                raise FailureDefinitionMissing(
                    f"Undefined failure event reference: {expr.name}"
                )
            source = definition_sources[expr.name][0]
            substitutions.append(dict(source))
            return expand(
                definitions[expr.name],
                substitutions,
                basic_sources,
                (*stack, expr.name),
                expr.name,
            )
        raise TypeError(f"Unsupported expression node: {expr!r}")

    result: dict[str, Any] = {}
    for top_event, formula in spec.get("top_events", {}).items():
        substitutions: list[dict[str, Any]] = []
        basic_sources: dict[str, set[str]] = {}
        try:
            expanded = expand(
                parse_expr(formula),
                substitutions,
                basic_sources,
            )
            monotone = is_monotone(expanded)
            item = {
                "status": (
                    "EXPANDED"
                    if monotone
                    else "CONDITIONAL_FAILURE_RESULT"
                ),
                "diagnostic": None,
                "expression": expr_text(expanded),
                "monotone": monotone,
                "expansion_trace": {
                    "top_event": str(top_event),
                    "substitutions": substitutions,
                    "basic_event_sources": {
                        event: sorted(sources)
                        for event, sources in sorted(basic_sources.items())
                    },
                },
            }
            if monotone:
                atom_order = collect_atom_order(expanded)
                item["minimal_cut_sets"] = [
                    render_cut_set(cut_set, atom_order)
                    for cut_set in minimal_cut_sets(expanded)
                ]
            for composition in spec.get("parallel_compositions", []):
                if composition.get("top_event") != top_event:
                    continue
                left_instance = str(composition["left_instance"])
                right_instance = str(composition["right_instance"])
                if not _has_parallel_relation(
                    arch,
                    left_instance,
                    right_instance,
                ):
                    raise FailureDefinitionMissing(
                        "Parallel failure composition is not backed by an "
                        "explicit parallel relation: "
                        f"{left_instance}, {right_instance}"
                    )
                item["expansion_trace"]["substitutions"].append(
                    {
                        "kind": "parallel_composition",
                        "left_instance": left_instance,
                        "right_instance": right_instance,
                        "left_event": str(composition["left_event"]),
                        "right_event": str(composition["right_event"]),
                        "operator": str(composition["operator"]),
                    }
                )
        except FailureDefinitionConflict as exc:
            item = {
                "status": "FAILURE_DEFINITION_CONFLICT",
                "diagnostic": str(exc),
                "conflicting_event": exc.event,
                "sources": exc.sources,
                "minimal_cut_sets": [],
            }
        except FailureDependencyCyclic as exc:
            item = {
                "status": "FAILURE_EXPANSION_CYCLIC",
                "diagnostic": str(exc),
                "minimal_cut_sets": [],
            }
        except (FailureDefinitionMissing, ValueError, KeyError) as exc:
            item = {
                "status": "FAILURE_SPEC_INCOMPLETE",
                "diagnostic": str(exc),
                "minimal_cut_sets": [],
            }
        result[str(top_event)] = item
    return result
