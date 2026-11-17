"""Bronchodilator response (BDR) and airflow-obstruction classifications.

Inputs (read only):
  data/processed/spirometry_intermediate.csv   (src/prepare_spirometry.py)
  data/processed/gli_reference.csv             (src/gli_reference.R)
Output:
  data/processed/spirometry.csv                (all 7,495 participants)

Thresholds and boundary operators come from config.yaml.

Conventions
-----------
* Volumes are the original NHANES integer mL values (SPXNFEV1, SPXBFEV1, ...);
  GLI predictions are in litres and converted to mL.
* A volume is usable only if finite and > 0. Changes are computed only when
  both pre and post volumes are usable; percentages also need a usable
  denominator. Nothing is rounded or imputed; negative changes are kept.
* Threshold tests use cross-multiplication, e.g. 100*delta >= 12*pre rather
  than 100*delta/pre >= 12, so exact boundaries are not lost to rounding
  (all denominators are > 0, so the operator direction is unchanged).
* Classifications are three-valued (pandas nullable boolean): True, False, or
  <NA> = not assessable. OR follows Kleene logic: any True -> True; False only
  when every component is assessable and False.
* Physiology is kept separate from data quality: classifications are computed
  wherever the arithmetic is possible; `primary_bdr_eligible` says whether a
  record is suitable for primary clinical interpretation.

No asthma or COPD diagnosis is made.
"""

from __future__ import annotations

import operator
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
INTERMEDIATE_PATH = REPO_ROOT / "data" / "processed" / "spirometry_intermediate.csv"
GLI_PATH = REPO_ROOT / "data" / "processed" / "gli_reference.csv"
OUT_PATH = REPO_ROOT / "data" / "processed" / "spirometry.csv"
N_EXPECTED = 7495

OPS = {">=": operator.ge, ">": operator.gt, "<": operator.lt, "<=": operator.le}


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as fh:
        cfg = yaml.safe_load(fh)
    for rule in (cfg["bdr"]["gina"]["pct_baseline"], cfg["bdr"]["gina"]["abs_change_ml"],
                 cfg["bdr"]["ats_ers"]["pct_predicted"], cfg["obstruction"]["fixed_ratio"]["fev1_fvc"],
                 cfg["obstruction"]["lln"]["fev1_fvc"]):
        if rule["operator"] not in OPS:
            raise ValueError(f"Unsupported operator {rule['operator']!r} in {path}")
    return cfg


# --------------------------------------------------------------------------- #
# Elementary calculations
# --------------------------------------------------------------------------- #
def _num(x) -> pd.Series:
    return pd.to_numeric(pd.Series(x), errors="coerce").astype(float)


def usable(x) -> pd.Series:
    """True where a value is finite and > 0 (never <NA>)."""
    x = _num(x)
    return pd.Series(np.isfinite(x) & (x > 0), index=x.index)


def tri(condition: pd.Series, assessable: pd.Series) -> pd.Series:
    """Nullable boolean: condition where assessable, <NA> elsewhere."""
    out = pd.Series(condition, dtype="boolean")
    return out.mask(~assessable.astype(bool))


def bd_change(pre_ml, post_ml, pred_l) -> pd.DataFrame:
    """Absolute and relative bronchodilator change for one measure.

    pre_ml, post_ml: measured volumes in mL; pred_l: GLI predicted value in L.
    """
    pre, post, pred_ml = _num(pre_ml), _num(post_ml), _num(pred_l) * 1000
    both = usable(pre) & usable(post)
    delta = (post - pre).where(both)
    return pd.DataFrame({
        "delta_ml": delta,
        "pct_baseline": (100 * delta / pre).where(both),
        "pct_predicted": (100 * delta / pred_ml).where(both & usable(pred_ml)),
        "_pre_ml": pre,
        "_pred_ml": pred_ml.where(usable(pred_ml)),
    })


def gina_component(ch: pd.DataFrame, cfg: dict) -> pd.Series:
    """GINA criterion for one measure: % of baseline AND absolute change."""
    g = cfg["bdr"]["gina"]
    pct, ab = g["pct_baseline"], g["abs_change_ml"]
    d, pre = ch["delta_ml"], ch["_pre_ml"]
    ok = d.notna()
    meets = OPS[pct["operator"]](100 * d, pct["threshold"] * pre) & OPS[ab["operator"]](d, ab["threshold"])
    return tri(meets, ok)


