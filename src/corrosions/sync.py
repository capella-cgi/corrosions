"""Put the CIPS and PCM surveys of each segment in the same direction.

CIPS and PCM surveys of one pipeline segment are often walked in opposite
directions (e.g. PCM east to west, CIPS west to east). ``SyncData`` reads the
index written by ``FileIndex.to_json`` and, for every segment, reorders the
normalized JSON files so both surveys start at the same end:

1. CIPS starts at its west end (smallest longitude of its two end points).
2. PCM starts at the end closer to the CIPS start, so it follows CIPS even on
   north-south lines where the longitudes of the two ends barely differ.

A reversed file gets ``real_distance`` recomputed and, for PCM,
``current_loss_rate`` and ``condition`` too, since both depend on the
previous reading. Files are overwritten in place. The rule gives the same
order every time, so running it again changes nothing.

Example:
    >>> from corrosions.sync import SyncData
    >>> report = SyncData("output/file_index.json", verbose=True).sync()
    >>> report[report["cips_reversed"] | report["pcm_reversed"]]
"""

import os
import json
from typing import cast

import pandas as pd

from corrosions.logging import logger
from corrosions.data.pcm import PCM
from corrosions.utils.geo_utils import calculate_distance
from corrosions.utils.path_utils import resolve_output_dir


