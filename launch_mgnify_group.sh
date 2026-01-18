#!/bin/bash
#SBATCH --job-name=afdb_annotate
#SBATCH --partition=cpu
#SBATCH --time=12:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=1
#SBATCH --output=logs/afdb_group_%A.out
#SBATCH --error=logs/afdb_group_%A.err

# Usage: sbatch run_group.sh <group_number>
# Example: sbatch run_group.sh 0

GROUP_NUM=${1:-0}
REPO_ROOT=/net/scratch/rib7/domain-annotation-pipeline

echo "Starting domain annotation pipeline for group ${GROUP_NUM}"
echo "Job ID: ${SLURM_JOB_ID}"
echo "Started at: $(date)"

# Create logs directory if it doesn't exist
mkdir -p logs

# Run the pipeline
nextflow run ${REPO_ROOT}/workflows/annotate.nf \
    -c ${REPO_ROOT}/nextflow.config \
    -profile largescale,singularity \
    --singularity_image_dir ${REPO_ROOT}/apptainer \
    --pdb_directory /squash/mgnify_pdbs \
    --heavy_chunk_size 10000 --light_chunk_size 10000 --chunk_size 10000 \
    --slurm_queue_gpu gpu-bf --slurm_time_gpu "6h" \
    --project_name full_mgnify_group_${GROUP_NUM} \
    --uniprot_csv_file ${REPO_ROOT}/examples/mgnify_full_group_${GROUP_NUM}.txt

echo "Finished at: $(date)"
