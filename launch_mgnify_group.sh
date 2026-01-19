#!/bin/bash
#SBATCH --job-name=mgnify_cath_annotations
#SBATCH --partition=cpu
#SBATCH --time=24:00:00
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
rm -rf work
echo "Cleaned up work directory at: $(date)"

# Create segmented PDB files to facilitate foldseek
mkdir -p reconstructed_domains
python ${REPO_ROOT}/utils/reconstruct_chopped_pdbs.py \
    --transformed-consensus results/${PROJECT_NAME}/transformed_consensus.tsv \
    --md5-file results/${PROJECT_NAME}/all_md5.tsv \
    --id-file ${ID_FILE} \
    --output reconstructed_domains \
    --validate

echo "Reconstructed segmented PDB files at: $(date)"

# Setup for Foldseek
mkdir -p foldseek/group_${GROUP_NUM}
cd foldseek/group_${GROUP_NUM}
mkdir -p output

# Create foldseek database from reconstructed domains
$FOLDSEEK_DIR/foldseek createdb ../../reconstructed_domains/ query_db

echo "Created Foldseek database at: $(date)"

# Search against CATH database
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

echo "Completed Foldseek search at: $(date)"

# Aggregate and format results
$FOLDSEEK_DIR/foldseek convertalis \
    query_db \
    ${REPO_ROOT}/cath_v4_4_0_s95_foldseekdb/cath_v4_4_0_s95_db \
    output/foldseek_output_db \
    foldseek_output.m8 \
    --format-output "query,target,fident,evalue,qlen,tlen,qtmscore,ttmscore,qcov,tcov"

# Assign CATH domains based on Foldseek results
python3 ${REPO_ROOT}/foldseek/bin/format_fs_output.py \
    -i foldseek_output.m8 \
    -c ${REPO_ROOT}/domain_lookup/CathDomainList.S95.v4.4.0 \
    -o output/parsed_results.tsv

cp output/parsed_results.tsv ${FINAL_SAVE_DIR}/group_${GROUP_NUM}_cath_annotations.tsv

# Clean up reconstructed domains
rm -rf ../../reconstructed_domains

echo "Full domain segmentation and CATH pipeline completed for group ${GROUP_NUM} at: $(date)"