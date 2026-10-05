import os
import re
from typing import Self, Literal

import numpy as np
import pandas as pd

from corrosions.logging import logger
from corrosions.data.base_data import BaseData
from corrosions.utils.geo_utils import calculate_distance
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
    before loading, and column names are aligned across export formats
    while loading (``_fix_columns``). ``clean`` normalizes ICCP/SACP
    voltages into a single ``Voltage`` column and ``check`` reports what
    is still missing.

    Example:
        >>> cips = CIPS("data/2024/CIPS/segment-01.xlsx", year=2024)
        >>> cips.clean().check().normalize()
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

    # normalize() writes these columns, in this order, to the JSON under
    # these keys (see BaseData.json_frame).
    JSON_COLUMNS: dict[str, str] = {
        "Voltage": "voltage",
        "Off Voltage": "off_voltage",
        "Latitude": "latitude",
        "Longitude": "longitude",
        "Real Distance": "real_distance",
        "Condition": "condition",
        "Comment": "comment",
        "DCP/Feature/DCVG Anomaly": "dcp_feature_dcvg_anomaly",
    }

    # Applied by ``_fix_columns``. Other voltage columns (``-mV On``, ``Potential (-mV)``,
    # ``On Potential (mV)``, ...) are left untouched.
    RENAME_COLUMNS: dict[str, str] = {
        "Voltage (V)": "Voltage",
        "Off Voltage (V)": "Off Voltage",
    }

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load a CIPS Excel file, coerce numeric columns and align names.

        Column names are aligned right after loading (``_fix_columns``), so
        ``check`` and ``clean`` see the same columns whatever their order.

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

        # Share of readings (0-100) per Condition, set by normalize():
        # PROTECTED + OVER PROTECTED, and UNPROTECTED.
        self.protected_percentage: float = 0.0
        self.unprotected_percentage: float = 0.0

        self._fix_columns()

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

    def _fix_columns(self) -> None:
        """Align column names across CIPS export formats.

        Called by ``__init__``.

        - Renames columns per ``RENAME_COLUMNS`` (``Voltage (V)`` ->
          ``Voltage``, ``Off Voltage (V)`` -> ``Off Voltage``), unless the
          target column already exists. ``-mV`` / ``Potential`` columns are
          left untouched.
        - Adds an empty ``Comment`` column when there is none.

        Never raises; use ``check`` to see what is still missing.
        """
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

        Run it after ``clean`` (like ``PCM`` / ``AcvgDcvgFile``) to describe
        the cleaned data; ``n_duplicates`` is then 0 because ``clean``
        removes duplicates.

        Returns:
            Self: ``self``, to allow method chaining.

        Example:
            >>> CIPS("segment.xlsx", year=2024).clean().check().report["has_voltage"]
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
        """Normalize voltages, then drop unusable rows.

        Runs ``_fix_voltage`` first. ICCP readings need both ``On Voltage``
        and ``Off Voltage``, so ICCP rows
        missing either one are dropped. SACP only needs ``Voltage`` (its
        ``On Voltage`` / ``Off Voltage`` are always empty). Then
        ``BaseData.clean`` drops all-empty rows, rows whose ``Latitude`` or
        ``Longitude`` is ``0`` or empty, rows with an empty ``Voltage``, and
        duplicate (``Latitude``, ``Longitude``) rows (first reading kept).
        ``self.cleaned`` is set by ``BaseData.clean``, so only when every
        step succeeded.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            ValueError: If the voltage columns cannot be resolved to ICCP or
                SACP, or if no row is left.
        """
        self._fix_voltage()
        if self.protection == "ICCP":
            self.df = self.df.dropna(subset=self.ICCP_COLUMNS)
        return super().clean()

    def normalize(self, normalize_dir: str | None = None) -> Self:
        """Add distances and protection condition, then save Excel and JSON.

        Adds to ``self.df``:

        - ``Distance``: meters from the previous reading (``0`` for the first).
        - ``Real Distance``: running total from the first reading, in meters.
        - ``Condition``: protection level of each reading, from ``Off Voltage``
          for ICCP or ``Voltage`` for SACP (in volts):

          - ``PROTECTED``: ``-1.2 < V <= -0.85``
          - ``OVER PROTECTED``: ``V <= -1.2``
          - ``UNPROTECTED``: anything else, including an empty reading.

        Sets ``self.protected_percentage`` (share of readings that are
        ``PROTECTED`` or ``OVER PROTECTED``) and ``self.unprotected_percentage``
        (share that is ``UNPROTECTED``), in percent of all readings, rounded to
        2 decimals; together they make 100.

        Then writes two files, sets ``self.normalized`` and adds to
        ``self.report`` (see ``BaseData._report_normalize``): ``normalized``,
        ``n_normalized``, ``normalize_excel_filepath``,
        ``normalize_json_filepath``, ``protection``, ``length_km`` (last
        ``Real Distance`` in km, 3 decimals), ``protected_percentage`` and
        ``unprotected_percentage``. The files:

        - ``normalize_excel_filepath``
          (``<output_dir>/normalize/cips/excel/<year>-<slug>.xlsx``): ``self.df``
          with its original column names, without the index.
        - ``normalize_json_filepath``
          (``<output_dir>/normalize/cips/json/<year>-<slug>.json``): one record
          per row with only these keys, in this order: ``voltage``,
          ``off_voltage``, ``latitude``, ``longitude``, ``real_distance``,
          ``condition``, ``comment`` and ``dcp_feature_dcvg_anomaly``. Empty
          cells are ``null``, including empty or blank text (such as the
          ``""`` ``Comment`` added by ``_fix_columns``). ``off_voltage`` is always
          ``null`` for SACP.

        Rows are taken in their current order. The index is not used, so the
        gaps ``clean`` leaves in it are fine. Call after ``clean``, which sets
        ``protection`` and makes sure every coordinate is present and
        deduplicated.

        Args:
            normalize_dir (str | None): Overrides ``self.normalize_dir``
                (default ``<output_dir>/normalize/cips``); the files go to its
                ``excel`` / ``json`` sub-folders and ``normalize_excel_dir``,
                ``normalize_json_dir`` and both file paths follow. ``None``
                keeps the current one.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If ``clean`` has not completed yet:
                ``_fix_voltage`` (run by ``clean``) sets
                ``protection`` and the voltage columns ``normalize`` reads.

        Example:
            >>> cips = CIPS("segment.xlsx", year=2024).clean().normalize()
            >>> cips.df["Real Distance"].iloc[-1]  # survey length in meters
            >>> cips.normalize_json_filepath
            'output/normalize/cips/json/2024-segment.json'
        """
        if not self.cleaned:
            raise RuntimeError(f"Run clean() before normalize(): {self.filepath}")
        self._set_normalize_dir(normalize_dir)

        def _condition(voltage: float) -> str:
            if -1.2 < voltage <= -0.85:
                return "PROTECTED"
            if voltage <= -1.2:
                return "OVER PROTECTED"
            return "UNPROTECTED"

        df = self.df.copy()
        lat, lon = df["Latitude"], df["Longitude"]
        distance = pd.Series(
            calculate_distance(lat.shift(), lon.shift(), lat, lon), index=df.index
        ).fillna(0.0)

        df["Distance"] = distance
        df["Real Distance"] = distance.cumsum()

        voltage_column = "Voltage" if self.protection == "SACP" else "Off Voltage"
        df["Condition"] = df[voltage_column].apply(lambda x: _condition(x))

        # clean() leaves at least one row, so len(df) > 0
        counts = df["Condition"].value_counts()
        protected = counts.get("PROTECTED", 0) + counts.get("OVER PROTECTED", 0)
        self.protected_percentage = round(100 * float(protected) / len(df), 2)
        # every reading has one of the three conditions
        self.unprotected_percentage = round(100 - self.protected_percentage, 2)

        # Save to excel with original column name
        os.makedirs(self.normalize_excel_dir, exist_ok=True)
        df.to_excel(self.normalize_excel_filepath, index=False)

        self.df = df

        # Save to JSON (JSON_COLUMNS). Empty or blank text cells (e.g. the ""
        # Comment added by _fix_columns) become null, like empty numbers.
        df = self.json_frame(df)
        os.makedirs(self.normalize_json_dir, exist_ok=True)
        df.to_json(self.normalize_json_filepath, orient="records")

        self.normalized = True
        self._report_normalize(
            protection=self.protection,
            length_km=round(float(self.df["Real Distance"].iloc[-1]) / 1000, 3),
            protected_percentage=self.protected_percentage,
            unprotected_percentage=self.unprotected_percentage,
        )

        return self

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
          after ``_fix_columns``, 2024 exports): ICCP and SACP surveys share this
          layout, so the filename decides. ICCP takes ``Voltage`` as the ON
          reading (``On Voltage = Voltage``).
        - ``Voltage`` only: SACP.

        Readings are stored as negative potentials. A column whose first
        non-empty reading is positive is negated as a whole.

        - ICCP copies ``On Voltage`` into ``Voltage`` and negates ``Voltage``
          and ``Off Voltage`` independently (``On Voltage`` keeps the source
          sign).
        - SACP negates ``Voltage`` and sets ``On Voltage`` / ``Off Voltage``
          to NaN.

        Both add a ``Protection`` column and set ``self.protection``.

        Raises:
            ValueError: If no ICCP/SACP layout matches, or the layout needs the
                filename and it names neither (or both) ``ICCP`` / ``SACP``.
        """

        def _as_negative(values: pd.Series) -> pd.Series:
            """Negate ``values`` when its first non-empty reading is positive.

            Empty leading rows are skipped, so they cannot hide the sign. An
            all-empty column is returned unchanged.
            """
            readings = values.dropna()
            if not readings.empty and readings.iloc[0] > 0:
                return values * -1
            return values

        def _fix_iccp(_df: pd.DataFrame) -> pd.DataFrame:
            """Fix and transform ICCP data."""
            if self.verbose:
                logger.info(f"Fixing ICCP: {self.filepath}")

            _df["On Voltage"] = pd.to_numeric(_df["On Voltage"], errors="coerce")
            _df["Off Voltage"] = pd.to_numeric(_df["Off Voltage"], errors="coerce")

            _df["Voltage"] = _as_negative(_df["On Voltage"])
            _df["Off Voltage"] = _as_negative(_df["Off Voltage"])

            _df["Protection"] = "ICCP"
            self.protection = "ICCP"

            return _df

        def _fix_sacp(_df: pd.DataFrame) -> pd.DataFrame:
            """Fix and transform SACP data."""
            if self.verbose:
                logger.info(f"Fixing SACP: {self.filepath}")

            _df["On Voltage"] = np.nan
            _df["Off Voltage"] = np.nan

            _df["Voltage"] = _as_negative(
                pd.to_numeric(_df["Voltage"], errors="coerce")
            )

            _df["Protection"] = "SACP"
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
