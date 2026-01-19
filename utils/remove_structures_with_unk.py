#!/usr/bin/env python3

import os
import sys
from pathlib import Path

from atomworks.io.utils.io_utils import load_any

def main():

    if len(sys.argv) != 3:
        print(
            "Usage: identify_structures_with_unk.py "
            "input_basename output_dir"
        )
        sys.exit(1)

    input_basename = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()

    task_id = int(os.environ["SLURM_ARRAY_TASK_ID"])

    task_file_path = input_basename.parent / f"{input_basename.stem}_{task_id}{input_basename.suffix}"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / task_file_path.name

    with task_file_path.open() as f:
        task_lines = f.readlines()

    for line in task_lines:
        pdb_path = Path(line.strip()).resolve()

        try:
            aa = load_any(pdb_path)

        except Exception as e:
            print(f"[ERROR] {pdb_path}: {e}", file=sys.stderr)
        
        if not (aa.res_name == "UNK").any():
            with open(output_path, "a") as out_f:
                out_f.write(f"{pdb_path}\n")


if __name__ == "__main__":
    main()
