#!/bin/bash
#
# Build all Apptainer containers for the domain annotation pipeline
# Can be run from any location - it will find the spec files automatically
#

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

echo "Apptainer specs: ${SCRIPT_DIR}"
echo "Output directory: ${SCRIPT_DIR}"
echo ""

# Check if apptainer/singularity is available
if ! command -v apptainer &> /dev/null && ! command -v singularity &> /dev/null; then
    echo -e "${RED}Error: Neither 'apptainer' nor 'singularity' command found${NC}"
    echo "Please install Apptainer or Singularity first"
    exit 1
fi

# Use apptainer if available, otherwise singularity
if command -v apptainer &> /dev/null; then
    CONTAINER_CMD="apptainer"
else
    CONTAINER_CMD="singularity"
fi

echo -e "${GREEN}Using: ${CONTAINER_CMD}${NC}"
echo ""

# Define containers to build
# The three main containers used by the workflow
MAIN_CONTAINERS=(
    "cath-af-cli"
    "script"
    "ted-tools"
)

# Additional containers that may be used
ADDITIONAL_CONTAINERS=(
    "chainsaw"
    "merizo"
    "pdb-tools"
    "unidoc"
)

# Parse command line arguments
BUILD_ALL=false
BUILD_MAIN_ONLY=true

if [ "$1" == "--all" ]; then
    BUILD_ALL=true
    BUILD_MAIN_ONLY=false
fi

# Function to build a container
build_container() {
    local name=$1
    local spec_file="${SCRIPT_DIR}/${name}.spec"
    local sif_file="${SCRIPT_DIR}/domain-annotation-pipeline-${name}_latest.sif"

    echo -e "${YELLOW}Building domain-annotation-pipeline-${name}_latest.sif...${NC}"

    if [ ! -f "${spec_file}" ]; then
        echo -e "${RED}✗ Spec file not found: ${spec_file}${NC}"
        return 1
    fi

    # For containers that need files from docker/ directory, cd to repo root
    # (specifically the 'script' container)
    local build_dir="${SCRIPT_DIR}"
    if [ "${name}" == "script" ]; then
        build_dir="${REPO_ROOT}"
        echo "  (building from repo root for file dependencies)"
    fi

    if (cd "${build_dir}" && ${CONTAINER_CMD} build "${sif_file}" "${spec_file}"); then
        echo -e "${GREEN}✓ domain-annotation-pipeline-${name}_latest.sif built successfully${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed to build domain-annotation-pipeline-${name}_latest.sif${NC}"
        return 1
    fi
}

# Track success/failure
SUCCESSFUL=()
FAILED=()

# Build main containers
echo -e "${GREEN}Building main containers (used by workflow)...${NC}"
echo "================================================"
for container in "${MAIN_CONTAINERS[@]}"; do
    if build_container "${container}"; then
        SUCCESSFUL+=("${container}")
    else
        FAILED+=("${container}")
    fi
    echo ""
done

# Build additional containers if requested
if [ "${BUILD_ALL}" = true ]; then
    echo -e "${GREEN}Building additional containers...${NC}"
    echo "================================================"
    for container in "${ADDITIONAL_CONTAINERS[@]}"; do
        if build_container "${container}"; then
            SUCCESSFUL+=("${container}")
        else
            FAILED+=("${container}")
        fi
        echo ""
    done
fi

# Summary
echo "================================================"
echo -e "${GREEN}Build Summary${NC}"
echo "================================================"

if [ ${#SUCCESSFUL[@]} -gt 0 ]; then
    echo -e "${GREEN}Successfully built (${#SUCCESSFUL[@]}):${NC}"
    for container in "${SUCCESSFUL[@]}"; do
        echo "  ✓ domain-annotation-pipeline-${container}_latest.sif"
    done
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Failed to build (${#FAILED[@]}):${NC}"
    for container in "${FAILED[@]}"; do
        echo "  ✗ domain-annotation-pipeline-${container}_latest.sif"
    done
fi

echo ""

if [ "${BUILD_MAIN_ONLY}" = true ]; then
    echo "Note: Only main containers were built. Use --all to build all containers."
fi

echo ""
echo "To use these containers with Nextflow:"
echo "  nextflow run workflows/annotate.nf -profile singularity \\"
echo "    --singularity_image_dir \"${SCRIPT_DIR}\""
echo ""

# Exit with error if any builds failed
if [ ${#FAILED[@]} -gt 0 ]; then
    exit 1
fi

exit 0
