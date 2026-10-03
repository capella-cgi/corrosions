import os
import json

import pandas as pd
import pytest

from corrosions.data.cips import CIPS
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
            "Segment": [f"S{i}" for i in range(n)],  # Segment + Diameter unique
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

    index = FileIndex(str(index_path))
    report = index.check_cips_file(str(data_dir))
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

    # normalized file + protection land in the report and in index.df
    assert report.loc["good.xlsx", "cips_protection"] == "ICCP"
    assert report.loc["good.xlsx", "normalized"]
    assert not report.loc["unknown.xlsx", "normalized"]  # clean failed
    assert not report.loc["missing.xlsx", "normalized"]  # never loaded
    assert not report.loc["nodata.xlsx", "normalized"]  # load error
    assert report["normalized"].dtype == bool  # no NaN from early returns
    assert report.loc["good.xlsx", "normalized_cips_file"] == "2024-good.json"
    assert os.path.isfile(
        tmp_path / "output" / "normalize" / "cips" / "json" / "2024-good.json"
    )
    assert index.df["normalized_cips_file"].tolist()[:3] == [
        "2024-good.json",
        "2022-cips-iccp-legacy.json",
        None,  # unknown.xlsx: clean failed
    ]
    assert index.df["cips_protection"].tolist()[:3] == ["ICCP", "ICCP", None]
    assert pd.isna(index.df.loc[6, "normalized_cips_file"])  # missing.xlsx
    assert pd.isna(index.df.loc[7, "cips_protection"])  # no CIPS filename

    records = json.loads(open(index.to_json(str(tmp_path / "out")), encoding="utf-8").read())
    assert records[0]["cips_protection"] == "ICCP"
    assert records[0]["normalized_cips_file"] == "2024-good.json"
    assert records[2]["normalized_cips_file"] is None

    # skip_years leaves those years out of the report entirely
    skipped = FileIndex(str(index_path), skip_years=[2021, 2022]).check_cips_file(
        str(data_dir)
    )
    assert set(skipped["year"]) == {2024}
    assert len(skipped) == 4


def test_check_cips_file_normalize_failure(tmp_path, monkeypatch):
    # n_jobs=1 runs in this process, so the patched normalize() is used
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    os.makedirs(data_dir / "2024" / "CIPS")
    _write_sheets(data_dir / "2024" / "CIPS" / "good.xlsx", {"Data": _cips_data()})
    index_path = tmp_path / "index.xlsx"
    _write_index(index_path, [(2024, "good.xlsx")])

    def _fail(self):
        raise OSError("disk full")

    monkeypatch.setattr(CIPS, "normalize", _fail)
    index = FileIndex(str(index_path))
    report = index.check_cips_file(str(data_dir), n_jobs=1)

    row = report.iloc[0]
    assert not row["is_valid"]
    assert not row["normalized"]
    assert pd.isna(row["normalized_cips_file"])
    assert row["reason"] == "normalize failed: OSError: disk full"
    assert row["cips_protection"] == "ICCP"  # clean() still succeeded
    assert pd.isna(index.df.loc[0, "normalized_cips_file"])
    assert index.df.loc[0, "cips_protection"] == "ICCP"


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


def test_to_json(tmp_path):
    index_path = tmp_path / "index.xlsx"
    pd.DataFrame(
        {
            "Year": [2025, 2025],
            "Area": ["Jakarta", "Jakarta"],
            "Segment": [None, "RE Martadinata"],
            "Sub Segment": ["Pipa Servis Indonesia Power", "Sub"],
            "Diameter": [16, 10.5],
            "Length": [1.75, 2.0],
            "Province Code": [31, 31],
            "ACVG/DCVG": [None, None],
            "CIPS": ["CIPS - SACP 01.xlsx", None],
            "PCM": [None, None],
        }
    ).to_excel(index_path, index=False)

    out = tmp_path / "out"
    path = FileIndex(str(index_path)).to_json(str(out))
    assert path == os.path.join(str(out), "file_index.json")

    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    assert records == [
        {
            "id": 0,
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "segment": "Pipa Servis Indonesia Power",  # filled from Sub Segment
            "pipe_diameter": 16,
            "length": 1.75,
            "segment_code": "pipa-servis-indonesia-power-16",
            "cips_protection": None,  # check_cips_file has not run
            "normalized_cips_file": None,
        },
        {
            "id": 1,
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "segment": "RE Martadinata",
            "pipe_diameter": 10.5,
            "length": 2.0,  # length stays a float even when whole
            "segment_code": "re-martadinata-10-5",
            "cips_protection": None,
            "normalized_cips_file": None,
        },
    ]
    # == cannot tell 16 from 16.0, so check the JSON types explicitly
    assert type(records[0]["pipe_diameter"]) is int
    assert type(records[0]["year"]) is int
    assert type(records[1]["length"]) is float


