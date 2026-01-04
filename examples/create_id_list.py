#!/usr/bin/env python3
"""
Create one or more lists of PDB IDs from a directory or zip file.

This script generates the uniprot_csv_file (ID list) required by the
domain annotation pipeline. Despite the name, it's a text file with
one ID per line (without the .pdb extension).

Supports:
- Absolute limits (e.g. --limit 10000)
- Fractional limits (e.g. --limit 0.2 for 20%)
- Deterministic group selection (--group-index)
- Chunking entire datasets into non-overlapping groups (--chunk-all)

Usage examples:
    # Single group (20%, first chunk)
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2

    # Second 20% chunk
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2 --group-index 1

    # Chunk entire directory into multiple files
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2 --chunk-all
"""

import argparse
import math
import os
import sys
import zipfile
from pathlib import Path


# ==============================
# Input discovery
# ==============================

def list_pdb_ids_from_directory(directory_path):
    directory = Path(directory_path)

    if not directory.exists():
        print(f"ERROR: Directory not found: {directory_path}", file=sys.stderr)
        sys.exit(1)

    if not directory.is_dir():
        print(f"ERROR: Not a directory: {directory_path}", file=sys.stderr)
        sys.exit(1)

    pdb_files = sorted(directory.rglob("*.pdb"))

    if not pdb_files:
        print(f"WARNING: No .pdb files found in {directory_path}", file=sys.stderr)
        return []

    ids = [f.stem for f in pdb_files]
    print(f"Found {len(ids)} PDB IDs in directory", file=sys.stderr)
    return ids


def list_pdb_ids_from_zip(zip_path):
    if not os.path.exists(zip_path):
        print(f"ERROR: Zip file not found: {zip_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            pdb_files = sorted(
                f for f in zf.namelist() if f.endswith(".pdb")
            )

            if not pdb_files:
                print(f"WARNING: No .pdb files found in {zip_path}", file=sys.stderr)
                return []

            ids = [
                os.path.splitext(os.path.basename(f))[0]
                for f in pdb_files
            ]

            print(f"Found {len(ids)} PDB IDs in zip file", file=sys.stderr)
            return ids

    except zipfile.BadZipFile:
        print(f"ERROR: Invalid zip file: {zip_path}", file=sys.stderr)
        sys.exit(1)


# ==============================
# Chunking logic (deterministic)
# ==============================

def apply_limit_and_group(ids, limit, group_index):
    total = len(ids)

    if limit is None:
        return ids

    if limit <= 0:
        print("ERROR: --limit must be > 0", file=sys.stderr)
        sys.exit(1)

    # Determine chunk size
    if limit < 1:
        chunk_size = math.ceil(total * limit)
    else:
        chunk_size = int(limit)

    if chunk_size <= 0:
        print("ERROR: Computed chunk size is zero", file=sys.stderr)
        sys.exit(1)

    start = group_index * chunk_size
    end = min(start + chunk_size, total)

    if start >= total:
        print(
            f"ERROR: group_index {group_index} out of range "
            f"(start={start} >= total={total})",
            file=sys.stderr,
        )
        sys.exit(1)

    return ids[start:end]


def compute_num_groups(total, limit):
    if limit < 1:
        chunk_size = math.ceil(total * limit)
    else:
        chunk_size = int(limit)

    if chunk_size <= 0:
        print("ERROR: Computed chunk size is zero", file=sys.stderr)
        sys.exit(1)

    return math.ceil(total / chunk_size)


def make_group_output_path(base_output, group_index):
    base = Path(base_output)
    return base.with_name(
        f"{base.stem}_group_{group_index}{base.suffix}"
    )


# ==============================
# Output
# ==============================

def write_id_list(ids, output_path):
    if not ids:
        print(f"WARNING: No IDs written to {output_path}", file=sys.stderr)

    with open(output_path, "w") as f:
        for id_ in ids:
            f.write(f"{id_}\n")

    print(f"Wrote {len(ids)} IDs to {output_path}", file=sys.stderr)


# ==============================
# Main
# ==============================

def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic ID lists for domain annotation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input directory or zip file containing .pdb files",
    )

    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output file path (base name when using --chunk-all)",
    )

    parser.add_argument(
        "--limit",
        type=float,
        default=None,
        help=(
            "Maximum number of IDs per group. "
            "If <1, treated as fraction of total (e.g. 0.2 = 20%). "
            "If >=1, treated as absolute count."
        ),
    )

    parser.add_argument(
        "--group-index",
        type=int,
        default=0,
        help="Which deterministic group to output (default: 0)",
    )

    parser.add_argument(
        "--chunk-all",
        action="store_true",
        help=(
            "Generate ID lists for all groups implied by --limit. "
            "Outputs multiple files with '_group_<i>' appended."
        ),
    )

    args = parser.parse_args()

    # Load IDs
    if os.path.isdir(args.input):
        print(f"Reading PDB files from directory: {args.input}", file=sys.stderr)
        ids = list_pdb_ids_from_directory(args.input)
    elif os.path.isfile(args.input) and args.input.endswith(".zip"):
        print(f"Reading PDB files from zip: {args.input}", file=sys.stderr)
        ids = list_pdb_ids_from_zip(args.input)
    else:
        print(f"ERROR: Input must be a directory or .zip file: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not ids:
        print("ERROR: No IDs found", file=sys.stderr)
        sys.exit(1)

    # Chunk-all mode
    if args.chunk_all:
        if args.limit is None:
            print("ERROR: --chunk-all requires --limit", file=sys.stderr)
            sys.exit(1)

        total = len(ids)
        num_groups = compute_num_groups(total, args.limit)

        print(
            f"Chunking enabled: {num_groups} groups "
            f"(total IDs={total}, limit={args.limit})",
            file=sys.stderr,
        )

        for group_index in range(num_groups):
            group_ids = apply_limit_and_group(ids, args.limit, group_index)
            output_path = make_group_output_path(args.output, group_index)
            write_id_list(group_ids, output_path)

    # Single-group mode
    else:
        group_ids = apply_limit_and_group(ids, args.limit, args.group_index)
        write_id_list(group_ids, args.output)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
