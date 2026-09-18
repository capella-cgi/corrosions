import os
from typing import Self

import pandas as pd

from corrosions.utils.path_utils import resolve_output_dir


class PCM:
    """Pipeline Current Mapping (PCM) survey reader.

    PCM surveys are performed to determine the coating integrity of underground
    gas pipelines. This class loads a single PCM Excel export, coerces its
    numeric columns, and exposes a data-quality ``check`` for reporting.

    Attributes:
        COLUMNS (list[str]): Required columns expected in the source Excel.
        NUMERIC_COLUMNS (list[str]): Columns coerced to numeric via
            ``pd.to_numeric(..., errors="coerce")`` at load time.
        CLEAN_REQUIRED_COLUMNS (list[str]): Columns whose presence and
            non-NaN value is required for a row to survive ``clean``. Excludes
            ``Ext GPS Latitude`` / ``Ext GPS Longitude`` because they are
            frequently blank in real PCM exports.
        UNIQUE_COLUMNS (tuple[str, str]): Columns whose combination must be
            unique across rows (used by ``check`` to flag duplicates).
        filepath (str): Path to the source Excel file.
        df (pd.DataFrame): Working DataFrame with numeric columns coerced.
        year (int): Survey year associated with this file.
        output_dir (str): Resolved output directory for downstream artifacts.
        verbose (bool): If True, downstream methods may emit progress messages.

    Example:
        >>> pcm = PCM("data/2024/PCM FINAL/segment-01.xlsx", year=2024)
        >>> report = pcm.check()
    """

    COLUMNS: list[str] = [
        "Index",
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Ext GPS Latitude",
        "Ext GPS Longitude",
        "Survey name (0-100)",
        "Gain (dB)",
    ]

    NUMERIC_COLUMNS: list[str] = [
        "Index",
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
    ]

    CLEAN_REQUIRED_COLUMNS: list[str] = [
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
    ]

    UNIQUE_COLUMNS: tuple[str, str] = ("Int GPS Latitude", "Int GPS Longitude")

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load a PCM Excel file and coerce numeric columns.

        Reads ``filepath`` into a DataFrame and casts every column listed in
        ``NUMERIC_COLUMNS`` (if present) to numeric, turning unparseable
        values into ``NaN``.

        Args:
            filepath (str): Path to the source PCM Excel file.
            year (int): Survey year for this file.
            output_dir (str | None): Destination root for downstream artifacts.
                Defaults to ``<cwd>/output`` via ``resolve_output_dir``.
            verbose (bool): If True, downstream methods may emit progress
                messages via the logger. Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.

        Example:
            >>> pcm = PCM("data/2024/PCM FINAL/segment-01.xlsx", year=2024)
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        df = pd.read_excel(filepath)

        for col in self.NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        self.filepath = filepath
        self.df = df
        self.year = year
        self.output_dir = resolve_output_dir(output_dir)
        self.cleaned_dir = os.path.join(self.output_dir, "cleaned", str(year), "PCM")
        self.cleaned_path: str | None = None
        self.verbose = verbose

    def clean(self) -> Self:
        """Drop empty rows from the DataFrame.

        Removes any row that either has all values empty across every column
        or has any ``NaN`` in the columns listed in ``CLEAN_REQUIRED_COLUMNS``
        (limited to those actually present in the DataFrame). ``Ext GPS
        Latitude`` and ``Ext GPS Longitude`` are intentionally excluded — they
        are sparse in typical PCM exports and dropping on them removes almost
        every row.

        Returns:
            PCM: ``self``, to allow method chaining.

        Raises:
            ValueError: If the cleaned DataFrame is empty (no row satisfied
                ``CLEAN_REQUIRED_COLUMNS``), which usually means the source
                file is malformed or the required columns are missing.

        Example:
            >>> pcm = PCM("data/2024/PCM FINAL/segment-01.xlsx", year=2024)
            >>> pcm.clean()
        """
        required_present = [
            c for c in self.CLEAN_REQUIRED_COLUMNS if c in self.df.columns
        ]

        self.df = self.df.dropna(how="all")
        if required_present:
            self.df = self.df.dropna(subset=required_present)

        if self.df.empty:
            raise ValueError(
                f"Cleaned DataFrame is empty after applying CLEAN_REQUIRED_COLUMNS "
                f"({self.CLEAN_REQUIRED_COLUMNS}) to {self.filepath}"
            )

        self.save()

        return self

    def save(self) -> Self:
        """Save the current DataFrame under ``cleaned_dir``.

        Writes ``self.df`` to ``{cleaned_dir}/{original_filename}``, preserving
        the source Excel's basename. Creates the destination directory if it
        does not already exist.

        Returns:
            PCM: ``self``, to allow method chaining.

        Example:
            >>> pcm = PCM("data/2024/PCM FINAL/segment-01.xlsx", year=2024)
            >>> pcm.clean().save()
        """
        os.makedirs(self.cleaned_dir, exist_ok=True)

        filename = os.path.basename(self.filepath)
        target_path = os.path.join(self.cleaned_dir, filename)
        self.df.to_excel(target_path, index=False)
        self.cleaned_path = target_path

        return self

    def check(self) -> dict:
        """Run data-quality checks and return a summary dict.

        Checks that every column in ``COLUMNS`` is present and that the
        combination of ``UNIQUE_COLUMNS`` is unique across rows. Nothing is
        raised: findings are reported so results can be aggregated across many
        files.

        Returns:
            dict: A summary with the following keys:

                - ``filepath`` (str): Source file path.
                - ``is_valid`` (bool): True if no missing columns and no duplicates.
                - ``n_missing`` (int): Number of missing required columns.
                - ``n_duplicates`` (int): Number of duplicate rows by ``UNIQUE_COLUMNS``.
                - ``missing_columns`` (list[str]): Names of missing required columns.
                - ``duplicates`` (list[dict]): One dict per duplicate row with keys
                  ``row`` (DataFrame index) and the unique-column values.

        Example:
            >>> pcm.check()
            {'filepath': '...', 'is_valid': True, 'n_missing': 0, ...}
        """
        cleaned_path = os.path.join(self.cleaned_dir, os.path.basename(self.filepath))
        if os.path.isfile(cleaned_path):
            self.df = pd.read_excel(cleaned_path)
            self.cleaned_path = cleaned_path
        else:
            self.clean()

        missing_columns = [c for c in self.COLUMNS if c not in self.df.columns]

        unique_cols = [c for c in self.UNIQUE_COLUMNS if c in self.df.columns]
        if len(unique_cols) == len(self.UNIQUE_COLUMNS):
            duplicated = self.df.duplicated(subset=unique_cols, keep=False)
            dupes = self.df.loc[duplicated, unique_cols]
            duplicates = [
                {"row": idx, **{col: row[col] for col in unique_cols}}
                for idx, row in dupes.iterrows()
            ]
        else:
            duplicates = []

        return {
            "filepath": cleaned_path,
            "is_valid": not missing_columns and not duplicates,
            "n_missing": len(missing_columns),
            "n_duplicates": len(duplicates),
            "missing_columns": None if len(missing_columns) == 0 else missing_columns,
            "duplicates": None if len(duplicates) == 0 else duplicates,
        }
