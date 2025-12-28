# Apptainer Quick Start Guide

This guide will help you quickly build and use the Apptainer containers for the domain annotation pipeline.

## TL;DR - Fast Build

```bash
cd /home/rib7/protocols/domain-annotation-pipeline/apptainer
./build_all.sh          # Builds the 3 main containers
./build_all.sh --all    # Builds all 7 containers
```

The script can be run from anywhere - it automatically finds the spec files.

## What Gets Built

### Main Containers (used by workflow):
1. **cath-af-cli.sif** - CATH-AF-CLI domain annotation
2. **script.sif** - Python processing scripts
3. **ted-tools.sif** - TED domain segmentation

### Additional Containers:
4. **chainsaw.sif** - Chainsaw domain segmentation
5. **merizo.sif** - Merizo domain prediction
6. **pdb-tools.sif** - PDB manipulation tools
7. **unidoc.sif** - UniDoc domain prediction

## Manual Build (Individual Containers)

If you prefer to build specific containers:

```bash
# From the apptainer directory
cd /home/rib7/protocols/domain-annotation-pipeline

# Main containers
sudo apptainer build apptainer/cath-af-cli.sif apptainer/cath-af-cli.spec
sudo apptainer build apptainer/script.sif apptainer/script.spec
sudo apptainer build apptainer/ted-tools.sif apptainer/ted-tools.spec

# Additional containers
sudo apptainer build apptainer/chainsaw.sif apptainer/chainsaw.spec
sudo apptainer build apptainer/merizo.sif apptainer/merizo.spec
sudo apptainer build apptainer/pdb-tools.sif apptainer/pdb-tools.spec
sudo apptainer build apptainer/unidoc.sif apptainer/unidoc.spec
```

**Note:** The `script` container must be built from the repository root (as shown above) because it needs to copy files from `docker/script/`.

## Using the Containers with Nextflow

Once built, use them with the workflow:

```bash
nextflow run workflows/annotate.nf \
    -profile singularity \
    --singularity_image_dir "/home/rib7/protocols/domain-annotation-pipeline/apptainer"
```

## Testing the Build

Verify containers work correctly:

```bash
cd /home/rib7/protocols/domain-annotation-pipeline/apptainer

# Test cath-af-cli
apptainer exec cath-af-cli.sif cath-af-cli --help

# Test script container
apptainer exec script.sif python --version
apptainer exec script.sif ls -la /app/

# Test ted-tools
apptainer exec ted-tools.sif ls -la /app/ted-tools/ted_consensus_1.0/
```

## Build Time Estimates

- **cath-af-cli:** ~15-20 minutes (builds STRIDE, clones and installs cath-alphaflow)
- **script:** ~5 minutes (Python packages only)
- **ted-tools:** ~20-30 minutes (large setup.sh script, ML dependencies)
- **chainsaw:** ~10-15 minutes (builds STRIDE)
- **merizo:** ~10 minutes (ML packages)
- **pdb-tools:** ~3 minutes (minimal dependencies)
- **unidoc:** ~10 minutes (downloads pre-built binaries)

**Total for all 7:** ~60-90 minutes (depends on network speed)
**Total for main 3:** ~40-55 minutes

## Troubleshooting

### "Permission denied"
```bash
# Use sudo
sudo apptainer build container.sif container.spec

# Or use fakeroot (if available)
apptainer build --fakeroot container.sif container.spec
```

### "No space left on device"
```bash
# Set temp directory to location with more space
export APPTAINER_TMPDIR=/scratch/$USER/tmp
mkdir -p $APPTAINER_TMPDIR
```

### Network timeouts during git clone
```bash
# Increase git timeout
git config --global http.postBuffer 524288000
```

### UniDoc won't run (ARM architecture)
The unidoc container requires x86_64. On ARM systems:
```bash
# Check your architecture
uname -m

# If not x86_64, you may need to:
# 1. Build on an x86_64 node
# 2. Use remote builder: apptainer build --remote unidoc.sif unidoc.spec
# 3. Skip UniDoc if not needed for your workflow
```

## Storage Requirements

Each container size (approximate):
- cath-af-cli: ~1.5 GB
- script: ~800 MB
- ted-tools: ~4 GB (largest - includes ML models)
- chainsaw: ~1 GB
- merizo: ~2 GB
- pdb-tools: ~500 MB
- unidoc: ~1.2 GB

**Total:** ~11 GB for all containers

Ensure you have at least **15 GB** free space to account for build temporaries.

## What's Different from Docker?

These Apptainer specs reproduce the Docker containers **exactly**:
- Same base images (python:3.10-slim, python:3.11-slim, etc.)
- Same system packages
- Same Python packages
- Same git repositories cloned
- Same build steps
- Same working directories

See [DOCKER_TO_APPTAINER_MAPPING.md](DOCKER_TO_APPTAINER_MAPPING.md) for detailed line-by-line verification.

## Next Steps

1. **Build the containers** (use `build_all.sh` for convenience)
2. **Test them** (run the test commands above)
3. **Use with Nextflow** (pass `--singularity_image_dir` parameter)

For detailed information:
- [README.md](README.md) - Complete documentation
- [DOCKER_TO_APPTAINER_MAPPING.md](DOCKER_TO_APPTAINER_MAPPING.md) - Verification details
