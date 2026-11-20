"""Tests for src/summarize.py. Expected values are worked out by hand."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import summarize as sm  # noqa: E402

NA = pd.NA


def b(*vals):
    return pd.Series(list(vals), dtype="boolean")


class TestContingencyAndKappa(unittest.TestCase):
    def test_cells_sum_to_denominator_and_marginals(self):
        # x: T T F F T NA ; y: T F T F NA F  -> classified rows 0-3 only
        t = sm.contingency(b(True, True, False, False, True, NA), b(True, False, True, False, NA, False))
        self.assertEqual((t["n_both_pos"], t["n_first_only"], t["n_second_only"], t["n_both_neg"]), (1, 1, 1, 1))
        self.assertEqual(t["n_classified"], 4)
        self.assertEqual(t["n_missing_classification"], 2)
        self.assertEqual(t["n_first_pos"], 2)       # x True among classified rows
        self.assertEqual(t["n_second_pos"], 2)
        self.assertEqual(sum(t[k] for k in ("n_both_pos", "n_first_only", "n_second_only", "n_both_neg")),
                         t["n_classified"])

    def test_missing_not_counted_as_negative(self):
        # Two NA rows must not enter the both-negative cell.
        t = sm.contingency(b(True, NA, NA), b(True, False, NA))
        self.assertEqual(t["n_both_neg"], 0)
        self.assertEqual(t["n_classified"], 1)
        self.assertEqual(t["n_missing_classification"], 2)

    def test_kappa_hand_calculated(self):
        # a=20 b=5 c=10 d=15, n=50: po=0.70; pe=(25*30 + 25*20)/2500 = 0.50; kappa=0.40
        self.assertAlmostEqual(sm.cohens_kappa(20, 5, 10, 15), 0.40, places=12)
        # a=45 b=12 c=8 d=210, n=275: po=255/275; pe=(57*53 + 218*222)/275^2
        po, pe = 255 / 275, (57 * 53 + 218 * 222) / 275 ** 2
        self.assertAlmostEqual(sm.cohens_kappa(45, 12, 8, 210), (po - pe) / (1 - pe), places=12)
        self.assertAlmostEqual(sm.cohens_kappa(10, 0, 0, 10), 1.0)
        self.assertTrue(np.isnan(sm.cohens_kappa(10, 0, 0, 0)))   # pe = 1: undefined
        self.assertTrue(np.isnan(sm.cohens_kappa(0, 0, 0, 0)))


def frame(rows):
    base = dict(is_adult=True, RIDAGEYR=45, SPXNFEV1=2500.0, SPXNFVC=3000.0, SPXBFEV1=2600.0, SPXBFVC=3000.0,
                gli_fev1_pred=3.0, gli_fvc_pred=4.0, gli_fev1fvc_lln=0.7,
                SPXNQFV1="A", SPXNQFVC="A", SPXBQFV1="A", SPXBQFVC="A", height_not_straight=False)
    d = pd.DataFrame([{**base, **r} for r in rows])
    d["is_adult"] = d["is_adult"].astype("boolean")
    return d


class TestSubsets(unittest.TestCase):
    def setUp(self):
        self.d = frame([
            {},                                    # 0 adult, all A -> strict and expanded
            {"is_adult": False, "RIDAGEYR": 12},   # 1 child -> never
            {"SPXBFEV1": np.nan},                  # 2 no post FEV1 -> not paired
            {"SPXNFVC": 0.0},                      # 3 invalid volume -> not paired
            {"gli_fvc_pred": np.nan},              # 4 no prediction
            {"SPXBQFVC": "C"},                     # 5 grade C -> expanded only
            {"SPXNQFV1": "D"},                     # 6 grade D -> neither
            {"RIDAGEYR": 39}, {"RIDAGEYR": 40}, {"RIDAGEYR": 59}, {"RIDAGEYR": 60},   # 7-10
        ])

    def test_bdr_populations(self):
        ab = sm.bdr_population(self.d, sm.GRADES_AB)
        abc = sm.bdr_population(self.d, sm.GRADES_ABC)
        self.assertEqual(list(np.where(ab["final"])[0]), [0, 7, 8, 9, 10])
        self.assertEqual(list(np.where(abc["final"])[0]), [0, 5, 7, 8, 9, 10])
        self.assertEqual(list(np.where(~ab["paired"] & ab["adults"])[0]), [2, 3])
        self.assertEqual(list(np.where(ab["paired"] & ~ab["pred"])[0]), [4])

    def test_obstruction_populations(self):
        d = self.d.copy()
        d.loc[4, "gli_fev1fvc_lln"] = np.nan
        broad = sm.obstruction_population(d, None)["final"]
        strict = sm.obstruction_population(d, sm.GRADES_AB)["final"]
        # Post-BD data are irrelevant for obstruction: row 2 (no post FEV1) is included.
        self.assertEqual(list(np.where(broad)[0]), [0, 2, 5, 6, 7, 8, 9, 10])
        self.assertEqual(list(np.where(strict)[0]), [0, 2, 5, 7, 8, 9, 10])   # 6 has pre grade D

    def test_age_bands_inclusive(self):
        self.assertEqual(list(np.where(sm.age_band(self.d, 18, 39))[0]), [7])
        self.assertEqual(list(np.where(sm.age_band(self.d, 40, 59))[0]), [0, 2, 3, 4, 5, 6, 8, 9])
        self.assertEqual(list(np.where(sm.age_band(self.d, 60, 200))[0]), [10])

    def test_sensitivity_row_counts(self):
        d = self.d.assign(gina_bdr=b(*([True] * 11)), ats_ers_bdr=b(*([False] * 11)))
        r = sm.sensitivity_row("bdr", "strict_AB", sm.bdr_population(d, sm.GRADES_AB),
                               pd.Series(True, index=d.index), d["gina_bdr"], d["ats_ers_bdr"])
        self.assertEqual(r["n_adults_in_scope"], 10)
        self.assertEqual(r["n_missing_or_invalid_measurements"], 2)
        self.assertEqual(r["n_missing_or_invalid_prediction"], 1)
        self.assertEqual(r["n_failed_quality_rule"], 2)
        self.assertEqual(r["n_included"], 5)
        self.assertEqual(r["n_first_only"], 5)


class TestCandidateIds(unittest.TestCase):
    def sel(self, seqns):
        return pd.DataFrame({"SEQN": seqns, "selection_category": "x", "selection_reason": "y"})

    def test_ids_deterministic(self):
        a, ma = sm.assign_ids(self.sel([300, 100, 200]), None)
        b_, mb = sm.assign_ids(self.sel([300, 100, 200]), None)
        self.assertEqual(a["case_id"].tolist(), ["PB001", "PB002", "PB003"])
        pd.testing.assert_frame_equal(a, b_)
        pd.testing.assert_frame_equal(ma, mb)

    def test_ids_stable_with_existing_mapping(self):
        _, m1 = sm.assign_ids(self.sel([300, 100, 200]), None)
        # Re-selection in a different order, one participant dropped, one new.
        out, m2 = sm.assign_ids(self.sel([200, 400, 300]), m1)
        self.assertEqual(dict(zip(out["SEQN"], out["case_id"])), {200: "PB003", 400: "PB004", 300: "PB001"})
        # Dropped participant keeps PB002 in the mapping; the ID is not reused.
        self.assertEqual(m2.set_index("SEQN").loc[100, "case_id"], "PB002")
        self.assertFalse(m2.set_index("SEQN").loc[100, "currently_selected"])
        self.assertTrue(m2["case_id"].is_unique and m2["SEQN"].is_unique)


class TestControls(unittest.TestCase):
    """Synthetic participants only; real control SEQNs live in the private registry."""

    def setUp(self):
        fp = dict(RIDAGEYR=40.0, RIAGENDR=1.0, BMXHT=175.0, SPXNFEV1=3000.0, SPXNFVC=4000.0,
                  SPXBFEV1=3500.0, SPXBFVC=4000.0)
        self.d = pd.DataFrame([
            {"SEQN": 1, **fp, "primary_bdr_eligible": True, "gina_bdr_status": "positive", "ats_ers_bdr_status": "positive"},
            {"SEQN": 2, **fp, "primary_bdr_eligible": True, "gina_bdr_status": "negative", "ats_ers_bdr_status": "negative"},
            {"SEQN": 3, **fp, "primary_bdr_eligible": True, "gina_bdr_status": "positive", "ats_ers_bdr_status": "negative"},
            {"SEQN": 4, **fp, "primary_bdr_eligible": False, "gina_bdr_status": "positive", "ats_ers_bdr_status": "positive"},
        ])
        self.d["primary_bdr_eligible"] = self.d["primary_bdr_eligible"].astype("boolean")
        self.fp = fp
        self.selected = pd.DataFrame({"SEQN": [3], "selection_category": ["x"], "selection_reason": ["y"]})

    def reg(self, *entries):
        return pd.DataFrame([{"control_label": f"K{i}", **self.fp, **e} for i, e in enumerate(entries)])

    def test_controls_appended_in_registry_order_with_next_ids(self):
        reg = self.reg({"SEQN": 2, "selection_category": "concordant_negative_control"},
                       {"SEQN": 1, "selection_category": "concordant_positive_control"})
        out = sm.add_controls(self.d, self.selected, reg)
        self.assertEqual(out["SEQN"].tolist(), [3, 2, 1])
        _, m1 = sm.assign_ids(self.selected, None)                 # existing mapping: PB001 only
        ided, m2 = sm.assign_ids(out, m1)
        self.assertEqual(ided["case_id"].tolist(), ["PB001", "PB002", "PB003"])
        self.assertEqual(ided.iloc[1]["selection_category"], "concordant_negative_control")

    def test_no_registry_changes_nothing(self):
        pd.testing.assert_frame_equal(sm.add_controls(self.d, self.selected, None), self.selected)

    def test_rejects_wrong_label_ineligible_duplicate_and_fingerprint(self):
        cases = [({"SEQN": 1, "selection_category": "concordant_negative_control"}, "not a primary-eligible"),
                 ({"SEQN": 4, "selection_category": "concordant_positive_control"}, "not a primary-eligible"),
                 ({"SEQN": 3, "selection_category": "concordant_positive_control"}, "already selected"),
                 ({"SEQN": 9, "selection_category": "concordant_positive_control"}, "not in spirometry.csv"),
                 ({"SEQN": 1, "selection_category": "random_control"}, "unknown selection_category"),
                 ({"SEQN": 1, "selection_category": "concordant_positive_control", "BMXHT": 176.0},
                  "disagree with spirometry.csv for ['BMXHT']")]
        for entry, msg in cases:
            with self.assertRaises(ValueError) as cm:
                sm.add_controls(self.d, self.selected, self.reg(entry))
            self.assertIn(msg, str(cm.exception))


@unittest.skipUnless(sm.IN_PATH.is_file(), "data/processed/spirometry.csv not built")
class TestRealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        cls.paths = dict(summary_dir=t / "summary", candidates_path=t / "candidate_cases.csv",
                         mapping_path=t / "mapping.csv", cases_dir=t)
        cls.r1 = sm.run(verbose=False, **cls.paths)
        cls.files1 = {p: p.read_bytes() for p in t.rglob("*.csv")}
        cls.r2 = sm.run(verbose=False, **cls.paths)   # second run reuses the mapping
        cls.files2 = {p: p.read_bytes() for p in t.rglob("*.csv")}
        cls.d = sm.load()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_marginals_match_source(self):
        e = self.d[sm.T(self.d["primary_bdr_eligible"])]
        t = self.r1["t_bdr"]
        self.assertEqual(t["n_classified"], len(e))
        self.assertEqual(t["n_first_pos"], int(sm.T(e["gina_bdr"]).sum()))
        self.assertEqual(t["n_second_pos"], int(sm.T(e["ats_ers_bdr"]).sum()))

    def test_repeated_runs_identical(self):
        self.assertEqual(self.files1.keys(), self.files2.keys())
        for p in self.files1:
            self.assertEqual(self.files1[p], self.files2[p], p.name)

    def test_public_candidates_have_no_seqn(self):
        pub = pd.read_csv(self.paths["candidates_path"], dtype=str)
        mapping = pd.read_csv(self.paths["mapping_path"], dtype=str)
        self.assertFalse(any("SEQN" in c.upper() for c in pub.columns))
        self.assertFalse(pub.isin(set(mapping["SEQN"])).any().any())
        self.assertTrue(set(pub["case_id"]) <= set(mapping["case_id"]))
        self.assertTrue(pub["case_id"].is_unique)

    def test_input_not_modified(self):
        # run() asserts this internally; here just confirm it returned.
        self.assertIn("t_bdr", self.r1)


if __name__ == "__main__":
    unittest.main()
