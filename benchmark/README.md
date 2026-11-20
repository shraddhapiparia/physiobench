# Benchmark items (PhysioBench v0.1.0, frozen 2026-11-20)

| File | Audience | In Git? | Contents |
|---|---|---|---|
| `item_specs.yaml` | Authors | **No (private)** | Expert item specifications: case data, gold labels, reasoning, critical errors, clinical-interpretation fields |
| `grading_spec.yaml` | Authors / graders | **No (private)** | Rubric anchors, numerical and clinical-interpretation policy, tolerances, acceptable qualifications, critical-error severities |
| `candidate_cases.csv` | Authors | **No (private)** | Task 6 candidate cases (incl. controls) used to cross-check specs |
| `prompt_template.txt` | Authors | Yes | Shared prompt template (`$case_block`, `$rules_block`, `$question`, `$response_format`) |
| `items.jsonl` | **Model-facing** | **No (private)** | One record per item: `item_id`, `benchmark_version`, `prompt`, `response_schema`. Runners send only `prompt`. |
| `items_review.md` | Expert reviewers | **No (private)** | The ten prompts and response schemas as Markdown, generated from `items.jsonl` (no grading content) |
| `../grading/answer_key.jsonl` | **Graders only** | **No (private)** | Gold, key calculations with tolerances, required reasoning, qualifications, critical errors, item role |
| `../grading/grading_review.md` | **Graders only** | **No (private)** | Ten-item review table for expert sign-off |
| `control_selection.md` | Authors | **No (private)** | BDR control selection rules and identifiers |
| `version_manifest.json` | Authors | **No (private)** | Full freeze manifest (all artifact hashes, item-to-candidate mapping) |
| `../docs/release_manifest.json` | Public | Yes | Release metadata, environment, sources, commands, hashes of public inputs |

## Rebuild

```
python3 src/summarize.py        # candidates + private mapping (needs data/processed/benchmark_controls.csv for the controls)
python3 src/build_items.py      # validates specs; writes items.jsonl, items_review.md, grading/answer_key.jsonl, grading/grading_review.md
python3 src/freeze_manifest.py --check   # exit 1 if any frozen artifact changed
python3 -m unittest discover -s tests -v
```

The model-facing prompts are private because they contain real (pseudonymous)
NHANES case values; publishing them would expose the challenge set.

`build_items.py` stops with an error, writing nothing, if:
- a spec field is missing, malformed or unknown;
- an item ID or source candidate is duplicated;
- rubric totals differ between items;
- the case data disagree with `candidate_cases.csv`;
- a gold label disagrees with `src/bdr.py` recomputed from the case data;
- a formal label or control role in the expert clinical-interpretation fields
  disagrees with gold.

Output is deterministic: rebuilding gives byte-identical files.

## Separation of prompts and answers

Model prompts contain only:
- the case data, printed exactly as in the spec;
- rule definitions generated from `config.yaml`;
- a neutral question for the item's family;
- the response format.

Spec fields that state or imply the answer go only to the answer key. Model
runners must load items with `build_items.load_public_items()`. It refuses any
path under `grading/`, and any record that has fields beyond the public set.
Prompts do not show the item ID or the item's role.

Item families decide the rules, the question and the answer fields; every item
in a family gets identical text apart from the participant data:

| Family | Rules shown | Answer fields |
|---|---|---|
| `bdr` | GINA, ERS/ATS | overall and per-measurement BDR |
| `obstruction` | GINA, ERS/ATS, fixed ratio, GLI LLN | fixed-ratio and LLN classifications, overall BDR |
| `missing_bdr` | GINA, ERS/ATS, fixed ratio, GLI LLN | overall BDR, fixed-ratio and LLN classifications |
| `quality` | GINA, ERS/ATS, eligibility | overall and per-measurement BDR, eligibility |

`reference_components` and `reference_calculations` in the answer key are
derived by the pipeline (`src/bdr.py`) for graders. They are not expert gold.

## Composition

A purposively selected challenge set of ten items: eight targeted challenge
items and two BDR controls. It is not a representative sample; see
`docs/methodology.md` (Benchmark composition).

## Release protection

The private files above are gitignored, and
`tests/test_release_protection.py` fails if any of them is tracked or staged,
or if any publishable file contains gold or grading text or a candidate SEQN.
