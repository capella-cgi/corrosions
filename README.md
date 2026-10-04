# Corrosion 

---

### Check CIPS and PCM files

```bash
uv run main.py                  # check both; writes output/checked-cips.xlsx and output/checked-pcm.xlsx
uv run main.py --type cips      # CIPS only
uv run main.py --skip-years     # process every year (default skips 2021)
uv run main.py -y 2021 2022     # skip 2021 and 2022
uv run main.py --no-sync        # keep the normalized JSON in survey order
uv run main.py --help           # index path, source dir, skip years, output dir, workers
```

Loads `IDDA - File List.xlsx` without the `--skip-years` rows (default
`2021`), copies the referenced files from the source
tree (default `D:\Data\Data IDDA`) into `output/raw_data`, then writes one
report per data type:

- `checked-cips.xlsx`: per file, after the CIPS column fixes
  (`Voltage (V)` → `Voltage`, …): the data sheet loaded (`sheet_name`),
  every qualifying sheet (`candidate_sheets`), `has_voltage`, missing
  required columns, and the number of duplicate GPS rows. Each file is
  then cleaned (cleaned copies go to `output/cleaned/<year>/CIPS/`,
  path in `cleaned_path`). A file that cannot be cleaned is marked invalid
  with a `clean failed: …` reason.
- `checked-pcm.xlsx`: missing columns and duplicate GPS rows per file, after
  cleaning (cleaned copies go to `output/cleaned/<year>/PCM/`). Each file
  is then normalized (current loss in `dbma`, `Current Loss Rate`,
  `Condition`) into `output/normalize/pcm/excel|json/`.
- `file_index.json`: one record per index row that has both a normalized
  CIPS and a normalized PCM file (`year`, `area`, `area_code`, `segment`,
  `pipe_diameter`, `length`, `segment_code`, `cips_protection`,
  `normalized_cips_file`, `normalized_pcm_file`).
- `file_index_excluded.json`: the other rows, with their source `cips_file`
  / `pcm_file` and a `missing` list. With `--type cips` or `--type pcm`
  every row lands here, because the other type is never normalized.
- `sync-report.xlsx`: the last step puts each indexed segment's CIPS and PCM
  JSON in the same direction, CIPS starting at its west end and PCM at the
  end closer to the CIPS start. It rewrites `output/normalize/*/json/` in
  place and recomputes `real_distance` (and PCM `current_loss_rate` /
  `condition`). The report lists `cips_reversed`, `pcm_reversed` and
  `start_gap_m` per segment; gaps over 200 m usually mean the CIPS and PCM
  files do not cover the same pipe. Skip this step with `--no-sync`. CIPS files are also normalized into
  `output/normalize/cips/excel|json/`.

Close the reports in Excel before rerunning; Windows locks open files.

### How to
1. Extract indirects > run `data-2025.ipynb`
2. Check `/tests/files.xlsx`
3. Run `all.ipynb`
4. Run `sync.ipynb`
5. Run `calculate-stats.ipynb`
6. Run `seeder-builder.ipynb`