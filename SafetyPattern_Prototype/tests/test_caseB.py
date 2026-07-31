from __future__ import annotations

from pathlib import Path

from src.checker import load_architecture, run_consistency_check
from src.cutsets import caseB_cutset_rows
from src.rules import caseB_rules


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"


def test_caseB_consistency_statuses() -> None:
    expected = {
        "caseB_valid.yaml": "SAT",
        "caseB_invalid_1_mn_shared_power.yaml": "UNSAT",
        "caseB_invalid_2_cc_shared_cpu.yaml": "UNSAT",
        "caseB_invalid_3_im_monitor_shared_clock.yaml": "UNSAT",
        "caseB_invalid_4_interface_dal_conflict.yaml": "UNSAT",
        "caseB_invalid_5_data_path_broken.yaml": "UNSAT",
        "caseB_invalid_6_control_path_missing.yaml": "UNSAT",
    }

    rules = caseB_rules()

    for filename, status in expected.items():
        arch = load_architecture(DATA_DIR / filename)
        report = run_consistency_check(arch, rules=rules)
        assert report.status == status


def test_caseB_expected_violated_rules() -> None:
    expected = {
        "caseB_invalid_1_mn_shared_power.yaml": "MN_CHANNEL_RESOURCE_INDEPENDENCE",
        "caseB_invalid_2_cc_shared_cpu.yaml": "CC_COMPARATOR_INDEPENDENCE",
        "caseB_invalid_3_im_monitor_shared_clock.yaml": "IM_MONITOR_INDEPENDENCE",
        "caseB_invalid_4_interface_dal_conflict.yaml": "INTERFACE_DAL_CONSISTENCY",
        "caseB_invalid_5_data_path_broken.yaml": "DATA_PATH_CONSISTENCY",
        "caseB_invalid_6_control_path_missing.yaml": "CONTROL_PATH_CONSISTENCY",
    }

    rules = caseB_rules()

    for filename, rule_id in expected.items():
        arch = load_architecture(DATA_DIR / filename)
        report = run_consistency_check(arch, rules=rules)
        violated_rule_ids = {v.rule_id for v in report.violations}
        assert rule_id in violated_rule_ids


def test_caseB_rule_results_have_families() -> None:
    arch = load_architecture(DATA_DIR / "caseB_valid.yaml")
    report = run_consistency_check(arch, rules=caseB_rules())

    for result in report.rule_results:
        assert result.rule_family in {"MN", "CC", "IM", "Interface", "Topology"}


def test_caseB_minimal_cut_sets() -> None:
    rows = caseB_cutset_rows(case_name="caseB_valid")

    observed = [
        (row["top_event"], row["events"])
        for row in rows
    ]

    expected = [
        ("HazardousParameterDisplayed", "F_s1_err;F_s2_err;F_im_miss"),
        ("HazardousParameterDisplayed", "F_s1_err;F_s3_err;F_im_miss"),
        ("HazardousParameterDisplayed", "F_s2_err;F_s3_err;F_im_miss"),
        ("HazardousParameterDisplayed", "F_voter_err;F_im_miss"),
        ("HazardousParameterDisplayed", "F_nav_diff;F_cmp_miss;F_im_miss"),
    ]

    assert observed == expected