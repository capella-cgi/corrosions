"""ACVG/DCVG anomaly data: extract per segment and link it to the file index.

ACVG/DCVG surveys are saved as one workbook per year, listed in an index
workbook (``Year``, ``Filename``). Each workbook has one sheet per area
(``AcvgDcvg.SHEET_NAMES``) next to non-data sheets (e.g. ``Contoh format
Gabungan``). Every row is one anomaly (a point) on a pipeline segment.

``AcvgDcvg`` reads the anomalies, matches each group of anomalies to a row of
the CIPS/PCM file index (by segment name, else by the nearest normalized CIPS
track), writes one Excel per matched segment and adds its filename to the
index as ``ACVG_DCVG``.

Example:
    >>> acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021])
    >>> csv = "output/file_index_idda-pcm-cips-file-list.csv"
    >>> acvg.load().match(csv).rebuild()
    >>> report = acvg.assign_index()
"""

import os
import json
from typing import Self
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from slugify import slugify

from corrosions.logging import logger
from corrosions.data.base_data import BaseData
from corrosions.utils.geo_utils import parse_coordinate, calculate_distance
from corrosions.utils.path_utils import resolve_output_dir
from corrosions.utils.dataframe_utils import get_sheets


class AcvgDcvg:
    """Alternative Current Voltage Gradient (ACVG) and Direct Current Voltage
    Gradient (DCVG) reader.

    Fluent pipeline: ``load()`` reads the anomalies, ``match(index_csv)`` links
    every anomaly to a file-index row, ``rebuild()`` writes one Excel per
    segment, ``clean()`` / ``normalize()`` run ``AcvgDcvgFile`` on each of them
    (same ``cleaned`` / ``normalize`` layout as CIPS and PCM), and
    ``assign_index()`` adds the ``ACVG_DCVG`` column to the index.

    Attributes:
        SHEET_NAMES (tuple[str, ...]): Area sheets that hold anomalies; any
            other sheet is skipped.
        REQUIRED_COLUMNS (list[str]): Columns every area sheet must have (after
            stripping surrounding spaces from the header).
        NUMERIC_COLUMNS (list[str]): Columns coerced to numbers (``"61.80%"``
            -> ``61.8``; ``"N/A"``, ``"-"``, ``"not detected"`` -> empty).
        DATE_COLUMNS (tuple[str, str]): Survey dates; a row dated in another
            year than its workbook is dropped (copied template rows).
        MAX_DISTANCE_M (float): Largest distance (meters) between an anomaly
            and the CIPS track it is linked to.
        DEFAULT_DATA_DIR (str): Folder of the yearly workbooks.
        DESTINATION_SUBDIR (str): Sub-folder per year for the extracted files.
        INDEX_COLUMN (str): Column added to the file index.
        filepath (str): Path to the ACVG/DCVG index workbook.
        data_dir (str): Folder of the yearly workbooks.
        df (pd.DataFrame): The index (``Year``, ``Filename``), minus
            ``skip_years``.
        skip_years (list[int]): Survey years left out.
        anomalies (pd.DataFrame | None): One row per anomaly after ``load``.
        load_report (pd.DataFrame | None): Skipped sheets, sheets with missing
            columns and dropped rows, from ``load``.
        groups (pd.DataFrame | None): Match report after ``match``: one row
            per (index row, method), plus one per unmatched name group (see
            ``match``).
        index_csv (str | None): File index CSV used by ``match``.
        output_files (list[str]): Paths written by ``rebuild``.
        file_report (pd.DataFrame | None): One row per extracted file after
            ``clean`` / ``normalize`` (see ``clean``).
        verbose (bool): If True, log progress.

    Example:
        >>> acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021])
        >>> acvg.load().match("output/file_index_idda-pcm-cips-file-list.csv")
        >>> acvg.rebuild().assign_index()
    """

    SHEET_NAMES = (
        "Bekasi",
        "Bogor",
        "Cilegon",
        "Cirebon",
        "Jakarta",
        "Karawang",
        "Tangerang",
    )

    REQUIRED_COLUMNS: list[str] = [
        "Segmen",
        "Lokasi Anomali",
        "Kondisi Permukaan",
        "Dia (inch)",
        "Latitude",
        "Longitude",
        "On Potential (volt)",
        "Off Potential (volt)",
        "IR Drop (%)",
        "Hasil ACVG (dB)",
        "Kedalaman Pipa (m)",
        "%drop PCM",
        "Tgl DCVG",
        "Tgl ACVG",
    ]

    NUMERIC_COLUMNS: list[str] = [
        "Dia (inch)",
        "On Potential (volt)",
        "Off Potential (volt)",
        "IR Drop (%)",
        "Hasil ACVG (dB)",
        "Kedalaman Pipa (m)",
        "%drop PCM",
    ]

    DATE_COLUMNS: tuple[str, str] = ("Tgl DCVG", "Tgl ACVG")

    MAX_DISTANCE_M: float = 500.0

    DEFAULT_DATA_DIR: str = r"D:\Data\ACVG DCVG 2021-2025"

    DESTINATION_SUBDIR: str = "ACVG_DCVG"

    INDEX_COLUMN: str = "ACVG_DCVG"

    FILE_REPORT_COLUMNS: list[str] = [
        "year",
        "filename",
        "n_anomalies",
        "n_duplicates",
        "n_cleaned",
        "cleaned_path",
        "cips_file",
        "normalized_file",
        "count",
        "n_on_cips",
        "reason",
    ]

    def __init__(
        self,
        filepath: str,
        data_dir: str = DEFAULT_DATA_DIR,
        skip_years: list[int] | None = None,
        verbose: bool = False,
    ):
        """Load the ACVG/DCVG index and check its workbooks exist.

        Args:
            filepath (str): Index workbook with ``Year`` and ``Filename``.
            data_dir (str): Folder of the yearly workbooks. Defaults to
                ``DEFAULT_DATA_DIR``.
            skip_years (list[int] | None): Survey years to leave out.
            verbose (bool): If True, log progress. Defaults to ``False``.

        Raises:
            FileNotFoundError: If the index or a listed workbook is missing.
            KeyError: If the index has no ``Year`` or ``Filename`` column.

        Example:
            >>> acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021])
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        df = pd.read_excel(filepath)
        missing = [c for c in ("Year", "Filename") if c not in df.columns]
        if missing:
            raise KeyError(f"{filepath}: columns not found: {missing}")
        df = df.dropna(subset=["Year", "Filename"])
        df["Year"] = df["Year"].astype(int)

        self.verbose = verbose
        self.skip_years: list[int] = sorted(set(skip_years or []))
        if self.skip_years:
            skipped = df["Year"].isin(self.skip_years)
            df = df[~skipped].reset_index(drop=True)
            if self.verbose:
                logger.info(
                    f"Skipped {int(skipped.sum())} rows from years {self.skip_years}"
                )

        missing_files = [
            name
            for name in df["Filename"]
            if not os.path.isfile(os.path.join(data_dir, name))
        ]
        if missing_files:
            raise FileNotFoundError(
                f"Workbooks not found in {data_dir}: {missing_files}"
            )

        self.filepath = filepath
        self.data_dir = data_dir
        self.df = df
        self.anomalies: pd.DataFrame | None = None
        self.load_report: pd.DataFrame | None = None
        self.groups: pd.DataFrame | None = None
        self.index_csv: str | None = None
        self.output_files: list[str] = []
        self.file_report: pd.DataFrame | None = None
        # Kept by match() for unlinked_segments() and normalize().
        self._index: pd.DataFrame | None = None
        self._tracks: dict[int, dict[int, tuple[str, np.ndarray]]] = {}
        self._max_distance: float = self.MAX_DISTANCE_M
        self._normalize_dir: str = ""
        # Kept by rebuild() for clean() / normalize(): path -> (year, CIPS JSON).
        self._output_dir: str | None = None
        self._file_info: dict[str, tuple[int, str | None]] = {}
        self._files: dict[str, AcvgDcvgFile] = {}

    def load(self) -> Self:
        """Read every area sheet of every workbook into ``self.anomalies``.

        Per workbook (one per year): only ``SHEET_NAMES`` sheets are read.
        Header names are stripped of surrounding spaces, and a sheet missing
        any ``REQUIRED_COLUMNS`` is skipped. Rows without a ``Segmen`` are
        dropped (notes, empty rows). ``Latitude`` / ``Longitude`` are parsed
        with ``parse_coordinate`` (numbers and degrees-minutes-seconds),
        ``NUMERIC_COLUMNS`` are coerced to numbers, and a row with a real date
        in ``DATE_COLUMNS`` from another year is dropped. ``Year`` and ``Area``
        (the sheet) are added in front. Every skipped sheet and dropped row is
        listed in ``self.load_report``.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            ValueError: If no anomaly is left.

        Example:
            >>> AcvgDcvg("IDDA - ACVG FIle List.xlsx").load().anomalies.shape
        """
        frames: list[pd.DataFrame] = []
        report: list[dict] = []

        for _, entry in self.df.iterrows():
            year = int(entry["Year"])
            path = os.path.join(self.data_dir, entry["Filename"])
            sheets = get_sheets(path)
            report += [
                {"year": year, "sheet": s, "issue": "not an area sheet", "rows": None}
                for s in sheets
                if s not in self.SHEET_NAMES
            ]
            area_sheets = [s for s in sheets if s in self.SHEET_NAMES]
            if not area_sheets:
                continue

            for sheet, df in pd.read_excel(path, sheet_name=area_sheets).items():
                df.columns = [str(c).strip() for c in df.columns]
                missing = [c for c in self.REQUIRED_COLUMNS if c not in df.columns]
                if missing:
                    report.append(
                        {
                            "year": year,
                            "sheet": sheet,
                            "issue": f"missing columns {missing}",
                            "rows": len(df),
                        }
                    )
                    continue

                segment = df["Segmen"].astype("string").str.strip()
                df = df[segment.notna() & segment.ne("")].copy()
                df["Segmen"] = df["Segmen"].astype(str).str.strip()

                other_year = df.apply(_dated_elsewhere, axis=1, args=(year,))
                if other_year.any():
                    report.append(
                        {
                            "year": year,
                            "sheet": sheet,
                            "issue": "dated in another year: "
                            + ", ".join(df.loc[other_year, "Segmen"].unique()),
                            "rows": int(other_year.sum()),
                        }
                    )
                    df = df[~other_year]

                df.insert(0, "Year", year)
                df.insert(1, "Area", sheet)
                frames.append(df)

        if not frames:
            raise ValueError(f"No ACVG/DCVG anomalies found in {self.data_dir}")

        anomalies = pd.concat(frames, ignore_index=True)
        for column in ("Latitude", "Longitude"):
            anomalies[column] = anomalies[column].map(parse_coordinate).astype(float)
        for column in self.NUMERIC_COLUMNS:
            anomalies[column] = _to_number(anomalies[column])

        self.anomalies = anomalies
        self.load_report = pd.DataFrame(
            report, columns=["year", "sheet", "issue", "rows"]
        )

        if self.verbose:
            logger.info(
                f"Loaded {len(anomalies)} ACVG/DCVG anomalies; "
                f"{len(self.load_report)} sheet issues"
            )

        return self

    def match(
        self,
        index_csv: str,
        normalize_dir: str | None = None,
        max_distance_m: float | None = None,
    ) -> Self:
        """Link every anomaly to a row of the file index.

        1. **name** (per group): a group is the anomalies sharing ``Year``,
           ``Area``, ``Segmen`` and ``Dia (inch)``. When ``slugify(Segmen)``
           equals the slug of a same-year index ``Segment`` or ``Sub Segment``
           (the same ``Diameter`` wins a tie), all its anomalies go to that
           row.
        2. **cips** (per anomaly): every other anomaly goes to the same-year
           index row whose normalized CIPS track
           (``<normalize_dir>/cips/json/<year>-<slug of CIPS>.json``, the name
           ``CIPS.normalize`` writes) passes closest to it, if within
           ``max_distance_m``. A group can therefore be split: anomalies named
           after a parent pipeline go to the index section they lie on, and
           anomalies at a segment border go to the segment they lie on.
        3. **none**: the rest stay unmatched, grouped by name.

        Anomalies linked to a row get that row's file name,
        ``acvg-dcvg-<segment>-<diameter>-<area>.xlsx`` (slugified, from the
        index), so every linked row has exactly one file. Unmatched groups use
        their own ``Segmen``, ``Dia (inch)`` and sheet.

        Args:
            index_csv (str): File-index CSV (``FileIndex.save``), with
                ``Year``, ``Area``, ``Segment``, ``Sub Segment``, ``Diameter``
                and ``CIPS``.
            normalize_dir (str | None): Root of the normalized files. Defaults
                to ``<cwd>/output/normalize``.
            max_distance_m (float | None): Distance limit for the CIPS match.
                Defaults to ``MAX_DISTANCE_M``.

        Returns:
            Self: ``self``, to allow method chaining. ``self.anomalies`` gets
                ``_row`` (index row position, ``NaN`` when unmatched),
                ``_method`` and ``_distance`` (meters to the linked row's
                track). ``self.groups`` has one row per (index row, method)
                and per unmatched name group: ``year``, ``area``,
                ``segment`` (the ACVG/DCVG names, joined), ``diameter``,
                ``n_anomalies``, ``method`` (``name`` / ``cips`` / ``none``),
                ``index_row`` (CSV row position), ``index_segment``,
                ``cips_file``, ``distance_m`` (median over its anomalies) and
                ``filename``.

        Raises:
            FileNotFoundError: If ``index_csv`` does not exist.
            KeyError: If it misses one of the columns above.
        """
        if self.anomalies is None:
            self.load()
        anomalies = _require_loaded(self.anomalies).copy()
        max_distance = self.MAX_DISTANCE_M if max_distance_m is None else max_distance_m
        normalize_dir = normalize_dir or os.path.join(resolve_output_dir(), "normalize")

        index = _read_index(index_csv)
        tracks = _cips_tracks(index, normalize_dir)

        # load() concatenates with ignore_index, so labels are positions.
        n = len(anomalies)
        row_of = np.full(n, np.nan)
        method_of = np.full(n, "none", dtype=object)
        distance_of = np.full(n, np.nan)

        # 1. name, per group: all anomalies of a matching group go to that row.
        name_keys = ["Year", "Area", "Segmen", "Dia (inch)"]
        for _, part in anomalies.groupby(name_keys, dropna=False, sort=False):
            first = part.iloc[0]
            year = int(first["Year"])
            position = _match_name(index, year, first["Segmen"], first["Dia (inch)"])
            if position is None:
                continue
            labels = part.index.to_numpy()
            row_of[labels] = position
            method_of[labels] = "name"
            track = tracks.get(year, {}).get(position)
            if track is not None:
                distance_of[labels] = _distances_to_track(track[1], part)

        # 2. cips, per anomaly: the nearest same-year track within the limit.
        rest = anomalies[np.isnan(row_of)]
        for year in rest["Year"].unique():
            part = rest[rest["Year"] == year]
            positions, distances = _nearest_tracks(tracks, int(year), part)
            close = distances <= max_distance
            labels = part.index.to_numpy()[close]
            row_of[labels] = positions[close]
            method_of[labels] = "cips"
            distance_of[labels] = distances[close]

        anomalies["_row"] = row_of
        anomalies["_method"] = method_of
        anomalies["_distance"] = distance_of
        anomalies["_group"] = [
            f"{method} row {int(row)}"
            if method != "none"
            else f"none {year} {area} {segmen} {dia}"
            for method, row, year, area, segmen, dia in zip(
                method_of,
                row_of,
                anomalies["Year"],
                anomalies["Area"],
                anomalies["Segmen"],
                anomalies["Dia (inch)"],
                strict=True,
            )
        ]

        rows: list[dict] = []
        for group_key, part in anomalies.groupby("_group", sort=False):
            first = part.iloc[0]
            year = int(first["Year"])
            method = first["_method"]
            diameters = part["Dia (inch)"].dropna().unique()

            if method != "none":
                position = int(first["_row"])
                matched = index.iloc[position]
                filename = _filename(
                    matched["Segment"], matched["Diameter"], matched["Area"]
                )
                index_segment = matched["Segment"]
                cips_file = tracks.get(year, {}).get(position, (None, None))[0]
            else:
                position = None
                filename = _filename(
                    first["Segmen"], first["Dia (inch)"], first["Area"]
                )
                index_segment = cips_file = None

            distances = part["_distance"].dropna()
            rows.append(
                {
                    "group": group_key,
                    "year": year,
                    "area": ", ".join(dict.fromkeys(part["Area"])),
                    "segment": ", ".join(dict.fromkeys(part["Segmen"])),
                    "diameter": diameters[0]
                    if len(diameters) == 1
                    else ", ".join(f"{d:g}" for d in diameters) or None,
                    "n_anomalies": len(part),
                    "method": method,
                    "index_row": position,
                    "index_segment": index_segment,
                    "cips_file": cips_file,
                    "distance_m": round(float(distances.median()), 1)
                    if len(distances)
                    else None,
                    "filename": filename,
                }
            )

        self.anomalies = anomalies
        self.groups = pd.DataFrame(rows)
        self.index_csv = index_csv
        self._index, self._tracks, self._max_distance = index, tracks, max_distance
        self._normalize_dir = normalize_dir

        if self.verbose:
            counts = anomalies["_method"].value_counts().to_dict()
            logger.info(
                f"Matched {len(anomalies)} ACVG/DCVG anomalies: {counts}; "
                f"{int(self.groups['index_row'].notna().sum())} index rows linked"
            )

        return self

    def unlinked_segments(self) -> pd.DataFrame:
        """Return the index rows that got no ACVG/DCVG file, with the reason.

        For every row of the index CSV that ``match`` linked to no group:

        - ``no CIPS file in the index`` / ``CIPS not normalized``: there is no
          track to compare the anomalies with (only a name match was
          possible).
        - ``no ACVG/DCVG anomaly in <year>``: that year has no anomalies with
          coordinates.
        - ``no anomaly within <limit> m``: the nearest anomaly of that year is
          further than the distance limit from the row's CIPS track,
          usually because no ACVG/DCVG survey was done on that segment.
        - ``anomalies nearby, linked to another row``: the nearest anomaly
          lies within the limit but went to another row, either by its name
          or because another row's track passes even closer (e.g. two index
          rows on the same pipe). ``anomalies nearby, not linked`` should not
          occur with per-anomaly matching; it is kept as a safety net.

        Returns:
            pd.DataFrame: One row per unlinked index row: ``year``, ``area``,
                ``segment``, ``diameter``, ``cips``, ``reason``,
                ``nearest_anomaly_m`` (meters from the row's CIPS track to the
                nearest same-year anomaly), ``nearest_anomaly_segmen`` (its
                ACVG/DCVG name) and ``nearest_linked_to`` (the index segment
                it was linked to; empty when unmatched).

        Raises:
            RuntimeError: If ``match`` has not run yet.

        Example:
            >>> acvg.load().match(csv).unlinked_segments()["reason"].value_counts()
        """
        if self.groups is None or self._index is None or self.anomalies is None:
            raise RuntimeError("Run match() before unlinked_segments()")

        index, tracks, limit = self._index, self._tracks, self._max_distance
        linked = set(self.anomalies["_row"].dropna().astype(int))
        anomalies = self.anomalies.dropna(subset=["Latitude", "Longitude"])

        rows: list[dict] = []
        for position, (_, row) in enumerate(index.iterrows()):
            if position in linked:
                continue
            year = int(row["Year"])
            entry = {
                "year": year,
                "area": row["Area"],
                "segment": row["Segment"],
                "diameter": row["Diameter"],
                "cips": row["CIPS"],
                "reason": None,
                "nearest_anomaly_m": None,
                "nearest_anomaly_segmen": None,
                "nearest_linked_to": None,
            }
            same_year = anomalies[anomalies["Year"] == year]
            if pd.isna(row["CIPS"]):
                entry["reason"] = "no CIPS file in the index"
            elif position not in tracks.get(year, {}):
                entry["reason"] = "CIPS not normalized"
            elif same_year.empty:
                entry["reason"] = f"no ACVG/DCVG anomaly in {year}"
            else:
                track = tracks[year][position][1]
                distances = np.asarray(
                    calculate_distance(
                        same_year[["Latitude"]].to_numpy(),
                        same_year[["Longitude"]].to_numpy(),
                        track[None, :, 0],
                        track[None, :, 1],
                    )
                ).min(axis=1)
                nearest = same_year.iloc[int(distances.argmin())]
                target = (
                    None
                    if pd.isna(nearest["_row"])
                    else index.iloc[int(nearest["_row"])]["Segment"]
                )
                entry.update(
                    {
                        "nearest_anomaly_m": round(float(distances.min()), 1),
                        "nearest_anomaly_segmen": nearest["Segmen"],
                        "nearest_linked_to": target,
                    }
                )
                if distances.min() > limit:
                    entry["reason"] = f"no anomaly within {limit:g} m"
                elif target is None:
                    entry["reason"] = "anomalies nearby, not linked"
                else:
                    entry["reason"] = "anomalies nearby, linked to another row"
            rows.append(entry)

        return pd.DataFrame(
            rows,
            columns=[
                "year",
                "area",
                "segment",
                "diameter",
                "cips",
                "reason",
                "nearest_anomaly_m",
                "nearest_anomaly_segmen",
                "nearest_linked_to",
            ],
        )

    def rebuild(
        self,
        output_dir: str | None = None,
        destination_dir: str = "raw_data",
    ) -> Self:
        """Write one Excel per file name in ``self.groups``.

        Every anomaly of the groups sharing a file name is written to
        ``<output_dir>/<destination_dir>/<year>/ACVG_DCVG/<filename>`` with
        ``Year``, ``Area`` and the sheet's columns (parsed coordinates and
        numbers). ``REQUIRED_COLUMNS`` are always kept; other columns that
        are empty in that file (extra columns of another workbook) and the
        internal ``_`` match columns are left out. Existing files are
        overwritten.

        Args:
            output_dir (str | None): Output root. Defaults to ``<cwd>/output``.
            destination_dir (str): Sub-folder of ``output_dir``. Defaults to
                ``"raw_data"``, next to ``FileIndex.rebuild``'s CIPS/PCM copies.

        Returns:
            Self: ``self``, to allow method chaining. The written paths are in
                ``self.output_files``.

        Raises:
            RuntimeError: If ``match`` has not run yet.
        """
        if self.groups is None or self.anomalies is None:
            raise RuntimeError("Run match() before rebuild()")

        root = os.path.join(resolve_output_dir(output_dir), destination_dir)
        filename_of = dict(
            zip(self.groups["group"], self.groups["filename"], strict=True)
        )
        anomalies = self.anomalies.assign(
            _file=self.anomalies["_group"].map(filename_of)
        )

        cips_of = {
            filename: cips
            for filename, cips in zip(
                self.groups["filename"], self.groups["cips_file"], strict=True
            )
            if isinstance(cips, str)
        }
        keep = {"Year", "Area", *self.REQUIRED_COLUMNS}

        self.output_files = []
        self._file_info = {}
        for (year, filename), part in anomalies.groupby(["Year", "_file"], sort=True):
            folder = os.path.join(root, str(year), self.DESTINATION_SUBDIR)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, str(filename))
            drop = [
                c
                for c in part.columns
                if str(c).startswith("_") or (c not in keep and part[c].isna().all())
            ]
            part.drop(columns=drop).to_excel(path, index=False)
            self.output_files.append(path)
            year_of_file = int(part["Year"].iloc[0])
            self._file_info[path] = (year_of_file, cips_of.get(str(filename)))
        self._output_dir = resolve_output_dir(output_dir)

        if self.verbose:
            logger.info(f"Wrote {len(self.output_files)} ACVG/DCVG files under {root}")

        return self

    def clean(self) -> Self:
        """Clean every file ``rebuild`` wrote and save it.

        Runs ``AcvgDcvgFile(path, year).check().clean().save()`` per file:
        rows with an empty or ``0`` coordinate and duplicate points are
        dropped, and the result goes to
        ``<output_dir>/cleaned/<year>/ACVG_DCVG/<filename>`` (``output_dir``
        as passed to ``rebuild``), next to the cleaned CIPS and PCM files. A
        file that fails (e.g. no anomaly with coordinates) gets a ``reason``
        and is left out of ``normalize``; the others go on.

        Returns:
            Self: ``self``, to allow method chaining. ``self.file_report`` has
                one row per file: ``year``, ``filename``, ``n_anomalies``,
                ``n_duplicates``, ``n_cleaned``, ``cleaned_path``,
                ``cips_file``, ``normalized_file``, ``count``,
                ``n_on_cips`` and ``reason`` (the last four are filled by
                ``normalize``).

        Raises:
            RuntimeError: If ``rebuild`` has not run yet.

        Example:
            >>> acvg.load().match(csv).rebuild().clean().normalize()
        """
        if self._output_dir is None:
            raise RuntimeError("Run rebuild() before clean()")

        self._files = {}
        rows: list[dict] = []
        for path, (year, cips_file) in self._file_info.items():
            entry: dict = dict.fromkeys(self.FILE_REPORT_COLUMNS)
            entry.update(
                {
                    "year": year,
                    "filename": os.path.basename(path),
                    "cips_file": cips_file,
                }
            )
            try:
                data = AcvgDcvgFile(
                    path, year, output_dir=self._output_dir, verbose=self.verbose
                )
                entry["n_anomalies"] = len(data.df)
                data.check().clean().save()
                entry.update(
                    {
                        "n_duplicates": data.report["n_duplicates"],
                        "n_cleaned": len(data.df),
                        "cleaned_path": data.cleaned_path,
                    }
                )
                self._files[path] = data
            except (OSError, ValueError) as e:
                entry["reason"] = f"clean failed: {e}"
            rows.append(entry)

        self.file_report = pd.DataFrame(rows, columns=self.FILE_REPORT_COLUMNS)

        if self.verbose:
            logger.info(f"Cleaned {len(self._files)}/{len(rows)} ACVG/DCVG files")

        return self

    def normalize(self, normalize_dir: str | None = None) -> Self:
        """Normalize every cleaned file against its segment's CIPS line.

        Runs ``AcvgDcvgFile.normalize`` per file ``clean`` kept, with the
        normalized CIPS JSON of the index row the file belongs to
        (``<normalize_dir>/cips/json/<cips_file>``, ``normalize_dir`` as
        passed to ``match``). Files of unmatched groups, or of rows without a
        normalized CIPS, are normalized too, with an empty ``real_distance``
        and ``condition``. Run it after the CIPS/PCM sync (``main.py`` does),
        so the distances follow the synced CIPS direction.

        Args:
            normalize_dir (str | None): Passed to every
                ``AcvgDcvgFile.normalize``, where it overrides the file's
                ``normalize_dir`` (default
                ``<output_dir>/normalize/acvg_dcvg``): where the normalized
                ACVG/DCVG files are written. The CIPS JSON is still read from
                the ``normalize_dir`` given to ``match``. ``None`` keeps the
                default.

        Returns:
            Self: ``self``, to allow method chaining. ``self.file_report``
                gets ``normalized_file`` (JSON basename), ``count``
                (``AcvgDcvgFile.count``), ``n_on_cips`` (anomalies placed on
                the CIPS line) and, on failure, ``reason``.

        Raises:
            RuntimeError: If ``clean`` has not run yet.
        """
        if self.file_report is None:
            raise RuntimeError("Run clean() before normalize()")

        report = self.file_report
        for position, (path, (_, cips_file)) in enumerate(self._file_info.items()):
            data = self._files.get(path)
            if data is None:
                continue
            cips_json = (
                os.path.join(self._normalize_dir, "cips", "json", cips_file)
                if cips_file
                else None
            )
            try:
                data.normalize(cips_json, normalize_dir=normalize_dir)
                report.loc[position, "normalized_file"] = os.path.basename(
                    data.normalize_json_filepath
                )
                report.loc[position, "count"] = data.count
                report.loc[position, "n_on_cips"] = data.report["n_on_cips"]
            except (OSError, ValueError, KeyError) as e:
                report.loc[position, "reason"] = f"normalize failed: {e}"

        if self.verbose:
            logger.info(
                f"Normalized {int(report['normalized_file'].notna().sum())}"
                f"/{len(report)} ACVG/DCVG files"
            )

        return self

    def normalized_files(self) -> dict[int, str]:
        """Return the normalized JSON of every linked index row.

        For ``FileIndex.assign_acvg_dcvg``: files of unmatched groups and
        files that failed to clean or normalize are left out.

        Returns:
            dict[int, str]: Row position in the index CSV given to ``match``
                -> normalized JSON filename (``<year>-<slug>.json``).

        Raises:
            RuntimeError: If ``normalize`` has not run yet.

        Example:
            >>> acvg.load().match(csv).rebuild().clean().normalize()
            >>> acvg.normalized_files()
            {3: '2024-acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.json'}
        """
        return {
            row: str(value) for row, value in self._per_row("normalized_file").items()
        }

    def anomaly_counts(self) -> dict[int, int]:
        """Return the number of normalized anomalies of every linked index row.

        For ``FileIndex.assign_acvg_dcvg`` (``total_anomaly``): the
        ``AcvgDcvgFile.count`` of each file ``normalized_files`` returns.

        Returns:
            dict[int, int]: Row position in the index CSV given to ``match``
                -> number of anomalies in its normalized file.

        Raises:
            RuntimeError: If ``normalize`` has not run yet.

        Example:
            >>> acvg.load().match(csv).rebuild().clean().normalize()
            >>> acvg.anomaly_counts()
            {3: 2}
        """
        return {row: int(value) for row, value in self._per_row("count").items()}

    def _per_row(self, column: str) -> dict:
        """Return ``file_report[column]`` per linked index row (normalized only)."""
        if self.file_report is None or self.groups is None:
            raise RuntimeError("Run normalize() first")

        linked = self.groups.dropna(subset=["index_row"])
        row_of = {
            (int(year), filename): int(row)
            for year, filename, row in zip(
                linked["year"], linked["filename"], linked["index_row"], strict=True
            )
        }
        report = self.file_report
        return {
            row_of[(int(year), filename)]: value
            for year, filename, normalized, value in zip(
                report["year"],
                report["filename"],
                report["normalized_file"],
                report[column],
                strict=True,
            )
            if isinstance(normalized, str) and (int(year), filename) in row_of
        }

    def assign_index(self, index_csv: str | None = None) -> pd.DataFrame:
        """Add the ``ACVG_DCVG`` column to the file-index CSV and save it.

        Each index row matched by ``match`` gets its file name; other rows
        stay empty. The CSV is written back in place.

        Args:
            index_csv (str | None): CSV to update. Defaults to the one passed
                to ``match``.

        Returns:
            pd.DataFrame: ``self.groups``, the per-group match report.

        Raises:
            RuntimeError: If ``match`` has not run yet.
        """
        if self.groups is None or self.index_csv is None:
            raise RuntimeError("Run match() before assign_index()")

        path = index_csv or self.index_csv
        index = pd.read_csv(path)
        matched = self.groups.dropna(subset=["index_row"])
        filenames = dict(
            zip(matched["index_row"].astype(int), matched["filename"], strict=True)
        )
        index[self.INDEX_COLUMN] = [filenames.get(i) for i in range(len(index))]
        index.to_csv(path, index=False)

        if self.verbose:
            logger.info(
                f"Linked {len(filenames)} index rows to ACVG/DCVG files in {path}"
            )

        return self.groups


class AcvgDcvgFile(BaseData):
    """One extracted ACVG/DCVG segment file (``AcvgDcvg.rebuild`` output).

    Inherits the fluent ``check`` / ``clean`` / ``save`` pipeline from
    ``BaseData``, like ``CIPS`` and ``PCM``, so the outputs land in the same
    layout: ``<output_dir>/cleaned/<year>/ACVG_DCVG/<filename>`` and
    ``<output_dir>/normalize/acvg_dcvg/<excel|json>/<year>-<slug>``.
    ``clean`` drops all-empty rows, rows with an empty or ``0`` coordinate and
    duplicate points (first kept). ``normalize`` places every anomaly on its
    segment's normalized CIPS line.

    Example:
        >>> data = AcvgDcvgFile("output/raw_data/2024/ACVG_DCVG/x.xlsx", year=2024)
        >>> data.check().clean().save().normalize("output/normalize/cips/json/2024-y.json")
    """

    KIND = "acvg_dcvg"

    REQUIRED_COLUMNS: list[str] = AcvgDcvg.REQUIRED_COLUMNS

    NUMERIC_COLUMNS: list[str] = ["Latitude", "Longitude", *AcvgDcvg.NUMERIC_COLUMNS]

    CLEAN_REQUIRED_COLUMNS: list[str] = ["Latitude", "Longitude"]

    UNIQUE_COLUMNS: tuple[str, str] = ("Latitude", "Longitude")

    # normalize() writes these columns, in this order, to the JSON under
    # these keys (see BaseData.json_frame).
    JSON_COLUMNS: dict[str, str] = {
        "Latitude": "latitude",
        "Longitude": "longitude",
        "Real Distance": "real_distance",
        "Lokasi Anomali": "anomaly_location",
        "Kondisi Permukaan": "surface_condition",
        "Dia (inch)": "diameter",
        "On Potential (volt)": "on_potential",
        "Off Potential (volt)": "off_potential",
        "IR Drop (%)": "ir_drop",
        "Hasil ACVG (dB)": "result_acvg",
        "Kedalaman Pipa (m)": "pipe_depth",
        "%drop PCM": "drop_pcm",
        "Tgl DCVG": "survey_dcvg",
        "Tgl ACVG": "survey_acvg",
        "Condition": "closest_cips_condition",
    }

    def __init__(
        self,
        filepath: str,
        year: int,
        output_dir: str | None = None,
        verbose: bool = False,
    ):
        """Load an extracted ACVG/DCVG file and coerce numeric columns.

        Args:
            filepath (str): Path to the file written by ``AcvgDcvg.rebuild``.
            year (int): Survey year for this file.
            output_dir (str | None): Destination root for downstream artifacts.
                Defaults to ``<cwd>/output`` via ``resolve_output_dir``.
            verbose (bool): If True, methods may emit progress messages.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``filepath`` does not exist.
        """
        super().__init__(filepath, year, output_dir, verbose)
        self.cips_json: str | None = None
        # Number of anomalies in the normalized file, set by normalize().
        self.count: int = 0

    def normalize(
        self,
        cips_json: str | None = None,
        max_distance_m: float = AcvgDcvg.MAX_DISTANCE_M,
        normalize_dir: str | None = None,
    ) -> Self:
        """Place each anomaly on the CIPS line, then save Excel and JSON.

        Every anomaly takes the nearest reading of ``cips_json`` (the
        segment's normalized CIPS, after the CIPS/PCM sync, so the distances
        run in the same direction as the CIPS and PCM charts) and adds to
        ``self.df``:

        - ``Real Distance``: that reading's ``real_distance``, i.e. where the
          anomaly sits along the CIPS line, in meters.
        - ``Condition``: that reading's ``condition`` (``PROTECTED`` /
          ``OVER PROTECTED`` / ``UNPROTECTED``).
        - ``CIPS Offset (m)``: meters from the anomaly to that reading (Excel
          only).

        ``Real Distance`` and ``Condition`` stay empty without ``cips_json``
        or when the nearest reading is further than ``max_distance_m``. Rows
        are sorted by ``Real Distance`` (empty last). Missing
        ``REQUIRED_COLUMNS`` are added empty. ``self.count`` is set to the
        number of anomalies (rows of ``self.df``).

        Then writes two files, sets ``self.normalized`` and adds to
        ``self.report`` (see ``BaseData._report_normalize``): ``normalized``,
        ``n_normalized``, ``normalize_excel_filepath``,
        ``normalize_json_filepath``, ``count``, ``n_on_cips`` (anomalies with
        a ``Real Distance``) and ``cips_json``. The files:

        - ``normalize_excel_filepath``
          (``<output_dir>/normalize/acvg_dcvg/excel/<year>-<slug>.xlsx``):
          ``self.df`` with its original column names, without the index.
        - ``normalize_json_filepath``
          (``<output_dir>/normalize/acvg_dcvg/json/<year>-<slug>.json``): one
          record per anomaly with the ``JSON_COLUMNS`` keys, in order
          (``Condition`` is ``closest_cips_condition``; ``Segmen`` is left
          out, the file is one segment already). ``survey_dcvg`` /
          ``survey_acvg`` are always ``YYYY-MM-DD`` or ``null``: date cells
          are formatted, date text is parsed (``"20-May"`` takes the file's
          ``year``: ``"2024-05-20"``), and text that is not a date is
          ``null``. Other empty cells, including blank text, are ``null``.

        Args:
            cips_json (str | None): Normalized CIPS JSON of the segment
                (``latitude``, ``longitude``, ``real_distance``,
                ``condition``), or ``None`` when the segment has none.
            max_distance_m (float): Largest distance to the CIPS line for a
                ``Real Distance`` / ``Condition``. Defaults to
                ``AcvgDcvg.MAX_DISTANCE_M``.
            normalize_dir (str | None): Overrides ``self.normalize_dir``
                (default ``<output_dir>/normalize/acvg_dcvg``); the files go
                to its ``excel`` / ``json`` sub-folders and
                ``normalize_excel_dir``, ``normalize_json_dir`` and both file
                paths follow. ``None`` keeps the current one.

        Returns:
            Self: ``self``, to allow method chaining.

        Raises:
            RuntimeError: If ``clean`` has not completed yet.
            FileNotFoundError: If ``cips_json`` is given but does not exist.

        Example:
            >>> data = AcvgDcvgFile("x.xlsx", year=2024).clean()
            >>> data.normalize("output/normalize/cips/json/2024-y.json")
            >>> data.df[["Segmen", "Real Distance", "Condition"]]
        """
        if not self.cleaned:
            raise RuntimeError(f"Run clean() before normalize(): {self.filepath}")
        if cips_json is not None and not os.path.isfile(cips_json):
            raise FileNotFoundError(f"File not found: {cips_json}")
        self._set_normalize_dir(normalize_dir)

        df = self.df.copy()
        for column in self.REQUIRED_COLUMNS:
            if column not in df.columns:
                df[column] = np.nan

        distance = np.full(len(df), np.nan)
        condition = np.full(len(df), None, dtype=object)
        offset = np.full(len(df), np.nan)
        if cips_json is not None:
            with open(cips_json, encoding="utf-8") as file:
                readings = pd.DataFrame(json.load(file))
            if not readings.empty:
                readings = readings.dropna(subset=["latitude", "longitude"])
            if not readings.empty:
                # clean() leaves no empty coordinate, so argmin is defined
                matrix = np.asarray(
                    calculate_distance(
                        df[["Latitude"]].to_numpy(dtype=float),
                        df[["Longitude"]].to_numpy(dtype=float),
                        readings["latitude"].to_numpy(dtype=float)[None, :],
                        readings["longitude"].to_numpy(dtype=float)[None, :],
                    )
                )
                nearest = matrix.argmin(axis=1)
                offset = matrix[np.arange(len(df)), nearest]
                on_line = offset <= max_distance_m
                distance = np.where(
                    on_line,
                    readings["real_distance"].to_numpy(dtype=float)[nearest],
                    np.nan,
                )
                condition = readings["condition"].to_numpy(dtype=object)[nearest]
                condition[~on_line] = None

        df["Real Distance"] = distance
        df["Condition"] = condition
        df["CIPS Offset (m)"] = np.round(offset, 1)
        df = df.sort_values("Real Distance", kind="stable", na_position="last")

        # Save to excel with original column name
        os.makedirs(self.normalize_excel_dir, exist_ok=True)
        df.to_excel(self.normalize_excel_filepath, index=False)

        self.df = df
        self.cips_json = cips_json
        self.count = len(df)

        # Save to JSON (JSON_COLUMNS); dates as text, blank text becomes null.
        frame = df.copy()
        for column in AcvgDcvg.DATE_COLUMNS:
            frame[column] = (
                frame[column]
                .map(lambda value: _iso_date(value, self.year))
                .astype(object)
            )
        frame = self.json_frame(frame)
        os.makedirs(self.normalize_json_dir, exist_ok=True)
        frame.to_json(self.normalize_json_filepath, orient="records")

        self.normalized = True
        self._report_normalize(
            count=self.count,
            n_on_cips=int(df["Real Distance"].notna().sum()),
            cips_json=cips_json,
        )

        return self


def _require_loaded(df: pd.DataFrame | None) -> pd.DataFrame:
    """Return ``df``, which ``load`` has set (narrows ``None`` for type checks)."""
    if df is None:
        raise RuntimeError("Run load() first")
    return df


def _to_number(values: pd.Series) -> pd.Series:
    """Coerce to numbers; ``"61.80%"`` -> ``61.8``, text -> ``NaN``."""
    text = values.astype("string").str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(text, errors="coerce")


def _dated_elsewhere(row: pd.Series, year: int) -> bool:
    """True when a real date in ``DATE_COLUMNS`` falls in another year.

    Only date cells count; text such as ``"20-May"`` (no year) is ignored.
    """
    for column in AcvgDcvg.DATE_COLUMNS:
        value = row.get(column)
        # pd.Timestamp is a datetime, and so is NaT (an empty cell in a date
        # column): skip it, its year is NaN
        if isinstance(value, datetime) and not pd.isna(value) and value.year != year:
            return True
    return False


# Date text seen in the workbooks ("20-May", 2024) plus full dates; formats
# without a year take the survey year.
DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
)
DATE_FORMATS_NO_YEAR: tuple[str, ...] = ("%d-%b", "%d %b", "%d-%B", "%d %B")


def _iso_date(value, year: int) -> str | None:
    """Return a date cell as ``YYYY-MM-DD``, or ``None``.

    Date cells are formatted; text is parsed with ``DATE_FORMATS``, or with
    ``DATE_FORMATS_NO_YEAR`` and ``year`` (``"20-May"`` -> ``"<year>-05-20"``).
    Empty cells and text that is not a date give ``None``.
    """
    if not isinstance(value, (datetime, str)) or pd.isna(value):
        return None  # empty cell, NaN or NaT (which is a datetime)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    for fmt in DATE_FORMATS_NO_YEAR:
        try:
            # parse with the year, so 29-Feb works in leap years
            parsed = datetime.strptime(f"{text} {year}", f"{fmt} %Y")
        except ValueError:
            continue
        return parsed.strftime("%Y-%m-%d")
    return None


def _read_index(index_csv: str) -> pd.DataFrame:
    """Read the file-index CSV and check the columns ``match`` uses."""
    if not os.path.isfile(index_csv):
        raise FileNotFoundError(f"File not found: {index_csv}")
    index = pd.read_csv(index_csv).reset_index(drop=True)
    needed = ["Year", "Area", "Segment", "Sub Segment", "Diameter", "CIPS"]
    missing = [c for c in needed if c not in index.columns]
    if missing:
        raise KeyError(f"{index_csv}: columns not found: {missing}")
    index["Segment"] = index["Segment"].where(
        index["Segment"].notna(), index["Sub Segment"]
    )
    return index


def _cips_tracks(
    index: pd.DataFrame, normalize_dir: str
) -> dict[int, dict[int, tuple[str, np.ndarray]]]:
    """Return ``{year: {row position: (json name, [[lat, lon], ...])}}``."""
    tracks: dict[int, dict[int, tuple[str, np.ndarray]]] = {}
    for position, (year, cips) in enumerate(
        zip(index["Year"], index["CIPS"], strict=True)
    ):
        if pd.isna(cips):
            continue
        name = f"{int(year)}-{slugify(Path(str(cips)).stem)}.json"
        path = os.path.join(normalize_dir, "cips", "json", name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as file:
            records = json.load(file)
        points = np.array(
            [[r["latitude"], r["longitude"]] for r in records if "latitude" in r],
            dtype=float,
        )
        if len(points):
            tracks.setdefault(int(year), {})[position] = (name, points)
    return tracks


def _distances_to_track(track: np.ndarray, part: pd.DataFrame) -> np.ndarray:
    """Return each anomaly's distance (meters) to its nearest track reading.

    Anomalies without coordinates get ``inf``.
    """
    lat = part[["Latitude"]].to_numpy(dtype=float)
    lon = part[["Longitude"]].to_numpy(dtype=float)
    distances = np.asarray(
        calculate_distance(lat, lon, track[None, :, 0], track[None, :, 1])
    ).min(axis=1)
    return np.where(np.isnan(distances), np.inf, distances)


def _nearest_tracks(
    tracks: dict[int, dict[int, tuple[str, np.ndarray]]],
    year: int,
    part: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """Return, per anomaly, the nearest same-year track and its distance.

    Returns:
        tuple[np.ndarray, np.ndarray]: Row position of the nearest track
            (``NaN`` when the year has no track) and the distance in meters
            (``inf`` without a track or coordinates), one per anomaly.
    """
    year_tracks = tracks.get(year, {})
    if not year_tracks:
        return np.full(len(part), np.nan), np.full(len(part), np.inf)

    positions = np.array(list(year_tracks), dtype=float)
    matrix = np.vstack(
        [_distances_to_track(track, part) for _, track in year_tracks.values()]
    )
    nearest = matrix.argmin(axis=0)
    return positions[nearest], matrix[nearest, np.arange(len(part))]


def _match_name(
    index: pd.DataFrame, year: int, segment: str, diameter: float
) -> int | None:
    """Return the index row position whose segment name matches, or ``None``."""
    slug = slugify(str(segment))
    same_year = index[index["Year"] == year]
    names = same_year["Segment"].map(lambda s: slugify(str(s)))
    subs = same_year["Sub Segment"].map(
        lambda s: slugify(str(s)) if pd.notna(s) else ""
    )
    candidates = same_year[(names == slug) | (subs == slug)]
    if candidates.empty:
        return None
    if len(candidates) > 1 and pd.notna(diameter):
        same_diameter = candidates[candidates["Diameter"] == diameter]
        if not same_diameter.empty:
            candidates = same_diameter
    # _read_index gives a 0..n-1 index, so the label is the row position.
    return int(candidates.index[0])


def _filename(segment, diameter, area) -> str:
    """Return ``acvg-dcvg-<segment>-<diameter>-<area>.xlsx``, slugified."""
    if pd.notna(diameter) and float(diameter).is_integer():
        diameter = int(diameter)
    parts = [str(segment), "" if pd.isna(diameter) else str(diameter), str(area)]
    return f"{slugify('acvg-dcvg-' + '-'.join(p for p in parts if p))}.xlsx"
