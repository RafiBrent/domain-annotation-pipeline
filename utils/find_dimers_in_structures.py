#!/usr/bin/env python3
"""
Detect domain dimer pairs within protein structures.

For each structure (unique path), loads the CIF file and checks whether any pair
of domain rows from the input parquet constitutes a dimer. A dimer is defined as
two domains where each has at least 4 CA atoms within 10 Å of the other domain's
CA atoms.

Designed to run as a SLURM array job. Reads SLURM_ARRAY_TASK_ID and
SLURM_ARRAY_TASK_COUNT from the environment to determine which slice of
structures to process.
"""

import os
import sys
import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import biotite.structure as struc

from atomworks.io.utils.io_utils import load_any, to_cif_file


# ---------------------------------------------------------------------------
# Chopping helpers
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


def get_domain_ca_mask(aa: struc.AtomArray, chopping: str) -> np.ndarray:
    """Return a boolean mask selecting CA atoms that fall within a domain's residue ranges.

    Uses res_id to match residues (not array indices).
    """
    ranges = parse_chopping(chopping)
    res_mask = np.zeros(len(aa), dtype=bool)
    for start, end in ranges:
        res_mask |= (aa.res_id >= start) & (aa.res_id <= end)
    return res_mask & (aa.atom_name == "CA")


def get_domain_atom_mask(aa: struc.AtomArray, chopping: str) -> np.ndarray:
    """Return a boolean mask selecting ALL atoms (not just CA) within a domain."""
    ranges = parse_chopping(chopping)
    mask = np.zeros(len(aa), dtype=bool)
    for start, end in ranges:
        mask |= (aa.res_id >= start) & (aa.res_id <= end)
    return mask


# ---------------------------------------------------------------------------
# Dimer detection
# ---------------------------------------------------------------------------

def is_dimer(aa: struc.AtomArray, chopping_a: str, chopping_b: str) -> bool:
    """Return True if domain a and domain b form a dimer.

    Criterion: each domain must have >= 4 CA residues within 10 Å of any CA
    residue in the other domain.

    Uses biotite CellList for efficient spatial lookup.
    """
    ca_a = aa[get_domain_ca_mask(aa, chopping_a)]
    ca_b = aa[get_domain_ca_mask(aa, chopping_b)]

    if len(ca_a) == 0 or len(ca_b) == 0:
        return False

    # Build CellList over domain B's CA positions; query with domain A's coords.
    # contacts shape: (len(ca_a), p), with -1 padding for empty slots.
    # Each contacts[i, j] is an index into ca_b (>= 0) or -1 (padding).
    cell_list = struc.CellList(ca_b, cell_size=10.0)
    contacts = cell_list.get_atoms(ca_a.coord, radius=10.0)

    # Number of A residues with at least one B CA within 10 Å
    a_contacting = int(np.any(contacts >= 0, axis=1).sum())
    if a_contacting < 4:
        return False

    # Number of unique B residues contacted by any A CA
    b_contacted = int(np.unique(contacts[contacts >= 0]).shape[0])
    return b_contacted >= 4


# ---------------------------------------------------------------------------
# Output file helpers
# ---------------------------------------------------------------------------

def get_shard_relative_path(original_path: str) -> Path:
    """Extract the path relative to the first pair of consecutive 2-character directories.

    Scans path components for the first occurrence of two consecutive components
    that are both exactly 2 characters long. The relative output path starts from
    that first 2-char component onward.

    Example:
        /squash/mgnify_distill_rf3/cifs/e6/79/MGYP001468467970_model_0.cif.gz
        -> e6/79/MGYP001468467970_model_0.cif.gz

    Raises:
        ValueError: if no consecutive 2-char directory pair is found.
    """
    parts = Path(original_path).parts
    # Skip root '/' component
    non_root = [p for p in parts if p != "/"]
    for i in range(len(non_root) - 2):
        if len(non_root[i]) == 2 and len(non_root[i + 1]) == 2:
            return Path(*non_root[i:])
    raise ValueError(
        f"Could not find consecutive 2-character directory pair in path: {original_path}"
    )


