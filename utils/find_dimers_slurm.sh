#!/bin/bash
#SBATCH --job-name=find_dimers
#SBATCH --partition=cpu
#SBATCH --time=04:00:00
#SBATCH --mem=32G
#SBATCH --output=/net/scratch/rib7/teddimore/logs/find_dimers_%A_%a.log
#SBATCH --error=/net/scratch/rib7/teddimore/logs/find_dimers_%A_%a.log
#SBATCH --array=0-99

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PARQUET=/projects/ml/latent_design/latent_train_parquet_files/june_and_december_2025_mgnify_domain_monomers.parquet
OUTPUT_DIR=/net/scratch/rib7/teddimore/task_parquets
OUTPUT_FINAL=/net/scratch/rib7/teddimore/teddimore_interfaces_df.parquet

# Optional: set to a directory path to save dimer CIF files to disk.
# Leave empty to disable file saving.
OUTPUT_FILE_BASE_DIR=
# OUTPUT_FILE_BASE_DIR=/net/scratch/rib7/teddimore/dimer_files

# Pilot mode: restrict to first 1000 rows for testing.
# When true, submit with: sbatch --array=0-9 find_dimers_slurm.sh
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

FILE_BASE_FLAG=""
if [ -n "$OUTPUT_FILE_BASE_DIR" ]; then
    FILE_BASE_FLAG="--output_file_base_dir $OUTPUT_FILE_BASE_DIR"
fi

# ---------------------------------------------------------------------------
# Run worker
# ---------------------------------------------------------------------------

python utils/find_dimers_in_structures.py \
    "$PARQUET" \
    "$OUTPUT_DIR" \
    $PILOT_FLAG \
    $FILE_BASE_FLAG
