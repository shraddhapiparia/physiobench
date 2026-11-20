"""Tests for the SYNTHETIC worked example (examples/). Public; no private content.

The example must agree with the pipeline and its documentation, sit well away
from every threshold, and stay out of the benchmark. Checks against private
benchmark files and real participants run only when those files exist.
"""

import json
import shutil
import subprocess
import sys
import unittest
from fractions import Fraction as F
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "examples"))
import build_items as bi  # noqa: E402
import render_example as rx  # noqa: E402

EX = rx.load_example()
CASE = EX["case_data"]
README = (REPO / "examples" / "README.md").read_text()


class TestSyntheticExample(unittest.TestCase):
    def test_labelled_synthetic_and_excluded(self):
        self.assertIs(EX["synthetic"], True)
        self.assertIs(EX["excluded_from_benchmark"], True)
        self.assertIn("SYNTHETIC", EX["notice"])
        self.assertIn("Synthetic and illustrative only", README)
        self.assertNotIn("item_id", EX)
        self.assertNotIn("source_candidate_id", EX)

    def test_case_fields_match_benchmark_schema(self):
        self.assertEqual(set(CASE), set(bi.CASE_FIELDS))
        for f in ("fev1_pre_L", "fvc_pre_L", "fev1_post_L", "fvc_post_L"):
            bi.to_ml(CASE[f], f)                                   # whole mL
        self.assertLessEqual(abs(CASE["fev1fvc_pre_ratio"] - CASE["fev1_pre_L"] / CASE["fvc_pre_L"]), 1e-12)
        self.assertGreaterEqual(CASE["age_years"], 18)
        for g in ("SPXNQFV1", "SPXNQFVC", "SPXBQFV1", "SPXBQFVC"):
            self.assertIn(CASE[g], ("A", "B"))
        self.assertEqual(CASE["post_bd_exam_status"], "complete")

    def test_reference_answer_matches_pipeline(self):
        ref = rx.reference(CASE)
        self.assertEqual(EX["reference_answer"]["classifications"], ref["classifications"])
        self.assertEqual(EX["reference_answer"]["calculations"], ref["calculations"])
        self.assertEqual(CASE["fev1fvc_pre_ratio"], ref["fev1fvc_pre_ratio"])
        self.assertEqual(EX["reference_details"]["fev1fvc_pre_minus_lln"], ref["fev1fvc_pre_minus_lln"])
        schema = bi.response_schema(rx.FAMILY)
        self.assertEqual(list(EX["reference_answer"]["classifications"]), list(schema["classifications"]))
        self.assertEqual(list(EX["reference_answer"]["calculations"]), schema["calculations"])

    def test_independent_exact_arithmetic(self):
        calc = EX["reference_answer"]["calculations"]
        for m, pred in (("fev1", "gli_fev1_pred"), ("fvc", "gli_fvc_pred")):
            pre, post = round(CASE[f"{m}_pre_L"] * 1000), round(CASE[f"{m}_post_L"] * 1000)
            d = post - pre
            pb, pp = F(100 * d, pre), 100 * F(d) / (1000 * F(repr(CASE[pred])))
            self.assertEqual(calc[f"{m}_change_mL"], d)
            self.assertAlmostEqual(calc[f"{m}_change_pct_of_baseline"], float(pb), places=12)
            self.assertAlmostEqual(calc[f"{m}_change_pct_of_predicted"], float(pp), places=12)
            gina, ers = (pb >= 12 and d >= 200), pp > 10
            self.assertEqual(EX["reference_answer"]["classifications"][f"gina_2026_{m}"], "positive" if gina else "negative")
            self.assertEqual(EX["reference_answer"]["classifications"][f"ers_ats_2022_{m}"], "positive" if ers else "negative")
            mg = EX["reference_details"]["margins"]
            self.assertAlmostEqual(mg[f"{m}_pct_baseline_minus_12"], float(pb - 12), places=12)
            self.assertAlmostEqual(mg[f"{m}_pct_predicted_minus_10"], float(pp - 10), places=12)
            self.assertEqual(mg[f"{m}_mL_minus_200"], d - 200)

    def test_comfortably_away_from_every_threshold(self):
        mg = EX["reference_details"]["margins"]
        for k, v in mg.items():
            self.assertGreaterEqual(abs(v), 100 if k.endswith("mL_minus_200") else 3.0, k)
        ratio, lln = CASE["fev1fvc_pre_ratio"], CASE["gli_fev1fvc_lln"]
        self.assertGreaterEqual(abs(ratio - 0.70), 0.02)
        self.assertGreaterEqual(abs(ratio - lln), 0.02)

    @unittest.skipUnless(shutil.which("Rscript"), "R not available")
    def test_gli_values_reproduced_by_rspiro(self):
        code = ('suppressPackageStartupMessages(library(rspiro)); a<-44; h<-1.63; s<-2; '
                'cat(format(c(pred_GLIgl(a,h,s,param="FEV1"), pred_GLIgl(a,h,s,param="FVC"), '
                'LLN_GLIgl(a,h,s,param="FEV1FVC")), digits=15), sep="\\n")')
        r = subprocess.run(["Rscript", "-e", code], capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("rspiro not installed")
        self.assertEqual((CASE["age_years"], CASE["sex"], CASE["height_cm"]), (44.0, "female", 163.0))
        # The pipeline stores GLI values at 15 significant digits (R write.csv default).
        got = [float(f"{float(x):.15g}") for x in r.stdout.split()]
        self.assertEqual(got, [CASE["gli_fev1_pred"], CASE["gli_fvc_pred"], CASE["gli_fev1fvc_lln"]])

    def test_readme_matches_code(self):
        ref = rx.reference(CASE)
        self.assertIn(rx.render_prompt(CASE).rstrip("\n"), README)
        self.assertIn(json.dumps(EX["reference_answer"], indent=2, ensure_ascii=False), README)
        self.assertIn(rx.demo_table(ref), README)

    def test_prompt_uses_benchmark_format(self):
        p = rx.render_prompt(CASE)
        self.assertIn(bi.render_rules(rx.FAMILY, rx.bdr.load_config()), p)
        self.assertIn(bi.render_question(rx.FAMILY), p)
        self.assertIn(bi.render_response(rx.FAMILY), p)
        for w in ("synthetic", "example", "control", "expected"):
            self.assertNotIn(w, p.lower())

    def test_demo_contrasts_deterministic_and_explanation_grading(self):
        ref = rx.reference(CASE)
        b, c = (rx.deterministic_check(r, ref) for r in rx.DEMO_RESPONSES.values())
        self.assertTrue(all(b["classifications"].values()) and all(c["classifications"].values()))
        self.assertEqual([k for k, ok in b["calculations"].items() if not ok], ["fvc_change_pct_of_baseline"])
        self.assertEqual([k for k, ok in c["calculations"].items() if not ok],
                         ["fev1_change_pct_of_predicted", "fvc_change_pct_of_predicted"])


SPEC = REPO / "benchmark" / "item_specs.yaml"
ITEMS = REPO / "benchmark" / "items.jsonl"
SPIRO = REPO / "data" / "processed" / "spirometry.csv"


class TestExampleNotFromBenchmarkOrCohort(unittest.TestCase):
    """Private-data checks; skipped in a public checkout."""

    @unittest.skipUnless(SPEC.is_file() and ITEMS.is_file(), "private benchmark files not available")
    def test_not_in_benchmark(self):
        spec = bi.load_yaml(SPEC)
        keys = ("age_years", "sex", "height_cm", "fev1_pre_L", "fvc_pre_L", "fev1_post_L", "fvc_post_L")
        for it in spec["items"]:
            c = it["case_data"]
            shared = [k for k in keys if c[k] == CASE[k] and k != "sex"]
            self.assertEqual(shared, [], f"example shares {shared} with a held-out item")
        text = ITEMS.read_text()
        for f in ("gli_fev1_pred", "gli_fvc_pred", "gli_fev1fvc_lln", "fev1fvc_pre_ratio"):
            self.assertNotIn(repr(CASE[f]), text)
        self.assertNotIn(EX["example_id"], text)
        key = REPO / "grading" / "answer_key.jsonl"
        if key.is_file():
            self.assertNotIn(EX["example_id"], key.read_text())

    @unittest.skipUnless(SPIRO.is_file(), "processed NHANES data not available")
    def test_not_a_real_participant(self):
        import pandas as pd
        d = pd.read_csv(SPIRO, usecols=["RIDAGEYR", "RIAGENDR", "BMXHT", "SPXNFEV1", "SPXNFVC", "SPXBFEV1", "SPXBFVC"])
        vol = {"SPXNFEV1": CASE["fev1_pre_L"], "SPXNFVC": CASE["fvc_pre_L"],
               "SPXBFEV1": CASE["fev1_post_L"], "SPXBFVC": CASE["fvc_post_L"]}
        near = pd.Series(True, index=d.index)
        for col, litres in vol.items():
            near &= (d[col] - litres * 1000).abs() <= 30
        self.assertEqual(int(near.sum()), 0, "a real participant is within 30 mL on all four volumes")
        same = (d.RIDAGEYR == CASE["age_years"]) & (d.RIAGENDR == 2) & (d.BMXHT == CASE["height_cm"])
        self.assertEqual(int(same.sum()), 0)


if __name__ == "__main__":
    unittest.main()
