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
    "name": "Seg A",
    "code": "seg-a-16",
    "diameter": 16,
    "pipe_length": 1.0,
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
        **INDEX_RECORD,
        "cips_normalized_file": cips_file,
        "pcm_normalized_file": pcm_file,
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


def _excel_of(json_path: str) -> str:
    """Path of the normalized Excel next to a normalized JSON file."""
    folder, name = os.path.split(json_path)
    return os.path.join(
        os.path.dirname(folder), "excel", os.path.splitext(name)[0] + ".xlsx"
    )


def _excel_from_json(normalize_dir, kind: str, filename: str) -> None:
    """Write the Excel twin of a hand-made normalized JSON file.

    Uses normalize()'s Excel names (the survey's JSON_COLUMNS, reversed); any
    column the hand-made JSON lacks is left empty, as are PCM's other source
    columns.
    """
    survey = {"cips": CIPS, "pcm": PCM}[kind]
    records = _load(str(normalize_dir / kind / "json" / filename))
    excel_names = {key: column for column, key in survey.JSON_COLUMNS.items()}
    df = pd.DataFrame(records).rename(columns=excel_names)
    extra = PCM.REQUIRED_COLUMNS if kind == "pcm" else []
    for column in [*survey.JSON_COLUMNS, *extra]:
        if column not in df.columns:
            df[column] = None
    df.insert(0, "Distance", 0.0)
    excel = normalize_dir / kind / "excel"
    os.makedirs(excel, exist_ok=True)
    df.to_excel(excel / (os.path.splitext(filename)[0] + ".xlsx"), index=False)


@pytest.mark.parametrize("n_jobs", [1, 2])
def test_sync_matches_normalizing_the_reversed_survey(tmp_path, n_jobs):
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
    report = SyncData(
        index, normalize_dir=str(out / "normalize"), n_jobs=n_jobs
    ).sync()

    row = report.iloc[0]
    assert row["cips_reversed"] and row["pcm_reversed"]
    assert pd.isna(row["reason"])
    assert row["start_gap_m"] == 0.0

    cips = _load(cips_json)
    pcm = _load(pcm_json)
    assert cips[0]["longitude"] == 106.1  # starts at the west end
    assert pcm[0]["longitude"] == 106.1
    assert cips[0]["real_distance"] == 0.0
    _assert_records_equal(cips, _load(cips_expected))
    # current_loss_rate and condition recomputed against the new previous row
    _assert_records_equal(pcm, _load(pcm_expected))

    # the normalized Excel of each survey is reversed and recomputed the same way
    for synced, wanted in ((cips_json, cips_expected), (pcm_json, pcm_expected)):
        got = pd.read_excel(_excel_of(synced))
        want = pd.read_excel(_excel_of(wanted))
        assert list(got.columns) == list(want.columns)
        pd.testing.assert_frame_equal(got, want, check_exact=False, atol=1e-6)


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


def _write_survey(normalize_dir, kind: str, filename: str, points) -> None:
    """Write a hand-made normalized JSON (and its Excel twin) from points."""
    record = {"real_distance": 0.0}
    if kind == "pcm":
        record.update(
            {"dbma": 50.0, "current_loss_rate": 0.0, "condition": "Medium to High"}
        )
    _write_json(
        normalize_dir / kind / "json" / filename,
        [{"latitude": lat, "longitude": lon, **record} for lat, lon in points],
    )
    _excel_from_json(normalize_dir, kind, filename)


