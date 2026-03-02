# Design Document: Domain Dimer Detection Pipeline

## Overview

Processes a 13.8M-row parquet file of protein domain annotations to find co-occurring domain pairs ("dimers") within the same structure. Runs as a 100-job SLURM array. Outputs a merged parquet of dimer pairs, with an optional mode to save the two-domain AtomArrays to disk.

---

## Input Data Summary

- **Parquet**: `june_and_december_2025_mgnify_domain_monomers.parquet` (13.8M rows, 809 MB on disk, 14 row groups)
- **Unique paths**: 9.3M; of these, **3.5M (38%) have 2+ domain rows** and are the only candidates for dimer detection
- **Domains per path**: mostly 1–3; max observed is 9
- **Path format**: `/squash/mgnify_distill_rf3/cifs/e6/79/MGYP001468467970_model_0.cif.gz`
- **Chopping format**: `"21-274"` (single segment) or `"28-174_185-204"` (multiple segments, `_`-separated, both ends inclusive, match `res_id` annotation of the AtomArray)

### Column Classification

| Column | Level | Notes |
|---|---|---|
| `path` | file | shared by all domains in a structure |
| `distillation_set` | file | |
| `overall_plddt` | file | |
| `overall_pde` | file | |
| `overall_pae` | file | |
| `ptm` | file | |
| `example_id` | domain | gets `pn_unit_1_` / `pn_unit_2_` prefix |
| `chopping` | domain | |
| `domqual` | domain | |
| `cath_code` | domain | |

---

## File Layout

```
utils/
  find_dimers_in_structures.py   # Worker script called by each SLURM array task
  find_dimers_slurm.sh           # SLURM array job (--array=0-99, or 0-9 for pilot)
  collect_dimer_results.py       # Post-processing: concatenate per-job outputs
```

---

## Workflow

### Phase 1 — Array Jobs (`find_dimers_slurm.sh`, `--array=0-99`)

Each of the 100 jobs independently:

1. Reads `SLURM_ARRAY_TASK_ID` and `SLURM_ARRAY_TASK_COUNT` from the SLURM environment
2. Loads the **full parquet** into a pandas DataFrame (809 MB on disk, ~2–4 GB in RAM)
3. Identifies unique paths with **≥ 2 domain rows** (the only dimer candidates); single-domain paths are skipped as a no-op
4. Shards those ~3.5M multi-domain paths across `num_tasks` jobs using the same start/end calculation as the existing reference script:
   ```
   files_per_task = total // num_tasks
   remainder = total % num_tasks
   start = task_id * files_per_task + min(task_id, remainder)
   end = start + files_per_task + (1 if task_id < remainder else 0)
   ```
5. Filters the DataFrame to only the rows whose `path` is in the assigned shard
6. For each unique path in the shard (structure):
   - Loads the CIF/CIF.gz file via `atomworks.io.utils.io_utils.load_any`
   - Skips gracefully on load error (logs to stderr)
   - Enumerates all `(i, j)` unordered pairs of domain rows for that structure (0-indexed within the group)
   - For each pair, runs dimer detection (see below)
   - If dimer, appends a row to the per-job result list
7. Converts result list to a DataFrame; saves to `{output_dir}/task_{task_id:04d}.parquet`
   - Always writes the file (empty parquet with correct schema if no dimers found), so the collection step can reliably glob `task_*.parquet`

### Phase 2 — Collection (`collect_dimer_results.py`)

Run after all array jobs complete (manually, or via `--dependency=afterok:$JOB_ID`):

```bash
python utils/collect_dimer_results.py \
    --input_dir /net/scratch/rib7/dimer_detection/partial_outputs/ \
    --output /net/scratch/rib7/dimer_detection/dimers_final.parquet \
    --expected_tasks 100   # optional validation
```

Reads all `task_*.parquet` files, validates that the expected count is present, concatenates, and saves. The final output path is also configured as a variable in the SLURM script for documentation purposes.

---

## Pilot Mode

When `--pilot` is passed to the worker script:

- Restricts to only the **first 1000 rows** of the parquet before computing unique paths
- Expects the SLURM array to be submitted with `--array=0-9` (10 jobs)
- The script uses `SLURM_ARRAY_TASK_COUNT` for sharding, so no other changes are needed

**Pilot submission**:
```bash
# Edit PILOT=true in find_dimers_slurm.sh, then:
sbatch --array=0-9 utils/find_dimers_slurm.sh
```

(SBATCH `--array` cannot be set dynamically from within the script header, so the user must specify it on the `sbatch` command line for pilot mode.)

---

## Dimer Detection Logic

