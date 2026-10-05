# Corrosion

Organizes, checks and normalizes corrosion survey data of underground gas
pipelines:

- **CIPS** (Close Interval Potential Survey) and **PCM** (Pipeline Current
  Mapping): one Excel file per survey, listed in a master index.
- **ACVG/DCVG**: anomaly points, one workbook per year.

**Start here: `main.py`.** It is the entry point of the project and runs the
whole pipeline: copy the files, check and clean them, normalize them to
Excel/JSON, put each segment's CIPS and PCM in the same direction, and split
the ACVG/DCVG anomalies per segment, then clean and normalize them on the
CIPS line. After [installing](#installation), run:

```bash
uv run main.py --n-jobs 8
```

---

## Requirements

### Software

| Tool | Version | Notes |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | recent | installs Python and every dependency; the only package manager used |
| Python | 3.11 | pinned in `.python-version`; uv installs it if missing |
| Excel | any | only to open the reports; close them before a rerun (Windows locks open files) |

Runtime dependencies (from `pyproject.toml`, locked in `uv.lock`): `pandas`,
`openpyxl`, `xlsxwriter`, `joblib`, `loguru`, `python-dotenv`,
`python-slugify`. Development tools: `pytest`, `ruff`, `ty`, `notebook`.

### Input files

| File / folder | Default location | Content |
| --- | --- | --- |
| CIPS/PCM index | `IDDA - PCM CIPS File List.xlsx` (repo root) | one row per segment: `Year`, `Area`, `Nomor Segment`, `Segment`, `Sub Segment`, `Diameter`, `Length`, `Province Code`, `ACVG/DCVG`, `CIPS`, `PCM` |
| CIPS/PCM source tree | `D:\Data\Data IDDA` | `<Year>\CIPS FINAL\<file>` and `<Year>\PCM FINAL\<file>`, the files named in the index |
| ACVG/DCVG index | `IDDA - ACVG FIle List.xlsx` (repo root) | `Year`, `Filename` |
| ACVG/DCVG workbooks | `D:\Data\ACVG DCVG 2021-2025` | one workbook per year, one sheet per area (Bekasi, Bogor, Cilegon, Cirebon, Jakarta, Karawang, Tangerang) |

Rules the CIPS/PCM index must follow (checked when it loads, with the Excel
row numbers of every problem):

- `Area` is filled.
- `Segment` is filled, or `Sub Segment` is (an empty `Segment` takes the
  `Sub Segment`).
- `Segment` + `Diameter` is unique (the same route with two diameters is two
  pipes and is allowed).

Each ACVG/DCVG area sheet needs `Segmen`, `Lokasi Anomali`,
`Kondisi Permukaan`, `Dia (inch)`, `Latitude`, `Longitude`,
`On Potential (volt)`, `Off Potential (volt)`, `IR Drop (%)`,
`Hasil ACVG (dB)`, `Kedalaman Pipa (m)`, `%drop PCM`, `Tgl DCVG`, `Tgl ACVG`.

Other paths can be given on the command line (`-i`, `-s`, `--acvg-index`,
`--acvg-dir`).

## Installation

```bash
git clone https://github.com/capella-cgi/corrosions.git
cd corrosions
uv sync                 # creates .venv with Python 3.11 and all dependencies
uv run pytest           # optional: check the installation (all tests pass)
```

Optional: logging to `logs/` is off by default. Turn it on with a `.env` file
in the repo root:

```bash
ENABLE_LOG=true
```

## How to

1. **Prepare the input files** listed above (index workbooks in the repo root,
   data folders on `D:\`).
2. **Run the pipeline:**

   ```bash
   uv run main.py --n-jobs 8
   ```

   It loads the index (skipping 2021 by default), copies the referenced
   files into `output/raw_data`, checks, cleans and normalizes every CIPS
   and PCM file, writes `file_index.json`, syncs the survey direction, and
   finally splits the ACVG/DCVG anomalies per segment, cleans them and
   normalizes them (each anomaly gets the position and condition of the
   nearest reading of its segment's synced CIPS).
3. **Check the reports in `output/`** (see [Outputs](#outputs)):
   - `checked-cips.xlsx` / `checked-pcm.xlsx`: rows with `is_valid = False`
     and their `reason`;
   - `file_index_excluded.json`: segments missing a normalized CIPS or PCM
     file;
   - `sync-report.xlsx`: segments whose CIPS and PCM start more than 200 m
     apart (usually the wrong file in the index);
   - `acvg-dcvg-report.xlsx`: ACVG/DCVG groups with `method = none` (not
     linked to a segment), the `load issues` sheet, and the
     `segments without ACVG-DCVG` sheet, which explains every empty
     `ACVG_DCVG` cell (e.g. `no anomaly within 500 m`: no ACVG/DCVG survey
     on that segment that year).
4. **Fix the index or the data and run again.** Every step can be repeated;
   the sync never reverses a file twice.

Common options:

```bash
uv run main.py --type cips      # CIPS only (pcm, acvg also possible)
uv run main.py --type acvg      # ACVG/DCVG only (needs the normalized CIPS of an earlier run)
uv run main.py --skip-years     # process every year (default skips 2021)
uv run main.py -y 2021 2022     # skip 2021 and 2022
uv run main.py --no-sync        # keep the normalized files in survey order
uv run main.py -o D:\out        # another output root
uv run main.py --help           # all options
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-i`, `--index` | `IDDA - PCM CIPS File List.xlsx` | CIPS/PCM index |
| `-s`, `--source-dir` | `D:\Data\Data IDDA` | CIPS/PCM source tree |
| `-d`, `--drop-columns` | `Nomor Segment` | index columns to drop |
| `-y`, `--skip-years` | `2021` | years to leave out; no value = every year |
| `-t`, `--type` | `all` | `all`, `cips`, `pcm` or `acvg` |
| `-o`, `--output-dir` | `output` | output root |
| `-n`, `--n-jobs` | `8` | parallel workers, `-1` = all cores |
| `--no-sync` | off | skip the CIPS/PCM direction sync |
| `--acvg-index` | `IDDA - ACVG FIle List.xlsx` | ACVG/DCVG index |
| `--acvg-dir` | `D:\Data\ACVG DCVG 2021-2025` | ACVG/DCVG workbooks |

With `--type all`, a missing ACVG/DCVG index or workbook is skipped with a
message so the CIPS/PCM run still finishes; `--type acvg` stops with the
error instead, and never rewrites `file_index.json`.

## Outputs

Everything goes to `output/` (or `-o`):

| Path | Content |
| --- | --- |
| `raw_data/<year>/<CIPS\|PCM>/` | copies of the indexed source files |
| `file_index_<index name>.csv` | the index after `fix()`, with the `ACVG_DCVG` column |
| `checked-cips.xlsx` | per CIPS file: data sheet used (`sheet_name`, `candidate_sheets`), `has_voltage`, missing columns, duplicate GPS rows, `cleaned_path`, `cips_protection`, `protected_percentage`, `unprotected_percentage`, `normalized_cips_file`, `reason` |
| `checked-pcm.xlsx` | per PCM file: missing columns, duplicate GPS rows, `normalized_pcm_file`, `medium_to_poor_percentage`, `medium_to_high_percentage`, `reason` |
| `cleaned/<year>/<CIPS\|PCM\|ACVG_DCVG>/` | cleaned copies (empty/zero coordinates and duplicates removed, CIPS voltages normalized) |
| `normalize/<cips\|pcm>/<excel\|json>/<year>-<slug>.*` | (another folder with `normalize(normalize_dir=...)` from Python) normalized surveys: distances, CIPS `condition` (PROTECTED / OVER PROTECTED / UNPROTECTED), PCM `dbma`, `current_loss_rate`, `condition` |
| `normalize/acvg_dcvg/<excel\|json>/<year>-acvg-dcvg-<segment>-<dia>-<area>.*` | normalized anomalies, sorted along the line: `real_distance` and `closest_cips_condition` from the nearest CIPS reading (empty when the segment has no CIPS line), the ACVG/DCVG readings, dates as `YYYY-MM-DD`; the Excel also has `CIPS Offset (m)` |
| `file_index.json` | one record per segment with both a normalized CIPS and PCM file (`year`, `area`, `area_code`, `province_code`, `name`, `code`, `diameter`, `pipe_length`, `cips_protection`, `protected`, `unprotected`, `total_anomaly`, `medium_to_poor`, `medium_to_high`, `acvg_dcvg_normalized_file`, `cips_normalized_file`, `pcm_normalized_file`; `protected` / `unprotected` are the % of CIPS readings (over) protected / unprotected, `medium_to_poor` / `medium_to_high` the % of PCM readings per condition; `total_anomaly` (number of ACVG/DCVG anomalies) and `acvg_dcvg_normalized_file` are filled after the ACVG/DCVG step, `null` for segments without ACVG/DCVG) |
| `file_index_excluded.json` | the other segments, with their source files and a `missing` list |
| `area.json` | one summary per area and year (`code` = `area_code`): `name`, `code`, `year`, `total_length` (sum of `pipe_length`), `protected` / `unprotected` / `medium_to_poor` / `medium_to_high` (simple mean of the segments' percentages, 2 decimals), `total_anomaly` (sum), `province_code` |
| `sync-report.xlsx` | per segment: `cips_axis`, `cips_reversed`, `pcm_reversed`, `start_gap_m`, file paths |
| `raw_data/<year>/ACVG_DCVG/acvg-dcvg-<segment>-<dia>-<area>.xlsx` | ACVG/DCVG anomalies per segment |
| `acvg-dcvg-report.xlsx` | `groups` (how each ACVG/DCVG group was matched: `name`, `cips` or `none`, distance, file), `files` (per extracted file: anomalies before/after cleaning, CIPS file, normalized file, `n_on_cips`, `reason`), `load issues`, and `segments without ACVG-DCVG` (every index row without a file, with the reason and the distance to the nearest anomaly) |

How the sync works: each segment's CIPS starts at its west end (west-east
lines) or north end (north-south lines), and its PCM starts at the end
closer to the CIPS start. Reversed files get their distances (and PCM loss
rate / condition) recalculated; JSON and Excel stay identical.

How ACVG/DCVG is matched: a group whose segment name equals an index
segment goes to that segment; every other anomaly goes, one by one, to the
same-year CIPS track it lies on (up to 500 m away). So anomalies named after
a whole pipeline are split over the index sections they lie on.

## Using the package from Python

`main.py` is the normal way in. The classes below are what it calls, for
notebooks or one-off checks:

```python
from corrosions.data.file_index import FileIndex
from corrosions.data.cips import CIPS
from corrosions.data.pcm import PCM
from corrosions.data.acvg_dcvg import AcvgDcvg

# one file
cips = CIPS("output/raw_data/2025/CIPS/<file>.xlsx", year=2025).fix().check().clean().save().normalize()
pcm = PCM("output/raw_data/2025/PCM/<file>.xlsx", year=2025).clean().save().normalize()

# the whole index (what main.py does)
fi = FileIndex("IDDA - PCM CIPS File List.xlsx", drop_columns=["Nomor Segment"], skip_years=[2021])
fi.rebuild(source_dir=r"D:\Data\Data IDDA")
fi.check_cips_file("output/raw_data", n_jobs=8)
fi.check_pcm_file("output/raw_data", n_jobs=8)
fi.to_json(n_jobs=8)                       # also syncs the CIPS/PCM direction
fi.sync_report

# ACVG/DCVG
acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021])
acvg.load().match("output/file_index_idda-pcm-cips-file-list.csv").rebuild()
acvg.clean().normalize()                  # cleaned/<year>/ACVG_DCVG, normalize/acvg_dcvg
acvg.assign_index()
fi.assign_acvg_dcvg(acvg.normalized_files(), counts=acvg.anomaly_counts())  # acvg_dcvg_normalized_file + total_anomaly in file_index.json
```

### Checking one file: `check()` and `report`

`check()` (on `CIPS`, `PCM` and `AcvgDcvgFile`) never raises: it stores a
quality summary on `report` (a `dict`, empty until `check()` runs) and
returns the object, so it chains like the other steps. It checks whatever
`df` holds when it is called, so its place in the chain matters: CIPS checks
the raw data (after `fix()`), PCM checks the cleaned data
(`clean().save().check()` in `check_pcm_file`).

```python
cips = CIPS("output/raw_data/2025/CIPS/<file>.xlsx", year=2025).fix().check()
cips.report["is_valid"]          # False -> look at missing_columns / has_voltage
cips.report["missing_columns"]
```

| Key | Meaning |
| --- | --- |
| `filepath` | source file |
| `sheet_name` | sheet the data was read from |
| `is_valid` | no missing required column and no duplicate GPS rows; CIPS: no missing required column and `has_voltage` (duplicates allowed, `clean()` removes them) |
| `n_missing` / `missing_columns` | required columns not in the file (`None` when all present) |
| `n_duplicates` / `duplicates` | rows sharing a latitude/longitude pair; `duplicates` lists each as `{"row": <index>, <lat>: ..., <lon>: ...}` (`None` when there are none) |
| `has_voltage` | CIPS only: an ICCP (`On`/`Off Voltage`) or SACP (`Voltage`) column is present |

`normalize()` then adds its results to the same `report`, keeping the
`check()` keys (`check()` replaces the whole report, so run it first):

| Key | Meaning |
| --- | --- |
| `normalized` | `True` once both normalized files are written |
| `n_normalized` | rows in the normalized files |
| `normalize_excel_filepath` / `normalize_json_filepath` | the files written |
| `protection` | CIPS: `ICCP` or `SACP` |
| `length_m` | CIPS, PCM: survey length (last `Real Distance`, meters) |
| `protected_percentage` / `unprotected_percentage` | CIPS: % of readings (over) protected / unprotected |
| `medium_to_high_percentage` / `medium_to_poor_percentage` | PCM: % of readings per condition |
| `count` / `n_on_cips` / `cips_json` | ACVG/DCVG: anomalies, anomalies placed on the CIPS line, CIPS JSON used |

```python
cips = cips.clean().normalize()
cips.report["protected_percentage"], cips.report["length_m"]
```

Every `normalize()` (`CIPS`, `PCM`, `AcvgDcvgFile`, and `AcvgDcvg`, which
passes it on to each file) takes `normalize_dir=None`. It replaces the
default `output/normalize/<cips|pcm|acvg_dcvg>`: the files go to
`<normalize_dir>/excel` and `<normalize_dir>/json`.

```python
pcm.clean().normalize(normalize_dir="D:/tmp/pcm")   # D:/tmp/pcm/json/<year>-<slug>.json
```

The sync and the ACVG/DCVG matching still read the normalized CIPS/PCM from
`output/normalize/`, so `main.py` keeps the default.

`check_cips_file` / `check_pcm_file` put one `report` per file into
`checked-cips.xlsx` / `checked-pcm.xlsx`, next to the clean/normalize
results and a `reason` for any failure; the CIPS report leaves out the
`duplicates` list (too long for an Excel cell).

Full API: [wiki/API-Reference.md](wiki/API-Reference.md).

## Development

```bash
uv run pytest                  # tests (tests/)
uv run ruff check --fix src/   # lint
uv run ruff format .           # format
uvx ty check src/              # type check
```

## Other workflow (notebooks)

Steps used after this pipeline; the notebooks below are not part of this
repository:

1. Extract indirects > run `data-2025.ipynb`
2. Check `/tests/files.xlsx`
3. Run `all.ipynb`
4. Run `sync.ipynb`
5. Run `calculate-stats.ipynb`
6. Run `seeder-builder.ipynb`