def _write_value_index(path, rows: list[dict]) -> None:
    defaults = {
        "Year": 2024,
        "Area": "A",
        "Segment": "S",
        "Sub Segment": "SS",
        "Diameter": 4.0,
        "Length": 1.0,
        "Province Code": 31,
        "ACVG/DCVG": None,
        "CIPS": None,
        "PCM": None,
    }
    pd.DataFrame([{**defaults, **row} for row in rows]).to_excel(path, index=False)


def test_empty_area_raises_with_excel_rows(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(path, [{}, {"Area": None}, {"Area": "  "}])
    with pytest.raises(ValueError, match=r"'Area' empty at Excel rows \[3, 4\]"):
        FileIndex(str(path))


def test_segment_may_be_empty_only_with_sub_segment(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path,
        [
            {"Segment": None, "Sub Segment": "From Sub"},  # filled by fix()
            {"Segment": "Own", "Sub Segment": None},  # Sub Segment may be empty
        ],
    )
    index = FileIndex(str(path))
    assert index.fix().df["Segment"].tolist() == ["From Sub", "Own"]

    _write_value_index(path, [{}, {"Segment": None, "Sub Segment": None}])
    with pytest.raises(
        ValueError, match=r"'Segment' and 'Sub Segment' empty at Excel rows \[3\]"
    ):
        FileIndex(str(path))


def test_value_errors_are_combined_and_ignore_skipped_years(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path,
        [
            {"Year": 2021, "Area": None},  # row 2: skipped below
            {"Area": None},  # row 3
            {"Segment": None, "Sub Segment": None},  # row 4
        ],
    )
    with pytest.raises(ValueError) as error:
        FileIndex(str(path), skip_years=[2021])
    message = str(error.value)
    # row numbers still match the Excel file after skip_years removed row 2
    assert "'Area' empty at Excel rows [3]" in message
    assert "'Segment' and 'Sub Segment' empty at Excel rows [4]" in message

    # the 2021 row alone does not block loading when its year is skipped
    _write_value_index(path, [{"Year": 2021, "Area": None}, {}])
    assert FileIndex(str(path), skip_years=[2021]).df["Year"].tolist() == [2024]


def test_segment_and_diameter_must_be_unique(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path,
        [
            {"Segment": "Route", "Diameter": 16},  # row 2
            {"Segment": None, "Sub Segment": "Route", "Diameter": 16},  # row 3
            {"Segment": " Route ", "Diameter": 16},  # row 4: stripped -> Route
            {"Segment": "Route", "Diameter": 10},  # row 5: other diameter, OK
            {"Segment": "Other", "Sub Segment": "Route", "Diameter": 16},  # row 6
        ],
    )
    with pytest.raises(ValueError) as error:
        FileIndex(str(path))
    message = str(error.value)
    assert "'Segment' + 'Diameter' not unique" in message
    # the Sub Segment of row 6 is not used, because its Segment is filled
    assert "'Route' (16 in) at Excel rows [2, 3, 4]" in message
    assert "(10 in)" not in message  # row 5: other diameter
    assert "'Other'" not in message  # row 6: unique once its Segment is used

    # same route, different diameters: two pipes, allowed
    _write_value_index(
        path,
        [
            {"Segment": None, "Sub Segment": "Unisma - Pd Ungu", "Diameter": 16},
            {"Segment": None, "Sub Segment": "Unisma - Pd Ungu", "Diameter": 10},
        ],
    )
    index = FileIndex(str(path))
    assert index.fix().df["Segment"].tolist() == ["Unisma - Pd Ungu"] * 2


def test_duplicates_in_skipped_years_are_ignored(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path,
        [
            {"Year": 2021, "Segment": "Route"},
            {"Year": 2021, "Segment": "Route"},
            {"Year": 2024, "Segment": "Route"},
        ],
    )
    with pytest.raises(ValueError, match=r"at Excel rows \[2, 3, 4\]"):
        FileIndex(str(path))
    with pytest.raises(ValueError, match=r"at Excel rows \[2, 3\]"):
        FileIndex(str(path), skip_years=[2024])
    assert len(FileIndex(str(path), skip_years=[2021]).df) == 1
