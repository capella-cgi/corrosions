import os

import pandas as pd

from corrosions.data.file_index import FileIndex


def _write_sheets(path, sheets: dict[str, dict]) -> None:
    with pd.ExcelWriter(path) as writer:
        for name, data in sheets.items():
            pd.DataFrame(data).to_excel(writer, sheet_name=name, index=False)


def _cips_data(**extra) -> dict:
    data = {
        "Data No": [1, 2],
        "Latitude": [-6.1, -6.2],
        "Longitude": [106.1, 106.2],
        "Altitude": [10.0, 11.0],
        "Comment": ["", ""],
        "DCP/Feature/DCVG Anomaly": ["", ""],
        "On Voltage": [-1.1, -1.2],
        "Off Voltage": [-0.9, -1.0],
    }
    data.update(extra)
    return data


def _write_index(path, rows: list[tuple[int, str | None]]) -> None:
    n = len(rows)
    pd.DataFrame(
        {
            "Year": [year for year, _ in rows],
            "Area": ["A"] * n,
            "Segment": ["S"] * n,
            "Sub Segment": ["SS"] * n,
            "Diameter": [4.0] * n,
            "Length": [1.0] * n,
            "Province Code": [31] * n,
            "ACVG/DCVG": [None] * n,
            "CIPS": [name for _, name in rows],
            "PCM": [None] * n,
        }
    ).to_excel(path, index=False)


def test_check_cips_file(tmp_path):
    data_dir = tmp_path / "data"
    for year in (2021, 2022, 2024):
        os.makedirs(data_dir / str(year) / "CIPS")

    # valid: data sheet named after the segment, behind a chart sheet
    _write_sheets(
        data_dir / "2024" / "CIPS" / "good.xlsx",
        {"Grafik": {}, "Segment A": _cips_data()},
    )
    # 2022 export: "Index" / "Voltage (V)" / "Off Voltage (V)" are fixed -> valid
    legacy = _cips_data()
    legacy["Index"] = legacy.pop("Data No")
    legacy["Voltage (V)"] = legacy.pop("On Voltage")
    legacy["Off Voltage (V)"] = legacy.pop("Off Voltage")
    _write_sheets(data_dir / "2022" / "CIPS" / "legacy.xlsx", {"Data": legacy})
    # no Altitude -> invalid, flagged
    no_alt = _cips_data()
    del no_alt["Altitude"]
    _write_sheets(data_dir / "2024" / "CIPS" / "noalt.xlsx", {"Data": no_alt})
    # 2021 -mV export: left as is, no ICCP/SACP column -> invalid, flagged
    mv = _cips_data(**{"-mV On": [1100, 1200], "-mV Off": [900, 1000]})
    del mv["On Voltage"], mv["Off Voltage"]
    _write_sheets(data_dir / "2021" / "CIPS" / "mv.xlsx", {"Data": mv})
    # no data sheet at all
    _write_sheets(
        data_dir / "2024" / "CIPS" / "nodata.xlsx",
        {"Survey Info": {"Survey Type": ["x"]}},
    )

    index_path = tmp_path / "index.xlsx"
    _write_index(
        index_path,
        [
            (2024, "good.xlsx"),
            (2022, "legacy.xlsx"),
            (2024, "noalt.xlsx"),
            (2021, "mv.xlsx"),
            (2024, "nodata.xlsx"),
            (2024, "missing.xlsx"),
            (2024, None),
        ],
    )

    report = FileIndex(str(index_path)).check_cips_file(str(data_dir))
    report.index = [os.path.basename(p) for p in report["filepath"]]

    assert len(report) == 6  # row with no CIPS filename is skipped

    assert report.loc["good.xlsx", "is_valid"]
    assert report.loc["good.xlsx", "sheet_name"] == "Segment A"
    assert report.loc["good.xlsx", "candidate_sheets"] == ["Segment A"]

    assert report.loc["legacy.xlsx", "is_valid"]
    assert report.loc["legacy.xlsx", "n_missing"] == 0

    assert not report.loc["noalt.xlsx", "is_valid"]
    assert not report.loc["noalt.xlsx", "has_altitude"]
    assert report.loc["noalt.xlsx", "missing_columns"] == ["Altitude"]

    assert not report.loc["mv.xlsx", "is_valid"]
    assert not report.loc["mv.xlsx", "has_voltage"]
    assert report.loc["mv.xlsx", "n_missing"] == 0

    assert not report.loc["nodata.xlsx", "is_valid"]
    assert "No CIPS data sheet" in report.loc["nodata.xlsx", "reason"]

    assert report.loc["missing.xlsx", "reason"] == "file not found on disk"
