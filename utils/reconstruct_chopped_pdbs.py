#!/usr/bin/env python3
"""
Post-hoc reconstruction of chopped domain PDB files.

This script reconstructs chopped domain PDB files from published workflow outputs
after work directories have been deleted. It uses transformed_consensus.tsv to
identify domain boundaries and regenerates the exact same chopped PDB files that
were produced during the workflow.

Requirements:
    - transformed_consensus.tsv (contains domain boundaries)
    - all_md5.tsv (for validation)
    - Original input PDB files (directory or ZIP)
"""
import os
import sys
import re
import argparse
import zipfile
import subprocess
import tempfile
import hashlib
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set


class ShardManager:
    """Manages sharding of output files into subdirectories."""

    def __init__(self, output_dir: str, shard_size: Optional[int] = None):
        """
        Initialize the shard manager.

        Args:
            output_dir: Base output directory
            shard_size: Maximum files per shard (None = no sharding)
        """
        self.output_dir = output_dir
        self.shard_size = shard_size
        self.file_count = 0
        self.current_shard = 0
        self._created_shards: Set[int] = set()

    def get_output_path(self, filename: str) -> str:
        """
        Get the output path for a file, creating shard directories as needed.

        Args:
            filename: The filename to write

        Returns:
            Full path to write the file
        """
        if self.shard_size is None:
            return os.path.join(self.output_dir, filename)

        # Determine which shard this file belongs to
        shard_num = self.file_count // self.shard_size
        shard_dir = os.path.join(self.output_dir, f"shard_{shard_num:04d}")

        # Create shard directory if needed
        if shard_num not in self._created_shards:
            os.makedirs(shard_dir, exist_ok=True)
            self._created_shards.add(shard_num)

        self.file_count += 1
        return os.path.join(shard_dir, filename)

    def get_shard_count(self) -> int:
        """Return the number of shards created."""
        return len(self._created_shards) if self._created_shards else (1 if self.file_count > 0 else 0)


def parse_chopping_string(chopping: str) -> List[Tuple[int, int]]:
    """
    Parse chopping string from transformed_consensus.tsv into residue ranges.

    Args:
        chopping: Chopping string (e.g., "12-160" or "18-94_210-470")

    Returns:
        List of (start, end) tuples for residue ranges

    Examples:
        "12-160" -> [(12, 160)]
        "18-94_210-470" -> [(18, 94), (210, 470)]
    """
    if not chopping or chopping.lower() == 'na':
        return []

    ranges = []
    for segment in chopping.split('_'):
        try:
            start, end = map(int, segment.split('-'))
            ranges.append((start, end))
        except ValueError:
            print(f"⚠️  Warning: Invalid chopping segment '{segment}'", file=sys.stderr)
            continue

    return ranges


def run_pdb_selres(pdb_content: str, domain_ranges: List[Tuple[int, int]],
                   output_file: str, is_file: bool = False) -> None:
    """
    Run pdb_selres on PDB content to extract domain residues.

    Reused from chop_pdbs.py with minor modifications.

    Args:
        pdb_content: PDB file path (if is_file=True) or content as string
        domain_ranges: List of (start, end) residue ranges
        output_file: Path to output file
        is_file: Whether pdb_content is a file path or content string
    """
    if not domain_ranges:
        print(f"⚠️  No domain ranges specified for {output_file}", file=sys.stderr)
        return

    chopping_string = ','.join([f"{start}:{end}" for start, end in domain_ranges])

    if is_file:
        # Direct file path - use as-is
        pdb_path = pdb_content
        cleanup_temp = False
    else:
        # Content string - write to temp file
        tmp_fd, pdb_path = tempfile.mkstemp(suffix='.pdb', text=True)
        try:
            with os.fdopen(tmp_fd, 'w') as tmp_file:
                tmp_file.write(pdb_content)
        except:
            os.unlink(pdb_path)
            raise
        cleanup_temp = True

    try:
        with open(output_file, 'w') as out:
            subprocess.run(
                ['python', '-m', 'pdbtools.pdb_selres', f'-{chopping_string}', pdb_path],
                stdout=out,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=30
            )
    except subprocess.TimeoutExpired:
        print(f"⚠️  Timeout processing {output_file}", file=sys.stderr)
        raise
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error processing {output_file}: {e.stderr}", file=sys.stderr)
        raise
    finally:
        if cleanup_temp:
            try:
                os.unlink(pdb_path)
            except OSError:
                pass


