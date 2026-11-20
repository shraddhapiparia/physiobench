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

### Provenance of predicted values and LLN

Established from the code and installed software, not assumed:

- Equations: GLI Global 2022 race-neutral (Bowerman et al., *AJRCCM*
  2023;207:768–774), via `rspiro::pred_GLIgl`, `LLN_GLIgl` and `zscore_GLIgl`
  (`src/gli_reference.R`). No GLI-2012 or ethnicity-specific function is used.
- Software: R 4.5.2, rspiro 0.5 (CRAN binary built 2025-04-01). The lookup
  tables inside rspiro match `gli_global_lookuptables_dec6.xlsx` exactly.
- LLN = 5th centile, i.e. z = −1.645. rspiro computes it as
  LLN = M·(1 − 1.645·L·S)^(1/L), which is the LMS value at z = −1.645
  (`rspiro::LLN_GLIgl` source, version 0.5). An earlier version of this line
  gave "+1.645"; that was a documentation error only. The implementation is
  confirmed by validation check V3 (z at the LLN = −1.645 for every row, max
  deviation 2 × 10⁻¹⁵) and by the official calculator (36/36). rspiro uses the
  rounded constant 1.645 rather than the exact 1.644854; no participant has a
  ratio z-score between the two, so no classification depends on the rounding.
  No LLN value was changed.
- Inputs: `RIDAGEYR` (whole years), `RIAGENDR`, `BMXHT / 100` (m).
- Generated by the committed pipeline (commit 3264b4f). `gli_reference.csv`
  does not itself record the software versions; they are recorded here and in
  `requirements.txt`.

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

## Bronchodilator response and airflow obstruction

`src/bdr.py` merges `spirometry_intermediate.csv` and `gli_reference.csv` on
SEQN (one-to-one) and writes `data/processed/spirometry.csv` (7,495 rows).
All thresholds and boundary operators are in `config.yaml`.

- **Changes** (FEV1 and FVC): absolute change `post − pre` (mL); percent of
  baseline `100·(post − pre)/pre`; percent of predicted
  `100·(post − pre)/GLI predicted`. Computed from the original integer mL
  values, only when pre and post are finite and > 0 (and the prediction for
  the predicted-based change); negative changes are kept; nothing is rounded
  or imputed.
