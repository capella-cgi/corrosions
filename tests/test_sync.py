import os
import json

import pandas as pd
import pytest

from corrosions.data.cips import CIPS
from corrosions.data.pcm import PCM
from corrosions.sync import SyncData

INDEX_RECORD = {
    "year": 2025,
    "area": "Jakarta",
    "area_code": "jakarta-2025",
    "segment": "Seg A",
    "segment_code": "seg-a-16",
    "pipe_diameter": 16,
    "length": 1.0,
    "cips_protection": "ICCP",
}


def _cips_source(longitudes: list[float]) -> dict:
    n = len(longitudes)
    return {
        "Latitude": [-6.1] * n,
        "Longitude": longitudes,
        "Comment": [""] * n,
        "DCP/Feature/DCVG Anomaly": [""] * n,
        "On Voltage": [-1.0, -1.1, -0.8, -1.3][:n],
        "Off Voltage": [-0.9, -0.95, -0.7, -1.25][:n],
    }


def _pcm_source(longitudes: list[float]) -> dict:
    n = len(longitudes)
    return {
        "4Hz Current (A)": [0.5, 0.45, 0.2, 0.19][:n],
        "Int GPS Latitude": [-6.1] * n,
        "Int GPS Longitude": longitudes,
        "Comment (0-100)": ["TP 1"] + [None] * (n - 1),
        "Gain (dB)": [30] * n,
        "Depth (m)": [1.2] * n,
    }


def _reversed(data: dict) -> dict:
    return {key: list(reversed(values)) for key, values in data.items()}


def _normalize(cls, data: dict, path, output_dir) -> str:
    pd.DataFrame(data).to_excel(path, index=False)
    survey = cls(str(path), year=2025, output_dir=str(output_dir)).clean().normalize()
    return survey.normalize_json_filepath


