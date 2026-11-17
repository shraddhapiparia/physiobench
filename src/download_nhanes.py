"""Download and verify NHANES 2011-2012 spirometry, demographics, and body measures.

Downloads SPX_G, DEMO_G, and BMX_G SAS transport (.xpt) files from the CDC into
data/raw/, then checks that each file loads, that SEQN is unique, that the
variables identified in the codebook audit are present, and reports missingness.

This script does not merge, filter, or derive anything.

Codebooks:
  https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/SPX_G.htm
  https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/DEMO_G.htm
  https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/BMX_G.htm

Usage:
  python src/download_nhanes.py            # download missing files, then verify
  python src/download_nhanes.py --force    # re-download everything
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"

# Current CDC path first; legacy path as fallback.
URL_TEMPLATES = (
    "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/{name}.xpt",
    "https://wwwn.cdc.gov/Nchs/Nhanes/2011-2012/{name}.XPT",
)

# Every SAS transport file begins with this library header record.
XPT_MAGIC = b"HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!"

USER_AGENT = "physiobench-nhanes-downloader/0.1"
TIMEOUT_S = 120

# Expected values come from the codebook audit (Task 1). None = not stated
# in the codebook page, so it is reported but not checked.
DATASETS: dict[str, dict] = {
    "SPX_G": {
        "expected_rows": 7495,
        "variables": {
            # name: expected non-missing count from codebook frequency table
            "SEQN": 7495,
            "SPXNSTAT": 7495,
            "SPXNCMT": 532,
            "SPXNFEV1": 6652,
            "SPXNFVC": 6652,
            "SPXNQFV1": 6696,
            "SPXNQFVC": 6696,
            "SPXNQEFF": 6686,
            "SPDNACC": 6696,
            "SPDBRONC": 6695,
            "SPXBSTAT": 842,
            "SPXBCMT": 204,
            "SPXBFEV1": 457,
            "SPXBFVC": 457,
            "SPXBQFV1": 457,
            "SPXBQFVC": 457,
            "SPXBQEFF": 457,
            "SPDBACC": 457,
        },
        # Coded variables: expected {code: count} from the codebook.
        "value_counts": {
            "SPXNSTAT": {1: 6344, 2: 351, 3: 437, 4: 363},
            "SPDBRONC": {1: 842, 2: 5853},
            "SPXBSTAT": {1: 456, 2: 1, 3: 218, 4: 167},
            "SPXNQFV1": {"A": 4267, "B": 1618, "C": 547, "D": 216, "F": 48},
            "SPXNQFVC": {"A": 4104, "B": 1562, "C": 718, "D": 249, "F": 63},
            "SPXBQFV1": {"A": 334, "B": 90, "C": 33},
            "SPXBQFVC": {"A": 321, "B": 107, "C": 28, "D": 1},
        },
    },
    "DEMO_G": {
        "expected_rows": 9756,
        "variables": {
            "SEQN": 9756,
            "RIDSTATR": 9756,
            "RIAGENDR": 9756,
            "RIDAGEYR": 9756,
            "RIDEXAGY": None,
            "RIDRETH1": 9756,
            "RIDRETH3": 9756,
            "RIDEXPRG": 1208,
            "WTMEC2YR": None,
        },
        "value_counts": {
            "RIAGENDR": {1: 4856, 2: 4900},
            "RIDRETH1": {1: 1355, 2: 1076, 3: 2973, 4: 2683, 5: 1669},
            "RIDRETH3": {1: 1355, 2: 1076, 3: 2973, 4: 2683, 6: 1282, 7: 387},
            "RIDEXPRG": {1: 57, 2: 1066, 3: 85},
            "RIDSTATR": {1: 418, 2: 9338},
        },
    },
    "BMX_G": {
        # The BMX_G codebook page publishes no frequency tables.
        "expected_rows": None,
        "variables": {
            "SEQN": None,
            "BMDSTATS": None,
            "BMXHT": None,
            "BMIHT": None,
        },
        "value_counts": {},
    },
}


class DownloadError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def is_valid_xpt(path: Path) -> bool:
    """True if the file exists, is non-empty, and has a SAS XPORT header."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as fh:
        return fh.read(len(XPT_MAGIC)) == XPT_MAGIC


