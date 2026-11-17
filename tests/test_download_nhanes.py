"""Tests for src/download_nhanes.py (no network access)."""

import contextlib
import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import download_nhanes as dn  # noqa: E402

HAVE_RAW = all((dn.RAW_DIR / f"{n}.xpt").is_file() for n in dn.DATASETS)


def run_main_offline(datasets):
    """Run main() against local raw files, with download() never touching the network."""
    with mock.patch.object(dn, "DATASETS", datasets), \
         mock.patch.object(dn, "download", lambda name, force: dn.RAW_DIR / f"{name}.xpt"), \
         contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return dn.main([])


class TestXptValidation(unittest.TestCase):
    def test_html_error_page_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.xpt"
            p.write_bytes(b"<!doctype html><html>Page not found</html>")
            self.assertFalse(dn.is_valid_xpt(p))

    def test_empty_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.xpt"
            p.write_bytes(b"")
            self.assertFalse(dn.is_valid_xpt(p))


@unittest.skipUnless(HAVE_RAW, "raw XPT files not downloaded")
class TestExitStatus(unittest.TestCase):
    def test_clean_files_exit_zero(self):
        self.assertEqual(run_main_offline(dn.DATASETS), 0)

    def test_codebook_row_mismatch_exits_nonzero(self):
        ds = copy.deepcopy(dn.DATASETS)
        ds["SPX_G"]["expected_rows"] = 1
        self.assertEqual(run_main_offline(ds), 1)

    def test_codebook_code_count_mismatch_exits_nonzero(self):
        ds = copy.deepcopy(dn.DATASETS)
        ds["SPX_G"]["value_counts"]["SPDBRONC"] = {1: 843, 2: 5852}
        self.assertEqual(run_main_offline(ds), 1)

    def test_missing_expected_variable_exits_nonzero(self):
        ds = copy.deepcopy(dn.DATASETS)
        ds["BMX_G"]["variables"]["NOT_A_VARIABLE"] = None
        self.assertEqual(run_main_offline(ds), 1)


@unittest.skipUnless(HAVE_RAW, "raw XPT files not downloaded")
class TestNearZeroCorrection(unittest.TestCase):
    def test_only_true_zeros_are_restored(self):
        import pandas as pd
        path = dn.RAW_DIR / "DEMO_G.xpt"
        raw = pd.read_sas(path, format="xport", encoding="utf-8")
        fixed = dn.load_xpt(path)
        num = raw.select_dtypes("number").columns
        tiny = raw[num].abs() < 1e-70
        # Every changed cell was exactly 16**-65 (pandas' decoding of IBM zero) and is now 0.
        self.assertTrue((raw[num][tiny] == 16.0 ** -65).sum().sum() == tiny.sum().sum())
        self.assertTrue((fixed[num][tiny] == 0).sum().sum() == tiny.sum().sum())
        # Nothing else changed, including SEQN and missing values.
        pd.testing.assert_frame_equal(raw[num].mask(tiny), fixed[num].mask(tiny))
        self.assertTrue(raw["SEQN"].equals(fixed["SEQN"]))


if __name__ == "__main__":
    unittest.main()
