# PhysioBench methodology

## Data availability, examination status, and bronchodilator selection

These are separate questions and must not be collapsed into one flag. A
missing or not-assessed value is never evidence of a normal result.

| Concept | Meaning | Columns |
|---|---|---|
| Measurement availability | A value was released by CDC | `has_fev1_pre`, `has_fvc_pre`, `has_fev1_post`, `has_fvc_post` |
| Source-data quality | CDC grade of the released value (A–F) | `SPXNQFV1`, `SPXNQFVC`, `SPXBQFV1`, `SPXBQFVC`; `*_grade_AB` (blank if no grade) |
| Examination status | CDC exam outcome | `SPXNSTAT` (baseline); `SPXBSTAT` / `post_bd_exam_status` (post-BD) |
| Bronchodilator selection | CDC's algorithmic selection, plus whether baseline data exist | `SPDBRONC`, `bd_selected`, `bd_selection_status` |
| Analytical eligibility | Decided per analysis (e.g. FEV1 and FVC grades A/B) | not pre-computed |

`bd_selection_status`:

| Value | Definition | n |
|---|---|---|
| `selected` | `SPDBRONC = 1` | 842 |
| `not_selected` | `SPDBRONC = 2` and baseline FEV1 and FVC released | 5,809 |
| `not_selected_no_baseline_values` | `SPDBRONC = 2` but no baseline values (all grade F) | 44 |
| `not_evaluated` | `SPDBRONC` missing (includes discordant SEQN 68442) | 800 |

Only `not_selected` supports the statement "baseline FEV1/FVC did not meet the
CDC selection criteria", and that statement uses CDC's criteria (NHANES III
race-specific LLN or ratio < 0.70), not GLI Global.

`post_bd_exam_status` maps `SPXBSTAT`: `complete` (456), `partial` (1),
`not_done` (218), `safety_exclusion` (167), `not_applicable` (never selected,
6,653). Missing post-BD values for a selected participant mean the test was
not done or not permitted; they do not mean "no bronchodilator response".

**Selection bias.** Post-BD data exist only for participants CDC selected and a
physician cleared (457 of 842 selected). In adults with baseline FEV1 and FVC
grades A/B, 392 are below the GLI Global FEV1/FVC LLN; 17 of them were not
selected, and only 198 have post-BD values. Any post-BD result describes this
selected, medically screened group, not all adults with airflow limitation.

## GLI Global reference equations

### Implementation

Predicted values, lower limits of normal (LLN), and z-scores for pre-bronchodilator
FEV1, FVC, and FEV1/FVC are calculated with the race-neutral GLI Global (2022)
equations (Bowerman et al., *Am J Respir Crit Care Med* 2023;207:768–774), using
the R package `rspiro` (functions `pred_GLIgl`, `LLN_GLIgl`, `zscore_GLIgl`).

- Software: R 4.5.2, rspiro 0.5 (CRAN).
- Script: `src/gli_reference.R`. Input: `data/processed/spirometry_intermediate.csv`.
  Output: `data/processed/gli_reference.csv`, one row per SEQN (7,495 rows).
- Inputs: age = `RIDAGEYR` (years), sex = `RIAGENDR` (1 = male, 2 = female, the
  coding rspiro expects), height = `BMXHT / 100` (metres), FEV1 and FVC in litres
  (`SPXNFEV1`, `SPXNFVC` / 1000); FEV1/FVC as a fraction.
- LLN is the 5th centile (z = −1.645).
- No imputation. Predictions are missing when age (supported range 3–95 years),
  sex, or height is unavailable; z-scores are also missing when the baseline
  measurement is missing. The reason is recorded per row.
- Observed values must be finite and greater than zero to receive a z-score;
  zero, negative, or infinite values keep their predictions but get no z-score
  (reason "invalid baseline FEV1/FVC"). None occur in the current data
  (minimum FEV1 0.409 L, FVC 0.592 L).
- z-scores are computed regardless of quality grade, so the output carries
  `SPXNSTAT`, `SPXNQFV1`, `SPXNQFVC`, `fev1_pre_grade_AB`, `fvc_pre_grade_AB`
  and `fev1fvc_pre_grades_AB` (both grades A/B; blank if a grade is missing).
  1,165 participants with z-scores are not A/B on both, including 306 graded
  D or F; analyses must filter on these columns.
