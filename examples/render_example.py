"""Render and check the SYNTHETIC worked example (not part of the benchmark).

Uses only public code: the prompt is rendered with the same functions and
template as the benchmark's bronchodilator-response items (src/build_items.py),
and the reference answer is recomputed by src/bdr.py. The deterministic check
below is an ILLUSTRATION for this example only; it is not the benchmark's
grader (benchmark grading is not yet implemented in v0.1.0).

Usage:
  python3 examples/render_example.py            # print prompt, reference and demo check
  python3 examples/render_example.py --prompt   # print only the model-facing prompt
"""

from __future__ import annotations

import json
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
import bdr  # noqa: E402
import build_items as bi  # noqa: E402

EXAMPLE_PATH = HERE / "synthetic_spirometry_example.json"
FAMILY = "bdr"
# Public numerical tolerances (docs/methodology.md, Numerical grading policy).
TOLERANCES = {"change_mL": 1.0, "change_pct_of_baseline": 0.05, "change_pct_of_predicted": 0.05}
TRI = {True: "positive", False: "negative", None: "not_assessable"}

# Two invented, flawed responses used to contrast deterministic and explanation grading.
DEMO_RESPONSES = {
    "B: correct labels, coarse rounding, overclaim": {
        "classifications": {k: "positive" for k in ("gina_2026_fev1", "gina_2026_fvc", "gina_2026_overall",
                                                    "ers_ats_2022_fev1", "ers_ats_2022_fvc", "ers_ats_2022_overall")},
        "calculations": {"fev1_change_mL": 500, "fev1_change_pct_of_baseline": 24.5,
                         "fev1_change_pct_of_predicted": 17.9, "fvc_change_mL": 460,
                         "fvc_change_pct_of_baseline": 15, "fvc_change_pct_of_predicted": 13.6},
        "physiological_explanation": "Both FEV1 and FVC meet both GINA criteria and exceed 10% of predicted, "
                                     "so both guidelines are positive.",
        "limitations": "This confirms a diagnosis of asthma.",
    },
    "C: correct labels, wrong ERS/ATS denominator": {
        "classifications": {k: "positive" for k in ("gina_2026_fev1", "gina_2026_fvc", "gina_2026_overall",
                                                    "ers_ats_2022_fev1", "ers_ats_2022_fvc", "ers_ats_2022_overall")},
        "calculations": {"fev1_change_mL": 500, "fev1_change_pct_of_baseline": 24.51,
                         "fev1_change_pct_of_predicted": 24.51, "fvc_change_mL": 460,
                         "fvc_change_pct_of_baseline": 15.28, "fvc_change_pct_of_predicted": 15.28},
        "physiological_explanation": "ERS/ATS is positive because each change is more than 10% of the "
                                     "pre-bronchodilator value.",
        "limitations": "A single test; a positive response does not by itself establish asthma.",
    },
}


def load_example(path: Path = EXAMPLE_PATH) -> dict:
    return json.loads(Path(path).read_text())


def render_prompt(case: dict) -> str:
    tpl = string.Template(bi.TEMPLATE_PATH.read_text())
    return tpl.substitute(case_block=bi.render_case(case), rules_block=bi.render_rules(FAMILY, bdr.load_config()),
                          question=bi.render_question(FAMILY), response_format=bi.render_response(FAMILY))


def reference(case: dict) -> dict:
    """Reference classifications and calculations recomputed by src/bdr.py."""
    r = bi.recompute(case, bdr.load_config())
    labels = {"gina_2026_overall": r["labels"]["gina_bdr_status"],
              "ers_ats_2022_overall": r["labels"]["ers_ats_bdr_status"],
              **{k: TRI[None if v is None else bool(v)] for k, v in r["components"].items()}}
    order = bi.response_schema(FAMILY)
    return {"classifications": {k: labels[k] for k in order["classifications"]},
            "calculations": {k: r["calculations"][k] for k in order["calculations"]},
            "fev1fvc_pre_minus_lln": r["calculations"]["fev1fvc_pre_minus_lln"],
            "fev1fvc_pre_ratio": r["calculations"]["fev1fvc_pre_ratio"]}


def tolerance(name: str) -> float:
    return next(t for suffix, t in TOLERANCES.items() if name.endswith(suffix))


def deterministic_check(response: dict, ref: dict) -> dict:
    """Exact-match classifications and tolerance-checked calculations (illustration only)."""
    cls = {k: response["classifications"].get(k) == v for k, v in ref["classifications"].items()}
    calc = {}
    for k, v in ref["calculations"].items():
        got = response["calculations"].get(k)
        calc[k] = got is not None and abs(float(got) - v) <= tolerance(k)
    return {"classifications": cls, "calculations": calc}


def demo_table(ref: dict) -> str:
    rows = ["| Response | Classifications correct | Calculations within tolerance | Calculations outside tolerance |",
            "|---|---|---|---|"]
    responses = {"A: reference answer": load_example()["reference_answer"], **DEMO_RESPONSES}
    for name, resp in responses.items():
        r = deterministic_check(resp, ref)
        bad = [k for k, ok in r["calculations"].items() if not ok]
        rows.append(f"| {name} | {sum(r['classifications'].values())}/{len(r['classifications'])} | "
                    f"{sum(r['calculations'].values())}/{len(r['calculations'])} | "
                    f"{', '.join(f'`{b}`' for b in bad) or 'none'} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ex = load_example()
    prompt = render_prompt(ex["case_data"])
    if "--prompt" in argv:
        print(prompt, end="")
        return 0
    ref = reference(ex["case_data"])
    print(prompt)
    print(json.dumps(ref, indent=2))
    print()
    print(demo_table(ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
