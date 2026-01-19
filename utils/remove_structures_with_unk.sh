#!/bin/bash
#SBATCH --job-name=mgnify_skip_unks
#SBATCH --partition=cpu
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --output=logs/mgnify_skip_unks_%A_%a.log
#SBATCH --error=logs/mgnify_skip_unks_%A_%a.log
#SBATCH --array=0-19

INPUT_BASE=/net/scratch/rib7/domain-annotation-pipeline/examples/full_mgnify_with_unk/full_mgnify_group.txt
OUTPUT_DIR=/net/scratch/rib7/domain-annotation-pipeline/examples/full_mgnify_without_unk

# Must contain atomworks
source /home/rib7/protocols/atomworks-dev/.venv/bin/activate

python /net/scratch/rib7/domain-annotation-pipeline/utils/remove_structures_with_unk.py \
    "$INPUT_BASE" \
    "$OUTPUT_DIR" \