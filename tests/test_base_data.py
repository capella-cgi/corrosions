import os

import numpy as np
import pandas as pd
import pytest

from corrosions.data.cips import CIPS
from corrosions.data.pcm import PCM


def _write_excel(path, data: dict) -> str:
    pd.DataFrame(data).to_excel(path, index=False)
    return str(path)


@pytest.fixture
def pcm_file(tmp_path):
    return _write_excel(
        tmp_path / "segment-01.xlsx",
        {
            # row 2 is blank; trailing blank rows are not read back from Excel
            "Index": [1, 2, np.nan, 3, 4],
            "4Hz Current (A)": [0.5, 0.6, np.nan, np.nan, 0.7],
            "Int GPS Latitude": [-6.1, -6.2, np.nan, -6.3, -6.1],
            "Int GPS Longitude": [106.1, 106.2, np.nan, 106.3, 106.1],
            "Ext GPS Latitude": [np.nan] * 5,
            "Ext GPS Longitude": [np.nan] * 5,
            "Survey name (0-100)": ["a", "b", np.nan, "c", "d"],
            "Gain (dB)": [10, 20, np.nan, 30, "bad"],
        },
    )


def test_pcm_loads_and_coerces(pcm_file, tmp_path):
    pcm = PCM(pcm_file, year=2024, output_dir=str(tmp_path / "out"))
    assert len(pcm.df) == 5
    assert pd.api.types.is_numeric_dtype(pcm.df["Gain (dB)"])


def test_pcm_check_returns_self_and_report(pcm_file, tmp_path):
    pcm = PCM(pcm_file, year=2024, output_dir=str(tmp_path / "out"))
    assert pcm.check() is pcm
    assert pcm.report["filepath"] == pcm_file
    assert pcm.report["n_missing"] == 0
    # rows 0 and 4 share lat/lon
    assert pcm.report["n_duplicates"] == 2
    assert pcm.report["is_valid"] is False


def test_pcm_check_missing_columns(tmp_path):
    path = _write_excel(
        tmp_path / "partial.xlsx",
        {"Int GPS Latitude": [-6.1], "Int GPS Longitude": [106.1]},
    )
    report = PCM(path, year=2024, output_dir=str(tmp_path / "out")).check().report
    assert report["n_missing"] == 6
    assert "Gain (dB)" in report["missing_columns"]


def test_pcm_clean_drops_incomplete_rows(pcm_file, tmp_path):
    pcm = PCM(pcm_file, year=2024, output_dir=str(tmp_path / "out")).clean()
    # row 2 (all NaN), row 3 (NaN current), row 4 ("bad" gain) are dropped
    assert pcm.df.index.tolist() == [0, 1]


def test_pcm_clean_raises_when_empty(tmp_path):
    path = _write_excel(
        tmp_path / "empty.xlsx",
        {
            "4Hz Current (A)": [np.nan],
            "Int GPS Latitude": [-6.1],
            "Int GPS Longitude": [106.1],
            "Gain (dB)": [10],
        },
    )
    with pytest.raises(ValueError, match="empty"):
        PCM(path, year=2024, output_dir=str(tmp_path / "out")).clean()


def test_pcm_full_chain(pcm_file, tmp_path):
    out = tmp_path / "out"
    pcm = PCM(pcm_file, year=2024, output_dir=str(out)).check().clean().save()
    expected = os.path.join(str(out), "cleaned", "2024", "PCM", "segment-01.xlsx")
    assert pcm.cleaned_path == expected
    assert os.path.isfile(expected)
    assert len(pd.read_excel(expected)) == 2
    assert pcm.report["n_duplicates"] == 2


def _cips_base() -> dict:
    return {
        "Data No": [1, 2, 3],
        "Latitude": [-6.1, -6.2, -6.3],
        "Longitude": [106.1, 106.2, 106.3],
        "Altitude": [10.0, 11.0, 12.0],
        "Comment": ["", "", ""],
        "DCP/Feature/DCVG Anomaly": ["", "", ""],
    }


