"""Integration tests for src/gli_reference.R, run in temporary copies of the repo.

Skipped if Rscript, rspiro, or the processed intermediate dataset is unavailable.
The real repository files are only read, never written.
"""

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "src" / "gli_reference.R"
INTERMEDIATE = REPO / "data" / "processed" / "spirometry_intermediate.csv"
CASES = REPO / "data" / "reference" / "gli_global_validation_cases.csv"


def have_rspiro():
    if not shutil.which("Rscript"):
        return False
    r = subprocess.run(["Rscript", "-e", "quit(status = !requireNamespace('rspiro', quietly = TRUE))"],
                       capture_output=True)
    return r.returncode == 0


AVAILABLE = INTERMEDIATE.is_file() and have_rspiro()


def make_copy(root: Path, intermediate: pd.DataFrame = None, cases_text: str = None) -> Path:
    for sub in ("src", "data/processed", "data/reference"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, root / "src")
    if intermediate is None:
        shutil.copy(INTERMEDIATE, root / "data/processed")
    else:
        intermediate.to_csv(root / "data/processed/spirometry_intermediate.csv", index=False)
    (root / "data/reference/gli_global_validation_cases.csv").write_text(cases_text or CASES.read_text())
    return root


def run_from_elsewhere(root: Path):
    """Run the copied script with a working directory outside the copy."""
    with tempfile.TemporaryDirectory() as cwd:
        return subprocess.run(["Rscript", str(root / "src/gli_reference.R")], cwd=cwd,
                              capture_output=True, text=True)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@unittest.skipUnless(AVAILABLE, "Rscript/rspiro or processed data unavailable")
class TestGliReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = make_copy(Path(cls.tmp.name) / "base")
        cls.proc = run_from_elsewhere(cls.root)
        cls.out_path = cls.root / "data/processed/gli_reference.csv"
        cls.inter = pd.read_csv(INTERMEDIATE, keep_default_na=False, dtype=str)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_runs_outside_repo_root(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stdout[-2000:] + self.proc.stderr[-2000:])
        self.assertTrue(self.out_path.is_file())

    # Mismatches are counted rather than compared as long lists: unittest's
    # list diff is extremely slow for 7,495 elements.
    def test_rows_and_seqn_preserved(self):
        out = pd.read_csv(self.out_path)
        self.assertEqual(len(out), 7495)
        self.assertTrue(out["SEQN"].is_unique)
        seqn_in = pd.to_numeric(self.inter["SEQN"]).to_numpy()
        self.assertEqual(int((out["SEQN"].to_numpy() != seqn_in).sum()), 0)

    def test_quality_grades_preserved(self):
        out = pd.read_csv(self.out_path, keep_default_na=False, dtype=str)
        for col in ("SPXNQFV1", "SPXNQFVC"):  # grade letters, "" = missing
            self.assertEqual(int((out[col] != self.inter[col]).sum()), 0, col)
        # SPXNSTAT is numeric; Python writes 1.0, R writes 1.
        stat_out = pd.to_numeric(out["SPXNSTAT"]).to_numpy()
        stat_in = pd.to_numeric(self.inter["SPXNSTAT"]).to_numpy()
        self.assertEqual(int((stat_out != stat_in).sum()), 0, "SPXNSTAT")
        both = pd.read_csv(self.out_path)["fev1fvc_pre_grades_AB"]
        self.assertEqual(int((both == True).sum()), 5531)  # noqa: E712 - pandas object column

    def test_invalid_measurements_rejected_and_others_unchanged(self):
        base = pd.read_csv(self.out_path)
        inter = pd.read_csv(INTERMEDIATE)
        valid = base.index[base["gli_fev1fvc_z"].notna()][:3]
        inter.loc[valid[0], "fev1_pre_L"] = 0.0
        inter.loc[valid[1], "fev1_pre_L"] = -1.0
        inter.loc[valid[2], "fvc_pre_L"] = np.inf
        with tempfile.TemporaryDirectory() as d:
            root = make_copy(Path(d) / "bad", intermediate=inter)
            proc = run_from_elsewhere(root)
            self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
            out = pd.read_csv(root / "data/processed/gli_reference.csv")
        bad = out.loc[valid]
        self.assertTrue(bad["gli_fev1fvc_z"].isna().all())
        self.assertTrue((bad["gli_z_missing_reason"] == "invalid baseline FEV1/FVC (<=0 or non-finite)").all())
        self.assertTrue(np.isnan(out.loc[valid[0], "gli_fev1_z"]))         # FEV1 = 0
        self.assertTrue(np.isnan(out.loc[valid[1], "gli_fev1_z"]))         # FEV1 < 0
        self.assertTrue(np.isfinite(out.loc[valid[2], "gli_fev1_z"]))      # FEV1 still valid
        self.assertTrue(np.isnan(out.loc[valid[2], "gli_fvc_z"]))          # FVC = Inf
        self.assertTrue(bad["gli_fev1_pred"].notna().all())                # predictions kept
        rest = out.index.difference(valid)
        z_cols = [c for c in out.columns if c.startswith("gli_")]
        pd.testing.assert_frame_equal(out.loc[rest, z_cols], base.loc[rest, z_cols])

    def test_failed_validation_does_not_overwrite_output(self):
        lines = CASES.read_text().splitlines()
        i = next(k for k, l in enumerate(lines) if l.startswith("C1,gli_calculator,"))
        parts = lines[i].split(",")
        parts[7] = f"{float(parts[7]) + 0.1:.3f}"   # fev1_pred off by 0.1
        lines[i] = ",".join(parts)
        with tempfile.TemporaryDirectory() as d:
            root = make_copy(Path(d) / "fail", cases_text="\n".join(lines) + "\n")
            out = root / "data/processed/gli_reference.csv"
            out.write_text("sentinel\n")
            before = md5(out)
            proc = run_from_elsewhere(root)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(md5(out), before)


if __name__ == "__main__":
    unittest.main()