```python
def parse_chopping(chopping: str) -> list[tuple[int, int]]:
    # "28-174_185-204" → [(28, 174), (185, 204)]
    return [(int(a), int(b)) for seg in chopping.split("_") for a, b in [seg.split("-")]]

def get_domain_ca_mask(aa: AtomArray, chopping: str) -> np.ndarray:
    ranges = parse_chopping(chopping)
    mask = np.zeros(len(aa), dtype=bool)
    for start, end in ranges:
        mask |= (aa.res_id >= start) & (aa.res_id <= end)
    return mask & (aa.atom_name == "CA")

def is_dimer(aa: AtomArray, chopping_a: str, chopping_b: str) -> bool:
    ca_a = aa[get_domain_ca_mask(aa, chopping_a)]
    ca_b = aa[get_domain_ca_mask(aa, chopping_b)]
    if len(ca_a) == 0 or len(ca_b) == 0:
        return False

    # Build CellList over domain B's CA coords; query each CA in A
    cell_list = CellList(ca_b.coord, cell_size=10.0)
    contacts = cell_list.get_atoms(ca_a.coord, radius=10.0)
    # contacts[i] = array of indices into ca_b within 10 Å of ca_a[i]

    a_contacting = sum(1 for c in contacts if len(c) > 0)
    b_contacted = len({idx for c in contacts for idx in c})
    return a_contacting >= 4 and b_contacted >= 4
```

**Note on CellList**: for typical domain sizes (50–300 CAs), the speedup from CellList vs. a numpy pairwise `cdist` is modest. CellList is used as specified, but `scipy.spatial.distance.cdist` is a valid fallback if the biotite CellList API differs from the above pseudocode.

---

## Output DataFrame Schema

One row per detected dimer pair.

**Without `--output_file_base_dir`** (no files saved):

```
path
distillation_set
overall_plddt, overall_pde, overall_pae, ptm
pn_unit_1_example_id, pn_unit_1_chopping, pn_unit_1_domqual, pn_unit_1_cath_code
pn_unit_2_example_id, pn_unit_2_chopping, pn_unit_2_domqual, pn_unit_2_cath_code
```

**With `--output_file_base_dir`** (dimer files saved):

```
full_structure_path     ← renamed from "path"
path                    ← path to the saved dimer CIF file
distillation_set
overall_plddt, overall_pde, overall_pae, ptm
pn_unit_1_example_id, pn_unit_1_chopping, pn_unit_1_domqual, pn_unit_1_cath_code
pn_unit_2_example_id, pn_unit_2_chopping, pn_unit_2_domqual, pn_unit_2_cath_code
```

The `pn_unit_1_*` and `pn_unit_2_*` columns are internally consistent: all `pn_unit_1_` values come from the same original row, and all `pn_unit_2_` values from the other. `pn_unit_1_*` always corresponds to chain A (domain index i in the saved file); `pn_unit_2_*` always corresponds to chain B (domain index j).

---

## Output File Naming (when `--output_file_base_dir` is set)

**Format**: CIF via `atomworks.io.utils.io_utils.to_cif_file`. Extension: `.cif`.

**Shard directory auto-detection**: scan the path components for the first occurrence of two **consecutive** components that are both exactly 2 characters long. The relative output path starts from that first 2-char component onward, with the filename stem appended with `_pair{i}_{j}` and extension `.cif`.

Example:
```
Original:  /squash/mgnify_distill_rf3/cifs/e6/79/MGYP001468467970_model_0.cif.gz
                                           ^^  ^^  ← first consecutive 2-char pair
Relative:  e6/79/MGYP001468467970_model_0_pair0_1.cif
Output:    {output_file_base_dir}/e6/79/MGYP001468467970_model_0_pair0_1.cif
```

If no consecutive 2-char directory pair is found, the script raises a `ValueError`. No other fallback is needed.

The pair indices (`i`, `j`) are the 0-based indices of the two domain rows within the path group, where `i` is always the chain A domain and `j` is always the chain B domain. This ensures uniqueness across all domain pairs from the same structure and that the filename order matches the chain order inside the file.

The saved AtomArray is the concatenation of both domain subsets: all atoms from domain i (chain A) followed by all atoms from domain j (chain B). The `chain_id` annotation is set to `"A"` for all atoms from domain i and `"B"` for all atoms from domain j. No other new annotations are added.

---

## SLURM Script Configuration

`find_dimers_slurm.sh` top-of-file variables:

```bash
PARQUET=/projects/ml/latent_design/latent_train_parquet_files/june_and_december_2025_mgnify_domain_monomers.parquet
OUTPUT_DIR=/net/scratch/rib7/dimer_detection/partial_outputs
OUTPUT_FINAL=/net/scratch/rib7/dimer_detection/dimers_final.parquet
OUTPUT_FILE_BASE_DIR=   # leave empty to disable dimer file saving
PILOT=false             # set to true, then submit with --array=0-9
```

SBATCH directives:
```
#SBATCH --array=0-99
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --partition=cpu
#SBATCH --output=logs/find_dimers_%A_%a.log
#SBATCH --error=logs/find_dimers_%A_%a.log
```

Memory budget per job: ~4 GB for full parquet load + ~1 GB working memory for CIF parsing and result accumulation = 5 GB peak; 8 GB requested for headroom.
