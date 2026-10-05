"""Check CIPS, PCM and ACVG/DCVG survey files listed in the file indexes.

Mirrors ``file-index.ipynb``: load the index (leaving out ``--skip-years``),
fix filenames, copy the existing files into ``<output_dir>/raw_data``, then
write one report per data type to ``<output_dir>/checked-cips.xlsx`` /
``checked-pcm.xlsx``, and the index as JSON to ``<output_dir>/file_index.json``.
``to_json`` also syncs each segment's CIPS and PCM files to the same
direction (rewriting the normalized JSON and Excel in place); its report goes
to ``<output_dir>/sync-report.xlsx``. Last, the ACVG/DCVG anomalies (their own
index, ``--acvg-index``) are split per segment into
``<output_dir>/raw_data/<year>/ACVG_DCVG/`` and linked to the file index CSV
(column ``ACVG_DCVG``), cleaned and normalized; their report goes to
``<output_dir>/acvg-dcvg-report.xlsx``, and each segment's normalized ACVG/DCVG
file is added to ``file_index.json`` (``acvg_dcvg_normalized_file``).

Example:
    uv run main.py                     # check both CIPS and PCM, skip 2021
    uv run main.py --type cips         # CIPS check + clean only
    uv run main.py --skip-years        # process every year
    uv run main.py -y 2021 2022        # skip 2021 and 2022
    uv run main.py --no-sync           # leave the normalized JSON order as is
    uv run main.py --type acvg         # ACVG/DCVG only (uses the normalized CIPS
                                       # files of an earlier run)
"""

import os
import argparse

import pandas as pd

from corrosions.data.acvg_dcvg import AcvgDcvg
from corrosions.data.file_index import FileIndex
from corrosions.utils.path_utils import resolve_output_dir


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="Corrosion file checker",
        description="Check CIPS, PCM and ACVG/DCVG files listed in the file indexes.",
    )
    parser.add_argument(
        "-i",
        "--index",
        default="IDDA - PCM CIPS File List.xlsx",
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
        choices=["all", "cips", "pcm", "acvg"],
        default="all",
        help="Which data type to check (default: %(default)s)",
    )
    parser.add_argument(
        "--acvg-index",
        default="IDDA - ACVG FIle List.xlsx",
        help="ACVG/DCVG index with Year and Filename (default: %(default)s)",
    )
    parser.add_argument(
        "--acvg-dir",
        default=AcvgDcvg.DEFAULT_DATA_DIR,
        help="Folder of the yearly ACVG/DCVG workbooks (default: %(default)s)",
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

    # --type acvg runs no CIPS/PCM check, so to_json() would write an empty
    # file_index.json over the one from the last full run.
    if args.type != "acvg":
        # to_json() also syncs the CIPS/PCM direction, unless --no-sync.
        index_json = fi.to_json(output_dir, sync=not args.no_sync, n_jobs=args.n_jobs)
        print(f"Index JSON -> {index_json}")
        print(
            "Rows left out (no normalized CIPS/PCM file) -> "
            f"{os.path.join(output_dir, FileIndex.EXCLUDED_JSON_FILENAME)}"
        )

        if fi.sync_report is not None:
            save_sync_report(
                fi.sync_report, os.path.join(output_dir, "sync-report.xlsx")
            )

    if args.type in ("all", "acvg"):
        index_csv = os.path.join(output_dir, f"file_index_{fi.filename_slug}.csv")
        try:
            acvg = run_acvg(args, index_csv, output_dir)
        except FileNotFoundError as e:
            # --type all still finishes on a machine without the ACVG/DCVG data
            if args.type == "acvg":
                raise
            print(f"ACVG/DCVG skipped: {e}")
        else:
            # file_index.json was written before the ACVG/DCVG step; add the
            # normalized ACVG/DCVG file and anomaly count of each segment to it
            files = acvg.normalized_files()
            fi.assign_acvg_dcvg(files, output_dir, counts=acvg.anomaly_counts())
            print(
                f"{FileIndex.ACVG_DCVG_FILE_KEY}: {len(files)} segments -> "
                f"{os.path.join(output_dir, FileIndex.JSON_FILENAME)}"
            )


# Sheet of acvg-dcvg-report.xlsx listing the index rows without a file.
UNLINKED_SHEET = "segments without ACVG-DCVG"


def run_acvg(args: argparse.Namespace, index_csv: str, output_dir: str) -> AcvgDcvg:
    """Split the ACVG/DCVG anomalies per segment and link them to the index CSV.

    ``index_csv`` is the CSV ``FileIndex.rebuild`` saved; it gets the
    ``ACVG_DCVG`` column. Matching uses the normalized CIPS tracks under
    ``<cwd>/output/normalize`` (from this run, or an earlier one with
    ``--type acvg``). Each extracted file is then cleaned and normalized
    (``<output_dir>/cleaned/<year>/ACVG_DCVG`` and
    ``<cwd>/output/normalize/acvg_dcvg``; every anomaly takes the
    ``real_distance`` and ``condition`` of its nearest CIPS reading). The
    per-group report, the per-file report, the load issues and the index
    rows without an ACVG/DCVG file (``unlinked_segments``, with the reason)
    are written to ``<output_dir>/acvg-dcvg-report.xlsx``.
    """
    acvg = AcvgDcvg(
        args.acvg_index,
        data_dir=args.acvg_dir,
        skip_years=args.skip_years,
        verbose=True,
    )
    acvg.load().match(index_csv).rebuild(output_dir=output_dir)
    acvg.clean().normalize()
    groups = acvg.assign_index()
    unlinked = acvg.unlinked_segments()

    report_path = os.path.join(output_dir, "acvg-dcvg-report.xlsx")
    with pd.ExcelWriter(report_path) as writer:
        groups.drop(columns=["group"]).to_excel(
            writer, sheet_name="groups", index=False
        )
        if acvg.file_report is not None:
            acvg.file_report.to_excel(writer, sheet_name="files", index=False)
        if acvg.load_report is not None:
            acvg.load_report.to_excel(writer, sheet_name="load issues", index=False)
        # Excel sheet names cannot contain "/"
        unlinked.to_excel(writer, sheet_name=UNLINKED_SHEET, index=False)

    methods = groups["method"].value_counts().to_dict()
    linked = groups["index_row"].dropna().nunique()
    reasons = unlinked["reason"].value_counts().to_dict()
    files = acvg.file_report
    normalized = 0 if files is None else int(files["normalized_file"].notna().sum())
    print(
        f"ACVG/DCVG: {len(groups)} groups ({methods}), "
        f"{len(acvg.output_files)} files ({normalized} normalized), "
        f"{linked} index rows linked; "
        f"{len(unlinked)} without ACVG/DCVG ({reasons}) -> {report_path}"
    )
    return acvg


def save_sync_report(report: pd.DataFrame, report_path: str) -> None:
    """Write the per-segment sync report and print a summary.

    Rows are sorted by ``start_gap_m``, largest first (skipped segments last),
    so the CIPS/PCM pairs whose start points are furthest apart come first;
    the report has the full JSON/Excel paths of both files to inspect them.

    Only the segments in ``file_index.json`` are synced, i.e. those with both
    a normalized CIPS and PCM file; with ``--type cips`` / ``pcm`` there are none.
    """
    report = report.sort_values("start_gap_m", ascending=False, na_position="last")
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