- **GINA 2026** (adults only): positive if FEV1 or FVC rises by ≥ 12 % of
  baseline and ≥ 200 mL in the same measurement; `gina_fev1_only` uses FEV1
  alone. Participants under 18 get `not_applicable_pediatric` (GINA's
  paediatric criterion, ≥ 12 % of predicted FEV1, is not implemented).
  Sources: Global Initiative for Asthma, *GINA 2026 Summary Guide*, Table 1,
  p. 8 ("Adults: FEV1 or FVC increases by ≥12% and by ≥200 mL from the
  pre-bronchodilator value"), and *Global Strategy for Asthma Management and
  Prevention, 2026 update* (Strategy Report), Box 1-2, pp. 28–29 ("Adults:
  increase from baseline in FEV1 or FVC of ≥12% and ≥200 mL"); ginasthma.org.
  Wording checked against both PDFs. Both operators are inclusive.
- **ERS/ATS 2022 source (primary)**: Stanojevic S, Kaminsky DA, Miller MR, et
  al. ERS/ATS technical standard on interpretive strategies for routine lung
  function tests. *Eur Respir J* 2022;60:2101499.
  doi:10.1183/13993003.01499-2021. Criterion: a bronchodilator response is a
  change in FEV1 or FVC of > 10 % of the individual's predicted value. The
  criterion was supplied by the project lead from the standard; the full text
  could not be retrieved in this environment. It is consistent with the GINA
  2026 Strategy Report (p. 22), which cites the 2022 ">10% predicted"
  criterion.
- **ERS/ATS 2022**: positive if the FEV1 or FVC change is > 10 % of the GLI
  Global predicted value; `ats_ers_fev1_only` uses FEV1 alone. Computed at all
  ages.
- **Obstruction** (pre-BD FEV1/FVC): fixed ratio < 0.70; GLI LLN: ratio <
  `gli_fev1fvc_lln` (full precision). These are physiological flags, not
  diagnoses of asthma or COPD. Both are calculated at every age, but the fixed
  ratio is an adult criterion: use `obstruction_fixed_ratio_adult` (blank,
  status `not_applicable_pediatric`, for participants under 18) for
  interpretation; `obstruction_fixed_ratio` is the raw calculation. The GLI
  LLN flag uses age-specific reference values and applies at all ages.
- **Three-valued logic**: classifications are True, False, or blank (not
  assessable). An OR is positive if any component is positive, negative only
  if every component is assessable and negative. Missing or unperformed
  post-BD tests are never negative. `*_status` columns spell this out
  (`positive`, `negative`, `not_assessable`, `not_applicable_pediatric`).
- **Boundaries** are tested by cross-multiplication (e.g. `100·Δ ≥ 12·pre`) so
  exact boundary values are not lost to floating-point division. In the data,
  two FEV1 changes are exactly +200 mL; one of them (an eligible adult) is
  GINA-positive under GINA 2026's ≥ 200 mL and is kept positive.
- **Eligibility**: `primary_bdr_eligible` requires an adult with pre- and
  post-BD FEV1 and FVC present, finite and > 0, all four grades A/B, and valid
  GLI predictions; `primary_bdr_exclusion_reason` gives the first failing
  criterion. Classifications are still reported for ineligible records.

## Descriptive comparisons and candidate cases (Task 6)

`src/summarize.py` reads `spirometry.csv` (unchanged) and writes aggregate
tables to `results/summary/` and pseudonymous candidates to
`benchmark/candidate_cases.csv`.

- All counts are **unweighted NHANES sample counts**. They describe this
  sample, not U.S. prevalence (no survey weights are applied).
- Comparisons use only participants classified under both definitions;
  not-assessable records are excluded and counted separately, never treated
  as negative. Agreement is reported as observed agreement and Cohen's kappa.
- **BDR** (GINA vs ERS/ATS) uses the 275 primary-eligible adults. Sensitivity
  subsets: strict A/B (= primary eligibility), expanded A/B/C (all four
  grades), strict A/B excluding `height_not_straight`, and strict A/B by age
  18–39, 40–59, 60+. Each needs paired, finite, > 0 volumes and valid GLI
  predictions.
- **Obstruction** (fixed < 0.70 vs < GLI LLN) uses adults with valid pre-BD
  FEV1 and FVC and a GLI LLN, reported separately for all assessable adults and
  for pre-BD grades A/B (plus A/B/C, height, and age subsets).
- Disagreements are described by the measurement and criterion that differ.
  This does not imply that either guideline or definition is more clinically
  accurate, and neither obstruction flag is an asthma or COPD diagnosis.
- **Candidates**: about 20 participants chosen by fixed, documented rules
  (guideline disagreements, FEV1-/FVC-only responders, cases nearest each BDR
  threshold, fixed-vs-LLN disagreements, borderline LLN, poor quality, missing
  post-BD data or height). Ties are broken by SEQN, so selection is
  deterministic. Case IDs (`PB001`…) come from an append-only mapping in
  `data/processed/candidate_seqn_mapping.csv` (gitignored): an ID is never
  reassigned. The public table has no SEQN, but because NHANES is public, the
  values in it could be matched back to NHANES records; it is pseudonymous,
  not anonymous.
- **Controls**: expert-chosen BDR controls are listed by SEQN in the private,
  hand-curated registry `data/processed/benchmark_controls.csv` (with their raw
  measurements as a fingerprint, the selection timing and a note). They are
  appended after the rule-based candidates, so existing case IDs never change
  and controls take the next IDs. A control whose measurements or labels no
  longer match `spirometry.csv` stops the run. Because the registry cannot be
  rebuilt from code, it must be backed up with the mapping.

## Benchmark item generation (Task 8)

**Release: PhysioBench v0.1.0, frozen 2026-11-20** (expert-approved; rubric
v0.1.0). See *Release v0.1.0* below.

`src/build_items.py` turns the ten expert specifications in
`benchmark/item_specs.yaml` into model-facing prompts (`benchmark/items.jsonl`)
and a separate grading key (`grading/answer_key.jsonl`). See
`benchmark/README.md` for the rebuild steps and file roles. The item
specifications, grading specification, answer key and grading review are
private (gitignored) until a release decision is made; this section describes
the method only.

- Before writing anything, it validates:
  - every spec (required fields, no unknown fields, unique IDs, case
    measurements, rubric totals);
  - the gold labels, recomputed from the case data by `src/bdr.py`;
  - expert clinical-interpretation fields: any formal label stated there, and
    the overall labels implied by a control role, must equal gold;
  - the case data, against `benchmark/candidate_cases.csv`.
  Gold is never changed automatically; a disagreement stops the build.
- Prompts use case values exactly as written in the spec (no rounding). Rule
  text, including thresholds and operators, is generated from `config.yaml`.
- Titles, capabilities and question objectives in the specs reveal the expected
  answer, so prompts use one neutral question per item family instead. Items
  in the same family, including controls, receive identical rules, question
  and response format; only the participant data differ. Prompts never state
  an item's role, why it was selected, or its expected classification.
- No LLM is called, and gold answers are copied unchanged from the specs.
- Each item has primary classifications (scored) and secondary ones
  (recorded, no points). Which fields are primary is grading-only.

### Benchmark composition

The benchmark is a **purposively selected challenge set**, not a
representative sample: eight items target specific reasoning hazards
(guideline denominators, inclusive thresholds, measurement specificity,
fixed-ratio versus LLN, data quality and missing data), and two are BDR
controls (one concordant-negative, one concordant-positive under both
guidelines). Scores describe performance on these deliberately difficult
cases. They are not estimates of prevalence or of general model accuracy, and
control items are reported separately from challenge items.

**Control selection (retrospective, not pre-registered).** Both controls were
added after the eight challenge items were drafted, and were chosen by the
expert from candidate pools that had already been listed and inspected. They
were chosen before any model was run. Neither selection was pre-registered.

- *Concordant-negative control.* A scripted shortlist of primary-eligible
  adults with all quality grades A, a complete baseline exam, straight height,
  both guidelines negative, and FEV1 and FVC changes far from every threshold
  (small absolute, baseline-relative and predicted-relative changes), ranked
  by the smallest change relative to predicted. The expert chose from the top three,
  rejecting candidates whose baseline ratio lay essentially at the LLN.
- *Concordant-positive control.* Rules written after listing the pool of
  eligible concordant positives: per-measurement agreement between the
  guidelines; a qualifying measurement well above every criterion (GINA's
  higher-confidence level and a margin above ERS/ATS); a non-qualifying
  measurement well below every criterion; no change above the cohort's 90th
  percentile; straight height and a baseline ratio away from both cut-offs.
  Passing cases were ranked by all-A grades, then by closeness to the cohort
  median FEV1 change. Each cut-off is tied to a guideline threshold or a cohort
  statistic rather than to a particular participant, but because the pool was
  seen first, the selection is post hoc.

The exact rules, counts and identifiers are kept in the private selection
record and re-run by the private test suite.

**These are BDR classification controls, not healthy or normal-lung-function
controls.** Both have a baseline FEV1/FVC below 0.70 and below the GLI LLN.
They test whether an unambiguous negative or positive bronchodilator response
is classified correctly; they say nothing about recognising normal spirometry.
Both controls are men; a sex-balanced alternative would have introduced a
partial-criterion (near-threshold) pattern and was declined.

### Numerical grading policy

- Thresholds are applied to unrounded values; the gold labels were derived
  this way.
- Calculations are scored against unrounded reference values. Tolerances
  accept ordinary displayed precision: ±1 mL (whole mL, or L to 3 decimals);
  ±0.05 percentage points (1 decimal); ±0.0005 for ratios and ratio − LLN
  (3 decimals). More decimals are always accepted.
- A value displayed at that precision may reach a threshold it does not meet
  unrounded (e.g. a value just below 12% shown as 12.0%). It earns calculation
  credit if the classification follows the unrounded value.
- Coarser rounding (e.g. a percentage reported as a whole number) loses credit
  for that calculation only.
- Premature rounding that reverses a classification is a classification error,
  scored by the classification anchor, and triggers the item's rounding
  critical error where one is listed.
- A threshold-relative value with the wrong sign (ratio − LLN) is incorrect
  even within tolerance. Where the expected value is null, any number is
  incorrect.

### Formal versus clinical interpretation

- The formal classification follows the stated rule applied to unrounded
  values. A value just below a threshold remains formally negative unless
  another measurement qualifies.
- Where an item is borderline, an answer may also say so: describing a
  near-threshold result as borderline, or noting that a binary label cannot
  diagnose or exclude disease, earns `limits_and_uncertainty` credit without
  changing the formal label. Statements the experts list as not accepted earn
  no such credit.
- Formal classification and clinical interpretation are scored by separate
  criteria and do not affect each other.

### Critical errors

- Each critical error is recorded separately (observed or not) with a
  severity label: `major`, `moderate` or `overreach`. The label is for
  reporting; consequences are set per error in the grading specification.
- Classification and calculation credit is scored only against gold labels and
  tolerances. No flag changes it. If an error produces a wrong label or value,
  the anchor has already removed that credit.
- A flag changes only the criteria it lists, and only
  `scientific_explanation` (a cap or a 1-point deduction) or
  `limits_and_uncertainty` (set to 0). The build rejects any flag that targets
  classification or calculation credit.
- Some errors are pure label errors; they have no extra consequence and are
  recorded for analysis.
- An item may promote per-measurement labels to primary when the expert gold
  summary states them; the build checks them against `src/bdr.py`.
- The public `response_schema` does not say which fields are primary.
- The answer key and grading review are rebuilt deterministically with
  `python3 src/build_items.py`.

## Release v0.1.0

- `benchmark_version` 0.1.0 is set in the expert specifications and carried
  into every generated prompt and answer-key record; the grading rubric is
  also v0.1.0. All ten items are `expert_approved`. The build refuses a release
  version (X.Y.Z) if any item is still a draft or the rubric version differs.
- `src/freeze_manifest.py` records SHA-256 hashes of the frozen artifacts
  (prompts, expert specifications, grading specification, answer key, prompt
  template, review copies, candidate files, case mapping, control registry and
  selection record), the item-to-candidate mapping, the guideline sources and
  thresholds, the GLI implementation, the NHANES source files, the Python/R
  environment and the generation commands. `--check` fails if any frozen
  artifact, the version or the item-to-candidate mapping changes.
- The full manifest is private. The public `docs/release_manifest.json` has the
  same metadata but hashes only public inputs (prompt template, config, code,
  raw NHANES files). Private-file hashes are withheld because the candidate
  pool can be rebuilt from public code and data, so a hash could be used to
  confirm guesses about which participants were used.
- Regeneration is deterministic: `python3 src/summarize.py && python3
  src/build_items.py` reproduces every artifact byte for byte, and the
  candidate mapping is append-only (`src/summarize.py` refuses to change an
  existing ID).

**Not public.** The GitHub repository holds code, synthetic test fixtures, the
generic prompt template, this methodology and aggregate results. The item
specifications, grading specification, model-facing prompts (`items.jsonl`,
`items_review.md`), answer key, grading review, participant-level files,
candidate mapping, control registry and selection record, private manifest and
private tests are gitignored and kept in a separate private backup.

## Tests

Run from the repository root:

```
python3 -m unittest discover -s tests -v
```

Item-specific gold checks, the control-selection re-run and the freeze checks
live in `tests/private/` (gitignored) and run automatically when present. In a
public clone they are absent and the tests that need private files skip. `tests/test_release_protection.py` fails if any
private file is tracked or staged, or if any publishable file contains gold
or grading text, a candidate SEQN or an unrounded real-case value, or if the
public manifest contains a private-file hash.

Public test inventory:

| File | Covers |
|---|---|
| `tests/test_download_nhanes.py`, `tests/test_prepare_spirometry.py`, `tests/test_gli_reference.py` | Data download, preparation and GLI reference values (below) |
| `tests/test_bdr.py` | GINA, ERS/ATS and obstruction classifications |
| `tests/test_summarize.py` | Task 6 summaries, candidate IDs and the control registry (synthetic fixtures) |
| `tests/test_build_items.py` | Item generation: validation, determinism, no gold leakage into prompts (item-specific checks are private) |
| `tests/test_examples.py` | The synthetic worked example: agreement with `src/bdr.py`, exact arithmetic and rspiro, distance from every threshold, consistency with `examples/README.md`, and (when private files exist) absence from the benchmark and the cohort |
| `tests/test_docs.py` | Offline documentation check: relative links, heading anchors and script paths in the public Markdown files |
| `tests/test_release_protection.py` | Private files ignored and untracked; no private content in publishable files |

`tests/test_download_nhanes.py`, `tests/test_prepare_spirometry.py` and
`tests/test_gli_reference.py` cover the codebook exit status, the near-zero
correction, the status labels, quality grades in the GLI output, invalid
observed values, running from outside the repository, and a failed validation
leaving existing output untouched. Integration tests are skipped if the raw
data, processed data, or R/rspiro are unavailable.
