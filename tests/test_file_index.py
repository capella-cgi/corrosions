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


def test_check_cips_file(tmp_path, monkeypatch):
    # check_cips_file saves cleaned copies under <cwd>/output; keep them in tmp
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    for year in (2021, 2022, 2024):
        os.makedirs(data_dir / str(year) / "CIPS")

    # valid: data sheet named after the segment, behind a chart sheet
    _write_sheets(
        data_dir / "2024" / "CIPS" / "good.xlsx",
        {"Grafik": {}, "Segment A": _cips_data()},
    )
    # 2022 export: "Voltage (V)" / "Off Voltage (V)" are fixed; the filename
    # tells ICCP from SACP -> valid
    legacy = _cips_data()
    legacy["Index"] = legacy.pop("Data No")
    legacy["Voltage (V)"] = legacy.pop("On Voltage")
    legacy["Off Voltage (V)"] = legacy.pop("Off Voltage")
    _write_sheets(data_dir / "2022" / "CIPS" / "CIPS - ICCP legacy.xlsx", {"Data": legacy})
    # same columns, but the filename names neither ICCP nor SACP -> checks
    # pass, clean() fails
    _write_sheets(data_dir / "2022" / "CIPS" / "unknown.xlsx", {"Data": legacy})
    # Altitude is not required -> valid
    no_alt = _cips_data()
    del no_alt["Altitude"]
    _write_sheets(data_dir / "2024" / "CIPS" / "noalt.xlsx", {"Data": no_alt})
    # 2021 -mV export: no ICCP/SACP column -> invalid, flagged
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
            (2022, "CIPS - ICCP legacy.xlsx"),
            (2022, "unknown.xlsx"),
            (2024, "noalt.xlsx"),
            (2021, "mv.xlsx"),
            (2024, "nodata.xlsx"),
            (2024, "missing.xlsx"),
            (2024, None),
        ],
    )

    report = FileIndex(str(index_path)).check_cips_file(str(data_dir))
    report.index = [os.path.basename(p) for p in report["filepath"]]

    assert len(report) == 7  # row with no CIPS filename is skipped

    assert report.loc["good.xlsx", "is_valid"]
    assert report.loc["good.xlsx", "sheet_name"] == "Segment A"
    assert report.loc["good.xlsx", "candidate_sheets"] == ["Segment A"]
    assert report.loc["good.xlsx", "cleaned_path"] == os.path.join(
        str(tmp_path), "output", "cleaned", "2024", "CIPS", "good.xlsx"
    )
    assert os.path.isfile(report.loc["good.xlsx", "cleaned_path"])

    assert report.loc["CIPS - ICCP legacy.xlsx", "is_valid"]
    assert report.loc["CIPS - ICCP legacy.xlsx", "n_missing"] == 0

    # check columns are kept when only clean() fails
    assert not report.loc["unknown.xlsx", "is_valid"]
    assert report.loc["unknown.xlsx", "has_voltage"]
    assert report.loc["unknown.xlsx", "n_missing"] == 0
    assert pd.isna(report.loc["unknown.xlsx", "cleaned_path"])
    assert "Cannot tell ICCP from SACP" in report.loc["unknown.xlsx", "reason"]

    assert report.loc["noalt.xlsx", "is_valid"]
    assert report.loc["noalt.xlsx", "n_missing"] == 0
    assert "has_altitude" not in report.columns

    assert not report.loc["mv.xlsx", "is_valid"]
    assert not report.loc["mv.xlsx", "has_voltage"]
    assert report.loc["mv.xlsx", "n_missing"] == 0
    assert report.loc["mv.xlsx", "reason"].startswith("clean failed")

    assert not report.loc["nodata.xlsx", "is_valid"]
    assert "No CIPS data sheet" in report.loc["nodata.xlsx", "reason"]

    assert report.loc["missing.xlsx", "reason"] == "file not found on disk"

    # skip_years leaves those years out of the report entirely
    skipped = FileIndex(str(index_path), skip_years=[2021, 2022]).check_cips_file(
        str(data_dir)
    )
    assert set(skipped["year"]) == {2024}
    assert len(skipped) == 4


def test_skip_years_applies_to_every_data_type(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    index_path = tmp_path / "index.xlsx"
    pd.DataFrame(
        {
            "Year": [2021, 2024],
            "Area": ["A", "A"],
            "Segment": ["S", "S"],
            "Sub Segment": ["SS", "SS"],
            "Diameter": [4.0, 4.0],
            "Length": [1.0, 1.0],
            "Province Code": [31, 31],
            "ACVG/DCVG": [None, None],
            "CIPS": ["c-2021.xlsx", "c-2024.xlsx"],
            "PCM": ["p-2021.xlsx", "p-2024.xlsx"],
        }
    ).to_excel(index_path, index=False)

    index = FileIndex(str(index_path), skip_years=[2021])
    assert index.skip_years == [2021]
    assert index.df["Year"].tolist() == [2024]
    assert list(index.df.index) == [0]
    assert index.by_year(2021).empty

    # neither file exists, so each report has only the 2024 row
    data_dir = str(tmp_path / "data")
    assert index.check_pcm_file(data_dir)["year"].tolist() == [2024]
    assert index.check_cips_file(data_dir)["year"].tolist() == [2024]

    index.check_existing_file(data_dir)
    assert index.df["Year"].tolist() == [2024]


def test_rebuild_fixes_filenames_before_checking_existence(tmp_path):
    # the index lists "seg" without .xlsx; the file on disk is "seg.xlsx"
    source = tmp_path / "source"
    os.makedirs(source / "2024" / "CIPS FINAL")
    pd.DataFrame({"Latitude": [-6.1]}).to_excel(
        source / "2024" / "CIPS FINAL" / "seg.xlsx", index=False
    )
    index_path = tmp_path / "index.xlsx"
    _write_index(index_path, [(2024, "seg")])

    out = tmp_path / "out"
    index = FileIndex(str(index_path)).rebuild(
        source_dir=str(source), output_dir=str(out)
    )

    assert index.fixed
    assert index.df.loc[0, "CIPS"] == "seg.xlsx"
    assert index.df.loc[0, "CIPS File Exists"]
    assert os.path.isfile(out / "raw_data" / "2024" / "CIPS" / "seg.xlsx")
