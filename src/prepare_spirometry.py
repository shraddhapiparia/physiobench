"""Initial merge and QC flagging of NHANES 2011-2012 spirometry data.

Reads SPX_G (base), DEMO_G, and BMX_G from data/raw/, left-joins on SEQN,
converts units, adds availability / quality flags, prints a QC report, and
writes data/processed/spirometry_intermediate.csv.

No rows are dropped, nothing is imputed, and no reference equations, BDR, or
obstruction classifications are computed here.

Run `python src/download_nhanes.py` first.
"""

from __future__ import annotations

import sys

import pandas as pd

from download_nhanes import RAW_DIR, REPO_ROOT, load_xpt

OUT_PATH = REPO_ROOT / "data" / "processed" / "spirometry_intermediate.csv"
N_SPX = 7495  # SPX_G codebook row count

SPX_COLS = [
    "SEQN",
    # Baseline (pre-bronchodilator) 1st test
    "SPXNSTAT", "SPXNCMT", "SPXNFEV1", "SPXNFVC",
    "SPXNQFV1", "SPXNQFVC", "SPXNQEFF", "SPDNACC",
    # Bronchodilator selection and 2nd test
    "SPDBRONC", "SPXBSTAT", "SPXBCMT", "SPXBFEV1", "SPXBFVC",
    "SPXBQFV1", "SPXBQFVC", "SPXBQEFF", "SPDBACC",
]
DEMO_COLS = [
    "SEQN", "RIDSTATR", "RIAGENDR", "RIDAGEYR", "RIDEXAGY",
    "RIDRETH1", "RIDRETH3", "RIDEXPRG", "WTMEC2YR", "SDMVPSU", "SDMVSTRA",
]
BMX_COLS = ["SEQN", "BMDSTATS", "BMXHT", "BMIHT"]

