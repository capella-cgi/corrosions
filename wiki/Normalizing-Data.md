# Normalizing Data

How to normalize each data type (CIPS, PCM, ACVG/DCVG) and what the output
looks like. `main.py` does all of this for the whole index; this page shows
the same steps for one file, for notebooks or one-off checks. The full API is
in [API Reference](API-Reference.md); the columns each input file needs are in
[Required Columns](Required-Columns.md).

Every type uses the same chain:

```python
Data(path, year=...).clean().check().save().normalize(...)
```

| Step | What it does |
| --- | --- |
| constructor | loads the data sheet and converts numeric columns (CIPS also renames `Voltage (V)` / `Off Voltage (V)` and adds an empty `Comment`) |
| `clean()` | drops all-empty rows, rows with an empty or `0` coordinate, rows missing a required value, then duplicate coordinates (first kept); raises `ValueError` if nothing is left |
| `check()` | optional: stores a quality summary of the (cleaned) data on `report` |
| `save()` | optional: writes the cleaned copy to `output/cleaned/<year>/<KIND>/<filename>` |
| `normalize()` | adds distances and a condition, then writes Excel and JSON to `output/normalize/<kind>/<excel\|json>/<year>-<slug>.*`; raises `RuntimeError` before `clean()` |

`<slug>` is the source filename without extension, slugified
(`CIPS - ICCP Demo Segment.xlsx` → `cips-iccp-demo-segment`). Every
`normalize()` takes `normalize_dir=None` to write somewhere else
(`<normalize_dir>/excel`, `<normalize_dir>/json`), and adds its results to
`report` (run `check()` first: it replaces the whole report).

The examples below come from running the chains on the small demo files
shown with each section (6 readings along a line in Jakarta, about 100 m
apart). Distances are in meters.