def calculate_sequence_md5(pdb_file: str) -> str:
    """
    Calculate MD5 hash of the amino acid sequence from a PDB file.

    This matches the MD5 calculation used in the workflow's create_domain_md5.py.

    Args:
        pdb_file: Path to PDB file

    Returns:
        MD5 hash of the sequence
    """
    sequence = []

    with open(pdb_file, 'r') as f:
        for line in f:
            if line.startswith('ATOM'):
                # Extract residue name (columns 18-20) and residue number (columns 23-26)
                res_name = line[17:20].strip()
                res_num = line[22:26].strip()

                # Map 3-letter to 1-letter amino acid codes
                aa_map = {
                    'ALA': 'A', 'ARG': 'R', 'ASN': 'N', 'ASP': 'D',
                    'CYS': 'C', 'GLN': 'Q', 'GLU': 'E', 'GLY': 'G',
                    'HIS': 'H', 'ILE': 'I', 'LEU': 'L', 'LYS': 'K',
                    'MET': 'M', 'PHE': 'F', 'PRO': 'P', 'SER': 'S',
                    'THR': 'T', 'TRP': 'W', 'TYR': 'Y', 'VAL': 'V'
                }

                if res_name in aa_map:
                    # Only add if we haven't seen this residue number yet
                    if not sequence or res_num != sequence[-1][1]:
                        sequence.append((aa_map[res_name], res_num))

    # Extract just the amino acid sequence
    seq_string = ''.join([aa for aa, _ in sequence])

    # Calculate MD5
    return hashlib.md5(seq_string.encode()).hexdigest()


def extract_base_pdb_id(domain_id: str) -> str:
    """
    Extract base PDB ID from domain ID by removing domain number suffix.

    Args:
        domain_id: Domain ID (e.g., "AF-A0A009Q8S9-F1-model_v4_01")

    Returns:
        Base PDB ID (e.g., "AF-A0A009Q8S9-F1-model_v4")
    """
    # Remove _01, _02, etc. suffix
    return re.sub(r'_\d{2}$', '', domain_id)


