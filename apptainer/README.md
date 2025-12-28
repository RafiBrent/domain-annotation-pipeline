# Apptainer/Singularity Container Specifications

This directory contains Apptainer spec files reverse-engineered from the Docker specifications in the `docker/` directory. These allow you to build the containers locally without authentication to the GitHub Container Registry.

## Overview

There are 7 container specifications corresponding to the Docker containers:

1. **cath-af-cli.spec** - CATH-AF-CLI domain annotation tool
2. **chainsaw.spec** - Chainsaw domain segmentation tool
3. **merizo.spec** - Merizo domain prediction tool
4. **pdb-tools.spec** - PDB file manipulation utilities
5. **script.spec** - Collection of Python processing scripts
6. **ted-tools.spec** - TED domain segmentation and consensus tools
7. **unidoc.spec** - UniDoc protein domain prediction

According to the main workflow, the three primary containers used are:
- **cath-af-cli**
- **script**
- **ted-tools**

## Building the Containers

### Prerequisites

- Apptainer/Singularity installed on your system
- Sudo/root access (required for building from spec files)
- Sufficient disk space (~5-10 GB per container)

### Build Commands

Build each container using the `apptainer build` command:

```bash
# Build all three main containers
sudo apptainer build cath-af-cli.sif cath-af-cli.spec
sudo apptainer build script.sif script.spec
sudo apptainer build ted-tools.sif ted-tools.spec

# Build additional containers if needed
sudo apptainer build chainsaw.sif chainsaw.spec
sudo apptainer build merizo.sif merizo.spec
sudo apptainer build pdb-tools.sif pdb-tools.spec
sudo apptainer build unidoc.sif unidoc.spec
```

### Build Script

For convenience, you can build all containers at once:

```bash
#!/bin/bash
# build_all.sh

CONTAINERS=(
    "cath-af-cli"
    "script"
    "ted-tools"
    "chainsaw"
    "merizo"
    "pdb-tools"
    "unidoc"
)

for container in "${CONTAINERS[@]}"; do
    echo "Building ${container}..."
    sudo apptainer build ${container}.sif ${container}.spec
    if [ $? -eq 0 ]; then
        echo "✓ ${container}.sif built successfully"
    else
        echo "✗ Failed to build ${container}.sif"
    fi
done
```

## Special Considerations

### script.spec - File Dependencies

The `script.spec` file requires copying files from the `docker/script/` directory. Build from the repository root:

```bash
cd /home/rib7/protocols/domain-annotation-pipeline
sudo apptainer build apptainer/script.sif apptainer/script.spec
```

### pdb-tools.spec - Missing File Warning

The original Dockerfile references `chop_pdbs.py` which is not present in `docker/pdb-tools/`. This file exists in `docker/script/chop_pdbs.py`. If you need this file in the pdb-tools container, you should:

1. Edit the `%files` section in `pdb-tools.spec` to uncomment the copy line
2. Or use the script container instead, which includes this file

### unidoc.spec - Platform Architecture

The UniDoc container requires **linux/amd64** architecture. The original Dockerfile specifies:
```dockerfile
FROM --platform=linux/amd64 python:3.10
```

If you're building on a different architecture (e.g., ARM64/aarch64):

**Option 1:** Build with fakeroot (no platform restriction):
```bash
apptainer build --fakeroot unidoc.sif unidoc.spec
```

**Option 2:** Use remote builder if available on your cluster:
```bash
apptainer build --remote unidoc.sif unidoc.spec
```

**Option 3:** Accept that binaries may not work on your architecture - you may need to use QEMU emulation or build on an x86_64 node.

## Container Comparison with Docker

Each Apptainer spec file matches its corresponding Dockerfile precisely:

| Container | Base Image | Key Components |
|-----------|------------|----------------|
| cath-af-cli | python:3.10-slim | STRIDE, cath-alphaflow |
| chainsaw | python:3.10-slim | chainsaw repo, STRIDE |
| merizo | python:3.10-slim | Merizo repo |
| pdb-tools | python:3.11-slim | pdb-tools package |
| script | python:3.10-slim | Custom Python scripts |
| ted-tools | python:3.10-slim | TED tools (sillitoe fork) |
| unidoc | python:3.10 | UniDoc_20250514 |

## Using the Containers with Nextflow

Once built, specify the directory containing your `.sif` files when running the workflow:

```bash
nextflow run workflows/annotate.nf -profile singularity \
    --singularity_image_dir "/path/to/apptainer"
```

For example, if you built the containers in this directory:

```bash
nextflow run workflows/annotate.nf -profile singularity \
    --singularity_image_dir "/home/rib7/protocols/domain-annotation-pipeline/apptainer"
```

## Testing the Containers

Test each container to ensure it built correctly:

```bash
# Test cath-af-cli
apptainer exec cath-af-cli.sif cath-af-cli --help

# Test script container
apptainer exec script.sif python --version

# Test ted-tools
apptainer exec ted-tools.sif ls /app/ted-tools/ted_consensus_1.0

# Test unidoc
apptainer exec unidoc.sif ./UniDoc_struct
```

## Troubleshooting

### Build Failures

**Problem:** Permission denied during build
**Solution:** Use `sudo` or `--fakeroot` flag
```bash
sudo apptainer build container.sif container.spec
# OR
apptainer build --fakeroot container.sif container.spec
```

**Problem:** Network errors during git clone or wget
**Solution:** Check internet connectivity and firewall rules

**Problem:** Out of disk space
**Solution:** Set temporary directory with more space:
```bash
export APPTAINER_TMPDIR=/path/to/large/tmp
```

### Runtime Issues

**Problem:** "command not found" when running scripts
**Solution:** Use `apptainer exec` instead of `apptainer run` and specify full paths

**Problem:** UniDoc binaries won't execute
**Solution:** Verify you're on x86_64 architecture: `uname -m`

## Maintenance

These spec files are based on the Docker specifications as of the repository state. If the Docker files are updated, the Apptainer specs should be regenerated to maintain parity.

To update:
1. Pull latest changes from the repository
2. Review changes in `docker/*/Dockerfile`
3. Update corresponding `.spec` files
4. Rebuild affected containers

## Additional Notes

- Build time varies by container (5-30 minutes each depending on network speed)
- The containers clone from upstream repositories, so builds get the latest versions
- For reproducibility, consider using specific git commits in the spec files
- Cache git clones locally to speed up rebuilds if needed
