#!/bin/bash
#SBATCH --job-name=chop_domains
#SBATCH --partition=cpu
#SBATCH --time=06:00:00
#SBATCH --mem=32G
#SBATCH --output=/net/scratch/ncorley/teddimonomore/logs/chop_domains_%A_%a.log
#SBATCH --error=/net/scratch/ncorley/teddimonomore/logs/chop_domains_%A_%a.log
#SBATCH --array=0-199

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PARQUET=/projects/ml/latent_design/latent_train_parquet_files/june_and_december_2025_mgnify_domain_monomers.parquet
OUTPUT_DIR=/net/scratch/ncorley/teddimonomore/monomer_files/

# Pilot mode: restrict to first 1000 rows for testing.
# When true, submit with: sbatch --array=0-9 chop_domains_slurm.sh
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

python utils/chop_domains.py \
    "$PARQUET" \
    "$OUTPUT_DIR" \
    $PILOT_FLAG
