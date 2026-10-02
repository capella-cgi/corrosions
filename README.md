# Corrosion 

---

### Check CIPS and PCM files

```bash
uv run main.py                  # check both; writes output/checked-cips.xlsx and output/checked-pcm.xlsx
uv run main.py --type cips      # CIPS only
uv run main.py --help           # index path, source dir, output dir, workers
```

Loads `IDDA - File List.xlsx`, copies the referenced files from the source
tree (default `D:\Data\Data IDDA`) into `output/raw_data`, then writes one
report per data type:

- `checked-cips.xlsx`: per file, after the CIPS column fixes (`Index` →
  `Data No`, `Voltage (V)` → `Voltage`, …): the data sheet loaded
  (`sheet_name`), every qualifying sheet (`candidate_sheets`),
  `has_altitude`, `has_voltage`, missing required columns, and the number
  of duplicate GPS rows.
- `checked-pcm.xlsx`: missing columns and duplicate GPS rows per file, after
  cleaning (cleaned copies go to `output/cleaned/<year>/PCM/`).

Close the reports in Excel before rerunning; Windows locks open files.

### How to
1. Extract indirects > run `data-2025.ipynb`
2. Check `/tests/files.xlsx`
3. Run `all.ipynb`
4. Run `sync.ipynb`
5. Run `calculate-stats.ipynb`
6. Run `seeder-builder.ipynb`