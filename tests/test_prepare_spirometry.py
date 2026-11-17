"""Tests for derived flags in src/prepare_spirometry.py (synthetic data)."""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from prepare_spirometry import add_derived  # noqa: E402

NA = np.nan


def synthetic():
    # One row per scenario. Columns are those add_derived() reads.
    rows = {
        #                  SPDBRONC SPXNSTAT FEV1   FVC    gradeV1 gradeVC SPXBSTAT postFEV1
        "selected_done":   (1,      1,       2000., 3000., "A",    "A",    1,       2100.),
        "not_selected":    (2,      1,       3000., 3600., "B",    "A",    NA,      NA),
        "partial_no_vals": (2,      2,       NA,    NA,    "F",    "F",    NA,      NA),
        "not_evaluated":   (NA,     3,       NA,    NA,    None,   None,   NA,      NA),
        "excluded_vals":   (NA,     4,       2840., 3343., "D",    "D",    NA,      NA),
        "selected_safety": (1,      1,       1500., 2600., "C",    "B",    4,       NA),
    }
    df = pd.DataFrame.from_dict(rows, orient="index", columns=[
        "SPDBRONC", "SPXNSTAT", "SPXNFEV1", "SPXNFVC", "SPXNQFV1", "SPXNQFVC", "SPXBSTAT", "SPXBFEV1"])
    df["SPXBFVC"] = df["SPXBFEV1"] * 1.3
    df["SPXBQFV1"] = np.where(df["SPXBFEV1"].notna(), "A", None)
    df["SPXBQFVC"] = df["SPXBQFV1"]
    df["RIDAGEYR"] = 40.0
    df["BMXHT"] = 170.0
    df["BMIHT"] = NA
    return add_derived(df)


class TestStatusLabels(unittest.TestCase):
    def setUp(self):
        self.d = synthetic()

    def test_bd_selection_status(self):
        self.assertEqual(self.d["bd_selection_status"].to_dict(), {
            "selected_done": "selected",
            "not_selected": "not_selected",
            "partial_no_vals": "not_selected_no_baseline_values",
            "not_evaluated": "not_evaluated",
            "excluded_vals": "not_evaluated",
            "selected_safety": "selected",
        })

    def test_post_bd_exam_status(self):
        s = self.d["post_bd_exam_status"]
        self.assertEqual(s["selected_done"], "complete")
        self.assertEqual(s["selected_safety"], "safety_exclusion")
        self.assertEqual(s["not_selected"], "not_applicable")

    def test_missing_is_never_false(self):
        # Missing source codes give <NA>, not False.
        self.assertTrue(pd.isna(self.d.loc["not_evaluated", "bd_selected"]))
        self.assertTrue(pd.isna(self.d.loc["not_evaluated", "fev1_pre_grade_AB"]))
        self.assertTrue(pd.isna(self.d.loc["not_selected", "bd_completed"]))
        # CDC's recorded code is preserved for the 44-type case.
        self.assertEqual(self.d.loc["partial_no_vals", "SPDBRONC"], 2)
        self.assertFalse(self.d.loc["partial_no_vals", "has_fev1_pre"])

    def test_anomaly_flags(self):
        self.assertTrue(self.d.loc["partial_no_vals", "pre_partial_no_values"])
        self.assertTrue(self.d.loc["excluded_vals", "pre_excluded_with_values"])
        self.assertEqual(self.d.loc["excluded_vals", "SPXNSTAT"], 4)

    def test_unit_conversion_keeps_originals(self):
        self.assertAlmostEqual(self.d.loc["not_selected", "fev1_pre_L"], 3.0)
        self.assertEqual(self.d.loc["not_selected", "SPXNFEV1"], 3000.0)
        self.assertAlmostEqual(self.d.loc["not_selected", "height_m"], 1.70)


if __name__ == "__main__":
    unittest.main()