def make_output_cif_path(original_path: str, output_base_dir: str, idx_a: int, idx_b: int) -> Path:
    """Build the output CIF path for a dimer, mirroring the input shard directory structure.

    The pair indices follow chain ordering: idx_a is chain A, idx_b is chain B.
    """
    rel = get_shard_relative_path(original_path)
    # Strip all CIF-related extensions from the filename
    name = rel.name
    stem = None
    for suffix in (".cif.gz", ".bcif.gz", ".bcif", ".cif"):
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    if stem is None:
        stem = Path(name).stem

    filename = f"{stem}_domains_{idx_a}_{idx_b}.cif"
    return Path(output_base_dir) / rel.parent / filename


def make_contiguous_symlink(out_cif: Path, output_base: Path) -> None:
    """Create a symlink to out_cif in the sibling contiguous_<base> directory.

    Used to build a filtered view of dimers where both domains are single
    contiguous segments (no '_' in their chopping string).
    """
    contiguous_base = output_base.parent / f"contiguous_{output_base.name}"
    rel = out_cif.relative_to(output_base)
    symlink_path = contiguous_base / rel
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.symlink_to(out_cif.resolve())


def build_dimer_atomarray(
    aa: struc.AtomArray, chopping_a: str, chopping_b: str
) -> struc.AtomArray:
    """Build a two-chain AtomArray for the dimer.

    Domain a atoms are assigned chain_id "A"; domain b atoms are assigned chain_id "B".
    The returned array has all atoms from domain a (chain A) followed by all atoms
    from domain b (chain B).
    """
    # Assign chain IDs based on domain membership
    domain_a_mask = get_domain_atom_mask(aa, chopping_a)
    domain_b_mask = get_domain_atom_mask(aa, chopping_b)

    # Subset to only the two domains of interest
    out_array = aa.copy()
    output_domain_arrays = []

    # Reindex the res_id (to adhere to CIF conventions)
    for domain_mask, chain_id in [(domain_a_mask, "A"), (domain_b_mask, "B")]:
        domain_array = out_array[domain_mask]
        domain_array.set_annotation("original_res_id", domain_array.res_id.copy())
        domain_array.chain_id = np.full(domain_array.array_length(), chain_id, dtype=domain_array.chain_id.dtype)
        res_starts = struc.get_residue_starts(domain_array)
        new_res_ids_residue_level = np.arange(1, len(res_starts) + 1)
        new_res_ids = struc.spread_residue_wise(domain_array, new_res_ids_residue_level)
        domain_array.res_id = new_res_ids
        output_domain_arrays.append(domain_array)
    
    final_output_array = output_domain_arrays[0] + output_domain_arrays[1]

    return final_output_array


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect domain dimer pairs in protein structures (SLURM array worker)."
    )
    parser.add_argument(
        "parquet_path",
        help="Path to the input parquet file of domain annotations.",
    )
    parser.add_argument(
        "output_dir",
        help="Directory for per-job partial output parquets.",
    )
    parser.add_argument(
        "--output_file_base_dir",
        default=None,
        help=(
            "If provided, save detected dimer CIF files under this directory, "
            "mirroring the input shard structure. When set, the original path is "
            "recorded as 'full_structure_path' and 'path' becomes the dimer file path."
        ),
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
    # Identify multi-domain paths and shard across tasks
    # ------------------------------------------------------------------
    path_counts = df.groupby("path").size()
    multi_domain_paths = sorted(path_counts[path_counts >= 2].index.tolist())
    total = len(multi_domain_paths)

    files_per_task = total // num_tasks
    remainder = total % num_tasks
    start = task_id * files_per_task + min(task_id, remainder)
    end = start + files_per_task + (1 if task_id < remainder else 0)

    my_paths = set(multi_domain_paths[start:end])
    print(f"[task {task_id}] Processing {len(my_paths)} structures ({start}–{end-1} of {total})")

    # ------------------------------------------------------------------
    # Column classification
    # ------------------------------------------------------------------
    FILE_LEVEL_COLS = {
        "path", "distillation_set", "overall_plddt", "overall_pde", "overall_pae", "ptm"
    }
    domain_level_cols = [
        c for c in df.columns
        if c not in FILE_LEVEL_COLS and not c.startswith("__")
    ]

    # ------------------------------------------------------------------
    # Process each structure in the shard
    # ------------------------------------------------------------------
    df_shard = df[df["path"].isin(my_paths)]
    output_base = Path(args.output_file_base_dir) if args.output_file_base_dir else None
    results = []

    for path_str, group in df_shard.groupby("path"):
        group = group.reset_index(drop=True)

        try:
            aa = load_any(path_str, extra_fields=["b_factor", "occupancy"])
            if isinstance(aa, struc.AtomArrayStack):
                if aa.stack_depth() == 1:
                    aa = aa[0]
                else:
                    raise ValueError(f"Expected single model in {path_str}, but got stack of depth {aa.stack_depth()}")
        except Exception as e:
            print(f"[ERROR] Failed to load {path_str}: {e}", file=sys.stderr)
            continue

        for idx_a, idx_b in combinations(range(len(group)), 2):
            row_a = group.iloc[idx_a]
            row_b = group.iloc[idx_b]

            try:
                dimer = is_dimer(aa, row_a["chopping"], row_b["chopping"])
            except Exception as e:
                print(
                    f"[ERROR] Dimer check failed for {path_str} "
                    f"pair ({row_a['example_id']}, {row_b['example_id']}): {e}",
                    file=sys.stderr,
                )
                continue

            if not dimer:
                continue

            row: dict = {}

            if output_base is not None:
                try:
                    out_cif = make_output_cif_path(path_str, str(output_base), idx_a, idx_b)
                    out_cif.parent.mkdir(parents=True, exist_ok=True)
                    dimer_aa = build_dimer_atomarray(aa, row_a["chopping"], row_b["chopping"])
                    to_cif_file(dimer_aa, out_cif, extra_fields=["original_res_id"])
                    row["full_structure_path"] = path_str
                    row["path"] = str(out_cif)

                    # Symlink contiguous dimers (single-segment choppings on both sides)
                    if "_" not in row_a["chopping"] and "_" not in row_b["chopping"]:
                        try:
                            make_contiguous_symlink(out_cif, output_base)
                        except Exception as e:
                            print(
                                f"[WARN] Failed to create contiguous symlink for {out_cif}: {e}",
                                file=sys.stderr,
                            )
                except Exception as e:
                    print(
                        f"[ERROR] Failed to save dimer CIF for {path_str} "
                        f"pair ({idx_a}, {idx_b}): {e}",
                        file=sys.stderr,
                    )
                    continue
            else:
                row["path"] = path_str

            # File-level columns (shared; taken from row_a — all rows with the same
            # path have identical values for these columns)
            for col in FILE_LEVEL_COLS:
                if col == "path":
                    continue  # already set above
                row[col] = row_a[col]

            # Domain-level columns with pn_unit_1_ / pn_unit_2_ prefixes.
            # unit_1 = chain A (idx_a), unit_2 = chain B (idx_b).
            for col in domain_level_cols:
                row[f"pn_unit_1_{col}"] = row_a[col]
                row[f"pn_unit_2_{col}"] = row_b[col]

            results.append(row)

    # ------------------------------------------------------------------
    # Write per-job output parquet (always write, even if empty)
    # ------------------------------------------------------------------
    out_df = pd.DataFrame(results)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"task_{task_id:04d}.parquet"
    out_df.to_parquet(out_path, index=False)
    print(f"[task {task_id}] Found {len(out_df)} dimers -> {out_path}")


if __name__ == "__main__":
    main()
