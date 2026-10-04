# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Package manager

This project uses **`uv`** exclusively — never suggest `pip`, `venv`, or `python -m pip`. The uv cache is pinned to `./.cache/uv` (see `pyproject.toml`).

```bash
uv sync                 # install runtime + dev dependencies from uv.lock
uv add <package>        # add a runtime dependency
uv add --dev <package>  # add a dev dependency
uv run <cmd>            # run a command inside the project environment
```

Python version is pinned to **3.11** by `.python-version` and `requires-python = ">=3.11"`.

## Common commands

```bash
uv run ruff check --fix src/   # lint + autofix (config in ruff.toml)
uv run ruff format .           # format
uvx ty check src/              # type check (Astral's ty; config in ty.toml, root = ./src)
uv run pytest                  # run all tests
uv run pytest tests/test_foo.py::test_bar  # single test
uv run jupyter notebook        # open notebooks used for ad-hoc workflows
```

`main.py` at the repo root is the file-check CLI, mirroring `file-index.ipynb`: `FileIndex(..., skip_years=args.skip_years)`, `rebuild()` (runs `fix()` then `check_existing_file(source)`) into `<output>/raw_data`, then `check_cips_file` / `check_pcm_file` written to `<output>/checked-cips.xlsx` / `checked-pcm.xlsx` (list cells flattened to `a, b` text). Finally `to_json()` writes `<output>/file_index.json` (rows with both normalized files) and `file_index_excluded.json` (the rest). `to_json` also syncs the CIPS/PCM direction (`--no-sync` passes `sync=False`); `main.py` writes `fi.sync_report` to `<output>/sync-report.xlsx`. Run `uv run main.py [--type cips|pcm] [--skip-years [YEAR ...]] [--output-dir DIR] [--no-sync]` (`--skip-years` defaults to `2021`; pass it with no value to process every year); see `--help`. Other ad-hoc workflows live in Jupyter notebooks at the repo root (`file-index.ipynb`, `check.ipynb`, `check-existsing-files.ipynb`) that drive the `corrosions` package.

## Architecture

The package lives under `src/corrosions/` (src layout — always import from the installed package, not by relative path).

### Domain: CIPS and PCM survey data

The package organizes and validates two types of corrosion survey files collected on underground gas pipelines: **CIPS** (Close Interval Potential Survey) and **PCM** (Pipeline Current Mapping). Files arrive as year-partitioned Excel workbooks and are indexed by a single master Excel spreadsheet (e.g. `IDDA - File List.xlsx` at the repo root).

### Design

1. **`FileIndex`** (`src/corrosions/data/file_index.py`) is the top-level orchestrator. It loads the master Excel index, validates its schema (`FileIndex.COLUMNS`), normalizes filenames (`fix()`), verifies each referenced file exists at `<data_dir>/<Year>/<CIPS|PCM> FINAL/<filename>` (`check_existing_file()`), and copies referenced files into a clean output tree (`rebuild()`). `FileIndex(..., skip_years=[2021])` removes those years' rows from `df` at load, so every method (CIPS and PCM alike) ignores them. After that, `validate_values()` raises `ValueError` (with Excel row numbers) if a kept row has an empty `Area`, an empty `Segment` with no `Sub Segment` to fill it (`Sub Segment` alone may be empty), or a duplicate filled-`Segment` + `Diameter` pair (keeps `segment_code` unique). Most mutating methods return `Self` to support chaining and set boolean flags (`checked`, `fixed`) to make idempotency explicit.

