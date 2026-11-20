# PhysioBench

**A benchmark for guideline-based pulmonary-function reasoning in language models.**

PhysioBench tests whether language models can apply spirometry interpretation rules **and explain their conclusions appropriately**—especially when guideline definitions disagree, measurements lie near a threshold, or data are incomplete. The initial release focuses on adult bronchodilator responsiveness and baseline airflow-obstruction classifications using public-use NHANES 2011–2012 spirometry data.

It is a focused benchmark of applying supplied clinical standards to structured measurements. It is **not** an evaluation of autonomous research agents, tool use or end-to-end data analysis.

> **Status — v0.1.0 (frozen 2026-11-20):** The ten-item benchmark and its expert grading specification are frozen and verified. **No model has been run and no results exist yet.** The model runner and graders (`src/run_models.py`, `src/grade_deterministic.py`, `src/grade_judge.py`) are empty placeholders for the next stage. No model-performance claims are made.

## What is being evaluated?

The initial ten-item set contains **eight targeted reasoning challenges and two concordant bronchodilator-response (BDR) controls**. It evaluates four capabilities:

| Capability | What the model must do |
| --- | --- |
| Guideline application | Independently apply GINA 2026 and ERS/ATS 2022 bronchodilator-response rules to FEV1 and FVC. |
| Reference-limit interpretation | Compare baseline FEV1/FVC with the adult fixed-ratio threshold and an individual GLI lower limit of normal (LLN). |
| Data reliability | Distinguish calculable response from the project's stricter A/B-quality eligibility, and **not assessable** from negative. |
| Clinical interpretation | Recognize borderline measurements, explain discordant classifications, and avoid turning spirometric findings into unsupported diagnoses. |

The challenge items cover inclusive threshold boundaries, denominator-dependent guideline disagreement, measurement-specific (FEV1 versus FVC) responses, age-sensitive obstruction definitions, quality restrictions and missing post-bronchodilator values. The two controls are clear-cut negative and positive bronchodilator responses; they are BDR-classification controls, **not** healthy or normal-lung-function controls. **The cases are purposively selected, not a representative NHANES sample or an estimate of clinical prevalence.**

A fully synthetic worked example, separate from the benchmark, is in [`examples/`](examples/README.md).

## Scientific reference rules

The benchmark explicitly provides the applicable rules to the model. It therefore measures **application and interpretation of supplied standards**, not unaided recall of clinical guidelines.

| Standard | Operational definition used in the benchmark |
| --- | --- |
| GINA 2026 (adults) | A post-bronchodilator increase in **FEV1 or FVC** of **≥12% of its pre-bronchodilator value and ≥200 mL**, with both conditions satisfied in the same measurement. |
| ERS/ATS 2022 | A change in **FEV1 or FVC >10% of its corresponding predicted value**. |
| Baseline fixed-ratio comparison (adults) | FEV1/FVC <0.70. |
| GLI LLN comparison | Baseline FEV1/FVC below its individual GLI Global 2022 fifth-percentile LLN. |

Thresholds and operators are defined once, in [`config.yaml`](config.yaml), and the rule text in every prompt is generated from it. Threshold comparisons use **unrounded values**. The benchmark keeps formal threshold classification separate from clinical significance: a measurement marginally below a cutoff is formally below it, but may be clinically borderline. Neither bronchodilator responsiveness nor a baseline obstruction flag is, by itself, an asthma or COPD diagnosis.

GLI Global 2022 race-neutral reference values were generated with `rspiro` 0.5 under R 4.5.2 and validated against the ERS GLI calculator and an independent implementation. See [methodology](docs/methodology.md) for data-processing, quality-control, reference-equation and cohort details.

## Data and benchmark construction

| Step | Command | Inputs |
| --- | --- | --- |
| 1. Download NHANES 2011–2012 spirometry, demographics and body measures | `python3 src/download_nhanes.py` | Public CDC files |
| 2. Prepare spirometry, status and quality fields | `python3 src/prepare_spirometry.py` | Public |
| 3. GLI Global 2022 reference values (with validation) | `Rscript src/gli_reference.R` | Public; needs R and `rspiro` |
| 4. Deterministic GINA, ERS/ATS and obstruction classifications | `python3 src/bdr.py` | Public |
| 5. Unweighted concordance, disagreement and sensitivity summaries; candidate cases | `python3 src/summarize.py` | Public; the two controls need a private registry |
| 6. Model-facing prompts and a **separate** expert answer key, each validated against the pipeline | `python3 src/build_items.py` | **Private** item and grading specifications |
| 7. Verify the frozen release | `python3 src/freeze_manifest.py --check` | **Private** manifest |

Steps 1–4 and the aggregate tables in step 5 can be reproduced from a public checkout. Counts are unweighted NHANES sample counts, not population prevalence. Steps 6–7 require the withheld evaluation files.

