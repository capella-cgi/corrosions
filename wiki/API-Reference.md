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
- [`corrosions.sync`](#corrosionssync) — `SyncData`: same survey direction for CIPS and PCM
- [`corrosions.data.acvg_dcvg`](#corrosionsdataacvg_dcvg) — `AcvgDcvg`: ACVG/DCVG anomalies per segment; `AcvgDcvgFile`: clean / normalize one segment file

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
| `sync_report` | `pd.DataFrame \| None` | `SyncData` report from the last `to_json(sync=True)`; `None` until then. |
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
  required column is missing after `drop_columns` is applied; `ValueError`
  from [`validate_values`](#validate_valuesexcel_rows-pdseries--none--none---none)
  if a row kept after `skip_years` has an empty `Area`, or an empty
  `Segment` with no `Sub Segment` to fill it, or if the filled `Segment` +
  `Diameter` is not unique.

#### `validate() -> None`

Ensure every column in `COLUMNS` is present in `df`. Raises `KeyError`
otherwise.

#### `validate_values(excel_rows: pd.Series | None = None) -> None`

Ensure every row has the values the index needs. Called by `__init__` after
`skip_years` is applied, so rows from skipped years are not checked.

- `Area` must not be empty.
- `Segment` may be empty only when `Sub Segment` is filled, because `fix()`
  copies `Sub Segment` into an empty `Segment`. `Sub Segment` on its own may
  be empty.
- The segment after that fill (`Segment`, else `Sub Segment`) together with
  `Diameter` must be unique, so every row gets its own `code` in
  `to_json`. The same route with two diameters (e.g. `Unisma - Pd Ungu` at
  16 and 10 inch) is two pipes and allowed.
- Text is compared with surrounding whitespace stripped; blank text (only
  whitespace) counts as empty.

Raises one `ValueError` listing every problem with its Excel row numbers,
e.g. `'Area' empty at Excel rows [3]; 'Segment' and 'Sub Segment' empty at
Excel rows [4]; 'Segment' + 'Diameter' not unique: 'Route' (16 in) at Excel
rows [5, 6]`. `excel_rows` maps `df` rows to Excel rows; `__init__` passes
it so the numbers still match the source file after `skip_years` removed
rows. Defaults to `df.index + 2`, because the header is Excel row 1.

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
the report describes the cleaned data. Then [`normalize()`](#normalizenormalize_dirnone---self)
writes the normalized Excel/JSON under `<cwd>/output/normalize/pcm/`; a file
that fails to normalize keeps its check columns.

It also adds `normalized_pcm_file` to `df` (filename of the normalized JSON)
and `pcm_medium_to_poor` / `pcm_medium_to_high`
(`PCM.medium_to_poor_percentage` / `medium_to_high_percentage`), used by
[`to_json`](#to_jsonoutput_dir-str--none--none---str). They are empty for
rows without a PCM file, or whose file failed to load, clean or normalize.

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
| `normalized` | `True` once `normalize()` wrote the Excel and JSON (`PCM.normalized`); `False` otherwise. |
| `normalized_pcm_file` | Filename of the normalized JSON; empty unless `normalized`. |
| `medium_to_poor_percentage` / `medium_to_high_percentage` | Share of readings whose `Condition` is `Medium to Poor` / `Medium to High`, in percent; empty unless `normalized`. |
| `reason` | Populated when the row failed to load (missing file, exception, …) or to normalize (prefixed `normalize failed:`). |

#### `check_cips_file(data_dir: str, n_jobs: int = 1) -> pd.DataFrame`

Run [`CIPS(...).fix().check()`](#corrosionsdatacips) on every referenced CIPS
file at `<data_dir>/<Year>/CIPS/<filename>`, in parallel via joblib's `loky`
backend like `check_pcm_file`. The data sheet is located, column names
are aligned, then checked. Then `clean().save()` writes a cleaned copy to
`<cwd>/output/cleaned/<year>/CIPS/` and [`normalize()`](#normalizenormalize_dirnone---self-1)
writes the normalized Excel/JSON under `<cwd>/output/normalize/cips/`. The
steps are separate, so a file that fails to clean still reports its column
checks. Check columns describe the file before cleaning.

It also adds two columns to `df`, used by [`to_json`](#to_jsonoutput_dir-str--none--none---str).
They are empty for rows without a CIPS file, or whose file failed to
clean/normalize:

- `normalized_cips_file`: filename of the normalized JSON
  (`CIPS.normalize_json_filepath`), e.g. `2025-cips-sacp-01-jkt-….json`.
- `cips_protection`: `"ICCP"` or `"SACP"`.
- `cips_protected_percentage` / `cips_unprotected_percentage`:
  `CIPS.protected_percentage` / `unprotected_percentage` (set only when
  normalized).

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
| `protected_percentage` / `unprotected_percentage` | Share of readings that are `PROTECTED` or `OVER PROTECTED` / `UNPROTECTED`, in percent; empty unless normalized. |
| `normalized` | `True` once `normalize()` wrote the Excel and JSON (`CIPS.normalized`); `False` otherwise. Only these rows get `normalized_cips_file` in `df`. |
| `normalized_cips_file` | Filename of the normalized JSON; empty when cleaning or normalizing failed. |
| `reason` | Populated when the file is missing, has no data sheet, or fails to load, or when cleaning or normalizing fails (prefixed `clean failed:` / `normalize failed:`). |

#### `to_json(output_dir: str | None = None, sync: bool = True, n_jobs: int = 1) -> str`

Write the index as JSON records to `<output_dir>/file_index.json`
(`JSON_FILENAME`; `output_dir` defaults to `<cwd>/output`) and return the
path. Runs `fix()` first if needed, so empty `Segment` values are filled from
`Sub Segment`. Empty values are written as `null`.

Only rows with **both** a `cips_normalized_file` and a `pcm_normalized_file`
(`NORMALIZED_FILE_KEYS`) are written, so run `check_cips_file` and
`check_pcm_file` first. Every other row goes to
`<output_dir>/file_index_excluded.json` (`EXCLUDED_JSON_FILENAME`) with the
same keys, plus:

| Extra key | Content |
| --- | --- |
| `cips_file`, `pcm_file` | Source filenames from the index (`CIPS` / `PCM`); `null` when the index has none. |
| `missing` | The `NORMALIZED_FILE_KEYS` that are `null`, e.g. `["pcm_normalized_file"]`. |

Why a file was not normalized is in the `check_cips_file` / `check_pcm_file`
report (`reason`). Both files are always written, possibly as `[]`.

`<output_dir>/area.json` (`AREA_JSON_FILENAME`) is written next to them:
one summary per `area_code` of the `file_index.json` records, see
[`area_records`](#area_recordsrecords---listdict).

With `sync=True` (the default), [`SyncData`](#corrosionssync) then runs on the
written index: the normalized CIPS and PCM files of every kept segment (JSON
and Excel, under `<cwd>/output/normalize`) are reordered in place so both
surveys start at the same end. The per-segment report is stored on
`sync_report`. Pass `sync=False` to leave the normalized files as they are.
`n_jobs` runs the sync segments in parallel (`-1` for all cores).

| Key | Source |
| --- | --- |
| `year`, `area` | `Year`, `Area`. |
| `area_code` | Slug of `<area>-<year>`, e.g. `jakarta-2025`. |
| `province_code` | `Province Code`. |
| `name` | `Segment`. |
| `code` | Slug of `<name>-<diameter>`, e.g. `pipa-servis-indonesia-power-16`. |
| `diameter` | `Diameter`, as an int when whole (`16`, not `16.0`). |
| `pipe_length` | `Length` in km, always a float (`2.0` stays `2.0`). When `Length` is empty: the surveyed length, the last `Real Distance` of the normalized CIPS (`df` column `cips_length_km`), else of the normalized PCM (`pcm_length_km`), from meters to km, 3 decimals; `null` without either. |
| `cips_protection` | `"ICCP"` / `"SACP"`, set by `check_cips_file`; `null` until it ran. |
| `total_anomaly` | Number of ACVG/DCVG anomalies of the segment (`AcvgDcvgFile.count`), set by `assign_acvg_dcvg` (`df` column `acvg_dcvg_total_anomaly`); `null` until it ran and for segments without ACVG/DCVG anomalies. Written right after `unprotected`. |
| `protected`, `unprotected` | Share of the CIPS readings that are `PROTECTED` or `OVER PROTECTED` / `UNPROTECTED`, in percent (they add up to 100). Set by `check_cips_file` (`df` columns `cips_protected_percentage` / `cips_unprotected_percentage`); `null` without a normalized CIPS. |
| `medium_to_poor`, `medium_to_high` | Share of the PCM readings whose `Condition` is `Medium to Poor` / `Medium to High`, in percent (they add up to 100). Set by `check_pcm_file` (`df` columns `pcm_medium_to_poor` / `pcm_medium_to_high`); `null` without a normalized PCM. |
| `acvg_dcvg_normalized_file` | Normalized ACVG/DCVG JSON of the segment, set by [`assign_acvg_dcvg`](#assign_acvg_dcvgfiles-output_dirnone---self) (`df` column `normalized_acvg_dcvg_file`); `null` until it ran and for segments without ACVG/DCVG anomalies. Not required to keep a row. |
| `cips_normalized_file`, `pcm_normalized_file` | Set by `check_cips_file` / `check_pcm_file` (`df` columns `normalized_cips_file` / `normalized_pcm_file`); `null` until they ran. |

```python
index.check_cips_file("output/raw_data", n_jobs=-1)
index.check_pcm_file("output/raw_data", n_jobs=-1)
index.to_json()   # "output/file_index.json" (+ "output/file_index_excluded.json")
index.sync_report[index.sync_report["start_gap_m"] > 200]
```

#### `area_records(records) -> list[dict]`

Class method: summarize `file_index.json` records per `area_code` (written
to `area.json` by `to_json`, and rebuilt by `assign_acvg_dcvg`). One record
per area, in order of first appearance:

| Key | Value |
| --- | --- |
| `name` / `code` / `year` | `area` / `area_code` / `year`. |
| `total_length` | Sum of `pipe_length` (3 decimals, to drop float noise). |
| `protected`, `unprotected`, `medium_to_poor`, `medium_to_high` | Simple mean of the segments' percentages (every segment counts the same), 2 decimals; `null` values skipped, `null` when all are. |
| `total_anomaly` | Sum of the segments' `total_anomaly` (`null` = 0), int. |
| `province_code` | Of the first segment of the area. |

#### `assign_acvg_dcvg(files, output_dir=None, counts=None) -> Self`

Add the normalized ACVG/DCVG file and the anomaly count of each row. `files`
maps a row position in `df` (the row of the index CSV that `AcvgDcvg.match`
read) to the JSON filename, as returned by
[`AcvgDcvg.normalized_files()`](#normalized_files---dictint-str); `counts`
maps it to the number of anomalies, as returned by
[`AcvgDcvg.anomaly_counts()`](#anomaly_counts---dictint-int). Sets the `df`
columns `normalized_acvg_dcvg_file` (`ACVG_DCVG_COLUMN`) and
`acvg_dcvg_total_anomaly` (`TOTAL_ANOMALY_COLUMN`), so later `to_json` calls
write them. The ACVG/DCVG step runs after `to_json` (its `normalize` needs
the synced CIPS), so `file_index.json` and `file_index_excluded.json` in
`output_dir` are also updated in place: every record, found by `year` +
`code`, gets `acvg_dcvg_normalized_file` and `total_anomaly` (`null` without
a file; `area.json` is rebuilt from the result), in the same key order as `to_json` records (the order comes from
`_record`; the excluded file's `cips_file`, `pcm_file`, `missing` stay
last). Missing JSON files are skipped; nothing is synced again.

```python
acvg.load().match(csv).rebuild().clean().normalize()
index.assign_acvg_dcvg(acvg.normalized_files(), counts=acvg.anomaly_counts())
```

#### `save(output_dir: str | None = None) -> None`

Write the current `df` to `<output_dir>/file_index_<filename_slug>.csv`.
`output_dir` defaults to `<cwd>/output`.

#### End-to-end example

```python
from corrosions.data.file_index import FileIndex

index = FileIndex("IDDA - PCM CIPS File List.xlsx", verbose=True)
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
| `KIND` | `Literal["pcm", "cips", "acvg_dcvg"]` | Survey type; names the cleaned output sub-directory (upper-cased) and the normalize one (lower-cased). |
| `REQUIRED_COLUMNS` | `list[str]` | Columns expected in the source Excel, checked by `check()`. |
| `NUMERIC_COLUMNS` | `list[str]` | Columns coerced with `pd.to_numeric(..., errors="coerce")` at load time. |
| `CLEAN_REQUIRED_COLUMNS` | `list[str]` | Columns whose non-NaN value is required for a row to survive `clean()`. |
| `JSON_COLUMNS` | `dict[str, str]` | Subclasses with `normalize()`: the `df` columns written to the normalized JSON, in order, mapped to their JSON keys. Used by `json_frame()`. |
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
| `normalize_dir` | `str` | `<output_dir>/normalize/<kind>`, unless a subclass `normalize(normalize_dir=...)` overrode it. |
| `normalize_excel_dir` | `str` | `<normalize_dir>/excel`. |
| `normalize_json_dir` | `str` | `<normalize_dir>/json`. |
| `normalize_excel_filepath` | `str` | Excel written by a subclass `normalize()`: `<normalize_excel_dir>/<year>-<slug>.xlsx` (`<slug>` = slugified source filename without its extension). |
| `normalize_json_filepath` | `str` | JSON written by a subclass `normalize()`: `<normalize_json_dir>/<year>-<slug>.json`. |
| `cleaned` | `bool` | `True` once `clean()` completed; `normalize()` requires it. |
| `normalized` | `bool` | `True` once a subclass `normalize()` wrote both files. |
| `report` | `dict` | Summary from the last `check()` call (empty until then), plus the `normalize()` results once a subclass `normalize()` ran (see [`check()`](#check---self)). |
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

#### `json_frame(df) -> pd.DataFrame` *(classmethod)*

Return `df` as it is written to the normalized JSON: only `JSON_COLUMNS`, in
their order, renamed to their JSON keys, with empty or blank text turned into
`None` (`null`). Used by `CIPS.normalize()` / `PCM.normalize()` and by
[`SyncData`](#corrosionssync) to rebuild the JSON from a reversed normalized
Excel. `CIPS.JSON_COLUMNS` and `PCM.JSON_COLUMNS` hold the mappings listed in
their `normalize()` sections.

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

A subclass `normalize()` adds its results to `report` once both files are
written, keeping the `check()` keys (`check()` itself replaces the whole
report, so call it before `normalize()`):

| Key | Type | Description |
| --- | --- | --- |
| `normalized` | `bool` | `True`. |
| `n_normalized` | `int` | Rows in the normalized files. |
| `normalize_excel_filepath` / `normalize_json_filepath` | `str` | Files written. |
| `protection` | `str` | CIPS: `"ICCP"` or `"SACP"`. |
| `length_km` | `float` | CIPS, PCM: last `Real Distance` in km (survey length, 3 decimals, like `pipe_length`). |
| `protected_percentage` / `unprotected_percentage` | `float` | CIPS: same as the attributes. |
| `medium_to_high_percentage` / `medium_to_poor_percentage` | `float` | PCM: same as the attributes. |
| `count` | `int` | ACVG/DCVG: number of anomalies (`AcvgDcvgFile.count`). |
| `n_on_cips` | `int` | ACVG/DCVG: anomalies placed on the CIPS line (with a `Real Distance`). |
| `cips_json` | `str \| None` | ACVG/DCVG: CIPS JSON used. |

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
`check()` / `clean()` / `save()` from [`BaseData`](#corrosionsdatabase_data)
and adds `normalize()`.

| Attribute | Value |
| --- | --- |
| `KIND` | `"pcm"` |
| `REQUIRED_COLUMNS` | `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Comment (0-100)`, `Gain (dB)`, `Depth (m)` |
| `NUMERIC_COLUMNS` | `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Gain (dB)`, `Depth (m)` |
| `CLEAN_REQUIRED_COLUMNS` | `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Gain (dB)` (Ext GPS columns are excluded because they are frequently blank) |
| `UNIQUE_COLUMNS` | `("Int GPS Latitude", "Int GPS Longitude")` |

```python
from corrosions.data.pcm import PCM

pcm = PCM("data/2024/PCM/segment-01.xlsx", year=2024).check().clean().save()
pcm.report["is_valid"]   # quality of the raw data
pcm.cleaned_path         # "output/cleaned/2024/PCM/segment-01.xlsx"
```

#### `current_loss(dbma, distance) -> tuple[pd.Series, pd.Series]` *(staticmethod)*

Return the `Current Loss Rate` and `Condition` of each reading from its
`dbma` and the meters from the previous reading. Used by `normalize()` and
by [`SyncData`](#corrosionssync) after reversing a survey, so both always
compute the same values. Rate: `abs(Δdbma / distance) * 1000`, rounded to 2
decimals, `0` for the first reading and a zero step, empty when either
`dbma` is empty. Condition: `Medium to High` when the rate is `<= 50`,
otherwise `Medium to Poor` (also for an empty rate).

#### `normalize(normalize_dir=None) -> Self`

Add the current-loss analysis to `df`, then save it as Excel and JSON.
Requires a completed `clean()` (`RuntimeError` otherwise) and raises
`ValueError` if a column it reads is missing (`Int GPS Latitude` /
`Longitude`, `4Hz Current (A)`, `Depth (m)`, `Comment (0-100)`).
`normalize_dir` overrides `self.normalize_dir` (default
`<output_dir>/normalize/pcm`): the files go to its `excel` / `json`
sub-folders, and `normalize_excel_dir`, `normalize_json_dir` and both file
paths follow. `None` keeps the current one.

| Added column | Description |
| --- | --- |
| `Distance` | Meters from the previous reading (`0` for the first), from the `Int GPS` coordinates, as in CIPS. Replaces the `Distance` column some exports already have. |
| `Real Distance` | Running total of `Distance`, in meters. |
| `dbma` | `20 * log10(4Hz Current (A) * 1000)`, rounded to 2 decimals. `clean()` drops readings with a current `<= 0` (a lost signal, often with `0` depth), so the next reading's rate is taken against the last valid one. |
| `Current Loss Rate` | `abs(Δdbma / Δdistance) * 1000` between a reading and the previous one, rounded to 2 decimals; `0` for the first reading. Empty when either `dbma` is empty. |
| `Condition` | `Medium to High` when `Current Loss Rate <= 50`, otherwise `Medium to Poor`, including when the rate is empty (no `dbma`). |

It also sets `medium_to_high_percentage` (share of `Medium to High`
readings, in percent, rounded to 2 decimals) and `medium_to_poor_percentage`
(`100 -` that). Both are `0.0` before `normalize()`. Reversing the survey
(`SyncData`) keeps the same reading pairs, so it does not change them.
`report` gets the normalize keys (`length_km`, the two percentages, …; see
[`check()`](#check---self)).

"Previous" means the row above: the index is not used, so the gaps `clean()`
leaves in it are fine.

| File | Content |
| --- | --- |
| `normalize_excel_filepath` = `<output_dir>/normalize/pcm/excel/<year>-<slug>.xlsx` | `df` with its original column names, without the index. |
| `normalize_json_filepath` = `<output_dir>/normalize/pcm/json/<year>-<slug>.json` | One record per row with only these keys, in this order: `latitude`, `longitude` (from `Int GPS Latitude` / `Longitude`, same keys as CIPS), `real_distance`, `4hz_current_a`, `dbma`, `current_loss_rate`, `depth_m`, `condition`, `comment_0_100` (from `Comment (0-100)`). `Distance` is not in the JSON. Empty cells, including blank text, are `null`. |

Very short GPS steps inflate `Current Loss Rate`: on the 2022–2025 data,
steps under 3 m (0.3% of rows) have a median rate of 490–3,900 against 32
for steps of 10 m or more.

```python
pcm = PCM("data/2025/PCM/segment-01.xlsx", year=2025).clean().normalize()
pcm.df["Condition"].value_counts()
pcm.normalize_json_filepath   # "output/normalize/pcm/json/2025-segment-01.json"
pcm.report["length_km"], pcm.report["medium_to_high_percentage"]

# another folder: D:/tmp/pcm/excel/... and D:/tmp/pcm/json/...
PCM("data/2025/PCM/segment-01.xlsx", year=2025).clean().normalize(normalize_dir="D:/tmp/pcm")
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
`clean()`) and `fixed` (`True` once `fix()` ran). `cleaned` comes from
`BaseData`.

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

#### `normalize(normalize_dir=None) -> Self`

Add distances and a protection condition to `df`, then save it as Excel
and JSON. Distances are computed with
[`calculate_distance`](#corrosionsutilsgeo_utils) on whole columns.
`normalize_dir` overrides `self.normalize_dir` (default
`<output_dir>/normalize/cips`): the files go to its `excel` / `json`
sub-folders, and `normalize_excel_dir`, `normalize_json_dir` and both file
paths follow. `None` keeps the current one.

| Added column | Description |
| --- | --- |
| `Distance` | Meters from the previous reading (`0` for the first). |
| `Real Distance` | Running total from the first reading, in meters. |
| `Condition` | `PROTECTED` (`-1.2 < V <= -0.85`), `OVER PROTECTED` (`V <= -1.2`) or `UNPROTECTED` (anything else, including an empty reading). `V` is `Off Voltage` for ICCP and `Voltage` for SACP, in volts. |

It also sets `protected_percentage` (share of readings that are `PROTECTED`
or `OVER PROTECTED`, in percent, rounded to 2 decimals) and
`unprotected_percentage` (`100 - protected_percentage`, the `UNPROTECTED`
share). Both are `0.0` before `normalize()`. `report` gets the normalize
keys (`protection`, `length_km`, the two percentages, …; see
[`check()`](#check---self)).

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
cips.report["protected_percentage"] # also in report, with protection, length_km, …

# another folder: D:/tmp/cips/excel/... and D:/tmp/cips/json/...
CIPS("segment.xlsx", year=2024).clean().normalize(normalize_dir="D:/tmp/cips")
```

---

## `corrosions.data.acvg_dcvg`

### `class AcvgDcvg`

ACVG/DCVG anomaly reader. Anomalies (points) are saved as one workbook per
year in `DEFAULT_DATA_DIR` (`D:\Data\ACVG DCVG 2021-2025`), listed in an
index workbook (`IDDA - ACVG FIle List.xlsx`: `Year`, `Filename`). Each
workbook has one sheet per area (`SHEET_NAMES`: Bekasi, Bogor, Cilegon,
Cirebon, Jakarta, Karawang, Tangerang); other sheets (e.g. `Contoh format
Gabungan`) are skipped.

Fluent pipeline:

```python
from corrosions.data.acvg_dcvg import AcvgDcvg

csv = "output/file_index_idda-pcm-cips-file-list.csv"   # FileIndex.save()
acvg = AcvgDcvg("IDDA - ACVG FIle List.xlsx", skip_years=[2021], verbose=True)
acvg.load().match(csv).rebuild()   # output/raw_data/<year>/ACVG_DCVG/*.xlsx
acvg.clean().normalize()           # output/cleaned/<year>/ACVG_DCVG, output/normalize/acvg_dcvg
report = acvg.assign_index()       # adds ACVG_DCVG to the CSV; per-group report
acvg.file_report                   # per-file clean/normalize report
```

| Attribute | Description |
| --- | --- |
| `SHEET_NAMES` | Area sheets that hold anomalies. |
| `REQUIRED_COLUMNS` | `Segmen`, `Lokasi Anomali`, `Kondisi Permukaan`, `Dia (inch)`, `Latitude`, `Longitude`, `On Potential (volt)`, `Off Potential (volt)`, `IR Drop (%)`, `Hasil ACVG (dB)`, `Kedalaman Pipa (m)`, `%drop PCM`, `Tgl DCVG`, `Tgl ACVG` (after stripping header spaces). |
| `NUMERIC_COLUMNS` | Coerced to numbers: `"61.80%"` -> `61.8`; `N/A`, `-`, `not detected` -> empty. |
| `DATE_COLUMNS` | `Tgl DCVG`, `Tgl ACVG`; a row with a real date in another year than its workbook is dropped. |
| `MAX_DISTANCE_M` | `500`: largest distance between an anomaly and the CIPS track it is linked to. |
| `DESTINATION_SUBDIR` / `INDEX_COLUMN` | `ACVG_DCVG`. |
| `FILE_REPORT_COLUMNS` | Columns of `file_report`. |
| `anomalies`, `load_report`, `groups`, `output_files`, `file_report` | Results of `load`, `match`, `rebuild` and `clean` / `normalize`. |

#### `__init__(filepath, data_dir=DEFAULT_DATA_DIR, skip_years=None, verbose=False)`

Load the ACVG/DCVG index, drop `skip_years`, and check every listed workbook
exists (`FileNotFoundError` naming the missing ones; `KeyError` without `Year`
/ `Filename`).

#### `load() -> Self`

Read every area sheet: strip header names, skip sheets missing a required
column, drop rows without `Segmen` (notes such as `Tim Aldi 4`), parse
`Latitude` / `Longitude` with [`parse_coordinate`](#parse_coordinatevalue---float--none)
(numbers and degrees-minutes-seconds), coerce `NUMERIC_COLUMNS`, and drop rows
dated in another year. `Year` and `Area` (the sheet) are added in front. Every
skipped sheet and dropped row is listed in `load_report` (`year`, `sheet`,
`issue`, `rows`).

#### `match(index_csv, normalize_dir=None, max_distance_m=None) -> Self`

Link every anomaly to a row of the file-index CSV:

1. **name** (per group): a group is the anomalies sharing `Year`, `Area`,
   `Segmen` and `Dia (inch)`. When the slug of `Segmen` equals the slug of a
   same-year index `Segment` or `Sub Segment` (the same `Diameter` wins a
   tie), the whole group goes to that row.
2. **cips** (per anomaly): every other anomaly goes to the same-year index row
   whose normalized CIPS track
   (`<normalize_dir>/cips/json/<year>-<slug of CIPS>.json`) passes closest to
   it, if within `max_distance_m`. A group can be split: anomalies named after
   a parent pipeline (2023: `Batuceper - Pondok Ungu`) go to the index section
   they lie on (`PU - Batu Ceper: Dok Kodja - BP AKR Sunter`, …), numbered
   names (2022: `Eks Sumber Bata 0`, `… 1`) go to their track, and anomalies at
   a segment border go to the segment they lie on.
3. **none**: the rest stay unmatched, grouped by name.

Linked anomalies take the file name of their index row,
`acvg-dcvg-<segment>-<diameter>-<area>.xlsx` (slugified), so every linked row
has exactly one file. Unmatched groups use their own name. `anomalies` gets
`_row`, `_method` and `_distance`; `groups` (the report) holds one row per
(index row, method) and per unmatched name group: `year`, `area`, `segment`
(the ACVG/DCVG names, joined), `diameter`, `n_anomalies`, `method`,
`index_row`, `index_segment`, `cips_file`, `distance_m` (median over its
anomalies), `filename`.

#### `unlinked_segments() -> pd.DataFrame`

List every index row that `match` linked to no group, with the reason, so an
empty `ACVG_DCVG` cell can be explained. Columns: `year`, `area`, `segment`,
`diameter`, `cips`, `reason`, `nearest_anomaly_m` (meters from the row's CIPS
track to the nearest same-year anomaly), `nearest_anomaly_segmen` and
`nearest_linked_to` (the index segment that anomaly went to).

| `reason` | Meaning |
| --- | --- |
| `no anomaly within <limit> m` | the nearest anomaly is further than the limit: usually no ACVG/DCVG survey on that segment that year |
| `anomalies nearby, linked to another row` | an anomaly lies on the track but went to another row: by its name, or because another row's track passes even closer (e.g. two index rows on the same pipe) |
| `anomalies nearby, not linked` | safety net; does not occur with per-anomaly matching |
| `no CIPS file in the index` / `CIPS not normalized` | no track to compare with; only a name match was possible |
| `no ACVG/DCVG anomaly in <year>` | that year has no anomalies with coordinates |

Raises `RuntimeError` before `match`. On the 2022-2025 data: 93 unlinked rows
(77 no anomaly within 500 m, 10 linked to another row, 5 without a CIPS file,
1 not normalized).

#### `rebuild(output_dir=None, destination_dir="raw_data") -> Self`

Write one Excel per file name to
`<output_dir>/<destination_dir>/<year>/ACVG_DCVG/<filename>`, with `Year`,
`Area` and the sheet's columns (parsed values). `REQUIRED_COLUMNS` are always
kept; other all-empty columns (extra columns of another workbook) and the
internal `_` match columns are left out. Raises `RuntimeError` before
`match`.

#### `clean() -> Self`

Run [`AcvgDcvgFile`](#class-acvgdcvgfilebasedata)`(path, year).check().clean().save()`
on every file `rebuild` wrote; the cleaned copy goes to
`<output_dir>/cleaned/<year>/ACVG_DCVG/<filename>` (`output_dir` as given to
`rebuild`), next to the cleaned CIPS and PCM. A failing file gets a `reason`
(`clean failed: …`) and the others go on. Sets `file_report`: `year`,
`filename`, `n_anomalies`, `n_duplicates`, `n_cleaned`, `cleaned_path`,
`cips_file`, `normalized_file`, `count`, `n_on_cips`, `reason`. Raises `RuntimeError`
before `rebuild`.

#### `normalize(normalize_dir=None) -> Self`

Run `AcvgDcvgFile.normalize` on every cleaned file, with the normalized CIPS
JSON of the index row it belongs to (`<normalize_dir>/cips/json/<cips_file>`,
`normalize_dir` as given to `match`). Files without a CIPS line (unmatched
groups, rows without a normalized CIPS) are normalized with an empty
`real_distance` / `condition`. Fills `normalized_file`, `count` and `n_on_cips` in
`file_report` (`reason` = `normalize failed: …` on error). Run it after the
CIPS/PCM sync, as `main.py` does, so distances follow the synced direction.
`normalize_dir` is passed to every `AcvgDcvgFile.normalize`, so the
normalized ACVG/DCVG files go to `<normalize_dir>/<excel|json>` instead of
`<output_dir>/normalize/acvg_dcvg`; the CIPS JSON is still read from the
`normalize_dir` given to `match` (the normalize root, not a per-kind
folder). Raises `RuntimeError` before `clean`.

#### `normalized_files() -> dict[int, str]`

Row position in the index CSV given to `match` -> normalized JSON filename
(`<year>-<slug>.json`) of every linked row, for
[`FileIndex.assign_acvg_dcvg`](#assign_acvg_dcvgfiles-output_dirnone---self).
Unmatched groups and files that failed to clean or normalize are left out.
Raises `RuntimeError` before `normalize`.

#### `anomaly_counts() -> dict[int, int]`

Row position in the index CSV given to `match` -> number of anomalies in its
normalized file (`AcvgDcvgFile.count`), for the same rows as
`normalized_files()`; `total_anomaly` in `file_index.json`. Raises
`RuntimeError` before `normalize`.

#### `assign_index(index_csv=None) -> pd.DataFrame`

Add the `ACVG_DCVG` column (the file name of each matched index row, empty
otherwise) to the CSV given to `match` and write it back. Returns `groups`.

On the 2022-2025 data: 607 anomalies (339 linked by name, 251 by CIPS with a
median distance of 3.3 m, 17 unmatched), 98 of 191 index rows linked. The 2023 workbook holds 34 rows dated 2025 (33 also in the 2025
workbook), which are dropped from 2023. `clean` / `normalize`: 109 files, 606
anomalies after cleaning, 589 placed on a CIPS line (the 17 unmatched have
none), in about 20 s.

### `class AcvgDcvgFile(BaseData)`

One extracted segment file (`AcvgDcvg.rebuild` output). Inherits
`check` / `clean` / `save` from [`BaseData`](#corrosionsdatabase_data), so it
writes to the same layout as `CIPS` and `PCM`.

```python
from corrosions.data.acvg_dcvg import AcvgDcvgFile

data = AcvgDcvgFile("output/raw_data/2024/ACVG_DCVG/<file>.xlsx", year=2024)
data.check().clean().save()      # output/cleaned/2024/ACVG_DCVG/<file>.xlsx
data.normalize("output/normalize/cips/json/2024-<cips slug>.json")
```

| Attribute | Value |
| --- | --- |
| `KIND` | `"acvg_dcvg"` (cleaned: `ACVG_DCVG`, normalize: `acvg_dcvg`) |
| `REQUIRED_COLUMNS` | `AcvgDcvg.REQUIRED_COLUMNS` |
| `NUMERIC_COLUMNS` | `Latitude`, `Longitude` + `AcvgDcvg.NUMERIC_COLUMNS` |
| `CLEAN_REQUIRED_COLUMNS` / `UNIQUE_COLUMNS` | `Latitude`, `Longitude` |
| `JSON_COLUMNS` | `latitude`, `longitude`, `real_distance`, `anomaly_location` (`Lokasi Anomali`), `surface_condition` (`Kondisi Permukaan`), `diameter` (`Dia (inch)`), `on_potential`, `off_potential`, `ir_drop`, `result_acvg` (`Hasil ACVG (dB)`), `pipe_depth` (`Kedalaman Pipa (m)`), `drop_pcm`, `survey_dcvg` / `survey_acvg` (`Tgl DCVG` / `Tgl ACVG`), `closest_cips_condition` (`Condition`). `Segmen` is in the Excel only. |
| `cips_json` | CIPS JSON used by the last `normalize`, or `None` |
| `count` | Number of anomalies (rows of `df`) after `normalize`; `0` before. |

`clean()` (from `BaseData`) drops all-empty rows, rows with an empty or `0`
coordinate, and duplicate points (first kept).

#### `normalize(cips_json=None, max_distance_m=AcvgDcvg.MAX_DISTANCE_M, normalize_dir=None) -> Self`

Place every anomaly on its segment's CIPS line. Each anomaly takes the nearest
reading of `cips_json` (the normalized CIPS JSON) and gets:

- `Real Distance`: that reading's `real_distance`, i.e. its position along the
  CIPS line (meters), so anomalies line up with the CIPS/PCM charts;
- `Condition`: that reading's `condition` (`PROTECTED` / `OVER PROTECTED` /
  `UNPROTECTED`);
- `CIPS Offset (m)`: distance to that reading (Excel only).

`Real Distance` and `Condition` stay empty without `cips_json` or when the
nearest reading is further than `max_distance_m`. Rows are sorted by
`Real Distance` (empty last); missing `REQUIRED_COLUMNS` are added empty.
Writes `normalize_excel_filepath`
(`<output_dir>/normalize/acvg_dcvg/excel/<year>-<slug>.xlsx`, original column
names) and `normalize_json_filepath`
(`<output_dir>/normalize/acvg_dcvg/json/<year>-<slug>.json`, `JSON_COLUMNS`
keys; `survey_dcvg` / `survey_acvg` always `YYYY-MM-DD` or `null`: date text is parsed, `20-May` takes the file year (`2024-05-20`), non-date text is `null`; empty cells
`null`). `normalize_dir` overrides `self.normalize_dir` (default
`<output_dir>/normalize/acvg_dcvg`); the paths follow, as in CIPS and PCM.
`report` gets the normalize keys (`count`, `n_on_cips`,
`cips_json`, …; see [`check()`](#check---self)). Raises `RuntimeError`
before `clean`, `FileNotFoundError` for a missing `cips_json`.

---

## `corrosions.sync`

### `class SyncData`

Put the CIPS and PCM surveys of each segment in the same direction. Surveys
of one pipeline are often walked in opposite directions (e.g. PCM east to
west, CIPS west to east). `SyncData` reads the index written by
[`FileIndex.to_json`](#to_jsonoutput_dir-str--none--none---str) and reorders
the normalized JSON **and Excel** files **in place** so both surveys start at
the same end:

1. **CIPS starts by the main direction of its line** (`START`): an
   west-east line starts at its **west** end, a north-south line at its
   **north** end. The line is west-east when its two ends are further apart
   east-west than north-south (`cips_axis` in the report).
2. **PCM follows CIPS**: it is reversed when its last end is closer than its
   first end to the (synced) CIPS start, so the pair always agrees.

Each **end** is the average of the first / last `END_READINGS` (5) readings,
or of half the survey when it is shorter, so one bad GPS fix at an end
cannot flip the decision.

`FileIndex.to_json()` runs it by default. The decision is made on the
JSON. A reversed survey is recalculated **once, on its normalized Excel**
(`.../excel/<year>-<slug>.xlsx`, full-precision coordinates, `normalize()`'s
column names): `Distance` and `Real Distance`, and for PCM `Current Loss Rate`
and `Condition` with
[`PCM.current_loss`](#current_lossdbma-distance---tuplepdseries-pdseries-staticmethod),
because both depend on the previous reading. The JSON is then rebuilt from
that Excel with `json_frame` (the survey's `JSON_COLUMNS`, as `normalize()`
writes it), so both files carry the same values (the JSON rounded to 10
decimal places by `to_json`). Files already in order are not rewritten and
their Excel is not read.

**Safe writes:** every file of a segment is read and reversed, then written
to a uniquely named temporary file next to it; only when all of them are
written are they moved over the originals (`os.replace`). A segment that
fails at any point (e.g. its Excel is missing, lacks the survey's
`JSON_COLUMNS` / PCM `REQUIRED_COLUMNS`, or a write fails) is left untouched,
with no temporary file left behind. The unique names also keep parallel
workers apart when two segments share a file.

Segments run in parallel with `n_jobs` (joblib `loky`). The rule gives the
same order every time, so running `sync()` again changes nothing.

| Attribute | Description |
| --- | --- |
| `REQUIRED_KEYS` | Keys every index record must have: `year`, `area`, `area_code`, `name`, `code`, `diameter`, `pipe_length`, `cips_protection`, `cips_normalized_file`, `pcm_normalized_file`. |
| `COORDINATES` | JSON latitude/longitude keys per kind: `latitude` / `longitude` for both CIPS and PCM. |
| `EXCEL_COORDINATES` | Excel latitude/longitude columns: CIPS `Latitude` / `Longitude`, PCM `PCM.UNIQUE_COLUMNS` (`Int GPS Latitude` / `Longitude`). |
| `SURVEYS` | Survey class per kind (`CIPS`, `PCM`); its `json_frame` rebuilds the JSON. |
| `EXCEL_REQUIRED_COLUMNS` | Columns an Excel must have to be reversed: the survey's `JSON_COLUMNS`, plus `PCM.REQUIRED_COLUMNS` for PCM. |
| `EXCEL_COLUMNS` | Excel names of the order-dependent values: `Distance`, `Real Distance`, `dbma`, `Current Loss Rate`, `Condition`. |
| `END_READINGS` | Readings averaged at each end of a survey (`5`). |
| `START` | Where a CIPS survey starts, by line direction: `{"west-east": "west", "north-south": "north"}`. Set to `"east"` / `"south"` to flip. |
| `REPORT_COLUMNS` | Columns of the `sync()` report, in order. |
| `data` | Records of the index JSON. |
| `normalize_dir` | Root of the normalized files, `<normalize_dir>/<cips\|pcm>/<json\|excel>/<file>`. |
| `n_jobs` | Parallel workers for `sync()`. |
| `report` | DataFrame from the last `sync()` call. |

#### `__init__(json_file_index, normalize_dir=None, n_jobs=1, verbose=False)`

Load `file_index.json` and check every record has `REQUIRED_KEYS`.
`normalize_dir` defaults to `<cwd>/output/normalize`, where
`CIPS.normalize()` / `PCM.normalize()` write. `n_jobs` sets the parallel
workers for `sync()` (`-1` for all cores). Raises `FileNotFoundError` if the
index is missing and `KeyError` naming the first record that misses keys.

#### `ends(df, lat, lon) -> tuple[Point, Point]` *(classmethod)*

Return the first and last end of a survey as `(lat, lon)` points, each the
mean of `END_READINGS` readings (or half the survey when shorter).

#### `cips_direction(first, last) -> tuple[str, bool]` *(classmethod)*

Return the main direction of a CIPS line (`"west-east"` or
`"north-south"`, west-east on a tie) and whether it must be reversed to start
at `START[axis]`.

#### `sync() -> pd.DataFrame`

Sync every segment and return one report row per index record
(`REPORT_COLUMNS`):

| Column | Description |
| --- | --- |
| `year`, `area`, `segment_code` | From the index record (`segment_code` is its `code`). |
| `start_gap_m` | Meters between the CIPS and PCM start ends after syncing. A large gap means the two files do not cover the same stretch, or one of them belongs to another segment. |
| `cips_axis` | `west-east` or `north-south`, the main direction of the CIPS line (and the direction it is walked after syncing). |
| `cips_reversed`, `pcm_reversed` | Whether that survey was reversed and rewritten (JSON and Excel). |
| `reason` | Why a segment was skipped (missing, unreadable or empty file, missing keys/columns, missing Excel, `write failed: ...`); empty when synced. Other segments still run. |
| `normalized_cips_file`, `normalized_pcm_file` | From the index record (`cips_normalized_file` / `pcm_normalized_file`). |
| `cips_json_path`, `pcm_json_path`, `cips_excel_path`, `pcm_excel_path` | Full paths of the four files, also for skipped segments. |

On the 2022-2025 data (182 segments, `n_jobs=-1`): the sync took 14 s,
0 errors. 92 lines are west-east and 90 north-south. 71 CIPS (37 west-east,
34 north-south) and 73 PCM surveys reversed. 34 segments have `start_gap_m`
above 200 m. Some of them are partial coverage (the surveys touch, but PCM
covers only part of the CIPS line); others point to the wrong file in the
index, e.g. `16-in-bitung-1-valve-gantung-kawasan-olex-16` (2022, 86.6 km:
its CIPS file is the Karawang Pindodeli II survey, also used by
`16-in-pindodeli-ii-kiic-16`) and `serpong-batu-ceper-16` (2024, 12.1 km: its
PCM file is the Batu Ceper - Bitung survey).

```python
from corrosions.sync import SyncData

report = SyncData("output/file_index.json", n_jobs=8, verbose=True).sync()
report[report["start_gap_m"] > 200]   # CIPS/PCM pairs that do not line up
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

### `parse_coordinate(value) -> float | None`

Return a latitude/longitude as decimal degrees: numbers, numeric strings
(`"-6.587569"`) and degrees-minutes-seconds with a hemisphere letter
(`6°15'16.8"S`, `106°59'58.7"E`; any separator, so a mangled degree sign
still works). `S` / `W` give negative values; anything else (`None`, `NaN`,
`""`, `"N/A"`, `"-"`) gives `None`. Also importable from `corrosions.utils`.

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