class SyncData:
    """Sync the survey direction of the CIPS and PCM files in the index.

    Attributes:
        REQUIRED_KEYS (tuple[str, ...]): Keys every record of the index JSON
            must have.
        COORDINATES (dict[str, tuple[str, str]]): Latitude/longitude keys of
            the normalized JSON, per survey kind.
        json_file_index (str): Path to the index JSON (``file_index.json``).
        data (list[dict]): Records of the index JSON.
        normalize_dir (str): Root of the normalized files,
            ``<normalize_dir>/<cips|pcm>/json/<file>``.
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
        "pcm": ("int_gps_latitude", "int_gps_longitude"),
    }

    def __init__(
        self,
        json_file_index: str,
        normalize_dir: str | None = None,
        verbose: bool = False,
    ) -> None:
        """Load the index JSON written by ``FileIndex.to_json``.

        Args:
            json_file_index (str): Path to ``file_index.json``.
            normalize_dir (str | None): Root of the normalized files. Defaults
                to ``<cwd>/output/normalize``, where ``CIPS.normalize`` and
                ``PCM.normalize`` write them.
            verbose (bool): If True, log each reversed file and a summary.
                Defaults to ``False``.

        Raises:
            FileNotFoundError: If ``json_file_index`` does not exist.
            KeyError: If a record misses one of ``REQUIRED_KEYS``.

        Example:
            >>> sync = SyncData("output/file_index.json")
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

    def sync(self) -> pd.DataFrame:
        """Reorder every segment's CIPS and PCM files to start at the same end.

        For each record of the index:

        1. CIPS is reversed when its first reading is east of its last one,
           so it starts at its west end.
        2. PCM is reversed when its last reading is closer than its first one
           to the (synced) CIPS start.
        3. A reversed file gets ``real_distance`` recomputed; a reversed PCM
           file also gets ``current_loss_rate`` and ``condition`` recomputed
           (``PCM.current_loss``). It is then overwritten in place. Files
           that are already in order are not rewritten.

        A segment whose file is missing, unreadable or empty is skipped and
        reported with a ``reason``; the others still run.

        Returns:
            pd.DataFrame: One row per index record with ``segment_code``,
                ``normalized_cips_file``, ``normalized_pcm_file``,
                ``cips_reversed``, ``pcm_reversed``, ``start_gap_m`` (meters
                between the CIPS and PCM start after syncing) and ``reason``
                (``None`` when synced). Also stored on ``self.report``.

        Example:
            >>> report = SyncData("output/file_index.json").sync()
            >>> report["pcm_reversed"].sum()
        """
        rows = [self._sync_record(record) for record in self.data]
        self.report = pd.DataFrame(
            rows,
            columns=[
                "segment_code",
                "normalized_cips_file",
                "normalized_pcm_file",
                "cips_reversed",
                "pcm_reversed",
                "start_gap_m",
                "reason",
            ],
        )

        if self.verbose:
            report = self.report
            logger.info(
                f"Synced {int(report['reason'].isna().sum())}/{len(report)} "
                f"segments: reversed {int(report['cips_reversed'].sum())} CIPS "
                f"and {int(report['pcm_reversed'].sum())} PCM files"
            )

        return self.report

    def _sync_record(self, record: dict) -> dict:
        """Sync the CIPS and PCM files of one index record."""
        row = {
            "segment_code": record["segment_code"],
            "normalized_cips_file": record["normalized_cips_file"],
            "normalized_pcm_file": record["normalized_pcm_file"],
            "cips_reversed": False,
            "pcm_reversed": False,
            "start_gap_m": None,
            "reason": None,
        }

        try:
            cips_path = self.json_path("cips", record["normalized_cips_file"])
            pcm_path = self.json_path("pcm", record["normalized_pcm_file"])
            cips = self._read(cips_path)
            pcm = self._read(pcm_path)
        except Exception as e:
            row["reason"] = f"{type(e).__name__}: {e}"
            return row

        cips_lat, cips_lon = self.COORDINATES["cips"]
        pcm_lat, pcm_lon = self.COORDINATES["pcm"]

        # 1. CIPS starts at its west end.
        if cips[cips_lon].iloc[0] > cips[cips_lon].iloc[-1]:
            cips = self._reverse(cips, "cips")
            self._write(cips, cips_path)
            row["cips_reversed"] = True

        # 2. PCM starts at the end closer to the CIPS start.
        # Scalar inputs, so calculate_distance returns a float.
        start_lat, start_lon = cips[cips_lat].iloc[0], cips[cips_lon].iloc[0]
        to_first = cast(
            float,
            calculate_distance(
                start_lat, start_lon, pcm[pcm_lat].iloc[0], pcm[pcm_lon].iloc[0]
            ),
        )
        to_last = cast(
            float,
            calculate_distance(
                start_lat, start_lon, pcm[pcm_lat].iloc[-1], pcm[pcm_lon].iloc[-1]
            ),
        )
        if to_last < to_first:
            pcm = self._reverse(pcm, "pcm")
            self._write(pcm, pcm_path)
            row["pcm_reversed"] = True

        row["start_gap_m"] = round(min(to_first, to_last), 2)

        if self.verbose and (row["cips_reversed"] or row["pcm_reversed"]):
            logger.info(
                f"{record['segment_code']}: reversed "
                f"CIPS={row['cips_reversed']} PCM={row['pcm_reversed']}"
            )

        return row

    @staticmethod
    def _read(path: str) -> pd.DataFrame:
        """Read a normalized JSON file; it must have at least one record."""
        with open(path, encoding="utf-8") as file:
            records = json.load(file)
        if not records:
            raise ValueError(f"No records in {path}")
        # From the parsed records (not pd.read_json), so values keep their
        # JSON types and the key order is preserved.
        return pd.DataFrame(records)

    def _reverse(self, df: pd.DataFrame, kind: str) -> pd.DataFrame:
        """Reverse a survey and recompute the values that depend on order."""
        df = df.iloc[::-1].reset_index(drop=True)

        lat_key, lon_key = self.COORDINATES[kind]
        lat, lon = df[lat_key], df[lon_key]
        distance = pd.Series(
            calculate_distance(lat.shift(), lon.shift(), lat, lon), index=df.index
        ).fillna(0.0)
        df["real_distance"] = distance.cumsum()

        if kind == "pcm":
            dbma = pd.to_numeric(df["dbma"], errors="coerce")
            df["current_loss_rate"], df["condition"] = PCM.current_loss(dbma, distance)

        return df

    @staticmethod
    def _write(df: pd.DataFrame, path: str) -> None:
        """Overwrite a normalized JSON file, in the same format as normalize()."""
        df.to_json(path, orient="records")