def test_north_south_line_starts_north_and_pcm_follows(tmp_path):
    normalize_dir = tmp_path / "normalize"
    # CIPS walked south -> north; its south end is slightly west, so the old
    # "start west" rule kept it, but a north-south line now starts north
    _write_survey(
        normalize_dir,
        "cips",
        "c.json",
        [(-6.12, 106.09999), (-6.11, 106.1), (-6.10, 106.10001)],
    )
    # PCM also walked south -> north: it follows the CIPS start (north)
    _write_survey(
        normalize_dir,
        "pcm",
        "p.json",
        [(-6.12, 106.10002), (-6.11, 106.1), (-6.10, 106.09998)],
    )
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    row = report.iloc[0]
    assert row["cips_axis"] == "north-south"
    assert row["cips_reversed"] and row["pcm_reversed"]
    assert _load(str(normalize_dir / "cips" / "json" / "c.json"))[0]["latitude"] == -6.10
    pcm = _load(str(normalize_dir / "pcm" / "json" / "p.json"))
    assert pcm[0]["latitude"] == -6.10
    assert pcm[-1]["real_distance"] == pytest.approx(2223.9, abs=0.5)

    # the JSON was rebuilt from the recalculated Excel: same values (to_json
    # writes 10 decimal places, Excel keeps the full float)
    pcm_excel = pd.read_excel(normalize_dir / "pcm" / "excel" / "p.xlsx")
    assert pcm_excel["Int GPS Latitude"].tolist() == [-6.10, -6.11, -6.12]
    assert [r["real_distance"] for r in pcm] == pytest.approx(
        pcm_excel["Real Distance"].tolist(), abs=1e-9
    )


def test_start_can_be_configured(tmp_path, monkeypatch):
    normalize_dir = tmp_path / "normalize"
    points = [(-6.10, 106.1), (-6.11, 106.1), (-6.12, 106.1)]  # north -> south
    _write_survey(normalize_dir, "cips", "c.json", points)
    _write_survey(normalize_dir, "pcm", "p.json", points)
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")
    monkeypatch.setitem(SyncData.START, "north-south", "south")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    assert report.iloc[0]["cips_reversed"]
    assert _load(str(normalize_dir / "cips" / "json" / "c.json"))[0]["latitude"] == -6.12


def test_one_bad_gps_fix_at_an_end_does_not_flip_the_survey(tmp_path):
    normalize_dir = tmp_path / "normalize"
    # west -> east, but the very last fix jumped west of the first reading
    lons = [106.100 + i * 0.001 for i in range(11)] + [106.0995]
    _write_survey(normalize_dir, "cips", "c.json", [(-6.1, lon) for lon in lons])
    _write_survey(normalize_dir, "pcm", "p.json", [(-6.1, lon) for lon in lons])
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    # first/last reading alone would say "starts east"; the averaged ends don't
    assert report.iloc[0]["cips_axis"] == "west-east"
    assert not report.iloc[0]["cips_reversed"]
    assert not report.iloc[0]["pcm_reversed"]


def test_ends_average_the_end_readings():
    df = pd.DataFrame({"lat": [0.0] * 12, "lon": [float(i) for i in range(12)]})
    first, last = SyncData.ends(df, "lat", "lon")
    assert first == (0.0, 2.0)  # mean of 0..4
    assert last == (0.0, 9.0)  # mean of 7..11
    short = df.iloc[:3]  # fewer than 2 * END_READINGS: one reading per end
    assert SyncData.ends(short, "lat", "lon") == ((0.0, 0.0), (0.0, 2.0))


def test_failed_write_leaves_files_untouched(tmp_path, monkeypatch):
    normalize_dir = tmp_path / "normalize"
    east_to_west = [(-6.1, 106.102), (-6.1, 106.101), (-6.1, 106.100)]
    _write_survey(normalize_dir, "cips", "c.json", east_to_west)
    _write_survey(normalize_dir, "pcm", "p.json", east_to_west)
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")
    before = {
        path: path.read_bytes() for path in normalize_dir.rglob("*") if path.is_file()
    }

    real_write = SyncData._write

    def _write(df, path, fmt):
        if fmt == "excel" and "pcm" in path:
            raise OSError("disk full")
        real_write(df, path, fmt)

    # n_jobs=1 runs in this process, so the patched _write is used
    monkeypatch.setattr(SyncData, "_write", staticmethod(_write))
    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    row = report.iloc[0]
    assert row["reason"] == "write failed: OSError: disk full"
    assert not row["cips_reversed"]
    # every original file is unchanged and no temporary file is left behind
    after = {
        path: path.read_bytes() for path in normalize_dir.rglob("*") if path.is_file()
    }
    assert after == before


