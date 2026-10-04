import os
import json

import pandas as pd
import pytest

from corrosions.data.cips import CIPS
from corrosions.data.pcm import PCM
from corrosions.data.file_index import FileIndex, _length_km


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
    # set only for normalized files; the two shares add up to 100
    good = index.df.loc[0, ["cips_protected_percentage", "cips_unprotected_percentage"]]
    assert good.sum() == 100.0
    assert report.loc["good.xlsx", "protected_percentage"] == good.iloc[0]
    assert pd.isna(index.df.loc[2, "cips_protected_percentage"])  # clean failed
    # survey length in km, from the normalized CIPS' last Real Distance
    assert index.df.loc[0, "cips_length_km"] == report.loc["good.xlsx", "length_km"] > 0
    assert pd.isna(index.df.loc[6, "normalized_cips_file"])  # missing.xlsx
    assert pd.isna(index.df.loc[7, "cips_protection"])  # no CIPS filename

    # no PCM files in this index: every row lacks normalized_pcm_file
    records, excluded = _read_index_json(index.to_json(str(tmp_path / "out")))
    assert records == []
    assert excluded[0]["cips_protection"] == "ICCP"
    assert excluded[0]["cips_normalized_file"] == "2024-good.json"
    assert excluded[0]["missing"] == ["pcm_normalized_file"]
    assert excluded[2]["cips_file"] == "unknown.xlsx"
    assert excluded[2]["missing"] == ["cips_normalized_file", "pcm_normalized_file"]

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


def _read_index_json(path: str) -> tuple[list, list]:
    """Return the records of file_index.json and of the excluded file."""
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    excluded_path = os.path.join(
        os.path.dirname(path), FileIndex.EXCLUDED_JSON_FILENAME
    )
    with open(excluded_path, encoding="utf-8") as f:
        excluded = json.load(f)
    return records, excluded


def test_to_json(tmp_path):
    index_path = tmp_path / "index.xlsx"
    pd.DataFrame(
        {
            "Year": [2025, 2025, 2025, 2025],
            "Area": ["Jakarta"] * 4,
            "Segment": [None, "RE Martadinata", "Third", "Fourth"],
            "Sub Segment": ["Pipa Servis Indonesia Power", "Sub", "Sub", "Sub"],
            "Diameter": [16, 10.5, 8, 8],
            "Length": [1.75, 2.0, 1.0, 1.0],
            "Province Code": [31] * 4,
            "ACVG/DCVG": [None] * 4,
            "CIPS": ["CIPS - SACP 01.xlsx", "CIPS 02.xlsx", "CIPS 03.xlsx", None],
            "PCM": ["PCM 01.xlsx", "PCM 02.xlsx", None, None],
        }
    ).to_excel(index_path, index=False)

    index = FileIndex(str(index_path))
    out = tmp_path / "out"

    # before check_cips_file / check_pcm_file every row is excluded
    # sync=False: the normalized files named below do not exist
    path = index.to_json(str(out), sync=False)
    assert path == os.path.join(str(out), "file_index.json")
    assert index.sync_report is None
    records, excluded = _read_index_json(path)
    assert records == []
    assert len(excluded) == 4

    # what the two checks would merge into df
    index.df["cips_protection"] = ["SACP", "ICCP", "ICCP", None]
    index.df["cips_protected_percentage"] = [80.0, 66.67, 100.0, None]
    index.df["cips_unprotected_percentage"] = [20.0, 33.33, 0.0, None]
    index.df["normalized_cips_file"] = ["c1.json", "c2.json", "c3.json", None]
    index.df["normalized_pcm_file"] = ["p1.json", "p2.json", None, None]
    index.df["pcm_medium_to_poor"] = [10.0, 25.5, None, None]
    index.df["pcm_medium_to_high"] = [90.0, 74.5, None, None]

    records, excluded = _read_index_json(index.to_json(str(out), sync=False))
    assert records == [
        {
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "province_code": 31,
            "name": "Pipa Servis Indonesia Power",  # filled from Sub Segment
            "code": "pipa-servis-indonesia-power-16",
            "diameter": 16,
            "pipe_length": 1.75,
            "cips_protection": "SACP",
            "protected": 80.0,
            "unprotected": 20.0,
            "total_anomaly": None,
            "cips_normalized_file": "c1.json",
            "medium_to_poor": 10.0,
            "medium_to_high": 90.0,
            "pcm_normalized_file": "p1.json",
            "acvg_dcvg_normalized_file": None,
        },
        {
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "province_code": 31,
            "name": "RE Martadinata",
            "code": "re-martadinata-10-5",
            "diameter": 10.5,
            "pipe_length": 2.0,  # pipe_length stays a float
            "cips_protection": "ICCP",
            "protected": 66.67,
            "unprotected": 33.33,
            "total_anomaly": None,
            "cips_normalized_file": "c2.json",
            "medium_to_poor": 25.5,
            "medium_to_high": 74.5,
            "pcm_normalized_file": "p2.json",
            "acvg_dcvg_normalized_file": None,
        },
    ]
    # == cannot tell 16 from 16.0, so check the JSON types explicitly
    assert type(records[0]["diameter"]) is int
    assert type(records[0]["year"]) is int
    assert type(records[1]["pipe_length"]) is float

    # rows without both normalized files, no id, plus source files + missing
    assert excluded == [
        {
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "province_code": 31,
            "name": "Third",
            "code": "third-8",
            "diameter": 8,
            "pipe_length": 1.0,
            "cips_protection": "ICCP",
            "protected": 100.0,
            "unprotected": 0.0,
            "total_anomaly": None,
            "cips_normalized_file": "c3.json",
            "medium_to_poor": None,
            "medium_to_high": None,
            "pcm_normalized_file": None,
            "acvg_dcvg_normalized_file": None,
            "cips_file": "CIPS 03.xlsx",
            "pcm_file": None,
            "missing": ["pcm_normalized_file"],
        },
        {
            "year": 2025,
            "area": "Jakarta",
            "area_code": "jakarta-2025",
            "province_code": 31,
            "name": "Fourth",
            "code": "fourth-8",
            "diameter": 8,
            "pipe_length": 1.0,
            "cips_protection": None,
            "protected": None,
            "unprotected": None,
            "total_anomaly": None,
            "cips_normalized_file": None,
            "medium_to_poor": None,
            "medium_to_high": None,
            "pcm_normalized_file": None,
            "acvg_dcvg_normalized_file": None,
            "cips_file": None,
            "pcm_file": None,
            "missing": ["cips_normalized_file", "pcm_normalized_file"],
        },
    ]


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


