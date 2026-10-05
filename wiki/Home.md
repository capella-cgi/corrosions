# Corrosions Wiki

Welcome to the documentation for the **corrosions** package — a Python toolkit
by [Capella Global Innovation](https://github.com/capella-cgi) for organizing
and validating corrosion survey data (CIPS and PCM) collected from underground
gas pipelines.

## What is this wiki for?

This directory holds all long-form knowledge about the repository that does
not belong in the source code itself: package overviews, API references,
workflow guides, and internal notes. Every page here is a standalone Markdown
file — start from the index below.

## Package summary

- **Name:** `corrosions`
- **Version:** 0.3.0
- **Python:** >= 3.11
- **License:** MIT
- **Repository:** https://github.com/capella-cgi/corrosions
- **Issues:** https://github.com/capella-cgi/corrosions/issues

The package is installed and managed with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync            # install dependencies
uv run python -m corrosions  # run against the current source tree
```

## Documentation index

| Page | What you'll find |
| --- | --- |
| [Home](Home.md) | This page — overview and directory of the wiki. |
| [Normalizing Data](Normalizing-Data.md) | How to normalize one CIPS, PCM or ACVG/DCVG file (`clean().check().save().normalize()`), with example input, Excel, JSON and `report` output. |
| [API Reference](API-Reference.md) | Every public class, method, and helper in the `corrosions` package, grouped by module. |

## Package layout at a glance

```
src/corrosions/
├── __init__.py         # package metadata (__version__, __author__, …)
├── logging.py          # loguru-based logging setup and helpers
├── sync.py             # SyncData: same survey direction for CIPS and PCM; sync_files: one segment from Excel
├── data/
│   ├── file_index.py   # FileIndex: Excel index of CIPS/PCM files
│   ├── base_data.py    # BaseData: fluent clean().check().save().normalize() pipeline, report, normalize paths
│   ├── pcm.py          # PCM(BaseData): single PCM survey file
│   ├── cips.py         # CIPS(BaseData): single CIPS survey file
│   └── acvg_dcvg.py    # AcvgDcvg: anomalies per segment; AcvgDcvgFile(BaseData): clean/normalize
└── utils/
    ├── dataframe_utils.py  # get_sheets / get_sheet_columns helpers
    ├── geo_utils.py    # calculate_distance (haversine, Series-aware)
    └── path_utils.py   # resolve_output_dir helper
```

## Contributing to this wiki

- One topic per file; keep file names in `Title-Case-With-Dashes.md`.
- Cross-link related pages with relative Markdown links.
- Update the **Documentation index** table above when you add a new page.
- Prefer concrete examples pulled from the current source over prose.
