from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json

from src.scalability import (
    RESOURCE_CONFIGURATIONS, SIZES, VARIANTS, environment_info, run_once,
    summarise, validate_configuration, write_csv, write_plots,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mixed-architecture layered-checker scalability experiment")
    parser.add_argument("--sizes", nargs="+", type=int, default=list(SIZES), help="mixed-unit counts K")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--resource-configurations", nargs="+", choices=RESOURCE_CONFIGURATIONS, default=["isolated"])
    parser.add_argument("--output-dir", type=Path, help="fresh output directory; existing directories are never overwritten")
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()
    if args.repetitions < 1 or args.warmup < 0:
        parser.error("repetitions must be positive and warmup must be nonnegative")
    for name in ("sizes", "variants", "resource_configurations"):
        if len(getattr(args, name)) != len(set(getattr(args, name))):
            parser.error(f"duplicate {name} are not allowed")
    for size in args.sizes:
        for variant in args.variants:
            for configuration in args.resource_configurations:
                try:
                    validate_configuration(size, variant, configuration)
                except ValueError as error:
                    parser.error(str(error))
    if args.output_dir is None:
        args.output_dir = (Path("outputs") if args.resource_configurations == ["isolated"]
                           else Path("outputs") / "cross_unit_resource_independence")
    if args.output_dir.exists():
        parser.error(f"output directory already exists; refusing to overwrite: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    environment = environment_info()
    environment["run_timestamp"] = datetime.now(timezone.utc).isoformat()
    root = Path(__file__).resolve().parent
    environment["source_sha256"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in ("run_scalability_experiment.py", "src/scalability.py", "src/establishment.py",
                     "src/pattern_contracts.py", "src/model.py", "src/failure_expansion.py")
    }
    configuration = {
        "sizes": args.sizes, "repetitions": args.repetitions, "warmup": args.warmup,
        "variants": args.variants, "resource_configurations": args.resource_configurations,
        "model_loading_mode": "in_memory",
        "failure_analysis": "included when combination established; skipped otherwise",
        "cross_unit_chain": {
            "instances": "IM_Display_L_i -> IM_Display_L_(i+1)",
            "resource_roles": ["monitor", "gate"], "constrained_resources": ["PWR", "CPU", "CLK"],
            "shared_cpu_pair": "last adjacent pair only, when chain_shared_cpu",
        },
        "timing_semantics": {
            "instantiation_check_ms": "structural type and role-embedding checks only; not SMT local establishment",
            "obligation_check_ms": "original evaluate_obligations interval: local establishment, evidence scheduling and SMT calls",
            "context_check_ms": "original context-consistency check interval",
            "total_verification_ms": "original interval, excludes model generation, result rendering and file I/O",
            "total_run_ms": "model generation and verification; excludes result rendering and file I/O",
            "separate_local_establishment_or_pure_smt_timer": "not available in unchanged checker; no fabricated subphase values",
        },
    }
    with (args.output_dir / "scalability_configuration.json").open("x", encoding="utf-8") as file:
        json.dump({"environment": environment, "configuration": configuration}, file, ensure_ascii=False, indent=2)
    for size in args.sizes:
        for variant in args.variants:
            for resource_configuration in args.resource_configurations:
                for repetition in range(1, args.warmup + 1):
                    print(f"warmup K={size:>2} variant={variant} resources={resource_configuration} repetition={repetition}", flush=True)
                    record = run_once(size, variant, resource_configuration=resource_configuration)
                    record["repetition"] = repetition
                    with (args.output_dir / "scalability_warmup.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    records = []
    for size in args.sizes:
        for variant in args.variants:
            for resource_configuration in args.resource_configurations:
                for repetition in range(1, args.repetitions + 1):
                    record = run_once(size, variant, resource_configuration=resource_configuration)
                    record["repetition"] = repetition
                    records.append(record)
                    with (args.output_dir / "scalability_progress.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(f"K={size:>2} variant={variant:<18} resources={resource_configuration:<18} repetition={repetition} status={record['final_status']}", flush=True)
    summary = summarise(records)
    environment["completed_timestamp"] = datetime.now(timezone.utc).isoformat()
    payload = {"environment": environment, "configuration": configuration, "raw_runs": records, "summary": summary}
    with (args.output_dir / "scalability_results.json").open("x", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    write_csv(args.output_dir / "scalability_results.csv", records)
    write_csv(args.output_dir / "scalability_summary.csv", summary)
    if not args.skip_plots:
        for resource_configuration in args.resource_configurations:
            rows = [row for row in summary if row["resource_configuration"] == resource_configuration]
            directory = args.output_dir if len(args.resource_configurations) == 1 else args.output_dir / resource_configuration
            for path in write_plots(rows, directory):
                print(f"Wrote {path}", flush=True)


if __name__ == "__main__":
    main()