def test_check_pcm_file_normalizes_and_merges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "data"
    os.makedirs(data_dir / "2025" / "PCM")
    n = 3
    pd.DataFrame(
        {
            "Index": list(range(1, n + 1)),
            "4Hz Current (A)": [0.5, 0.45, 0.2],
            "Int GPS Latitude": [-6.1, -6.101, -6.102],
            "Int GPS Longitude": [106.1] * n,
            "Comment (0-100)": ["S"] * n,
            "Gain (dB)": [30] * n,
            "Depth (m)": [1.2] * n,
        }
    ).to_excel(data_dir / "2025" / "PCM" / "PCM 01 good.xlsx", index=False)
    pd.DataFrame({"Int GPS Latitude": [-6.1]}).to_excel(
        data_dir / "2025" / "PCM" / "bad.xlsx", index=False
    )

    index_path = tmp_path / "index.xlsx"
    _write_value_index(
        index_path,
        [
            {"Year": 2025, "Segment": "A", "PCM": "PCM 01 good.xlsx"},
            {"Year": 2025, "Segment": "B", "PCM": "bad.xlsx"},
            {"Year": 2025, "Segment": "C", "PCM": "missing.xlsx"},
            {"Year": 2025, "Segment": "D", "PCM": None},
        ],
    )
    index = FileIndex(str(index_path))
    report = index.check_pcm_file(str(data_dir), n_jobs=1)
    report.index = [os.path.basename(p) for p in report["filepath"]]

    assert report.loc["PCM 01 good.xlsx", "normalized"]
    assert report.loc["PCM 01 good.xlsx", "normalized_pcm_file"] == "2025-pcm-01-good.json"
    assert os.path.isfile(
        tmp_path / "output" / "normalize" / "pcm" / "json" / "2025-pcm-01-good.json"
    )
    # clean() only uses the columns present, so bad.xlsx fails in normalize()
    assert not report.loc["bad.xlsx", "normalized"]
    assert report.loc["bad.xlsx", "reason"].startswith(
        "normalize failed: ValueError: Cannot normalize"
    )
    assert "Int GPS Longitude" in report.loc["bad.xlsx", "reason"]
    assert not report.loc["missing.xlsx", "normalized"]
    assert report["normalized"].dtype == bool

    assert index.df["normalized_pcm_file"].tolist()[0] == "2025-pcm-01-good.json"
    assert index.df["normalized_pcm_file"].isna().tolist()[1:] == [True, True, True]
    # set only for the normalized file; the two shares add up to 100
    good = index.df.loc[0, ["pcm_medium_to_poor", "pcm_medium_to_high"]]
    assert good.sum() == 100.0
    assert report.loc["PCM 01 good.xlsx", "medium_to_high_percentage"] == good.iloc[1]
    assert index.df["pcm_medium_to_high"].isna().tolist()[1:] == [True, True, True]
    assert index.df.loc[0, "pcm_length_km"] == report.loc["PCM 01 good.xlsx", "length_km"] > 0

    records = json.loads(
        open(index.to_json(str(tmp_path / "out")), encoding="utf-8").read()
    )
    assert records == []  # no CIPS files in this index
    with open(tmp_path / "out" / "file_index_excluded.json", encoding="utf-8") as f:
        excluded = json.load(f)
    assert excluded[0]["pcm_normalized_file"] == "2025-pcm-01-good.json"
    assert excluded[0]["missing"] == ["cips_normalized_file"]
    assert excluded[3]["pcm_file"] is None


