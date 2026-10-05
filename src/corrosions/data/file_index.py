"""File index for organizing corrosion survey data files (CIPS/PCM).

Reads an Excel index of survey files, validates required columns, verifies
that referenced files exist on disk, normalizes filenames, and copies the
referenced files into a year-partitioned output directory.

Example:
    >>> from corrosions.data.file_index import FileIndex
    >>> index = FileIndex("IDDA - PCM CIPS File List.xlsx")
    >>> index.rebuild(source_dir="//nas/surveys")
    >>> index.save()
"""

import os
import json
import shutil
from typing import Self

import pandas as pd
from joblib import Parallel, delayed
from slugify import slugify

from corrosions.sync import SyncData
from corrosions.logging import logger
from corrosions.data.pcm import PCM
from corrosions.data.cips import CIPS
from corrosions.utils.path_utils import resolve_output_dir
from corrosions.utils.dataframe_utils import get_sheet_columns


class FileIndex:
    """Excel-backed index of CIPS and PCM survey files.

    Loads an Excel file that lists corrosion survey data per year, area, and
    segment, and provides helpers to validate, normalize, and copy the
    referenced files into a clean output tree.

    Attributes:
        COLUMNS (list[str]): Required columns that must be present in the source Excel.
        DATA_TYPES (tuple[str, str]): Data-type identifiers used to locate files on disk.
        JSON_FILENAME (str): Index JSON written by ``to_json``.
        EXCLUDED_JSON_FILENAME (str): JSON of the rows ``to_json`` left out.
        AREA_JSON_FILENAME (str): Per-area summary of ``JSON_FILENAME`` (see
            ``area_records``).
        NORMALIZED_FILE_KEYS (tuple[str, str]): Keys a row needs to be kept
            by ``to_json``.
        ACVG_DCVG_FILE_KEY (str): JSON key of the normalized ACVG/DCVG file
            (optional; set by ``assign_acvg_dcvg``).
        ACVG_DCVG_COLUMN (str): ``df`` column behind ``ACVG_DCVG_FILE_KEY``.
        TOTAL_ANOMALY_KEY (str): JSON key of the number of ACVG/DCVG
            anomalies (optional; set by ``assign_acvg_dcvg``).
        TOTAL_ANOMALY_COLUMN (str): ``df`` column behind
            ``TOTAL_ANOMALY_KEY``.
        filepath (str): Path to the source Excel file.
        filename (str): Base filename of the source Excel file.
        filename_slug (str): Slugified filename stem, used for output artifacts.
        df (pd.DataFrame): Working DataFrame derived from the source Excel.
        checked (bool): Whether ``check_existing_file()`` has been run.
        fixed (bool): Whether ``fix()`` has been run.
        skip_years (list[int]): Survey years removed from ``df`` at load time.
        sync_report (pd.DataFrame | None): ``SyncData`` report from the last
            ``to_json(sync=True)`` call; ``None`` until then.
        verbose (bool): If True, emit progress messages via the logger.

    Example:
        >>> index = FileIndex("IDDA - PCM CIPS File List.xlsx", verbose=True)
        >>> index.rebuild(source_dir="//nas/surveys", destination_dir="data")
        >>> index.save()
    """

    COLUMNS: list[str] = [
        "Year",
        "Area",
        "Segment",
        "Sub Segment",
        "Diameter",
        "Length",
        "Province Code",
        "ACVG/DCVG",
        "CIPS",
        "PCM",
    ]

    DATA_TYPES: tuple[str, str] = ("CIPS", "PCM")

    # Written by to_json() under its output_dir.
    JSON_FILENAME: str = "file_index.json"
    EXCLUDED_JSON_FILENAME: str = "file_index_excluded.json"
    AREA_JSON_FILENAME: str = "area.json"

    # area.json: mean of these segment percentages per area, 2 decimals.
    AREA_MEAN_KEYS: tuple[str, ...] = (
        "protected",
        "unprotected",
        "medium_to_poor",
        "medium_to_high",
    )

    # A row goes into JSON_FILENAME only when all of these are set.
    NORMALIZED_FILE_KEYS: tuple[str, str] = (
        "cips_normalized_file",
        "pcm_normalized_file",
    )

    # Optional: most rows have no ACVG/DCVG survey (see assign_acvg_dcvg).
    ACVG_DCVG_FILE_KEY: str = "acvg_dcvg_normalized_file"
    ACVG_DCVG_COLUMN: str = "normalized_acvg_dcvg_file"
    TOTAL_ANOMALY_KEY: str = "total_anomaly"
    TOTAL_ANOMALY_COLUMN: str = "acvg_dcvg_total_anomaly"

    def __init__(
        self,
        filepath: str,
        drop_columns: str | list[str] | None = None,
        skip_years: list[int] | None = None,
        verbose: bool = False,
    ):
        """Load the Excel file and prepare the working DataFrame.

        Args:
            filepath (str): Path to the source Excel file.
            drop_columns (str | list[str] | None): Column name or list of column
                names to drop after loading. Defaults to ``None``.
            skip_years (list[int] | None): Survey years to leave out, e.g.
                ``[2021]`` for exports the CIPS/PCM loaders cannot read. Their
                rows are removed from ``df`` right after loading, so every
                method (``check_existing_file``, ``rebuild``,
                ``check_pcm_file``, ``check_cips_file``, ``save``, ...)
                ignores them. Defaults to ``None`` (no year skipped).
            verbose (bool): If True, emit progress messages during ``fix()``.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
            KeyError: If any required column in ``COLUMNS`` is missing after
                ``drop_columns`` is applied.
            ValueError: If a row kept after ``skip_years`` has an empty
                ``Area``, or an empty ``Segment`` with no ``Sub Segment`` to
                fill it from, or if the filled ``Segment`` + ``Diameter`` is
                not unique (see ``validate_values``).

        Example:
            >>> index = FileIndex("IDDA - PCM CIPS File List.xlsx", drop_columns="Notes")
            >>> index = FileIndex("IDDA - PCM CIPS File List.xlsx", skip_years=[2021])
        """
        self.filepath = filepath

        if not os.path.isfile(self.filepath):
            raise FileNotFoundError(f"File not found: {self.filepath}")

        df = pd.read_excel(self.filepath)

        if isinstance(drop_columns, str):
            drop_columns = [drop_columns]
        if drop_columns is not None:
            df = df.drop(drop_columns, axis=1)

        self.filename = os.path.basename(self.filepath)
        self.filename_slug = slugify(os.path.splitext(self.filename)[0])
        self.df = df
        self.checked: bool = False
        self.fixed: bool = False
        self.verbose = verbose
        self.sync_report: pd.DataFrame | None = None
        self.validate()

        self.df["Year"] = self.df["Year"].astype(int)
        self.df["Diameter"] = self.df["Diameter"].astype(float)
        self.df["Length"] = self.df["Length"].astype(float)
        self.df["Province Code"] = self.df["Province Code"].astype(int)

        # Excel row number of each df row (1-based, after the header row), kept
        # through the skip_years filter so errors point at the source file.
        excel_rows = pd.Series(range(2, len(self.df) + 2), index=self.df.index)

        self.skip_years: list[int] = sorted(set(skip_years or []))
        if self.skip_years:
            skipped = self.df["Year"].isin(self.skip_years)
            self.df = self.df[~skipped].reset_index(drop=True)
            excel_rows = excel_rows[~skipped].reset_index(drop=True)
            if self.verbose:
                logger.info(
                    f"Skipped {int(skipped.sum())} rows from years {self.skip_years}"
                )

        self.validate_values(excel_rows)

    def validate(self) -> None:
        """Ensure that all required columns are present in ``df``.

        Raises:
            KeyError: If any column in ``COLUMNS`` is missing from ``df``.

        Example:
            >>> index.validate()
        """
        missing = [c for c in self.COLUMNS if c not in self.df.columns]
        if missing:
            raise KeyError(
                f"Columns not found: {missing}. Columns needed: {self.COLUMNS}"
            )

    def validate_values(self, excel_rows: pd.Series | None = None) -> None:
        """Ensure every row has an ``Area`` and a unique, usable ``Segment``.

        - ``Area`` must not be empty.
        - ``Segment`` may be empty only when ``Sub Segment`` is filled,
          because ``fix()`` copies ``Sub Segment`` into an empty ``Segment``.
          ``Sub Segment`` on its own may be empty.
        - The segment after that fill (``Segment``, else ``Sub Segment``)
          together with ``Diameter`` must be unique, so every row gets its
          own ``code`` in ``to_json``. The same route with two
          diameters (e.g. 16 and 10 inch) is two different pipes and allowed.

        Text is compared with surrounding whitespace stripped, and blank text
        (only whitespace) counts as empty.

        Args:
            excel_rows (pd.Series | None): Excel row number of each ``df`` row,
                used in the error message. Defaults to ``df.index + 2`` (the
                header is Excel row 1).

        Raises:
            ValueError: Listing the Excel rows with an empty ``Area``, the
                rows with both ``Segment`` and ``Sub Segment`` empty, and
                each duplicated segment + diameter with its rows.

        Example:
            >>> index.validate_values()
        """
        if excel_rows is None:
            excel_rows = pd.Series(self.df.index + 2, index=self.df.index)

        def _text(column: str) -> pd.Series:
            return self.df[column].astype("string").str.strip()

        def _empty(column: str) -> pd.Series:
            return _text(column).fillna("").eq("")

        empty_segment = _empty("Segment") & _empty("Sub Segment")
        problems = {
            "'Area'": _empty("Area"),
            "'Segment' and 'Sub Segment'": empty_segment,
        }
        messages = [
            f"{columns} empty at Excel rows {excel_rows[empty].tolist()}"
            for columns, empty in problems.items()
            if empty.any()
        ]

        # Same fill as fix(); rows with no segment at all are reported above.
        segment = _text("Segment").where(~_empty("Segment"), _text("Sub Segment"))
        keys = pd.DataFrame({"segment": segment, "diameter": self.df["Diameter"]})
        keys = keys[~empty_segment]
        duplicated = keys[keys.duplicated(keep=False)]
        if not duplicated.empty:
            groups = [
                f"{name!r} ({diameter:g} in) at Excel rows "
                f"{excel_rows[group.index].tolist()}"
                for (name, diameter), group in duplicated.groupby(
                    ["segment", "diameter"], sort=False
                )
            ]
            messages.append("'Segment' + 'Diameter' not unique: " + ", ".join(groups))

        if messages:
            raise ValueError(f"{self.filepath}: " + "; ".join(messages))

    def check_existing_file(self, data_dir: str) -> Self:
        """Flag which referenced files exist under ``data_dir``.

        For each data type in ``DATA_TYPES``, adds a boolean column
        ``"<data_type> File Exists"`` that is True when the referenced file
        exists at ``<data_dir>/<Year>/<data_type> FINAL/<filename>``.

        Args:
            data_dir (str): Root directory containing the year-partitioned data files.

        Returns:
            Self: The same ``FileIndex`` instance, to allow chaining.

        Example:
            >>> index.check_existing_file("//nas/surveys")
        """
        df = self.df.copy()

        def _check_existing_file(_data_dir: str, row, _data_type: str):
            if pd.notna(row[_data_type]):
                filename = row[_data_type]
                filepath = os.path.join(
                    _data_dir, str(row["Year"]), f"{_data_type} FINAL", filename
                )
                return os.path.isfile(filepath)
            return False

        for data_type in self.DATA_TYPES:
            df[f"{data_type} File Exists"] = df[["Year", data_type]].apply(
                lambda row: _check_existing_file(
                    _data_dir=data_dir,
                    row=row,
                    _data_type=data_type,  # noqa: B023
                ),
                axis=1,
            )

        self.df = df
        self.checked = True

        return self

    def fix(self) -> Self:
        """Normalize ``Segment`` and ``.xlsx`` filenames in place.

        Missing ``Segment`` values are back-filled from ``Sub Segment``, and any
        ``CIPS`` or ``PCM`` filename lacking the ``.xlsx`` suffix has one appended.

        Returns:
            Self: The same ``FileIndex`` instance, to allow chaining.

        Example:
            >>> index.fix()
        """
        df = self.df.copy()
        # An all-empty Segment column is read as float64, which cannot hold
        # the Sub Segment text copied in below.
        df["Segment"] = df["Segment"].astype(object)

        segment_updated = 0
        filename_updated = 0
        for index, row in df.iterrows():
            if pd.isna(row["Segment"]):
                df.loc[index, "Segment"] = row["Sub Segment"]
                segment_updated += 1

            for data_type in self.DATA_TYPES:
                value = row[data_type]
                if pd.notna(value):
                    value = str(value)
                    if not value.lower().endswith(".xlsx"):
                        df.loc[index, data_type] = f"{value}.xlsx"
                        filename_updated += 1

        self.df = df
        self.fixed = True

        if self.verbose:
            logger.info(f"Segment Updated: {segment_updated} segments")
            logger.info(f"Filename Updated: {filename_updated} filenames")

        return self

    def by_year(self, value: int) -> pd.DataFrame:
        """Return rows for a single ``Year``.

        Args:
            value (int): Year to filter on.

        Returns:
            pd.DataFrame: A copy of ``df`` filtered to ``Year == value``.

        Example:
            >>> rows_2024 = index.by_year(2024)
        """
        return self.df[self.df["Year"] == value].copy()

    def by_columns(self, columns: str | list[str]) -> pd.DataFrame:
        """Return a copy of ``df`` with only the given columns.

        Args:
            columns (str | list[str]): A single column name or list of column names
                to select.

        Returns:
            pd.DataFrame: A copy of ``df`` restricted to ``columns``.

        Raises:
            KeyError: If any name in ``columns`` is not a column of ``df``.

        Example:
            >>> subset = index.by_columns(["Year", "CIPS"])
            >>> cips_only = index.by_columns("CIPS")
        """
        if isinstance(columns, str):
            columns = [columns]
        return self.df[columns].copy()

    def rebuild(
        self,
        source_dir: str,
        output_dir: str | None = None,
        destination_dir: str = "raw_data",
    ) -> Self:
        """Copy referenced files from ``source_dir`` into a clean output tree.

        Applies ``fix()`` if not already applied, so filenames get their
        ``.xlsx`` suffix before they are looked up, then rechecks file
        existence against ``source_dir`` and copies every existing referenced
        file into ``<output_dir>/<destination_dir>/<Year>/<data_type>/``.
        Existing destination files are skipped.

        Args:
            source_dir (str): Root directory of the source data tree.
            output_dir (str | None): Destination root. Defaults to ``<cwd>/output``.
            destination_dir (str): Subdirectory under ``output_dir`` to copy into.
                Defaults to ``"raw_data"``.

        Returns:
            Self: The same ``FileIndex`` instance, to allow chaining.

        Example:
            >>> index.rebuild(source_dir="//nas/surveys", destination_dir="raw_data")
        """
        if not self.fixed:
            self.fix()

        self.check_existing_file(source_dir)

        output_dir = resolve_output_dir(output_dir)
        destination_dir = os.path.join(output_dir, destination_dir)
        os.makedirs(destination_dir, exist_ok=True)

        df = self.df

        copied = 0
        skipped = 0
        for data_type in self.DATA_TYPES:
            for _, row in df.iterrows():
                if not row[f"{data_type} File Exists"]:
                    continue

                filename = row[data_type]
                year = str(row["Year"])
                source_filepath = os.path.join(
                    source_dir,
                    year,
                    f"{data_type} FINAL",
                    filename,
                )

                destination_dir_year = os.path.join(destination_dir, year, data_type)
                os.makedirs(destination_dir_year, exist_ok=True)

                destination_filepath = os.path.join(destination_dir_year, filename)

                if os.path.isfile(destination_filepath):
                    logger.warning(f"Exists. Skipped: {source_filepath}")
                    skipped += 1
                    continue

                shutil.copy2(source_filepath, destination_filepath)
                copied += 1

        logger.info(
            f"Copied {copied} files to {destination_dir} (skipped {skipped} existing)"
        )

        self.save(output_dir)

        return self

    def check_pcm_file(self, data_dir: str, n_jobs: int = 1) -> pd.DataFrame:
        """Check, clean, save and normalize every referenced PCM file.

        Each file runs through ``PCM(...).clean().check().save()``, so the
        report describes the cleaned data and the cleaned copy is written
        under ``output/cleaned/<year>/PCM/``. Then ``normalize()`` writes the
        normalized Excel/JSON under ``<cwd>/output/normalize/pcm/``; a file
        that fails to normalize keeps its check columns.

        Also adds ``normalized_pcm_file`` to ``df`` (filename of the
        normalized JSON, ``PCM.normalize_json_filepath``) and
        ``pcm_medium_to_poor`` / ``pcm_medium_to_high``
        (``PCM.medium_to_poor_percentage`` / ``medium_to_high_percentage``)
        and ``pcm_length_km`` (last ``Real Distance`` of the normalized PCM,
        in km; ``to_json``'s fallback for an empty ``Length``), used by
        ``to_json``. It is ``None`` for rows without a PCM file, or whose file
        failed to load, clean or normalize.

        Args:
            data_dir (str): Root directory containing the year-partitioned data files.
            n_jobs (int): Number of parallel workers to use via joblib's ``loky``
                backend. ``1`` runs sequentially, ``-1`` uses all available cores.
                Defaults to ``1``.

        Returns:
            pd.DataFrame: One row per index entry with columns ``year``,
                ``filepath``, ``is_valid``, ``n_missing``, ``n_duplicates``,
                ``missing_columns``, ``duplicates``, ``normalized``
                (``PCM.normalized``), ``normalized_pcm_file``,
                ``medium_to_poor_percentage``, ``medium_to_high_percentage``,
                ``length_km`` and ``reason``.
                Rows with a missing file on disk, a load/clean error or a
                normalize error are recorded as ``is_valid=False`` with a
                populated ``reason``.
        """
        empty_result = {
            "n_missing": None,
            "n_duplicates": None,
            "missing_columns": None,
            "duplicates": None,
            "normalized": False,
            "normalized_pcm_file": None,
            "medium_to_poor_percentage": None,
            "medium_to_high_percentage": None,
            "length_km": None,
        }

        def _check_row(row: pd.Series) -> dict:
            year = int(row["Year"])
            filepath = os.path.join(data_dir, str(year), "PCM", row["PCM"])
            if not os.path.isfile(filepath):
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "reason": "file not found on disk",
                    **empty_result,
                }

            try:
                pcm = PCM(filepath, year=year).clean().check().save()
            except Exception as e:
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "reason": f"{type(e).__name__}: {e}",
                    **empty_result,
                }

            result = {
                "year": year,
                **pcm.report,
                "normalized": False,
                "normalized_pcm_file": None,
                "medium_to_poor_percentage": None,
                "medium_to_high_percentage": None,
                "length_km": None,
                "reason": None,
            }

            try:
                pcm.normalize()
            except Exception as e:
                result["is_valid"] = False
                result["reason"] = f"normalize failed: {type(e).__name__}: {e}"
                return result

            # pcm lives in this worker process: send its state back in result
            result["normalized"] = pcm.normalized
            if pcm.normalized:
                result["normalized_pcm_file"] = os.path.basename(
                    pcm.normalize_json_filepath
                )
                result["medium_to_poor_percentage"] = pcm.medium_to_poor_percentage
                result["medium_to_high_percentage"] = pcm.medium_to_high_percentage
                result["length_km"] = _length_km(pcm.df)
            return result

        rows = [row for _, row in self.df.iterrows() if pd.notna(row["PCM"])]
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_check_row)(row) for row in rows
        )

        self._merge_results(
            rows,
            {
                "normalized_pcm_file": [
                    result["normalized_pcm_file"] if result["normalized"] else None
                    for result in results
                ],
                "pcm_medium_to_poor": [
                    result["medium_to_poor_percentage"] for result in results
                ],
                "pcm_medium_to_high": [
                    result["medium_to_high_percentage"] for result in results
                ],
                "pcm_length_km": [result["length_km"] for result in results],
            },
        )

        columns = [
            "year",
            "filepath",
            "is_valid",
            "n_missing",
            "n_duplicates",
            "missing_columns",
            "duplicates",
            "normalized",
            "normalized_pcm_file",
            "medium_to_poor_percentage",
            "medium_to_high_percentage",
            "length_km",
            "reason",
        ]

        return pd.DataFrame(results, columns=columns)

    def check_cips_file(self, data_dir: str, n_jobs: int = 1) -> pd.DataFrame:
        """Check, clean, save and normalize every referenced CIPS file.

        Each file runs through ``CIPS(...).clean().check().save()``, like
        ``check_pcm_file``: the data sheet is located (CIPS workbooks are not
        uniform, see ``CIPS.find_sheet``) and its column names aligned while
        loading, ``clean()`` cleans it, ``check()`` reports on the cleaned
        data and ``save()`` writes the cleaned copy to
        ``<cwd>/output/cleaned/<year>/CIPS/``. Then ``normalize()`` writes the normalized Excel/JSON
        under ``<cwd>/output/normalize/cips/``. A file that fails to clean
        gets no check columns.

        Also adds two columns to ``df``, used by ``to_json`` (``None`` for
        rows without a CIPS file, or whose file failed to clean/normalize):

        - ``normalized_cips_file``: filename of the normalized JSON
          (``CIPS.normalize_json_filepath``).
        - ``cips_protection``: ``"ICCP"`` or ``"SACP"``.
        - ``cips_protected_percentage`` / ``cips_unprotected_percentage``:
          ``CIPS.protected_percentage`` / ``unprotected_percentage``, share
          of readings that are (over) protected / unprotected (only set when
          normalized).
        - ``cips_length_km``: last ``Real Distance`` of the normalized CIPS,
          in km (3 decimals); ``to_json`` uses it when ``Length`` is empty.

        Args:
            data_dir (str): Root directory containing the year-partitioned
                data files, laid out as ``<data_dir>/<Year>/CIPS/<filename>``.
            n_jobs (int): Number of parallel workers to use via joblib's
                ``loky`` backend. ``1`` runs sequentially, ``-1`` uses all
                available cores. Defaults to ``1``.

        Returns:
            pd.DataFrame: One row per index entry with a CIPS filename, with
                columns ``year``, ``filepath``, ``is_valid``, ``sheet_name``
                (sheet loaded), ``candidate_sheets`` (every qualifying sheet,
                best first), ``has_voltage``, ``n_missing``,
                ``missing_columns``, ``n_duplicates``, ``cleaned_path``,
                ``cips_protection``, ``protected_percentage``,
                ``unprotected_percentage``, ``normalized``
                (``CIPS.normalized``), ``normalized_cips_file``,
                ``length_km`` and ``reason``.
                Check columns describe the cleaned data, so ``n_duplicates``
                is 0 (``clean`` removes duplicates). The per-row duplicate
                list is left out of the report.
                ``is_valid`` is False when a check, cleaning or normalizing
                fails. Rows with a missing file, no data sheet, a load error,
                a clean error or a normalize error get a ``reason``.
                ``cleaned_path`` / ``cips_protection`` are set only when the
                cleaned copy was saved. ``normalized`` is True and
                ``normalized_cips_file`` is set only when the normalized
                files were written.

        Example:
            >>> report = index.check_cips_file("output/raw_data", n_jobs=-1)
            >>> report[~report["is_valid"]]
        """
        columns = [
            "year",
            "filepath",
            "is_valid",
            "sheet_name",
            "candidate_sheets",
            "has_voltage",
            "n_missing",
            "missing_columns",
            "n_duplicates",
            "cleaned_path",
            "cips_protection",
            "protected_percentage",
            "unprotected_percentage",
            "normalized",
            "normalized_cips_file",
            "length_km",
            "reason",
        ]

        def _check_row(row: pd.Series) -> dict:
            year = int(row["Year"])
            filepath = os.path.join(data_dir, str(year), "CIPS", row["CIPS"])
            if not os.path.isfile(filepath):
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "normalized": False,
                    "reason": "file not found on disk",
                }

            try:
                candidates = CIPS.data_sheets(get_sheet_columns(filepath))
                cips = CIPS(filepath, year=year)
            except Exception as e:
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "normalized": False,
                    "reason": f"{type(e).__name__}: {e}",
                }

            try:
                cips.clean().check().save()
            except Exception as e:
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "sheet_name": cips.sheet_name,
                    "candidate_sheets": candidates,
                    "normalized": False,
                    "reason": f"clean failed: {type(e).__name__}: {e}",
                }

            result = {
                "year": year,
                **cips.report,
                "candidate_sheets": candidates,
                "cleaned_path": cips.cleaned_path,
                "cips_protection": cips.protection,
                "protected_percentage": None,
                "unprotected_percentage": None,
                "normalized": False,
                "normalized_cips_file": None,
                "length_km": None,
                "reason": None,
            }

            try:
                cips.normalize()
            except Exception as e:
                result["is_valid"] = False
                result["reason"] = f"normalize failed: {type(e).__name__}: {e}"
                return result

            # cips lives in this worker process: send its state back in result
            result["normalized"] = cips.normalized
            if cips.normalized:
                result["normalized_cips_file"] = os.path.basename(
                    cips.normalize_json_filepath
                )
                result["protected_percentage"] = cips.protected_percentage
                result["unprotected_percentage"] = cips.unprotected_percentage
                result["length_km"] = _length_km(cips.df)
            return result

        rows = [row for _, row in self.df.iterrows() if pd.notna(row["CIPS"])]
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_check_row)(row) for row in rows
        )

        # Only files that were actually normalized get a normalized_cips_file.
        self._merge_results(
            rows,
            {
                "normalized_cips_file": [
                    result.get("normalized_cips_file")
                    if result.get("normalized")
                    else None
                    for result in results
                ],
                "cips_protection": [
                    result.get("cips_protection") for result in results
                ],
                "cips_protected_percentage": [
                    result.get("protected_percentage") for result in results
                ],
                "cips_unprotected_percentage": [
                    result.get("unprotected_percentage") for result in results
                ],
                "cips_length_km": [result.get("length_km") for result in results],
            },
        )

        return pd.DataFrame(results, columns=columns)

    def _merge_results(self, rows: list[pd.Series], values: dict[str, list]) -> None:
        """Write per-file worker results into new ``df`` columns.

        Workers run in separate processes and cannot update ``self.df``, so
        each value comes back in the worker's result and is written here by
        row label (``row.name``). Rows that were not processed get ``NaN``.

        Args:
            rows (list[pd.Series]): The ``df`` rows sent to the workers.
            values (dict[str, list]): Column name -> one value per row, in the
                order of ``rows``.
        """
        df = self.df.copy()
        labels = [row.name for row in rows]
        for column, column_values in values.items():
            df[column] = pd.Series(column_values, index=labels, dtype=object).reindex(
                df.index
            )
        self.df = df

    def to_json(
        self, output_dir: str | None = None, sync: bool = True, n_jobs: int = 1
    ) -> str:
        """Write the index as JSON records to ``<output_dir>/file_index.json``.

        Runs ``fix()`` first if needed, so empty ``Segment`` values are filled
        from ``Sub Segment``. Only rows with both a ``cips_normalized_file``
        and a ``pcm_normalized_file`` (``NORMALIZED_FILE_KEYS``) are written,
        so run ``check_cips_file`` and ``check_pcm_file`` first. Every other
        row goes to ``<output_dir>/file_index_excluded.json`` instead, with
        the same keys, plus ``cips_file`` / ``pcm_file`` (the
        source filenames from the index, ``null`` when the index has none)
        and ``missing`` (the ``NORMALIZED_FILE_KEYS`` that are ``null``). The
        reason a file was not normalized is in the ``check_*_file`` report.

        Keys of each written record:

        - ``year`` (int), ``area`` (str).
        - ``area_code`` (str): slug of ``<area>-<year>``, e.g.
          ``"jakarta-2025"``.
        - ``province_code`` (int): ``Province Code``.
        - ``name`` (str): ``Segment``.
        - ``code`` (str): slug of ``<name>-<diameter>``, e.g.
          ``"pipa-servis-indonesia-power-16"``.
        - ``diameter`` (int | float): ``Diameter``, as an int when whole.
        - ``pipe_length`` (float | None): ``Length``, in km. When it is
          empty: the surveyed length, i.e. the last ``Real Distance`` of the
          normalized CIPS (``cips_length_km``), else of the normalized PCM
          (``pcm_length_km``), converted from meters to km (3 decimals).
        - ``cips_protection`` (str | None): ``"ICCP"`` / ``"SACP"``, set by
          ``check_cips_file``.
        - ``protected`` / ``unprotected`` (float | None): share of CIPS
          readings that are ``PROTECTED`` or ``OVER PROTECTED`` /
          ``UNPROTECTED``, in percent (they add up to 100); set by
          ``check_cips_file`` (``df`` columns ``cips_protected_percentage`` /
          ``cips_unprotected_percentage``), ``None`` without a normalized
          CIPS.
        - ``total_anomaly`` (int | None): number of ACVG/DCVG anomalies of
          the segment (``AcvgDcvgFile.count``, ``TOTAL_ANOMALY_COLUMN``, set
          by ``assign_acvg_dcvg``); ``None`` until it ran, and for segments
          without ACVG/DCVG anomalies.
        - ``medium_to_poor`` / ``medium_to_high`` (float | None): share of
          PCM readings whose ``Condition`` is ``Medium to Poor`` / ``Medium
          to High``, in percent (they add up to 100); set by
          ``check_pcm_file`` (``df`` columns ``pcm_medium_to_poor`` /
          ``pcm_medium_to_high``), ``None`` without a normalized PCM.
        - ``acvg_dcvg_normalized_file`` (str | None): the normalized
          ACVG/DCVG JSON of the segment (``ACVG_DCVG_COLUMN``, set by
          ``assign_acvg_dcvg``); ``None`` until it ran, and for segments
          without ACVG/DCVG anomalies. Not required to keep a row.
        - ``cips_normalized_file`` / ``pcm_normalized_file`` (str | None):
          set by ``check_cips_file`` / ``check_pcm_file`` (``df`` columns
          ``normalized_cips_file`` / ``normalized_pcm_file``); ``None`` until
          they ran, and for rows without a usable file.

        Empty values are written as ``null``. Both files are always written,
        possibly as ``[]``. Then ``<output_dir>/area.json``
        (``AREA_JSON_FILENAME``) is written from the ``file_index.json``
        records, one per ``area_code`` (see ``area_records``).

        With ``sync`` (the default), ``corrosions.sync.SyncData`` then runs on
        the written index: every kept segment's normalized CIPS and PCM files
        (JSON and Excel, under ``<cwd>/output/normalize``) are reordered in
        place so both surveys start at the same end. Its per-segment report is
        stored on ``self.sync_report``.

        Args:
            output_dir (str | None): Destination directory. Defaults to
                ``<cwd>/output``.
            sync (bool): Run ``SyncData`` after writing the index. Defaults to
                ``True``; pass ``False`` to leave the normalized files as they
                are.
            n_jobs (int): Parallel workers for ``SyncData`` (joblib ``loky``);
                ``-1`` uses all cores. Defaults to ``1``.

        Returns:
            str: Path of ``file_index.json``. The excluded rows are next to it,
                in ``EXCLUDED_JSON_FILENAME``.

        Example:
            >>> index.check_cips_file("output/raw_data", n_jobs=-1)
            >>> index.check_pcm_file("output/raw_data", n_jobs=-1)
            >>> index.to_json()
            'output/file_index.json'
            >>> index.sync_report["pcm_reversed"].sum()
        """
        if not self.fixed:
            self.fix()

        records = []
        excluded = []
        for _, row in self.df.iterrows():
            record = self._record(row)

            missing = [key for key in self.NORMALIZED_FILE_KEYS if record[key] is None]
            if missing:
                excluded.append(
                    {
                        **record,
                        "cips_file": _json_value(row["CIPS"]),
                        "pcm_file": _json_value(row["PCM"]),
                        "missing": missing,
                    }
                )
            else:
                records.append(record)

        output_dir = resolve_output_dir(output_dir)
        filepath = os.path.join(output_dir, self.JSON_FILENAME)
        excluded_filepath = os.path.join(output_dir, self.EXCLUDED_JSON_FILENAME)
        area_filepath = os.path.join(output_dir, self.AREA_JSON_FILENAME)
        for path, data in (
            (filepath, records),
            (excluded_filepath, excluded),
            (area_filepath, self.area_records(records)),
        ):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        if self.verbose:
            logger.info(
                f"Wrote {len(records)} records to {filepath}; "
                f"{len(excluded)} rows without a normalized CIPS/PCM file to "
                f"{excluded_filepath}"
            )

        if sync:
            self.sync_report = SyncData(
                filepath, n_jobs=n_jobs, verbose=self.verbose
            ).sync()

        return filepath

    def _record(self, row: pd.Series) -> dict:
        """Return the ``to_json`` record of one ``df`` row."""
        year = _json_value(row["Year"], whole_as_int=True)
        area = _json_value(row["Area"])
        segment = _json_value(row["Segment"])
        diameter = _json_value(row["Diameter"], whole_as_int=True)
        province_code = _json_value(row["Province Code"])

        return {
            "year": year,
            "area": area,
            "area_code": slugify(f"{area}-{year}"),
            "province_code": province_code,
            "name": segment,
            "code": (slugify(f"{segment}-{diameter}") if segment else None),
            "diameter": diameter,
            "pipe_length": _first_value(
                row["Length"], row.get("cips_length_km"), row.get("pcm_length_km")
            ),
            "cips_protection": _json_value(row.get("cips_protection")),
            "protected": _json_value(row.get("cips_protected_percentage")),
            "unprotected": _json_value(row.get("cips_unprotected_percentage")),
            self.TOTAL_ANOMALY_KEY: _json_value(
                row.get(self.TOTAL_ANOMALY_COLUMN), whole_as_int=True
            ),
            "medium_to_poor": _json_value(row.get("pcm_medium_to_poor")),
            "medium_to_high": _json_value(row.get("pcm_medium_to_high")),
            self.ACVG_DCVG_FILE_KEY: _json_value(row.get(self.ACVG_DCVG_COLUMN)),
            "cips_normalized_file": _json_value(row.get("normalized_cips_file")),
            "pcm_normalized_file": _json_value(row.get("normalized_pcm_file")),
        }

    @classmethod
    def area_records(cls, records: list[dict]) -> list[dict]:
        """Summarize ``file_index.json`` records per ``area_code``.

        One record per ``area_code``, in order of first appearance:

        - ``name``: ``area``; ``code``: ``area_code``; ``year``.
        - ``total_length``: sum of ``pipe_length`` (rounded to 3 decimals,
          only to drop float noise).
        - ``protected``, ``unprotected``, ``medium_to_poor``,
          ``medium_to_high`` (``AREA_MEAN_KEYS``): simple mean of the
          segments' percentages (every segment counts the same), rounded to
          2 decimals; ``null`` values are skipped, ``null`` when all are.
        - ``total_anomaly``: sum of the segments' ``total_anomaly`` (``null``
          counts as 0), as an int.
        - ``province_code``: of the first segment of the area.

        Args:
            records (list[dict]): ``file_index.json`` records.

        Returns:
            list[dict]: One summary per area.

        Example:
            >>> FileIndex.area_records(records)[0]["total_length"]
            12.35
        """
        areas: dict[str, list[dict]] = {}
        for record in records:
            areas.setdefault(record.get("area_code"), []).append(record)

        summaries = []
        for code, segments in areas.items():
            first = segments[0]
            summary = {
                "name": first.get("area"),
                "code": code,
                "year": first.get("year"),
                "total_length": round(
                    sum(s.get("pipe_length") or 0.0 for s in segments), 3
                ),
            }
            for key in cls.AREA_MEAN_KEYS:
                values = [s[key] for s in segments if s.get(key) is not None]
                summary[key] = round(sum(values) / len(values), 2) if values else None
            summary["total_anomaly"] = int(
                sum(s.get(cls.TOTAL_ANOMALY_KEY) or 0 for s in segments)
            )
            summary["province_code"] = first.get("province_code")
            summaries.append(summary)
        return summaries

    def assign_acvg_dcvg(
        self,
        files: dict[int, str],
        output_dir: str | None = None,
        counts: dict[int, int] | None = None,
    ) -> Self:
        """Add each row's ACVG/DCVG file and anomaly count, also to the JSON.

        Sets the ``ACVG_DCVG_COLUMN`` and ``TOTAL_ANOMALY_COLUMN`` columns of
        ``df``, so later ``to_json`` calls write ``acvg_dcvg_normalized_file``
        and ``total_anomaly``. The ACVG/DCVG step runs after ``to_json`` (its
        ``normalize`` needs the synced CIPS), so the ``JSON_FILENAME`` and
        ``EXCLUDED_JSON_FILENAME`` already written in ``output_dir`` are
        updated in place: every record, found by its ``year`` and ``code``,
        gets both keys (``null`` when the row has no ACVG/DCVG file), in the
        same key order as ``to_json`` records. Keys only the excluded file has
        (``cips_file``, ``pcm_file``, ``missing``) stay last. A JSON file that
        does not exist is skipped. The CIPS/PCM files are not synced again.
        ``area.json`` is then rebuilt from the updated ``file_index.json``,
        so its ``total_anomaly`` counts the anomalies too.

        Args:
            files (dict[int, str]): Row position in ``df`` (= row of the index
                CSV ``AcvgDcvg.match`` read) -> normalized ACVG/DCVG JSON
                filename, as returned by ``AcvgDcvg.normalized_files()``.
            output_dir (str | None): Folder of the index JSON files. Defaults
                to ``<cwd>/output``.
            counts (dict[int, int] | None): Row position -> number of
                anomalies, as returned by ``AcvgDcvg.anomaly_counts()``.
                Defaults to none (``total_anomaly`` stays ``null``).

        Returns:
            Self: The same ``FileIndex`` instance, to allow chaining.

        Example:
            >>> acvg.load().match(csv).rebuild().clean().normalize()
            >>> index.assign_acvg_dcvg(
            ...     acvg.normalized_files(), counts=acvg.anomaly_counts()
            ... )
        """
        if not self.fixed:
            self.fix()

        counts = counts or {}
        df = self.df.copy()
        for column, values in (
            (self.ACVG_DCVG_COLUMN, files),
            (self.TOTAL_ANOMALY_COLUMN, counts),
        ):
            df[column] = pd.Series(
                [values.get(position) for position in range(len(df))],
                index=df.index,
                dtype=object,
            )
        self.df = df

        acvg_keys = (self.ACVG_DCVG_FILE_KEY, self.TOTAL_ANOMALY_KEY)
        by_segment: dict[tuple, dict] = {}
        record_keys: list[str] = []
        for _, row in self.df.iterrows():
            record = self._record(row)
            by_segment[(record["year"], record["code"])] = {
                key: record[key] for key in acvg_keys
            }
            record_keys = list(record)

        output_dir = resolve_output_dir(output_dir)
        for name in (self.JSON_FILENAME, self.EXCLUDED_JSON_FILENAME):
            path = os.path.join(output_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
            empty = dict.fromkeys(acvg_keys)
            records = [
                _ordered(
                    {
                        **record,
                        **by_segment.get(
                            (record.get("year"), record.get("code")), empty
                        ),
                    },
                    record_keys,
                )
                for record in records
            ]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=4, ensure_ascii=False)
            if name == self.JSON_FILENAME:
                area_path = os.path.join(output_dir, self.AREA_JSON_FILENAME)
                with open(area_path, "w", encoding="utf-8") as f:
                    json.dump(
                        self.area_records(records), f, indent=4, ensure_ascii=False
                    )

        if self.verbose:
            linked = sum(
                v[self.ACVG_DCVG_FILE_KEY] is not None for v in by_segment.values()
            )
            logger.info(
                f"Linked {linked} rows to a normalized ACVG/DCVG file in {output_dir}"
            )

        return self

    def save(self, output_dir: str | None = None) -> None:
        """Write ``df`` to ``<output_dir>/file_index_<slug>.csv``.

        Args:
            output_dir (str | None): Destination directory. Defaults to ``<cwd>/output``.

        Example:
            >>> index.save()
        """
        output_dir = resolve_output_dir(output_dir)
        filename = f"file_index_{self.filename_slug}.csv"
        filepath = os.path.join(output_dir, filename)

        self.df.to_csv(filepath, index=False)


