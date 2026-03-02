#!/usr/bin/env python3
"""
Concatenate per-job dimer parquets into a single final output file.

Run after all SLURM array tasks have completed:

    python utils/collect_dimer_results.py \\
        --input_dir /net/scratch/rib7/dimer_detection/partial_outputs \\
        --output    /net/scratch/rib7/dimer_detection/dimers_final.parquet \\
        --expected_tasks 100

Or submit as a dependent SLURM job:

    sbatch --dependency=afterok:<array_job_id> --wrap="python utils/collect_dimer_results.py ..."
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="Concatenate per-job dimer parquets into a final output file."
    )
    parser.add_argument(
        "--input_dir",
        required=True,
        help="Directory containing task_NNNN.parquet files from the array job.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the final merged parquet.",
    )
    parser.add_argument(
        "--expected_tasks",
        type=int,
        default=None,
        help="Expected number of task parquet files (optional validation).",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(input_dir.glob("task_*.parquet"))

    if len(files) == 0:
        print(f"[ERROR] No task_*.parquet files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    if args.expected_tasks is not None and len(files) != args.expected_tasks:
        print(
            f"[ERROR] Expected {args.expected_tasks} task files, found {len(files)}. "
            f"Check that all array tasks completed successfully.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Reading {len(files)} partial parquets from {input_dir} ...")
    dfs = [pd.read_parquet(f) for f in files]

    # When a task finds no dimers it writes pd.DataFrame([]), which has zero columns.
    # Separate those out before concatenating to avoid schema-alignment issues.
    dfs_with_data = [df for df in dfs if len(df.columns) > 0]

    result = pd.concat(dfs_with_data, ignore_index=True) if dfs_with_data else pd.DataFrame()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)

    print(f"Done: {len(result)} dimer rows -> {output_path}")


if __name__ == "__main__":
    main()
