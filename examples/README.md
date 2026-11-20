# Synthetic worked example — entirely invented, not part of the benchmark

> [!IMPORTANT]
> **Synthetic and illustrative only.**
>
> - **Entirely synthetic:** every value below (age, sex, height, spirometry,
>   quality grades) was invented for documentation.
> - **Not a real participant:** it is not an NHANES record and does not
>   correspond to any person.
> - **Excluded from the held-out benchmark:** it is not one of the ten
>   PhysioBench v0.1.0 items and is absent from the item specifications,
>   model-facing items, case mapping and answer key. It shares no measurement
>   with any held-out item.
>
> The prompt below is rendered from the benchmark's shared, generic template.
> Its opening sentence ("one spirometry (lung function) record from a research
> dataset") is generic template wording used for every item; it does **not**
> mean this example comes from a research dataset.

Files:

| File | Contents |
|---|---|
| [`synthetic_spirometry_example.json`](synthetic_spirometry_example.json) | Case data (same fields as a benchmark item), reference answer and margins |
| [`render_example.py`](render_example.py) | Renders the prompt with the benchmark's own code and recomputes the answer with `src/bdr.py` |

```bash
python3 examples/render_example.py            # prompt, recomputed reference, demo check
python3 examples/render_example.py --prompt   # model-facing prompt only
```

`tests/test_examples.py` checks that this page, the JSON file and the
pipeline agree.

## 1. The case

An invented 44-year-old woman, 163.0 cm, with complete pre- and
post-bronchodilator spirometry, all quality grades A. Predicted values and the
FEV1/FVC lower limit of normal (LLN) are GLI Global 2022 race-neutral values
computed with `rspiro` 0.5, the same functions used by `src/gli_reference.R`.

| Measurement | Pre | Post | Change | % of pre | Predicted | % of predicted |
|---|---|---|---|---|---|---|
| FEV1 | 2.040 L | 2.540 L | +500 mL | 24.51% | 2.795 L | 17.89% |
| FVC | 3.010 L | 3.470 L | +460 mL | 15.28% | 3.388 L | 13.58% |

Baseline FEV1/FVC is 0.6777 (LLN 0.7106). The values in
the table are rounded for display; every classification uses unrounded values.

## 2. Model-facing prompt

As noted above, the template's reference to "a research dataset" is generic
wording; this example is invented. The prompt uses the same template
(`benchmark/prompt_template.txt`), rule text
(generated from `config.yaml`), neutral question and response schema as the
benchmark's bronchodilator-response items. Only the participant data differ.

````text
You are given one spirometry (lung function) record from a research dataset. Use only the information provided. Do not assume, estimate or impute any value that is not given.

PARTICIPANT DATA
Participant
- Age: 44 years (recorded in whole years)
- Sex: female
- Standing height: 163.0 cm

Spirometry (pre = before bronchodilator; post = after bronchodilator)
- Post-bronchodilator test: completed
- FEV1 pre: 2.04 L
- FEV1 post: 2.54 L
- FVC pre: 3.01 L
- FVC post: 3.47 L
- FEV1/FVC pre (unrounded): 0.6777408637873754

Reference values (GLI Global 2022, race-neutral; unrounded)
- Predicted FEV1: 2.79480827552582 L
- Predicted FVC: 3.38784758814049 L
- Lower limit of normal (LLN) for FEV1/FVC: 0.710567896379585

Measurement quality grades (A exceeds ATS standards; B meets ATS standards; C potentially usable but does not meet all ATS standards; D questionable; F not valid)
- FEV1 pre: A
- FVC pre: A
- FEV1 post: A
- FVC post: A

RULES
GINA 2026 bronchodilator responsiveness (adults, age ≥18 years)
- For each measurement (FEV1, FVC), change = post − pre.
- A measurement is positive if its change is ≥12% of that same measurement's pre-bronchodilator value AND ≥200 mL. Both conditions must be met by the same measurement.

ERS/ATS 2022 bronchodilator responsiveness
- A measurement is positive if its change (post − pre) is >10% of that same measurement's predicted value (GLI Global 2022).

Overall classification for each guideline
- positive if FEV1 or FVC is positive; negative only if both FEV1 and FVC can be assessed and both are negative; otherwise not_assessable.

General conventions
- Apply every threshold to unrounded values. Round only when reporting.
- If a classification cannot be determined from the data provided, answer "not_assessable". Not assessable is different from negative.
- Baseline FEV1/FVC classifications describe a pre-bronchodilator measurement only; they are not a diagnosis of asthma, COPD or any other disease.

QUESTION
Classify the bronchodilator response under GINA 2026 and under ERS/ATS 2022. Evaluate FEV1 and FVC separately for each guideline, then give each guideline's overall classification. Explain the physiological and methodological reasons the two guidelines agree or differ for this record.

RESPONSE FORMAT
Reply with a single JSON object and nothing else, using exactly these fields. Give a classification for every field listed. Report calculations as unrounded numbers, or null where a value cannot be computed.
{
  "classifications": {
    "gina_2026_fev1": "positive | negative | not_assessable",
    "gina_2026_fvc": "positive | negative | not_assessable",
    "gina_2026_overall": "positive | negative | not_assessable",
    "ers_ats_2022_fev1": "positive | negative | not_assessable",
    "ers_ats_2022_fvc": "positive | negative | not_assessable",
    "ers_ats_2022_overall": "positive | negative | not_assessable"
  },
  "calculations": {
    "fev1_change_mL": "number (unrounded) or null if it cannot be computed",
    "fev1_change_pct_of_baseline": "number (unrounded) or null if it cannot be computed",
    "fev1_change_pct_of_predicted": "number (unrounded) or null if it cannot be computed",
    "fvc_change_mL": "number (unrounded) or null if it cannot be computed",
    "fvc_change_pct_of_baseline": "number (unrounded) or null if it cannot be computed",
    "fvc_change_pct_of_predicted": "number (unrounded) or null if it cannot be computed"
  },
  "physiological_explanation": "string",
  "limitations": "string"
}
````

## 3. Reference answer

```json
{
  "classifications": {
    "gina_2026_fev1": "positive",
    "gina_2026_fvc": "positive",
    "gina_2026_overall": "positive",
    "ers_ats_2022_fev1": "positive",
    "ers_ats_2022_fvc": "positive",
    "ers_ats_2022_overall": "positive"
  },
  "calculations": {
    "fev1_change_mL": 500.0,
    "fev1_change_pct_of_baseline": 24.50980392156863,
    "fev1_change_pct_of_predicted": 17.890314851952738,
    "fvc_change_mL": 460.0,
    "fvc_change_pct_of_baseline": 15.282392026578073,
    "fvc_change_pct_of_predicted": 13.577942573635175
  },
  "physiological_explanation": "FEV1 rose by 500 mL, 24.5% of its pre-bronchodilator value, and FVC rose by 460 mL, 15.3% of its pre-bronchodilator value; each measurement independently meets both GINA 2026 criteria (>=12% and >=200 mL in the same measurement), so GINA is positive. Relative to GLI predicted values, the FEV1 change is 17.9% and the FVC change 13.6% of predicted; both exceed the ERS/ATS 2022 criterion of >10% of predicted, so ERS/ATS is positive. The guidelines use different denominators (pre-bronchodilator value vs predicted value) but agree here because both changes are well clear of every threshold; the smallest margin is FVC, 3.3 percentage points above 12% of baseline and 3.6 points above 10% of predicted. A rise in both FEV1 and FVC is consistent with bronchodilator-reversible airflow limitation, possibly with reduced air trapping.",
  "limitations": "A positive bronchodilator response is a physiological finding, not a diagnosis: it supports reversible airflow limitation but does not by itself establish asthma, and it can occur in COPD. The baseline FEV1/FVC (0.678) is below 0.70 and below the GLI LLN, but whether obstruction persists after the bronchodilator was not asked and needs post-bronchodilator interpretation and clinical context. This is a single test session; responses vary between occasions, and interpretation depends on repeatability, symptoms and history. Age is recorded in whole years, which slightly affects the predicted values."
}
```

## 4. Calculations and criteria

Change = post − pre. GINA uses the measurement's own pre-bronchodilator value
as denominator; ERS/ATS uses its GLI predicted value.

| Criterion | FEV1 | FVC | Threshold | FEV1 | FVC |
|---|---|---|---|---|---|
| GINA: change ≥200 mL | 500 mL | 460 mL | ≥200 mL | met (+300) | met (+260) |
| GINA: change ≥12% of pre | 500 / 2040 = 24.510% | 460 / 3010 = 15.282% | ≥12% | met (+12.51) | met (+3.28) |
| ERS/ATS: change >10% of predicted | 500 / 2794.8 = 17.890% | 460 / 3387.8 = 13.578% | >10% | met (+7.89) | met (+3.58) |

- **GINA 2026:** FEV1 positive and FVC positive, because each meets *both*
  criteria within the same measurement. Overall **positive**.
- **ERS/ATS 2022:** FEV1 positive and FVC positive. Overall **positive**.
- The smallest margin is FVC: 3.3 percentage points above 12% of baseline and
  3.6 points above 10% of predicted, well beyond ordinary display rounding. The
  case was chosen so that no classification depends on a borderline value.

All values were computed by `src/bdr.py` (through
`build_items.recompute`) and checked independently with exact rational
arithmetic.

## 5. Clinical interpretation and limitations

- A rise in both FEV1 and FVC is consistent with bronchodilator-reversible
  airflow limitation, possibly with reduced air trapping.
- A positive bronchodilator response is a **physiological finding, not a
  diagnosis**. It supports reversibility but does not by itself establish
  asthma, and it also occurs in COPD.
- The baseline FEV1/FVC is below 0.70 and below the LLN. The question does not
  ask about obstruction, and persistent obstruction would need
  post-bronchodilator interpretation and clinical context.
- This is a single test session. Responses vary between occasions, and
  interpretation depends on repeatability, symptoms and history.
- Age is recorded in whole years, which slightly affects predicted values.

## 6. Deterministic grading versus explanation grading

PhysioBench scores structured answers in two different ways. In v0.1.0 the
scoring rules are frozen, but **no automated grader or model results exist
yet**; the check below is a toy illustration run by `render_example.py`.

**Deterministic part (computable).** Each classification is compared exactly
with the reference. Each calculation is compared with the unrounded reference
within a tolerance that accepts ordinary display precision (±1 mL; ±0.05
percentage points), as described in the
[methodology](../docs/methodology.md#numerical-grading-policy).

| Response | Classifications correct | Calculations within tolerance | Calculations outside tolerance |
|---|---|---|---|
| A: reference answer | 6/6 | 6/6 | none |
| B: correct labels, coarse rounding, overclaim | 6/6 | 5/6 | `fvc_change_pct_of_baseline` |
| C: correct labels, wrong ERS/ATS denominator | 6/6 | 4/6 | `fev1_change_pct_of_predicted`, `fvc_change_pct_of_predicted` |

Response B is A's answer with FVC % of baseline reported as `15` (coarse
rounding) and the limitation "This confirms a diagnosis of asthma." Response C
reports % of predicted using the pre-bronchodilator denominator (24.51% and
15.28%) and explains ERS/ATS as "more than 10% of the pre-bronchodilator
value".

**Explanation part (judgement).** The physiological explanation and the
limitations are scored against item-specific reasoning requirements and
acceptable qualifications, with critical errors recorded separately. This
needs a rubric-guided reviewer, not string matching:

| Response | What deterministic checks show | What explanation grading adds |
|---|---|---|
| A | All classifications and calculations correct | Correct reasoning; appropriate, non-diagnostic limitations |
| B | Labels correct; one calculation outside tolerance | Reasoning adequate, but "confirms a diagnosis of asthma" is an overclaim: no credit for limitations |
| C | Labels correct; % predicted wrong | Right answer for the wrong reason: the ERS/ATS denominator is wrong. This would be recorded as a method error even though every label is correct |

Response C shows why the two parts are kept separate. In this case the wrong
denominator still yields the correct labels, because every change is far from
the threshold, so a score based on labels alone would miss the error. Near a
threshold, the same error can change the labels.

The item-specific requirements, qualifications and critical errors for the
held-out benchmark items are private and are not shown here.
