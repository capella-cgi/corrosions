import os
import re
from typing import Self, Literal

import numpy as np
import pandas as pd

from corrosions.logging import logger
from corrosions.data.base_data import BaseData
from corrosions.utils.dataframe_utils import get_sheet_columns


class CIPS(BaseData):
    """CIPS (Close Interval Potential Survey)

    The CIPS (Close Interval Potential Survey) is a measurement of cathodic protection
    system potential taken at short intervals (typically 1–5 meters).
    The main objective of the CIPS survey is to evaluate the performance
    of the cathodic protection system applied along a buried pipeline.

    Additionally, CIPS can be used to identify interference or impacts caused by other
    cathodic protection systems, as well as stray currents from other facilities
    such as underground mining activities, electric trains, or power surges
    from high-voltage transmission towers.


    CIPS have two methods of cathodic protection:
    1. ICCP (Impressed Current Cathodic Protection)
    2. SACP (Sacrificial Anode Cathodic Protection)

    Inherits the fluent ``check`` / ``clean`` / ``save`` pipeline from
    ``BaseData``. Workbooks are not uniform: the data sheet may be named
    ``Data``, ``Sheet1``, after the segment, etc., next to chart, DCP and
    survey-info sheets. ``find_sheet`` picks the data sheet by its header
    before loading. ``fix`` aligns column names across export formats,
    ``check`` reports what is still missing, and ``clean`` normalizes
    ICCP/SACP voltages into a single ``Voltage`` column.

    Example:
        >>> cips = CIPS("data/2024/CIPS/segment-01.xlsx", year=2024)
        >>> cips.fix().check().clean().save()
        >>> cips.protection
        'ICCP'
    """

    KIND = "cips"

    REQUIRED_COLUMNS: list[str] = [
        "Latitude",
        "Longitude",
        "Comment",
        "DCP/Feature/DCVG Anomaly",
    ]

    NUMERIC_COLUMNS: list[str] = [
        "Latitude",
        "Longitude",
    ]

    CLEAN_REQUIRED_COLUMNS: list[str] = [
        "Latitude",
        "Longitude",
        "Voltage",
    ]

    UNIQUE_COLUMNS: tuple[str, str] = ("Latitude", "Longitude")

    ICCP_COLUMNS: list[str] = [
        "On Voltage",
        "Off Voltage",
    ]

    SACP_COLUMNS: list[str] = [
        "Voltage",
    ]

    # Present on every CIPS data sheet seen so far (2021-2026 exports).
    # "DCP Data" sheets use "DCP/Feature/Anomaly", so they do not match.
    SHEET_COLUMNS: list[str] = [
        "Latitude",
        "Longitude",
        "DCP/Feature/DCVG Anomaly",
    ]

    SHEET_POSSIBILITIES: list[str] = [
        "Data",
        "Sheet1",
        "Sequential File",
        "Sequential Files",
    ]

    # Applied by ``fix``. Other voltage columns (``-mV On``, ``Potential (-mV)``,
    # ``On Potential (mV)``, ...) are left untouched.
    RENAME_COLUMNS: dict[str, str] = {
        "Voltage (V)": "Voltage",
        "Off Voltage (V)": "Off Voltage",
    }

    # Years whose exports ``fix`` leaves as they are; ``check`` still reports
    # on them.
    SKIP_FIX_YEARS: tuple[int, ...] = (2021,)

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load a CIPS Excel file and coerce numeric columns.

        Args:
            filepath (str): Path to the source CIPS Excel file.
            year (int): Survey year for this file.
            output_dir (str | None): Destination root for downstream artifacts.
                Defaults to ``<cwd>/output`` via ``resolve_output_dir``.
            verbose (bool): If True, methods may emit progress messages.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
        """
        super().__init__(filepath, year, output_dir, verbose)
        self.protection: Literal["ICCP", "SACP"] = "ICCP"
        self.fixed: bool = False

    @classmethod
    def data_sheets(cls, sheet_columns: dict[str, list[str]]) -> list[str]:
        """Return the sheets that look like CIPS data, best match first.

        A sheet qualifies when its header row contains every column in
        ``SHEET_COLUMNS``, which rules out chart, ``DCP Data``, ``Survey Info``
        and empty sheets. Names listed in ``SHEET_POSSIBILITIES`` come first
        (in that order), then the remaining qualifying sheets in workbook
        order. This puts ``Data`` ahead of copies such as ``Raw Data``.

        Args:
            sheet_columns (dict[str, list[str]]): Sheet name -> header row, as
                returned by ``get_sheet_columns``.

        Returns:
            list[str]: Qualifying sheet names; empty if none qualify.
        """
        candidates = [
            sheet
            for sheet, columns in sheet_columns.items()
            if all(c in columns for c in cls.SHEET_COLUMNS)
        ]
        preferred = [s for s in cls.SHEET_POSSIBILITIES if s in candidates]
        return preferred + [s for s in candidates if s not in preferred]

    @classmethod
    def find_sheet(cls, filepath: str) -> str:
        """Return the sheet that holds the CIPS survey data.

        Reads only the header row of each sheet and returns the first entry of
        ``data_sheets``.

        Args:
            filepath (str): Path to the source CIPS Excel file.

        Returns:
            str: Name of the data sheet.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
            ValueError: If no sheet has the ``SHEET_COLUMNS`` header.

        Example:
            >>> CIPS.find_sheet("CIPS - ICCP 07 CLG 16 in Cilegon.xlsx")
            'Data'
        """
        sheet_columns = get_sheet_columns(filepath)
        candidates = cls.data_sheets(sheet_columns)

        if not candidates:
            raise ValueError(
                f"No CIPS data sheet in {filepath}: no sheet has the columns "
                f"{cls.SHEET_COLUMNS}. Sheets: {list(sheet_columns)}"
            )

        if len(candidates) > 1:
            logger.info(
                f"{filepath}: {len(candidates)} candidate data sheets "
                f"{candidates}, using {candidates[0]!r}"
            )

        return candidates[0]

    def fix(self) -> Self:
        """Align column names across CIPS export formats.

        - Renames columns per ``RENAME_COLUMNS`` (``Voltage (V)`` ->
          ``Voltage``, ``Off Voltage (V)`` -> ``Off Voltage``), unless the
          target column already exists. ``-mV`` / ``Potential`` columns are
          left untouched.
        - Adds an empty ``Comment`` column when there is none.

        Files from ``SKIP_FIX_YEARS`` (2021) are left as they are. Never raises;
        use ``check`` to see what is still missing. Running it twice is a no-op.

        Returns:
            Self: ``self``, to allow method chaining.

        Example:
            >>> CIPS("2022/CIPS/segment.xlsx", year=2022).fix().df.columns
            Index(['Index', ..., 'Voltage', 'Off Voltage', ...], dtype='object')
        """
        if self.fixed:
            return self
        self.fixed = True

        if self.year in self.SKIP_FIX_YEARS:
            if self.verbose:
                logger.info(f"Skipping fix for {self.year}: {self.filepath}")
            return self

        renames = {
            old: new
            for old, new in self.RENAME_COLUMNS.items()
            if old in self.df.columns and new not in self.df.columns
        }
        df = self.df.rename(columns=renames)

        added_comment = "Comment" not in df.columns
        if added_comment:
            df["Comment"] = ""

        if self.verbose and (renames or added_comment):
            logger.info(
                f"Fixed {self.filepath}: renamed {renames}, "
                f"added empty Comment: {added_comment}"
            )

        self.df = df

        return self

    def check(self) -> Self:
        """Run ``BaseData.check`` plus CIPS-specific checks.

        ``SHEET_COLUMNS`` is a subset of ``REQUIRED_COLUMNS``, so the base
        missing-column check covers both. On top of that ``self.report`` gets:

        - ``has_voltage`` (bool): at least one of ``ICCP_COLUMNS`` or
          ``SACP_COLUMNS`` is present. ``is_valid`` is False without it.

        Duplicate ``UNIQUE_COLUMNS`` rows are still counted (``n_duplicates``)
        but do not make the file invalid: repeated readings at one GPS point
        are normal in CIPS surveys, and ``clean`` removes them. So
        ``is_valid`` means: no missing required column and a voltage column.

        Call ``fix`` first to check the data as ``clean`` will see it.

        Returns:
            Self: ``self``, to allow method chaining.

        Example:
            >>> CIPS("segment.xlsx", year=2024).fix().check().report["has_voltage"]
            True
        """
        super().check()

        columns = self.df.columns
        has_voltage = any(
            c in columns for c in [*self.ICCP_COLUMNS, *self.SACP_COLUMNS]
        )

        self.report["has_voltage"] = has_voltage
        self.report["is_valid"] = self.report["n_missing"] == 0 and has_voltage

        return self

    def clean(self) -> Self:
        """Fix columns, normalize voltages, then drop unusable rows.

        Runs ``fix`` if it has not run yet, then ``_fix_voltage``, then
        ``BaseData.clean``: drops all-empty rows, rows whose ``Latitude`` or
        ``Longitude`` is ``0`` or empty, rows with an empty ``Voltage``, and
        duplicate (``Latitude``, ``Longitude``) rows (first reading kept).

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            ValueError: If the voltage columns cannot be resolved to ICCP or
                SACP, or if no row is left.
        """
        self.fix()
        self._fix_voltage()
        return super().clean()

    def _protection_from_filename(self) -> Literal["ICCP", "SACP"] | None:
        """Return ``ICCP`` / ``SACP`` when the filename names exactly one."""
        filename = os.path.basename(self.filepath).upper()
        found = set(re.findall(r"\b(ICCP|SACP)\b", filename))
        if found == {"ICCP"}:
            return "ICCP"
        if found == {"SACP"}:
            return "SACP"
        return None

    def _fix_voltage(self) -> None:
        """Normalize ICCP/SACP voltages into a single ``Voltage`` column.

        Protection is decided by the columns present:

        - ``On Voltage`` + ``Off Voltage``: ICCP.
        - ``Voltage`` + ``Off Voltage`` without ``On Voltage`` (2022 exports
          after ``fix``, 2024 exports): ICCP and SACP surveys share this
          layout, so the filename decides. ICCP takes ``Voltage`` as the ON
          reading (``On Voltage = Voltage``).
        - ``Voltage`` only: SACP.

        Readings are stored as negative potentials. A column whose first
        reading is positive is negated as a whole.

        - ICCP copies ``On Voltage`` into ``Voltage`` and negates ``Voltage``
          and ``Off Voltage`` independently (``On Voltage`` keeps the source
          sign).
        - SACP negates ``Voltage`` and sets ``On Voltage`` / ``Off Voltage``
          to NaN.

        Both add a ``protection`` column and set ``self.protection``.

        Raises:
            ValueError: If no ICCP/SACP layout matches, or the layout needs the
                filename and it names neither (or both) ``ICCP`` / ``SACP``.
        """

        def _fix_iccp(_df: pd.DataFrame) -> pd.DataFrame:
            """Fix and transform ICCP data."""
            if self.verbose:
                logger.info(f"Fixing ICCP: {self.filepath}")

            _df["On Voltage"] = pd.to_numeric(_df["On Voltage"], errors="coerce")
            _df["Off Voltage"] = pd.to_numeric(_df["Off Voltage"], errors="coerce")

            _df["Voltage"] = _df["On Voltage"]
            if _df.iloc[0]["Voltage"] > 0:
                _df["Voltage"] = _df["Voltage"] * -1

            if _df.iloc[0]["Off Voltage"] > 0:
                _df["Off Voltage"] = _df["Off Voltage"] * -1

            _df["protection"] = "ICCP"
            self.protection = "ICCP"

            return _df

        def _fix_sacp(_df: pd.DataFrame) -> pd.DataFrame:
            """Fix and transform SACP data."""
            if self.verbose:
                logger.info(f"Fixing SACP: {self.filepath}")

            _df["On Voltage"] = np.nan
            _df["Off Voltage"] = np.nan

            _df["Voltage"] = pd.to_numeric(_df["Voltage"], errors="coerce")
            if _df.iloc[0]["Voltage"] > 0:
                _df["Voltage"] = _df["Voltage"] * -1

            _df["protection"] = "SACP"
            self.protection = "SACP"

            return _df

        columns = self.df.columns
        if all(c in columns for c in self.ICCP_COLUMNS):
            self.df = _fix_iccp(self.df.copy())
        elif "Voltage" in columns and "Off Voltage" in columns:
            protection = self._protection_from_filename()
            if protection == "ICCP":
                df = self.df.copy()
                df["On Voltage"] = df["Voltage"]
                self.df = _fix_iccp(df)
            elif protection == "SACP":
                self.df = _fix_sacp(self.df.copy())
            else:
                raise ValueError(
                    f"Cannot tell ICCP from SACP for {self.filepath}: it has "
                    "'Voltage' + 'Off Voltage' and the filename names neither "
                    "(or both)."
                )
        elif all(c in columns for c in self.SACP_COLUMNS):
            self.df = _fix_sacp(self.df.copy())
        else:
            raise ValueError(
                f"Invalid CIPS data: {self.filepath} (sheet {self.sheet_name!r}). "
                f"Expected either ICCP {self.ICCP_COLUMNS} or SACP "
                f"{self.SACP_COLUMNS} columns, found {list(self.df.columns)}"
            )
