from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json

from src.scalability import SIZES, VARIANTS, environment_info, run_once, summarise, write_csv, write_plots


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mixed-architecture layered-checker scalability experiment")
    parser.add_argument("--sizes", nargs="+", type=int, default=list(SIZES), help="mixed-unit counts K")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()
    for size in args.sizes:
        for variant in args.variants:
            for _ in range(args.warmup):
                run_once(size, variant)
    records = []
    for size in args.sizes:
        for variant in args.variants:
            for repetition in range(1, args.repetitions + 1):
                record = run_once(size, variant)
                record["repetition"] = repetition
                records.append(record)
                print(f"K={size:>2} variant={variant:<18} repetition={repetition} status={record['final_status']}")
    summary = summarise(records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    environment = environment_info(); environment["run_timestamp"] = datetime.now(timezone.utc).isoformat()
    payload = {"environment": environment, "configuration": {"sizes": args.sizes, "repetitions": args.repetitions, "warmup": args.warmup, "variants": args.variants, "model_loading_mode": "in_memory", "failure_analysis": "included for valid; skipped after controlled failure"}, "raw_runs": records, "summary": summary}
    with (args.output_dir / "scalability_results.json").open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    write_csv(args.output_dir / "scalability_results.csv", records)
    write_csv(args.output_dir / "scalability_summary.csv", summary)
    if not args.skip_plots:
        for path in write_plots(summary, args.output_dir):
            print(f"Wrote {path}")


if __name__ == "__main__":
    main()