- The script resolves paths from its own location and can be run from any
  directory. A failed validation stops the run before the output is written.

### Known limitations

- **Age in whole years.** NHANES `RIDAGEYR` is public only in whole years, so the
  true age is up to about one year older than the value used. GLI splines are
  tabulated at quarter-year steps, so whole-year ages are looked up exactly;
  the limitation is the age itself, not the lookup.
- **Height measured "not straight".** Participants with `BMIHT = 3` (126
  participants, all adults) are retained with predictions and flagged as
  `height_not_straight` for a sensitivity analysis, because a reduced standing
  height may underestimate predicted values.
- Height is missing for 76 participants (65 adults); they have no predictions.

### Validation

| Check | Method | Result |
|---|---|---|
| **External: official GLI calculator** | Four synthetic cases (below) entered by hand at the ERS GLI calculator (gli-calculator.ersnet.org, *Race-neutral* option, pre-BD FEV1 and FVC only) on 2026-11-17. Predicted, LLN, and z-score for FEV1, FVC, and FEV1/FVC recorded as displayed (3 dp) and compared with rspiro; tolerance 0.01. | **36/36 pass.** Max \|difference\|: predicted 0.00046, LLN 0.00050, z-score 0.00045. All 36 rspiro values rounded to 3 dp equal the calculator's values exactly. |
| Independent reimplementation | Standalone Python code (no rspiro) using the GLI lookup workbook `gli_global_lookuptables_dec6.xlsx` and the equations printed in it; same four cases and all 7,419 participants with predictions. | Max \|difference\| 3 × 10⁻¹⁴. The workbook is the one rspiro was built from, so this checks rspiro's arithmetic and sheet mapping, not the workbook. |
| Row-order integrity | Vectorised results vs one-participant-at-a-time calls (25 random rows). | Identical. |
| Internal identities | z(predicted) = 0 and z(LLN) = −1.645 for every participant with predictions. | Max deviation 2 × 10⁻¹⁵. |
| LLN vs z-score agreement | FEV1/FVC < LLN compared with z < −1.645 (n = 6,615). | 0 disagreements. |

The external check is the only one independent of the shared lookup workbook.

Validation cases (`data/reference/gli_global_validation_cases.csv`; synthetic,
not NHANES participants):

| Case | Sex | Age (y) | Height (cm) | FEV1 (L) | FVC (L) |
|---|---|---|---|---|---|
| C1 | Male | 40 | 175 | 3.20 | 4.30 |
| C2 | Female | 65 | 160 | 1.80 | 2.60 |
| C3 | Male | 12 | 150 | 2.50 | 2.90 |
| C4 | Female | 25 | 168 | 3.40 | 3.90 |

Calculator values (predicted / LLN / z):

| Case | FEV1 | FVC | FEV1/FVC |
|---|---|---|---|
| C1 | 3.835 / 2.939 / −1.176 | 4.699 / 3.618 / −0.603 | 0.815 / 0.710 / −1.151 |
| C2 | 2.175 / 1.539 / −0.984 | 2.747 / 1.971 / −0.307 | 0.796 / 0.671 / −1.389 |
| C3 | 2.388 / 1.880 / 0.375 | 2.781 / 2.190 / 0.328 | 0.866 / 0.755 / −0.066 |
| C4 | 3.338 / 2.577 / 0.138 | 3.862 / 2.990 / 0.071 | 0.869 / 0.761 / 0.045 |

The validation runs on every execution of `src/gli_reference.R`; the script exits
with a non-zero status, without writing output, if any check fails. Validation
cases must be exactly C1–C4 for each source with identical paired inputs; all
nine values per case must be present and finite; the tolerance is capped at
0.01 in code and calculator values must also agree to within 0.0005 (3-dp
display rounding).

## Tests

Run from the repository root:

```
python3 -m unittest discover -s tests -v
```

`tests/test_download_nhanes.py`, `tests/test_prepare_spirometry.py` and
`tests/test_gli_reference.py` cover the codebook exit status, the near-zero
correction, the status labels, quality grades in the GLI output, invalid
observed values, running from outside the repository, and a failed validation
leaving existing output untouched. Integration tests are skipped if the raw
data, processed data, or R/rspiro are unavailable.