GOOD_GRADES = ["A", "B"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def flag(condition: pd.Series, source: pd.Series) -> pd.Series:
    """Nullable boolean: condition where source is observed, <NA> where it is missing."""
    return condition.astype("boolean").mask(source.isna())


def pct(n: int, d: int) -> str:
    return f"{n:,}/{d:,} ({100 * n / d:.1f}%)" if d else f"{n}/0"


# --------------------------------------------------------------------------- #
# Load and merge
# --------------------------------------------------------------------------- #
def load_and_merge() -> pd.DataFrame:
    spx = load_xpt(RAW_DIR / "SPX_G.xpt")[SPX_COLS]
    demo = load_xpt(RAW_DIR / "DEMO_G.xpt")[DEMO_COLS]
    bmx = load_xpt(RAW_DIR / "BMX_G.xpt")[BMX_COLS]

    for name, df in [("SPX_G", spx), ("DEMO_G", demo), ("BMX_G", bmx)]:
        assert df["SEQN"].is_unique, f"{name}: SEQN not unique"
        assert df["SEQN"].notna().all(), f"{name}: SEQN has missing values"
    assert len(spx) == N_SPX, f"SPX_G has {len(spx)} rows, expected {N_SPX}"

    df = spx.merge(demo, on="SEQN", how="left", validate="one_to_one", indicator="_demo")
    df = df.merge(bmx, on="SEQN", how="left", validate="one_to_one", indicator="_bmx")

    assert len(df) == N_SPX, "merge changed the number of spirometry rows"
    assert df["SEQN"].is_unique, "merge duplicated SEQN"

    df["in_demo"] = df.pop("_demo").eq("both")
    df["in_bmx"] = df.pop("_bmx").eq("both")
    df["SEQN"] = df["SEQN"].astype("int64")
    return df


# --------------------------------------------------------------------------- #
# Derived columns (originals are kept untouched)
# --------------------------------------------------------------------------- #
def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    # Age at screening; 80 = top-coded 80+, but SPX_G only covers 6-79.
    df["is_adult"] = flag(df["RIDAGEYR"] >= 18, df["RIDAGEYR"])

    # Unit conversions: mL -> L, cm -> m.
    df["fev1_pre_L"] = df["SPXNFEV1"] / 1000
    df["fvc_pre_L"] = df["SPXNFVC"] / 1000
    df["fev1_post_L"] = df["SPXBFEV1"] / 1000
    df["fvc_post_L"] = df["SPXBFVC"] / 1000
    df["height_m"] = df["BMXHT"] / 100

    # Measurement availability.
    df["has_fev1_pre"] = df["SPXNFEV1"].notna()
    df["has_fvc_pre"] = df["SPXNFVC"].notna()
    df["has_fev1_post"] = df["SPXBFEV1"].notna()
    df["has_fvc_post"] = df["SPXBFVC"].notna()

    # SPDBRONC: 1 = selected, 2 = not selected, missing = no baseline evaluation.
    df["bd_selected"] = flag(df["SPDBRONC"] == 1, df["SPDBRONC"])
    # SPXBSTAT: 1 = complete; 2/3/4 = partial / not done / safety exclusion;
    # missing = not selected for bronchodilator testing.
    df["bd_completed"] = flag(df["SPXBSTAT"] == 1, df["SPXBSTAT"])

    # Quality grades A/B (meets or exceeds ATS standards), kept per measure.
    for col, raw in [
        ("fev1_pre_grade_AB", "SPXNQFV1"),
        ("fvc_pre_grade_AB", "SPXNQFVC"),
        ("fev1_post_grade_AB", "SPXBQFV1"),
        ("fvc_post_grade_AB", "SPXBQFVC"),
    ]:
        df[col] = flag(df[raw].isin(GOOD_GRADES), df[raw])

    # Height. CDC deleted implausible BMXHT values before release (BMX_G
    # "Data Processing and Editing"), so a present value is a valid height.
    df["has_valid_height"] = df["BMXHT"].notna()
    # BMIHT 3 = "Not straight": SP could not stand fully straight (e.g. kyphosis)
    # but stature was still recorded. Labels from the BMX_H (2013-14) codebook;
    # the comment is described in the 2011-12 Anthropometry Procedures Manual.
    # Informational only - not an exclusion.
    df["height_not_straight"] = df["BMIHT"].eq(3)

    # Known baseline status anomalies (see report), preserved as flags.
    has_pre = df["has_fev1_pre"] | df["has_fvc_pre"]
    df["pre_partial_no_values"] = df["SPXNSTAT"].eq(2) & ~has_pre
    df["pre_excluded_with_values"] = df["SPXNSTAT"].eq(4) & has_pre

    # Downstream-facing status labels that keep CDC selection separate from
    # whether baseline data exist. SPDBRONC=2 alone does NOT mean "not
    # obstructed": 44 participants have SPDBRONC=2 but no baseline values.
    both_pre = df["has_fev1_pre"] & df["has_fvc_pre"]
    df["bd_selection_status"] = "not_evaluated"                      # SPDBRONC missing
    df.loc[df["SPDBRONC"].eq(1), "bd_selection_status"] = "selected"
    df.loc[df["SPDBRONC"].eq(2) & both_pre, "bd_selection_status"] = "not_selected"
    df.loc[df["SPDBRONC"].eq(2) & ~both_pre, "bd_selection_status"] = "not_selected_no_baseline_values"
    # Post-BD exam outcome from SPXBSTAT; "not_applicable" = never selected.
    df["post_bd_exam_status"] = df["SPXBSTAT"].map(
        {1: "complete", 2: "partial", 3: "not_done", 4: "safety_exclusion"}
    ).fillna("not_applicable")
    return df


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def grade_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = {"FEV1 pre": "SPXNQFV1", "FVC pre": "SPXNQFVC", "FEV1 post": "SPXBQFV1", "FVC post": "SPXBQFVC"}
    out = pd.DataFrame({k: df[v].fillna("missing").value_counts() for k, v in cols.items()})
    order = [g for g in ["A", "B", "C", "D", "F", "missing"] if g in out.index]
    return out.reindex(order).fillna(0).astype(int)


def report_cohort(df: pd.DataFrame, label: str) -> None:
    n = len(df)
    print(f"\n{'=' * 70}\n{label}: n = {n:,}\n{'=' * 70}")

    print("\nMerge completeness")
    print(f"  matched in DEMO_G     {pct(int(df['in_demo'].sum()), n)}")
    print(f"  matched in BMX_G      {pct(int(df['in_bmx'].sum()), n)}")

    print("\nBaseline (pre-BD)")
    print(f"  SPXNSTAT              {df['SPXNSTAT'].value_counts().sort_index().astype(int).to_dict()}"
          "  (1 complete, 2 partial, 3 not done, 4 safety excl.)")
    print(f"  FEV1 available        {pct(int(df['has_fev1_pre'].sum()), n)}")
    print(f"  FVC available         {pct(int(df['has_fvc_pre'].sum()), n)}")
    both_ab = (df["fev1_pre_grade_AB"] & df["fvc_pre_grade_AB"]).fillna(False)
    print(f"  FEV1 & FVC grade A/B  {pct(int(both_ab.sum()), n)}")

    print("\nBronchodilator funnel")
    print(f"  SPDBRONC              {df['SPDBRONC'].value_counts(dropna=False).sort_index().to_dict()}"
          "  (1 selected, 2 not, NaN no baseline eval)")
    print(f"  SPXBSTAT              {df['SPXBSTAT'].value_counts(dropna=False).sort_index().to_dict()}")
    print(f"  bd_selection_status   {df['bd_selection_status'].value_counts().to_dict()}")
    print(f"  post-BD FEV1 avail.   {pct(int(df['has_fev1_post'].sum()), n)}")
    print(f"  post-BD FVC avail.    {pct(int(df['has_fvc_post'].sum()), n)}")
    post_ab = (df["fev1_post_grade_AB"] & df["fvc_post_grade_AB"]).fillna(False)
    pre_post_ab = both_ab & post_ab
    print(f"  post FEV1 & FVC A/B   {pct(int(post_ab.sum()), n)}")
    print(f"  pre AND post all A/B  {pct(int(pre_post_ab.sum()), n)}")

    print("\nQuality grades (counts)")
    print(grade_table(df).to_string().replace("\n", "\n  ").join(["  ", ""]))

    print("\nHeight")
    print(f"  valid height          {pct(int(df['has_valid_height'].sum()), n)}")
    print(f"  BMIHT                 {df['BMIHT'].value_counts(dropna=False).sort_index().to_dict()}"
          "  (1 could not obtain, 3 not straight)")
    print(f"  BMDSTATS              {df['BMDSTATS'].value_counts(dropna=False).sort_index().to_dict()}"
          "  (1 complete, 2 ht+wt only, 3 other partial, 4 none)")

    print("\nMissingness")
    key = ["RIDAGEYR", "RIAGENDR", "RIDRETH1", "BMXHT", "SPXNFEV1", "SPXNFVC",
           "SPXNQFV1", "SPXNQFVC", "SPDBRONC", "SPXBSTAT", "SPXBFEV1", "SPXBFVC",
           "SPXBQFV1", "SPXBQFVC"]
    for c in key:
        m = int(df[c].isna().sum())
        print(f"  {c:<10} {pct(m, n)}")


def report_anomalies(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 70}\nBaseline status anomalies\n{'=' * 70}")

    a = df[df["pre_partial_no_values"]]
    print(f"\n1) SPXNSTAT=2 (partial) with no baseline FEV1/FVC: n = {len(a)}")
    print(f"   FEV1 grade {a['SPXNQFV1'].value_counts().to_dict()}, FVC grade {a['SPXNQFVC'].value_counts().to_dict()}")
    print(f"   SPDBRONC {a['SPDBRONC'].value_counts(dropna=False).to_dict()}  "
          f"SPXNCMT {a['SPXNCMT'].value_counts(dropna=False).to_dict()}")
    print(f"   SPDNACC (acceptable curves) {a['SPDNACC'].value_counts().sort_index().astype(int).to_dict()}")
    print(f"   adults {int(a['is_adult'].sum())}, children {int((~a['is_adult']).sum())}")
    f_with_vals_fev1 = int((df["SPXNQFV1"].eq("F") & df["has_fev1_pre"]).sum())
    f_with_vals_fvc = int((df["SPXNQFVC"].eq("F") & df["has_fvc_pre"]).sum())
    print(f"   for contrast: grade F WITH released values: FEV1 {f_with_vals_fev1}, FVC {f_with_vals_fvc}")

    b = df[df["pre_excluded_with_values"]]
    print(f"\n2) SPXNSTAT=4 (safety exclusion) with baseline values: n = {len(b)}")
    cols = ["SEQN", "RIDAGEYR", "RIAGENDR", "SPXNFEV1", "SPXNFVC", "SPXNQFV1",
            "SPXNQFVC", "SPDNACC", "SPXNCMT", "SPDBRONC", "SPXBSTAT"]
    print(b[cols].to_string(index=False).replace("\n", "\n   ").join(["   ", ""]))


# --------------------------------------------------------------------------- #
def main() -> int:
    df = add_derived(load_and_merge())

    report_cohort(df, "Full spirometry cohort (SPX_G, ages 6-79)")
    report_cohort(df[df["is_adult"].fillna(False)], "Adult subset (RIDAGEYR >= 18)")
    report_anomalies(df)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {OUT_PATH.relative_to(REPO_ROOT)}  ({len(df):,} rows x {df.shape[1]} columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