2. **`BaseData`** (`src/corrosions/data/base_data.py`) is the per-file worker base. Construction loads the sheet returned by the `find_sheet(filepath)` classmethod (default: first sheet; stored as `sheet_name`) and coerces `NUMERIC_COLUMNS` with `pd.to_numeric(..., errors="coerce")`. It exposes a fluent pipeline where every step returns `Self`: `check()` stores a quality summary on `self.report` (missing `REQUIRED_COLUMNS` + duplicate rows on `UNIQUE_COLUMNS`) for whatever `df` holds at call time; `clean()` drops all-empty rows, rows with a `0` coordinate (`UNIQUE_COLUMNS` is the lat/lon pair in both subclasses), rows with NaN in `CLEAN_REQUIRED_COLUMNS`, then duplicate lat/lon rows (first kept). It raises `ValueError` if nothing is left and never saves; `save()` writes to `cleaned_dir`. Subclasses only declare `KIND` and the column constants:
   - **`PCM`** (`pcm.py`) — `UNIQUE_COLUMNS = ("Int GPS Latitude", "Int GPS Longitude")`; Ext GPS columns are excluded from `CLEAN_REQUIRED_COLUMNS` because they are often blank. `REQUIRED_COLUMNS` = current, Int GPS lat/lon, `Comment (0-100)`, gain, `Depth (m)`. `normalize()` (after `clean()`) adds `Distance` (step from Int GPS, as in CIPS; replaces any source `Distance`) and `Real Distance` (cumulative), `dbma` (`20*log10(current*1000)`, empty for current <= 0), `Current Loss Rate` (`|Δdbma/Δdistance|*1000` vs the previous row, 0 for the first) and `Condition` (`Medium to High` if rate <= 50 else `Medium to Poor`, also when the rate is empty), then writes `normalize/pcm/excel|json/<year>-<slug>` (JSON keys `latitude`, `longitude` (from Int GPS, same as CIPS), `real_distance`, `4hz_current_a`, `dbma`, `current_loss_rate`, `depth_m`, `condition`, `comment_0_100` from `Comment (0-100)`). `BaseData.clean()` sets `cleaned`, which both `normalize()` methods require.
   - **`CIPS`** (`cips.py`) — workbooks are not uniform (data sheet may be `Data`, `Sheet1`, named after the segment, …, next to `Grafik`/`DCP Data`/`Survey Info`/`Raw Data`). `find_sheet` reads only header rows (`utils.dataframe_utils.get_sheet_columns`) and picks via `data_sheets()`: sheets whose header has all `SHEET_COLUMNS` (`Latitude`, `Longitude`, `DCP/Feature/DCVG Anomaly`), ranked by `SHEET_POSSIBILITIES` (`Data` first). `fix()` aligns column names (`RENAME_COLUMNS`: `Voltage (V)`→`Voltage`, `Off Voltage (V)`→`Off Voltage`) and adds an empty `Comment`; `Data No` / `Altitude` are neither required nor generated. It runs for every year and never raises. `check()` adds `has_voltage`; duplicates are counted but do not make a file invalid. `clean()` runs `fix()`, normalizes voltages into `Voltage` (ICCP if `On`+`Off Voltage`; `Voltage`+`Off Voltage` is decided by `ICCP`/`SACP` in the filename; `Voltage` only is SACP), drops ICCP rows missing `On` or `Off Voltage` (SACP only needs `Voltage`), then applies `BaseData.clean()` (zero/empty lat/lon, empty `Voltage`, dedupe). `normalize()` (after `clean()`; raises `RuntimeError` otherwise) adds `Distance` (meters from the previous row, via `utils.geo_utils.calculate_distance` on shifted columns), `Real Distance` (cumulative) and `Condition` (`PROTECTED` / `OVER PROTECTED` / `UNPROTECTED` from `Off Voltage` for ICCP or `Voltage` for SACP). It then writes `normalize_excel_filepath` (`<output_dir>/normalize/cips/excel/<year>-<slug>.xlsx`, original names, no index) and `normalize_json_filepath` (`.../json/<year>-<slug>.json`, records with only `voltage`, `off_voltage`, `latitude`, `longitude`, `real_distance`, `condition`, `comment`, `dcp_feature_dcvg_anomaly`; empty/blank cells are `null`). `self.df` keeps the original names. It does not rely on a contiguous index. Chain: `CIPS(...).fix().check().clean().save()`.

   Usage: `PCM(path, year=2024).check().clean().save()`.

3. **`FileIndex.check_cips_file(data_dir, n_jobs=...)`** is the CIPS counterpart: it runs `CIPS(...).fix().check()` per file in parallel and adds `candidate_sheets`. Then, as separate steps, it runs `clean().save()` (records `cleaned_path`) and `normalize()`; `cips_protection` and `normalized_cips_file` (JSON basename) are returned per worker and merged back into `self.df` by row label, since loky workers cannot mutate `self`. `FileIndex.to_json(output_dir)` then writes `<output_dir>/file_index.json` records (`id`, `year`, `area`, `area_code`, `segment`, `pipe_diameter`, `length`, `segment_code`, `cips_protection`, `normalized_cips_file`, `normalized_pcm_file`) for rows that have both normalized files (`NORMALIZED_FILE_KEYS`); every other row goes to `file_index_excluded.json` with `cips_file` / `pcm_file` and a `missing` list. A clean/normalize failure sets `is_valid=False` and a `reason` (`clean failed: …` / `normalize failed: …`) but keeps the check columns. The per-row `duplicates` list is left out of the report because it can exceed Excel's cell limit.

4. **`FileIndex.check_pcm_file(data_dir, n_jobs=...)`** is the fan-out point that runs `PCM(...).clean().save().check()`, then `normalize()` (report `normalized` / `normalized_pcm_file`, merged into `self.df` like the CIPS columns), across every referenced PCM file in parallel via `joblib.Parallel(backend="loky")` and collects each `report`. Loader errors are captured per row (`reason` column) rather than raised, so a single bad file does not abort a batch.

5. **`SyncData`** (`src/corrosions/sync.py`) runs inside `FileIndex.to_json(sync=True)` (default; result on `FileIndex.sync_report`). It reads `file_index.json` (records must have `REQUIRED_KEYS`) and rewrites the normalized JSON and Excel files under `<cwd>/output/normalize/<cips|pcm>/<json|excel>/` **in place** (decision on the JSON; a reversed survey is recalculated once on its Excel and the JSON is rebuilt from it with `json_frame` / `JSON_COLUMNS`; every file of a segment is read and reversed before any is written), so each segment's surveys start at the same end. Each end of a survey is the mean of its first/last `END_READINGS` (5) readings. CIPS starts by its line's main direction (`START`: east-west lines west, north-south lines north; `cips_axis` in the report). PCM is reversed when its last end is closer to the CIPS start than its first (follows CIPS). Segments run in parallel (`n_jobs`, passed through `to_json(..., n_jobs)` from `main.py --n-jobs`); files are written to unique temp files and `os.replace`d only when all of a segment's writes succeeded. A reversed file gets its distances recomputed (JSON `real_distance`, Excel `Distance` / `Real Distance`); PCM also gets the loss rate / condition via the shared `PCM.current_loss` (also used by `PCM.normalize`). Idempotent; files already in order are not rewritten. `sync()` returns a per-segment report (`cips_reversed`, `pcm_reversed`, `start_gap_m`, `reason`).

