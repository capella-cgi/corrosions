import os
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from slugify import slugify

from corrosions.data.acvg_dcvg import AcvgDcvg, AcvgDcvgFile

# Header as in the workbooks, incl. the trailing spaces of 2023/2025 exports
HEADER = [
    "No ",
    "Segmen",
    "Dia (inch)",
    "Lokasi Anomali",
    "Kondisi Permukaan ",
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


def _anomaly(segment, dia, lat, lon, year=2024, **extra) -> dict:
    row = dict.fromkeys(HEADER)
    row.update(
        {
            "No ": 1,
            "Segmen": segment,
            "Dia (inch)": dia,
            "Lokasi Anomali": "depan rumah",
            "Kondisi Permukaan ": "Aspal",
            "%drop PCM": "61.80%",
            "On Potential (volt)": "-1.1",
            "Off Potential (volt)": "N/A",
            "Tgl DCVG": datetime(year, 5, 20),
            "Tgl ACVG": datetime(year, 5, 11),
            "Latitude": lat,
            "Longitude": lon,
            "IR Drop (%)": 2.5,
            "Kedalaman Pipa (m)": 1.2,
            "Hasil ACVG (dB)": "not detected",
        }
    )
    row.update(extra)
    return row


def _write_workbook(path, sheets: dict[str, list[dict]]) -> None:
    with pd.ExcelWriter(path) as writer:
        for name, rows in sheets.items():
            pd.DataFrame(rows, columns=HEADER if rows else None).to_excel(
                writer, sheet_name=name, index=False
            )


def _write_track(normalize_dir, year: int, cips: str, lat: float, lons) -> Path:
    """Write a normalized CIPS JSON with the name CIPS.normalize() gives it.

    Reading ``i`` is at ``real_distance`` ``i * 100``; even readings are
    ``PROTECTED``, odd ones ``UNPROTECTED``.
    """
    folder = Path(normalize_dir) / "cips" / "json"
    os.makedirs(folder, exist_ok=True)
    name = f"{year}-{slugify(os.path.splitext(cips)[0])}.json"
    records = [
        {
            "latitude": lat,
            "longitude": float(lon),
            "real_distance": i * 100.0,
            "condition": "UNPROTECTED" if i % 2 else "PROTECTED",
        }
        for i, lon in enumerate(lons)
    ]
    with open(folder / name, "w", encoding="utf-8") as f:
        json.dump(records, f)
    return folder / name


@pytest.fixture
def setup(tmp_path):
    """ACVG index + workbooks for 2022 and 2024, a file index and CIPS tracks."""
    data_dir = tmp_path / "data"
    os.makedirs(data_dir)
    pd.DataFrame(
        {"Year": [2022, 2024], "Filename": ["Rekap 2022.xlsx", "Rekap 2024.xlsx"]}
    ).to_excel(tmp_path / "acvg-index.xlsx", index=False)

    _write_workbook(
        data_dir / "Rekap 2024.xlsx",
        {
            "Jakarta": [
                # name match with the index (case and punctuation ignored)
                _anomaly("Pipa Servis Indonesia Power", 16, -6.10, 106.80),
                _anomaly("Pipa Servis Indonesia Power", 16, "6°06'10.0\"S", 106.801),
                # another name, but it lies on the track of "Cawang - Kompor"
                _anomaly("Cawang Kompor 2", 10, -6.200, 106.9001),
                # far from every track: unmatched
                _anomaly("Somewhere Else", 8, -7.5, 110.0),
                # copied from another year: dropped
                _anomaly("Offtake Serpong", 16, -6.16, 106.65, year=2023),
                # notes under the table: no Segmen, dropped
                {"No ": "Tim Aldi 4", "Segmen": None},
            ],
            "Contoh format Gabungan": [_anomaly("Template", 4, 0, 0)],
        },
    )
    # 2022: every anomaly has its own numbered name; all lie on one track
    _write_workbook(
        data_dir / "Rekap 2022.xlsx",
        {
            "Bekasi": [
                _anomaly(f"Eks Sumber Bata {i}", 4, -6.300, 107.0 + i * 0.001, year=2022)
                for i in range(3)
            ],
        },
    )

    index_csv = tmp_path / "file_index.csv"
    pd.DataFrame(
        {
            "Year": [2024, 2024, 2022],
            "Area": ["Jakarta", "Jakarta", "Bekasi"],
            "Segment": ["Pipa Servis Indonesia Power", "Cawang - Kompor", None],
            "Sub Segment": [None, None, "Eks Sumber Bata"],
            "Diameter": [16.0, 10.0, 4.0],
            "CIPS": ["CIPS 01.xlsx", "CIPS 02.xlsx", "CIPS 03.xlsx"],
        }
    ).to_csv(index_csv, index=False)

    normalize_dir = tmp_path / "normalize"
    _write_track(normalize_dir, 2024, "CIPS 01.xlsx", -6.10, [106.80, 106.801])
    _write_track(normalize_dir, 2024, "CIPS 02.xlsx", -6.20, np.arange(106.90, 106.91, 0.001))
    _write_track(normalize_dir, 2022, "CIPS 03.xlsx", -6.30, np.arange(107.0, 107.01, 0.001))

    return {
        "index": str(tmp_path / "acvg-index.xlsx"),
        "data_dir": str(data_dir),
        "index_csv": str(index_csv),
        "normalize_dir": str(normalize_dir),
        "out": tmp_path / "out",
    }


def _acvg(setup) -> AcvgDcvg:
    return AcvgDcvg(setup["index"], data_dir=setup["data_dir"])


def test_load_reads_area_sheets_and_cleans_values(setup):
    acvg = _acvg(setup).load()
    df = acvg.anomalies

    # 2024: 4 kept (copied 2023 row and the note dropped), 2022: 3
    assert df.groupby("Year").size().to_dict() == {2022: 3, 2024: 4}
    assert "Template" not in set(df["Segmen"])
    assert "Kondisi Permukaan" in df.columns  # header spaces stripped
    power = df[df["Segmen"] == "Pipa Servis Indonesia Power"]
    assert power["Latitude"].tolist() == pytest.approx([-6.10, -6.10278], abs=1e-5)
    assert power["%drop PCM"].tolist() == [61.8, 61.8]  # "61.80%"
    assert power["Off Potential (volt)"].isna().all()  # "N/A"
    assert power["Hasil ACVG (dB)"].isna().all()  # "not detected"

    issues = acvg.load_report["issue"].tolist()
    assert "not an area sheet" in issues
    assert "dated in another year: Offtake Serpong" in issues


def test_sheet_missing_required_columns_is_reported(setup):
    path = os.path.join(setup["data_dir"], "Rekap 2024.xlsx")
    pd.DataFrame({"Segmen": ["x"]}).to_excel(path, sheet_name="Bogor", index=False)
    acvg = _acvg(setup).load()
    issue = acvg.load_report.loc[acvg.load_report["sheet"] == "Bogor", "issue"].iloc[0]
    assert issue.startswith("missing columns")


def test_match_by_name_cips_and_none(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    groups = acvg.groups.set_index("segment")

    assert groups.loc["Pipa Servis Indonesia Power", "method"] == "name"
    assert groups.loc["Pipa Servis Indonesia Power", "n_anomalies"] == 2

    cawang = groups.loc["Cawang Kompor 2"]
    assert cawang["method"] == "cips"
    assert cawang["index_row"] == 1
    assert cawang["distance_m"] < 50
    # named after the index row it belongs to
    assert cawang["filename"] == "acvg-dcvg-cawang-kompor-10-jakarta.xlsx"

    other = groups.loc["Somewhere Else"]
    assert other["method"] == "none"
    assert other["filename"] == "acvg-dcvg-somewhere-else-8-jakarta.xlsx"


def test_numbered_names_on_one_track_share_one_row(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    groups = acvg.groups[acvg.groups["year"] == 2022]

    # 2022 names are numbered per anomaly; all three lie on one CIPS track
    assert len(groups) == 1
    group = groups.iloc[0]
    assert group["method"] == "cips"
    assert group["n_anomalies"] == 3
    assert group["segment"] == "Eks Sumber Bata 0, Eks Sumber Bata 1, Eks Sumber Bata 2"
    assert group["index_segment"] == "Eks Sumber Bata"
    assert group["filename"] == "acvg-dcvg-eks-sumber-bata-4-bekasi.xlsx"


def _add_index_rows(setup, rows: list[dict]) -> None:
    index = pd.read_csv(setup["index_csv"])
    pd.concat([index, pd.DataFrame(rows)]).to_csv(setup["index_csv"], index=False)


def test_parent_pipeline_group_is_split_over_its_sections(setup):
    # 2023 style: the index splits a pipeline into sections, the ACVG/DCVG
    # workbook names the whole pipeline
    _add_index_rows(
        setup,
        [
            {"Year": 2024, "Area": "Jakarta", "Segment": "PU: A - B",
             "Diameter": 16.0, "CIPS": "CIPS AB.xlsx"},
            {"Year": 2024, "Area": "Jakarta", "Segment": "PU: B - C",
             "Diameter": 16.0, "CIPS": "CIPS BC.xlsx"},
        ],
    )
    normalize_dir = Path(setup["normalize_dir"])
    _write_track(normalize_dir, 2024, "CIPS AB.xlsx", -6.40, np.arange(106.50, 106.51, 0.001))
    _write_track(normalize_dir, 2024, "CIPS BC.xlsx", -6.40, np.arange(106.53, 106.54, 0.001))
    path = os.path.join(setup["data_dir"], "Rekap 2024.xlsx")
    sheets = pd.read_excel(path, sheet_name=None)
    jakarta = sheets["Jakarta"]
    parent = [
        _anomaly("PU Pipeline", 16, -6.40, lon) for lon in (106.501, 106.505, 106.532)
    ]
    sheets["Jakarta"] = pd.concat([jakarta, pd.DataFrame(parent)], ignore_index=True)
    with pd.ExcelWriter(path) as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)

    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    pu = acvg.groups[acvg.groups["segment"] == "PU Pipeline"].set_index("index_segment")

    # one named group, split by where each anomaly lies
    assert pu.loc["PU: A - B", "n_anomalies"] == 2
    assert pu.loc["PU: B - C", "n_anomalies"] == 1
    assert set(pu["method"]) == {"cips"}
    assert acvg.unlinked_segments()["segment"].tolist() == []


def test_name_match_keeps_a_group_together(setup):
    # one "Pipa Servis Indonesia Power" anomaly sits right on another track
    _add_index_rows(
        setup,
        [{"Year": 2024, "Area": "Jakarta", "Segment": "Neighbour",
          "Diameter": 16.0, "CIPS": "CIPS N.xlsx"}],
    )
    _write_track(Path(setup["normalize_dir"]), 2024, "CIPS N.xlsx", -6.10278, [106.801])

    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    power = acvg.groups[acvg.groups["index_segment"] == "Pipa Servis Indonesia Power"]

    assert power["method"].tolist() == ["name"]
    assert power["n_anomalies"].tolist() == [2]  # not split off to "Neighbour"


def test_max_distance_limits_the_cips_match(setup):
    acvg = _acvg(setup).load()
    acvg.match(setup["index_csv"], setup["normalize_dir"], max_distance_m=0.0001)
    methods = acvg.groups.set_index("segment")["method"]
    assert methods["Cawang Kompor 2"] == "none"


def test_rebuild_writes_one_file_per_segment(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    acvg.rebuild(output_dir=str(setup["out"]))

    folder = setup["out"] / "raw_data" / "2024" / "ACVG_DCVG"
    assert sorted(os.listdir(folder)) == [
        "acvg-dcvg-cawang-kompor-10-jakarta.xlsx",
        "acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.xlsx",
        "acvg-dcvg-somewhere-else-8-jakarta.xlsx",
    ]
    assert os.listdir(setup["out"] / "raw_data" / "2022" / "ACVG_DCVG") == [
        "acvg-dcvg-eks-sumber-bata-4-bekasi.xlsx"
    ]
    df = pd.read_excel(folder / "acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.xlsx")
    assert len(df) == 2
    assert list(df.columns[:3]) == ["Year", "Area", "No"]
    assert len(acvg.output_files) == 4


def test_rebuild_before_match_raises(setup):
    with pytest.raises(RuntimeError, match="match"):
        _acvg(setup).load().rebuild(output_dir=str(setup["out"]))


def test_assign_index_adds_the_column(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    report = acvg.assign_index()

    index = pd.read_csv(setup["index_csv"])
    assert index["ACVG_DCVG"].tolist() == [
        "acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.xlsx",
        "acvg-dcvg-cawang-kompor-10-jakarta.xlsx",
        "acvg-dcvg-eks-sumber-bata-4-bekasi.xlsx",
    ]
    assert set(report["method"]) == {"name", "cips", "none"}


def test_skip_years_and_missing_workbook(setup, tmp_path):
    acvg = AcvgDcvg(setup["index"], data_dir=setup["data_dir"], skip_years=[2022])
    assert acvg.df["Year"].tolist() == [2024]

    os.remove(os.path.join(setup["data_dir"], "Rekap 2022.xlsx"))
    with pytest.raises(FileNotFoundError, match="Rekap 2022.xlsx"):
        _acvg(setup)


def test_unlinked_segments_explain_empty_rows(setup):
    index = pd.read_csv(setup["index_csv"])
    extra = pd.DataFrame(
        {
            "Year": [2024, 2024, 2024, 2023, 2024],
            "Area": ["Jakarta"] * 5,
            "Segment": ["Far Away", "No CIPS", "Not Normalized", "Other Year", "Overlap"],
            "Sub Segment": [None] * 5,
            "Diameter": [4.0, 4.0, 4.0, 4.0, 10.0],
            "CIPS": ["CIPS 04.xlsx", None, "CIPS 05.xlsx", "CIPS 06.xlsx", "CIPS 07.xlsx"],
        }
    )
    pd.concat([index, extra]).to_csv(setup["index_csv"], index=False)
    normalize_dir = Path(setup["normalize_dir"])
    _write_track(normalize_dir, 2024, "CIPS 04.xlsx", -6.5, [107.5, 107.501])  # ~70 km off
    _write_track(normalize_dir, 2023, "CIPS 06.xlsx", -6.2, [106.9, 106.901])
    # the same pipe as "Cawang - Kompor": its anomaly already went to that row
    _write_track(normalize_dir, 2024, "CIPS 07.xlsx", -6.20, [106.900, 106.901])

    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    unlinked = acvg.unlinked_segments().set_index("segment")

    assert list(unlinked.index) == extra["Segment"].tolist()  # the 3 linked rows are not listed
    assert unlinked.loc["Far Away", "reason"] == "no anomaly within 500 m"
    assert unlinked.loc["Far Away", "nearest_anomaly_m"] > 50_000
    assert unlinked.loc["No CIPS", "reason"] == "no CIPS file in the index"
    assert unlinked.loc["Not Normalized", "reason"] == "CIPS not normalized"
    assert unlinked.loc["Other Year", "reason"] == "no ACVG/DCVG anomaly in 2023"
    overlap = unlinked.loc["Overlap"]
    assert overlap["reason"] == "anomalies nearby, linked to another row"
    assert overlap["nearest_anomaly_segmen"] == "Cawang Kompor 2"
    assert overlap["nearest_linked_to"] == "Cawang - Kompor"


def test_unlinked_segments_before_match_raises(setup):
    with pytest.raises(RuntimeError, match="match"):
        _acvg(setup).load().unlinked_segments()


def test_rebuild_keeps_required_columns_and_hides_match_columns(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    acvg.rebuild(output_dir=str(setup["out"]))

    for path in acvg.output_files:
        columns = pd.read_excel(path).columns
        assert set(AcvgDcvg.REQUIRED_COLUMNS) <= set(columns), path
        assert not [c for c in columns if c.startswith("_")], path


def test_clean_and_normalize_every_extracted_file(setup):
    out = setup["out"]
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    acvg.rebuild(output_dir=str(out)).clean().normalize()

    report = acvg.file_report.set_index("filename")
    assert len(report) == 4
    assert report["reason"].isna().all()

    power = "acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.xlsx"
    # same layout as CIPS/PCM: cleaned/<year>/<KIND>, normalize/<kind>/<excel|json>
    assert report.loc[power, "cleaned_path"] == str(
        out / "cleaned" / "2024" / "ACVG_DCVG" / power
    )
    json_dir = out / "normalize" / "acvg_dcvg" / "json"
    assert report.loc[power, "normalized_file"] == f"2024-{power[:-5]}.json"
    assert (out / "normalize" / "acvg_dcvg" / "excel" / f"2024-{power}").is_file()

    with open(json_dir / f"2024-{power[:-5]}.json", encoding="utf-8") as f:
        records = json.load(f)
    assert list(records[0]) == list(AcvgDcvgFile.JSON_COLUMNS.values())
    # each anomaly takes position and condition of its nearest CIPS reading
    assert [(r["real_distance"], r["closest_cips_condition"]) for r in records] == [
        (0.0, "PROTECTED"),
        (100.0, "UNPROTECTED"),
    ]
    assert records[0]["survey_dcvg"] == "2024-05-20"
    assert records[0]["result_acvg"] is None  # "not detected"

    # an unmatched group has no CIPS line: normalized without a position
    somewhere = "acvg-dcvg-somewhere-else-8-jakarta.xlsx"
    assert pd.isna(report.loc[somewhere, "cips_file"])
    assert report.loc[somewhere, "n_on_cips"] == 0
    with open(json_dir / f"2024-{somewhere[:-5]}.json", encoding="utf-8") as f:
        (record,) = json.load(f)
    assert record["real_distance"] is None and record["closest_cips_condition"] is None


def test_normalized_files_of_the_linked_rows(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    with pytest.raises(RuntimeError, match="normalize"):
        acvg.normalized_files()
    with pytest.raises(RuntimeError, match="normalize"):
        acvg.anomaly_counts()
    acvg.rebuild(output_dir=str(setup["out"])).clean().normalize()

    # index CSV rows: 0 Pipa Servis, 1 Cawang - Kompor, 2 Eks Sumber Bata;
    # the unmatched "Somewhere Else" file has no row
    assert acvg.normalized_files() == {
        0: "2024-acvg-dcvg-pipa-servis-indonesia-power-16-jakarta.json",
        1: "2024-acvg-dcvg-cawang-kompor-10-jakarta.json",
        2: "2022-acvg-dcvg-eks-sumber-bata-4-bekasi.json",
    }
    # AcvgDcvgFile.count of each of those files
    assert acvg.anomaly_counts() == {0: 2, 1: 1, 2: 3}


def test_clean_and_normalize_need_the_previous_step(setup):
    acvg = _acvg(setup).load().match(setup["index_csv"], setup["normalize_dir"])
    with pytest.raises(RuntimeError, match="rebuild"):
        acvg.clean()
    with pytest.raises(RuntimeError, match="clean"):
        acvg.rebuild(output_dir=str(setup["out"])).normalize()


def _segment_file(tmp_path, rows: list[dict]) -> str:
    path = tmp_path / "acvg-dcvg-seg-a-16-jakarta.xlsx"
    frame = pd.DataFrame(rows)
    frame.insert(0, "Year", 2024)
    frame.insert(1, "Area", "Jakarta")
    frame.columns = [str(c).strip() for c in frame.columns]
    frame.to_excel(path, index=False)
    return str(path)


def test_file_clean_drops_unusable_rows(tmp_path):
    path = _segment_file(
        tmp_path,
        [
            _anomaly("Seg A", 16, -6.1, 106.803),
            _anomaly("Seg A", 16, -6.1, 106.803),  # duplicate point
            _anomaly("Seg A", 16, 0, 106.8),  # no GPS fix
            _anomaly("Seg A", 16, None, None),  # no coordinates
            _anomaly("Seg A", 16, -6.1, 106.801),
        ],
    )
    data = AcvgDcvgFile(path, year=2024, output_dir=str(tmp_path / "out"))
    data.check().clean().save()

    assert data.report["n_duplicates"] == 2
    assert data.df["Longitude"].tolist() == [106.803, 106.801]
    assert data.cleaned_path == str(
        tmp_path / "out" / "cleaned" / "2024" / "ACVG_DCVG" / os.path.basename(path)
    )


def test_file_normalize_places_anomalies_on_the_cips_line(tmp_path):
    track = _write_track(
        tmp_path / "normalize", 2024, "CIPS A.xlsx", -6.1, np.arange(106.800, 106.8045, 0.001)
    )
    path = _segment_file(
        tmp_path,
        [
            _anomaly("Seg A", 16, -6.1, 106.8031),  # reading 3
            _anomaly("Seg A", 16, -6.1, 106.8009, **{"Tgl DCVG": "20-May"}),  # reading 1
            _anomaly("Seg A", 16, -6.2, 106.8),  # ~11 km off the line
        ],
    )
    data = AcvgDcvgFile(path, year=2024, output_dir=str(tmp_path / "out"))

    with pytest.raises(RuntimeError, match="clean"):
        data.normalize(str(track))
    assert data.count == 0
    data.clean().normalize(str(track))
    assert data.count == 3  # the far anomaly is kept, without a position

    # sorted along the line; the far anomaly gets no position or condition
    assert data.df["Real Distance"].tolist()[:2] == [100.0, 300.0]
    assert data.df["Condition"].tolist()[:2] == ["UNPROTECTED", "UNPROTECTED"]
    assert data.df[["Real Distance", "Condition"]].iloc[2].isna().all()
    assert data.df["CIPS Offset (m)"].iloc[2] > 10_000
    with open(data.normalize_json_filepath, encoding="utf-8") as f:
        records = json.load(f)
    assert [r["survey_dcvg"] for r in records] == ["20-May", "2024-05-20", "2024-05-20"]
    assert "CIPS Offset (m)" in pd.read_excel(data.normalize_excel_filepath).columns


def test_file_normalize_without_cips(tmp_path):
    path = _segment_file(tmp_path, [_anomaly("Seg A", 16, -6.1, 106.8)])
    data = AcvgDcvgFile(path, year=2024, output_dir=str(tmp_path / "out"))
    data.clean().normalize()

    assert data.normalized
    assert data.df["Real Distance"].isna().all()
    assert data.normalize_json_filepath == str(
        tmp_path / "out" / "normalize" / "acvg_dcvg" / "json"
        / "2024-acvg-dcvg-seg-a-16-jakarta.json"
    )
