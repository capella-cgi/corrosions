import os
from typing import Self

import numpy as np
import pandas as pd

from corrosions.data.base_data import BaseData
from corrosions.utils.geo_utils import calculate_distance


class PCM(BaseData):
    """Pipeline Current Mapping (PCM) survey reader.

    PCM surveys are performed to determine the coating integrity of underground
    gas pipelines. This class loads a single PCM Excel export, coerces its
    numeric columns, and inherits the fluent ``check`` / ``clean`` / ``save``
    pipeline from ``BaseData``. ``normalize`` adds the current-loss analysis
    and writes the normalized Excel/JSON.

    Attributes:
        REQUIRED_COLUMNS (list[str]): Required columns expected in the source Excel.
        NUMERIC_COLUMNS (list[str]): Columns coerced to numeric via
            ``pd.to_numeric(..., errors="coerce")`` at load time.
        CLEAN_REQUIRED_COLUMNS (list[str]): Columns whose presence and
            non-NaN value is required for a row to survive ``clean``. Excludes
            ``Ext GPS Latitude`` / ``Ext GPS Longitude`` because they are
            frequently blank in real PCM exports.
        UNIQUE_COLUMNS (tuple[str, str]): Columns whose combination must be
            unique across rows (used by ``check`` to flag duplicates).
        medium_to_high_percentage (float): Share of readings whose
            ``Condition`` is ``Medium to High``, in percent; set by
            ``normalize`` (``0.0`` before).
        medium_to_poor_percentage (float): ``100 - medium_to_high_percentage``,
            the ``Medium to Poor`` share.

    Example:
        >>> pcm = PCM("data/2024/PCM/segment-01.xlsx", year=2024)
        >>> pcm.clean().check().save().normalize()
        >>> pcm.report["is_valid"]
        True
    """

    KIND = "pcm"

    REQUIRED_COLUMNS: list[str] = [
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Comment (0-100)",
        "Gain (dB)",
        "Depth (m)",
    ]

    NUMERIC_COLUMNS: list[str] = [
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
        "Depth (m)",
    ]

    CLEAN_REQUIRED_COLUMNS: list[str] = [
        "4Hz Current (A)",
        "Int GPS Latitude",
        "Int GPS Longitude",
        "Gain (dB)",
    ]

    UNIQUE_COLUMNS: tuple[str, str] = ("Int GPS Latitude", "Int GPS Longitude")

    # normalize() writes these columns, in this order, to the JSON under
    # these keys (see BaseData.json_frame).
    JSON_COLUMNS: dict[str, str] = {
        "Int GPS Latitude": "latitude",
        "Int GPS Longitude": "longitude",
        "Real Distance": "real_distance",
        "4Hz Current (A)": "4hz_current_a",
        "dbma": "dbma",
        "Current Loss Rate": "current_loss_rate",
        "Depth (m)": "depth_m",
        "Condition": "condition",
        "Comment (0-100)": "comment_0_100",
    }

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load a PCM Excel file and coerce numeric columns.

        Args:
            filepath (str): Path to the source PCM Excel file.
            year (int): Survey year for this file.
            output_dir (str | None): Destination root for downstream artifacts.
                Defaults to ``<cwd>/output`` via ``resolve_output_dir``.
            verbose (bool): If True, methods may emit progress messages.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
        """
        super().__init__(filepath, year, output_dir, verbose)

        # Share of readings (0-100) per Condition, set by normalize().
        self.medium_to_poor_percentage: float = 0.0
        self.medium_to_high_percentage: float = 0.0

    def clean(self) -> Self:
        """Drop dropped readings, then apply ``BaseData.clean``.

        A reading with ``4Hz Current (A) <= 0`` is a lost signal (the locator
        records ``0`` current and ``0`` depth): it has no ``dbma``, so it
        would get no loss rate, leave the next reading without one too, and
        count as ``Medium to Poor``. It is dropped, so the next reading's
        rate is measured against the last valid one. Then ``BaseData.clean``
        drops empty rows, rows with an empty or ``0`` coordinate, rows with
        an empty ``CLEAN_REQUIRED_COLUMNS`` value, and duplicate points.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            ValueError: If no row is left.
        """
        if "4Hz Current (A)" in self.df.columns:
            current = self.df["4Hz Current (A)"]
            # NaN is left for BaseData.clean (CLEAN_REQUIRED_COLUMNS)
            self.df = self.df[~(current <= 0)]
        return super().clean()

    @staticmethod
    def current_loss(
        dbma: pd.Series, distance: pd.Series
    ) -> tuple[pd.Series, pd.Series]:
        """Return the ``Current Loss Rate`` and ``Condition`` of each reading.

        Shared by ``normalize`` and ``corrosions.sync.SyncData``, so a survey
        that is reversed later gets the same values as a fresh one.

        - Rate: ``|Δdbma / distance| * 1000`` against the previous reading,
          rounded to 2 decimals; ``0`` for the first reading and for a zero
          step; empty when either ``dbma`` is empty.
        - Condition: ``"Medium to High"`` when the rate is ``<= 50``,
          otherwise ``"Medium to Poor"``, including an empty rate.

        Args:
            dbma (pd.Series): ``dbma`` of each reading, in survey order.
            distance (pd.Series): Meters from the previous reading (``0`` for
                the first), same index as ``dbma``.

        Returns:
            tuple[pd.Series, pd.Series]: Rate and condition, indexed like
                ``dbma``.
        """
        rate = ((dbma.diff() / distance).abs() * 1000).round(2)
        rate = rate.where(distance > 0, 0.0)
        # An empty rate (no dbma) compares False, so it is "Medium to Poor".
        condition = pd.Series(
            np.where(rate <= 50, "Medium to High", "Medium to Poor"),
            index=dbma.index,
            dtype=object,
        )
        return rate, condition

    def normalize(self, normalize_dir: str | None = None) -> Self:
        """Add current-loss analysis, then save Excel and JSON.

        Adds to ``self.df``:

        - ``Distance``: meters from the previous reading (``0`` for the
          first), from the ``Int GPS`` coordinates, as in ``CIPS.normalize``.
          It replaces the ``Distance`` column some exports already have.
        - ``Real Distance``: running total of ``Distance``, in meters.
        - ``dbma``: ``20 * log10(4Hz Current (A) * 1000)``, rounded to 2
          decimals. ``clean`` drops readings with a current ``<= 0`` (log is
          undefined); should one remain, its ``dbma`` is empty.
        - ``Current Loss Rate``: ``|Δdbma / Δdistance| * 1000`` between a
          reading and the previous one, rounded to 2 decimals; ``0`` for the
          first reading. Empty when either ``dbma`` is empty.
        - ``Condition``: ``"Medium to High"`` when ``Current Loss Rate <= 50``,
          otherwise ``"Medium to Poor"``, including when the rate is empty
          (no ``dbma``).

        Sets ``self.medium_to_high_percentage`` (share of ``Medium to High``
        readings, in percent, rounded to 2 decimals) and
        ``self.medium_to_poor_percentage`` (``100 -`` that). Reversing the
        survey (``SyncData``) keeps the same reading pairs, so it does not
        change them.

        Then writes two files, sets ``self.normalized`` and adds to
        ``self.report`` (see ``BaseData._report_normalize``): ``normalized``,
        ``n_normalized``, ``normalize_excel_filepath``,
        ``normalize_json_filepath``, ``length_km`` (last ``Real Distance`` in
        km, 3 decimals), ``medium_to_high_percentage`` and
        ``medium_to_poor_percentage``. The files:

        - ``normalize_excel_filepath``
          (``<output_dir>/normalize/pcm/excel/<year>-<slug>.xlsx``): ``self.df``
          with its original column names, without the index.
        - ``normalize_json_filepath``
          (``<output_dir>/normalize/pcm/json/<year>-<slug>.json``): one record
          per row with only these keys, in this order: ``latitude`` and
          ``longitude`` (from ``Int GPS Latitude`` / ``Longitude``, the same
          keys as the CIPS JSON), ``real_distance``, ``4hz_current_a``,
          ``dbma``, ``current_loss_rate``, ``depth_m``, ``condition`` and
          ``comment_0_100``. Empty cells, including blank text, are ``null``.

        Rows are taken in their current order (previous row = row above). The
        index is not used, so the gaps ``clean`` leaves in it are fine. Call
        after ``clean``, which makes sure every coordinate is present and
        deduplicated.

        Args:
            normalize_dir (str | None): Overrides ``self.normalize_dir``
                (default ``<output_dir>/normalize/pcm``); the files go to its
                ``excel`` / ``json`` sub-folders and ``normalize_excel_dir``,
                ``normalize_json_dir`` and both file paths follow. ``None``
                keeps the current one.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If ``clean`` has not completed yet.
            ValueError: If a column ``normalize`` reads is missing
                (``Int GPS Latitude`` / ``Longitude``, ``4Hz Current (A)``,
                ``Depth (m)``, ``Comment (0-100)``).

        Example:
            >>> pcm = PCM("segment.xlsx", year=2024).clean().normalize()
            >>> pcm.df["Condition"].value_counts()
            >>> pcm.normalize_json_filepath
            'output/normalize/pcm/json/2024-segment.json'
        """
        if not self.cleaned:
            raise RuntimeError(f"Run clean() before normalize(): {self.filepath}")
        self._set_normalize_dir(normalize_dir)

        needed = [
            "Int GPS Latitude",
            "Int GPS Longitude",
            "4Hz Current (A)",
            "Depth (m)",
            "Comment (0-100)",
        ]
        missing = [c for c in needed if c not in self.df.columns]
        if missing:
            raise ValueError(f"Cannot normalize {self.filepath}: missing {missing}")

        df = self.df.copy()

        lat, lon = df["Int GPS Latitude"], df["Int GPS Longitude"]
        distance = pd.Series(
            calculate_distance(lat.shift(), lon.shift(), lat, lon), index=df.index
        ).fillna(0.0)

        df["Distance"] = distance
        df["Real Distance"] = distance.cumsum()

        # log10 is undefined for a current <= 0, so dbma is left empty there.
        current = df["4Hz Current (A)"]
        df["dbma"] = (20 * np.log10(current.where(current > 0) * 1000)).round(2)

        df["Current Loss Rate"], df["Condition"] = self.current_loss(
            df["dbma"], distance
        )

        # clean() leaves at least one row; every reading has one of the two
        high = int((df["Condition"] == "Medium to High").sum())
        self.medium_to_high_percentage = round(100 * high / len(df), 2)
        self.medium_to_poor_percentage = round(100 - self.medium_to_high_percentage, 2)

        # Save to excel with original column name
        os.makedirs(self.normalize_excel_dir, exist_ok=True)
        df.to_excel(self.normalize_excel_filepath, index=False)

        self.df = df

        # Save to JSON (JSON_COLUMNS); blank text becomes null.
        df = self.json_frame(df)
        os.makedirs(self.normalize_json_dir, exist_ok=True)
        df.to_json(self.normalize_json_filepath, orient="records")

        self.normalized = True
        self._report_normalize(
            length_km=round(float(self.df["Real Distance"].iloc[-1]) / 1000, 3),
            medium_to_high_percentage=self.medium_to_high_percentage,
            medium_to_poor_percentage=self.medium_to_poor_percentage,
        )

        return self