def fetch(url: str, dest: Path) -> None:
    """Stream url to dest via a temporary file; raise DownloadError on failure."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"HTTP {e.code} {e.reason} for {url}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"Network error for {url}: {e}") from e

    if not is_valid_xpt(tmp):
        # CDC returns an HTML error page with HTTP 200 for unknown files.
        head = tmp.read_bytes()[:80]
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"{url} did not return a SAS XPT file (starts with {head!r})")
    tmp.replace(dest)


def download(name: str, force: bool) -> Path:
    dest = RAW_DIR / f"{name}.xpt"
    if not force and is_valid_xpt(dest):
        print(f"[skip] {dest.relative_to(REPO_ROOT)} already present ({dest.stat().st_size:,} bytes)")
        return dest

    errors = []
    for template in URL_TEMPLATES:
        url = template.format(name=name)
        print(f"[get ] {url}")
        try:
            fetch(url, dest)
        except DownloadError as e:
            print(f"       failed: {e}")
            errors.append(str(e))
            continue
        print(f"       saved {dest.relative_to(REPO_ROOT)} ({dest.stat().st_size:,} bytes)")
        return dest
    raise DownloadError(f"Could not download {name}:\n  " + "\n  ".join(errors))


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def load_xpt(path: Path) -> pd.DataFrame:
    df = pd.read_sas(path, format="xport", encoding="utf-8")
    # pandas decodes SAS XPT zeros as ~5.4e-79; restore them to exact 0.
    num_cols = df.select_dtypes(include="number").columns
    df[num_cols] = df[num_cols].mask(df[num_cols].abs() < 1e-70, 0.0)
    # Character variables use "" for missing; make that NaN so missingness is honest.
    obj_cols = df.select_dtypes(include="object").columns
    for col in obj_cols:
        df[col] = df[col].replace("", pd.NA).str.strip().replace("", pd.NA)
    return df


def normalise_code(value):
    """Turn 1.0 into 1 so numeric codes compare equal to the codebook's ints."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def verify(name: str, path: Path, spec: dict) -> list[str]:
    """Print a verification report for one dataset; return discrepancy messages."""
    issues: list[str] = []
    print(f"\n=== {name} ({path.relative_to(REPO_ROOT)}) ===")

    try:
        df = load_xpt(path)
    except Exception as e:  # noqa: BLE001 - surface any reader failure clearly
        msg = f"{name}: pandas.read_sas failed: {e}"
        print(f"ERROR {msg}")
        return [msg]

    n_rows, n_cols = df.shape
    print(f"rows={n_rows:,}  columns={n_cols}")
    if spec["expected_rows"] is not None and n_rows != spec["expected_rows"]:
        issues.append(f"{name}: {n_rows} rows, codebook says {spec['expected_rows']}")

    if "SEQN" not in df.columns:
        issues.append(f"{name}: SEQN column missing")
    else:
        n_dup = int(df["SEQN"].duplicated().sum())
        n_na = int(df["SEQN"].isna().sum())
        print(f"SEQN unique={n_dup == 0 and n_na == 0}  duplicates={n_dup}  missing={n_na}")
        if n_dup or n_na:
            issues.append(f"{name}: SEQN has {n_dup} duplicates and {n_na} missing")

    expected_vars = spec["variables"]
    absent = [v for v in expected_vars if v not in df.columns]
    if absent:
        issues.append(f"{name}: expected variables absent: {absent}")
    extra = [c for c in df.columns if c not in expected_vars]
    print(f"expected variables present: {len(expected_vars) - len(absent)}/{len(expected_vars)}"
          + (f"  ABSENT: {absent}" if absent else ""))
    print(f"other columns in file ({len(extra)}): {', '.join(extra)}")

    print(f"\n{'variable':<10} {'dtype':<8} {'non-miss':>9} {'missing':>8} {'%miss':>6}  {'codebook':>8}")
    for var, expected_n in expected_vars.items():
        if var not in df.columns:
            continue
        s = df[var]
        n_ok = int(s.notna().sum())
        n_miss = n_rows - n_ok
        flag = ""
        if expected_n is not None and n_ok != expected_n:
            flag = "  <-- MISMATCH"
            issues.append(f"{name}.{var}: {n_ok} non-missing, codebook says {expected_n}")
        exp = "-" if expected_n is None else str(expected_n)
        print(f"{var:<10} {str(s.dtype):<8} {n_ok:>9,} {n_miss:>8,} {100 * n_miss / n_rows:>5.1f}%  {exp:>8}{flag}")

    for var, expected_counts in spec["value_counts"].items():
        if var not in df.columns:
            continue
        observed = {normalise_code(k): int(v) for k, v in df[var].value_counts(dropna=True).items()}
        ok = all(observed.get(k, 0) == v for k, v in expected_counts.items()) and \
            set(observed) <= set(expected_counts)
        print(f"\n{var} codes: {dict(sorted(observed.items(), key=lambda kv: str(kv[0])))}"
              + ("" if ok else f"\n  codebook: {expected_counts}  <-- MISMATCH"))
        if not ok:
            issues.append(f"{name}.{var}: code counts {observed} != codebook {expected_counts}")

    # Continuous ranges for the measurements we care about (sanity only).
    for var in ("SPXNFEV1", "SPXNFVC", "SPXBFEV1", "SPXBFVC", "RIDAGEYR", "BMXHT"):
        if var in df.columns and df[var].notna().any():
            print(f"{var} range: {df[var].min():g} to {df[var].max():g}")

    return issues


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--force", action="store_true", help="re-download even if valid files exist")
    args = parser.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    failed: list[str] = []
    for name in DATASETS:
        try:
            paths[name] = download(name, args.force)
        except DownloadError as e:
            print(f"ERROR {e}", file=sys.stderr)
            failed.append(name)

    issues: list[str] = []
    for name, path in paths.items():
        issues += verify(name, path, DATASETS[name])

    print("\n=== Summary ===")
    if failed:
        print(f"Download failed: {', '.join(failed)}")
    if issues:
        print(f"{len(issues)} discrepancy(ies) with the codebook:")
        for msg in issues:
            print(f"  - {msg}")
    if not failed and not issues:
        print("All files downloaded and match the codebook checks.")
    # Codebook discrepancies are failures too: a revised or corrupted CDC file
    # must not pass silently into data preparation.
    return 1 if (failed or issues) else 0


if __name__ == "__main__":
    sys.exit(main())
