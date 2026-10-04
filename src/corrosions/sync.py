"""Put the CIPS and PCM surveys of each segment in the same direction.

CIPS and PCM surveys of one pipeline segment are often walked in opposite
directions (e.g. PCM east to west, CIPS west to east). ``SyncData`` reads the
index written by ``FileIndex.to_json`` and, for every segment, reorders the
normalized files so both surveys start at the same end:

1. CIPS starts by the main direction of its line: an east-west line starts
   at its west end, a north-south line at its north end (``START``).
2. PCM starts at the end closer to the CIPS start, so the pair always agrees.

Each end of a survey is the average of its first / last ``END_READINGS``
readings, so a single bad GPS fix at an end cannot flip the decision.

The decision is made on the normalized JSON. A reversed survey is
recalculated once, on its normalized Excel (full-precision coordinates,
``normalize()``'s column names): ``Distance`` and ``Real Distance`` and, for
PCM, ``Current Loss Rate`` and ``Condition``, since both depend on the
previous reading. The JSON is then rebuilt from that Excel with
``json_frame`` (the same columns and keys ``normalize()`` writes), so both
files carry the same values. Files are written to temporary files first and
then moved over the originals, so a failed write leaves them intact. The
rule gives the same order every time, so running it again changes nothing.

Example:
    >>> from corrosions.sync import SyncData
    >>> report = SyncData("output/file_index.json", n_jobs=-1).sync()
    >>> report[report["cips_reversed"] | report["pcm_reversed"]]
"""

import os
import json
import tempfile
from typing import cast
from pathlib import Path

import pandas as pd
from joblib import Parallel, delayed

from corrosions.logging import logger
from corrosions.data.pcm import PCM
from corrosions.data.cips import CIPS
from corrosions.utils.geo_utils import calculate_distance
from corrosions.utils.path_utils import resolve_output_dir


Point = tuple[float, float]


