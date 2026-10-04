"""Check CIPS and PCM survey files listed in the master file index.

Mirrors ``file-index.ipynb``: load the index (leaving out ``--skip-years``),
fix filenames, copy the existing files into ``<output_dir>/raw_data``, then
write one report per data type to ``<output_dir>/checked-cips.xlsx`` /
``checked-pcm.xlsx``, and the index as JSON to ``<output_dir>/file_index.json``.
Finally ``SyncData`` puts each segment's CIPS and PCM JSON in the same
direction (rewriting them in place) and writes ``<output_dir>/sync-report.xlsx``.

Example:
    uv run main.py                     # check both CIPS and PCM, skip 2021
    uv run main.py --type cips         # CIPS check + clean only
    uv run main.py --skip-years        # process every year
    uv run main.py -y 2021 2022        # skip 2021 and 2022
    uv run main.py --no-sync           # leave the normalized JSON order as is
"""

import os
import argparse

import pandas as pd

from corrosions.sync import SyncData
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
        "-y",
        "--skip-years",
        nargs="*",
        type=int,
        default=[2021],
        help="Survey years to leave out; pass no value to process every year "
        "(default: %(default)s)",
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
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip syncing the CIPS/PCM survey direction (it rewrites the "
        "normalized JSON files in place)",
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

    fi = FileIndex(
        filepath=args.index,
        drop_columns=args.drop_columns,
        skip_years=args.skip_years,
        verbose=True,
    )
    # rebuild() checks which files exist and runs fix() itself
    fi.rebuild(source_dir=args.source_dir, output_dir=output_dir)

    if args.type in ("all", "cips"):
        checked = fi.check_cips_file(data_dir=data_dir, n_jobs=args.n_jobs)
        save_report(checked, os.path.join(output_dir, "checked-cips.xlsx"))

    if args.type in ("all", "pcm"):
        checked = fi.check_pcm_file(data_dir=data_dir, n_jobs=args.n_jobs)
        save_report(checked, os.path.join(output_dir, "checked-pcm.xlsx"))

    index_json = fi.to_json(output_dir)
    print(f"Index JSON -> {index_json}")
    print(
        "Rows left out (no normalized CIPS/PCM file) -> "
        f"{os.path.join(output_dir, FileIndex.EXCLUDED_JSON_FILENAME)}"
    )

    if not args.no_sync:
        sync_index(index_json, os.path.join(output_dir, "sync-report.xlsx"))


def sync_index(index_json: str, report_path: str) -> None:
    """Sync CIPS/PCM survey direction and write the per-segment report.

    Only the segments in ``index_json`` are synced, i.e. those with both a
    normalized CIPS and PCM file; with ``--type cips`` / ``pcm`` there are none.
    """
    report = SyncData(index_json, verbose=True).sync()
    report.to_excel(report_path, index=False)

    far = int((report["start_gap_m"] > 200).sum())
    print(
        f"Synced {int(report['reason'].isna().sum())}/{len(report)} segments "
        f"(reversed {int(report['cips_reversed'].sum())} CIPS, "
        f"{int(report['pcm_reversed'].sum())} PCM; {far} with CIPS/PCM starts "
        f"> 200 m apart) -> {report_path}"
    )


if __name__ == "__main__":
    main()
