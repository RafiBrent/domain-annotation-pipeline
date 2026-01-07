#!/usr/bin/env python3

import os
import sys
from pathlib import Path

from atomworks.io.utils.io_utils import load_any, to_pdb_string

def main():



    if len(sys.argv) != 4:
        print(
            "Usage: convert_cif_to_pdb.py "
            "<filelist> <input_base> <output_base>"
        )
        sys.exit(1)

    filelist_path = Path(sys.argv[1])
    input_base = Path(sys.argv[2]).resolve()
    output_base = Path(sys.argv[3]).resolve()

    task_id = int(os.environ["SLURM_ARRAY_TASK_ID"])
    num_tasks = int(os.environ["SLURM_ARRAY_TASK_COUNT"])

    with filelist_path.open() as f:
        lines = f.readlines()

    total_files = len(lines)

    # total_files = len(lines)
    files_per_task = total_files // num_tasks
    remainder = total_files % num_tasks

    # Start/end for this task
    start_idx = task_id * files_per_task + min(task_id, remainder)
    end_idx = start_idx + files_per_task
    if task_id < remainder:
        end_idx += 1  # first `remainder` tasks get 1 extra file

    task_lines = lines[start_idx:end_idx]


    for line in task_lines:
        cif_path = Path(line.strip()).resolve()

        try:

            rel_path = cif_path.relative_to(input_base)
            out_path = (
                output_base
                / rel_path.parent
                / rel_path.name.replace(".cif.gz", ".pdb")
            )

            if out_path.exists():
                continue

            aa = load_any(cif_path)

            out_path.parent.mkdir(parents=True, exist_ok=True)

            with open(out_path, "w") as f:
                f.write(to_pdb_string(aa))

        except Exception as e:
            print(f"[ERROR] {cif_path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
