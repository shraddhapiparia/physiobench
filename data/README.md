# Data

| Folder | Contents | In Git? |
|---|---|---|
| `raw/` | NHANES 2011–2012 `SPX_G.xpt`, `DEMO_G.xpt`, `BMX_G.xpt` from the CDC (`src/download_nhanes.py`) | No (ignored; re-download) |
| `processed/` | Generated: `spirometry_intermediate.csv` (`src/prepare_spirometry.py`), `gli_reference.csv` (`src/gli_reference.R`) | No (ignored; rebuild) |
| `reference/` | `gli_global_validation_cases.csv`: GLI Global validation cases, including values entered by hand from the official ERS GLI calculator | **Yes** — not reproducible from code |

Rebuild order:

```
python3 src/download_nhanes.py       # exits non-zero on download failure or codebook mismatch
python3 src/prepare_spirometry.py
Rscript src/gli_reference.R          # exits non-zero, without writing, if validation fails
```

`processed/spirometry.csv` is an empty placeholder that is still tracked from
the initial commit; it is not yet produced by any script.

See `docs/methodology.md` for variable definitions, status labels, and
validation.
