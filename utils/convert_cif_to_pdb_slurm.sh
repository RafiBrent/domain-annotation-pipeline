#!/bin/bash
#SBATCH --job-name=convert_mgnify_to_pdb
#SBATCH --partition=cpu
#SBATCH --time=01:00:00
#SBATCH --mem=4G
#SBATCH --output=logs/mgnify_conversion_chunk_%A_%a.log
#SBATCH --error=logs/mgnify_conversion_chunk_%A_%a.log
#SBATCH --array=0-99

FILELIST=/net/scratch/rib7/domain-annotation-pipeline/mgnify_cif_files.txt
INPUT_BASE=/squash/mgnify_distill_rf3/cifs
OUTPUT_BASE=/net/scratch/rib7/mgnify_distill_pdbs

# Must contain atomworks
source /home/rib7/protocols/atomworks-dev/.venv/bin/activate

python convert_cif_to_pdb.py \
    "$FILELIST" \
    "$INPUT_BASE" \
    "$OUTPUT_BASE"