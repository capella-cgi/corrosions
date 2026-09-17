import os

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
        "Ext GPS Latitude",
        "Ext GPS Longitude",
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
        self.verbose = verbose

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
            "filepath": self.filepath,
            "is_valid": not missing_columns and not duplicates,
            "n_missing": len(missing_columns),
            "n_duplicates": len(duplicates),
            "missing_columns": missing_columns,
            "duplicates": duplicates,
        }
