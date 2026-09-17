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
| [API Reference](API-Reference.md) | Every public class, method, and helper in the `corrosions` package, grouped by module. |

## Package layout at a glance

```
src/corrosions/
├── __init__.py         # package metadata (__version__, __author__, …)
├── logging.py          # loguru-based logging setup and helpers
├── data/
│   ├── file_index.py   # FileIndex: Excel index of CIPS/PCM files
│   └── pcm.py          # PCM: single PCM survey loader + QA
└── utils/
    └── path_utils.py   # resolve_output_dir helper
```

## Contributing to this wiki

- One topic per file; keep file names in `Title-Case-With-Dashes.md`.
- Cross-link related pages with relative Markdown links.
- Update the **Documentation index** table above when you add a new page.
- Prefer concrete examples pulled from the current source over prose.