class SyncData:
    """Sync the survey direction of the CIPS and PCM files in the index.

    Attributes:
        REQUIRED_KEYS (tuple[str, ...]): Keys every record of the index JSON
            must have.
        COORDINATES (dict[str, tuple[str, str]]): Latitude/longitude keys of
            the normalized JSON, per survey kind (the same for CIPS and PCM).
        EXCEL_COORDINATES (dict[str, tuple[str, str]]): Latitude/longitude
            columns of the normalized Excel, per survey kind. PCM uses
            ``PCM.UNIQUE_COLUMNS`` (``Int GPS Latitude`` / ``Longitude``).
        SURVEYS (dict[str, type[CIPS] | type[PCM]]): Survey class per kind;
            its ``json_frame`` rebuilds the JSON from the reversed Excel.
        EXCEL_REQUIRED_COLUMNS (dict[str, list[str]]): Columns a normalized
            Excel must have before it is reversed, per survey kind: the
            survey's ``JSON_COLUMNS`` (to rebuild the JSON) and, for PCM,
            ``PCM.REQUIRED_COLUMNS`` (``normalize()`` keeps the source
            columns under their original names; ``dbma`` is in its
            ``JSON_COLUMNS``).
        EXCEL_COLUMNS (dict[str, str]): Excel names of the order-dependent
            values: ``distance``, ``real_distance``, ``dbma``, ``rate`` and
            ``condition``.
        END_READINGS (int): Readings averaged at each end of a survey.
        START (dict[str, str]): Where a CIPS survey starts, by the main
            direction of its line: ``"east-west"`` -> ``"west"`` or
            ``"east"``; ``"north-south"`` -> ``"north"`` or ``"south"``.
        json_file_index (str): Path to the index JSON (``file_index.json``).
        data (list[dict]): Records of the index JSON.
        normalize_dir (str): Root of the normalized files,
            ``<normalize_dir>/<cips|pcm>/<json|excel>/<file>``.
        n_jobs (int): Parallel workers for ``sync`` (joblib ``loky``).
        report (pd.DataFrame | None): Result of the last ``sync`` call.
        verbose (bool): If True, log each reversed file and a summary.
    """

    REQUIRED_KEYS = (
        "year",
        "area",
        "area_code",
        "segment",
        "segment_code",
        "pipe_diameter",
        "length",
        "cips_protection",
        "normalized_cips_file",
        "normalized_pcm_file",
    )

    COORDINATES: dict[str, tuple[str, str]] = {
        "cips": ("latitude", "longitude"),
        "pcm": ("latitude", "longitude"),
    }

    EXCEL_COORDINATES: dict[str, tuple[str, str]] = {
        "cips": ("Latitude", "Longitude"),
        "pcm": PCM.UNIQUE_COLUMNS,
    }

    SURVEYS: dict[str, type[CIPS] | type[PCM]] = {"cips": CIPS, "pcm": PCM}

    EXCEL_REQUIRED_COLUMNS: dict[str, list[str]] = {
        "cips": list(CIPS.JSON_COLUMNS),
        # dict.fromkeys: both lists name the coordinates, keep them once
        "pcm": list(dict.fromkeys([*PCM.REQUIRED_COLUMNS, *PCM.JSON_COLUMNS])),
    }

    EXCEL_COLUMNS: dict[str, str] = {
        "distance": "Distance",
        "real_distance": "Real Distance",
        "dbma": "dbma",
        "rate": "Current Loss Rate",
        "condition": "Condition",
    }

    END_READINGS: int = 5

    START: dict[str, str] = {"east-west": "west", "north-south": "north"}

    REPORT_COLUMNS: list[str] = [
        "year",
        "area",
        "segment_code",
        "start_gap_m",
        "cips_axis",
        "cips_reversed",
        "pcm_reversed",
        "reason",
        "normalized_cips_file",
        "normalized_pcm_file",
        "cips_json_path",
        "pcm_json_path",
        "cips_excel_path",
        "pcm_excel_path",
    ]

    def __init__(
        self,
        json_file_index: str,
        normalize_dir: str | None = None,
        n_jobs: int = 1,
        verbose: bool = False,
    ) -> None:
        """Load the index JSON written by ``FileIndex.to_json``.

        Args:
            json_file_index (str): Path to ``file_index.json``.
            normalize_dir (str | None): Root of the normalized files. Defaults
                to ``<cwd>/output/normalize``, where ``CIPS.normalize`` and
                ``PCM.normalize`` write them.
            n_jobs (int): Parallel workers for ``sync`` via joblib's ``loky``
                backend. ``1`` runs sequentially, ``-1`` uses all cores.
                Defaults to ``1``.
            verbose (bool): If True, log each reversed file and a summary.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``json_file_index`` does not exist.
            KeyError: If a record misses one of ``REQUIRED_KEYS``.

        Example:
            >>> sync = SyncData("output/file_index.json", n_jobs=-1)
        """
        if not os.path.exists(json_file_index):
            raise FileNotFoundError(
                f"File not found: {json_file_index}. Please check the file path. "
                f"Or run FileIndex(...).to_json(...) first."
            )

        with open(json_file_index, encoding="utf-8") as file:
            data = json.load(file)

        self.data = data
        self.json_file_index = json_file_index
        self.normalize_dir = normalize_dir or os.path.join(
            resolve_output_dir(), "normalize"
        )
        self.n_jobs = n_jobs
        self.report: pd.DataFrame | None = None
        self.verbose = verbose
        self.validate()

    def validate(self) -> None:
        """Ensure every record of the index has all ``REQUIRED_KEYS``.

        Raises:
            KeyError: Naming the first record (by position and
                ``segment_code``) that misses keys, and the missing keys.

        Example:
            >>> sync.validate()
        """
        for position, record in enumerate(self.data):
            missing = [key for key in self.REQUIRED_KEYS if key not in record]
            if missing:
                raise KeyError(
                    f"{self.json_file_index}: record {position} "
                    f"({record.get('segment_code')!r}) misses keys {missing}"
                )

    def json_path(self, kind: str, filename: str) -> str:
        """Return the path of a normalized JSON file.

        Args:
            kind (str): ``"cips"`` or ``"pcm"``.
            filename (str): Filename from the index
                (``normalized_cips_file`` / ``normalized_pcm_file``).

        Returns:
            str: ``<normalize_dir>/<kind>/json/<filename>``.
        """
        return os.path.join(self.normalize_dir, kind, "json", filename)

    def excel_path(self, kind: str, filename: str) -> str:
        """Return the path of the normalized Excel next to a JSON file.

        ``normalize()`` gives both files the same ``<year>-<slug>`` name.

        Args:
            kind (str): ``"cips"`` or ``"pcm"``.
            filename (str): JSON filename from the index.

        Returns:
            str: ``<normalize_dir>/<kind>/excel/<year>-<slug>.xlsx``.
        """
        return os.path.join(
            self.normalize_dir, kind, "excel", f"{Path(filename).stem}.xlsx"
        )

    def sync(self) -> pd.DataFrame:
        """Reorder every segment's CIPS and PCM files to start at the same end.

        For each record of the index (in parallel with ``n_jobs``):

        1. The ends of each survey are the averages of its first and last
           ``END_READINGS`` readings (fewer for short surveys).
        2. CIPS: its line is ``"east-west"`` when its ends are further apart
           east-west than north-south, else ``"north-south"``. It is reversed
           unless it already starts at ``START[axis]`` (west / north).
        3. PCM is reversed when its last end is closer than its first end to
           the (synced) CIPS start.
        4. A reversed survey is reversed and recalculated once, on its
           Excel: ``Distance`` and ``Real Distance``; PCM also gets
           ``Current Loss Rate`` and ``Condition`` (``PCM.current_loss``).
           The JSON is rebuilt from that Excel (``json_frame``), so both carry
           the same values. Surveys already in order are not rewritten, and
           their Excel is not read.

        Every file of a segment is read and reversed, then written to a
        temporary file next to it; only when all of them are written are
        they moved over the originals. A segment that fails at any point is
        left untouched and reported with a ``reason`` (missing, unreadable or
        empty JSON, missing keys, missing Excel or columns, failed write);
        the others still run.

        Returns:
            pd.DataFrame: One row per index record (``REPORT_COLUMNS``):
                ``year``, ``area``, ``segment_code``, ``start_gap_m`` (meters
                between the CIPS and PCM start ends after syncing),
                ``cips_axis`` (``"east-west"`` / ``"north-south"``),
                ``cips_reversed``, ``pcm_reversed`` (JSON and Excel),
                ``reason`` (``None`` when synced), the index filenames
                ``normalized_cips_file`` / ``normalized_pcm_file`` and the
                full paths ``cips_json_path``, ``pcm_json_path``,
                ``cips_excel_path``, ``pcm_excel_path`` to open each pair.
                Also stored on ``self.report``.

        Example:
            >>> report = SyncData("output/file_index.json").sync()
            >>> report["pcm_reversed"].sum()
        """
        rows = Parallel(n_jobs=self.n_jobs, backend="loky")(
            delayed(self._sync_record)(record) for record in self.data
        )
        self.report = pd.DataFrame(rows, columns=self.REPORT_COLUMNS)

        if self.verbose:
            report = self.report
            logger.info(
                f"Synced {int(report['reason'].isna().sum())}/{len(report)} "
                f"segments: reversed {int(report['cips_reversed'].sum())} CIPS "
                f"and {int(report['pcm_reversed'].sum())} PCM surveys (JSON and "
                f"Excel)"
            )

        return self.report

    @classmethod
    def ends(cls, df: pd.DataFrame, lat: str, lon: str) -> tuple[Point, Point]:
        """Return the (first, last) end of a survey as averaged points.

        Each end is the mean latitude/longitude of the first / last
        ``END_READINGS`` readings, or of half the survey when it is shorter,
        so the two ends never share a reading.

        Args:
            df (pd.DataFrame): Readings in survey order.
            lat (str): Latitude column.
            lon (str): Longitude column.

        Returns:
            tuple[Point, Point]: ``((lat, lon) of the first end, (lat, lon)
                of the last end)``.
        """
        n = max(1, min(cls.END_READINGS, len(df) // 2))
        head, tail = df.iloc[:n], df.iloc[-n:]
        return (
            (float(head[lat].mean()), float(head[lon].mean())),
            (float(tail[lat].mean()), float(tail[lon].mean())),
        )

    @classmethod
    def cips_direction(cls, first: Point, last: Point) -> tuple[str, bool]:
        """Return the main direction of a CIPS line and whether to reverse it.

        Args:
            first (Point): First end of the survey.
            last (Point): Last end of the survey.

        Returns:
            tuple[str, bool]: ``"east-west"`` or ``"north-south"`` (whichever
                span between the ends is longer; east-west on a tie) and
                ``True`` when the survey does not start at ``START[axis]``.
        """
        east_west = _distance(first, (first[0], last[1]))
        north_south = _distance(first, (last[0], first[1]))

        if east_west >= north_south:
            starts_west = first[1] <= last[1]
            wanted_west = cls.START["east-west"] == "west"
            return "east-west", starts_west != wanted_west

        starts_north = first[0] >= last[0]
        wanted_north = cls.START["north-south"] == "north"
        return "north-south", starts_north != wanted_north

    def _sync_record(self, record: dict) -> dict:
        """Sync the CIPS and PCM files of one index record."""
        row = dict.fromkeys(self.REPORT_COLUMNS)
        cips_name = record["normalized_cips_file"]
        pcm_name = record["normalized_pcm_file"]
        row.update(
            {
                "year": record["year"],
                "area": record["area"],
                "segment_code": record["segment_code"],
                "cips_reversed": False,
                "pcm_reversed": False,
                "normalized_cips_file": cips_name,
                "normalized_pcm_file": pcm_name,
                # full paths, so each pair can be opened for inspection
                "cips_json_path": self.json_path("cips", cips_name),
                "pcm_json_path": self.json_path("pcm", pcm_name),
                "cips_excel_path": self.excel_path("cips", cips_name),
                "pcm_excel_path": self.excel_path("pcm", pcm_name),
            }
        )

        try:
            cips_file = record["normalized_cips_file"]
            pcm_file = record["normalized_pcm_file"]
            cips = self._read_json(self.json_path("cips", cips_file), "cips")
            pcm = self._read_json(self.json_path("pcm", pcm_file), "pcm")

            # 1-2. CIPS starts by the main direction of its line.
            cips_first, cips_last = self.ends(cips, *self.COORDINATES["cips"])
            axis, cips_reverse = self.cips_direction(cips_first, cips_last)

            # 3. PCM starts at the end closer to the (synced) CIPS start.
            start = cips_last if cips_reverse else cips_first
            pcm_first, pcm_last = self.ends(pcm, *self.COORDINATES["pcm"])
            to_first = _distance(start, pcm_first)
            to_last = _distance(start, pcm_last)
            pcm_reverse = to_last < to_first

            # 4. Read and reverse every file to change.
            writes: list[tuple[str, pd.DataFrame, str]] = []
            for kind, filename, reverse in (
                ("cips", cips_file, cips_reverse),
                ("pcm", pcm_file, pcm_reverse),
            ):
                if not reverse:
                    continue
                excel_path = self.excel_path(kind, filename)
                excel = self._reverse(self._read_excel(excel_path, kind), kind)
                writes.append((excel_path, excel, "excel"))
                # The JSON is rebuilt from the recalculated Excel.
                json_frame = self.SURVEYS[kind].json_frame(excel)
                writes.append((self.json_path(kind, filename), json_frame, "json"))
        except Exception as e:
            row["reason"] = f"{type(e).__name__}: {e}"
            return row

        try:
            self._write_all(writes)
        except Exception as e:
            row["reason"] = f"write failed: {type(e).__name__}: {e}"
            return row

        row["cips_axis"] = axis
        row["cips_reversed"] = cips_reverse
        row["pcm_reversed"] = pcm_reverse
        row["start_gap_m"] = round(min(to_first, to_last), 2)

        if self.verbose and (cips_reverse or pcm_reverse):
            logger.info(
                f"{record['segment_code']}: reversed "
                f"CIPS={cips_reverse} ({axis}) PCM={pcm_reverse}"
            )

        return row

    def _read_json(self, path: str, kind: str) -> pd.DataFrame:
        """Read a normalized JSON file and check it has the keys sync uses.

        Raises:
            ValueError: If the file has no records, or misses the coordinate
                keys (e.g. a PCM file written before they were renamed to
                ``latitude`` / ``longitude``), which the decision is made on.
        """
        with open(path, encoding="utf-8") as file:
            records = json.load(file)
        if not records:
            raise ValueError(f"No records in {path}")

        missing = [key for key in self.COORDINATES[kind] if key not in records[0]]
        if missing:
            raise ValueError(
                f"{path} misses keys {missing}; normalize it again (main.py)"
            )
        # From the parsed records (not pd.read_json), so values keep their
        # JSON types and the key order is preserved.
        return pd.DataFrame(records)

    def _read_excel(self, path: str, kind: str) -> pd.DataFrame:
        """Read a normalized Excel file and check it has the columns sync uses.

        Raises:
            FileNotFoundError: If the Excel next to the JSON does not exist.
            ValueError: If it has no rows or misses one of
                ``EXCEL_REQUIRED_COLUMNS``.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"No normalized Excel for this JSON: {path}; normalize it again "
                f"(main.py)"
            )
        df = pd.read_excel(path)
        if df.empty:
            raise ValueError(f"No rows in {path}")

        required = self.EXCEL_REQUIRED_COLUMNS[kind]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(
                f"{path} misses columns {missing}; normalize it again (main.py)"
            )
        return df

    def _reverse(self, df: pd.DataFrame, kind: str) -> pd.DataFrame:
        """Reverse a normalized Excel and recompute the order-dependent values.

        Args:
            df (pd.DataFrame): Rows of the normalized Excel.
            kind (str): ``"cips"`` or ``"pcm"``.
        """
        df = df.iloc[::-1].reset_index(drop=True)
        columns = self.EXCEL_COLUMNS

        lat_key, lon_key = self.EXCEL_COORDINATES[kind]
        lat, lon = df[lat_key], df[lon_key]
        distance = pd.Series(
            calculate_distance(lat.shift(), lon.shift(), lat, lon), index=df.index
        ).fillna(0.0)

        df[columns["distance"]] = distance
        df[columns["real_distance"]] = distance.cumsum()

        if kind == "pcm":
            dbma = pd.to_numeric(df[columns["dbma"]], errors="coerce")
            df[columns["rate"]], df[columns["condition"]] = PCM.current_loss(
                dbma, distance
            )

        return df

    @classmethod
    def _write_all(cls, writes: list[tuple[str, pd.DataFrame, str]]) -> None:
        """Write files via temporary files, then move them over the originals.

        Every file is first written to a uniquely named temporary file in its
        own folder. Only when all of them are written are they moved over the
        originals (``os.replace``, atomic per file). If a write fails, the
        temporary files are removed and the originals are left untouched.
        Unique names keep parallel workers from colliding when two segments
        share a file.

        Raises:
            Exception: Whatever the failing write raised, after cleanup.
        """
        written: list[tuple[str, str]] = []
        try:
            for path, df, fmt in writes:
                folder, name = os.path.split(path)
                stem, suffix = os.path.splitext(name)
                # Keep the extension: to_excel picks its engine from it.
                fd, temp = tempfile.mkstemp(
                    prefix=f".{stem}.", suffix=suffix, dir=folder
                )
                os.close(fd)
                written.append((temp, path))
                cls._write(df, temp, fmt)
        except Exception:
            for temp, _ in written:
                if os.path.exists(temp):
                    os.remove(temp)
            raise

        for temp, path in written:
            os.replace(temp, path)

    @staticmethod
    def _write(df: pd.DataFrame, path: str, fmt: str) -> None:
        """Write a normalized file, in the same format as ``normalize()``."""
        if fmt == "json":
            df.to_json(path, orient="records")
        else:
            df.to_excel(path, index=False)


def _distance(a: Point, b: Point) -> float:
    """Return the distance in meters between two ``(lat, lon)`` points."""
    # Scalar inputs, so calculate_distance returns a float.
    return cast(float, calculate_distance(a[0], a[1], b[0], b[1]))
