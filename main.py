"""Check CIPS and PCM survey files listed in the master file index.

Mirrors ``file-index.ipynb``: load the index, fix filenames, check which files
exist, copy them into ``<output_dir>/raw_data``, then write one report per
data type to ``<output_dir>/checked-cips.xlsx`` / ``checked-pcm.xlsx``.

Example:
    uv run main.py                     # check both CIPS and PCM
    uv run main.py --type cips         # CIPS sheet/column check only
"""

import os
import argparse

import pandas as pd

from corrosions.data.file_index import FileIndex
from corrosions.utils.path_utils import resolve_output_dir


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="Corrosion file checker",
        description="Check CIPS and PCM files listed in the master file index.",
    )
    parser.add_argument(
        "-i",
        "--index",
        default="IDDA - File List.xlsx",
        help="Master Excel file index (default: %(default)s)",
    )
    parser.add_argument(
        "-s",
        "--source-dir",
        default=r"D:\Data\Data IDDA",
        help="Root of the source data tree, <Year>/<CIPS|PCM> FINAL/ (default: %(default)s)",
    )
    parser.add_argument(
        "-d",
        "--drop-columns",
        nargs="*",
        default=["Nomor Segment"],
        help="Index columns to drop after loading (default: %(default)s)",
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["all", "cips", "pcm"],
        default="all",
        help="Which data type to check (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Output root (default: <cwd>/output)",
    )
    parser.add_argument(
        "-n",
        "--n-jobs",
        type=int,
        default=8,
        help="Parallel workers, -1 for all cores (default: %(default)s)",
    )

    return parser.parse_args()


def save_report(report: pd.DataFrame, filepath: str) -> None:
    """Write a check report to Excel, flattening list cells to ``a, b`` text."""
    report = report.map(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else v)
    report.to_excel(filepath, index=False)

    n_valid = int(report["is_valid"].sum())
    print(f"{n_valid}/{len(report)} valid -> {filepath}")


def main() -> None:
    args = arguments()
    output_dir = resolve_output_dir(args.output_dir)
    data_dir = os.path.join(output_dir, "raw_data")

    fi = FileIndex(filepath=args.index, drop_columns=args.drop_columns, verbose=True)
    fi.fix().check_existing_file(data_dir=args.source_dir)
    fi.rebuild(source_dir=args.source_dir, output_dir=output_dir)

    if args.type in ("all", "cips"):
        checked = fi.check_cips_file(data_dir=data_dir, n_jobs=args.n_jobs)
        save_report(checked, os.path.join(output_dir, "checked-cips.xlsx"))

    if args.type in ("all", "pcm"):
        checked = fi.check_pcm_quality(data_dir=data_dir, n_jobs=args.n_jobs)
        save_report(checked, os.path.join(output_dir, "checked-pcm.xlsx"))


if __name__ == "__main__":
    main()
