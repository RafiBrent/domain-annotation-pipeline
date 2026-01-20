#!/bin/bash
#SBATCH --job-name=foldseek_chunk
#SBATCH --partition=cpu
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1

# Usage: sbatch --array=0-N run_foldseek_chunk.sh <workdir> <repo_root> <project_name> <chunk_size>
#
# This script processes a chunk of domains through the full pipeline:
#   1. Reconstruct chopped PDB files for this chunk
#   2. Run foldseek search against CATH database
#   3. Parse and format results
#
# Required environment:
#   SLURM_ARRAY_TASK_ID - The chunk index to process
#
# Arguments:
#   $1 - WORKDIR: Base working directory containing results/<project_name>/
#   $2 - REPO_ROOT: Path to the domain-annotation-pipeline repository
#   $3 - PROJECT_NAME: Name of the project (for finding transformed_consensus.tsv)
#   $4 - CHUNK_SIZE: Number of domains per chunk (default: 20000)

set -e

WORKDIR=${1:?Error: WORKDIR not specified}
REPO_ROOT=${2:?Error: REPO_ROOT not specified}
PROJECT_NAME=${3:?Error: PROJECT_NAME not specified}
CHUNK_SIZE=${4:-20000}
FOLDSEEK_DIR=/software/foldseek

CHUNK_IDX=${SLURM_ARRAY_TASK_ID}
CHUNK_NAME=$(printf "chunk_%04d" $CHUNK_IDX)

echo "=========================================="
echo "Processing ${CHUNK_NAME} (chunk index ${CHUNK_IDX})"
echo "Working directory: ${WORKDIR}"
echo "Project: ${PROJECT_NAME}"
echo "Chunk size: ${CHUNK_SIZE}"
echo "Started at: $(date)"
echo "=========================================="

# Activate virtual environment
source ${REPO_ROOT}/.venv/bin/activate

# Create chunk-specific working directory
CHUNK_WORKDIR="${WORKDIR}/chunks/${CHUNK_NAME}"
mkdir -p "${CHUNK_WORKDIR}"
cd "${CHUNK_WORKDIR}"

# Paths to input files
TRANSFORMED_CONSENSUS="${WORKDIR}/results/${PROJECT_NAME}/transformed_consensus.tsv"
MD5_FILE="${WORKDIR}/results/${PROJECT_NAME}/all_md5.tsv"
FULL_ID_FILE="${WORKDIR}/full_id_file.txt"

# Verify input files exist
for f in "$TRANSFORMED_CONSENSUS" "$MD5_FILE" "$FULL_ID_FILE"; do
    if [ ! -f "$f" ]; then
        echo "Error: Required file not found: $f"
        exit 1
    fi
done

# Extract this chunk's domain IDs from transformed_consensus.tsv
# Skip header, get uniprot_id column, then extract chunk
echo "Extracting domain IDs for chunk ${CHUNK_IDX}..."
START_LINE=$((CHUNK_IDX * CHUNK_SIZE + 1))
END_LINE=$(((CHUNK_IDX + 1) * CHUNK_SIZE))

# Get domain IDs for this chunk (column 1 is uniprot_id after header)
tail -n +2 "$TRANSFORMED_CONSENSUS" | \
    cut -f1 | \
    sed -n "${START_LINE},${END_LINE}p" > chunk_domain_ids.txt

DOMAIN_COUNT=$(wc -l < chunk_domain_ids.txt)
echo "This chunk contains ${DOMAIN_COUNT} domains"

if [ "$DOMAIN_COUNT" -eq 0 ]; then
    echo "No domains in this chunk - exiting successfully"
    # Create empty result file
    echo -e "query_id\tcath_domain\tcath_code\tfident\tevalue\tqlen\ttlen\tqtmscore\tttmscore\tqcov\ttcov" > output/parsed_results.tsv
    exit 0
fi

# Step 1: Reconstruct chopped PDB files for this chunk
echo "Step 1: Reconstructing PDB files at $(date)"
mkdir -p reconstructed_domains

python ${REPO_ROOT}/utils/reconstruct_chopped_pdbs.py \
    --transformed-consensus "$TRANSFORMED_CONSENSUS" \
    --md5-file "$MD5_FILE" \
    --id-file "$FULL_ID_FILE" \
    --output reconstructed_domains \
    --domain-ids chunk_domain_ids.txt

RECONSTRUCTED_COUNT=$(find reconstructed_domains -name "*.pdb" | wc -l)
echo "Reconstructed ${RECONSTRUCTED_COUNT} PDB files"

if [ "$RECONSTRUCTED_COUNT" -eq 0 ]; then
    echo "Warning: No PDB files reconstructed - creating empty result"
    mkdir -p output
    echo -e "query_id\tcath_domain\tcath_code\tfident\tevalue\tqlen\ttlen\tqtmscore\tttmscore\tqcov\ttcov" > output/parsed_results.tsv
    exit 0
fi

# Step 2: Create foldseek database
echo "Step 2: Creating foldseek database at $(date)"
$FOLDSEEK_DIR/foldseek createdb reconstructed_domains/ query_db

# Step 3: Search against CATH database
echo "Step 3: Running foldseek search at $(date)"
mkdir -p output

$FOLDSEEK_DIR/foldseek search query_db \
    ${REPO_ROOT}/cath_v4_4_0_s95_foldseekdb/cath_v4_4_0_s95_db \
    output/foldseek_output_db \
    tmp \
    --cov-mode 5 \
    --alignment-type 2 \
    -e 0.476641 \
    -s 10 \
    -c 0.459063 \
    -a

echo "Foldseek search completed at $(date)"

# Step 4: Convert alignments to readable format
echo "Step 4: Converting alignments at $(date)"
$FOLDSEEK_DIR/foldseek convertalis \
    query_db \
    ${REPO_ROOT}/cath_v4_4_0_s95_foldseekdb/cath_v4_4_0_s95_db \
    output/foldseek_output_db \
    foldseek_output.m8 \
    --format-output "query,target,fident,evalue,qlen,tlen,qtmscore,ttmscore,qcov,tcov"

# Step 5: Parse and assign CATH domains
echo "Step 5: Parsing results at $(date)"
python3 ${REPO_ROOT}/foldseek/bin/format_fs_output.py \
    -i foldseek_output.m8 \
    -c ${REPO_ROOT}/domain_lookup/CathDomainList.S95.v4.4.0 \
    -o output/parsed_results.tsv

RESULT_COUNT=$(tail -n +2 output/parsed_results.tsv | wc -l)
echo "Generated ${RESULT_COUNT} CATH annotations"

# Clean up intermediate files to save disk space
echo "Cleaning up intermediate files..."
rm -rf tmp query_db* output/foldseek_output_db* reconstructed_domains foldseek_output.m8

echo "=========================================="
echo "Chunk ${CHUNK_NAME} completed successfully at $(date)"
echo "=========================================="
