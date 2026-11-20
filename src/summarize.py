"""Task 6: guideline disagreements, sensitivity analyses, and candidate cases.

Input (read only): data/processed/spirometry.csv (src/bdr.py)

Aggregate outputs (no participant-level rows; safe to share):
  results/summary/cohort_summary.csv
  results/summary/bdr_disagreement.csv
  results/summary/obstruction_disagreement.csv
  results/summary/sensitivity_analysis.csv
Participant-level input (gitignored, hand-curated; optional):
  data/processed/benchmark_controls.csv      expert-chosen BDR controls, by SEQN
Participant-level outputs (gitignored):
  benchmark/candidate_cases.csv              pseudonymous; no SEQN
  data/processed/candidate_seqn_mapping.csv  case_id <-> SEQN (append-only)
  data/processed/bdr_disagreement_cases.csv
  data/processed/obstruction_disagreement_cases.csv

All counts and percentages are UNWEIGHTED NHANES sample counts. They describe
this sample, not U.S. population prevalence (no survey weights are applied).
Classifications that are not assessable are excluded from every comparison,
never counted as negative. Nothing here judges which guideline is more
clinically accurate, and no obstruction flag is an asthma or COPD diagnosis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
IN_PATH = REPO_ROOT / "data" / "processed" / "spirometry.csv"
SUMMARY_DIR = REPO_ROOT / "results" / "summary"
CANDIDATES_PATH = REPO_ROOT / "benchmark" / "candidate_cases.csv"
MAPPING_PATH = REPO_ROOT / "data" / "processed" / "candidate_seqn_mapping.csv"
CONTROLS_PATH = REPO_ROOT / "data" / "processed" / "benchmark_controls.csv"
CASES_DIR = REPO_ROOT / "data" / "processed"

TRI_COLS = ["is_adult", "height_not_straight", "gina_fev1_only", "gina_fvc_only", "gina_bdr",
            "ats_ers_fev1_only", "ats_ers_fvc_only", "ats_ers_bdr", "obstruction_fixed_ratio",
            "obstruction_gli_lln", "obstruction_fixed_ratio_adult", "primary_bdr_eligible"]
AGE_BANDS = [("18-39", 18, 39), ("40-59", 40, 59), ("60+", 60, 200)]
GRADES_AB, GRADES_ABC = ("A", "B"), ("A", "B", "C")
BDR_GRADE_COLS = ["SPXNQFV1", "SPXNQFVC", "SPXBQFV1", "SPXBQFVC"]
PRE_GRADE_COLS = ["SPXNQFV1", "SPXNQFVC"]


# --------------------------------------------------------------------------- #
# Loading and population definitions
# --------------------------------------------------------------------------- #
def to_tri(s: pd.Series) -> pd.Series:
    """CSV True/False/blank -> nullable boolean."""
    m = {True: True, False: False, "True": True, "False": False, "TRUE": True, "FALSE": False}
    return s.map(lambda v: m.get(v, pd.NA)).astype("boolean")


def load(path: Path = IN_PATH) -> pd.DataFrame:
    d = pd.read_csv(path)
    for c in TRI_COLS:
        d[c] = to_tri(d[c])
    d["primary_bdr_exclusion_reason"] = d["primary_bdr_exclusion_reason"].fillna("")
    return d


def T(s: pd.Series) -> pd.Series:
    """True where a nullable boolean is True; not assessable -> False (for row selection)."""
    return s.astype("boolean").fillna(False).astype(bool)


def F(s: pd.Series) -> pd.Series:
    """True where a nullable boolean is False; not assessable -> False."""
    return (~s.astype("boolean")).fillna(False).astype(bool)


def tv(x) -> bool:
    """Scalar: True only for a real True (not NA)."""
    return (not pd.isna(x)) and bool(x)


def usable(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    return np.isfinite(s) & (s > 0)


def grades_in(d: pd.DataFrame, cols, allowed) -> pd.Series:
    return d[cols].isin(allowed).all(axis=1)


def adults(d: pd.DataFrame) -> pd.Series:
    return d["is_adult"].fillna(False).astype(bool)


def bdr_population(d: pd.DataFrame, grades=GRADES_AB) -> dict:
    """Stepwise BDR population: paired measurements, valid predictions, grades."""
    a = adults(d)
    paired = a & usable(d["SPXNFEV1"]) & usable(d["SPXNFVC"]) & usable(d["SPXBFEV1"]) & usable(d["SPXBFVC"])
    pred = paired & usable(d["gli_fev1_pred"]) & usable(d["gli_fvc_pred"])
    final = pred & grades_in(d, BDR_GRADE_COLS, grades)
    return {"adults": a, "paired": paired, "pred": pred, "final": final}


def obstruction_population(d: pd.DataFrame, grades=None) -> dict:
    """Adults with valid pre-BD FEV1/FVC and a GLI LLN; optional pre-BD grade rule."""
    a = adults(d)
    base = a & usable(d["SPXNFEV1"]) & usable(d["SPXNFVC"])
    pred = base & usable(d["gli_fev1fvc_lln"])
    final = pred & (grades_in(d, PRE_GRADE_COLS, grades) if grades else True)
    return {"adults": a, "paired": base, "pred": pred, "final": final}


def age_band(d: pd.DataFrame, lo: int, hi: int) -> pd.Series:
    return d["RIDAGEYR"].between(lo, hi)


# --------------------------------------------------------------------------- #
# Agreement statistics
# --------------------------------------------------------------------------- #
def contingency(x: pd.Series, y: pd.Series) -> dict:
    """2x2 table of two nullable booleans; rows with either value missing are excluded."""
    x, y = x.astype("boolean"), y.astype("boolean")
    ok = x.notna() & y.notna()
    xs, ys = x[ok].astype(bool), y[ok].astype(bool)
    t = {"n_both_pos": int((xs & ys).sum()), "n_first_only": int((xs & ~ys).sum()),
         "n_second_only": int((~xs & ys).sum()), "n_both_neg": int((~xs & ~ys).sum())}
    t["n_classified"] = int(ok.sum())
    t["n_missing_classification"] = int((~ok).sum())
    t["n_first_pos"] = t["n_both_pos"] + t["n_first_only"]
    t["n_second_pos"] = t["n_both_pos"] + t["n_second_only"]
    t["observed_agreement"] = (t["n_both_pos"] + t["n_both_neg"]) / t["n_classified"] if t["n_classified"] else np.nan
    t["cohens_kappa"] = cohens_kappa(t["n_both_pos"], t["n_first_only"], t["n_second_only"], t["n_both_neg"])
    return t


def cohens_kappa(a: int, b: int, c: int, d: int) -> float:
    """Kappa for [[a, b], [c, d]] (a = both positive, d = both negative)."""
    n = a + b + c + d
    if n == 0:
        return np.nan
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / n ** 2
    return np.nan if pe == 1 else (po - pe) / (1 - pe)


def pct(n, d):
    return 100 * n / d if d else np.nan


# --------------------------------------------------------------------------- #
# Disagreement causes
# --------------------------------------------------------------------------- #
def bdr_cause(r: pd.Series) -> tuple[str, str]:
    """(category, detail) explaining a GINA vs ERS/ATS disagreement."""
    parts, cats = [], []
    for m, M in (("fev1", "FEV1"), ("fvc", "FVC")):
        g, a = r[f"gina_{m}_only"], r[f"ats_ers_{m}_only"]
        dml, pb, pp = r[f"{m}_bd_change_ml"], r[f"{m}_bd_change_pct_baseline"], r[f"{m}_bd_change_pct_pred"]
        pre_pp = 100 * r[f"SPXN{M}"] / (1000 * r[f"gli_{m}_pred"])
        txt = f"{M} {dml:+.0f} mL, {pb:.1f}% baseline, {pp:.1f}% pred (pre-BD {pre_pp:.0f}% pred)"
        if tv(r["gina_bdr"]) and not tv(r["ats_ers_bdr"]) and tv(g):
            cats.append(f"GINA met via {M}; ERS/ATS {M} <=10% pred")
            parts.append(txt)
        if tv(r["ats_ers_bdr"]) and not tv(r["gina_bdr"]) and tv(a):
            fail = [lbl for ok, lbl in ((pb >= 12, "<12% baseline"), (dml >= 200, "<200 mL")) if not ok]
            cats.append(f"ERS/ATS met via {M}; GINA {M} failed {' and '.join(fail)}")
            parts.append(txt)
    return " | ".join(cats), " | ".join(parts)


# --------------------------------------------------------------------------- #
# Candidate selection
# --------------------------------------------------------------------------- #
def _pick(pool: pd.DataFrame, key: pd.Series, k: int, taken: set, ascending=True) -> list:
    """Deterministic: sort by key, then SEQN; skip already chosen participants."""
    p = pool.assign(_k=key.reindex(pool.index)).dropna(subset=["_k"])
    p = p[~p["SEQN"].isin(taken)].sort_values(["_k", "SEQN"], ascending=[ascending, True])
    return p["SEQN"].head(k).tolist()


def select_candidates(d: pd.DataFrame) -> pd.DataFrame:
    """Return SEQN, category and reason for ~20 candidates, in a fixed order."""
    e = d[T(d["primary_bdr_eligible"])]
    ob = d[obstruction_population(d, GRADES_AB)["final"]]
    adult = d[adults(d)]
    rows, taken = [], set()

    def add(seqns, category, reason):
        for s in seqns:
            rows.append({"SEQN": int(s), "selection_category": category, "selection_reason": reason})
            taken.add(s)

    best_pp = e[["fev1_bd_change_pct_pred", "fvc_bd_change_pct_pred"]].max(axis=1)
    best_ml = e[["fev1_bd_change_ml", "fvc_bd_change_ml"]].max(axis=1)
    g_only = e[T(e["gina_bdr"]) & F(e["ats_ers_bdr"])]
    a_only = e[T(e["ats_ers_bdr"]) & F(e["gina_bdr"])]
    add(_pick(g_only, best_ml, 3, taken, ascending=False), "bdr_gina_only",
        "GINA-positive, ERS/ATS-negative (largest absolute change)")
    add(_pick(a_only, best_pp, 3, taken, ascending=False), "bdr_ats_ers_only",
        "ERS/ATS-positive, GINA-negative (largest % predicted change)")

    def only(m, n):  # measure m positive and n negative under both guidelines
        return T(e[f"gina_{m}_only"]) & F(e[f"gina_{n}_only"]) & T(e[f"ats_ers_{m}_only"]) & F(e[f"ats_ers_{n}_only"])
    add(_pick(e[only("fev1", "fvc")], e["fev1_bd_change_ml"], 2, taken, ascending=False),
        "fev1_only_responder", "FEV1-only response under both guidelines")
    fvc_pool, fvc_reason = e[only("fvc", "fev1")], "FVC-only response under both guidelines"
    if len(fvc_pool) < 2:
        fvc_pool = e[T(e["gina_fvc_only"]) & F(e["gina_fev1_only"])]
        fvc_reason = "FVC-only response under GINA"
    add(_pick(fvc_pool, e["fvc_bd_change_ml"], 2, taken, ascending=False), "fvc_only_responder", fvc_reason)

    # Near thresholds: distance on the criterion that decides the call.
    d200 = pd.concat([(e[f"{m}_bd_change_ml"] - 200).abs().where(e[f"{m}_bd_change_pct_baseline"] >= 12)
                      for m in ("fev1", "fvc")], axis=1).min(axis=1)
    d12 = pd.concat([(e[f"{m}_bd_change_pct_baseline"] - 12).abs().where(e[f"{m}_bd_change_ml"] >= 200)
                     for m in ("fev1", "fvc")], axis=1).min(axis=1)
    d10 = pd.concat([(e[f"{m}_bd_change_pct_pred"] - 10).abs() for m in ("fev1", "fvc")], axis=1).min(axis=1)
    add(_pick(e, d200, 1, taken), "near_threshold_200ml", "Change closest to 200 mL (with >=12% baseline)")
    add(_pick(e, d12, 1, taken), "near_threshold_12pct", "Change closest to 12% of baseline (with >=200 mL)")
    add(_pick(e, d10, 1, taken), "near_threshold_10pct_pred", "Change closest to 10% of predicted")

    fixed_only = ob[T(ob["obstruction_fixed_ratio"]) & F(ob["obstruction_gli_lln"])]
    lln_only = ob[F(ob["obstruction_fixed_ratio"]) & T(ob["obstruction_gli_lln"])]
    add(_pick(fixed_only, ob["fev1fvc_pre_ratio"], 1, taken), "obstruction_fixed_only",
        "FEV1/FVC < 0.70 but above GLI LLN (lowest ratio)")
    add(_pick(lln_only, ob["fev1fvc_pre_ratio"], 1, taken, ascending=False), "obstruction_lln_only",
        "FEV1/FVC below GLI LLN but >= 0.70 (highest ratio)")
    gap = ob["fev1fvc_pre_ratio"] - ob["gli_fev1fvc_lln"]
    add(_pick(ob, gap.where(gap < 0).abs(), 1, taken), "borderline_lln_below", "FEV1/FVC just below GLI LLN")
    add(_pick(ob, gap.where(gap >= 0), 1, taken), "borderline_lln_above", "FEV1/FVC just above GLI LLN")

    bdr_pop = bdr_population(d, GRADES_AB)
    low_q = d[bdr_pop["pred"] & ~bdr_pop["final"] & (T(d["gina_bdr"]) | T(d["ats_ers_bdr"]))]
    add(_pick(low_q, low_q["SEQN"], 1, taken), "poor_quality_bdr",
        "BDR-positive but a pre/post grade is not A/B")
    poor_base = adult[adult[PRE_GRADE_COLS].isin(["D", "F"]).any(axis=1) & T(adult["obstruction_gli_lln"])]
    add(_pick(poor_base, poor_base["SEQN"], 1, taken), "poor_quality_baseline",
        "Baseline grade D/F with FEV1/FVC below LLN")

    no_post = adult[(adult["bd_selection_status"] == "selected") &
                    adult["post_bd_exam_status"].isin(["not_done", "safety_exclusion"]) &
                    T(adult["obstruction_gli_lln"])]
    add(_pick(no_post, no_post["SEQN"], 1, taken), "missing_post_bd",
        "Selected for BD testing and below LLN, but post-BD test not done")
    no_ht = adult[adult["height_m"].isna() & adult["SPXBFEV1"].notna()]
    add(_pick(no_ht, no_ht["SEQN"], 1, taken), "missing_height",
        "Post-BD data present but height missing (no GLI predictions)")
    return pd.DataFrame(rows)


# Expert-chosen controls are kept in a private registry (SEQN is never written
# to public files). Each entry carries the raw measurements as a fingerprint so a
# changed or mistyped SEQN fails instead of silently selecting someone else.
CONTROL_CATEGORIES = {
    "concordant_negative_control": ("negative", "Concordant-negative BDR control (GINA and ERS/ATS both negative)"),
    "concordant_positive_control": ("positive", "Concordant-positive BDR control (GINA and ERS/ATS both positive)"),
}
CONTROL_FINGERPRINT = ["RIDAGEYR", "RIAGENDR", "BMXHT", "SPXNFEV1", "SPXNFVC", "SPXBFEV1", "SPXBFVC"]


def add_controls(d: pd.DataFrame, selected: pd.DataFrame, controls: pd.DataFrame | None) -> pd.DataFrame:
    """Append registry controls after the rule-based candidates, in registry order.

    Controls are appended (never interleaved), so rule-based case IDs are unchanged
    and new controls take the next free IDs in the append-only mapping.
    """
    if controls is None or not len(controls):
        return selected
    errs, rows = [], []
    taken = set(selected["SEQN"].astype(int))
    by_seqn = d.set_index("SEQN")
    for r in controls.to_dict("records"):
        s, cat, lab = int(r["SEQN"]), r["selection_category"], r.get("control_label", "?")
        if cat not in CONTROL_CATEGORIES:
            errs.append(f"{lab}: unknown selection_category {cat!r}")
            continue
        if s in taken:
            errs.append(f"{lab}: participant already selected")
            continue
        if s not in by_seqn.index:
            errs.append(f"{lab}: participant not in spirometry.csv")
            continue
        row = by_seqn.loc[s]
        bad = [c for c in CONTROL_FINGERPRINT if float(row[c]) != float(r[c])]
        if bad:
            errs.append(f"{lab}: registry measurements disagree with spirometry.csv for {bad}")
        status, reason = CONTROL_CATEGORIES[cat]
        if not (tv(row["primary_bdr_eligible"]) and row["gina_bdr_status"] == status
                and row["ats_ers_bdr_status"] == status):
            errs.append(f"{lab}: not a primary-eligible {cat} (GINA {row['gina_bdr_status']}, "
                        f"ERS/ATS {row['ats_ers_bdr_status']}, eligible {row['primary_bdr_eligible']})")
        rows.append({"SEQN": s, "selection_category": cat, "selection_reason": reason})
        taken.add(s)
    if errs:
        raise ValueError("benchmark_controls.csv is invalid:\n  - " + "\n  - ".join(errs))
    return pd.concat([selected, pd.DataFrame(rows)], ignore_index=True)


def assign_ids(selected: pd.DataFrame, existing: pd.DataFrame | None) -> pd.DataFrame:
    """Stable case IDs: reuse any existing SEQN->ID; new SEQNs get the next numbers.

    The mapping is append-only, so an ID is never reused for another participant.
    """
    mapping = existing[["case_id", "SEQN"]].copy() if existing is not None and len(existing) else \
        pd.DataFrame({"case_id": pd.Series(dtype=str), "SEQN": pd.Series(dtype="int64")})
    known = dict(zip(mapping["SEQN"].astype(int), mapping["case_id"]))
    nxt = max([int(c[2:]) for c in mapping["case_id"]], default=0) + 1
    ids = []
    for s in selected["SEQN"].astype(int):
        if s not in known:
            known[s] = f"PB{nxt:03d}"
            mapping = pd.concat([mapping, pd.DataFrame({"case_id": [known[s]], "SEQN": [s]})], ignore_index=True)
            nxt += 1
        ids.append(known[s])
    out = selected.copy()
    out.insert(0, "case_id", ids)
    mapping["currently_selected"] = mapping["SEQN"].astype(int).isin(selected["SEQN"].astype(int))
    return out, mapping.sort_values("case_id").reset_index(drop=True)


def limitations(r: pd.Series) -> str:
    notes = []
    grades = {c: r[c] for c in BDR_GRADE_COLS if isinstance(r[c], str)}
    bad = [f"{c}={g}" for c, g in grades.items() if g not in GRADES_AB]
    if bad:
        notes.append("quality grade not A/B (" + ", ".join(bad) + ")")
    if tv(r["height_not_straight"]):
        notes.append("height measured not straight")
    if pd.isna(r["height_m"]):
        notes.append("height missing: no GLI predictions")
    if pd.isna(r["SPXBFEV1"]):
        notes.append(f"no post-BD data ({r['post_bd_exam_status']})")
    if r["SPXNSTAT"] != 1:
        notes.append(f"baseline exam status SPXNSTAT={int(r['SPXNSTAT'])}")
    if r["selection_category"].startswith(("near_threshold", "borderline")):
        notes.append("near a threshold: measurement variability could change the classification")
    notes.append("age in whole years")
    return "; ".join(notes)


PUBLIC_COLS = [
    "case_id", "selection_category", "selection_reason", "limitations",
    "age_years", "sex", "height_cm", "height_not_straight",
    "fev1_pre_L", "fvc_pre_L", "fev1_post_L", "fvc_post_L", "fev1fvc_pre_ratio",
    "SPXNQFV1", "SPXNQFVC", "SPXBQFV1", "SPXBQFVC", "bd_selection_status", "post_bd_exam_status",
    "gli_fev1_pred", "gli_fev1_lln", "gli_fev1_z", "gli_fvc_pred", "gli_fvc_lln", "gli_fvc_z",
    "gli_fev1fvc_pred", "gli_fev1fvc_lln", "gli_fev1fvc_z",
    "fev1_bd_change_ml", "fev1_bd_change_pct_baseline", "fev1_bd_change_pct_pred",
    "fvc_bd_change_ml", "fvc_bd_change_pct_baseline", "fvc_bd_change_pct_pred",
    "gina_fev1_only", "gina_fvc_only", "gina_bdr", "gina_bdr_status",
    "ats_ers_fev1_only", "ats_ers_fvc_only", "ats_ers_bdr", "ats_ers_bdr_status",
    "obstruction_fixed_ratio_adult", "obstruction_gli_lln",
    "primary_bdr_eligible", "primary_bdr_exclusion_reason",
]


def public_candidates(d: pd.DataFrame, ided: pd.DataFrame) -> pd.DataFrame:
    m = ided.merge(d, on="SEQN", how="left", validate="one_to_one")
    m["age_years"] = m["RIDAGEYR"]
    m["sex"] = m["RIAGENDR"].map({1: "male", 2: "female"})
    m["height_cm"] = m["BMXHT"]
    m["limitations"] = m.apply(limitations, axis=1)
    return m[PUBLIC_COLS]


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def long_row(section, population, metric, category="", count=np.nan, denominator=np.nan, value=np.nan):
    return {"section": section, "population": population, "metric": metric, "category": category,
            "count": count, "denominator": denominator,
            "percent": pct(count, denominator) if pd.notna(count) and pd.notna(denominator) else np.nan,
            "value": value}


def table_rows(section, population, t, first, second):
    n = t["n_classified"]
    rows = [long_row(section, population, "both_positive", f"{first}+ {second}+", t["n_both_pos"], n),
            long_row(section, population, "first_only_positive", f"{first}+ {second}-", t["n_first_only"], n),
            long_row(section, population, "second_only_positive", f"{first}- {second}+", t["n_second_only"], n),
            long_row(section, population, "both_negative", f"{first}- {second}-", t["n_both_neg"], n),
            long_row(section, population, "marginal_positive", first, t["n_first_pos"], n),
            long_row(section, population, "marginal_positive", second, t["n_second_pos"], n),
            long_row(section, population, "excluded_not_assessable", "", t["n_missing_classification"]),
            long_row(section, population, "observed_agreement", value=t["observed_agreement"]),
            long_row(section, population, "cohens_kappa", value=t["cohens_kappa"])]
    return rows


def describe(s: pd.Series) -> dict:
    s = s.dropna()
    return {"n": len(s), "mean": s.mean(), "sd": s.std(), "median": s.median(),
            "q1": s.quantile(0.25), "q3": s.quantile(0.75), "min": s.min(), "max": s.max(),
            "n_negative": int((s < 0).sum())}


def sensitivity_row(comparison, subset, pops, mask, x, y) -> dict:
    scope = pops["adults"] & mask
    t = contingency(x[scope & pops["final"]], y[scope & pops["final"]])
    n_scope = int(scope.sum())
    return {
        "comparison": comparison, "subset": subset,
        "n_adults_in_scope": n_scope,
        "n_missing_or_invalid_measurements": int((scope & ~pops["paired"]).sum()),
        "n_missing_or_invalid_prediction": int((scope & pops["paired"] & ~pops["pred"]).sum()),
        "n_failed_quality_rule": int((scope & pops["pred"] & ~pops["final"]).sum()),
        "n_included": int((scope & pops["final"]).sum()),
        **t,
        "pct_first_pos": pct(t["n_first_pos"], t["n_classified"]),
        "pct_second_pos": pct(t["n_second_pos"], t["n_classified"]),
    }


# --------------------------------------------------------------------------- #
def run(in_path=IN_PATH, summary_dir=SUMMARY_DIR, candidates_path=CANDIDATES_PATH,
        mapping_path=MAPPING_PATH, cases_dir=CASES_DIR, controls_path=CONTROLS_PATH, verbose=True) -> dict:
    in_bytes = Path(in_path).read_bytes()
    d = load(in_path)
    elig = d["primary_bdr_eligible"].fillna(False).astype(bool)

    # Strict A/B population must reproduce the Task 5 eligibility rule exactly.
    strict = bdr_population(d, GRADES_AB)["final"]
    assert strict.equals(elig), "strict A/B population differs from primary_bdr_eligible"
    e = d[elig]

    cohort = [long_row("cohort", "all", "participants", count=len(d)),
              long_row("cohort", "all", "adults", count=int(adults(d).sum()), denominator=len(d)),
              long_row("cohort", "adults", "primary_bdr_eligible", count=int(elig.sum()),
                       denominator=int(adults(d).sum()))]
    for reason, n in d.loc[adults(d), "primary_bdr_exclusion_reason"].replace("", "eligible").value_counts().items():
        cohort.append(long_row("cohort", "adults", "primary_bdr_exclusion_reason", reason, int(n),
                               int(adults(d).sum())))

    # --- BDR: GINA vs ERS/ATS ------------------------------------------------
    t_bdr = contingency(e["gina_bdr"], e["ats_ers_bdr"])
    src_gina, src_ats = int(T(e["gina_bdr"]).sum()), int(T(e["ats_ers_bdr"]).sum())
    assert (t_bdr["n_first_pos"], t_bdr["n_second_pos"]) == (src_gina, src_ats), "marginals differ from source"
    assert sum(t_bdr[k] for k in ("n_both_pos", "n_first_only", "n_second_only", "n_both_neg")) == t_bdr["n_classified"]
    bdr_rows = table_rows("gina_vs_ats_ers", "primary_bdr_eligible", t_bdr, "GINA", "ERS/ATS")

    dis = e[(e["gina_bdr"] != e["ats_ers_bdr"]).fillna(False)].copy()
    causes = dis.apply(bdr_cause, axis=1, result_type="expand")
    dis["direction"] = np.where(T(dis["gina_bdr"]), "GINA+ ERS/ATS-", "GINA- ERS/ATS+")
    dis["cause_category"], dis["cause_detail"] = causes[0], causes[1]
    for (direction, cat), n in dis.groupby(["direction", "cause_category"]).size().items():
        bdr_rows.append(long_row("disagreement_cause", "primary_bdr_eligible", direction, cat, int(n), len(dis)))
    pre_pp = {m: 100 * e[f"SPXN{m.upper()}"] / (1000 * e[f"gli_{m}_pred"]) for m in ("fev1", "fvc")}
    for direction, sub in [("GINA+ ERS/ATS-", dis[dis["direction"] == "GINA+ ERS/ATS-"]),
                           ("GINA- ERS/ATS+", dis[dis["direction"] == "GINA- ERS/ATS+"]),
                           ("concordant", e.drop(dis.index))]:
        bdr_rows.append(long_row("baseline_fev1_pct_predicted", "primary_bdr_eligible", direction,
                                 "median", count=len(sub), value=pre_pp["fev1"].reindex(sub.index).median()))

    # --- FEV1 vs FVC contribution ---------------------------------------------
    for g, label in (("gina", "GINA"), ("ats_ers", "ERS/ATS")):
        f1, fv = e[f"{g}_fev1_only"].astype(bool), e[f"{g}_fvc_only"].astype(bool)
        for cat, mask in (("FEV1 only", f1 & ~fv), ("FVC only", ~f1 & fv), ("both", f1 & fv), ("neither", ~f1 & ~fv)):
            cohort.append(long_row("measure_contribution", "primary_bdr_eligible", label, cat, int(mask.sum()), len(e)))
        cohort.append(long_row("measure_contribution", "primary_bdr_eligible", label,
                               "FEV1 criterion met (any)", int(f1.sum()), len(e)))
        cohort.append(long_row("measure_contribution", "primary_bdr_eligible", label,
                               "FVC criterion met (any)", int(fv.sum()), len(e)))
    for m in ("fev1", "fvc"):
        for kind in ("ml", "pct_baseline", "pct_pred"):
            for stat, v in describe(e[f"{m}_bd_change_{kind}"]).items():
                cohort.append(long_row("bd_change", "primary_bdr_eligible", f"{m}_bd_change_{kind}", stat, value=v))
    # Negative FVC change vs FVC grade: all adults with paired FVC (any grade).
    pf = d[adults(d) & d["fvc_bd_change_ml"].notna()]
    for col in ("SPXNQFVC", "SPXBQFVC"):
        for grade, sub in pf.groupby(pf[col].fillna("missing")):
            cohort.append(long_row("fvc_negative_change_by_grade", "adults_paired_fvc", col, grade,
                                   int((sub["fvc_bd_change_ml"] < 0).sum()), len(sub)))

    # --- Obstruction ------------------------------------------------------------
    ob_rows, ob_cases = [], []
    for pop_name, grades in (("adults_assessable_any_grade", None), ("adults_pre_grades_AB", GRADES_AB)):
        pop = obstruction_population(d, grades)["final"]
        sub = d[pop]
        t = contingency(sub["obstruction_fixed_ratio"], sub["obstruction_gli_lln"])
        ob_rows += table_rows("fixed_vs_lln", pop_name, t, "fixed<0.70", "<LLN")
        for band, lo, hi in AGE_BANDS:
            sb = sub[age_band(sub, lo, hi)]
            tb = contingency(sb["obstruction_fixed_ratio"], sb["obstruction_gli_lln"])
            for metric, k in (("fixed_only", "n_first_only"), ("lln_only", "n_second_only"),
                              ("both_positive", "n_both_pos"), ("both_negative", "n_both_neg")):
                ob_rows.append(long_row("fixed_vs_lln_by_age", pop_name, metric, band, tb[k], tb["n_classified"]))
            ob_rows.append(long_row("fixed_vs_lln_by_age", pop_name, "cohens_kappa", band, value=tb["cohens_kappa"]))
        if grades:
            dd = sub[(sub["obstruction_fixed_ratio"] != sub["obstruction_gli_lln"]).fillna(False)]
            ob_cases = dd.assign(direction=np.where(T(dd["obstruction_fixed_ratio"]), "fixed_only", "lln_only"))

    # --- Sensitivity ------------------------------------------------------------
    sens = []
    allm = pd.Series(True, index=d.index)
    not_straight = d["height_not_straight"].fillna(False).astype(bool)
    defs = [("strict_AB", GRADES_AB, allm), ("expanded_ABC", GRADES_ABC, allm),
            ("strict_AB_excl_height_not_straight", GRADES_AB, ~not_straight)]
    defs += [(f"strict_AB_age_{b}", GRADES_AB, age_band(d, lo, hi)) for b, lo, hi in AGE_BANDS]
    for name, grades, mask in defs:
        sens.append(sensitivity_row("bdr_gina_vs_ats_ers", name, bdr_population(d, grades), mask,
                                    d["gina_bdr"], d["ats_ers_bdr"]))
        sens.append(sensitivity_row("obstruction_fixed_vs_lln", name, obstruction_population(d, grades), mask,
                                    d["obstruction_fixed_ratio"], d["obstruction_gli_lln"]))
    sens.append(sensitivity_row("obstruction_fixed_vs_lln", "assessable_any_grade",
                                obstruction_population(d, None), allm,
                                d["obstruction_fixed_ratio"], d["obstruction_gli_lln"]))
    sens_df = pd.DataFrame(sens)

    # --- Candidates -------------------------------------------------------------
    mp = Path(mapping_path)
    existing = pd.read_csv(mp) if mp.is_file() else None
    cp = Path(controls_path) if controls_path is not None else None
    controls = pd.read_csv(cp) if cp is not None and cp.is_file() else None
    ided, mapping = assign_ids(add_controls(d, select_candidates(d), controls), existing)
    if existing is not None:   # append-only: every earlier ID keeps its participant
        old_ids = existing[["case_id", "SEQN"]].merge(mapping[["case_id", "SEQN"]], how="left", indicator=True)
        assert (old_ids["_merge"] == "both").all(), "candidate mapping is not append-only"
    public = public_candidates(d, ided)
    assert "SEQN" not in public.columns

    # --- Write ------------------------------------------------------------------
    summary_dir, cases_dir = Path(summary_dir), Path(cases_dir)
    summary_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(cohort).to_csv(summary_dir / "cohort_summary.csv", index=False)
    pd.DataFrame(bdr_rows).to_csv(summary_dir / "bdr_disagreement.csv", index=False)
    pd.DataFrame(ob_rows).to_csv(summary_dir / "obstruction_disagreement.csv", index=False)
    sens_df.to_csv(summary_dir / "sensitivity_analysis.csv", index=False)
    Path(candidates_path).parent.mkdir(parents=True, exist_ok=True)
    public.to_csv(candidates_path, index=False)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mapping.to_csv(mp, index=False)
    case_cols = ["SEQN", "RIDAGEYR", "RIAGENDR", "direction"]
    dis[case_cols + ["cause_category", "cause_detail"]].to_csv(cases_dir / "bdr_disagreement_cases.csv", index=False)
    ob_cases[case_cols + ["fev1fvc_pre_ratio", "gli_fev1fvc_lln", "gli_fev1fvc_z"]].to_csv(
        cases_dir / "obstruction_disagreement_cases.csv", index=False)
    assert Path(in_path).read_bytes() == in_bytes, "input was modified"

    result = {"t_bdr": t_bdr, "dis": dis, "sens": sens_df, "public": public, "mapping": mapping,
              "ob_rows": pd.DataFrame(ob_rows), "cohort": pd.DataFrame(cohort)}
    if verbose:
        print_summary(result, len(d), int(adults(d).sum()))
    return result


def print_summary(r: dict, n_all: int, n_adults: int) -> None:
    t = r["t_bdr"]
    n = t["n_classified"]
    print("PhysioBench Task 6 summary (unweighted NHANES sample counts; not prevalence estimates)")
    print(f"Participants {n_all:,}; adults {n_adults:,}; primary BDR-eligible adults {n}")
    print(f"\nGINA vs ERS/ATS (n={n}):  both+ {t['n_both_pos']}  GINA-only {t['n_first_only']}  "
          f"ERS/ATS-only {t['n_second_only']}  both- {t['n_both_neg']}")
    print(f"  GINA+ {t['n_first_pos']}/{n}  ERS/ATS+ {t['n_second_pos']}/{n}  "
          f"agreement {t['observed_agreement']:.3f}  kappa {t['cohens_kappa']:.3f}")
    print("  disagreement causes:")
    for (dirn, cat), k in r["dis"].groupby(["direction", "cause_category"]).size().items():
        print(f"    {dirn:<15} {k:>3}  {cat}")
    ob = r["ob_rows"]
    for pop in ("adults_assessable_any_grade", "adults_pre_grades_AB"):
        s = ob[(ob.section == "fixed_vs_lln") & (ob.population == pop) &
               (ob.metric != "marginal_positive")].set_index("metric")

        def cnt(m):
            return int(s.loc[m, "count"])
        print(f"\nObstruction fixed<0.70 vs <LLN [{pop}] (n={int(s.loc['both_positive', 'denominator'])}): "
              f"both+ {cnt('both_positive')}  fixed-only {cnt('first_only_positive')}  "
              f"LLN-only {cnt('second_only_positive')}  both- {cnt('both_negative')}  "
              f"kappa {s.loc['cohens_kappa', 'value']:.3f}")
    print("\nSensitivity:")
    cols = ["comparison", "subset", "n_adults_in_scope", "n_included", "n_first_pos", "n_second_pos",
            "n_first_only", "n_second_only", "cohens_kappa"]
    print(r["sens"][cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"\nCandidates: {len(r['public'])} (IDs {r['public'].case_id.min()}-{r['public'].case_id.max()})")
    print(r["public"][["case_id", "selection_category"]].to_string(index=False))


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
