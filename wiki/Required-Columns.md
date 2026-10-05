# Required Columns

The columns each input file needs, per data type: **CIPS**, **PCM** and
**ACVG/DCVG**. A missing column has different effects depending on where it
is used:

| Effect | Meaning |
| --- | --- |
| **load** | The file cannot be opened: the constructor raises `ValueError`. |
| **clean** | `clean()` raises `ValueError`; nothing is cleaned or normalized. |
| **normalize** | `clean()` works, but `normalize()` raises `ValueError`. |
| **report** | Everything runs. `check()` lists the column in `missing_columns` and sets `is_valid = False`. |
| **added** | Created empty when it is missing. |

Column names must match exactly (case and spaces), except for the
renames listed for CIPS. Leading and trailing spaces in the header are
ignored. Any other columns are kept as they are in the cleaned and normalized
Excel files, but not in the JSON.

To see what a file is missing, run `check()` on it:

```python
from corrosions.data.pcm import PCM

report = PCM("PCM Seg A.xlsx", year=2024).check().report
report["missing_columns"]   # e.g. ['Gain (dB)'], or None
report["is_valid"]
```

`main.py` writes these reports to `checked-cips.xlsx` / `checked-pcm.xlsx` and,
for ACVG/DCVG, the `load issues` sheet of `acvg-dcvg-report.xlsx`.

