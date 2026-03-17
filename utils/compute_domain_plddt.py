#!/usr/bin/env python3
"""
Compute per-domain pLDDT confidence from source CIF b-factor fields.

For each domain row in the input parquet, loads the source CIF (retaining its
b-factor annotation, which stores pLDDT for AlphaFold structures), extracts the
domain atoms via the chopping string, averages the b-factor per residue, and
computes the fraction of residues whose mean b-factor exceeds 0.9.

The result is written as a new column `fraction_plddt_above_90` in the output
parquet. All original columns are preserved.

Designed to run as a SLURM array job. Reads SLURM_ARRAY_TASK_ID and
SLURM_ARRAY_TASK_COUNT from the environment to determine which slice of
structures to process.

Collect results with:
    python utils/collect_dimer_results.py \\
        --input_dir <output_dir> \\
        --output <final.parquet> \\
        --expected_tasks <N>
"""

import os
import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import biotite.structure as struc

from atomworks.io.utils.io_utils import load_any


# ---------------------------------------------------------------------------
# Chopping helpers (mirrors chop_domains.py)
# ---------------------------------------------------------------------------

def parse_chopping(chopping: str) -> list[tuple[int, int]]:
    """Parse a chopping string into a list of (start, end) residue ranges.

    Examples:
        "21-274"          -> [(21, 274)]
        "28-174_185-204"  -> [(28, 174), (185, 204)]
    """
    result = []
    for seg in chopping.split("_"):
        a, b = seg.split("-")
        result.append((int(a), int(b)))
    return result


def get_domain_atom_mask(aa: struc.AtomArray, chopping: str) -> np.ndarray:
    """Return a boolean mask selecting ALL atoms within a domain's residue ranges."""
    ranges = parse_chopping(chopping)
    mask = np.zeros(len(aa), dtype=bool)
    for start, end in ranges:
        mask |= (aa.res_id >= start) & (aa.res_id <= end)
    return mask


# ---------------------------------------------------------------------------
# Per-domain pLDDT computation
# ---------------------------------------------------------------------------

def fraction_plddt_above_90(aa: struc.AtomArray, chopping: str) -> float:
    """Return the fraction of domain residues whose mean b-factor exceeds 0.9.

    Args:
        aa: Full-structure AtomArray with b_factor annotation loaded.
        chopping: Domain chopping string, e.g. "21-274" or "28-174_185-204".

    Returns:
        Fraction in [0, 1], or NaN if the domain has no residues.
    """
    mask = get_domain_atom_mask(aa, chopping)
    domain_aa = aa[mask]
    if len(domain_aa) == 0:
        return float("nan")
    res_mean_b = struc.apply_residue_wise(domain_aa, domain_aa.b_factor, np.mean)
    return float(np.mean(res_mean_b > 0.9))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Compute fraction_plddt_above_90 for each domain row (SLURM array worker)."
        )
    )
    parser.add_argument(
        "parquet_path",
        help="Path to the input parquet file of domain annotations.",
    )
    parser.add_argument(
        "output_dir",
        help="Directory to write per-task parquet files (task_NNNN.parquet).",
    )
    parser.add_argument(
        "--pilot",
        action="store_true",
        help=(
            "Restrict to the first 1000 rows of the parquet. "
            "Submit with --array=0-9 (10 tasks) when using this flag."
        ),
    )
    args = parser.parse_args()

    task_id = int(os.environ["SLURM_ARRAY_TASK_ID"])
    num_tasks = int(os.environ["SLURM_ARRAY_TASK_COUNT"])

    # ------------------------------------------------------------------
    # Compute row shard from parquet metadata (no data loaded)
    # ------------------------------------------------------------------
    meta = pq.read_metadata(args.parquet_path)
    total_rows = meta.num_rows
    if args.pilot:
        total_rows = min(total_rows, 1000)
        print(f"[task {task_id}] Pilot mode: restricted to {total_rows} rows")

    rows_per_task = total_rows // num_tasks
    remainder = total_rows % num_tasks
    start = task_id * rows_per_task + min(task_id, remainder)
    end = start + rows_per_task + (1 if task_id < remainder else 0)
    print(f"[task {task_id}/{num_tasks}] Loading rows {start}–{end-1} of {total_rows}")

    # ------------------------------------------------------------------
    # Load only this task's row slice via pyarrow batches
    # ------------------------------------------------------------------
    pf = pq.ParquetFile(args.parquet_path)
    batches = []
    row_offset = 0
    for batch in pf.iter_batches():
        batch_len = len(batch)
        batch_end = row_offset + batch_len
        if batch_end <= start:
            row_offset = batch_end
            continue
        if row_offset >= end:
            break
        lo = max(0, start - row_offset)
        hi = min(batch_len, end - row_offset)
        batches.append(batch.slice(lo, hi - lo))
        row_offset = batch_end

    import pyarrow as pa
    df_shard = pa.Table.from_batches(batches).to_pandas() if batches else pd.DataFrame()
    results: list[dict] = []
    n_errors = 0

    for path_str, group in df_shard.groupby("path"):
        try:
            aa = load_any(path_str, extra_fields=["b_factor"])
            if isinstance(aa, struc.AtomArrayStack):
                if aa.stack_depth() == 1:
                    aa = aa[0]
                else:
                    raise ValueError(
                        f"Expected single model in {path_str}, "
                        f"but got stack of depth {aa.stack_depth()}"
                    )
        except Exception as e:
            print(f"[ERROR] Failed to load {path_str}: {e}", file=sys.stderr)
            for _, row in group.iterrows():
                results.append({"domain_id": row["domain_id"], "fraction_plddt_above_90": float("nan")})
            n_errors += len(group)
            continue

        for _, row in group.iterrows():
            try:
                frac = fraction_plddt_above_90(aa, row["chopping"])
            except Exception as e:
                print(
                    f"[ERROR] Failed to compute pLDDT for {row['domain_id']}: {e}",
                    file=sys.stderr,
                )
                frac = float("nan")
                n_errors += 1
            results.append({"domain_id": row["domain_id"], "fraction_plddt_above_90": frac})

    # ------------------------------------------------------------------
    # Merge results back onto shard df (preserves all original columns)
    # ------------------------------------------------------------------
    results_df = pd.DataFrame(results)
    output_df = df_shard.merge(results_df, on="domain_id", how="left")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"task_{task_id:04d}.parquet"
    output_df.to_parquet(out_path, index=False)

    n_computed = int((~output_df["fraction_plddt_above_90"].isna()).sum())
    print(
        f"[task {task_id}] Computed pLDDT fraction for {n_computed}/{len(output_df)} domains, "
        f"{n_errors} errors -> {out_path}"
    )


if __name__ == "__main__":
    main()
