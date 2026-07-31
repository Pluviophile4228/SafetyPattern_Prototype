from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

try:
    from z3 import Distinct, Int, Solver, sat
except ImportError as exc:
    raise ImportError(
        "z3-solver is required. Please run: pip install z3-solver"
    ) from exc


@dataclass(frozen=True)
class AssignedValue:
    name: str
    value: str | None


class FiniteDomainEncoder:
    """
    Map concrete string values such as PWR_A, CPU_NA or DAL A to finite integer ids.
    Z3 then checks equality and distinctness constraints over these finite ids.
    """

    def __init__(self) -> None:
        self._value_to_id: dict[str, int] = {}

    def value_id(self, value: str) -> int:
        if value not in self._value_to_id:
            self._value_to_id[value] = len(self._value_to_id) + 1
        return self._value_to_id[value]


def _valid(value: str | None) -> bool:
    return value not in (None, "", "None", "null")


def _safe_var_name(name: str) -> str:
    result = name
    for old in ("-", ".", ":", "/", " ", ";", "(", ")"):
        result = result.replace(old, "_")
    return result


def check_all_distinct(assignments: Iterable[AssignedValue]) -> bool:
    """
    Return True if concrete assignments satisfy pairwise distinctness.
    Return False if the encoded SMT constraints are UNSAT.
    """
    encoder = FiniteDomainEncoder()
    solver = Solver()
    variables = []

    for item in assignments:
        if not _valid(item.value):
            continue

        var = Int(_safe_var_name(item.name))
        solver.add(var == encoder.value_id(str(item.value)))
        variables.append(var)

    if len(variables) >= 2:
        solver.add(Distinct(*variables))

    return solver.check() == sat


def check_all_equal(assignments: Iterable[AssignedValue]) -> bool:
    """
    Return True if concrete assignments satisfy equality consistency.
    Return False if the encoded SMT constraints are UNSAT.
    """
    encoder = FiniteDomainEncoder()
    solver = Solver()
    variables = []

    for item in assignments:
        if not _valid(item.value):
            continue

        var = Int(_safe_var_name(item.name))
        solver.add(var == encoder.value_id(str(item.value)))
        variables.append(var)

    if len(variables) >= 2:
        first = variables[0]
        for other in variables[1:]:
            solver.add(first == other)

    return solver.check() == sat


def check_equal_to_required(name: str, actual: str | None, required: str) -> bool:
    encoder = FiniteDomainEncoder()
    solver = Solver()

    var = Int(_safe_var_name(name))
    solver.add(var == encoder.value_id(str(actual)))
    solver.add(var == encoder.value_id(required))

    return solver.check() == sat