### Output tree convention

All artifacts land under `<cwd>/output` by default, resolved through `corrosions.utils.path_utils.resolve_output_dir` (a single chokepoint — always call this instead of hard-coding paths). Sub-layouts:

- `output/<destination_dir>/<Year>/<CIPS|PCM>/<filename>` — rebuilt file tree from `FileIndex.rebuild()`.
- `output/cleaned/<year>/<PCM|CIPS>/<filename>` — cleaned Excel files from `.clean().save()`.
- `output/file_index_<slug>.csv` — CSV snapshot of the working DataFrame written by `FileIndex.save()`.

### Logging: gated on `ENABLE_LOG`

`corrosions.logging` configures loguru but **only installs handlers when the environment variable `ENABLE_LOG=true` is set at import time**. Without it, log calls are silent. Two rotating files are written under `<cwd>/logs`: `corrosions_{date}.log` (DEBUG+, 30d retention) and `errors_{date}.log` (ERROR+, 90d). `set_log_level`, `set_log_directory`, `disable_logging`, and `enable_logging` re-install handlers through the shared `_configure_handlers` helper — do not `logger.add` directly.

`.env` is loaded at module import via `python-dotenv` with `override=True`, so `ENABLE_LOG` (and any other env vars) can be set there.

## Tooling notes

- **`ruff.toml`** excludes `tests/`, notebooks, `output*`, and `logs` from linting. `__init__.py` is exempt from `F401`. Docstring convention is Google; import sorting groups `corrosions` as first-party.
- **`ty.toml`** points at `./src` as the type-check root and excludes `tests/`. `no-matching-overload` is disabled.
- **`tests/`** holds pytest files (e.g. `tests/test_base_data.py`, which builds synthetic Excel files under `tmp_path`).

## Wiki

Long-form docs live in `wiki/` (`Home.md`, `API-Reference.md`). Keep the wiki's API reference in sync when public signatures on `FileIndex`, `PCM`, or the logging helpers change.

## Claude Code Guidelines

- Always use available skills whenever possible when executing commands (e.g. use the `scikit-learn` skill for ML tasks, `matplotlib` / `seaborn` skills for plotting, `pandas`-adjacent skills for dataframe work, etc.). Prefer a listed skill over improvising from memory.

## Rules

- **Log every completed task in the daily changelog.** Any finished task — bug fix, refactor, new feature, test, documentation change — must have its outcome recorded in `changelogs/YYYY-mm-dd.md` (using today's date) before moving on. Create the file if it does not exist. Append new entries; never overwrite previous entries in the same file. The `changelogs/` directory is git-ignored (local only).
- **Type checker is `ty`.** Use `uvx ty check src/` for type checking. Always use forward slashes: `uvx ty check src/` (not `.\src`).
- **Lint with `ruff`.** Use `uv run ruff check --fix src/` for linting.
- **All `uv`, `uvx`, and `python` commands are permitted.** `uv sync`, `uv run`, `uv pip install/uninstall`, `uv lock`, `uvx ty check`, `python main.py`, etc. — no need to ask. The user has granted permission to run these commands without approval.
- **Always create a new branch before any commits or modifications.** Use `git checkout -b <prefix>/<branch-name>` before making ANY commits or code modifications. Choose the prefix based on the type of work:
  - `fix/` for bug fixes (e.g. `fix/docstring-errors`)
  - `ft/` for new features (e.g. `ft/add-fdsn-source`)
  - `dev/` as the default for everything else (e.g. `dev/refactor-utils`)

  Never work directly on `main` or `master`.
- **Always use the `tests/` directory when running testing.** Write test outputs inside `tests/`.
- **Do not commit temporary test files.** Files starting with `test` in the repo root (e.g. `test_*.py`, `test.py`) are temporary scratch scripts and are excluded via `.gitignore` — do not commit them.
- **All module imports must be at the top of the file.** Never place `import` statements inside functions, methods, or conditional blocks. All stdlib, third-party, and local imports belong at the module level, grouped and sorted by ruff.
- **Documentation updates are comprehensive.** When asked to add/update docs, update ALL of: `wiki/*.md`, `README.md`. Also update `CLAUDE.md` for architecture/design changes.
- **Always `git checkout <branch>` before creating or working on a branch.** Never create a branch from the wrong base — verify the current branch first with `git status` or `git branch`.
- **Ask when unsure.** If the intent, scope, or correct approach is unclear, ask before proceeding.
