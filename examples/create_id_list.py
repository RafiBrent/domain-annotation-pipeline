#!/usr/bin/env python3
"""
Create one or more lists of PDB IDs or paths from a directory or zip file.

This script generates the uniprot_csv_file (ID list) required by the
domain annotation pipeline. By default, it outputs bare IDs (one per line,
without the .pdb extension). With --full-paths, it outputs full paths to
the PDB files, which is useful for sharded directory structures.

Supports:
- Absolute limits (e.g. --limit 10000)
- Fractional limits (e.g. --limit 0.2 for 20%)
- Deterministic group selection (--group-index)
- Chunking entire datasets into non-overlapping groups (--chunk-all)
- Full path output for sharded directories (--full-paths)

Usage examples:
    # Single group (20%, first chunk) - outputs bare IDs
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2

    # Second 20% chunk
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2 --group-index 1

    # Chunk entire directory into multiple files
    python create_id_list.py --input pdb_files/ --output ids.txt --limit 0.2 --chunk-all

    # Output full paths (for sharded directories)
    python create_id_list.py --input /data/shards/ --output paths.txt --full-paths
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

def list_pdb_entries_from_directory(directory_path: str, full_paths: bool = False):
    """
    List PDB entries from a directory.

    Args:
        directory_path: Path to directory containing PDB files
        full_paths: If True, return absolute paths; if False, return bare IDs

    Returns:
        List of PDB IDs (bare stems) or full paths depending on full_paths flag
    """
    directory = Path(directory_path).resolve()

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

    if full_paths:
        entries = [str(f.resolve()) for f in pdb_files]
        print(f"Found {len(entries)} PDB files in directory (full paths mode)", file=sys.stderr)
    else:
        entries = [f.stem for f in pdb_files]
        print(f"Found {len(entries)} PDB IDs in directory", file=sys.stderr)

    return entries


def list_pdb_entries_from_zip(zip_path: str, full_paths: bool = False):
    """
    List PDB entries from a zip file.

    Args:
        zip_path: Path to zip file containing PDB files
        full_paths: If True, return paths within zip; if False, return bare IDs
                   Note: Full paths within zip are relative to zip root.

    Returns:
        List of PDB IDs (bare stems) or paths within zip depending on full_paths flag
    """
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

            if full_paths:
                # For zip files, full paths doesn't make sense externally
                # Just warn and return IDs
                print(
                    "WARNING: --full-paths has no effect for zip files (returning IDs)",
                    file=sys.stderr
                )

            entries = [
                os.path.splitext(os.path.basename(f))[0]
                for f in pdb_files
            ]

            print(f"Found {len(entries)} PDB IDs in zip file", file=sys.stderr)
            return entries

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

def write_entry_list(entries, output_path, full_paths=False):
    """Write entries (IDs or paths) to output file."""
    if not entries:
        print(f"WARNING: No entries written to {output_path}", file=sys.stderr)

    with open(output_path, "w") as f:
        for entry in entries:
            f.write(f"{entry}\n")

    entry_type = "paths" if full_paths else "IDs"
    print(f"Wrote {len(entries)} {entry_type} to {output_path}", file=sys.stderr)


# ==============================
# Main
# ==============================

def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic ID or path lists for domain annotation pipeline",
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
            "Maximum number of entries per group. "
            "If <1, treated as fraction of total (e.g. 0.2 = 20%%). "
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
            "Generate lists for all groups implied by --limit. "
            "Outputs multiple files with '_group_<i>' appended."
        ),
    )

    parser.add_argument(
        "--full-paths",
        action="store_true",
        help=(
            "Output full absolute paths instead of bare IDs. "
            "Useful for sharded directory structures where files are not "
            "in a flat directory. When using this mode, the pipeline's "
            "pdb_directory argument is ignored during extraction."
        ),
    )

    args = parser.parse_args()

    # Load entries (IDs or paths)
    if os.path.isdir(args.input):
        print(f"Reading PDB files from directory: {args.input}", file=sys.stderr)
        entries = list_pdb_entries_from_directory(args.input, full_paths=args.full_paths)
    elif os.path.isfile(args.input) and args.input.endswith(".zip"):
        print(f"Reading PDB files from zip: {args.input}", file=sys.stderr)
        entries = list_pdb_entries_from_zip(args.input, full_paths=args.full_paths)
    else:
        print(f"ERROR: Input must be a directory or .zip file: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("ERROR: No PDB files found", file=sys.stderr)
        sys.exit(1)

    # Chunk-all mode
    if args.chunk_all:
        if args.limit is None:
            print("ERROR: --chunk-all requires --limit", file=sys.stderr)
            sys.exit(1)

        total = len(entries)
        num_groups = compute_num_groups(total, args.limit)

        entry_type = "paths" if args.full_paths else "IDs"
        print(
            f"Chunking enabled: {num_groups} groups "
            f"(total {entry_type}={total}, limit={args.limit})",
            file=sys.stderr,
        )

        for group_index in range(num_groups):
            group_entries = apply_limit_and_group(entries, args.limit, group_index)
            output_path = make_group_output_path(args.output, group_index)
            write_entry_list(group_entries, output_path, full_paths=args.full_paths)

    # Single-group mode
    else:
        group_entries = apply_limit_and_group(entries, args.limit, args.group_index)
        write_entry_list(group_entries, args.output, full_paths=args.full_paths)

    print("\nDone.", file=sys.stderr)


if __name__ == "__main__":
    main()
