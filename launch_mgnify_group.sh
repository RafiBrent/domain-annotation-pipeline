#!/bin/bash
#SBATCH --job-name=mgnify_cath_annotations
#SBATCH --partition=cpu
#SBATCH --time=2-00:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=1
#SBATCH --output=/net/scratch/rib7/all_mgnify_domain_results/logs/mgnify_group_%A.log
#SBATCH --error=/net/scratch/rib7/all_mgnify_domain_results/logs/mgnify_group_%A.log

# Usage: sbatch run_group.sh <group_number>
# Example: sbatch run_group.sh 0

echo "Initial file count: $(df -i /net/scratch/$USER)"
echo "Initial memory usage: $(df -h /net/scratch/$USER)"

GROUP_NUM=${1:-0}
REPO_ROOT=/net/scratch/rib7/domain-annotation-pipeline
FINAL_SAVE_DIR=/net/scratch/rib7/all_mgnify_domain_results
FOLDSEEK_DIR=/software/foldseek

PROJECT_NAME=full_mgnify_group_${GROUP_NUM}
ID_FILE=${REPO_ROOT}/examples/full_mgnify_without_unk/full_mgnify_group_${GROUP_NUM}.txt

echo "Starting domain annotation pipeline for group ${GROUP_NUM}"
echo "Job ID: ${SLURM_JOB_ID}"
echo "Started at: $(date)"

# Setup for domain segmentation
mkdir -p /net/scratch/$USER/mgnify_domain_segmentation
cd /net/scratch/$USER/mgnify_domain_segmentation
source ${REPO_ROOT}/.venv/bin/activate

# Run the pipeline
nextflow run ${REPO_ROOT}/workflows/annotate.nf \
    -c ${REPO_ROOT}/nextflow.config \
    -profile largescale,singularity \
    --singularity_image_dir ${REPO_ROOT}/apptainer \
    --pdb_directory /squash/mgnify_pdbs \
    --heavy_chunk_size 10000 --light_chunk_size 10000 --chunk_size 10000 \
    --slurm_queue_gpu gpu-bf --slurm_time_gpu "6h" \
    --project_name ${PROJECT_NAME} \
    --uniprot_csv_file ${ID_FILE}

cp results/${PROJECT_NAME}/final_domain_annotations.tsv ${FINAL_SAVE_DIR}/group_${GROUP_NUM}_final_domain_annotations.tsv
echo "Finished domain segmentation at: $(date)"

echo "Peak file count: $(df -i /net/scratch/$USER)"
echo "Peak memory usage: $(df -h /net/scratch/$USER)"

# Remove workdir to save disk space
# rm -rf work
# echo "Cleaned up work directory at: $(date)"

# Setup for parallel reconstruction + foldseek processing
WORKDIR=$(pwd)
CHUNK_SIZE=20000

# Exclude certain nodes
EXCLUDE_NODES="c1306"
mkdir -p chunks logs

# Copy the ID file for workers to access (they need the path mapping)
cp ${ID_FILE} full_id_file.txt

# Count total domains from transformed_consensus.tsv (subtract 1 for header)
TOTAL_DOMAINS=$(($(wc -l < results/${PROJECT_NAME}/transformed_consensus.tsv) - 1))
NUM_CHUNKS=$(( (TOTAL_DOMAINS + CHUNK_SIZE - 1) / CHUNK_SIZE ))
ARRAY_MAX=$((NUM_CHUNKS - 1))

echo "Total domains: ${TOTAL_DOMAINS}"
echo "Chunk size: ${CHUNK_SIZE}"
echo "Number of chunks: ${NUM_CHUNKS} (array indices 0-${ARRAY_MAX})"

# Submit array job - each task handles reconstruction + foldseek for its chunk
echo "Submitting reconstruction + foldseek array job at: $(date)"
if [ -n "$EXCLUDE_NODES" ]; then
    echo "Excluding nodes: ${EXCLUDE_NODES}"
fi
ARRAY_JOB_ID=$(sbatch --parsable --wait \
    --array=0-${ARRAY_MAX} \
    --job-name=cath_g${GROUP_NUM} \
    ${EXCLUDE_NODES:+--exclude=${EXCLUDE_NODES}} \
    --output="${WORKDIR}/logs/chunk_%A_%a.log" \
    --error="${WORKDIR}/logs/chunk_%A_%a.log" \
    ${REPO_ROOT}/utils/run_foldseek_chunk.sh "${WORKDIR}" "${REPO_ROOT}" "${PROJECT_NAME}" "${CHUNK_SIZE}")

ARRAY_EXIT_CODE=$?
echo "Array job ${ARRAY_JOB_ID} completed with exit code ${ARRAY_EXIT_CODE} at: $(date)"

if [ $ARRAY_EXIT_CODE -ne 0 ]; then
    echo "Warning: Some chunk jobs may have failed. Check logs in ${WORKDIR}/logs/"
    # Continue anyway to concatenate whatever results we have
fi

echo "All chunks processed. Concatenating results at: $(date)"

# Concatenate all parsed_results.tsv files
RESULT_COUNT=0
FIRST_FILE=1

find chunks -path '*/output/parsed_results.tsv' | sort |
while IFS= read -r RESULT_FILE; do
    if [ "$FIRST_FILE" -eq 1 ]; then
        # Include header from first file
        cat "$RESULT_FILE" > combined_parsed_results.tsv
        FIRST_FILE=0
    else
        # Skip header (first line) for subsequent files
        tail -n +2 "$RESULT_FILE" >> combined_parsed_results.tsv
    fi
    RESULT_COUNT=$((RESULT_COUNT + 1))
done

if [ "$RESULT_COUNT" -eq 0 ]; then
    echo "Error: No parsed_results.tsv files found"
    exit 1
fi

echo "Found ${RESULT_COUNT} result files to concatenate"

FINAL_COUNT=$(($(wc -l < combined_parsed_results.tsv) - 1))
echo "Combined results contain ${FINAL_COUNT} annotations"

# Save only the concatenated result to final_save_dir
cp combined_parsed_results.tsv ${FINAL_SAVE_DIR}/group_${GROUP_NUM}_cath_annotations.tsv
echo "Saved concatenated results to ${FINAL_SAVE_DIR}/group_${GROUP_NUM}_cath_annotations.tsv"

# Clean up chunk directories (optional - uncomment to enable)
# rm -rf chunks

echo "Full domain segmentation and CATH pipeline completed for group ${GROUP_NUM} at: $(date)"