from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CRITICAL_RESOURCE_KINDS = ("PWR", "CLK", "SW", "CPU")


@dataclass(frozen=True)
class Component:
    name: str
    kind: str
    type: str | None = None
    dal: str | None = None
    resources: dict[str, str | None] = field(default_factory=dict)

    @staticmethod
    def from_yaml(name: str, raw: dict[str, Any]) -> "Component":
        return Component(
            name=name,
            kind=str(raw.get("kind", "atomic")),
            type=raw.get("type"),
            dal=raw.get("dal"),
            resources={
                str(k): None if v is None else str(v)
                for k, v in raw.get("resources", {}).items()
            },
        )

    def resource(self, resource_kind: str) -> str | None:
        return self.resources.get(resource_kind)


@dataclass(frozen=True)
class InterfaceDecl:
    signal: str
    owner: str
    port: str
    type: str
    dal: str

    @staticmethod
    def from_yaml(raw: dict[str, Any]) -> "InterfaceDecl":
        return InterfaceDecl(
            signal=str(raw["signal"]),
            owner=str(raw["owner"]),
            port=str(raw["port"]),
            type=str(raw["type"]),
            dal=str(raw["dal"]),
        )


@dataclass(frozen=True)
class PatternInstance:
    id: str
    kind: str
    roles: dict[str, Any]

    @staticmethod
    def from_yaml(raw: dict[str, Any]) -> "PatternInstance":
        return PatternInstance(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            roles=dict(raw.get("roles", {})),
        )


@dataclass(frozen=True)
class Relation:
    kind: str
    attributes: dict[str, Any]

    @staticmethod
    def from_yaml(raw: dict[str, Any]) -> "Relation":
        attrs = dict(raw)
        kind = str(attrs.pop("kind"))
        return Relation(kind=kind, attributes=attrs)

@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str

    @staticmethod
    def from_yaml(raw: dict[str, Any]) -> "Edge":
        return Edge(
            source=str(raw["source"]),
            target=str(raw["target"]),
            kind=str(raw["kind"]),
        )

@dataclass
class Architecture:
    case_name: str
    components: dict[str, Component]
    interfaces: list[InterfaceDecl]
    patterns: list[PatternInstance]
    relations: list[Relation]
    edges: list[Edge] = field(default_factory=list)
    # Optional architecture declarations used by the layered establishment
    # checker.  They deliberately remain part of the intermediate model rather
    # than the legacy rule API, so existing cases/runners stay valid.
    context_assertions: list[dict[str, Any]] = field(default_factory=list)
    failure_semantics: dict[str, Any] | None = None
    # Explicit instance-level parallel relations.  They are intentionally not
    # inferred from repeated pattern kinds: a configuration must declare which
    # branches carry an independence requirement.
    parallel_relations: list[dict[str, Any]] = field(default_factory=list)

    def component(self, name: str) -> Component:
        try:
            return self.components[name]
        except KeyError as exc:
            raise KeyError(f"Unknown component: {name}") from exc

    def patterns_by_kind(self, kind: str) -> list[PatternInstance]:
        return [p for p in self.patterns if p.kind == kind]

    def interfaces_for_signal(self, signal: str) -> list[InterfaceDecl]:
        return [i for i in self.interfaces if i.signal == signal]

    def has_edge(self, source: str, target: str, kind: str) -> bool:
        return any(
            edge.source == source and edge.target == target and edge.kind == kind
            for edge in self.edges
        )

    def component_resource_values(
        self,
        component_names: list[str],
        resource_kind: str,
    ) -> set[str]:
        values: set[str] = set()

        for name in component_names:
            value = self.component(name).resource(resource_kind)
            if value is not None:
                values.add(value)

        return values


def architecture_from_dict(raw: dict[str, Any]) -> Architecture:
    components = {
        name: Component.from_yaml(name, item)
        for name, item in raw.get("components", {}).items()
    }

    interfaces = [
        InterfaceDecl.from_yaml(item)
        for item in raw.get("interfaces", [])
    ]

    patterns = [
        PatternInstance.from_yaml(item)
        for item in raw.get("patterns", [])
    ]

    relations = [
        Relation.from_yaml(item)
        for item in raw.get("relations", [])
    ]

    edges = [
        Edge.from_yaml(item)
        for item in raw.get("edges", [])
    ]

    return Architecture(
        case_name=str(raw["case_name"]),
        components=components,
        interfaces=interfaces,
        patterns=patterns,
        relations=relations,
        edges=edges,
        context_assertions=[dict(item) for item in raw.get("context_assertions", [])],
        failure_semantics=(
            dict(raw["failure_semantics"])
            if isinstance(raw.get("failure_semantics"), dict)
            else None
        ),
        parallel_relations=[
            dict(item) for item in raw.get("parallel_relations", [])
        ],
    )