def build_path_mapping(id_file: str) -> Dict[str, str]:
    """
    Build a mapping from ID stem to full path from an ID file.

    If entries are absolute paths, extracts the stem as the key.
    If entries are bare IDs, the mapping value will be the ID itself.

    Args:
        id_file: Path to file containing IDs or paths (one per line)

    Returns:
        Dictionary mapping ID stem to full path
    """
    mapping = {}
    with open(id_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if os.path.isabs(line):
                # Extract stem from path: /data/shards/00/AF-A.pdb -> AF-A
                stem = Path(line).stem
                mapping[stem] = line
            else:
                # Bare ID - use as-is
                mapping[line] = line
    return mapping


def load_md5_lookup(md5_file: str) -> Dict[str, str]:
    """
    Load MD5 lookup table from all_md5.tsv.

    Args:
        md5_file: Path to all_md5.tsv

    Returns:
        Dictionary mapping PDB filename to MD5 hash
    """
    md5_lookup = {}

    with open(md5_file, 'r') as f:
        header = f.readline()  # Skip header
        for line in f:
            fields = line.strip().split('\t')
            if len(fields) >= 3:
                pdb_file = fields[0]
                md5_hash = fields[2]
                md5_lookup[pdb_file] = md5_hash

    return md5_lookup


def load_domain_filter(domain_ids_file: str) -> Set[str]:
    """
    Load domain ID filter from file.

    Args:
        domain_ids_file: Path to file containing domain IDs (one per line)

    Returns:
        Set of domain IDs to reconstruct
    """
    domain_ids = set()

    with open(domain_ids_file, 'r') as f:
        for line in f:
            domain_id = line.strip()
            if domain_id:
                domain_ids.add(domain_id)

    return domain_ids


def reconstruct_from_directory(transformed_consensus: str, pdb_dir: str,
                                output_dir: str, md5_lookup: Dict[str, str],
                                validate: bool, consensus_filter: Optional[str],
                                domain_filter: Optional[Set[str]],
                                path_mapping: Optional[Dict[str, str]] = None,
                                shard_size: Optional[int] = None) -> Dict[str, int]:
    """
    Reconstruct chopped PDB files from a directory of PDB structures.

    Args:
        transformed_consensus: Path to transformed_consensus.tsv
        pdb_dir: Directory containing original PDB files (fallback if not in path_mapping)
        output_dir: Output directory for reconstructed domains
        md5_lookup: Dictionary mapping filenames to MD5 hashes
        validate: Whether to validate MD5 hashes
        consensus_filter: Optional consensus level filter ('high', 'med', or None)
        domain_filter: Optional set of domain IDs to reconstruct
        path_mapping: Optional dict mapping ID stem to full path (for sharded dirs)

    Returns:
        Dictionary with statistics (processed, missing_pdb, md5_mismatch, shard_count)
    """
    stats = {
        'processed': 0,
        'missing_pdb': 0,
        'md5_mismatch': 0,
        'parse_error': 0,
        'skipped_filter': 0,
        'shard_count': 0
    }

    shard_manager = ShardManager(output_dir, shard_size)

    with open(transformed_consensus, 'r') as f:
        header = f.readline().strip().split('\t')

        # Find column indices
        try:
            uniprot_idx = header.index('uniprot_id')
            chopping_idx = header.index('chopping')
            consensus_idx = header.index('consensus_level')
        except ValueError as e:
            print(f"✗ Error: Required column not found in transformed_consensus.tsv: {e}",
                  file=sys.stderr)
            sys.exit(1)

        for line_num, line in enumerate(f, start=2):
            fields = line.strip().split('\t')

            if len(fields) <= max(uniprot_idx, chopping_idx, consensus_idx):
                print(f"⚠️  Line {line_num}: Insufficient fields", file=sys.stderr)
                continue

            domain_id = fields[uniprot_idx]
            chopping = fields[chopping_idx]
            consensus_level = fields[consensus_idx]

            # Apply filters
            if consensus_filter and consensus_level != consensus_filter:
                stats['skipped_filter'] += 1
                continue

            if domain_filter and domain_id not in domain_filter:
                stats['skipped_filter'] += 1
                continue

            # Extract base PDB ID and find PDB path
            base_pdb_id = extract_base_pdb_id(domain_id)

            # Look up path from mapping if available, otherwise construct from pdb_dir
            if path_mapping and base_pdb_id in path_mapping:
                pdb_path = path_mapping[base_pdb_id]
            else:
                pdb_path = os.path.join(pdb_dir, f"{base_pdb_id}.pdb")

            if not os.path.exists(pdb_path):
                print(f"⚠️  PDB not found: {pdb_path}", file=sys.stderr)
                stats['missing_pdb'] += 1
                continue

            # Parse chopping string
            try:
                ranges = parse_chopping_string(chopping)
            except Exception as e:
                print(f"⚠️  Line {line_num}: Error parsing chopping '{chopping}': {e}",
                      file=sys.stderr)
                stats['parse_error'] += 1
                continue

            if not ranges:
                print(f"⚠️  Line {line_num}: No valid ranges for {domain_id}", file=sys.stderr)
                stats['parse_error'] += 1
                continue

            # Reconstruct domain (use shard manager for output path)
            output_file = shard_manager.get_output_path(f"{domain_id}.pdb")

            try:
                run_pdb_selres(pdb_path, ranges, output_file, is_file=True)
                stats['processed'] += 1

                # Validate MD5 if requested
                if validate:
                    expected_md5 = md5_lookup.get(f"{domain_id}.pdb")
                    if expected_md5:
                        actual_md5 = calculate_sequence_md5(output_file)
                        if actual_md5 != expected_md5:
                            stats['md5_mismatch'] += 1
                            print(f"⚠️  MD5 mismatch for {domain_id}: expected {expected_md5}, got {actual_md5}",
                                  file=sys.stderr)

            except Exception as e:
                print(f"⚠️  Error reconstructing {domain_id}: {e}", file=sys.stderr)
                stats['parse_error'] += 1
                continue

    stats['shard_count'] = shard_manager.get_shard_count()
    return stats


def reconstruct_from_zip(transformed_consensus: str, pdb_zip: str,
                         output_dir: str, md5_lookup: Dict[str, str],
                         validate: bool, consensus_filter: Optional[str],
                         domain_filter: Optional[Set[str]],
                         shard_size: Optional[int] = None) -> Dict[str, int]:
    """
    Reconstruct chopped PDB files from a ZIP archive of PDB structures.

    Args:
        transformed_consensus: Path to transformed_consensus.tsv
        pdb_zip: ZIP file containing original PDB files
        output_dir: Output directory for reconstructed domains
        md5_lookup: Dictionary mapping filenames to MD5 hashes
        validate: Whether to validate MD5 hashes
        consensus_filter: Optional consensus level filter ('high', 'med', or None)
        domain_filter: Optional set of domain IDs to reconstruct

    Returns:
        Dictionary with statistics (processed, missing_pdb, md5_mismatch, shard_count)
    """
    stats = {
        'processed': 0,
        'missing_pdb': 0,
        'md5_mismatch': 0,
        'parse_error': 0,
        'skipped_filter': 0,
        'shard_count': 0
    }

    shard_manager = ShardManager(output_dir, shard_size)

    with zipfile.ZipFile(pdb_zip, 'r') as zip_ref:
        # Build lookup dictionary for ZIP contents
        zip_contents = {Path(name).stem: name for name in zip_ref.namelist()}

        with open(transformed_consensus, 'r') as f:
            header = f.readline().strip().split('\t')

            # Find column indices
            try:
                uniprot_idx = header.index('uniprot_id')
                chopping_idx = header.index('chopping')
                consensus_idx = header.index('consensus_level')
            except ValueError as e:
                print(f"✗ Error: Required column not found in transformed_consensus.tsv: {e}",
                      file=sys.stderr)
                sys.exit(1)

            for line_num, line in enumerate(f, start=2):
                fields = line.strip().split('\t')

                if len(fields) <= max(uniprot_idx, chopping_idx, consensus_idx):
                    print(f"⚠️  Line {line_num}: Insufficient fields", file=sys.stderr)
                    continue

                domain_id = fields[uniprot_idx]
                chopping = fields[chopping_idx]
                consensus_level = fields[consensus_idx]

                # Apply filters
                if consensus_filter and consensus_level != consensus_filter:
                    stats['skipped_filter'] += 1
                    continue

                if domain_filter and domain_id not in domain_filter:
                    stats['skipped_filter'] += 1
                    continue

                # Extract base PDB ID
                base_pdb_id = extract_base_pdb_id(domain_id)

                if base_pdb_id not in zip_contents:
                    print(f"⚠️  PDB not found in ZIP: {base_pdb_id}.pdb", file=sys.stderr)
                    stats['missing_pdb'] += 1
                    continue

                # Parse chopping string
                try:
                    ranges = parse_chopping_string(chopping)
                except Exception as e:
                    print(f"⚠️  Line {line_num}: Error parsing chopping '{chopping}': {e}",
                          file=sys.stderr)
                    stats['parse_error'] += 1
                    continue

                if not ranges:
                    print(f"⚠️  Line {line_num}: No valid ranges for {domain_id}", file=sys.stderr)
                    stats['parse_error'] += 1
                    continue

                # Extract PDB content from ZIP
                try:
                    pdb_bytes = zip_ref.read(zip_contents[base_pdb_id])
                    pdb_content = pdb_bytes.decode('utf-8', errors='replace')
                except Exception as e:
                    print(f"⚠️  Error reading {base_pdb_id} from ZIP: {e}", file=sys.stderr)
                    stats['parse_error'] += 1
                    continue

                # Reconstruct domain (use shard manager for output path)
                output_file = shard_manager.get_output_path(f"{domain_id}.pdb")

                try:
                    run_pdb_selres(pdb_content, ranges, output_file, is_file=False)
                    stats['processed'] += 1

                    # Validate MD5 if requested
                    if validate:
                        expected_md5 = md5_lookup.get(f"{domain_id}.pdb")
                        if expected_md5:
                            actual_md5 = calculate_sequence_md5(output_file)
                            if actual_md5 != expected_md5:
                                stats['md5_mismatch'] += 1
                                print(f"⚠️  MD5 mismatch for {domain_id}: expected {expected_md5}, got {actual_md5}",
                                      file=sys.stderr)

                except Exception as e:
                    print(f"⚠️  Error reconstructing {domain_id}: {e}", file=sys.stderr)
                    stats['parse_error'] += 1
                    continue

    stats['shard_count'] = shard_manager.get_shard_count()
    return stats


def main():
    """Main function with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description='Reconstruct chopped domain PDB files from workflow outputs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Reconstruct from directory with validation
  %(prog)s --transformed-consensus results/PROJECT/transformed_consensus.tsv \\
           --md5-file results/PROJECT/all_md5.tsv \\
           --pdb-dir /path/to/original/pdbs \\
           --output ./reconstructed_domains \\
           --validate

  # Reconstruct from ZIP archive
  %(prog)s --transformed-consensus results/PROJECT/transformed_consensus.tsv \\
           --md5-file results/PROJECT/all_md5.tsv \\
           --pdb-zip /path/to/structures.zip \\
           --output ./reconstructed_domains \\
           --validate

  # Reconstruct only high-confidence domains
  %(prog)s --transformed-consensus results/PROJECT/transformed_consensus.tsv \\
           --md5-file results/PROJECT/all_md5.tsv \\
           --pdb-dir /path/to/original/pdbs \\
           --output ./high_conf_domains \\
           --consensus-level high \\
           --validate

  # Reconstruct specific domains from file
  %(prog)s --transformed-consensus results/PROJECT/transformed_consensus.tsv \\
           --md5-file results/PROJECT/all_md5.tsv \\
           --pdb-dir /path/to/original/pdbs \\
           --output ./selected_domains \\
           --domain-ids domain_list.txt \\
           --validate

  # Reconstruct from sharded directory using ID file with absolute paths
  # (--pdb-dir not needed when --id-file contains absolute paths)
  %(prog)s --transformed-consensus results/PROJECT/transformed_consensus.tsv \\
           --md5-file results/PROJECT/all_md5.tsv \\
           --id-file paths_with_shards.txt \\
           --output ./reconstructed_domains \\
           --validate
        """
    )

    parser.add_argument('--transformed-consensus', '-t', required=True,
                        help='Path to transformed_consensus.tsv from workflow output')
    parser.add_argument('--md5-file', '-m', required=True,
                        help='Path to all_md5.tsv from workflow output')
    parser.add_argument('--pdb-dir', '-d',
                        help='Directory containing original PDB files (optional if --id-file has absolute paths)')
    parser.add_argument('--pdb-zip', '-z',
                        help='ZIP file containing original PDB files')
    parser.add_argument('--id-file', '-f',
                        help='File containing IDs or absolute paths (required for sharded directories)')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory for reconstructed domain PDB files')
    parser.add_argument('--validate', '-v', action='store_true',
                        help='Validate reconstructed domains with MD5 comparison')
    parser.add_argument('--consensus-level', '-c', choices=['high', 'med'],
                        help='Filter by consensus level (high or med)')
    parser.add_argument('--domain-ids', '-i',
                        help='File containing domain IDs to reconstruct (one per line)')
    parser.add_argument('--shard', '-s', type=int,
                        help='Shard output into subdirectories with at most this many files each')

    args = parser.parse_args()

    # Validate arguments
    if not args.pdb_dir and not args.pdb_zip and not args.id_file:
        parser.error("Either --pdb-dir, --pdb-zip, or --id-file (with absolute paths) must be specified")

    if args.pdb_dir and args.pdb_zip:
        parser.error("Cannot specify both --pdb-dir and --pdb-zip")

    if not os.path.exists(args.transformed_consensus):
        parser.error(f"transformed_consensus file not found: {args.transformed_consensus}")

    if not os.path.exists(args.md5_file):
        parser.error(f"MD5 file not found: {args.md5_file}")

    pdb_source = args.pdb_zip if args.pdb_zip else (args.pdb_dir or "")
    use_zip = bool(args.pdb_zip)

    if pdb_source and not os.path.exists(pdb_source):
        parser.error(f"PDB source not found: {pdb_source}")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    # Load MD5 lookup if validation is enabled
    md5_lookup = {}
    if args.validate:
        print(f"Loading MD5 hashes from {args.md5_file}...")
        md5_lookup = load_md5_lookup(args.md5_file)
        print(f"✓ Loaded {len(md5_lookup)} MD5 hashes")

    # Load domain filter if specified
    domain_filter = None
    if args.domain_ids:
        print(f"Loading domain filter from {args.domain_ids}...")
        domain_filter = load_domain_filter(args.domain_ids)
        print(f"✓ Loaded {len(domain_filter)} domain IDs to reconstruct")

    # Load path mapping if specified (for sharded directories)
    path_mapping = None
    if args.id_file:
        if not os.path.exists(args.id_file):
            parser.error(f"ID file not found: {args.id_file}")
        print(f"Loading path mapping from {args.id_file}...")
        path_mapping = build_path_mapping(args.id_file)
        print(f"✓ Loaded {len(path_mapping)} path mappings")

    # Reconstruct domains
    print(f"\nReconstructing domains from {pdb_source}...")
    print(f"Output directory: {args.output}")
    if args.consensus_level:
        print(f"Filtering by consensus level: {args.consensus_level}")
    if args.validate:
        print(f"MD5 validation: enabled")
    if args.shard:
        print(f"Sharding: {args.shard} files per shard")
    print()

    if use_zip:
        stats = reconstruct_from_zip(
            args.transformed_consensus,
            pdb_source,
            args.output,
            md5_lookup,
            args.validate,
            args.consensus_level,
            domain_filter,
            args.shard
        )
    else:
        stats = reconstruct_from_directory(
            args.transformed_consensus,
            pdb_source,
            args.output,
            md5_lookup,
            args.validate,
            args.consensus_level,
            domain_filter,
            path_mapping,
            args.shard
        )

    # Print summary
    print()
    print("=" * 60)
    print("RECONSTRUCTION SUMMARY")
    print("=" * 60)
    print(f"✓ Successfully reconstructed: {stats['processed']} domains")
    if stats.get('shard_count', 0) > 0:
        print(f"  Output shards:              {stats['shard_count']} directories")

    if stats['skipped_filter'] > 0:
        print(f"  Skipped by filter:          {stats['skipped_filter']} domains")
    if stats['missing_pdb'] > 0:
        print(f"⚠️  Missing PDB files:         {stats['missing_pdb']} domains")
    if stats['parse_error'] > 0:
        print(f"⚠️  Parse/processing errors:   {stats['parse_error']} domains")
    if args.validate and stats['md5_mismatch'] > 0:
        print(f"✗ MD5 validation failures:   {stats['md5_mismatch']} domains")
    elif args.validate:
        print(f"✓ MD5 validation:            All {stats['processed']} domains passed")

    print("=" * 60)

    # Exit with appropriate code
    if stats['processed'] == 0:
        print("\n✗ No domains were reconstructed", file=sys.stderr)
        sys.exit(1)
    elif stats['md5_mismatch'] > 0:
        print(f"\n⚠️  Reconstruction completed with {stats['md5_mismatch']} MD5 mismatches",
              file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n✓ Reconstruction completed successfully")
        sys.exit(0)


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
