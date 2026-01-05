#!/usr/bin/env python3
"""
Extract PDB files from a directory by creating symlinks.
Optimized for large-scale processing with direct path construction.
"""
import os
import sys
import argparse
from pathlib import Path


def extract_pdbs(id_file, pdb_dir, output_dir='.'):
    """
    Extract PDB files by creating symlinks.

    Args:
        id_file: File containing PDB IDs (one per line, without .pdb extension)
        pdb_dir: Directory containing PDB files
        output_dir: Output directory for symlinks (default: current directory)

    Returns:
        tuple: (found_count, missing_count, total_count, missing_ids)
    """
    found = 0
    missing = 0
    total = 0
    missing_ids = []

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    with open(id_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            pdb_id = line.strip()
            if not pdb_id:
                continue

            total += 1

            # Construct full path
            pdb_path = os.path.join(pdb_dir, f"{pdb_id}.pdb")

            # Check if file exists
            if not os.path.exists(pdb_path):
                missing += 1
                missing_ids.append(pdb_id)
                continue

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
                print(f"  Progress: {total} IDs processed, {found} found, {missing} missing", file=sys.stderr)

    return found, missing, total, missing_ids


def main():
    parser = argparse.ArgumentParser(
        description='Extract PDB files from directory using symlinks (optimized for large-scale processing)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Examples:
            # Extract PDBs from a directory
            %(prog)s id_list.txt /path/to/pdbs

            # Extract to specific output directory
            %(prog)s id_list.txt /path/to/pdbs --output ./extracted_pdbs

            # Typical Nextflow usage
            %(prog)s chunk_001.txt /net/tukwila/afdb_clustered/pdb_files/
        """
    )

    parser.add_argument('id_file', help='File containing PDB IDs (one per line, without .pdb extension)')
    parser.add_argument('pdb_directory', help='Directory containing PDB files')
    parser.add_argument('--output', '-o', default='.', help='Output directory for symlinks (default: current directory)')
    parser.add_argument('--fail-on-missing', action='store_true', help='Exit with error if any files are missing')

    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.id_file):
        print(f"✗ Error: ID file not found: {args.id_file}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.pdb_directory):
        print(f"✗ Error: PDB directory not found: {args.pdb_directory}", file=sys.stderr)
        sys.exit(1)

    # Extract PDBs
    print(f"Extracting PDBs from: {args.pdb_directory}", file=sys.stderr)
    found, missing, total, missing_ids = extract_pdbs(args.id_file, args.pdb_directory, args.output)

    # Print summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Extraction Summary:", file=sys.stderr)
    print(f"  Total IDs:      {total}", file=sys.stderr)
    print(f"  Found:          {found} ({100*found/total:.1f}%)" if total > 0 else "  Found:          0", file=sys.stderr)
    print(f"  Missing:        {missing} ({100*missing/total:.1f}%)" if total > 0 else "  Missing:        0", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Print first few missing IDs for debugging
    if missing > 0 and missing_ids:
        print(f"\nFirst missing IDs (showing up to 10):", file=sys.stderr)
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
