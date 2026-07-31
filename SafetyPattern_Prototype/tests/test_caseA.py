from __future__ import annotations

from pathlib import Path

from src.checker import load_architecture, run_consistency_check
from src.cutsets import Atom, AND, OR, caseA_cutset_rows, minimal_cut_sets
from src.rules import caseA_rules


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def test_caseA_consistency_statuses() -> None:
    expected = {
        "caseA_valid.yaml": "SAT",
        "caseA_invalid_1_rta_shared_power.yaml": "UNSAT",
        "caseA_invalid_2_sr_shared_power.yaml": "UNSAT",
        "caseA_invalid_3_psc_shared_cpu.yaml": "UNSAT",
        "caseA_invalid_4_interface_dal_conflict.yaml": "UNSAT",
        "caseA_invalid_5_data_path_broken.yaml": "UNSAT",
        "caseA_invalid_6_control_path_missing.yaml": "UNSAT",
    }

    rules = caseA_rules()

    for filename, status in expected.items():
        arch = load_architecture(DATA_DIR / filename)
        report = run_consistency_check(arch, rules=rules)
        assert report.status == status


def test_caseA_expected_violated_rules() -> None:
    expected = {
        "caseA_invalid_1_rta_shared_power.yaml": "RTA_RESOURCE_INDEPENDENCE",
        "caseA_invalid_2_sr_shared_power.yaml": "SR_PRIMARY_STANDBY_INDEPENDENCE",
        "caseA_invalid_3_psc_shared_cpu.yaml": "PSC_CPU_INDEPENDENCE",
        "caseA_invalid_4_interface_dal_conflict.yaml": "INTERFACE_DAL_CONSISTENCY",
        "caseA_invalid_5_data_path_broken.yaml": "DATA_PATH_CONSISTENCY",
        "caseA_invalid_6_control_path_missing.yaml": "CONTROL_PATH_CONSISTENCY",
    }

    rules = caseA_rules()

    for filename, rule_id in expected.items():
        arch = load_architecture(DATA_DIR / filename)
        report = run_consistency_check(arch, rules=rules)
        violated_rule_ids = {v.rule_id for v in report.violations}
        assert rule_id in violated_rule_ids


def test_rule_results_have_families() -> None:
    arch = load_architecture(DATA_DIR / "caseA_valid.yaml")
    report = run_consistency_check(arch, rules=caseA_rules())

    for result in report.rule_results:
        assert result.rule_family in {"RTA", "SR", "PSC", "Interface", "Topology"}


def test_caseA_minimal_cut_sets() -> None:
    rows = caseA_cutset_rows(case_name="caseA_valid")

    observed = [
        (row["top_event"], row["events"])
        for row in rows
    ]

    expected = [
        ("LossOfActuatorCommand", "F_FCCA_LOF;F_FCCB_LOF"),
        ("LossOfActuatorCommand", "F_FCCA_LOF;F_fd_miss"),
        ("LossOfActuatorCommand", "F_FCCA_LOF;F_sw_fail"),
        ("LossOfActuatorCommand", "F_dp_perm"),
        ("LossOfActuatorCommand", "F_dp_trans;F_recover_fail"),
        ("HazardousActuatorCommand", "F_adv_vio;F_mon_miss"),
        ("HazardousActuatorCommand", "F_adv_vio;F_safe_fail"),
        ("HazardousActuatorCommand", "F_adv_vio;F_sel_fail"),
        ("HazardousActuatorCommand", "F_dp_err;F_am_miss"),
    ]

    assert observed == expected


def test_minimal_cut_set_absorption() -> None:
    expr = OR(
        Atom("A"),
        AND(Atom("A"), Atom("B")),
    )

    observed = minimal_cut_sets(expr)

    assert observed == [frozenset({"A"})]