def test_missing_file_is_reported_and_others_still_run(tmp_path):
    normalize_dir = tmp_path / "normalize"
    _write_json(
        normalize_dir / "cips" / "json" / "c.json",
        [{"latitude": -6.1, "longitude": 106.1, "real_distance": 0.0}],
    )
    with open(tmp_path / "file_index.json", "w", encoding="utf-8") as f:
        json.dump(
            [
                {**INDEX_RECORD, "cips_normalized_file": "c.json",
                 "pcm_normalized_file": "missing.json"},
                {**INDEX_RECORD, "code": "empty",
                 "cips_normalized_file": "c.json", "pcm_normalized_file": "e.json"},
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
    record = {**INDEX_RECORD, "cips_normalized_file": "c.json"}  # no PCM key
    with open(tmp_path / "file_index.json", "w", encoding="utf-8") as f:
        json.dump([record], f)
    with pytest.raises(KeyError, match="pcm_normalized_file"):
        SyncData(str(tmp_path / "file_index.json"), normalize_dir=str(tmp_path))


def test_file_with_old_pcm_keys_is_reported(tmp_path):
    # PCM JSON written before int_gps_latitude/longitude became latitude/longitude
    normalize_dir = tmp_path / "normalize"
    _write_json(
        normalize_dir / "cips" / "json" / "c.json",
        [{"latitude": -6.1, "longitude": 106.1, "real_distance": 0.0}],
    )
    _write_json(
        normalize_dir / "pcm" / "json" / "old.json",
        [{"int_gps_latitude": -6.1, "int_gps_longitude": 106.1, "dbma": 50.0}],
    )
    index = _write_index(tmp_path / "file_index.json", "c.json", "old.json")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    reason = report.iloc[0]["reason"]
    assert reason.startswith("ValueError")
    assert "['latitude', 'longitude']" in reason


def test_missing_excel_leaves_the_segment_untouched(tmp_path):
    normalize_dir = tmp_path / "normalize"
    cips_records = [
        {"latitude": -6.1, "longitude": lon, "real_distance": 0.0}
        for lon in (106.102, 106.101, 106.100)  # east -> west: needs reversing
    ]
    _write_json(normalize_dir / "cips" / "json" / "c.json", cips_records)
    _write_json(
        normalize_dir / "pcm" / "json" / "p.json",
        [
            {"latitude": -6.1, "longitude": lon, "real_distance": 0.0, "dbma": 50.0}
            for lon in (106.100, 106.101, 106.102)
        ],
    )
    # the PCM Excel exists, the CIPS Excel does not
    _excel_from_json(normalize_dir, "pcm", "p.json")
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")

    report = SyncData(index, normalize_dir=str(normalize_dir)).sync()

    row = report.iloc[0]
    assert row["reason"].startswith("FileNotFoundError: No normalized Excel")
    assert not row["cips_reversed"] and not row["pcm_reversed"]
    # nothing was written: the CIPS JSON keeps its east -> west order
    assert _load(str(normalize_dir / "cips" / "json" / "c.json")) == cips_records


def test_report_has_start_gap_and_file_paths(tmp_path):
    normalize_dir = tmp_path / "normalize"
    _write_json(
        normalize_dir / "cips" / "json" / "c.json",
        [{"latitude": -6.1, "longitude": lon, "real_distance": 0.0} for lon in (106.100, 106.101)],
    )
    _write_json(
        normalize_dir / "pcm" / "json" / "p.json",
        [{"latitude": -6.1, "longitude": lon, "dbma": 50.0} for lon in (106.101, 106.102)],
    )
    index = _write_index(tmp_path / "file_index.json", "c.json", "p.json")

    row = SyncData(index, normalize_dir=str(normalize_dir)).sync().iloc[0]

    assert (row["year"], row["area"]) == (2025, "Jakarta")
    # PCM starts 0.001 degree longitude east of the CIPS start (~110.57 m at -6.1)
    assert row["start_gap_m"] == pytest.approx(110.57, abs=0.01)
    assert row["cips_json_path"] == str(normalize_dir / "cips" / "json" / "c.json")
    assert row["pcm_json_path"] == str(normalize_dir / "pcm" / "json" / "p.json")
    assert row["cips_excel_path"] == str(normalize_dir / "cips" / "excel" / "c.xlsx")
    assert row["pcm_excel_path"] == str(normalize_dir / "pcm" / "excel" / "p.xlsx")