def test_cips_iccp_voltage_negated(tmp_path):
    path = _write_excel(
        tmp_path / "iccp.xlsx",
        {**_cips_base(), "On Voltage": [1.1, 1.2, 1.3], "Off Voltage": [0.9, 1.0, 1.1]},
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "ICCP"
    assert cips.df["Voltage"].tolist() == [-1.1, -1.2, -1.3]
    assert cips.df["Off Voltage"].tolist() == [-0.9, -1.0, -1.1]


def test_cips_sacp_positive_voltage_negated(tmp_path):
    path = _write_excel(
        tmp_path / "sacp.xlsx", {**_cips_base(), "Voltage": [0.9, 1.0, 1.1]}
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.df["Voltage"].tolist() == [-0.9, -1.0, -1.1]


def test_cips_sacp(tmp_path):
    path = _write_excel(
        tmp_path / "sacp.xlsx", {**_cips_base(), "Voltage": [-0.9, np.nan, -1.0]}
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "SACP"
    assert cips.df["Voltage"].tolist() == [-0.9, -1.0]
    assert cips.df["On Voltage"].isna().all()


def test_cips_without_voltage_raises(tmp_path):
    path = _write_excel(tmp_path / "bad.xlsx", _cips_base())
    with pytest.raises(ValueError, match="Expected either ICCP"):
        CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()


def test_cips_full_chain(tmp_path):
    out = tmp_path / "out"
    path = _write_excel(
        tmp_path / "iccp.xlsx",
        {**_cips_base(), "On Voltage": [-1.1, -1.2, -1.3], "Off Voltage": [0, 0, 0]},
    )
    cips = CIPS(path, year=2024, output_dir=str(out)).check().clean().save()
    assert cips.report["is_valid"] is True
    assert cips.cleaned_path == os.path.join(
        str(out), "cleaned", "2024", "CIPS", "iccp.xlsx"
    )
    assert os.path.isfile(cips.cleaned_path)


def _write_sheets(path, sheets: dict[str, dict]) -> str:
    with pd.ExcelWriter(path) as writer:
        for name, data in sheets.items():
            pd.DataFrame(data).to_excel(writer, sheet_name=name, index=False)
    return str(path)


def _iccp() -> dict:
    return {**_cips_base(), "On Voltage": [-1.1, -1.2, -1.3], "Off Voltage": [0, 0, 0]}


def test_pcm_uses_first_sheet(pcm_file, tmp_path):
    pcm = PCM(pcm_file, year=2024, output_dir=str(tmp_path / "out")).check()
    assert pcm.sheet_name == 0
    assert pcm.report["sheet_name"] == 0


def test_cips_skips_non_data_sheets(tmp_path):
    path = _write_sheets(
        tmp_path / "mixed.xlsx",
        {
            "Grafik": {},
            "DCP Data": {"Data No": [1], "DCP/Feature/Anomaly": ["TS"], "Latitude": [-6.1]},
            "Survey Info": {"Survey Type": ["Trigger CIS"]},
            "Data": _iccp(),
        },
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).check()
    assert cips.sheet_name == "Data"
    assert cips.report["sheet_name"] == "Data"
    assert len(cips.df) == 3


def test_cips_prefers_data_over_copies(tmp_path):
    raw = {**_iccp(), "On Voltage": [-0.01, -0.02, -0.03]}
    path = _write_sheets(
        tmp_path / "copies.xlsx", {"Sheet1": _iccp(), "Raw Data": raw, "Data": _iccp()}
    )
    assert CIPS.find_sheet(path) == "Data"


def test_cips_finds_segment_named_sheet(tmp_path):
    path = _write_sheets(
        tmp_path / "named.xlsx",
        {"Grafik": {}, "Indomaret Ancol - Pluit Kr Raya": _iccp()},
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.sheet_name == "Indomaret Ancol - Pluit Kr Raya"
    assert cips.protection == "ICCP"


def test_cips_no_data_sheet_raises(tmp_path):
    path = _write_sheets(
        tmp_path / "none.xlsx",
        {"Grafik": {}, "Survey Info": {"Survey Type": ["Trigger CIS"]}},
    )
    with pytest.raises(ValueError, match="No CIPS data sheet"):
        CIPS(path, year=2024, output_dir=str(tmp_path / "out"))


def test_cips_sheet_columns_subset_of_required():
    assert set(CIPS.SHEET_COLUMNS) <= set(CIPS.REQUIRED_COLUMNS)


def _cips_2022(**extra) -> dict:
    data = {
        "Index": [1, 2, 3],
        "Latitude": [-6.1, -6.2, -6.3],
        "Longitude": [106.1, 106.2, 106.3],
        "Altitude": [10.0, 11.0, 12.0],
        "DCP/Feature/DCVG Anomaly": ["", "", ""],
        "On Potential (mV)": [1100, 1200, 1300],
        "Voltage (V)": [1.1, 1.2, 1.3],
        "Off Voltage (V)": [0.9, 1.0, 1.1],
    }
    data.update(extra)
    return data


def test_cips_fix_renames_and_adds_comment(tmp_path):
    path = _write_excel(tmp_path / "CIPS - ICCP 2022.xlsx", _cips_2022())
    cips = CIPS(path, year=2022, output_dir=str(tmp_path / "out"))
    assert cips.fix() is cips
    cols = list(cips.df.columns)
    assert "Index" in cols and "Data No" not in cols  # Index is not renamed
    assert "Voltage" in cols and "Off Voltage" in cols
    assert "On Potential (mV)" in cols  # mV columns untouched
    assert (cips.df["Comment"] == "").all()
    assert cips.check().report["is_valid"] is True


def test_cips_fix_runs_for_every_year(tmp_path):
    path = _write_excel(tmp_path / "CIPS - ICCP 2021.xlsx", _cips_2022())
    cips = CIPS(path, year=2021, output_dir=str(tmp_path / "out")).fix()
    assert cips.fixed is True
    assert "Voltage" in cips.df.columns
    assert (cips.df["Comment"] == "").all()


def test_cips_check_flags_missing_voltage(tmp_path):
    data = {**_cips_base(), "-mV On": [1, 2, 3]}
    path = _write_excel(tmp_path / "mv.xlsx", data)
    report = CIPS(path, year=2021, output_dir=str(tmp_path / "out")).check().report
    assert report["has_voltage"] is False
    assert report["n_missing"] == 0
    assert report["is_valid"] is False
    assert "has_altitude" not in report


def test_cips_voltage_off_voltage_iccp_by_filename(tmp_path):
    path = _write_excel(tmp_path / "CIPS - ICCP 07 BKS 16 in A - B.xlsx", _cips_2022())
    cips = CIPS(path, year=2022, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "ICCP"
    assert cips.df["On Voltage"].tolist() == [1.1, 1.2, 1.3]
    assert cips.df["Voltage"].tolist() == [-1.1, -1.2, -1.3]
    assert cips.df["Off Voltage"].tolist() == [-0.9, -1.0, -1.1]


def test_cips_voltage_off_voltage_sacp_by_filename(tmp_path):
    path = _write_excel(tmp_path / "CIPS - SACP TNG 8 in A - B.xlsx", _cips_2022())
    cips = CIPS(path, year=2022, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "SACP"
    assert cips.df["Voltage"].tolist() == [-1.1, -1.2, -1.3]
    assert cips.df["Off Voltage"].isna().all()


def test_cips_voltage_off_voltage_unknown_filename_raises(tmp_path):
    path = _write_excel(tmp_path / "segment.xlsx", _cips_2022())
    with pytest.raises(ValueError, match="Cannot tell ICCP from SACP"):
        CIPS(path, year=2022, output_dir=str(tmp_path / "out")).clean()


def test_cips_clean_drops_zero_empty_and_duplicate_coordinates(tmp_path):
    data = {
        "Data No": [1, 2, 3, 4, 5, 6, 7],
        "Latitude": [-6.1, -6.1, 0.0, -6.3, np.nan, -6.5, -6.6],
        "Longitude": [106.1, 106.1, 106.2, 0.0, 106.4, np.nan, 106.6],
        "Altitude": [10.0] * 7,
        "Comment": [""] * 7,
        "DCP/Feature/DCVG Anomaly": [""] * 7,
        "Voltage": [-0.91, -0.92, -0.93, -0.94, -0.95, -0.96, -0.97],
    }
    path = _write_excel(tmp_path / "CIPS - SACP dup.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).check()

    # duplicates are counted but do not invalidate a CIPS file
    assert cips.report["n_duplicates"] == 2
    assert cips.report["is_valid"] is True

    cips.clean()
    # row 1 duplicate of row 0, row 2 lat 0, row 3 lon 0, rows 4-5 empty coords
    assert cips.df["Data No"].tolist() == [1, 7]
    assert cips.df["Voltage"].tolist() == [-0.91, -0.97]


def test_cips_clean_raises_when_only_zero_coordinates(tmp_path):
    data = {**_cips_base(), "Voltage": [-0.9, -1.0, -1.1]}
    data["Latitude"] = [0.0, 0.0, 0.0]
    path = _write_excel(tmp_path / "CIPS - SACP zero.xlsx", data)
    with pytest.raises(ValueError, match="empty"):
        CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()


def test_cips_valid_without_data_no_and_altitude(tmp_path):
    data = {**_cips_base(), "Voltage": [-0.9, -1.0, -1.1]}
    del data["Data No"], data["Altitude"]
    path = _write_excel(tmp_path / "CIPS - SACP minimal.xlsx", data)
    cips = CIPS(path, year=2025, output_dir=str(tmp_path / "out")).fix().check()
    assert "Data No" not in cips.df.columns
    assert "Altitude" not in cips.df.columns
    assert cips.report["is_valid"] is True


def test_pcm_clean_drops_zero_and_duplicate_coordinates(tmp_path):
    path = _write_excel(
        tmp_path / "pcm-gps.xlsx",
        {
            "Index": [1, 2, 3, 4, 5],
            "4Hz Current (A)": [0.5, 0.6, 0.7, 0.8, 0.9],
            "Int GPS Latitude": [-6.1, -6.1, 0.0, -6.4, -6.5],
            "Int GPS Longitude": [106.1, 106.1, 0.0, 0.0, 106.5],
            "Gain (dB)": [10, 20, 30, 40, 50],
        },
    )
    pcm = PCM(path, year=2024, output_dir=str(tmp_path / "out")).check()
    assert pcm.report["n_duplicates"] == 2  # rows 0 and 1 share (-6.1, 106.1)
    pcm.clean()
    # row 1 duplicate of row 0; rows 2 and 3 have a zero coordinate
    assert pcm.df["Index"].tolist() == [1, 5]
    assert pcm.check().report["n_duplicates"] == 0


def _cips_track(latitudes: list[float]) -> dict:
    n = len(latitudes)
    return {
        "Latitude": latitudes,
        "Longitude": [106.1] * n,
        "Comment": [""] * n,
        "DCP/Feature/DCVG Anomaly": [""] * n,
        "Voltage": [-0.9] * n,
    }


def test_cips_normalize_distances(tmp_path):
    # 0.001 degree of latitude apart -> ~111.195 m per step
    path = _write_excel(
        tmp_path / "CIPS - SACP track.xlsx", _cips_track([-6.1, -6.101, -6.102])
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.normalize() is cips
    assert cips.df["Distance"].tolist() == pytest.approx([0.0, 111.195, 111.195], abs=1e-3)
    assert cips.df["Real Distance"].tolist() == pytest.approx(
        [0.0, 111.195, 222.390], abs=1e-3
    )


def test_cips_normalize_after_clean_leaves_index_gaps(tmp_path):
    # row 0: lat 0 (dropped), row 2: duplicate of row 1 (dropped)
    path = _write_excel(
        tmp_path / "CIPS - SACP gaps.xlsx",
        _cips_track([0.0, -6.1, -6.1, -6.101, -6.102]),
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert list(cips.df.index) == [1, 3, 4]

    cips.normalize()
    assert list(cips.df.index) == [1, 3, 4]
    assert cips.df["Distance"].tolist() == pytest.approx([0.0, 111.195, 111.195], abs=1e-3)
    assert cips.df["Real Distance"].iloc[-1] == pytest.approx(222.390, abs=1e-3)


def test_cips_normalize_saves_excel_and_json(tmp_path):
    data = {**_cips_track([-6.1, -6.101])}
    del data["Voltage"]
    data["On Voltage"] = [-1.0, -1.0]
    data["Off Voltage"] = [-0.9, -0.9]
    path = _write_excel(tmp_path / "CIPS - ICCP cols.xlsx", data)
    out = tmp_path / "out"
    cips = CIPS(path, year=2024, output_dir=str(out)).clean().normalize()
    assert cips.normalized is True

    # Excel: original column names, no index column
    assert cips.normalize_excel_filepath == str(
        out / "normalize" / "cips" / "excel" / "2024-cips-iccp-cols.xlsx"
    )
    excel = pd.read_excel(cips.normalize_excel_filepath)
    assert list(excel.columns) == list(cips.df.columns)
    assert "Unnamed: 0" not in excel.columns
    assert {"Distance", "Real Distance", "Condition"} <= set(excel.columns)

    # JSON: one record per row, snake_case column names
    assert cips.normalize_json_filepath == str(
        out / "normalize" / "cips" / "json" / "2024-cips-iccp-cols.json"
    )
    records = pd.read_json(cips.normalize_json_filepath, orient="records")
    assert len(records) == 2
    assert set(records.columns) == {
        "latitude",
        "longitude",
        "voltage",
        "on_voltage",
        "off_voltage",
        "protection",
        "comment",
        "dcp_feature_dcvg_anomaly",
        "distance",
        "real_distance",
        "condition",
    }


def test_cips_normalize_before_clean_raises(tmp_path):
    path = _write_excel(tmp_path / "CIPS - SACP raw.xlsx", _cips_track([-6.1, -6.101]))
    with pytest.raises(RuntimeError, match="Run clean"):
        CIPS(path, year=2024, output_dir=str(tmp_path / "out")).normalize()


def test_cips_normalize_after_fix_only_raises(tmp_path):
    # fix() alone does not run _fix_voltage, so a SACP file has no Off Voltage
    path = _write_excel(tmp_path / "CIPS - SACP fixed.xlsx", _cips_track([-6.1, -6.101]))
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).fix()
    assert cips.cleaned is False
    with pytest.raises(RuntimeError, match="Run clean"):
        cips.normalize()


def test_cips_failed_clean_leaves_cleaned_false(tmp_path):
    path = _write_excel(tmp_path / "segment.xlsx", _cips_2022())
    cips = CIPS(path, year=2022, output_dir=str(tmp_path / "out"))
    with pytest.raises(ValueError, match="Cannot tell ICCP from SACP"):
        cips.clean()
    assert cips.cleaned is False
    with pytest.raises(RuntimeError, match="Run clean"):
        cips.normalize()


def test_cips_normalize_condition_sacp_uses_voltage(tmp_path):
    data = _cips_track([-6.1, -6.101, -6.102, -6.103, -6.104])
    data["Voltage"] = [-0.80, -0.85, -1.0, -1.2, -1.5]
    path = _write_excel(tmp_path / "CIPS - SACP cond.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean().normalize()
    assert cips.df["Condition"].tolist() == [
        "UNPROTECTED",
        "PROTECTED",
        "PROTECTED",
        "OVER PROTECTED",
        "OVER PROTECTED",
    ]


def test_cips_normalize_condition_iccp_uses_off_voltage(tmp_path):
    data = _cips_track([-6.1, -6.101, -6.102])
    del data["Voltage"]
    # ON readings are all protected; OFF readings decide the condition
    data["On Voltage"] = [-1.0, -1.0, -1.0]
    data["Off Voltage"] = [-0.7, -0.9, -1.3]
    path = _write_excel(tmp_path / "CIPS - ICCP cond.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean().normalize()
    assert cips.df["protection"].tolist() == ["ICCP"] * 3
    assert cips.df["Condition"].tolist() == [
        "UNPROTECTED",
        "PROTECTED",
        "OVER PROTECTED",
    ]


def _cips_iccp_track(on: list[float], off: list[float]) -> dict:
    data = _cips_track([-6.1 - i * 0.001 for i in range(len(on))])
    del data["Voltage"]
    data["On Voltage"] = on
    data["Off Voltage"] = off
    return data


def test_cips_clean_iccp_drops_rows_missing_on_or_off_voltage(tmp_path):
    data = _cips_iccp_track(
        on=[-1.0, -1.1, np.nan, -1.3],
        off=[-0.9, np.nan, -0.95, -1.0],
    )
    path = _write_excel(tmp_path / "CIPS - ICCP gaps.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "ICCP"
    assert list(cips.df.index) == [0, 3]
    assert cips.df["Off Voltage"].notna().all()
    assert cips.df["On Voltage"].notna().all()


def test_cips_clean_iccp_without_off_voltage_raises(tmp_path):
    data = _cips_iccp_track(on=[-1.0, -1.1], off=[np.nan, np.nan])
    path = _write_excel(tmp_path / "CIPS - ICCP no off.xlsx", data)
    with pytest.raises(ValueError, match="empty"):
        CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()


def test_cips_clean_sacp_keeps_rows_without_on_off_voltage(tmp_path):
    data = _cips_track([-6.1, -6.101, -6.102])
    data["Voltage"] = [-0.9, np.nan, -1.0]
    path = _write_excel(tmp_path / "CIPS - SACP keep.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.protection == "SACP"
    assert list(cips.df.index) == [0, 2]
    assert cips.df["Off Voltage"].isna().all()


def test_cips_iccp_sign_ignores_leading_empty_readings(tmp_path):
    data = _cips_iccp_track(on=[np.nan, 1.0, 1.0], off=[np.nan, 0.9, 1.3])
    path = _write_excel(tmp_path / "CIPS - ICCP leading nan.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.df["Voltage"].tolist() == [-1.0, -1.0]
    assert cips.df["Off Voltage"].tolist() == [-0.9, -1.3]
    assert cips.normalize().df["Condition"].tolist() == ["PROTECTED", "OVER PROTECTED"]


def test_cips_sacp_sign_ignores_leading_empty_readings(tmp_path):
    data = _cips_track([-6.1, -6.101, -6.102])
    data["Voltage"] = [np.nan, 0.9, 1.0]
    path = _write_excel(tmp_path / "CIPS - SACP leading nan.xlsx", data)
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out")).clean()
    assert cips.df["Voltage"].tolist() == [-0.9, -1.0]


def test_normalize_filename_drops_extension(tmp_path):
    path = _write_excel(
        tmp_path / "CIPS - SACP Segmen BKS 10 inch (A - B 4.9 km).xlsx",
        _cips_track([-6.1, -6.101]),
    )
    cips = CIPS(path, year=2024, output_dir=str(tmp_path / "out"))
    stem = "2024-cips-sacp-segmen-bks-10-inch-a-b-4-9-km"
    assert os.path.basename(cips.normalize_excel_filepath) == f"{stem}.xlsx"
    assert os.path.basename(cips.normalize_json_filepath) == f"{stem}.json"
