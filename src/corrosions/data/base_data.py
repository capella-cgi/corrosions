import os
from typing import Self, Literal
from pathlib import Path

import pandas as pd
from slugify import slugify

from corrosions.utils.path_utils import resolve_output_dir


class BaseData:
    """Shared load / check / clean / save pipeline for one survey Excel file.

    Subclasses declare their schema through class attributes and inherit a
    fluent pipeline: ``Subclass(...).check().clean().save()``.

    Attributes:
        KIND (Literal["pcm", "cips", "acvg_dcvg"]): Survey type; names the
            cleaned output sub-directory (upper-cased) and the normalize one
            (lower-cased).
        REQUIRED_COLUMNS (list[str]): Columns expected in the source Excel.
        NUMERIC_COLUMNS (list[str]): Columns coerced to numeric via
            ``pd.to_numeric(..., errors="coerce")`` at load time.
        CLEAN_REQUIRED_COLUMNS (list[str]): Columns whose non-NaN value is
            required for a row to survive ``clean``.
        JSON_COLUMNS (dict[str, str]): Subclasses with ``normalize``: the
            ``df`` columns written to the normalized JSON, in order, mapped to
            their JSON keys (see ``json_frame``).
        UNIQUE_COLUMNS (tuple[str, str]): The (latitude, longitude) pair.
            ``check`` counts rows sharing a pair; ``clean`` drops rows where
            either is ``0`` and keeps the first row of each pair.
        filepath (str): Path to the source Excel file.
        sheet_name (int | str): Sheet loaded into ``df``, chosen by
            ``find_sheet``.
        df (pd.DataFrame): Working DataFrame with numeric columns coerced.
        year (int): Survey year associated with this file.
        output_dir (str): Resolved output directory for downstream artifacts.
        cleaned_dir (str): ``<output_dir>/cleaned/<year>/<KIND>``.
        cleaned_path (str | None): Path of the saved Excel once ``save`` ran.
        normalize_dir (str): ``<output_dir>/normalize/<kind>``, unless a
            subclass ``normalize`` got another ``normalize_dir``.
        normalize_excel_dir (str): ``<normalize_dir>/excel``.
        normalize_json_dir (str): ``<normalize_dir>/json``.
        normalize_excel_filepath (str): Excel written by a subclass
            ``normalize``: ``<normalize_excel_dir>/<year>-<slug>.xlsx``, where
            ``<slug>`` is the slugified source filename without its extension.
        normalize_json_filepath (str): JSON written by a subclass
            ``normalize``: ``<normalize_json_dir>/<year>-<slug>.json``.
        cleaned (bool): True once ``clean`` completed; ``normalize`` requires
            it.
        normalized (bool): True once a subclass ``normalize`` wrote both files.
        report (dict): Summary from the last ``check`` call (empty until
            then), plus the ``normalize`` results once a subclass
            ``normalize`` ran (see ``_report_normalize``).
        verbose (bool): If True, methods may emit progress messages.
    """

    KIND: Literal["pcm", "cips", "acvg_dcvg"]
    REQUIRED_COLUMNS: list[str]
    NUMERIC_COLUMNS: list[str]
    CLEAN_REQUIRED_COLUMNS: list[str]
    UNIQUE_COLUMNS: tuple[str, str]
    JSON_COLUMNS: dict[str, str]

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load the data sheet of the Excel file and coerce numeric columns.

        The sheet is chosen by ``find_sheet`` before anything is read. Column
        names are converted to ``str`` and stripped of surrounding whitespace.

        Args:
            filepath (str): Path to the source Excel file.
            year (int): Survey year for this file.
            output_dir (str | None): Destination root for downstream artifacts.
                Defaults to ``<cwd>/output`` via ``resolve_output_dir``.
            verbose (bool): If True, methods may emit progress messages.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
            ValueError: If ``find_sheet`` finds no usable sheet.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        self.filepath = filepath
        self.year = year
        self.output_dir = resolve_output_dir(output_dir)
        self.cleaned_dir = os.path.join(
            self.output_dir, "cleaned", str(year), self.KIND.upper()
        )
        self.cleaned_path: str | None = None
        self._set_normalize_dir(
            os.path.join(self.output_dir, "normalize", self.KIND.lower())
        )

        self.report: dict = {}
        self.verbose = verbose
        self.sheet_name = self.find_sheet(filepath)

        df = pd.read_excel(filepath, sheet_name=self.sheet_name)
        # Same normalization as get_sheet_columns, which find_sheet relies on.
        df.columns = [str(c).strip() for c in df.columns]
        self.df: pd.DataFrame = df
        self.cleaned: bool = False
        self.normalized: bool = False
        self._coerce_numeric()

    @classmethod
    def json_frame(cls, df: pd.DataFrame) -> pd.DataFrame:
        """Return ``df`` as it is written to the normalized JSON.

        Keeps only the ``JSON_COLUMNS`` (in their order), renames them to
        their JSON keys and turns empty or blank text into ``None``
        (``null``). Used by ``normalize`` and by ``corrosions.sync.SyncData``
        to rebuild the JSON from a reversed normalized Excel.

        Args:
            df (pd.DataFrame): Normalized rows, with ``normalize``'s column
                names (``self.df`` after ``normalize``, or the normalized
                Excel).

        Returns:
            pd.DataFrame: One column per JSON key.
        """
        frame = df[list(cls.JSON_COLUMNS)].rename(columns=cls.JSON_COLUMNS)
        return frame.map(lambda v: None if isinstance(v, str) and not v.strip() else v)

    def _coerce_numeric(self) -> None:
        """Coerce every present ``NUMERIC_COLUMNS`` entry; bad values become NaN."""
        for col in self.NUMERIC_COLUMNS:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    @classmethod
    def find_sheet(cls, filepath: str) -> int | str:
        """Return the sheet that holds the survey data.

        The default is the first sheet. Subclasses whose workbooks vary in
        layout override this to inspect the sheets first.

        Args:
            filepath (str): Path to the source Excel file.

        Returns:
            int | str: Sheet name or position, as accepted by
                ``pd.read_excel(sheet_name=...)``.
        """
        return 0

    def check(self) -> Self:
        """Run data-quality checks on the current DataFrame.

        Checks that every column in ``REQUIRED_COLUMNS`` is present and that
        the combination of ``UNIQUE_COLUMNS`` is unique across rows. Nothing
        is raised: findings are stored on ``self.report`` so results can be
        aggregated across many files.

        ``self.report`` has the following keys:

        - ``filepath`` (str): Source file path.
        - ``sheet_name`` (int | str): Sheet the data was loaded from.
        - ``is_valid`` (bool): True if no missing columns and no duplicates.
        - ``n_missing`` (int): Number of missing required columns.
        - ``n_duplicates`` (int): Number of duplicate rows by ``UNIQUE_COLUMNS``.
        - ``missing_columns`` (list[str] | None): Missing required columns.
        - ``duplicates`` (list[dict] | None): One dict per duplicate row with
          keys ``row`` (DataFrame index) and the unique-column values.

        The report is replaced, so calling ``check`` after ``normalize`` drops
        the keys ``normalize`` added.

        Returns:
            Self: ``self``, to allow method chaining.

        Example:
            >>> PCM("segment-01.xlsx", year=2024).check().report["is_valid"]
            True
        """
        missing_columns = [c for c in self.REQUIRED_COLUMNS if c not in self.df.columns]

        unique_cols = [c for c in self.UNIQUE_COLUMNS if c in self.df.columns]
        if len(unique_cols) == len(self.UNIQUE_COLUMNS):
            duplicated = self.df.duplicated(subset=unique_cols, keep=False)
            dupes = self.df.loc[duplicated, unique_cols]
            # to_dict / Index iteration yield plain Python scalars, not numpy ones
            duplicates = [
                {"row": idx, **record}
                for idx, record in zip(
                    dupes.index, dupes.to_dict("records"), strict=True
                )
            ]
        else:
            duplicates = []

        self.report = {
            "filepath": self.filepath,
            "sheet_name": self.sheet_name,
            "is_valid": not missing_columns and not duplicates,
            "n_missing": len(missing_columns),
            "n_duplicates": len(duplicates),
            "missing_columns": missing_columns or None,
            "duplicates": duplicates or None,
        }

        return self

    def _set_normalize_dir(self, normalize_dir: str | None) -> None:
        """Set ``normalize_dir`` and the Excel/JSON dirs and paths under it.

        Called by ``__init__`` with ``<output_dir>/normalize/<kind>`` and by
        every subclass ``normalize`` with its ``normalize_dir`` argument.

        Args:
            normalize_dir (str | None): New ``normalize_dir``; ``None`` keeps
                the current one.
        """
        if normalize_dir is None:
            return

        self.normalize_dir = normalize_dir
        self.normalize_excel_dir = os.path.join(normalize_dir, "excel")
        self.normalize_json_dir = os.path.join(normalize_dir, "json")

        normalize_filename = f"{self.year}-{slugify(Path(self.filepath).stem)}"
        self.normalize_excel_filepath = os.path.join(
            self.normalize_excel_dir, f"{normalize_filename}.xlsx"
        )
        self.normalize_json_filepath = os.path.join(
            self.normalize_json_dir, f"{normalize_filename}.json"
        )

    def _report_normalize(self, **values) -> None:
        """Add the results of a subclass ``normalize`` to ``self.report``.

        Called at the end of ``normalize``, once both files are written. Keeps
        the ``check`` keys (if ``check`` ran) and adds:

        - ``normalized`` (bool): ``True``.
        - ``n_normalized`` (int): Rows in the normalized files.
        - ``normalize_excel_filepath`` / ``normalize_json_filepath`` (str):
          The files written.
        - ``values``: The subclass results (e.g. condition percentages).

        Args:
            **values: Subclass-specific keys, added last.
        """
        self.report.update(
            {
                "normalized": True,
                "n_normalized": len(self.df),
                "normalize_excel_filepath": self.normalize_excel_filepath,
                "normalize_json_filepath": self.normalize_json_filepath,
                **values,
            }
        )

    def clean(self) -> Self:
        """Drop unusable rows from the DataFrame.

        In order (each step only uses the columns actually present):

        1. Rows that are empty across every column.
        2. Rows whose latitude or longitude (``UNIQUE_COLUMNS``) is ``0``,
           i.e. no GPS fix.
        3. Rows with any ``NaN`` in ``CLEAN_REQUIRED_COLUMNS`` (which include
           the coordinates, so empty latitude/longitude rows go here).
        4. Duplicate ``UNIQUE_COLUMNS`` rows, keeping the first reading at
           each position.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            ValueError: If no row is left, which usually means the source file
                is malformed or required columns are missing.

        Example:
            >>> PCM("segment-01.xlsx", year=2024).clean().save()
        """
        required_present = [
            c for c in self.CLEAN_REQUIRED_COLUMNS if c in self.df.columns
        ]
        coordinates = [c for c in self.UNIQUE_COLUMNS if c in self.df.columns]

        self.df = self.df.dropna(how="all")
        if coordinates:
            # NaN != 0 is True: empty coordinates are left for the dropna below.
            self.df = self.df[(self.df[coordinates] != 0).all(axis=1)]
        if required_present:
            self.df = self.df.dropna(subset=required_present)

        if self.df.empty:
            raise ValueError(
                f"Cleaned DataFrame is empty after applying CLEAN_REQUIRED_COLUMNS "
                f"({self.CLEAN_REQUIRED_COLUMNS}) and dropping zero "
                f"{list(self.UNIQUE_COLUMNS)} to {self.filepath}"
            )

        if len(coordinates) == len(self.UNIQUE_COLUMNS):
            self.df = self.df.drop_duplicates(subset=coordinates)

        self.cleaned = True

        return self

    def save(self) -> Self:
        """Save the current DataFrame under ``cleaned_dir``.

        Writes ``self.df`` to ``{cleaned_dir}/{original_filename}`` and sets
        ``self.cleaned_path``. Creates the destination directory if needed.

        Returns:
            Self: ``self``, to allow method chaining.

        Example:
            >>> PCM("segment-01.xlsx", year=2024).clean().save().cleaned_path
            'output/cleaned/2024/PCM/segment-01.xlsx'
        """
        os.makedirs(self.cleaned_dir, exist_ok=True)

        target_path = os.path.join(self.cleaned_dir, os.path.basename(self.filepath))
        self.df.to_excel(target_path, index=False)
        self.cleaned_path = target_path

        return self
