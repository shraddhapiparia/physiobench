# Data

| Folder | Contents | In Git? |
|---|---|---|
| `raw/` | NHANES 2011–2012 `SPX_G.xpt`, `DEMO_G.xpt`, `BMX_G.xpt` from the CDC (`src/download_nhanes.py`) | No (ignored; re-download) |
| `processed/` | Generated: `spirometry_intermediate.csv` (`src/prepare_spirometry.py`), `gli_reference.csv` (`src/gli_reference.R`), `spirometry.csv` (`src/bdr.py`) | No (ignored; rebuild) |
| `reference/` | `gli_global_validation_cases.csv`: GLI Global validation cases, including values entered by hand from the official ERS GLI calculator | **Yes** — not reproducible from code |

Rebuild order:

```
python3 src/download_nhanes.py       # exits non-zero on download failure or codebook mismatch
python3 src/prepare_spirometry.py
Rscript src/gli_reference.R          # exits non-zero, without writing, if validation fails
python3 src/bdr.py                   # BDR and obstruction classifications (thresholds in config.yaml)
python3 src/summarize.py             # aggregate tables (results/summary/) and candidate cases
```

`processed/` also holds participant-level Task 6 files: `candidate_seqn_mapping.csv`
(case ID ↔ SEQN, append-only), `bdr_disagreement_cases.csv`, and
`obstruction_disagreement_cases.csv`.

Two files in `processed/` are **hand-curated and cannot be rebuilt from code**;
back them up and never publish them:

- `benchmark_controls.csv`: expert-chosen BDR controls (by SEQN), read by
  `src/summarize.py`. With it, the candidate set and mapping rebuild
  identically from scratch.
- `concordant_candidates_review.csv`: the shortlist of concordant candidates
  reviewed when the controls were chosen (produced by a one-off query, not by
  `src/`; the query is re-run by the private tests).

See `docs/methodology.md` for variable definitions, status labels, and
validation.