def _write_index(path, cips_file: str, pcm_file: str) -> str:
    record = {
        "id": 0,
        **INDEX_RECORD,
        "normalized_cips_file": cips_file,
        "normalized_pcm_file": pcm_file,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump([record], f)
    return str(path)


def _load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _assert_records_equal(actual: list[dict], expected: list[dict]) -> None:
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert list(got) == list(want)  # same keys, same order
        for key, value in want.items():
            if isinstance(value, float):
                assert got[key] == pytest.approx(value, abs=1e-6), key
            else:
                assert got[key] == value, key


def test_sync_matches_normalizing_the_reversed_survey(tmp_path):
    # both surveys walked east -> west; 0.001 degree longitude apart
    east_to_west = [106.103, 106.102, 106.101, 106.100]
    out, expected = tmp_path / "out", tmp_path / "expected"
    cips_json = _normalize(
        CIPS, _cips_source(east_to_west), tmp_path / "CIPS - ICCP a.xlsx", out
    )
    pcm_json = _normalize(PCM, _pcm_source(east_to_west), tmp_path / "PCM a.xlsx", out)
    # what normalize() gives for the same surveys walked west -> east
    cips_expected = _normalize(
        CIPS,
        _reversed(_cips_source(east_to_west)),
        tmp_path / "CIPS - ICCP a.xlsx",
        expected,
    )
    pcm_expected = _normalize(
        PCM, _reversed(_pcm_source(east_to_west)), tmp_path / "PCM a.xlsx", expected
    )

    index = _write_index(
        tmp_path / "file_index.json",
        os.path.basename(cips_json),
        os.path.basename(pcm_json),
    )
    report = SyncData(index, normalize_dir=str(out / "normalize")).sync()

    row = report.iloc[0]
    assert row["cips_reversed"] and row["pcm_reversed"]
    assert pd.isna(row["reason"])
    assert row["start_gap_m"] == 0.0

    cips = _load(cips_json)
    pcm = _load(pcm_json)
    assert cips[0]["longitude"] == 106.1  # starts at the west end
    assert pcm[0]["int_gps_longitude"] == 106.1
    assert cips[0]["real_distance"] == 0.0
    _assert_records_equal(cips, _load(cips_expected))
    # current_loss_rate and condition recomputed against the new previous row
    _assert_records_equal(pcm, _load(pcm_expected))


def test_sync_is_idempotent(tmp_path):
    out = tmp_path / "out"
    lons = [106.103, 106.102, 106.101]
    cips_json = _normalize(CIPS, _cips_source(lons), tmp_path / "CIPS - ICCP a.xlsx", out)
    pcm_json = _normalize(PCM, _pcm_source(lons), tmp_path / "PCM a.xlsx", out)
    index = _write_index(
        tmp_path / "file_index.json",
        os.path.basename(cips_json),
        os.path.basename(pcm_json),
    )

    SyncData(index, normalize_dir=str(out / "normalize")).sync()
    first = (_load(cips_json), _load(pcm_json))
    report = SyncData(index, normalize_dir=str(out / "normalize")).sync()

    assert not report["cips_reversed"].any()
    assert not report["pcm_reversed"].any()
    assert (_load(cips_json), _load(pcm_json)) == first


def test_files_already_west_to_east_are_not_rewritten(tmp_path):
    out = tmp_path / "out"
    lons = [106.100, 106.101, 106.102]
    cips_json = _normalize(CIPS, _cips_source(lons), tmp_path / "CIPS - ICCP a.xlsx", out)
    pcm_json = _normalize(PCM, _pcm_source(lons), tmp_path / "PCM a.xlsx", out)
    mtimes = (os.path.getmtime(cips_json), os.path.getmtime(pcm_json))
    index = _write_index(
        tmp_path / "file_index.json",
        os.path.basename(cips_json),
        os.path.basename(pcm_json),
    )

    report = SyncData(index, normalize_dir=str(out / "normalize")).sync()

    assert not report.iloc[0]["cips_reversed"]
    assert not report.iloc[0]["pcm_reversed"]
    assert (os.path.getmtime(cips_json), os.path.getmtime(pcm_json)) == mtimes


def _write_json(path, records: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f)


def test_pcm_follows_cips_start_on_north_south_line(tmp_path):
    normalize_dir = tmp_path / "normalize"
    # north-south CIPS line: its north end (-6.10) is 0.00001 degree east, so
    # CIPS is reversed and starts at the south end (-6.12)
    _write_json(
        normalize_dir / "cips" / "json" / "c.json",
        [
            {"latitude": lat, "longitude": lon, "real_distance": 0.0}
            for lat, lon in [(-6.10, 106.10001), (-6.11, 106.1), (-6.12, 106.1)]
        ],
    )
    # PCM starts in the north and its own west end is that north end, but it
    # must follow the CIPS start (south), so it is reversed anyway
    _write_json(
        normalize_dir / "pcm" / "json" / "p.json",
        [
            {
                "int_gps_latitude": lat,
                "int_gps_longitude": lon,
                "real_distance": 0.0,
                "dbma": 50.0,
                "current_loss_rate": 0.0,
                "condition": "Medium to High",
            }
            for lat, lon in [(-6.10, 106.09999), (-6.11, 106.1), (-6.12, 106.1)]
        ],
    )
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    assert report.iloc[0]["cips_reversed"]
    assert report.iloc[0]["pcm_reversed"]
    assert _load(str(normalize_dir / "cips" / "json" / "c.json"))[0]["latitude"] == -6.12
    pcm = _load(str(normalize_dir / "pcm" / "json" / "p.json"))
    assert pcm[0]["int_gps_latitude"] == -6.12
    assert pcm[-1]["real_distance"] == pytest.approx(2223.9, abs=0.5)


def test_missing_file_is_reported_and_others_still_run(tmp_path):
    normalize_dir = tmp_path / "normalize"
    _write_json(
        normalize_dir / "cips" / "json" / "c.json",
        [{"latitude": -6.1, "longitude": 106.1, "real_distance": 0.0}],
    )
    with open(tmp_path / "file_index.json", "w", encoding="utf-8") as f:
        json.dump(
            [
                {**INDEX_RECORD, "normalized_cips_file": "c.json",
                 "normalized_pcm_file": "missing.json"},
                {**INDEX_RECORD, "segment_code": "empty",
                 "normalized_cips_file": "c.json", "normalized_pcm_file": "e.json"},
            ],
            f,
        )
    _write_json(normalize_dir / "pcm" / "json" / "e.json", [])

    report = SyncData(
        str(tmp_path / "file_index.json"), normalize_dir=str(normalize_dir)
    ).sync()

    assert report.iloc[0]["reason"].startswith("FileNotFoundError")
    assert report.iloc[1]["reason"].startswith("ValueError: No records")
    assert not report["cips_reversed"].any()


def test_missing_index_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="to_json"):
        SyncData(str(tmp_path / "nope.json"))


def test_missing_required_key_raises(tmp_path):
    record = {**INDEX_RECORD, "normalized_cips_file": "c.json"}  # no PCM key
    with open(tmp_path / "file_index.json", "w", encoding="utf-8") as f:
        json.dump([record], f)
    with pytest.raises(KeyError, match="normalized_pcm_file"):
        SyncData(str(tmp_path / "file_index.json"), normalize_dir=str(tmp_path))
