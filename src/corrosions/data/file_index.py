"""File index for organizing corrosion survey data files (CIPS/PCM).

Reads an Excel index of survey files, validates required columns, verifies
that referenced files exist on disk, normalizes filenames, and copies the
referenced files into a year-partitioned output directory.

Example:
    >>> from corrosions.data.file_index import FileIndex
    >>> index = FileIndex("IDDA - File List.xlsx")
    >>> index.rebuild(source_dir="//nas/surveys")
    >>> index.save()
"""

import os
import shutil
from typing import Self

import pandas as pd
from joblib import Parallel, delayed
from slugify import slugify

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
        filepath (str): Path to the source Excel file.
        filename (str): Base filename of the source Excel file.
        filename_slug (str): Slugified filename stem, used for output artifacts.
        df (pd.DataFrame): Working DataFrame derived from the source Excel.
        checked (bool): Whether ``check_existing_file()`` has been run.
        fixed (bool): Whether ``fix()`` has been run.
        skip_years (list[int]): Survey years removed from ``df`` at load time.
        verbose (bool): If True, emit progress messages via the logger.

    Example:
        >>> index = FileIndex("IDDA - File List.xlsx", verbose=True)
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

        Example:
            >>> index = FileIndex("IDDA - File List.xlsx", drop_columns="Notes")
            >>> index = FileIndex("IDDA - File List.xlsx", skip_years=[2021])
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
        self.validate()

        self.df["Year"] = self.df["Year"].astype(int)
        self.df["Diameter"] = self.df["Diameter"].astype(float)
        self.df["Length"] = self.df["Length"].astype(float)
        self.df["Province Code"] = self.df["Province Code"].astype(int)

        self.skip_years: list[int] = sorted(set(skip_years or []))
        if self.skip_years:
            skipped = self.df["Year"].isin(self.skip_years)
            self.df = self.df[~skipped].reset_index(drop=True)
            if self.verbose:
                logger.info(
                    f"Skipped {int(skipped.sum())} rows from years {self.skip_years}"
                )

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
        """Run PCM data-quality checks on every referenced PCM file.

        Each file runs through ``PCM(...).clean().save().check()``, so the
        cleaned copy is written under ``output/cleaned/<year>/PCM/`` and the
        report describes the cleaned data.

        Args:
            data_dir (str): Root directory containing the year-partitioned data files.
            n_jobs (int): Number of parallel workers to use via joblib's ``loky``
                backend. ``1`` runs sequentially, ``-1`` uses all available cores.
                Defaults to ``1``.

        Returns:
            pd.DataFrame: One row per index entry with columns ``year``,
                ``filepath``, ``is_valid``, ``reason``, ``n_missing``,
                ``n_duplicates``, ``missing_columns``, and ``duplicates``. Rows
                with a missing filename, a missing file on disk, or a load
                error are recorded as ``is_valid=False`` with a populated
                ``reason``.
        """
        empty_result = {
            "n_missing": None,
            "n_duplicates": None,
            "missing_columns": None,
            "duplicates": None,
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
                pcm = PCM(filepath, year=year).clean().save().check()
                return {"year": year, **pcm.report, "reason": None}
            except Exception as e:
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "reason": f"{type(e).__name__}: {e}",
                    **empty_result,
                }

        rows = [row for _, row in self.df.iterrows() if pd.notna(row["PCM"])]
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_check_row)(row) for row in rows
        )

        columns = [
            "year",
            "filepath",
            "is_valid",
            "n_missing",
            "n_duplicates",
            "missing_columns",
            "duplicates",
            "reason",
        ]

        return pd.DataFrame(results, columns=columns)

    def check_cips_file(self, data_dir: str, n_jobs: int = 1) -> pd.DataFrame:
        """Check, clean and save every referenced CIPS file.

        Each file runs through ``CIPS(...).fix().check()``: the data sheet is
        located (CIPS workbooks are not uniform, see ``CIPS.find_sheet``),
        column names are aligned (``CIPS.fix``), then checked
        (``CIPS.check``). Then ``clean().save()`` writes a cleaned copy to
        ``<cwd>/output/cleaned/<year>/CIPS/``. The two steps are separate,
        so a file that fails to clean still reports its column checks.

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
                ``missing_columns``, ``n_duplicates``, ``cleaned_path`` and
                ``reason``. Check columns describe the file before cleaning.
                The per-row duplicate list is left out: CIPS files can repeat
                thousands of GPS points, too many for an Excel cell, and
                duplicates do not affect ``is_valid`` (``clean`` removes them).
                ``is_valid`` is False when a check fails or cleaning fails.
                Rows with a missing file, no data sheet, a load error or a
                clean error get a ``reason``. ``cleaned_path`` is set only
                when the cleaned copy was saved.

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
                    "reason": "file not found on disk",
                }

            try:
                candidates = CIPS.data_sheets(get_sheet_columns(filepath))
                cips = CIPS(filepath, year=year).fix().check()
            except Exception as e:
                return {
                    "year": year,
                    "filepath": filepath,
                    "is_valid": False,
                    "reason": f"{type(e).__name__}: {e}",
                }

            result = {
                "year": year,
                **cips.report,
                "candidate_sheets": candidates,
                "cleaned_path": None,
                "reason": None,
            }

            try:
                cips.clean().save()
            except Exception as e:
                result["is_valid"] = False
                result["reason"] = f"clean failed: {type(e).__name__}: {e}"
                return result

            result["cleaned_path"] = cips.cleaned_path
            cips.normalize()
            return result

        rows = [row for _, row in self.df.iterrows() if pd.notna(row["CIPS"])]
        results = Parallel(n_jobs=n_jobs, backend="loky")(
            delayed(_check_row)(row) for row in rows
        )

        return pd.DataFrame(results, columns=columns)

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
