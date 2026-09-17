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

The `main.py` at the repo root is a stub CLI scaffold (argparse only, `main()` returns `None`). Real workflows currently live in Jupyter notebooks at the repo root (`file-index.ipynb`, `check.ipynb`, `check-existsing-files.ipynb`) that drive the `corrosions` package.

## Architecture

The package lives under `src/corrosions/` (src layout — always import from the installed package, not by relative path).

### Domain: CIPS and PCM survey data

The package organizes and validates two types of corrosion survey files collected on underground gas pipelines: **CIPS** (Close Interval Potential Survey) and **PCM** (Pipeline Current Mapping). Files arrive as year-partitioned Excel workbooks and are indexed by a single master Excel spreadsheet (e.g. `IDDA - File List.xlsx` at the repo root).

### Two-layer design

1. **`FileIndex`** (`src/corrosions/data/file_index.py`) is the top-level orchestrator. It loads the master Excel index, validates its schema (`FileIndex.COLUMNS`), normalizes filenames (`fix()`), verifies each referenced file exists at `<data_dir>/<Year>/<CIPS|PCM> FINAL/<filename>` (`check_existing_file()`), and copies referenced files into a clean output tree (`rebuild()`). Most mutating methods return `Self` to support chaining and set boolean flags (`checked`, `fixed`) to make idempotency explicit.

2. **`PCM`** (`src/corrosions/data/pcm.py`) is the per-file worker. It loads one PCM Excel export, coerces `NUMERIC_COLUMNS` with `pd.to_numeric(..., errors="coerce")` at construction, drops rows with any NaN in numeric columns (`clean()`), and reports data quality via `check()` (missing required columns + duplicate rows on `UNIQUE_COLUMNS = ("Int GPS Latitude", "Int GPS Longitude")`).

3. **`FileIndex.check_pcm_quality(data_dir, n_jobs=...)`** is the fan-out point that runs `PCM.check` across every referenced PCM file in parallel via `joblib.Parallel(backend="loky")`. Loader errors are captured per row (`reason` column) rather than raised, so a single bad file does not abort a batch.

### Output tree convention

All artifacts land under `<cwd>/output` by default, resolved through `corrosions.utils.path_utils.resolve_output_dir` (a single chokepoint — always call this instead of hard-coding paths). Sub-layouts:

- `output/<destination_dir>/<Year>/<CIPS|PCM>/<filename>` — rebuilt file tree from `FileIndex.rebuild()`.
- `output/cleaned/<year>/PCM/<filename>` — cleaned PCM Excel files from `PCM.clean()/save()`. `PCM.check()` will reuse a pre-existing cleaned file at that path instead of re-cleaning.
- `output/file_index_<slug>.csv` — CSV snapshot of the working DataFrame written by `FileIndex.save()`.

### Logging: gated on `ENABLE_LOG`

`corrosions.logging` configures loguru but **only installs handlers when the environment variable `ENABLE_LOG=true` is set at import time**. Without it, log calls are silent. Two rotating files are written under `<cwd>/logs`: `corrosions_{date}.log` (DEBUG+, 30d retention) and `errors_{date}.log` (ERROR+, 90d). `set_log_level`, `set_log_directory`, `disable_logging`, and `enable_logging` re-install handlers through the shared `_configure_handlers` helper — do not `logger.add` directly.

`.env` is loaded at module import via `python-dotenv` with `override=True`, so `ENABLE_LOG` (and any other env vars) can be set there.

## Tooling notes

- **`ruff.toml`** excludes `tests/`, notebooks, `output*`, and `logs` from linting. `__init__.py` is exempt from `F401`. Docstring convention is Google; import sorting groups `corrosions` as first-party.
- **`ty.toml`** points at `./src` as the type-check root and excludes `tests/`. `no-matching-overload` is disabled.
- **`tests/`** currently contains Jupyter notebooks rather than pytest files — treat with care when adding real tests.

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
