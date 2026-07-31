from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Expr:
    pass


@dataclass(frozen=True)
class Atom(Expr):
    name: str


@dataclass(frozen=True)
class And(Expr):
    terms: tuple[Expr, ...]


@dataclass(frozen=True)
class Or(Expr):
    terms: tuple[Expr, ...]


def AND(*terms: Expr) -> And:
    flattened: list[Expr] = []
    for term in terms:
        if isinstance(term, And):
            flattened.extend(term.terms)
        else:
            flattened.append(term)
    return And(tuple(flattened))


def OR(*terms: Expr) -> Or:
    flattened: list[Expr] = []
    for term in terms:
        if isinstance(term, Or):
            flattened.extend(term.terms)
        else:
            flattened.append(term)
    return Or(tuple(flattened))


def minimize(cut_sets: list[frozenset[str]]) -> list[frozenset[str]]:
    unique: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()

    for cut_set in cut_sets:
        if cut_set not in seen:
            unique.append(cut_set)
            seen.add(cut_set)

    minimal: list[frozenset[str]] = []
    for cut_set in unique:
        if not any(other < cut_set for other in unique):
            minimal.append(cut_set)

    return minimal


def minimal_cut_sets(expr: Expr) -> list[frozenset[str]]:
    if isinstance(expr, Atom):
        return [frozenset({expr.name})]

    if isinstance(expr, Or):
        merged: list[frozenset[str]] = []
        for term in expr.terms:
            merged.extend(minimal_cut_sets(term))
        return minimize(merged)

    if isinstance(expr, And):
        result: list[frozenset[str]] = [frozenset()]

        for term in expr.terms:
            term_sets = minimal_cut_sets(term)
            result = [
                left.union(right)
                for left in result
                for right in term_sets
            ]
            result = minimize(result)

        return minimize(result)

    raise TypeError(f"Unsupported expression node: {expr!r}")


def collect_atom_order(expr: Expr) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()

    def visit(node: Expr) -> None:
        if isinstance(node, Atom):
            if node.name not in seen:
                order.append(node.name)
                seen.add(node.name)
            return

        if isinstance(node, (And, Or)):
            for child in node.terms:
                visit(child)
            return

        raise TypeError(f"Unsupported expression node: {node!r}")

    visit(expr)
    return order


def render_cut_set(cut_set: frozenset[str], atom_order: list[str]) -> str:
    order_index = {name: index for index, name in enumerate(atom_order)}
    events = sorted(cut_set, key=lambda name: order_index.get(name, 9999))
    return ";".join(events)


def caseA_top_events() -> dict[str, Expr]:
    te1 = OR(
        AND(
            Atom("F_FCCA_LOF"),
            OR(
                Atom("F_FCCB_LOF"),
                Atom("F_fd_miss"),
                Atom("F_sw_fail"),
            ),
        ),
        Atom("F_dp_perm"),
        AND(
            Atom("F_dp_trans"),
            Atom("F_recover_fail"),
        ),
    )

    te2 = OR(
        AND(
            Atom("F_adv_vio"),
            OR(
                Atom("F_mon_miss"),
                Atom("F_safe_fail"),
                Atom("F_sel_fail"),
            ),
        ),
        AND(
            Atom("F_dp_err"),
            Atom("F_am_miss"),
        ),
    )

    return {
        "LossOfActuatorCommand": te1,
        "HazardousActuatorCommand": te2,
    }

def caseA_expression_text() -> str:
    return (
        "TE_1 = "
        "(F_FCCA_LOF and (F_FCCB_LOF or F_fd_miss or F_sw_fail)) "
        "or F_dp_perm "
        "or (F_dp_trans and F_recover_fail)"
        "\n"
        "TE_2 = "
        "(F_adv_vio and (F_mon_miss or F_safe_fail or F_sel_fail)) "
        "or (F_dp_err and F_am_miss)"
    )

def caseA_cutset_rows(case_name: str = "caseA_valid") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for top_event, expr in caseA_top_events().items():
        atom_order = collect_atom_order(expr)
        cut_sets = minimal_cut_sets(expr)

        prefix = "TE1" if top_event == "LossOfActuatorCommand" else "TE2"

        for index, cut_set in enumerate(cut_sets, start=1):
            rows.append(
                {
                    "case": case_name,
                    "top_event": top_event,
                    "cut_set_id": f"{prefix}_CS{index}",
                    "events": render_cut_set(cut_set, atom_order),
                    "order": str(len(cut_set)),
                }
            )

    return rows

def caseB_top_event_expr() -> Expr:
    return AND(
        OR(
            AND(Atom("F_s1_err"), Atom("F_s2_err")),
            AND(Atom("F_s1_err"), Atom("F_s3_err")),
            AND(Atom("F_s2_err"), Atom("F_s3_err")),
            Atom("F_voter_err"),
            AND(Atom("F_nav_diff"), Atom("F_cmp_miss")),
        ),
        Atom("F_im_miss"),
    )


def caseB_expression_text() -> str:
    return (
        "TE_3 = ["
        "(F_s1_err and F_s2_err) or "
        "(F_s1_err and F_s3_err) or "
        "(F_s2_err and F_s3_err) or "
        "F_voter_err or "
        "(F_nav_diff and F_cmp_miss)"
        "] and F_im_miss"
    )


def caseB_cutset_rows(case_name: str = "caseB_valid") -> list[dict[str, str]]:
    expr = caseB_top_event_expr()
    atom_order = collect_atom_order(expr)
    cut_sets = minimal_cut_sets(expr)

    rows: list[dict[str, str]] = []

    for index, cut_set in enumerate(cut_sets, start=1):
        rows.append(
            {
                "case": case_name,
                "top_event": "HazardousParameterDisplayed",
                "cut_set_id": f"TE3_CS{index}",
                "events": render_cut_set(cut_set, atom_order),
                "order": str(len(cut_set)),
            }
        )

    return rows

def write_minimal_cut_sets_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["case", "top_event", "cut_set_id", "events"]
    if rows and "order" in rows[0]:
        fieldnames.append("order")

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)