- [CIPS](#cips)
- [PCM](#pcm)
- [ACVG/DCVG](#acvgdcvg)
- [Sync one segment from its Excel files](#sync-one-segment-from-its-excel-files)
- [Whole index](#whole-index)

---

## CIPS

```python
from corrosions.data.cips import CIPS

cips = (
    CIPS("output/raw_data/2024/CIPS/CIPS - ICCP Demo Segment.xlsx", year=2024)
    .clean()
    .check()
    .save()
    .normalize()
)
cips.protection                 # "ICCP"
cips.protected_percentage       # 75.0
cips.normalize_json_filepath    # .../normalize/cips/json/2024-cips-iccp-demo-segment.json
```

### Input

The data sheet is found by its header (`Latitude`, `Longitude`,
`DCP/Feature/DCVG Anomaly`), whatever its name. Voltages may be positive or
negative; the protection type comes from the columns, or from `ICCP` /
`SACP` in the filename when the columns don't decide it.

| Data No | Latitude | Longitude | Voltage (V) | Off Voltage (V) | DCP/Feature/DCVG Anomaly |
| --- | --- | --- | --- | --- | --- |
| 1 | -6.2000 | 106.8000 | 1.10 | 0.90 | Test Post TP-01 |
| 2 | -6.2000 | 106.8000 | 1.10 | 0.90 | |
| 3 | -6.2009 | 106.8001 | 0.95 | 0.86 | |
| 4 | -6.2018 | 106.8002 | 1.25 | 1.21 | Road crossing |
| 5 | 0 | 0 | 1.00 | 0.95 | |
| 6 | -6.2027 | 106.8003 | 0.70 | 0.80 | |

### What happens

1. **Load:** `Voltage (V)` → `Voltage`, `Off Voltage (V)` → `Off Voltage`,
   empty `Comment` added.
2. **`clean()`:** `Voltage` + `Off Voltage` without `On Voltage`, and the
   filename says `ICCP` → ICCP: `On Voltage` = source `Voltage`, `Voltage`
   and `Off Voltage` made negative, `Protection = ICCP`. Row 2 (duplicate)
   and row 5 (`0` coordinate) are dropped → 4 rows.
3. **`normalize()`:** adds `Distance`, `Real Distance` and `Condition` from
   the `Off Voltage` (ICCP) or `Voltage` (SACP):

   | Condition | Rule (volts) |
   | --- | --- |
   | `PROTECTED` | `-1.2 < V <= -0.85` |
   | `OVER PROTECTED` | `V <= -1.2` |
   | `UNPROTECTED` | anything else, including an empty reading |

### Output: Excel

`output/normalize/cips/excel/2024-cips-iccp-demo-segment.xlsx`: every column
of the cleaned data, original names.

| Data No | Latitude | Longitude | Voltage | Off Voltage | DCP/Feature/DCVG Anomaly | Comment | On Voltage | Protection | Distance | Real Distance | Condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | -6.2000 | 106.8000 | -1.10 | -0.90 | Test Post TP-01 | | 1.10 | ICCP | 0.00 | 0.00 | PROTECTED |
| 3 | -6.2009 | 106.8001 | -0.95 | -0.86 | | | 0.95 | ICCP | 100.68 | 100.68 | PROTECTED |
| 4 | -6.2018 | 106.8002 | -1.25 | -1.21 | Road crossing | | 1.25 | ICCP | 100.68 | 201.37 | OVER PROTECTED |
| 6 | -6.2027 | 106.8003 | -0.70 | -0.80 | | | 0.70 | ICCP | 100.68 | 302.05 | UNPROTECTED |

### Output: JSON

`output/normalize/cips/json/2024-cips-iccp-demo-segment.json`: one record per
reading, only these keys. Empty cells are `null`; `off_voltage` is always
`null` for SACP.

```json
[
  {
    "voltage": -1.1,
    "off_voltage": -0.9,
    "latitude": -6.2,
    "longitude": 106.8,
    "real_distance": 0.0,
    "condition": "PROTECTED",
    "comment": null,
    "dcp_feature_dcvg_anomaly": "Test Post TP-01"
  },
  {
    "voltage": -0.95,
    "off_voltage": -0.86,
    "latitude": -6.2009,
    "longitude": 106.8001,
    "real_distance": 100.6841260516,
    "condition": "PROTECTED",
    "comment": null,
    "dcp_feature_dcvg_anomaly": null
  }
]
```

### Output: `report`

```python
{
    "filepath": ".../CIPS - ICCP Demo Segment.xlsx",
    "sheet_name": "Sheet1",
    "is_valid": True,
    "n_missing": 0,
    "n_duplicates": 0,              # check() ran after clean()
    "missing_columns": None,
    "duplicates": None,
    "has_voltage": True,
    "normalized": True,
    "n_normalized": 4,
    "normalize_excel_filepath": ".../normalize/cips/excel/2024-cips-iccp-demo-segment.xlsx",
    "normalize_json_filepath": ".../normalize/cips/json/2024-cips-iccp-demo-segment.json",
    "protection": "ICCP",
    "length_km": 0.302,             # last Real Distance / 1000
    "protected_percentage": 75.0,   # PROTECTED + OVER PROTECTED
    "unprotected_percentage": 25.0,
}
```

---

## PCM

```python
from corrosions.data.pcm import PCM

pcm = (
    PCM("output/raw_data/2024/PCM/PCM Demo Segment.xlsx", year=2024)
    .clean()
    .check()
    .save()
    .normalize()
)
pcm.medium_to_high_percentage   # 100.0
```

### Input

The first sheet. Required: `4Hz Current (A)`, `Int GPS Latitude`,
`Int GPS Longitude`, `Comment (0-100)`, `Gain (dB)`, `Depth (m)`.

| Index | 4Hz Current (A) | Int GPS Latitude | Int GPS Longitude | Comment (0-100) | Gain (dB) | Depth (m) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.520 | -6.2000 | 106.8000 | Start | 40 | 1.2 |
| 2 | 0.520 | -6.2000 | 106.8000 | | 40 | 1.2 |
| 3 | 0.515 | -6.2009 | 106.8001 | | 40 | 1.3 |
| 4 | 0.000 | -6.2018 | 106.8002 | no signal | 40 | 1.1 |
| 5 | 0.480 | 0 | 0 | | 41 | 1.4 |
| 6 | 0.476 | -6.2027 | 106.8003 | End | 41 | 1.3 |

### What happens

1. **`clean()`:** row 4 (current `<= 0`, a lost signal), row 5 (`0`
   coordinate) and row 2 (duplicate) are dropped → 3 rows. Rows without
   current, Int GPS or gain are dropped too; Ext GPS columns may be empty.
2. **`normalize()`:** adds

   | Column | Value |
   | --- | --- |
   | `Distance` / `Real Distance` | from the Int GPS coordinates, like CIPS (replaces any source `Distance`) |
   | `dbma` | `20 * log10(current * 1000)`, 2 decimals |
   | `Current Loss Rate` | `abs(Δdbma / Δdistance) * 1000` against the previous reading, `0` for the first |
   | `Condition` | `Medium to High` if the rate is `<= 50`, else `Medium to Poor` |

### Output: Excel

`output/normalize/pcm/excel/2024-pcm-demo-segment.xlsx`:

| Index | 4Hz Current (A) | Int GPS Latitude | Int GPS Longitude | Comment (0-100) | Gain (dB) | Depth (m) | Distance | Real Distance | dbma | Current Loss Rate | Condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.520 | -6.2000 | 106.8000 | Start | 40 | 1.2 | 0.00 | 0.00 | 54.32 | 0.00 | Medium to High |
| 3 | 0.515 | -6.2009 | 106.8001 | | 40 | 1.3 | 100.68 | 100.68 | 54.24 | 0.79 | Medium to High |
| 6 | 0.476 | -6.2027 | 106.8003 | End | 41 | 1.3 | 201.37 | 302.05 | 53.55 | 3.43 | Medium to High |

### Output: JSON

`output/normalize/pcm/json/2024-pcm-demo-segment.json` (`latitude` /
`longitude` are the Int GPS columns):

```json
[
  {
    "latitude": -6.2,
    "longitude": 106.8,
    "real_distance": 0.0,
    "4hz_current_a": 0.52,
    "dbma": 54.32,
    "current_loss_rate": 0.0,
    "depth_m": 1.2,
    "condition": "Medium to High",
    "comment_0_100": "Start"
  },
  {
    "latitude": -6.2009,
    "longitude": 106.8001,
    "real_distance": 100.6841260516,
    "4hz_current_a": 0.515,
    "dbma": 54.24,
    "current_loss_rate": 0.79,
    "depth_m": 1.3,
    "condition": "Medium to High",
    "comment_0_100": null
  }
]
```

### Output: `report`

```python
{
    "filepath": ".../PCM Demo Segment.xlsx",
    "sheet_name": 0,
    "is_valid": True,
    "n_missing": 0,
    "n_duplicates": 0,
    "missing_columns": None,
    "duplicates": None,
    "normalized": True,
    "n_normalized": 3,
    "normalize_excel_filepath": ".../normalize/pcm/excel/2024-pcm-demo-segment.xlsx",
    "normalize_json_filepath": ".../normalize/pcm/json/2024-pcm-demo-segment.json",
    "length_km": 0.302,
    "medium_to_high_percentage": 100.0,
    "medium_to_poor_percentage": 0.0,
}
```

---

## ACVG/DCVG

An ACVG/DCVG file is one segment's anomalies, written by
`AcvgDcvg.rebuild()` (see [Whole index](#whole-index)). `normalize()` takes
the segment's **normalized CIPS JSON** and places every anomaly on that
line, so normalize the CIPS first.

```python
from corrosions.data.acvg_dcvg import AcvgDcvgFile

acvg = (
    AcvgDcvgFile("output/raw_data/2024/ACVG_DCVG/acvg-dcvg-demo-segment-8-jakarta.xlsx", year=2024)
    .clean()
    .check()
    .save()
    .normalize(cips.normalize_json_filepath)   # or None: no CIPS for this segment
)
acvg.count       # 2 anomalies
```

### Input

| Segmen | Lokasi Anomali | Kondisi Permukaan | Dia (inch) | Latitude | Longitude | On Potential (volt) | Off Potential (volt) | IR Drop (%) | Hasil ACVG (dB) | Kedalaman Pipa (m) | %drop PCM | Tgl DCVG | Tgl ACVG |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Demo Segment | Jl. Demo 1 | Tanah | 8 | -6.20185 | 106.80021 | -1.21 | -0.95 | 32.5 | 45 | 1.5 | 12.3 | 2024-05-20 | 2024-05-18 |
| Demo Segment | Jl. Demo 2 | Aspal | 8 | -6.20005 | 106.80001 | -1.05 | -0.88 | 18.0 | 38 | 1.2 | 8.1 | 21-May | 2024-05-19 |
| Demo Segment | Jl. Demo 3 | Beton | 8 | 0 | 0 | -1.00 | -0.90 | 10.0 | 30 | 1.0 | 5.0 | | |

### What happens

1. **`clean()`:** the anomaly with a `0` coordinate is dropped → 2 rows.
2. **`normalize(cips_json)`:** each anomaly takes its nearest CIPS reading
   and adds:

   | Column | Value |
   | --- | --- |
   | `Real Distance` | that reading's `real_distance`: where the anomaly sits on the CIPS line |
   | `Condition` | that reading's `condition` |
   | `CIPS Offset (m)` | meters from the anomaly to that reading (Excel only) |

   `Real Distance` and `Condition` stay empty without a CIPS JSON or when
   the nearest reading is more than 500 m away. Rows are sorted by
   `Real Distance` (empty last). In the JSON, dates become `YYYY-MM-DD`
   (`21-May` takes the file's year → `2024-05-21`; text that isn't a date
   is `null`).

### Output: Excel

`output/normalize/acvg_dcvg/excel/2024-acvg-dcvg-demo-segment-8-jakarta.xlsx`:
the input columns plus the three above, sorted along the line.

| Segmen | Lokasi Anomali | … | Tgl DCVG | Tgl ACVG | Real Distance | Condition | CIPS Offset (m) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Demo Segment | Jl. Demo 2 | … | 21-May | 2024-05-19 | 0.00 | PROTECTED | 5.7 |
| Demo Segment | Jl. Demo 1 | … | 2024-05-20 | 2024-05-18 | 201.37 | OVER PROTECTED | 5.7 |

### Output: JSON

`output/normalize/acvg_dcvg/json/2024-acvg-dcvg-demo-segment-8-jakarta.json`:
English keys, `Segmen` left out (the file is one segment).

```json
[
  {
    "latitude": -6.20005,
    "longitude": 106.80001,
    "real_distance": 0.0,
    "anomaly_location": "Jl. Demo 2",
    "surface_condition": "Aspal",
    "diameter": 8,
    "on_potential": -1.05,
    "off_potential": -0.88,
    "ir_drop": 18.0,
    "result_acvg": 38,
    "pipe_depth": 1.2,
    "drop_pcm": 8.1,
    "survey_dcvg": "2024-05-21",
    "survey_acvg": "2024-05-19",
    "closest_cips_condition": "PROTECTED"
  },
  {
    "latitude": -6.20185,
    "longitude": 106.80021,
    "real_distance": 201.3682500319,
    "anomaly_location": "Jl. Demo 1",
    "surface_condition": "Tanah",
    "diameter": 8,
    "on_potential": -1.21,
    "off_potential": -0.95,
    "ir_drop": 32.5,
    "result_acvg": 45,
    "pipe_depth": 1.5,
    "drop_pcm": 12.3,
    "survey_dcvg": "2024-05-20",
    "survey_acvg": "2024-05-18",
    "closest_cips_condition": "OVER PROTECTED"
  }
]
```

| Input column | JSON key |
| --- | --- |
| `Lokasi Anomali` | `anomaly_location` |
| `Kondisi Permukaan` | `surface_condition` |
| `Dia (inch)` | `diameter` |
| `On Potential (volt)` / `Off Potential (volt)` | `on_potential` / `off_potential` |
| `IR Drop (%)` | `ir_drop` |
| `Hasil ACVG (dB)` | `result_acvg` |
| `Kedalaman Pipa (m)` | `pipe_depth` |
| `%drop PCM` | `drop_pcm` |
| `Tgl DCVG` / `Tgl ACVG` | `survey_dcvg` / `survey_acvg` |
| `Condition` | `closest_cips_condition` |

### Output: `report`

```python
{
    "filepath": ".../acvg-dcvg-demo-segment-8-jakarta.xlsx",
    "sheet_name": 0,
    "is_valid": True,
    "n_missing": 0,
    "n_duplicates": 0,
    "missing_columns": None,
    "duplicates": None,
    "normalized": True,
    "n_normalized": 2,
    "normalize_excel_filepath": ".../normalize/acvg_dcvg/excel/2024-acvg-dcvg-demo-segment-8-jakarta.xlsx",
    "normalize_json_filepath": ".../normalize/acvg_dcvg/json/2024-acvg-dcvg-demo-segment-8-jakarta.json",
    "count": 2,          # anomalies in the file
    "n_on_cips": 2,      # anomalies with a Real Distance
    "cips_json": ".../normalize/cips/json/2024-cips-iccp-demo-segment.json",
}
```

---

## Sync one segment from its Excel files

`sync_files` runs the three sections above for one segment and puts the CIPS
and PCM in the same direction before the ACVG/DCVG step, so the anomalies'
`real_distance` follows the synced CIPS:

1. normalize the CIPS and PCM (`clean().normalize()`);
2. sync them in place: the CIPS starts at its west end (west-east line) or
   north end (north-south line), the PCM at the end closer to the CIPS
   start; a reversed survey gets its distances (and PCM loss rate /
   condition) recalculated;
3. if an ACVG/DCVG file is given, normalize it on the synced CIPS JSON.

Example with the demo CIPS and PCM above, but the PCM walked south to north
(rows in reverse order):

```python
from corrosions.sync import sync_files

result = sync_files(
    "CIPS - ICCP Demo Segment.xlsx",          # source CIPS
    "PCM Demo Segment Reversed.xlsx",         # source PCM, walked the other way
    2024,
    acvg_dcvg="acvg-dcvg-demo-segment-8-jakarta.xlsx",   # optional
    output_dir="output",
)
```

```python
{
    "cips_json": "output/normalize/cips/json/2024-cips-iccp-demo-segment.json",
    "pcm_json": "output/normalize/pcm/json/2024-pcm-demo-segment-reversed.json",
    "acvg_dcvg_json": "output/normalize/acvg_dcvg/json/2024-acvg-dcvg-demo-segment-8-jakarta.json",
    "cips_axis": "north-south",
    "cips_reversed": False,    # the CIPS already starts at the north end
    "pcm_reversed": True,      # the PCM now starts there too
    "start_gap_m": 50.34,
}
```

The demo CIPS line runs north-south (0.0027° of latitude, 0.0003° of
longitude) and already starts at the north end, so only the PCM is
reversed. `start_gap_m` is the distance between the two start ends (each the
mean of up to 5 end readings).

### Output: CIPS JSON (synced)

Unchanged, the same as in [CIPS](#cips):

```json
[
  {"voltage": -1.1, "off_voltage": -0.9, "latitude": -6.2, "longitude": 106.8, "real_distance": 0.0, "condition": "PROTECTED", "comment": null, "dcp_feature_dcvg_anomaly": "Test Post TP-01"},
  {"voltage": -0.95, "off_voltage": -0.86, "latitude": -6.2009, "longitude": 106.8001, "real_distance": 100.6841260516, "condition": "PROTECTED", "comment": null, "dcp_feature_dcvg_anomaly": null},
  {"voltage": -1.25, "off_voltage": -1.21, "latitude": -6.2018, "longitude": 106.8002, "real_distance": 201.3682500319, "condition": "OVER PROTECTED", "comment": null, "dcp_feature_dcvg_anomaly": "Road crossing"},
  {"voltage": -0.7, "off_voltage": -0.8, "latitude": -6.2027, "longitude": 106.8003, "real_distance": 302.0523719402, "condition": "UNPROTECTED", "comment": null, "dcp_feature_dcvg_anomaly": null}
]
```

### Output: PCM JSON (synced)

Reversed to start at the north end like the CIPS; `real_distance`,
`current_loss_rate` and `condition` are recalculated. (The first reading has
no comment: in the reversed source, the duplicate of the `Start` reading
comes first, and `clean()` keeps the first of two duplicates.)

```json
[
  {"latitude": -6.2, "longitude": 106.8, "real_distance": 0.0, "4hz_current_a": 0.52, "dbma": 54.32, "current_loss_rate": 0.0, "depth_m": 1.2, "condition": "Medium to High", "comment_0_100": null},
  {"latitude": -6.2009, "longitude": 106.8001, "real_distance": 100.6841260516, "4hz_current_a": 0.515, "dbma": 54.24, "current_loss_rate": 0.79, "depth_m": 1.3, "condition": "Medium to High", "comment_0_100": null},
  {"latitude": -6.2027, "longitude": 106.8003, "real_distance": 302.0523719402, "4hz_current_a": 0.476, "dbma": 53.55, "current_loss_rate": 3.43, "depth_m": 1.3, "condition": "Medium to High", "comment_0_100": "End"}
]
```

### Output: ACVG/DCVG JSON

Each anomaly takes `real_distance` and `closest_cips_condition` from the
nearest reading of the synced CIPS:

```json
[
  {"latitude": -6.20005, "longitude": 106.80001, "real_distance": 0.0, "anomaly_location": "Jl. Demo 2", "surface_condition": "Aspal", "diameter": 8, "on_potential": -1.05, "off_potential": -0.88, "ir_drop": 18.0, "result_acvg": 38, "pipe_depth": 1.2, "drop_pcm": 8.1, "survey_dcvg": "2024-05-21", "survey_acvg": "2024-05-19", "closest_cips_condition": "PROTECTED"},
  {"latitude": -6.20185, "longitude": 106.80021, "real_distance": 201.3682500319, "anomaly_location": "Jl. Demo 1", "surface_condition": "Tanah", "diameter": 8, "on_potential": -1.21, "off_potential": -0.95, "ir_drop": 32.5, "result_acvg": 45, "pipe_depth": 1.5, "drop_pcm": 12.3, "survey_dcvg": "2024-05-20", "survey_acvg": "2024-05-18", "closest_cips_condition": "OVER PROTECTED"}
]
```

The normalized Excel files are written and synced next to the JSON
(`.../excel/<year>-<slug>.xlsx`). Without `acvg_dcvg`, `acvg_dcvg_json` is
`None` and nothing is written under `normalize/acvg_dcvg/`.

---

## Whole index

`uv run main.py` runs all of the above for every file. From Python:

```python
from corrosions.data.acvg_dcvg import AcvgDcvg
from corrosions.data.file_index import FileIndex

fi = FileIndex("IDDA - PCM CIPS File List.xlsx", drop_columns=["Nomor Segment"], skip_years=[2021])
fi.rebuild(source_dir=r"D:\Data\Data IDDA")            # output/raw_data/<year>/<CIPS|PCM>/
fi.check_cips_file("output/raw_data", n_jobs=8)        # CIPS(...).clean().check().save(), then normalize()
fi.check_pcm_file("output/raw_data", n_jobs=8)         # PCM(...).clean().check().save(), then normalize()
fi.to_json(n_jobs=8)                                   # file_index.json + CIPS/PCM direction sync

acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021])
acvg.load().match("output/file_index_idda-pcm-cips-file-list.csv").rebuild()
acvg.clean().normalize()                               # AcvgDcvgFile per segment, on its synced CIPS
fi.assign_acvg_dcvg(acvg.normalized_files(), counts=acvg.anomaly_counts())
```

Differences from the single-file chains:

- **Sync:** `to_json()` may reverse a segment's normalized CIPS and PCM files
  in place, so both start at the same end; distances (and the PCM loss rate
  and condition) are recalculated. ACVG/DCVG is normalized after the sync,
  so its `real_distance` follows the synced CIPS.
- **Failures** don't stop the batch: the file gets `is_valid = False` and a
  `reason` (`clean failed: …` / `normalize failed: …`) in
  `checked-cips.xlsx`, `checked-pcm.xlsx` or the `files` sheet of
  `acvg-dcvg-report.xlsx`.
- **ACVG/DCVG** batch runs `AcvgDcvgFile(...).clean().check().save()`, like
  CIPS and PCM; `n_anomalies - n_cleaned` in the `files` sheet is the number
  of anomalies `clean()` dropped.
