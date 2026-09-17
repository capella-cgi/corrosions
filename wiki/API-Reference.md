# API Reference

This page documents the public API of the `corrosions` package as of
version **0.3.0**. It is organized by module. All symbols are importable from
their fully qualified paths shown in each section.

- [`corrosions`](#corrosions) — package metadata
- [`corrosions.logging`](#corrosionslogging) — logging configuration
- [`corrosions.data.file_index`](#corrosionsdatafile_index) — `FileIndex`
- [`corrosions.data.pcm`](#corrosionsdatapcm) — `PCM`
- [`corrosions.utils.path_utils`](#corrosionsutilspath_utils) — path helpers

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
| `verbose` | `bool` | If `True`, `fix()` emits progress messages. |

#### `__init__(filepath, drop_columns=None, verbose=False)`

Load the Excel file, optionally drop columns, validate schema, and coerce
`Year`, `Diameter`, `Length`, and `Province Code` to their expected dtypes.

- **`filepath`** *(str)* — path to the source Excel file.
- **`drop_columns`** *(str | list[str] | None)* — columns to drop after load.
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

#### `rebuild(source_dir, output_dir=None, destination_dir="data") -> Self`

Copy every referenced file from `source_dir` into a clean output tree.

Behavior:

1. Runs `check_existing_file(source_dir)`.
2. Runs `fix()` if not already applied.
3. Resolves `output_dir` (defaults to `<cwd>/output`).
4. For each existing referenced file, copies it (via `shutil.copy2`) to
   `<output_dir>/<destination_dir>/<Year>/<data_type>/<filename>`. Existing
   destination files are skipped.
5. Logs a summary of `copied` vs. `skipped` file counts.
6. Calls `self.save()` to write the updated CSV.

Returns `self` for chaining.

#### `check_pcm_quality(data_dir: str, n_jobs: int = 1) -> pd.DataFrame`

Run [`PCM.check`](#check---dict) on every referenced PCM file, in parallel via
joblib's `loky` backend when `n_jobs > 1` (or `-1` for all cores).

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

#### `save(output_dir: str | None = None) -> None`

Write the current `df` to `<output_dir>/file_index_<filename_slug>.csv`.
`output_dir` defaults to `<cwd>/output`.

#### End-to-end example

```python
from corrosions.data.file_index import FileIndex

index = FileIndex("IDDA - File List.xlsx", verbose=True)
index.rebuild(source_dir="//nas/surveys", destination_dir="data")
report = index.check_pcm_quality("output/data", n_jobs=-1)
```

---

## `corrosions.data.pcm`

Single-file Pipeline Current Mapping (PCM) survey reader.

### `class PCM`

Loads one PCM Excel export, coerces its numeric columns, and exposes cleaning
and data-quality helpers.

#### Class attributes

| Attribute | Type | Purpose |
| --- | --- | --- |
| `COLUMNS` | `list[str]` | Required columns expected in the source Excel: `Index`, `4Hz Current (A)`, `Int GPS Latitude`, `Int GPS Longitude`, `Ext GPS Latitude`, `Ext GPS Longitude`, `Survey name (0-100)`, `Gain (dB)`. |
| `NUMERIC_COLUMNS` | `list[str]` | Columns coerced with `pd.to_numeric(..., errors="coerce")` at load time. |
| `UNIQUE_COLUMNS` | `tuple[str, str]` | `("Int GPS Latitude", "Int GPS Longitude")` — the pair whose combination must be unique. |

#### Instance attributes

| Attribute | Type | Description |
| --- | --- | --- |
| `filepath` | `str` | Path to the source Excel file. |
| `df` | `pd.DataFrame` | Working DataFrame with numeric columns coerced. |
| `year` | `int` | Survey year for this file. |
| `output_dir` | `str` | Resolved output directory. |
| `cleaned_dir` | `str` | Destination for cleaned output: `<output_dir>/cleaned/<year>/PCM`. |
| `cleaned_path` | `str \| None` | Path of the cleaned Excel once saved. |
| `verbose` | `bool` | If `True`, downstream methods may emit progress messages. |

#### `__init__(filepath, year, output_dir=None, verbose=False)`

Load the Excel file and coerce every numeric column that is present.

- **`filepath`** *(str)* — path to the source PCM Excel file.
- **`year`** *(int)* — survey year.
- **`output_dir`** *(str | None)* — defaults to `<cwd>/output` via
  `resolve_output_dir`.
- **`verbose`** *(bool)* — enables progress logging in downstream methods.
- **Raises** `FileNotFoundError` if `filepath` does not exist.

#### `clean() -> Self`

Drop rows that are empty across every column or that contain any `NaN` in the
`NUMERIC_COLUMNS` actually present. Mutates `self.df` in place and calls
`save()`. Returns `self` for chaining.

#### `save() -> Self`

Write the current `df` to `<cleaned_dir>/<original_filename>`, creating
`cleaned_dir` if needed, and set `self.cleaned_path`. Returns `self` for
chaining.

#### `check() -> dict`

Run data-quality checks and return a summary.

Behavior:

1. If a previously cleaned copy exists at
   `<cleaned_dir>/<original_filename>`, it is loaded from disk. Otherwise,
   `clean()` is run.
2. Checks that every column in `COLUMNS` is present.
3. Checks that rows are unique on `UNIQUE_COLUMNS`.

Returned keys:

| Key | Type | Description |
| --- | --- | --- |
| `filepath` | `str` | Path to the cleaned file used for checks. |
| `is_valid` | `bool` | `True` when there are no missing columns and no duplicates. |
| `n_missing` | `int` | Count of missing required columns. |
| `n_duplicates` | `int` | Count of duplicate rows by `UNIQUE_COLUMNS`. |
| `missing_columns` | `list[str] \| None` | Names of missing required columns (or `None` when none). |
| `duplicates` | `list[dict] \| None` | One dict per duplicate row (`row` index + unique-column values), or `None` when none. |

```python
from corrosions.data.pcm import PCM

pcm = PCM("data/2024/PCM FINAL/segment-01.xlsx", year=2024)
report = pcm.clean().check()
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
