# API Reference

This page documents the public API of the `corrosions` package as of
version **0.3.0**. It is organized by module. All symbols are importable from
their fully qualified paths shown in each section.

- [`corrosions`](#corrosions) — package metadata
- [`corrosions.logging`](#corrosionslogging) — logging configuration
- [`corrosions.data.file_index`](#corrosionsdatafile_index) — `FileIndex`
- [`corrosions.data.base_data`](#corrosionsdatabase_data) — `BaseData`
- [`corrosions.data.pcm`](#corrosionsdatapcm) — `PCM`
- [`corrosions.data.cips`](#corrosionsdatacips) — `CIPS`
- [`corrosions.utils.dataframe_utils`](#corrosionsutilsdataframe_utils) — Excel sheet helpers
- [`corrosions.utils.path_utils`](#corrosionsutilspath_utils) — path helpers
- [`corrosions.utils.geo_utils`](#corrosionsutilsgeo_utils) — distance between coordinates

---

## `corrosions`

Top-level package. Exposes metadata constants only.

| Symbol | Type | Description |
| --- | --- | --- |
| `__version__` | `str` | Installed package version (read via `importlib.metadata`). |
| `__author__` | `str` | Package author. |
| `__author_email__` | `str` | Author email. |
| `__license__` | `str` | SPDX license identifier (`"MIT"`). |
| `__copyright__` | `str` | Copyright notice. |
| `__url__` | `str` | Upstream repository URL. |

```python
import corrosions
print(corrosions.__version__)
```

---

## `corrosions.logging`

Loguru-based logging bootstrap. Handlers are only installed automatically when
the environment variable `ENABLE_LOG=true` is set at import time. The default
log directory is `<cwd>/logs`.

### Constants (module-private)

- `_GENERAL_LOG_RETENTION = "30 days"` — retention for the general log.
- `_ERROR_LOG_RETENTION = "90 days"` — retention for the errors log.
- `_FILE_FORMAT`, `_CONSOLE_FORMAT` — loguru format strings.

### Log files

When enabled, two rotating log files are written under the current log
directory, rotating at midnight and compressed to `.zip`:

| File pattern | Level | Retention |
| --- | --- | --- |
| `corrosions_{time:YYYY-MM-DD}.log` | `DEBUG`+ | 30 days |
| `errors_{time:YYYY-MM-DD}.log` | `ERROR`+ | 90 days |

### Functions

#### `set_log_level(level: str) -> None`

Change the console log level dynamically. File handlers keep their original
levels (`DEBUG` and `ERROR`).

- **`level`** — one of `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`,
  `"CRITICAL"` (case-insensitive).
- **Raises** `ValueError` if `level` is not a loguru level name.

#### `set_log_directory(log_dir: Path | str) -> None`

Change the log file directory dynamically. The directory is created if it
does not exist and all handlers are re-installed there.

- **Raises** `PermissionError` if the process cannot create the directory.

#### `disable_logging() -> None`

Remove all active loguru handlers and set `ENABLE_LOG=false`. Nothing is
written to console or file until logging is re-enabled.

#### `enable_logging() -> None`

Restore console and file handlers using the current log directory and set
`ENABLE_LOG=true`. Safe to call when logging is already active.

```python
from corrosions.logging import logger, set_log_level, enable_logging

enable_logging()
set_log_level("DEBUG")
logger.info("hello")
```

---

## `corrosions.data.file_index`

Excel-backed index of CIPS and PCM survey files.

### `class FileIndex`

Loads an Excel file that lists corrosion survey data per year, area, and
segment, and provides helpers to validate, normalize, copy, and quality-check
the referenced files.

#### Class attributes

| Attribute | Type | Value |
| --- | --- | --- |
| `COLUMNS` | `list[str]` | Required source columns: `Year`, `Area`, `Segment`, `Sub Segment`, `Diameter`, `Length`, `Province Code`, `ACVG/DCVG`, `CIPS`, `PCM`. |
| `DATA_TYPES` | `tuple[str, str]` | `("CIPS", "PCM")` — data types looked up on disk. |

#### Instance attributes

| Attribute | Type | Description |
| --- | --- | --- |
| `filepath` | `str` | Path to the source Excel file. |
| `filename` | `str` | Basename of the source Excel file. |
| `filename_slug` | `str` | Slugified filename stem, used for output artifacts. |
| `df` | `pd.DataFrame` | Working DataFrame derived from the source Excel. |
| `checked` | `bool` | `True` after `check_existing_file()` has been run. |
| `fixed` | `bool` | `True` after `fix()` has been run. |
| `skip_years` | `list[int]` | Survey years removed from `df` at load time (sorted, deduplicated). |
| `verbose` | `bool` | If `True`, `fix()` emits progress messages. |

#### `__init__(filepath, drop_columns=None, skip_years=None, verbose=False)`

Load the Excel file, optionally drop columns, validate schema, coerce
`Year`, `Diameter`, `Length`, and `Province Code` to their expected dtypes,
then remove the rows of `skip_years`.

- **`filepath`** *(str)* — path to the source Excel file.
- **`drop_columns`** *(str | list[str] | None)* — columns to drop after load.
- **`skip_years`** *(list[int] | None)* — survey years to leave out, e.g.
  `[2021]` for exports the CIPS/PCM loaders cannot read. Their rows are
  removed from `df` right after loading (index reset), so every method
  ignores them, for both CIPS and PCM: `check_existing_file`, `rebuild`,
  `check_pcm_file`, `check_cips_file`, `by_year`, `save`, … Defaults to
  `None` (no year skipped).
- **`verbose`** *(bool)* — enable progress logging inside `fix()`.
- **Raises** `FileNotFoundError` if the file does not exist; `KeyError` if a
  required column is missing after `drop_columns` is applied.

#### `validate() -> None`

Ensure every column in `COLUMNS` is present in `df`. Raises `KeyError`
otherwise.

#### `check_existing_file(data_dir: str) -> Self`

For each data type in `DATA_TYPES`, add a boolean column
`"<data_type> File Exists"` that is `True` when the referenced file exists at
`<data_dir>/<Year>/<data_type> FINAL/<filename>`. Sets `self.checked = True`
and returns `self` for chaining.

#### `fix() -> Self`

Normalize the working DataFrame in place:

- Back-fill any missing `Segment` value from `Sub Segment`.
- Append `.xlsx` to any `CIPS`/`PCM` filename that lacks the suffix.

Sets `self.fixed = True`. When `verbose=True`, logs the count of updated
segments and filenames. Returns `self` for chaining.

#### `by_year(value: int) -> pd.DataFrame`

Return a copy of `df` filtered to `Year == value`.

#### `by_columns(columns: str | list[str]) -> pd.DataFrame`

Return a copy of `df` restricted to the given columns. Accepts a single
column name or a list. Raises `KeyError` on unknown column names.

#### `rebuild(source_dir, output_dir=None, destination_dir="raw_data") -> Self`

Copy every referenced file from `source_dir` into a clean output tree.

Behavior:

1. Runs `fix()` if not already applied, so filenames get their `.xlsx`
   suffix before they are looked up on disk.
2. Runs `check_existing_file(source_dir)`.
3. Resolves `output_dir` (defaults to `<cwd>/output`).
4. For each existing referenced file, copies it (via `shutil.copy2`) to
   `<output_dir>/<destination_dir>/<Year>/<data_type>/<filename>`. Existing
   destination files are skipped.
5. Logs a summary of `copied` vs. `skipped` file counts.
6. Calls `self.save()` to write the updated CSV.

Returns `self` for chaining.

#### `check_pcm_file(data_dir: str, n_jobs: int = 1) -> pd.DataFrame`

Run `PCM(...).clean().save().check()` on every referenced PCM file, in
parallel via joblib's `loky` backend when `n_jobs > 1` (or `-1` for all
cores). Each cleaned copy is written to `output/cleaned/<year>/PCM/`, and
the report describes the cleaned data.

Returns a DataFrame with one row per index entry and columns:

| Column | Description |
| --- | --- |
| `year` | Survey year for the row. |
| `filepath` | Full path to the referenced PCM file. |
| `is_valid` | `True` when no missing columns and no duplicates. |
| `n_missing` | Number of missing required columns. |
| `n_duplicates` | Number of duplicate rows by `(Int GPS Latitude, Int GPS Longitude)`. |
| `missing_columns` | Names of missing required columns. |
| `duplicates` | Duplicate row records. |
| `reason` | Populated when the row failed to load (missing file, exception, …). |

#### `check_cips_file(data_dir: str, n_jobs: int = 1) -> pd.DataFrame`

Run [`CIPS(...).fix().check()`](#corrosionsdatacips) on every referenced CIPS
file at `<data_dir>/<Year>/CIPS/<filename>`, in parallel via joblib's `loky`
backend like `check_pcm_file`. The data sheet is located, column names
are aligned, then checked. Then `clean().save()` writes a cleaned copy to
`<cwd>/output/cleaned/<year>/CIPS/` and [`normalize()`](#normalize---self)
writes the normalized Excel/JSON under `<cwd>/output/normalize/cips/`. The
steps are separate, so a file that fails to clean still reports its column
checks. Check columns describe the file before cleaning.

It also adds two columns to `df`, used by [`to_json`](#to_jsonoutput_dir-str--none--none---str).
They are empty for rows without a CIPS file, or whose file failed to
clean/normalize:

- `normalized_cips_file`: filename of the normalized JSON
  (`CIPS.normalize_json_filepath`), e.g. `2025-cips-sacp-01-jkt-….json`.
- `cips_protection`: `"ICCP"` or `"SACP"`.

The workers run in separate processes, so these values are returned with
each result and merged into `df` by row afterwards.

| Column | Description |
| --- | --- |
| `year` | Survey year for the row. |
| `filepath` | Full path to the referenced CIPS file. |
| `is_valid` | `True` when no required column is missing, a voltage column exists, and `clean()` and `normalize()` succeeded. Duplicates do not count. |
| `sheet_name` | Sheet that was loaded. |
| `candidate_sheets` | Every qualifying sheet, best match first. |
| `has_voltage` | At least one of `On Voltage`, `Off Voltage`, `Voltage` present. |
| `n_missing` / `missing_columns` | Required columns missing after `fix()`. |
| `n_duplicates` | Rows sharing a `(Latitude, Longitude)` pair. `clean()` removes them. The per-row list is left out because it can exceed Excel's cell limit. |
| `cleaned_path` | Path of the saved cleaned copy; empty when cleaning failed. |
| `cips_protection` | `"ICCP"` / `"SACP"`; empty when cleaning failed. |
| `normalized_cips_file` | Filename of the normalized JSON; empty when cleaning or normalizing failed. |
| `reason` | Populated when the file is missing, has no data sheet, or fails to load, or when cleaning or normalizing fails (prefixed `clean failed:` / `normalize failed:`). |

#### `to_json(output_dir: str | None = None) -> str`

Write the index as JSON records to `<output_dir>/file_index.json`
(`output_dir` defaults to `<cwd>/output`) and return the path. Runs `fix()`
first if needed, so empty `Segment` values are filled from `Sub Segment`.
Empty values are written as `null`.

| Key | Source |
| --- | --- |
| `id` | Row position, `0..n-1`. |
| `year`, `area` | `Year`, `Area`. |
| `area_code` | Slug of `<area>-<year>`, e.g. `jakarta-2025`. |
| `segment` | `Segment`. |
| `pipe_diameter` | `Diameter`, as an int when whole (`16`, not `16.0`). |
| `length` | `Length`, always a float (`2.0` stays `2.0`). |
| `segment_code` | Slug of `<segment>-<pipe_diameter>`, e.g. `pipa-servis-indonesia-power-16`. |
| `cips_protection`, `normalized_cips_file` | Set by `check_cips_file`; `null` until it ran. |

```python
index.check_cips_file("output/raw_data", n_jobs=-1)
index.to_json()   # "output/file_index.json"
```

#### `save(output_dir: str | None = None) -> None`

Write the current `df` to `<output_dir>/file_index_<filename_slug>.csv`.
`output_dir` defaults to `<cwd>/output`.

#### End-to-end example

```python
from corrosions.data.file_index import FileIndex

index = FileIndex("IDDA - File List.xlsx", verbose=True)
index.rebuild(source_dir="//nas/surveys", destination_dir="data")
report = index.check_pcm_file("output/data", n_jobs=-1)
cips_report = index.check_cips_file("output/raw_data", n_jobs=-1)
```

---

## `corrosions.data.base_data`

### `class BaseData`

Shared load / check / clean / save pipeline for one survey Excel file.
Subclasses ([`PCM`](#corrosionsdatapcm), [`CIPS`](#corrosionsdatacips))
declare their schema through class attributes and inherit a fluent pipeline:

```python
PCM("data/2024/PCM/segment-01.xlsx", year=2024).check().clean().save()
```

Every pipeline method returns `self`, so steps can run in any order.
`check()` reports on whatever `df` holds at the moment it is called: call it
before `clean()` to check the raw data and after to check the cleaned data.

#### Class attributes (set by subclasses)

| Attribute | Type | Purpose |
| --- | --- | --- |
| `KIND` | `Literal["pcm", "cips"]` | Survey type; names the cleaned output sub-directory (upper-cased) and the normalize one (lower-cased). |
| `REQUIRED_COLUMNS` | `list[str]` | Columns expected in the source Excel, checked by `check()`. |
| `NUMERIC_COLUMNS` | `list[str]` | Columns coerced with `pd.to_numeric(..., errors="coerce")` at load time. |
| `CLEAN_REQUIRED_COLUMNS` | `list[str]` | Columns whose non-NaN value is required for a row to survive `clean()`. |
| `UNIQUE_COLUMNS` | `tuple[str, str]` | The (latitude, longitude) pair. `check()` counts rows sharing a pair; `clean()` drops rows where either is `0` and keeps the first row of each pair. |

#### Instance attributes

| Attribute | Type | Description |
| --- | --- | --- |
| `filepath` | `str` | Path to the source Excel file. |
| `sheet_name` | `int \| str` | Sheet loaded into `df`, chosen by `find_sheet`. |
| `df` | `pd.DataFrame` | Working DataFrame with numeric columns coerced. |
| `year` | `int` | Survey year for this file. |
| `output_dir` | `str` | Resolved output directory. |
| `cleaned_dir` | `str` | `<output_dir>/cleaned/<year>/<KIND>`. |
| `cleaned_path` | `str \| None` | Path of the saved Excel once `save()` ran. |
| `normalize_dir` | `str` | `<output_dir>/normalize/<kind>`. |
| `normalize_excel_dir` | `str` | `<normalize_dir>/excel`. |
| `normalize_json_dir` | `str` | `<normalize_dir>/json`. |
| `normalize_excel_filepath` | `str` | Excel written by a subclass `normalize()`: `<normalize_excel_dir>/<year>-<slug>.xlsx` (`<slug>` = slugified source filename without its extension). |
| `normalize_json_filepath` | `str` | JSON written by a subclass `normalize()`: `<normalize_json_dir>/<year>-<slug>.json`. |
| `normalized` | `bool` | `True` once a subclass `normalize()` wrote both files. Stays `False` for subclasses without `normalize()` (`PCM`). |
| `report` | `dict` | Summary from the last `check()` call; empty until then. |
| `verbose` | `bool` | If `True`, methods may emit progress messages. |

#### `__init__(filepath, year, output_dir=None, verbose=False)`

Load the sheet returned by `find_sheet(filepath)`, strip whitespace from
column names (as `get_sheet_columns` does), and coerce every
`NUMERIC_COLUMNS` entry that is present.

- **`filepath`** *(str)* — path to the source Excel file.
- **`year`** *(int)* — survey year.
- **`output_dir`** *(str | None)* — defaults to `<cwd>/output` via
  `resolve_output_dir`.
- **`verbose`** *(bool)* — enables progress logging.
- **Raises** `FileNotFoundError` if `filepath` does not exist, or
  `ValueError` if `find_sheet` finds no usable sheet.

#### `find_sheet(filepath: str) -> int | str` *(classmethod)*

Return the sheet holding the survey data. The default is `0` (first sheet);
`CIPS` overrides it.

#### `check() -> Self`

Check the current `df` and store the summary on `self.report`. Nothing is
raised. The check confirms that every column in `REQUIRED_COLUMNS` is present
and that rows are unique on `UNIQUE_COLUMNS`.

`report` keys:

| Key | Type | Description |
| --- | --- | --- |
| `filepath` | `str` | Source file path. |
| `sheet_name` | `int \| str` | Sheet the data was loaded from. |
| `is_valid` | `bool` | `True` when there are no missing columns and no duplicates. |
| `n_missing` | `int` | Count of missing required columns. |
| `n_duplicates` | `int` | Count of duplicate rows by `UNIQUE_COLUMNS`. |
| `missing_columns` | `list[str] \| None` | Names of missing required columns (or `None` when none). |
| `duplicates` | `list[dict] \| None` | One dict per duplicate row (`row` index + unique-column values), or `None` when none. |

#### `clean() -> Self`

Drop unusable rows, in order (each step uses only the columns present):

1. Rows empty across every column.
2. Rows whose latitude or longitude (`UNIQUE_COLUMNS`) is `0` (no GPS fix).
3. Rows with any `NaN` in `CLEAN_REQUIRED_COLUMNS`. These include the
   coordinates, so rows with an empty latitude or longitude go here.
4. Duplicate `UNIQUE_COLUMNS` rows, keeping the first reading at each
   position.

Mutates `self.df`. It does **not** save; chain `.save()` to write the result.

- **Raises** `ValueError` if no row is left.

#### `save() -> Self`

Write the current `df` to `<cleaned_dir>/<original_filename>`, creating
`cleaned_dir` if needed, and set `self.cleaned_path`.

---

## `corrosions.data.pcm`

### `class PCM(BaseData)`

Single-file Pipeline Current Mapping (PCM) survey reader. Inherits
`check()` / `clean()` / `save()` from [`BaseData`](#corrosionsdatabase_data).

| Attribute | Value |
| --- | --- |
| `KIND` | `"pcm"` |
| `REQUIRED_COLUMNS` | `Index`, `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Ext GPS Latitude`, `Ext GPS Longitude`, `Survey name (0-100)`, `Gain (dB)` |
| `NUMERIC_COLUMNS` | `Index`, `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Gain (dB)` |
| `CLEAN_REQUIRED_COLUMNS` | `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Gain (dB)` (Ext GPS columns are excluded because they are frequently blank) |
| `UNIQUE_COLUMNS` | `("Int GPS Latitude", "Int GPS Longitude")` |

```python
from corrosions.data.pcm import PCM

pcm = PCM("data/2024/PCM/segment-01.xlsx", year=2024).check().clean().save()
pcm.report["is_valid"]   # quality of the raw data
pcm.cleaned_path         # "output/cleaned/2024/PCM/segment-01.xlsx"
```

---

## `corrosions.data.cips`

### `class CIPS(BaseData)`

Single-file Close Interval Potential Survey (CIPS) reader. Inherits `save()`
from [`BaseData`](#corrosionsdatabase_data). It overrides `find_sheet()` to
locate the data sheet, and `check()` and `clean()` to apply CIPS rules. It
adds `fix()` to align column names across export formats.

```python
from corrosions.data.cips import CIPS

cips = CIPS("data/2022/CIPS/segment-01.xlsx", year=2022).fix().check().clean().save()
cips.report["is_valid"]   # columns OK after fix()
cips.protection           # "ICCP" or "SACP"
```

| Attribute | Value |
| --- | --- |
| `KIND` | `"cips"` |
| `REQUIRED_COLUMNS` | `Latitude`, `Longitude`, `Comment`, `DCP/Feature/DCVG Anomaly` |
| `NUMERIC_COLUMNS` | `Latitude`, `Longitude` |
| `CLEAN_REQUIRED_COLUMNS` | `Latitude`, `Longitude`, `Voltage` |
| `UNIQUE_COLUMNS` | `("Latitude", "Longitude")` |
| `ICCP_COLUMNS` / `SACP_COLUMNS` | `On Voltage`, `Off Voltage` / `Voltage` |
| `SHEET_COLUMNS` | `Latitude`, `Longitude`, `DCP/Feature/DCVG Anomaly`: header that marks a sheet as CIPS data (a subset of `REQUIRED_COLUMNS`) |
| `SHEET_POSSIBILITIES` | `Data`, `Sheet1`, `Sequential File`, `Sequential Files`: preferred names when several sheets qualify |
| `RENAME_COLUMNS` | `Voltage (V)` → `Voltage`, `Off Voltage (V)` → `Off Voltage` |

Extra instance attributes: `protection` (`"ICCP"` or `"SACP"`, set by
`clean()`), `fixed` (`True` once `fix()` ran) and `cleaned` (`True` once
`clean()` completed; `normalize()` requires it).

#### `data_sheets(sheet_columns: dict[str, list[str]]) -> list[str]` *(classmethod)*

Given each sheet's header row (from `get_sheet_columns`), return the sheets
whose header contains every `SHEET_COLUMNS` entry, best match first. Names in
`SHEET_POSSIBILITIES` come first (in that order), then the rest in workbook
order. This excludes chart, `DCP Data` (which uses `DCP/Feature/Anomaly`),
`Survey Info` and empty sheets, and ranks `Data` ahead of copies like
`Raw Data`.

#### `find_sheet(filepath: str) -> str` *(classmethod)*

Read only the header row of each sheet and return `data_sheets(...)[0]`.
Raises `ValueError` (listing the sheet names) when no sheet qualifies. Called
by `__init__`, so a CIPS file without a data sheet fails at construction.

#### `fix() -> Self`

Align column names across export formats:

- Rename per `RENAME_COLUMNS`, unless the target column already exists.
  Other voltage columns (`-mV On`, `Potential (-mV)`, `On Potential (mV)`, …)
  are left untouched.
- Add an empty `Comment` column when there is none.

Never raises, and running it twice is a no-op. To leave out a year whose
exports `fix()` cannot align (such as 2021 `-mV` exports), pass
`skip_years` to the [`FileIndex`](#class-fileindex) constructor.

#### `check() -> Self`

`BaseData.check()` plus:

- `has_voltage`: at least one of `ICCP_COLUMNS` / `SACP_COLUMNS` present.
  The file is invalid without one.

`is_valid` is `n_missing == 0 and has_voltage`. Duplicates are still counted
in `n_duplicates` but do not affect `is_valid`, because `clean()` removes them.
Call `fix()` first to check the data as `clean()` will see it.

#### `clean() -> Self`

1. Runs `fix()` if it has not run yet.
2. Normalizes voltages into a single `Voltage` column:
   - `On Voltage` + `Off Voltage` → **ICCP**.
   - `Voltage` + `Off Voltage` without `On Voltage` (2022 exports after
     `fix()`, 2024 exports) → ICCP and SACP surveys share this layout, so the
     filename decides (`ICCP` / `SACP` as a whole word). ICCP takes `Voltage`
     as the ON reading.
   - `Voltage` only → **SACP**.

   Readings are stored as negative potentials: a column whose first
   non-empty reading is positive is negated as a whole. ICCP copies `On Voltage` into
   `Voltage` and negates `Voltage` and `Off Voltage` separately. SACP
   negates `Voltage` and sets `On Voltage` / `Off Voltage` to NaN. Both add a
   `Protection` column and set `self.protection`.
3. ICCP only: drops rows with an empty `On Voltage` or `Off Voltage`, since
   an ICCP reading needs both. SACP only needs `Voltage`.
4. `BaseData.clean()` drops:
   - all-empty rows;
   - rows whose `Latitude` or `Longitude` is `0` or empty;
   - rows with an empty `Voltage`;
   - duplicate `(Latitude, Longitude)` rows, keeping the first reading.

- **Raises** `ValueError` if no voltage layout matches, if the filename is
  needed but names neither (or both) `ICCP` / `SACP`, or if no row is left.

#### `normalize() -> Self`

Add distances and a protection condition to `df`, then save it as Excel
and JSON. Distances are computed with
[`calculate_distance`](#corrosionsutilsgeo_utils) on whole columns.

| Added column | Description |
| --- | --- |
| `Distance` | Meters from the previous reading (`0` for the first). |
| `Real Distance` | Running total from the first reading, in meters. |
| `Condition` | `PROTECTED` (`-1.2 < V <= -0.85`), `OVER PROTECTED` (`V <= -1.2`) or `UNPROTECTED` (anything else, including an empty reading). `V` is `Off Voltage` for ICCP and `Voltage` for SACP, in volts. |

| File | Content |
| --- | --- |
| `normalize_excel_filepath` = `<output_dir>/normalize/cips/excel/<year>-<slug>.xlsx` | `df` with its original column names, without the index. |
| `normalize_json_filepath` = `<output_dir>/normalize/cips/json/<year>-<slug>.json` | One record per row with only these keys, in this order: `voltage`, `off_voltage`, `latitude`, `longitude`, `real_distance`, `condition`, `comment`, `dcp_feature_dcvg_anomaly`. Empty cells are `null`, including empty or blank text (such as the `""` `Comment` added by `fix()`). `off_voltage` is always `null` for SACP. |

`<slug>` is the slugified source filename without its extension. `df` keeps
the original column names, and `normalized` is set to `True` once both files
are written.

Rows are taken in their current order. The index is not used, so the gaps
`clean()` leaves in it are fine. Call it after `clean()`, which sets
`protection` and makes sure every coordinate is present and deduplicated.
Raises `RuntimeError` if `clean()` has not completed. `fix()` alone is not
enough, because `clean()` is what sets `protection` and the voltage columns
`normalize()` reads.

```python
cips = CIPS("segment.xlsx", year=2024).clean().normalize()
cips.df["Real Distance"].iloc[-1]   # survey length in meters
cips.normalize_json_filepath        # "output/normalize/cips/json/2024-segment.json"
```

---

## `corrosions.utils.dataframe_utils`

### `get_sheets(filepath: str) -> list[int | str]`

Return the sheet names of an Excel file. Raises `FileNotFoundError` if the
file is missing and `ValueError` if it has no sheets.

### `get_sheet_columns(filepath: str) -> dict[str, list[str]]`

Return each sheet's header row (column names as stripped `str`), in workbook
order. Only the first row of every sheet is parsed. Empty sheets map to `[]`.

```python
from corrosions.utils.dataframe_utils import get_sheet_columns

get_sheet_columns("survey.xlsx")
# {'Data': ['Data No', 'Latitude', ...], 'Grafik': []}
```

---

## `corrosions.utils.path_utils`

### `resolve_output_dir(output_dir: str | None = None) -> str`

Resolve and create an output directory, defaulting to `<cwd>/output`. When
`output_dir` is `None`, `os.path.join(os.getcwd(), "output")` is used. The
directory is created (`os.makedirs(..., exist_ok=True)`) and returned.

```python
from corrosions.utils.path_utils import resolve_output_dir

out = resolve_output_dir()             # -> "<cwd>/output"
out = resolve_output_dir("custom/out") # -> "custom/out" (created if missing)
```

---

## `corrosions.utils.geo_utils`

Also importable from `corrosions.utils`.

### `EARTH_RADIUS_M: float`

Mean Earth radius, `6_371_000.0` meters.

### `calculate_distance(lat1, lon1, lat2, lon2) -> float | np.ndarray | pd.Series`

Great-circle distance in **meters** between two points given in **degrees**,
using the haversine formula on a sphere of radius `EARTH_RADIUS_M`.

- Works on scalars, numpy arrays and pandas Series. Inputs broadcast, so one
  side can be a single point.
- Scalar inputs return a `float`. Series inputs return a Series with the same
  index.
- A NaN coordinate gives a NaN distance.

```python
from corrosions.utils import calculate_distance

calculate_distance(-6.1, 106.1, -6.101, 106.1)   # 111.19...

# distance from each reading to the previous one (first row is NaN)
df["distance"] = calculate_distance(
    df["Latitude"].shift(), df["Longitude"].shift(),
    df["Latitude"], df["Longitude"],
)
```