def ats_ers_component(ch: pd.DataFrame, cfg: dict) -> pd.Series:
    """ERS/ATS 2022 criterion for one measure: change as % of predicted."""
    r = cfg["bdr"]["ats_ers"]["pct_predicted"]
    d, pred = ch["delta_ml"], ch["_pred_ml"]
    ok = d.notna() & pred.notna()
    return tri(OPS[r["operator"]](100 * d, r["threshold"] * pred), ok)


def or3(a: pd.Series, b: pd.Series) -> pd.Series:
    """Three-valued (Kleene) OR of nullable booleans."""
    return a.astype("boolean") | b.astype("boolean")


def status(x: pd.Series, not_applicable: pd.Series | None = None,
           na_label: str = "not_applicable_pediatric") -> pd.Series:
    s = pd.Series(np.where(x.isna(), "not_assessable", np.where(x.fillna(False), "positive", "negative")),
                  index=x.index)
    if not_applicable is not None:
        s[not_applicable.astype(bool)] = na_label
    return s


def obstruction(fev1_ml, fvc_ml, lln, cfg: dict) -> pd.DataFrame:
    """Pre-BD FEV1/FVC below the fixed ratio and below the GLI LLN."""
    fev1, fvc, lln = _num(fev1_ml), _num(fvc_ml), _num(lln)
    ok = usable(fev1) & usable(fvc)
    ratio = (fev1 / fvc).where(ok)
    fr = cfg["obstruction"]["fixed_ratio"]["fev1_fvc"]
    ll = cfg["obstruction"]["lln"]["fev1_fvc"]
    lln_ok = ok & np.isfinite(lln) & (lln > 0)
    return pd.DataFrame({
        "fev1fvc_pre_ratio": ratio,
        "obstruction_fixed_ratio": tri(OPS[fr["operator"]](ratio, fr["threshold"]), ok),
        "obstruction_gli_lln": tri(OPS[ll["operator"]](ratio, lln), lln_ok),
    })