- [CIPS](#cips)
- [PCM](#pcm)
- [ACVG/DCVG](#acvgdcvg)
- [Index workbooks](#index-workbooks)

---

## CIPS

One Excel file per survey. The workbook may have several sheets (charts,
`DCP Data`, `Survey Info`, …). The **data sheet** is the one whose header has
`Latitude`, `Longitude` and `DCP/Feature/DCVG Anomaly`. If several sheets
have them, the first of `Data`, `Sheet1`, `Sequential File`,
`Sequential Files` wins, then the first in workbook order.

| Column | Required for | Notes |
| --- | --- | --- |
| `Latitude` | load | Decimal degrees (numbers). Rows with an empty or `0` value are dropped. |
| `Longitude` | load | Same as `Latitude`. |
| `DCP/Feature/DCVG Anomaly` | load | Text (test posts, crossings, …); may be empty. In the JSON as `dcp_feature_dcvg_anomaly`. |
| `Comment` | added | Free text; may be empty. In the JSON as `comment`. |
| voltage columns | clean | One of the layouts below. In volts; the sign may be positive or negative. |

### Voltage layouts

The protection type (ICCP or SACP) is read from the voltage columns:

| Columns present | Protection | Notes |
| --- | --- | --- |
| `On Voltage` + `Off Voltage` | ICCP | Rows missing either value are dropped. |
| `Voltage` + `Off Voltage` (no `On Voltage`) | from the filename | The filename must contain `ICCP` or `SACP` as a whole word (e.g. `CIPS - ICCP Seg A.xlsx`); otherwise `clean()` raises `Cannot tell ICCP from SACP`. ICCP takes `Voltage` as the ON reading. |
| `Voltage` only | SACP | Rows with an empty `Voltage` are dropped. |
| anything else (e.g. only `-mV On` / `-mV Off`, or only `On Voltage`) | — | `clean()` raises `Invalid CIPS data`. Such years can be left out with `--skip-years`. |

These names are renamed while loading, so they count as the names above:

| Source name | Becomes |
| --- | --- |
| `Voltage (V)` | `Voltage` |
| `Off Voltage (V)` | `Off Voltage` |

Other voltage columns (`-mV On`, `Potential (-mV)`, `On Potential (mV)`, …)
are not used. `Data No` and `Altitude` are not required.

`check()` sets `has_voltage` (an ICCP or SACP voltage column exists) and
`is_valid = n_missing == 0 and has_voltage`. Duplicate coordinates do not
make a CIPS file invalid; `clean()` keeps the first reading.

Minimal valid files:

| Latitude | Longitude | DCP/Feature/DCVG Anomaly | On Voltage | Off Voltage |
| --- | --- | --- | --- | --- |
| -6.2000 | 106.8000 | Test Post TP-01 | -1.10 | -0.90 |
| -6.2009 | 106.8001 | | -0.95 | -0.86 |

| Latitude | Longitude | DCP/Feature/DCVG Anomaly | Voltage |
| --- | --- | --- | --- |
| -6.2000 | 106.8000 | | -0.90 |
| -6.2009 | 106.8001 | | -0.95 |

---

## PCM

One Excel file per survey; the **first sheet** is read.

| Column | Required for | Notes |
| --- | --- | --- |
| `4Hz Current (A)` | normalize | Amperes. Rows with an empty value or a current `<= 0` (lost signal) are dropped. In the JSON as `4hz_current_a`; `dbma` is computed from it. |
| `Int GPS Latitude` | normalize | Decimal degrees. Rows with an empty or `0` value are dropped. In the JSON as `latitude`. |
| `Int GPS Longitude` | normalize | Same as `Int GPS Latitude`. In the JSON as `longitude`. |
| `Depth (m)` | normalize | Meters; may be empty. In the JSON as `depth_m`. |
| `Comment (0-100)` | normalize | Free text; may be empty. In the JSON as `comment_0_100`. |
| `Gain (dB)` | report | Rows with an empty value are dropped when the column exists. Not in the JSON. |

`Ext GPS Latitude` / `Ext GPS Longitude` are not required (they are often
blank). A source `Distance` column is replaced by the computed one.

`check()` sets `is_valid = False` when a column is missing **or** two readings
share the same `Int GPS Latitude` / `Int GPS Longitude`. `main.py` checks
after `clean()`, which removes those duplicates.

Minimal valid file:

| 4Hz Current (A) | Int GPS Latitude | Int GPS Longitude | Comment (0-100) | Gain (dB) | Depth (m) |
| --- | --- | --- | --- | --- | --- |
| 0.520 | -6.2000 | 106.8000 | Start | 40 | 1.2 |
| 0.515 | -6.2009 | 106.8001 | | 40 | 1.3 |

---

## ACVG/DCVG

ACVG/DCVG data comes in two shapes:

1. **Yearly workbook** (read by `AcvgDcvg.load()`, in `--acvg-dir`): one
   workbook per year, **one sheet per area**. Only the sheets `Bekasi`,
   `Bogor`, `Cilegon`, `Cirebon`, `Jakarta`, `Karawang` and `Tangerang` are
   read. A sheet missing **any** column below is skipped and listed in the
   `load issues` sheet of `acvg-dcvg-report.xlsx`.
2. **One-segment file** (read by `AcvgDcvgFile`, and by `sync_files`): one
   segment's anomalies on the first sheet, as `AcvgDcvg.rebuild()` writes to
   `output/raw_data/<year>/ACVG_DCVG/`. Missing columns are only reported by
   `check()` and written empty by `normalize()`.

| Column | Required for | JSON key | Notes |
| --- | --- | --- | --- |
| `Segmen` | load (workbook) | — | Segment name, used to match the file index. Workbook rows without it are dropped (notes, empty rows). Excel only. |
| `Lokasi Anomali` | load (workbook) | `anomaly_location` | Text. |
| `Kondisi Permukaan` | load (workbook) | `surface_condition` | Text. |
| `Dia (inch)` | load (workbook) | `diameter` | Number; matched with the index `Diameter`. |
| `Latitude` | load (workbook) | `latitude` | Rows with an empty or `0` value are dropped. |
| `Longitude` | load (workbook) | `longitude` | Same as `Latitude`. |
| `On Potential (volt)` | load (workbook) | `on_potential` | Number. |
| `Off Potential (volt)` | load (workbook) | `off_potential` | Number. |
| `IR Drop (%)` | load (workbook) | `ir_drop` | Number. |
| `Hasil ACVG (dB)` | load (workbook) | `result_acvg` | Number. |
| `Kedalaman Pipa (m)` | load (workbook) | `pipe_depth` | Number. |
| `%drop PCM` | load (workbook) | `drop_pcm` | Number. |
| `Tgl DCVG` | load (workbook) | `survey_dcvg` | Date. A workbook row dated in another year than the workbook is dropped. |
| `Tgl ACVG` | load (workbook) | `survey_acvg` | Date, same as `Tgl DCVG`. |

Value formats:

| Values | Yearly workbook (`AcvgDcvg.load`) | One-segment file (`AcvgDcvgFile`) |
| --- | --- | --- |
| Coordinates | numbers, numeric text, or degrees-minutes-seconds (`6°15'16.8"S`, `106°59'58.7"E`) | numbers or numeric text only |
| Numeric columns | numbers; `"61.80%"` → `61.8`; `"N/A"`, `"-"`, `"not detected"` → empty | numbers or numeric text; anything else (including `"61.80%"`) → empty |
| Dates | date cells or date text (same rules as the next column); only date cells from another year drop the row | date cells, or text as `2024-05-20`, `20-05-2024`, `20/05/2024`, `20-May-2024`, `20 May 2024`, or without a year (`20-May`, `20 May`: takes the survey year); other text is `null` in the JSON |

Files written by `AcvgDcvg.rebuild()` already hold parsed numbers and
coordinates, so they work as one-segment files.

> **Note:** a one-segment file **without** `Latitude` / `Longitude` is not
> rejected: `clean()` cannot drop rows by a column that does not exist, and
> the anomalies end up with an empty `real_distance` and
> `closest_cips_condition`. Check `report["missing_columns"]` first.

Minimal one-segment file:

| Segmen | Lokasi Anomali | Kondisi Permukaan | Dia (inch) | Latitude | Longitude | On Potential (volt) | Off Potential (volt) | IR Drop (%) | Hasil ACVG (dB) | Kedalaman Pipa (m) | %drop PCM | Tgl DCVG | Tgl ACVG |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Seg A | Jl. Demo 1 | Tanah | 8 | -6.20185 | 106.80021 | -1.21 | -0.95 | 32.5 | 45 | 1.5 | 12.3 | 2024-05-20 | 2024-05-18 |

---

## Index workbooks

`main.py` also reads two index workbooks that list the files above.

**CIPS/PCM index** (`IDDA - PCM CIPS File List.xlsx`, `-i`): every column
below must exist, or loading fails with `KeyError`. Other columns are
allowed; `-d` drops some before processing (default `Nomor Segment`).

| Column | Notes |
| --- | --- |
| `Year` | Survey year; the files are read from `<source>/<Year>/CIPS FINAL/` and `PCM FINAL/`. |
| `Area` | Must be filled. |
| `Segment` | Must be filled, unless `Sub Segment` is (an empty `Segment` takes the `Sub Segment`). `Segment` + `Diameter` must be unique. |
| `Sub Segment` | May be empty. |
| `Diameter` | Inches. |
| `Length` | Kilometers; when empty, the CIPS or PCM survey length is used. |
| `Province Code` | |
| `ACVG/DCVG` | |
| `CIPS` | CIPS filename (`.xlsx` is added if missing); empty when the segment has none. |
| `PCM` | PCM filename; empty when the segment has none. |

**ACVG/DCVG index** (`IDDA - ACVG FIle List.xlsx`, `--acvg-index`):

| Column | Notes |
| --- | --- |
| `Year` | Survey year of the workbook. |
| `Filename` | Yearly workbook in `--acvg-dir`. |
