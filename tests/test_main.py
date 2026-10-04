"""End-to-end tests of the main.py CLI on a small synthetic data set."""

import os
import sys
import json
import importlib.util
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

MAIN_PATH = Path(__file__).resolve().parent.parent / "main.py"


def _load_main():
    """Import main.py from the repo root (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("corrosion_main", MAIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ACVG_HEADER = [
    "No",
    "Segmen",
    "Dia (inch)",
    "Lokasi Anomali",
    "Kondisi Permukaan",
    "%drop PCM",
    "On Potential (volt)",
    "Off Potential (volt)",
    "Tgl DCVG",
    "Tgl ACVG",
    "Latitude",
    "Longitude",
    "IR Drop (%)",
    "Kedalaman Pipa (m)",
    "Hasil ACVG (dB)",
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Index, CIPS/PCM source tree and ACVG/DCVG data for one 2024 segment."""
    monkeypatch.chdir(tmp_path)
    lons = [106.100, 106.101, 106.102]

    source = tmp_path / "source"
    os.makedirs(source / "2024" / "CIPS FINAL")
    os.makedirs(source / "2024" / "PCM FINAL")
    pd.DataFrame(
        {
            "Latitude": [-6.1] * 3,
            "Longitude": lons,
            "Comment": [""] * 3,
            "DCP/Feature/DCVG Anomaly": [""] * 3,
            "On Voltage": [-1.0, -1.1, -0.9],
            "Off Voltage": [-0.9, -0.95, -0.85],
        }
    ).to_excel(source / "2024" / "CIPS FINAL" / "CIPS - ICCP a.xlsx", index=False)
    pd.DataFrame(
        {
            "4Hz Current (A)": [0.5, 0.45, 0.2],
            "Int GPS Latitude": [-6.1] * 3,
            "Int GPS Longitude": lons,
            "Comment (0-100)": ["TP 1", None, None],
            "Gain (dB)": [30] * 3,
            "Depth (m)": [1.2] * 3,
        }
    ).to_excel(source / "2024" / "PCM FINAL" / "PCM a.xlsx", index=False)

    pd.DataFrame(
        {
            "Year": [2024],
            "Area": ["Jakarta"],
            "Nomor Segment": [1],
            "Segment": ["Seg A"],
            "Sub Segment": [None],
            "Diameter": [16],
            "Length": [1.0],
            "Province Code": [31],
            "ACVG/DCVG": [None],
            "CIPS": ["CIPS - ICCP a"],  # fix() appends .xlsx
            "PCM": ["PCM a.xlsx"],
        }
    ).to_excel(tmp_path / "index.xlsx", index=False)

    acvg_dir = tmp_path / "acvg"
    os.makedirs(acvg_dir)
    pd.DataFrame({"Year": [2024], "Filename": ["Rekap 2024.xlsx"]}).to_excel(
        tmp_path / "acvg-index.xlsx", index=False
    )
    anomaly = dict.fromkeys(ACVG_HEADER)
    anomaly.update(
        {
            "No": 1,
            # another name than the index: matched by the nearest CIPS track
            "Segmen": "Segmen A anomali",
            "Dia (inch)": 16,
            "Tgl DCVG": datetime(2024, 5, 20),
            "Tgl ACVG": datetime(2024, 5, 11),
            "Latitude": -6.1,
            "Longitude": 106.1012,
        }
    )
    pd.DataFrame([anomaly], columns=ACVG_HEADER).to_excel(
        acvg_dir / "Rekap 2024.xlsx", sheet_name="Jakarta", index=False
    )
    return tmp_path