# --------------------------------------------------------------------------- #
# Full classification
# --------------------------------------------------------------------------- #
def classify(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add BDR and obstruction columns. Input needs original mL volumes,
    GLI predictions/LLN, is_adult, and the four *_grade_AB flags."""
    out = df.copy()
    adult = out["is_adult"].astype("boolean")
    not_adult = adult.fillna(False).eq(False)
    comp = {}
    for m, pre, post, pred in [("fev1", "SPXNFEV1", "SPXBFEV1", "gli_fev1_pred"),
                               ("fvc", "SPXNFVC", "SPXBFVC", "gli_fvc_pred")]:
        ch = bd_change(out[pre], out[post], out[pred])
        ch.index = out.index
        out[f"{m}_bd_change_ml"] = ch["delta_ml"]
        out[f"{m}_bd_change_pct_baseline"] = ch["pct_baseline"]
        out[f"{m}_bd_change_pct_pred"] = ch["pct_predicted"]
        comp[("gina", m)] = gina_component(ch, cfg).mask(not_adult)   # adults only
        comp[("ats", m)] = ats_ers_component(ch, cfg)

    out["gina_fev1_only"] = comp[("gina", "fev1")]
    out["gina_fvc_only"] = comp[("gina", "fvc")]
    out["gina_bdr"] = or3(comp[("gina", "fev1")], comp[("gina", "fvc")])
    out["gina_bdr_status"] = status(out["gina_bdr"], not_applicable=not_adult)
    out["ats_ers_fev1_only"] = comp[("ats", "fev1")]
    out["ats_ers_fvc_only"] = comp[("ats", "fvc")]
    out["ats_ers_bdr"] = or3(comp[("ats", "fev1")], comp[("ats", "fvc")])
    out["ats_ers_bdr_status"] = status(out["ats_ers_bdr"])

    ob = obstruction(out["SPXNFEV1"], out["SPXNFVC"], out["gli_fev1fvc_lln"], cfg)
    ob.index = out.index
    for c in ob:
        out[c] = ob[c]
    # The fixed 0.70 ratio is an adult criterion: the calculation above is kept
    # at all ages, but the interpretable label is blank for children.
    if cfg["obstruction"]["fixed_ratio"].get("interpretation_population") == "adults":
        out["obstruction_fixed_ratio_adult"] = out["obstruction_fixed_ratio"].mask(not_adult)
        out["obstruction_fixed_ratio_adult_status"] = status(out["obstruction_fixed_ratio_adult"],
                                                             not_applicable=not_adult)

    # Primary-analysis eligibility (data quality, not physiology).
    vols_ok = usable(out["SPXNFEV1"]) & usable(out["SPXNFVC"]) & usable(out["SPXBFEV1"]) & usable(out["SPXBFVC"])
    vols_ok.index = out.index
    have = out[["SPXNFEV1", "SPXNFVC", "SPXBFEV1", "SPXBFVC"]].notna().all(axis=1)
    grades = pd.concat([out[c].astype("boolean").fillna(False) for c in
                        ("fev1_pre_grade_AB", "fvc_pre_grade_AB", "fev1_post_grade_AB", "fvc_post_grade_AB")],
                       axis=1).all(axis=1)
    pred_ok = (usable(out["gli_fev1_pred"]) & usable(out["gli_fvc_pred"])).set_axis(out.index)
    reasons = [
        (~adult.fillna(False), "not_adult"),
        (~have, "missing_pre_or_post_fev1_fvc"),
        (~vols_ok, "nonpositive_or_nonfinite_volume"),
        (~grades, "grade_not_AB"),
        (~pred_ok, "no_valid_gli_prediction"),
    ]
    reason = pd.Series("", index=out.index)
    for cond, label in reversed(reasons):           # first failing reason wins
        reason[cond.astype(bool)] = label
    out["primary_bdr_eligible"] = reason.eq("")
    out["primary_bdr_exclusion_reason"] = reason
    return out


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def load_inputs() -> pd.DataFrame:
    inter = pd.read_csv(INTERMEDIATE_PATH)
    gli = pd.read_csv(GLI_PATH)
    assert len(inter) == N_EXPECTED and inter["SEQN"].is_unique
    assert len(gli) == N_EXPECTED and gli["SEQN"].is_unique

    shared = [c for c in gli.columns if c in inter.columns and c != "SEQN"]
    m = inter.merge(gli, on="SEQN", how="left", validate="one_to_one", suffixes=("", "_gli"),
                    indicator=True)
    assert len(m) == N_EXPECTED and (m["_merge"] == "both").all(), "SEQN mismatch between inputs"
    m = m.drop(columns="_merge")

    # Columns present in both inputs must agree; keep the intermediate copy.
    for c in shared:
        a, b = m[c], m[f"{c}_gli"]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            same = np.isclose(a, b, rtol=0, atol=1e-12, equal_nan=True)
        else:
            same = (a.astype(str).str.lower() == b.astype(str).str.lower()) | (a.isna() & b.isna())
        assert bool(np.all(same)), f"inputs disagree on {c}"
        m = m.drop(columns=f"{c}_gli")
    return m


def report(out: pd.DataFrame) -> None:
    def vc(s):
        return s.value_counts(dropna=False).to_dict()

    adults = out[out["is_adult"].astype("boolean").fillna(False)]
    elig = out[out["primary_bdr_eligible"]]
    print(f"rows: {len(out):,} (adults {len(adults):,}); primary BDR eligible: {len(elig):,}")
    print("primary_bdr_exclusion_reason:", vc(out["primary_bdr_exclusion_reason"]))
    for label, d in [("all", out), ("adults", adults), ("primary eligible", elig)]:
        print(f"\n[{label}] n={len(d):,}")
        for c in ("gina_bdr_status", "ats_ers_bdr_status"):
            print(f"  {c:<22}", vc(d[c]))
        for c in ("gina_fev1_only", "ats_ers_fev1_only", "obstruction_fixed_ratio", "obstruction_gli_lln"):
            print(f"  {c:<22}", {str(k): v for k, v in vc(d[c]).items()})


def main() -> int:
    cfg = load_config()
    inter_bytes = INTERMEDIATE_PATH.read_bytes()
    gli_bytes = GLI_PATH.read_bytes()

    out = classify(load_inputs(), cfg)
    assert len(out) == N_EXPECTED and out["SEQN"].is_unique

    report(out)
    out.to_csv(OUT_PATH, index=False)
    assert INTERMEDIATE_PATH.read_bytes() == inter_bytes and GLI_PATH.read_bytes() == gli_bytes
    print(f"\nWrote {OUT_PATH.relative_to(REPO_ROOT)} ({len(out):,} rows x {out.shape[1]} columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