Strict field validation, recomputation of every gold label by the classification code, deterministic (byte-identical) generation and SHA-256 release manifests support reproducibility. Control selection was **retrospective and not preregistered**.

## Evaluation protocol (planned; not yet run)

Each item requests structured fields for classifications, calculations, scientific explanation and limitations. The frozen grading specification defines **separate outcomes**, which the evaluation stage is designed to report:

- **Strict endpoint success:** all required primary classifications match the frozen gold labels.
- **Numerical correctness:** calculations match specified precision/tolerance rules, with classifications evaluated on unrounded values.
- **Scientific reasoning score (0–8):** 2 points for classifications, 2 for calculations, 3 for explanation, and 1 for appropriate limitations.
- **Clinical error flags:** predefined critical errors and newly observed failure modes, analyzed separately from the numerical score.
- **Execution reliability:** response-schema validity, missing/failed responses and repeat-to-repeat consistency.

The initial evaluation plan is **one Gemini model, three runs per item**, with full run settings and output metadata retained. None of this has been run, and the grading code is not yet implemented. An LLM-as-judge, multi-model leaderboard and autonomous tool-use evaluations are outside the initial scope.

The [synthetic example](examples/README.md#6-deterministic-grading-versus-explanation-grading) illustrates the difference between deterministic classification grading and explanation grading.

## Repository guide

| Path | Purpose |
| --- | --- |
| `config.yaml` | Versioned guideline thresholds, operators and eligibility rules. |
| `src/` | NHANES download and preparation, GLI reference values, classification logic, summaries, benchmark generation and the release manifest. `run_models.py` and `grade_*.py` are placeholders. |
| `benchmark/prompt_template.txt` | Generic, model-facing prompt template. |
| `benchmark/README.md` | Roles of the benchmark files (most are private) and rebuild commands. |
| `examples/` | One fully synthetic worked example, excluded from the benchmark. |
| `data/README.md` | Data folders and rebuild order; data files are not in Git. |
| `data/reference/` | GLI Global validation cases. |
| `docs/methodology.md` | Scientific data processing, study design, decisions and limitations. |
| `docs/release_manifest.json` | Public release metadata (environment, sources, commands) and checksums for publishable inputs. |
| `results/summary/` | Aggregate, **unweighted** diagnostic and sensitivity summaries. |
| `tests/` | Public unit, example and release-protection tests. |

### Run public checks

```bash
git clone https://github.com/shraddhapiparia/physiobench.git
cd physiobench
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 examples/render_example.py
```

A public checkout intentionally does **not** contain the ten held-out evaluation prompts, case-level data, grading keys or the private end-to-end validation inputs. Tests that require these resources, downloaded NHANES files or R are skipped in the public workflow. R and `rspiro` are required for the reference-equation step; see [methodology](docs/methodology.md) and [data/README.md](data/README.md) for environment and rebuild details.

## Evaluation-set access and disclosure

The frozen ten-item question set, expert specifications, answer key, participant mappings, private tests and case-level files are withheld from the public repository to reduce evaluation contamination and unintentional disclosure of linkable participant records. Public NHANES source data remain available from the CDC. The public repository contains the **pipeline and methodology**, but does not promise that every held-out evaluation can be reconstructed from public files alone.

The worked example in [`examples/`](examples/README.md) is synthetic and **not** part of the held-out set. Results and documented failure analyses will be released after the initial evaluation; no results are implied by the frozen benchmark version.

## Limitations

- The initial **10 items** are a curated challenge set, not an externally validated clinical assessment or an estimate of performance across all physiology tasks.
- The task measures interpretation of supplied standards, not autonomous acquisition, cleaning and analysis of clinical data.
- The standard-defined classifications are reproducible, but clinically appropriate interpretation also requires judgment and acknowledgment of measurement variability.
- The dataset is public-use and case-level measurements may be linkable to NHANES records; therefore the evaluation materials are not described as anonymous.
- Outputs are for benchmarking and research, **not patient-level clinical decision-making**.

## References

- [GINA 2026 reports and resources](https://ginasthma.org/)
- Stanojevic S, et al. *ERS/ATS technical standard on interpretive strategies for routine lung function tests*. *European Respiratory Journal*. 2022;60:2101499. [DOI: 10.1183/13993003.01499-2021](https://doi.org/10.1183/13993003.01499-2021)
- Bowerman C, et al. *A race-neutral approach to the interpretation of lung function measurements*. *American Journal of Respiratory and Critical Care Medicine*. 2023;207:768–774 (GLI Global 2022).
- [CDC National Health and Nutrition Examination Survey](https://www.cdc.gov/nchs/nhanes/)

For implementation and provenance details, see [docs/methodology.md](docs/methodology.md).