def _ordered(record: dict, order: list[str]) -> dict:
    """Return ``record`` with the ``order`` keys first, in that order.

    Keys not in ``order`` (``cips_file``, ``pcm_file``, ``missing`` of the
    excluded file, or keys of an older index) keep their order, after them.
    """
    first = {key: record[key] for key in order if key in record}
    return {**first, **{k: v for k, v in record.items() if k not in first}}


def _length_km(df: pd.DataFrame) -> float | None:
    """Return the last ``Real Distance`` (meters) of a normalized survey in km.

    Rounded to 3 decimals (meters); ``None`` without a ``Real Distance``.
    """
    if df.empty or "Real Distance" not in df.columns:
        return None
    meters = df["Real Distance"].iloc[-1]
    return None if pd.isna(meters) else round(float(meters) / 1000, 3)


def _first_value(*values):
    """Return the first value that is not empty, as ``_json_value`` gives it."""
    for value in values:
        value = _json_value(value)
        if value is not None:
            return value
    return None


def _json_value(value, whole_as_int: bool = False):
    """Return ``value`` as a JSON-ready Python scalar.

    NaN / ``None`` become ``None`` and numpy scalars become Python ones. With
    ``whole_as_int``, whole floats become ints (``16.0`` -> ``16``).
    """
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if whole_as_int and isinstance(value, float) and value.is_integer():
        return int(value)
    return value
