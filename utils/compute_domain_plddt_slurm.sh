#!/bin/bash
#SBATCH --job-name=compute_domain_plddt
#SBATCH --partition=cpu
#SBATCH --time=12:00:00
#SBATCH --mem=32G
#SBATCH --output=/net/scratch/rib7/personal_tmpdir/domain_plddt/logs/compute_plddt_%A_%a.log
#SBATCH --error=/net/scratch/rib7/personal_tmpdir/domain_plddt/logs/compute_plddt_%A_%a.log
#SBATCH --array=0-199

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PARQUET=/home/rib7/public/june_and_december_2025_deduplicated_mgnify_cath_and_domain_annotations_with_confidences.parquet
OUTPUT_DIR=/net/scratch/rib7/personal_tmpdir/domain_plddt/partial_outputs

# Pilot mode: restrict to first 1000 rows for testing.
# When true, submit with: sbatch --array=0-9 compute_domain_plddt_slurm.sh
PILOT=false
# PILOT=true

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

source /home/rib7/protocols/atomworks-dev/.venv/bin/activate

# ---------------------------------------------------------------------------
# Build optional flags
# ---------------------------------------------------------------------------

PILOT_FLAG=""
if [ "$PILOT" = "true" ]; then
    PILOT_FLAG="--pilot"
fi

# ---------------------------------------------------------------------------
# Run worker
# ---------------------------------------------------------------------------

python utils/compute_domain_plddt.py \
    "$PARQUET" \
    "$OUTPUT_DIR" \
    $PILOT_FLAG
