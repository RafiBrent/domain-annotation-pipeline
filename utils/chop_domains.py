#!/usr/bin/env python3
"""
Chop each annotated domain from its source structure and save as an individual CIF file.

For each row in the input parquet, loads the source CIF and extracts the atoms
belonging to that domain (as defined by its chopping string), then writes the
result to <output_dir>/<example_id>.cif.

Designed to run as a SLURM array job. Reads SLURM_ARRAY_TASK_ID and
SLURM_ARRAY_TASK_COUNT from the environment to determine which slice of
structures to process.
"""

import os
import sys
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import biotite.structure as struc

from atomworks.io.utils.io_utils import load_any, to_cif_file


# ---------------------------------------------------------------------------
# Shard directory helpers (mirrors find_dimers_in_structures.py logic)
# ---------------------------------------------------------------------------

def get_shard_dirs(original_path: str) -> Path:
    """Return all consecutive 2-character directory components from a path.

    Scans path components for the first occurrence of two consecutive components
    that are both exactly 2 characters long, then continues collecting further
    2-character components until the run ends.

    Example:
        /squash/mgnify_distill_rf3/cifs/e6/79/MGYP001468467970_model_0.cif.gz
        -> PosixPath('e6/79')

        /data/ab/cd/ef/subdir/file.cif
        -> PosixPath('ab/cd/ef')

    Raises:
        ValueError: if no consecutive 2-char directory pair is found.
    """
    parts = Path(original_path).parts
    non_root = [p for p in parts if p != "/"]
    for i in range(len(non_root) - 2):
        if len(non_root[i]) == 2 and len(non_root[i + 1]) == 2:
            j = i + 1
            while j + 1 < len(non_root) and len(non_root[j + 1]) == 2:
                j += 1
            return Path(*non_root[i:j + 1])
    raise ValueError(
        f"Could not find consecutive 2-character directory pair in path: {original_path}"
    )


# ---------------------------------------------------------------------------
# Chopping helpers (shared logic with find_dimers_in_structures.py)
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
# Domain array builder
# ---------------------------------------------------------------------------

def build_domain_atomarray(aa: struc.AtomArray, chopping: str) -> struc.AtomArray:
    """Return a single-domain AtomArray with res_id reindexed from 1.

    Original res_ids are preserved in the 'original_res_id' annotation.
    """
    mask = get_domain_atom_mask(aa, chopping)
    domain_array = aa[mask].copy()
    domain_array.set_annotation("original_res_id", domain_array.res_id.copy())
    res_starts = struc.get_residue_starts(domain_array)
    new_res_ids = struc.spread_residue_wise(
        domain_array, np.arange(1, len(res_starts) + 1)
    )
    domain_array.res_id = new_res_ids
    return domain_array


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Chop domain annotations into individual CIF files (SLURM array worker)."
    )
    parser.add_argument(
        "parquet_path",
        help="Path to the input parquet file of domain annotations.",
    )
    parser.add_argument(
        "output_dir",
        help="Directory to save chopped domain CIF files (one per domain row).",
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
    # Load parquet and optionally restrict to pilot rows
    # ------------------------------------------------------------------
    print(f"[task {task_id}/{num_tasks}] Loading parquet: {args.parquet_path}")
    df = pd.read_parquet(args.parquet_path)

    if args.pilot:
        df = df.iloc[:1000]
        print(f"[task {task_id}] Pilot mode: restricted to {len(df)} rows")

    # ------------------------------------------------------------------
    # Shard unique structure paths across tasks
    # ------------------------------------------------------------------
    all_paths = sorted(df["path"].unique().tolist())
    total = len(all_paths)

    files_per_task = total // num_tasks
    remainder = total % num_tasks
    start = task_id * files_per_task + min(task_id, remainder)
    end = start + files_per_task + (1 if task_id < remainder else 0)

    my_paths = set(all_paths[start:end])
    print(f"[task {task_id}] Processing {len(my_paths)} structures ({start}–{end-1} of {total})")

    # ------------------------------------------------------------------
    # Process each structure in the shard
    # ------------------------------------------------------------------
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df_shard = df[df["path"].isin(my_paths)]
    n_saved = 0
    n_errors = 0

    for path_str, group in df_shard.groupby("path"):
        try:
            aa = load_any(path_str)
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
            n_errors += len(group)
            continue

        shard_dirs = get_shard_dirs(path_str)
        shard_out_dir = output_dir / shard_dirs
        shard_out_dir.mkdir(parents=True, exist_ok=True)

        for _, row in group.iterrows():

            # NOTE: We subset to only contiguous monomer domains!
            if "_" in row["chopping"]:
                continue

            example_id = row["example_id"]
            out_cif = shard_out_dir / f"{example_id}.cif"

            try:
                domain_aa = build_domain_atomarray(aa, row["chopping"])
                to_cif_file(domain_aa, out_cif, extra_fields=["original_res_id"])
                n_saved += 1
            except Exception as e:
                print(
                    f"[ERROR] Failed to save domain {example_id} from {path_str}: {e}",
                    file=sys.stderr,
                )
                n_errors += 1

    print(f"[task {task_id}] Saved {n_saved} domain CIFs, {n_errors} errors -> {output_dir}")


if __name__ == "__main__":
    main()