def test_to_json_syncs_the_normalized_files(tmp_path, monkeypatch):
    # CIPS/PCM normalize() and SyncData both use <cwd>/output/normalize
    monkeypatch.chdir(tmp_path)
    east_to_west = [106.102, 106.101, 106.100]
    pd.DataFrame(
        {
            "Latitude": [-6.1] * 3,
            "Longitude": east_to_west,
            "Comment": [""] * 3,
            "DCP/Feature/DCVG Anomaly": [""] * 3,
            "On Voltage": [-1.0, -1.1, -0.8],
            "Off Voltage": [-0.9, -0.95, -0.7],
        }
    ).to_excel(tmp_path / "CIPS - ICCP a.xlsx", index=False)
    pd.DataFrame(
        {
            "4Hz Current (A)": [0.5, 0.45, 0.2],
            "Int GPS Latitude": [-6.1] * 3,
            "Int GPS Longitude": east_to_west,
            "Comment (0-100)": ["TP 1", None, None],
            "Gain (dB)": [30] * 3,
            "Depth (m)": [1.2] * 3,
        }
    ).to_excel(tmp_path / "PCM a.xlsx", index=False)
    cips = CIPS(str(tmp_path / "CIPS - ICCP a.xlsx"), year=2024).clean().normalize()
    pcm = PCM(str(tmp_path / "PCM a.xlsx"), year=2024).clean().normalize()

    index_path = tmp_path / "index.xlsx"
    _write_value_index(index_path, [{"Segment": "Seg A"}])
    index = FileIndex(str(index_path))
    # what check_cips_file / check_pcm_file would merge into df
    index.df["cips_protection"] = ["ICCP"]
    index.df["normalized_cips_file"] = [os.path.basename(cips.normalize_json_filepath)]
    index.df["normalized_pcm_file"] = [os.path.basename(pcm.normalize_json_filepath)]

    index.to_json(str(tmp_path / "out"))

    report = index.sync_report
    assert report is not None
    assert report.iloc[0]["cips_reversed"] and report.iloc[0]["pcm_reversed"]
    with open(cips.normalize_json_filepath, encoding="utf-8") as f:
        assert json.load(f)[0]["longitude"] == 106.1  # now starts at the west end
    excel = pd.read_excel(pcm.normalize_excel_filepath)
    assert excel["Int GPS Longitude"].iloc[0] == 106.1
    # reversing keeps the same reading pairs: the condition shares are unchanged
    high = 100 * (excel["Condition"] == "Medium to High").mean()
    assert round(high, 2) == pcm.medium_to_high_percentage


def test_assign_acvg_dcvg_updates_the_written_json(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path, [{"Segment": "One"}, {"Segment": "Two"}, {"Segment": "Three"}]
    )
    index = FileIndex(str(path))
    index.df["normalized_cips_file"] = ["c1.json", "c2.json", None]
    index.df["normalized_pcm_file"] = ["p1.json", "p2.json", None]
    out = tmp_path / "out"
    records, excluded = _read_index_json(index.to_json(str(out), sync=False))
    assert [r["acvg_dcvg_normalized_file"] for r in records] == [None, None]

    # written before the ACVG/DCVG step: updated in place, by segment
    index.assign_acvg_dcvg(
        {1: "2024-acvg-two.json", 2: "2024-acvg-three.json"},
        str(out),
        counts={1: 4, 2: 7},
    )

    records, excluded = _read_index_json(str(out / FileIndex.JSON_FILENAME))
    assert [r["acvg_dcvg_normalized_file"] for r in records] == [
        None,
        "2024-acvg-two.json",
    ]
    assert [r["total_anomaly"] for r in records] == [None, 4]
    # same key order as the records to_json writes
    assert list(records[0]) == list(index._record(index.df.iloc[0]))
    assert excluded[0]["acvg_dcvg_normalized_file"] == "2024-acvg-three.json"
    assert excluded[0]["total_anomaly"] == 7
    # the excluded file's own keys stay last
    assert list(excluded[0])[-3:] == ["cips_file", "pcm_file", "missing"]
    # not a required key: the excluded row still misses only CIPS/PCM
    assert excluded[0]["missing"] == ["cips_normalized_file", "pcm_normalized_file"]

    # later to_json calls write it from df, the same way
    rewritten, _ = _read_index_json(index.to_json(str(out), sync=False))
    assert rewritten == records


