#!/usr/bin/env python3
"""
Extract PDB files from a directory by creating symlinks.
Optimized for large-scale processing with direct path construction.

Supports two input modes (auto-detected):
1. ID mode: Input file contains file stems (e.g., "AF-A0A009E9H3-F1-model_v4")
   - Script constructs paths as: {pdb_directory}/{stem}.pdb
2. Path mode: Input file contains absolute paths to PDB files
   - Script uses paths directly, ignoring the pdb_directory argument
"""
import os
import sys
import argparse
from pathlib import Path



def detect_input_mode(id_file: str) -> bool:
    """
    Peek at the first non-empty line to determine input mode.

    Args:
        id_file: Path to the input file

    Returns:
        True if file contains paths, False if it contains bare IDs
    """
    with open(id_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                return os.path.isabs(line)
    return False  # Empty file defaults to ID mode


def extract_pdbs(id_file: str, pdb_dir: str, output_dir: str = '.') -> tuple:
    """
    Extract PDB files by creating symlinks.

    Automatically detects input mode based on the first entry in the file.

    Args:
        id_file: File containing PDB IDs or paths (one per line)
        pdb_dir: Directory containing PDB files (used only in ID mode)
        output_dir: Output directory for symlinks (default: current directory)

    Returns:
        tuple: (found_count, missing_count, total_count, missing_ids, uses_paths)
    """
    found = 0
    missing = 0
    total = 0
    missing_ids = []

    # Detect mode once before processing
    uses_absolute_paths = detect_input_mode(id_file)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    with open(id_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            entry = line.strip()
            if not entry:
                continue

            total += 1

            if uses_absolute_paths:
                # Path mode: entry is the absolute path to the PDB file
                pdb_path = entry
                # Extract file stem for symlink naming
                pdb_id = os.path.splitext(os.path.basename(pdb_path))[0]
            else:
                # ID mode: construct path from pdb_dir + ID
                pdb_id = entry
                pdb_path = os.path.join(pdb_dir, f"{pdb_id}.pdb")

            # Check if file exists
            if not os.path.exists(pdb_path):
                missing += 1
                missing_ids.append(pdb_id)
                continue

            # Store mapping for later use (resolve to absolute path)
            abs_path = os.path.abspath(pdb_path)

            # Create symlink in output directory
            symlink_path = os.path.join(output_dir, f"{pdb_id}.pdb")
            try:
                # Remove existing symlink if present (for idempotency)
                if os.path.islink(symlink_path):
                    os.unlink(symlink_path)
                os.symlink(pdb_path, symlink_path)
                found += 1
            except OSError as e:
                print(f"⚠️  Error creating symlink for {pdb_id}: {e}", file=sys.stderr)
                missing += 1
                missing_ids.append(pdb_id)

            # Progress reporting every 1000 files
            if total % 1000 == 0:
                print(f"  Progress: {total} entries processed, {found} found, {missing} missing", file=sys.stderr)


    return found, missing, total, missing_ids, uses_absolute_paths


def main():
    parser = argparse.ArgumentParser(
        description='Extract PDB files from directory using symlinks (optimized for large-scale processing)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Input modes (auto-detected based on first entry):

  ID mode:   File contains bare IDs without extensions
             Example: AF-A0A009E9H3-F1-model_v4
             Script constructs: {pdb_directory}/{id}.pdb
             Requires: pdb_directory argument

  Path mode: File contains paths to PDB files
             Example: /data/shards/00/AF-A0A009E9H3-F1-model_v4.pdb
             Script uses paths directly (pdb_directory not needed)

Examples:
  # ID mode - extract from flat directory (pdb_directory required)
  %(prog)s id_list.txt /path/to/pdbs

  # Path mode - extract from sharded directory (pdb_directory optional)
  %(prog)s full_paths.txt
  %(prog)s full_paths.txt /ignored  # for backward compatibility

  # Extract to specific output directory
  %(prog)s id_list.txt /path/to/pdbs --output ./extracted_pdbs
        """
    )

    parser.add_argument('id_file', help='File containing PDB IDs or paths (one per line)')
    parser.add_argument('pdb_directory', nargs='?', default=None,
                        help='Directory containing PDB files (required for ID mode, ignored for path mode)')
    parser.add_argument('--output', '-o', default='.', help='Output directory for symlinks (default: current directory)')
    parser.add_argument('--fail-on-missing', action='store_true', help='Exit with error if any files are missing')

    args = parser.parse_args()

    # Validate input file exists
    if not os.path.exists(args.id_file):
        print(f"✗ Error: Input file not found: {args.id_file}", file=sys.stderr)
        sys.exit(1)

    # Detect input mode from file content
    uses_paths = detect_input_mode(args.id_file)

    # Validate pdb_directory: required for ID mode, optional for path mode
    if not uses_paths:
        if args.pdb_directory is None:
            print(f"✗ Error: pdb_directory is required when input file contains IDs (not paths)", file=sys.stderr)
            sys.exit(1)
        if not os.path.exists(args.pdb_directory):
            print(f"✗ Error: PDB directory not found: {args.pdb_directory}", file=sys.stderr)
            sys.exit(1)

    # Log the detected mode
    if uses_paths:
        print(f"Detected path mode: extracting PDBs from paths in {args.id_file}", file=sys.stderr)
    else:
        print(f"Detected ID mode: extracting PDBs from {args.pdb_directory}", file=sys.stderr)

    # Extract PDBs (pdb_directory may be None in path mode, but won't be used)
    pdb_dir = args.pdb_directory if args.pdb_directory else ""
    found, missing, total, missing_ids, _ = extract_pdbs(
        args.id_file, pdb_dir, args.output
    )

    # Print summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Extraction Summary:", file=sys.stderr)
    print(f"  Total entries:  {total}", file=sys.stderr)
    print(f"  Found:          {found} ({100*found/total:.1f}%)" if total > 0 else "  Found:          0", file=sys.stderr)
    print(f"  Missing:        {missing} ({100*missing/total:.1f}%)" if total > 0 else "  Missing:        0", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Print first few missing entries for debugging
    if missing > 0 and missing_ids:
        print(f"\nFirst missing entries (showing up to 10):", file=sys.stderr)
        for pdb_id in missing_ids[:10]:
            print(f"  - {pdb_id}", file=sys.stderr)
        if missing > 10:
            print(f"  ... and {missing - 10} more", file=sys.stderr)

    # Exit with error if fail-on-missing flag is set
    if args.fail_on_missing and missing > 0:
        print(f"\n✗ Error: {missing} PDB files not found (fail-on-missing enabled)", file=sys.stderr)
        sys.exit(1)

    if found == 0 and total > 0:
        print(f"\n✗ Error: No PDB files found", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ Extraction complete: {found}/{total} files extracted", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"✗ Fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