def _run(monkeypatch, project, *extra) -> None:
    argv = [
        "main.py",
        "-i",
        str(project / "index.xlsx"),
        "-s",
        str(project / "source"),
        "--acvg-index",
        str(project / "acvg-index.xlsx"),
        "--acvg-dir",
        str(project / "acvg"),
        "-n",
        "1",
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    _load_main().main()


def test_full_run_includes_acvg_dcvg(project, monkeypatch, capsys):
    _run(monkeypatch, project)
    out = project / "output"

    for name in ("checked-cips.xlsx", "checked-pcm.xlsx", "sync-report.xlsx"):
        assert (out / name).is_file(), name
    with open(out / "file_index.json", encoding="utf-8") as f:
        (record,) = json.load(f)  # the segment has both normalized files
    # every CIPS reading of the fixture is protected (Off -0.85..-0.95 V)
    assert record["protected"] == 100.0
    assert record["unprotected"] == 0.0
    # PCM rates 0, 8.27, 63.31 dB/km -> 2 of 3 readings Medium to High
    assert record["medium_to_high"] == 66.67
    assert record["medium_to_poor"] == 33.33
    # added after the ACVG/DCVG step
    assert record["acvg_dcvg_normalized_file"] == "2024-acvg-dcvg-seg-a-16-jakarta.json"
    assert record["total_anomaly"] == 1
    with open(out / "area.json", encoding="utf-8") as f:
        (area,) = json.load(f)
    assert area["code"] == "jakarta-2024"
    assert (area["total_anomaly"], area["protected"]) == (1, 100.0)

    # ACVG/DCVG: one file per segment, named after the index row
    acvg_file = out / "raw_data" / "2024" / "ACVG_DCVG" / "acvg-dcvg-seg-a-16-jakarta.xlsx"
    assert acvg_file.is_file()
    index = pd.read_csv(out / "file_index_index.csv")
    assert index["ACVG_DCVG"].tolist() == ["acvg-dcvg-seg-a-16-jakarta.xlsx"]

    report = pd.read_excel(out / "acvg-dcvg-report.xlsx", sheet_name=None)
    assert set(report) == {
        "groups",
        "files",
        "load issues",
        "segments without ACVG-DCVG",
    }
    assert report["segments without ACVG-DCVG"].empty  # the only segment is linked
    assert report["groups"]["method"].tolist() == ["cips"]

    # cleaned and normalized next to CIPS/PCM, placed on the (synced) CIPS line
    assert (out / "cleaned" / "2024" / "ACVG_DCVG" / acvg_file.name).is_file()
    normalized = out / "normalize" / "acvg_dcvg" / "json" / f"2024-{acvg_file.stem}.json"
    with open(normalized, encoding="utf-8") as f:
        (record,) = json.load(f)
    assert record["closest_cips_condition"] in {"PROTECTED", "OVER PROTECTED", "UNPROTECTED"}
    assert record["real_distance"] is not None
    assert report["files"]["n_on_cips"].tolist() == [1]
    assert "ACVG/DCVG: 1 groups" in capsys.readouterr().out


def test_type_acvg_keeps_file_index_json(project, monkeypatch):
    _run(monkeypatch, project)
    index_json = project / "output" / "file_index.json"
    before = index_json.read_bytes()
    os.remove(project / "output" / "acvg-dcvg-report.xlsx")

    # ACVG/DCVG only: uses the normalized CIPS of the first run
    _run(monkeypatch, project, "--type", "acvg")

    # not overwritten with []; the ACVG/DCVG key is set again, the same way
    assert index_json.read_bytes() == before
    assert (project / "output" / "acvg-dcvg-report.xlsx").is_file()


def test_missing_acvg_data_is_skipped_with_type_all(project, monkeypatch, capsys):
    os.remove(project / "acvg-index.xlsx")
    _run(monkeypatch, project)

    assert "ACVG/DCVG skipped:" in capsys.readouterr().out
    assert (project / "output" / "file_index.json").is_file()  # CIPS/PCM still ran


def test_missing_acvg_data_fails_with_type_acvg(project, monkeypatch):
    os.remove(project / "acvg-index.xlsx")
    with pytest.raises(FileNotFoundError):
        _run(monkeypatch, project, "--type", "acvg")