def test_area_records_summarize_per_area_code():
    segment = {
        "year": 2025,
        "area": "Jakarta",
        "area_code": "jakarta-2025",
        "province_code": 31,
    }
    records = [
        {**segment, "pipe_length": 1.75, "protected": 80.0, "unprotected": 20.0,
         "medium_to_poor": 10.0, "medium_to_high": 90.0, "total_anomaly": 3},
        {**segment, "pipe_length": 2.0, "protected": 66.67, "unprotected": 33.33,
         "medium_to_poor": 25.5, "medium_to_high": 74.5, "total_anomaly": None},
        {"year": 2024, "area": "Bogor", "area_code": "bogor-2024",
         "province_code": 32, "pipe_length": 0.5, "protected": None,
         "unprotected": None, "medium_to_poor": 0.0, "medium_to_high": 100.0,
         "total_anomaly": 2},
    ]

    assert FileIndex.area_records(records) == [
        {
            "name": "Jakarta",
            "code": "jakarta-2025",
            "year": 2025,
            "total_length": 3.75,
            # simple mean of the segments, 2 decimals
            "protected": 73.34,  # (80 + 66.67) / 2 = 73.335
            "unprotected": 26.66,
            "medium_to_poor": 17.75,
            "medium_to_high": 82.25,
            "total_anomaly": 3,  # null counts as 0
            "province_code": 31,
        },
        {
            "name": "Bogor",
            "code": "bogor-2024",
            "year": 2024,
            "total_length": 0.5,
            "protected": None,  # no value to average
            "unprotected": None,
            "medium_to_poor": 0.0,
            "medium_to_high": 100.0,
            "total_anomaly": 2,
            "province_code": 32,
        },
    ]


def test_area_json_is_written_and_follows_assign_acvg_dcvg(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(path, [{"Segment": "One"}, {"Segment": "Two"}])
    index = FileIndex(str(path))
    index.df["normalized_cips_file"] = ["c1.json", "c2.json"]
    index.df["normalized_pcm_file"] = ["p1.json", "p2.json"]
    index.df["cips_protected_percentage"] = [80.0, 60.0]
    index.df["cips_unprotected_percentage"] = [20.0, 40.0]
    out = tmp_path / "out"
    index.to_json(str(out), sync=False)

    with open(out / FileIndex.AREA_JSON_FILENAME, encoding="utf-8") as f:
        (area,) = json.load(f)
    assert (area["code"], area["total_length"]) == ("a-2024", 2.0)
    assert (area["protected"], area["total_anomaly"]) == (70.0, 0)

    # the counts arrive after to_json: area.json is rebuilt with them
    index.assign_acvg_dcvg({0: "a.json", 1: "b.json"}, str(out), counts={0: 4, 1: 5})
    with open(out / FileIndex.AREA_JSON_FILENAME, encoding="utf-8") as f:
        (area,) = json.load(f)
    assert area["total_anomaly"] == 9


def test_pipe_length_falls_back_to_the_surveyed_length(tmp_path):
    path = tmp_path / "index.xlsx"
    _write_value_index(
        path,
        [
            {"Segment": "Given", "Length": 1.5},
            {"Segment": "From CIPS", "Length": None},
            {"Segment": "From PCM", "Length": None},
            {"Segment": "Unknown", "Length": None},
        ],
    )
    index = FileIndex(str(path))
    # what check_cips_file / check_pcm_file merge into df (km, 3 decimals)
    index.df["cips_length_km"] = [9.9, 2.345, None, None]
    index.df["pcm_length_km"] = [9.9, 9.9, 0.812, None]

    lengths = [index._record(row)["pipe_length"] for _, row in index.df.iterrows()]

    # Length wins; else the CIPS survey length; else the PCM one
    assert lengths == [1.5, 2.345, 0.812, None]


def test_length_km_is_the_last_real_distance():
    df = pd.DataFrame({"Real Distance": [0.0, 1200.0, 2345.6789]})
    assert _length_km(df) == 2.346
    assert _length_km(pd.DataFrame({"Real Distance": []})) is None
