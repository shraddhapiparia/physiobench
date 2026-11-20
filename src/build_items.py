"""Task 8: build model-facing benchmark items and a separate grading key.

Inputs (read only):
  benchmark/item_specs.yaml        expert item specifications (Task 7)
  benchmark/prompt_template.txt    shared prompt template ($placeholders)
  config.yaml                      guideline thresholds (single source of truth)
  benchmark/candidate_cases.csv    Task 6 candidates, for cross-checking case data
Outputs:
  benchmark/items.jsonl            MODEL-FACING: prompt + response schema only
  grading/answer_key.jsonl         GRADING ONLY: gold labels, reasoning, errors, rubric
  grading/grading_review.md        GRADING ONLY: ten-item review table for expert sign-off
  benchmark/items_review.md        the ten prompts and schemas, for expert review
                                   (model-facing content only; regenerated from items.jsonl)

Model-visible prompts contain only case data, rule definitions, a neutral
question, and the response format. Spec fields that state or imply the answer
(title, capability, question_objective, gold, required_reasoning,
critical_errors, item_role, acceptable_clinical_qualifications,
formal_vs_clinical_interpretation) go only to the grading key. The model runner
must load items with load_public_items().

Usage: python3 src/build_items.py
"""

from __future__ import annotations

import json
import math
import re
import string
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bdr  # noqa: E402  (deterministic re-check of gold labels)

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "benchmark" / "item_specs.yaml"
TEMPLATE_PATH = REPO_ROOT / "benchmark" / "prompt_template.txt"
CANDIDATES_PATH = REPO_ROOT / "benchmark" / "candidate_cases.csv"
ITEMS_PATH = REPO_ROOT / "benchmark" / "items.jsonl"
KEY_PATH = REPO_ROOT / "grading" / "answer_key.jsonl"
GRADING_SPEC_PATH = REPO_ROOT / "benchmark" / "grading_spec.yaml"
REVIEW_PATH = REPO_ROOT / "benchmark" / "items_review.md"
GRADING_REVIEW_PATH = REPO_ROOT / "grading" / "grading_review.md"

# "family" is deliberately not public: names such as missing_bdr hint at the answer.
PUBLIC_KEYS = ("item_id", "benchmark_version", "prompt", "response_schema")

REQUIRED_ITEM_FIELDS = ("item_id", "source_candidate_id", "title", "capability", "question_objective",
                        "case_data", "gold", "required_reasoning", "critical_errors", "scoring", "draft_status")
# Expert scientific-qualification fields (grading only; never in prompts).
OPTIONAL_ITEM_FIELDS = ("item_role", "acceptable_clinical_qualifications", "formal_vs_clinical_interpretation")
TOP_LEVEL_FIELDS = ("benchmark_version", "purpose", "guideline_rules", "notes", "items", "interpretation_policy")
# Control role -> the overall label both guidelines must have (checked against gold).
ITEM_ROLES = {"concordant_negative_control": "negative", "concordant_positive_control": "positive"}
DEFAULT_ROLE = "challenge"
# A release version (X.Y.Z, no suffix) is a frozen benchmark: every item must be
# expert-approved and the rubric must carry the same version.
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+")
APPROVED_STATUS = "expert_approved"


def is_release(version) -> bool:
    return bool(RELEASE_VERSION.fullmatch(str(version)))
# formal_vs_clinical_interpretation labels -> gold pipeline_labels they must equal.
FORMAL_LABELS = {"formal_gina": "gina_bdr_status", "formal_ers_ats": "ers_ats_bdr_status",
                 "formal_fixed_ratio": "obstruction_fixed_ratio_adult", "formal_gli_lln": "obstruction_gli_lln"}
FVCI_TEXT_LISTS = ("accepted_clinical_qualifications", "not_accepted", "score_separately")
CASE_NUMERIC = ("age_years", "height_cm", "fev1_pre_L", "fvc_pre_L", "fev1fvc_pre_ratio",
                "gli_fev1_pred", "gli_fvc_pred", "gli_fev1fvc_lln")
CASE_POST = ("fev1_post_L", "fvc_post_L")
CASE_GRADES_PRE = ("SPXNQFV1", "SPXNQFVC")
CASE_GRADES_POST = ("SPXBQFV1", "SPXBQFVC")
CASE_FIELDS = CASE_NUMERIC + CASE_POST + CASE_GRADES_PRE + CASE_GRADES_POST + ("sex", "post_bd_exam_status")
GRADES = {"A", "B", "C", "D", "F"}
POST_STATUSES = {"complete", "partial", "not_done", "safety_exclusion", "not_applicable"}
LABEL_KEYS = {
    "gina_bdr_status": {"positive", "negative", "not_assessable", "not_applicable_pediatric"},
    "ers_ats_bdr_status": {"positive", "negative", "not_assessable"},
    "primary_bdr_eligible": {True, False},
    "obstruction_fixed_ratio_adult": {True, False, None},
    "obstruction_gli_lln": {True, False, None},
}
SCORING_KEYS = ("classification_and_calculation", "scientific_explanation", "limits_and_uncertainty")
# Spec label name -> column name in the pipeline output (src/bdr.py).
PIPELINE_COLUMN = {"gina_bdr_status": "gina_bdr_status", "ers_ats_bdr_status": "ats_ers_bdr_status",
                   "primary_bdr_eligible": "primary_bdr_eligible",
                   "obstruction_fixed_ratio_adult": "obstruction_fixed_ratio_adult",
                   "obstruction_gli_lln": "obstruction_gli_lln"}

# Item family decides which rules, question and answer fields a prompt gets.
FAMILY_BY_PREFIX = {"BDR": "bdr", "OBS": "obstruction"}
FAMILY_BY_CAPABILITY = {"quality_vs_computed_result": "quality", "missing_data_abstention": "missing_bdr"}

Q_BDR = ("Classify the bronchodilator response under GINA 2026 and under ERS/ATS 2022. Evaluate FEV1 and FVC "
         "separately for each guideline, then give each guideline's overall classification. Explain the "
         "physiological and methodological reasons the two guidelines agree or differ for this record.")
Q_OBS = ("Classify the baseline (pre-bronchodilator) FEV1/FVC with the fixed-ratio rule and with the GLI LLN "
         "rule, and explain why the two rules agree or differ for this record.")
QUESTIONS = {
    "bdr": {"primary": Q_BDR, "secondary": None},
    "obstruction": {"primary": Q_OBS,
                    "secondary": ("State the bronchodilator response classification under GINA 2026 and under "
                                  "ERS/ATS 2022, or not_assessable if it cannot be determined.")},
    "missing_bdr": {"primary": ("Determine whether bronchodilator responsiveness can be classified under GINA "
                                "2026 and under ERS/ATS 2022 from these data. Give each classification and "
                                "explain the basis for your determination."),
                    "secondary": ("Classify the baseline (pre-bronchodilator) FEV1/FVC with the fixed-ratio "
                                  "rule and with the GLI LLN rule.")},
    "quality": {"primary": ("Classify the bronchodilator response under GINA 2026 and under ERS/ATS 2022 (FEV1 "
                            "and FVC separately, then overall). Separately, determine whether this record meets "
                            "the primary-analysis eligibility rules, and explain how the two determinations "
                            "relate."),
                "secondary": None},
}

TRI = ["positive", "negative", "not_assessable"]
BDR_OVERALL = ["gina_2026_overall", "ers_ats_2022_overall"]
BDR_MEASURE = ["gina_2026_fev1", "gina_2026_fvc", "ers_ats_2022_fev1", "ers_ats_2022_fvc"]
OBSTRUCTION = ["fixed_ratio_obstruction", "gli_lln_obstruction"]
ELIGIBILITY = {"primary_analysis_eligibility": ["eligible", "not_eligible"]}
CHANGE_CALCS = [f"{m}_{k}" for m in ("fev1", "fvc")
                for k in ("change_mL", "change_pct_of_baseline", "change_pct_of_predicted")]
RATIO_CALCS = ["fev1fvc_pre_ratio", "fev1fvc_pre_minus_lln"]
# Primary fields carry classification points; secondary fields are recorded but
# earn no points (grading/answer_key + benchmark/grading_spec.yaml).
SCHEMAS = {
    "bdr": {"primary": BDR_OVERALL, "secondary": BDR_MEASURE, "extra": {}, "calculations": CHANGE_CALCS},
    "obstruction": {"primary": OBSTRUCTION, "secondary": BDR_OVERALL, "extra": {},
                    "calculations": RATIO_CALCS + CHANGE_CALCS},
    "missing_bdr": {"primary": BDR_OVERALL, "secondary": OBSTRUCTION, "extra": {},
                    "calculations": CHANGE_CALCS + RATIO_CALCS},
    "quality": {"primary": BDR_OVERALL + ["primary_analysis_eligibility"], "secondary": BDR_MEASURE,
                "extra": ELIGIBILITY, "calculations": CHANGE_CALCS},
}


def classification_values(family: str) -> dict:
    s = SCHEMAS[family]
    names = [n for n in BDR_MEASURE[:2] + ["gina_2026_overall"] + BDR_MEASURE[2:] + ["ers_ats_2022_overall"]
             + OBSTRUCTION + list(ELIGIBILITY) if n in s["primary"] + s["secondary"]]
    return {n: s["extra"].get(n, TRI) for n in names}

OP_SYMBOL = {">=": "≥", ">": ">", "<": "<", "<=": "≤"}
GRADE_LEGEND = ("A exceeds ATS standards; B meets ATS standards; C potentially usable but does not meet "
                "all ATS standards; D questionable; F not valid")


class SpecError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Loading and validation
# --------------------------------------------------------------------------- #
def load_yaml(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def family_of(item: dict) -> str:
    prefix = item["item_id"].split("-")[0]
    fam = FAMILY_BY_PREFIX.get(prefix) or FAMILY_BY_CAPABILITY.get(item.get("capability"))
    if fam is None:
        raise SpecError(f"{item['item_id']}: no item family for prefix {prefix!r} / capability "
                        f"{item.get('capability')!r}")
    return fam


def to_ml(litres: float, where: str) -> float:
    """Litres with 3 decimals -> exact integer mL (NHANES records whole mL)."""
    ml = litres * 1000
    if abs(ml - round(ml)) > 1e-6:
        raise SpecError(f"{where}: {litres} L is not a whole number of mL")
    return float(round(ml))


def validate_specs(spec: dict, cfg: dict) -> None:
    """Raise SpecError listing every problem found."""
    errs = []
    for k in ("benchmark_version", "guideline_rules", "items"):
        if k not in spec:
            errs.append(f"top level: missing {k!r}")
    unknown_top = sorted(set(spec) - set(TOP_LEVEL_FIELDS))
    if unknown_top:
        errs.append(f"top level: unknown fields {unknown_top} (add them to TOP_LEVEL_FIELDS deliberately)")
    items = spec.get("items") or []
    if not items:
        errs.append("no items")
    rules = " ".join(str(v) for v in (spec.get("guideline_rules") or {}).values())
    g, a = cfg["bdr"]["gina"], cfg["bdr"]["ats_ers"]
    for token in (f"{g['pct_baseline']['threshold']}%", f"{g['abs_change_ml']['threshold']} mL",
                  f"{a['pct_predicted']['threshold']}%", f"{cfg['obstruction']['fixed_ratio']['fev1_fvc']['threshold']:.2f}"):
        if token not in rules:
            errs.append(f"guideline_rules text does not mention {token!r} (config.yaml)")

    ids = [it.get("item_id") for it in items]
    srcs = [it.get("source_candidate_id") for it in items]
    for name, vals in (("item_id", ids), ("source_candidate_id", srcs)):
        dup = sorted({v for v in vals if vals.count(v) > 1})
        if dup:
            errs.append(f"duplicate {name}: {dup}")
    totals = set()
    for it in items:
        iid = it.get("item_id", "<missing id>")
        missing = [f for f in REQUIRED_ITEM_FIELDS if f not in it or it[f] in (None, "", [], {})]
        if missing:
            errs.append(f"{iid}: missing fields {missing}")
            continue
        unknown = sorted(set(it) - set(REQUIRED_ITEM_FIELDS) - set(OPTIONAL_ITEM_FIELDS))
        if unknown:
            errs.append(f"{iid}: unknown fields {unknown} (would be silently ignored by grading)")
        errs += validate_qualification_fields(it)
        if not re.fullmatch(r"[A-Z]+-\d{2}", iid):
            errs.append(f"{iid}: item_id must look like ABC-01")
        if not re.fullmatch(r"PB\d{3}", it["source_candidate_id"]):
            errs.append(f"{iid}: source_candidate_id must look like PB001")
        try:
            family_of(it)
        except SpecError as e:
            errs.append(str(e))
        c = it["case_data"]
        miss = [f for f in CASE_FIELDS if f not in c]
        extra = [f for f in c if f not in CASE_FIELDS]
        if miss or extra:
            errs.append(f"{iid}: case_data missing {miss}, unexpected {extra}")
            continue
        for f in CASE_NUMERIC:
            v = c[f]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0:
                errs.append(f"{iid}: case_data.{f} must be a positive finite number, got {v!r}")
        for f in CASE_POST:
            v = c[f]
            if v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0):
                errs.append(f"{iid}: case_data.{f} must be null or a positive finite number, got {v!r}")
        for f in CASE_GRADES_PRE:
            if c[f] not in GRADES:
                errs.append(f"{iid}: case_data.{f} must be one of A-F, got {c[f]!r}")
        for f in CASE_GRADES_POST:
            if c[f] is not None and c[f] not in GRADES:
                errs.append(f"{iid}: case_data.{f} must be null or A-F, got {c[f]!r}")
        if c["sex"] not in ("male", "female"):
            errs.append(f"{iid}: case_data.sex must be male/female")
        if c["post_bd_exam_status"] not in POST_STATUSES:
            errs.append(f"{iid}: unknown post_bd_exam_status {c['post_bd_exam_status']!r}")
        for v, gr in zip(CASE_POST, CASE_GRADES_POST):
            if (c[v] is None) != (c[gr] is None):
                errs.append(f"{iid}: {v} and {gr} must both be present or both null")
        if c["post_bd_exam_status"] in ("complete", "partial") and None in (c["fev1_post_L"], c["fvc_post_L"]):
            errs.append(f"{iid}: post-BD status {c['post_bd_exam_status']} but post values missing")
        if c["post_bd_exam_status"] not in ("complete", "partial") and c["fev1_post_L"] is not None:
            errs.append(f"{iid}: post-BD values present but status {c['post_bd_exam_status']}")
        try:
            for f in ("fev1_pre_L", "fvc_pre_L") + CASE_POST:
                if c[f] is not None:
                    to_ml(c[f], f"{iid}.{f}")
            if abs(c["fev1fvc_pre_ratio"] - c["fev1_pre_L"] / c["fvc_pre_L"]) > 1e-12:
                errs.append(f"{iid}: fev1fvc_pre_ratio does not equal fev1_pre_L / fvc_pre_L")
        except (SpecError, TypeError) as e:
            errs.append(str(e))
        gold = it["gold"]
        if not gold.get("summary"):
            errs.append(f"{iid}: gold.summary missing")
        labels = gold.get("pipeline_labels") or {}
        for k, allowed in LABEL_KEYS.items():
            if k not in labels:
                errs.append(f"{iid}: gold.pipeline_labels.{k} missing")
            elif labels[k] not in allowed:
                errs.append(f"{iid}: gold.pipeline_labels.{k}={labels[k]!r} not in {sorted(map(str, allowed))}")
        for f in ("required_reasoning", "critical_errors"):
            if not isinstance(it[f], list) or not all(isinstance(x, str) and x.strip() for x in it[f]):
                errs.append(f"{iid}: {f} must be a non-empty list of strings")
        sc = it["scoring"]
        if sorted(sc) != sorted(SCORING_KEYS):
            errs.append(f"{iid}: scoring keys {sorted(sc)} != {sorted(SCORING_KEYS)}")
        elif not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in sc.values()):
            errs.append(f"{iid}: scoring values must be positive integers")
        else:
            totals.add(sum(sc.values()))
    if len(totals) > 1:
        errs.append(f"rubric totals differ between items: {sorted(totals)}")
    if is_release(spec.get("benchmark_version")):
        drafts = [it.get("item_id") for it in items if it.get("draft_status") != APPROVED_STATUS]
        if drafts:
            errs.append(f"release {spec['benchmark_version']}: draft_status must be {APPROVED_STATUS!r} for {drafts}")
    if errs:
        raise SpecError("item_specs.yaml is invalid:\n  - " + "\n  - ".join(errs))


def _text_list(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, str) and x.strip() for x in v)


def validate_qualification_fields(it: dict) -> list:
    """item_role, acceptable_clinical_qualifications and formal_vs_clinical_interpretation.

    Formal labels and control roles must agree with gold; nothing here changes gold.
    """
    iid, errs = it["item_id"], []
    labels = (it.get("gold") or {}).get("pipeline_labels") or {}
    role = it.get("item_role")
    if role is not None:
        if role not in ITEM_ROLES:
            errs.append(f"{iid}: item_role {role!r} not in {sorted(ITEM_ROLES)}")
        else:
            want = ITEM_ROLES[role]
            got = (labels.get("gina_bdr_status"), labels.get("ers_ats_bdr_status"), labels.get("primary_bdr_eligible"))
            if got != (want, want, True):
                errs.append(f"{iid}: item_role {role} needs gold GINA and ERS/ATS {want} and primary_bdr_eligible "
                            f"true; gold has {got}")
    if "acceptable_clinical_qualifications" in it and not _text_list(it["acceptable_clinical_qualifications"]):
        errs.append(f"{iid}: acceptable_clinical_qualifications must be a non-empty list of strings")
    f = it.get("formal_vs_clinical_interpretation")
    if f is not None:
        if not isinstance(f, dict) or not f:
            return errs + [f"{iid}: formal_vs_clinical_interpretation must be a non-empty mapping"]
        unknown = sorted(set(f) - set(FORMAL_LABELS) - set(FVCI_TEXT_LISTS) - {"reason"})
        if unknown:
            errs.append(f"{iid}: formal_vs_clinical_interpretation has unknown fields {unknown}")
        for fk, lk in FORMAL_LABELS.items():
            if fk in f and lk in labels:
                gold = labels[lk] if isinstance(labels[lk], str) else TRI_LABEL[labels[lk]]
                if f[fk] != gold:
                    errs.append(f"{iid}: formal_vs_clinical_interpretation.{fk}={f[fk]!r} but gold {lk} is {gold!r}")
        for k in FVCI_TEXT_LISTS:
            if k in f and not _text_list(f[k]):
                errs.append(f"{iid}: formal_vs_clinical_interpretation.{k} must be a non-empty list of strings")
        if "reason" in f and not (isinstance(f["reason"], str) and f["reason"].strip()):
            errs.append(f"{iid}: formal_vs_clinical_interpretation.reason must be a string")
    return errs


def clinical_qualifications(it: dict) -> list:
    """Expert-accepted clinical qualifications from the item spec, in spec order."""
    f = it.get("formal_vs_clinical_interpretation") or {}
    return list(it.get("acceptable_clinical_qualifications") or []) + list(f.get("accepted_clinical_qualifications") or [])


def merged_qualifications(gi: dict, it: dict) -> list:
    """grading_spec acceptable_qualifications followed by expert clinical ones (deduplicated)."""
    out = []
    for q in list(gi.get("acceptable_qualifications") or []) + clinical_qualifications(it):
        if q not in out:
            out.append(q)
    return out


# --------------------------------------------------------------------------- #
# Deterministic checks of gold labels
# --------------------------------------------------------------------------- #
def case_frame(c: dict, cfg: dict) -> pd.DataFrame:
    def ml(v):
        return float("nan") if v is None else to_ml(v, "case")

    def ab(gr):
        return pd.NA if gr is None else gr in cfg["quality"]["acceptable_grades"]

    row = dict(SEQN=0, is_adult=c["age_years"] >= cfg["population"]["adult_min_age_years"],
               SPXNFEV1=ml(c["fev1_pre_L"]), SPXBFEV1=ml(c["fev1_post_L"]),
               SPXNFVC=ml(c["fvc_pre_L"]), SPXBFVC=ml(c["fvc_post_L"]),
               gli_fev1_pred=c["gli_fev1_pred"], gli_fvc_pred=c["gli_fvc_pred"],
               gli_fev1fvc_lln=c["gli_fev1fvc_lln"],
               fev1_pre_grade_AB=ab(c["SPXNQFV1"]), fvc_pre_grade_AB=ab(c["SPXNQFVC"]),
               fev1_post_grade_AB=ab(c["SPXBQFV1"]), fvc_post_grade_AB=ab(c["SPXBQFVC"]))
    return pd.DataFrame([row])


def _label(v):
    if v is pd.NA or (isinstance(v, float) and math.isnan(v)):
        return None
    return bool(v) if isinstance(v, (bool,)) or str(type(v)).endswith("bool_'>") else v


def recompute(c: dict, cfg: dict) -> dict:
    """Labels and unrounded calculations recomputed by src/bdr.py from case_data alone."""
    r = bdr.classify(case_frame(c, cfg), cfg).iloc[0]
    labels = {k: _label(r[col]) for k, col in PIPELINE_COLUMN.items()}
    calcs = {}
    for m in ("fev1", "fvc"):
        for src, dst in (("bd_change_ml", "change_mL"), ("bd_change_pct_baseline", "change_pct_of_baseline"),
                         ("bd_change_pct_pred", "change_pct_of_predicted")):
            v = r[f"{m}_{src}"]
            calcs[f"{m}_{dst}"] = None if pd.isna(v) else float(v)
    calcs["fev1fvc_pre_ratio"] = float(r["fev1fvc_pre_ratio"])
    calcs["fev1fvc_pre_minus_lln"] = float(r["fev1fvc_pre_ratio"] - c["gli_fev1fvc_lln"])
    comps = {f"{g}_{m}": _label(r[f"{col}_{m}_only"])
             for g, col in (("gina_2026", "gina"), ("ers_ats_2022", "ats_ers")) for m in ("fev1", "fvc")}
    return {"labels": labels, "calculations": calcs, "components": comps}


def check_gold(spec: dict, cfg: dict) -> None:
    errs = []
    for it in spec["items"]:
        got = recompute(it["case_data"], cfg)["labels"]
        for k, v in it["gold"]["pipeline_labels"].items():
            if got[k] != v:
                errs.append(f"{it['item_id']}: gold {k}={v!r} but src/bdr.py gives {got[k]!r}")
    if errs:
        raise SpecError("gold labels disagree with the deterministic pipeline:\n  - " + "\n  - ".join(errs))


def check_candidates(spec: dict, path: Path) -> None:
    if not path.is_file():
        raise SpecError(f"{path} not found; rebuild it with `python3 src/summarize.py` (Task 6)")
    cand = pd.read_csv(path).set_index("case_id")
    errs = []
    for it in spec["items"]:
        cid = it["source_candidate_id"]
        if cid not in cand.index:
            errs.append(f"{it['item_id']}: {cid} not in {path.name}")
            continue
        row = cand.loc[cid]
        for k, v in it["case_data"].items():
            cv = row[k]
            same = pd.isna(cv) if v is None else (
                not pd.isna(cv) and (float(cv) == float(v) if isinstance(v, (int, float)) else str(cv) == str(v)))
            if not same:
                errs.append(f"{it['item_id']}: case_data.{k}={v!r} but {cid} has {cv!r}")
        for k, col in PIPELINE_COLUMN.items():
            gv, cv = it["gold"]["pipeline_labels"][k], row[col]
            if str(gv).lower() != str(None if pd.isna(cv) else cv).lower():
                errs.append(f"{it['item_id']}: gold {k}={gv!r} but {cid} has {cv!r}")
    if errs:
        raise SpecError("item_specs.yaml disagrees with candidate_cases.csv:\n  - " + "\n  - ".join(errs))


# --------------------------------------------------------------------------- #
# Prompt rendering
# --------------------------------------------------------------------------- #
def fmt(v, unit=""):
    """Exact value as written in the spec (no rounding); whole numbers without '.0' for age."""
    if v is None:
        return "not available"
    return f"{v!r}{(' ' + unit) if unit else ''}"


POST_STATUS_TEXT = {"complete": "completed", "partial": "partially completed",
                    "not_done": "not performed", "safety_exclusion": "not performed (safety exclusion)",
                    "not_applicable": "not performed (not selected for bronchodilator testing)"}


def render_case(c: dict) -> str:
    age = int(c["age_years"]) if float(c["age_years"]).is_integer() else c["age_years"]
    lines = [
        "Participant",
        f"- Age: {age} years (recorded in whole years)",
        f"- Sex: {c['sex']}",
        f"- Standing height: {fmt(c['height_cm'], 'cm')}",
        "",
        "Spirometry (pre = before bronchodilator; post = after bronchodilator)",
        f"- Post-bronchodilator test: {POST_STATUS_TEXT[c['post_bd_exam_status']]}",
        f"- FEV1 pre: {fmt(c['fev1_pre_L'], 'L')}",
        f"- FEV1 post: {fmt(c['fev1_post_L'], 'L')}",
        f"- FVC pre: {fmt(c['fvc_pre_L'], 'L')}",
        f"- FVC post: {fmt(c['fvc_post_L'], 'L')}",
        f"- FEV1/FVC pre (unrounded): {fmt(c['fev1fvc_pre_ratio'])}",
        "",
        "Reference values (GLI Global 2022, race-neutral; unrounded)",
        f"- Predicted FEV1: {fmt(c['gli_fev1_pred'], 'L')}",
        f"- Predicted FVC: {fmt(c['gli_fvc_pred'], 'L')}",
        f"- Lower limit of normal (LLN) for FEV1/FVC: {fmt(c['gli_fev1fvc_lln'])}",
        "",
        f"Measurement quality grades ({GRADE_LEGEND})",
        f"- FEV1 pre: {c['SPXNQFV1']}",
        f"- FVC pre: {c['SPXNQFVC']}",
        f"- FEV1 post: {c['SPXBQFV1'] or 'not available'}",
        f"- FVC post: {c['SPXBQFVC'] or 'not available'}",
    ]
    return "\n".join(lines)


def render_rules(family: str, cfg: dict) -> str:
    g, a = cfg["bdr"]["gina"], cfg["bdr"]["ats_ers"]
    adult = cfg["population"]["adult_min_age_years"]
    gp, gm, ap = g["pct_baseline"], g["abs_change_ml"], a["pct_predicted"]
    out = [
        f"GINA {g['version']} bronchodilator responsiveness (adults, age ≥{adult} years)",
        "- For each measurement (FEV1, FVC), change = post − pre.",
        f"- A measurement is positive if its change is {OP_SYMBOL[gp['operator']]}{gp['threshold']}% of that "
        f"same measurement's pre-bronchodilator value AND {OP_SYMBOL[gm['operator']]}{gm['threshold']} mL. "
        "Both conditions must be met by the same measurement.",
        "",
        f"ERS/ATS {a['version']} bronchodilator responsiveness",
        f"- A measurement is positive if its change (post − pre) is {OP_SYMBOL[ap['operator']]}"
        f"{ap['threshold']}% of that same measurement's predicted value (GLI Global 2022).",
        "",
        "Overall classification for each guideline",
        "- positive if FEV1 or FVC is positive; negative only if both FEV1 and FVC can be assessed and both "
        "are negative; otherwise not_assessable.",
    ]
    if family in ("obstruction", "missing_bdr"):
        fr = cfg["obstruction"]["fixed_ratio"]["fev1_fvc"]
        out += ["",
                "Baseline FEV1/FVC classifications (pre-bronchodilator values)",
                f"- Fixed ratio: positive if FEV1/FVC {OP_SYMBOL[fr['operator']]} {fr['threshold']:.2f}.",
                f"- GLI LLN: positive if FEV1/FVC {OP_SYMBOL[cfg['obstruction']['lln']['fev1_fvc']['operator']]} "
                "the participant's GLI Global 2022 lower limit of normal for FEV1/FVC."]
    if family == "quality":
        grades = "/".join(cfg["quality"]["acceptable_grades"])
        out += ["",
                "Primary-analysis eligibility (applies to the record, not to the physiology)",
                f"- Eligible only if all of the following hold: age ≥{adult} years; pre- and post-bronchodilator "
                "FEV1 and FVC are available, finite and greater than zero; the quality grades for pre FEV1, pre "
                f"FVC, post FEV1 and post FVC are all {grades}; GLI predicted FEV1 and FVC are available.",
                "- Otherwise not_eligible.",
                "- A computed bronchodilator classification is determined separately from eligibility."]
    return "\n".join(out)


def render_question(family: str) -> str:
    q = QUESTIONS[family]
    if q["secondary"] is None:
        return q["primary"]
    return f"Primary question: {q['primary']}\nSecondary question: {q['secondary']}"


def render_response(family: str) -> str:
    s = SCHEMAS[family]
    skeleton = {
        "classifications": {k: " | ".join(v) for k, v in classification_values(family).items()},
        "calculations": {k: "number (unrounded) or null if it cannot be computed" for k in s["calculations"]},
        "physiological_explanation": "string",
        "limitations": "string",
    }
    return json.dumps(skeleton, indent=2, ensure_ascii=False)


def response_schema(family: str) -> dict:
    s = SCHEMAS[family]
    return {"classifications": {k: list(v) for k, v in classification_values(family).items()},
            "calculations": list(s["calculations"]),
            "text_fields": ["physiological_explanation", "limitations"]}


# --------------------------------------------------------------------------- #
# Grading specification (benchmark/grading_spec.yaml)
# --------------------------------------------------------------------------- #
def tolerance_for(name: str, tolerances: dict) -> float:
    for suffix, tol in tolerances.items():
        if name == suffix or name.endswith("_" + suffix):
            return float(tol)
    raise SpecError(f"no tolerance defined for calculation {name!r}")


# Critical-error flags may change only these criteria. Classification and
# calculation credit is scored against gold and tolerances alone.
FLAG_CRITERIA = ("scientific_explanation", "limits_and_uncertainty")


def validate_grading(spec: dict, g: dict) -> None:
    errs = []
    for k in ("rubric_version", "total_points", "criteria", "numeric_policy", "tolerances",
              "clinical_interpretation_policy", "severity_levels", "critical_error_policy", "combination_rule",
              "items"):
        if k not in g:
            errs.append(f"grading_spec: missing {k!r}")
    if errs:
        raise SpecError("grading_spec.yaml is invalid:\n  - " + "\n  - ".join(errs))
    crit = g["criteria"]
    if sorted(crit) != sorted(SCORING_KEYS):
        errs.append(f"criteria {sorted(crit)} != {sorted(SCORING_KEYS)}")
    else:
        if sum(c["points"] for c in crit.values()) != g["total_points"]:
            errs.append("criteria points do not sum to total_points")
        cc = crit["classification_and_calculation"]
        if sum(c["points"] for c in cc["components"].values()) != cc["points"]:
            errs.append("classification_and_calculation components do not sum to its points")
        anchored = [(n, c) for n, c in crit.items() if n != "classification_and_calculation"] + list(cc["components"].items())
        for name, c in anchored:
            if sorted(c.get("anchors", {})) != list(range(c["points"] + 1)):
                errs.append(f"{name}: anchors must cover every score 0..{c['points']}")
    if is_release(spec.get("benchmark_version")) and str(g["rubric_version"]) != str(spec["benchmark_version"]):
        errs.append(f"release {spec['benchmark_version']}: rubric_version must equal it (got {g['rubric_version']!r})")
    severities = set(g["severity_levels"])
    ids = [it["item_id"] for it in spec["items"]]
    if sorted(g["items"]) != sorted(ids):
        errs.append(f"grading_spec items {sorted(g['items'])} != item_specs items {sorted(ids)}")
    for it in spec["items"]:
        iid, gi = it["item_id"], g["items"].get(it["item_id"])
        if gi is None:
            continue
        fam = family_of(it)
        s = SCHEMAS[fam]
        prim, sec = list(gi.get("primary_classifications", [])), list(gi.get("secondary_classifications", []))
        promoted = prim[len(s["primary"]):]
        if prim[:len(s["primary"])] != s["primary"] or not set(promoted) <= set(s["secondary"]) \
                or len(set(promoted)) != len(promoted):
            errs.append(f"{iid}: primary_classifications must be {s['primary']} for family {fam}, "
                        f"optionally followed by fields promoted from {s['secondary']}")
        elif sec != [f for f in s["secondary"] if f not in promoted]:
            errs.append(f"{iid}: secondary_classifications must be the family's secondary fields "
                        f"minus promoted ones: {[f for f in s['secondary'] if f not in promoted]}")
        esl = gi.get("expert_summary_labels") or {}
        if set(esl) != set(promoted):
            errs.append(f"{iid}: promoted primary fields {promoted} need expert_summary_labels "
                        f"(got {sorted(esl)})")
        er = gi.get("explanation_requirements", [])
        if not isinstance(er, list) or not all(isinstance(x, str) and x.strip() for x in er):
            errs.append(f"{iid}: explanation_requirements must be a list of strings")
        kc = gi.get("key_calculations") or []
        if not kc or len(set(kc)) != len(kc) or not set(kc) <= set(s["calculations"]):
            errs.append(f"{iid}: key_calculations must be unique names from {s['calculations']}")
        for name in kc:
            try:
                tolerance_for(name, g["tolerances"])
            except SpecError as e:
                errs.append(f"{iid}: {e}")
        aq = gi.get("acceptable_qualifications")
        if aq is not None and not _text_list(aq):
            errs.append(f"{iid}: acceptable_qualifications must be a non-empty list of strings when given")
        elif not merged_qualifications(gi, it):
            errs.append(f"{iid}: no acceptable_qualifications (grading_spec) or clinical qualifications (item_specs)")
        ce = gi.get("critical_errors") or {}
        if set(ce) != set(it["critical_errors"]):
            errs.append(f"{iid}: critical_errors keys must match item_specs critical_errors exactly "
                        f"(missing {sorted(set(it['critical_errors']) - set(ce))}, "
                        f"unknown {sorted(set(ce) - set(it['critical_errors']))})")
        for desc, e in ce.items():
            if not isinstance(e, dict) or set(e) != {"severity", "affects"}:
                errs.append(f"{iid}: {desc!r} must have exactly 'severity' and 'affects'")
                continue
            if e["severity"] not in severities:
                errs.append(f"{iid}: {desc!r} has unknown severity {e['severity']!r}")
            for c, op in (e["affects"] or {}).items():
                if c not in FLAG_CRITERIA:
                    errs.append(f"{iid}: {desc!r} may not change {c!r}; flags affect only {FLAG_CRITERIA}")
                    continue
                pts = crit[c]["points"]
                if not (isinstance(op, dict) and len(op) == 1 and set(op) <= {"max", "deduct"}
                        and isinstance(next(iter(op.values())), int)
                        and 0 <= next(iter(op.values())) <= pts):
                    errs.append(f"{iid}: {desc!r} consequence for {c} must be {{max: n}} or {{deduct: n}}, 0..{pts}")
        for crit_name, pts in it["scoring"].items():
            if crit_name in crit and crit[crit_name]["points"] != pts:
                errs.append(f"{iid}: scoring.{crit_name}={pts} but rubric gives {crit[crit_name]['points']}")
    if errs:
        raise SpecError("grading_spec.yaml is invalid:\n  - " + "\n  - ".join(errs))


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
TRI_LABEL = {True: "positive", False: "negative", None: "not_assessable"}


def expert_labels(labels: dict) -> dict:
    """Expert gold (item_specs pipeline_labels) in response-field vocabulary."""
    return {"gina_2026_overall": labels["gina_bdr_status"], "ers_ats_2022_overall": labels["ers_ats_bdr_status"],
            "fixed_ratio_obstruction": TRI_LABEL[labels["obstruction_fixed_ratio_adult"]],
            "gli_lln_obstruction": TRI_LABEL[labels["obstruction_gli_lln"]],
            "primary_analysis_eligibility": "eligible" if labels["primary_bdr_eligible"] else "not_eligible"}


def gold_for(fields: list, expert: dict, components: dict, summary_labels: dict | None = None) -> dict:
    """expert_gold: item_specs pipeline_labels. expert_summary: a label stated in
    the expert gold summary (grading_spec expert_summary_labels), which must equal
    the pipeline value. pipeline_reference: derived by src/bdr.py only."""
    summary_labels = summary_labels or {}
    out = {}
    for f in fields:
        if f in expert:
            out[f] = {"value": expert[f], "source": "expert_gold"}
        elif f in summary_labels:
            if summary_labels[f] != components[f]:
                raise SpecError(f"expert_summary_labels {f}={summary_labels[f]!r} disagrees with "
                                f"src/bdr.py ({components[f]!r}); gold is not changed automatically")
            out[f] = {"value": summary_labels[f], "source": "expert_summary"}
        else:
            out[f] = {"value": components[f], "source": "pipeline_reference"}
    return out


def build(spec: dict, template: str, cfg: dict, grading: dict) -> tuple[list, list]:
    tpl = string.Template(template)
    items, keys = [], []
    for it in spec["items"]:
        fam = family_of(it)
        prompt = tpl.substitute(case_block=render_case(it["case_data"]), rules_block=render_rules(fam, cfg),
                                question=render_question(fam), response_format=render_response(fam))
        items.append({"item_id": it["item_id"], "benchmark_version": spec["benchmark_version"],
                      "prompt": prompt, "response_schema": response_schema(fam)})
        ref = recompute(it["case_data"], cfg)
        components = {k: TRI_LABEL[v] for k, v in ref["components"].items()}
        expert = expert_labels(it["gold"]["pipeline_labels"])
        gi = grading["items"][it["item_id"]]
        keys.append({
            "item_id": it["item_id"], "benchmark_version": spec["benchmark_version"], "family": fam,
            "rubric_version": grading["rubric_version"],
            "source_candidate_id": it["source_candidate_id"], "title": it["title"],
            "capability": it["capability"], "question_objective": it["question_objective"],
            "gold_primary_classifications": gold_for(gi["primary_classifications"], expert, components,
                                                     gi.get("expert_summary_labels")),
            "gold_secondary_classifications": gold_for(gi["secondary_classifications"], expert, components),
            "gold": it["gold"],
            "key_calculations": [{"name": n, "expected": ref["calculations"][n],
                                  "tolerance": tolerance_for(n, grading["tolerances"])}
                                 for n in gi["key_calculations"]],
            "reference_components": components,          # pipeline-derived, not expert gold
            "reference_calculations": ref["calculations"],
            "required_reasoning": it["required_reasoning"],
            "explanation_requirements": gi.get("explanation_requirements", []),
            "acceptable_qualifications": merged_qualifications(gi, it),
            "item_role": it.get("item_role", DEFAULT_ROLE),
            "clinical_interpretation": {
                "acceptable_clinical_qualifications": clinical_qualifications(it),
                "formal_vs_clinical_interpretation": it.get("formal_vs_clinical_interpretation"),
            },
            "interpretation_policy": spec.get("interpretation_policy"),
            "critical_errors": [{"description": e, "severity": gi["critical_errors"][e]["severity"],
                                 "affects": gi["critical_errors"][e]["affects"] or {}}
                                for e in it["critical_errors"]],
            "scoring": it["scoring"], "rubric_total": sum(it["scoring"].values()),
            "draft_status": it["draft_status"],
        })
    return items, keys


def dumps_jsonl(records: list) -> str:
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)


def render_review(items: list) -> str:
    """Markdown copy of the model-facing items for expert review. Built from the
    public records only, so it cannot contain grading content."""
    out = ["# PhysioBench model-facing items (review copy)", "",
           "Generated by `python3 src/build_items.py` from `benchmark/items.jsonl`; do not edit by hand.",
           "Contains only what a model is shown (prompt) and the response schema. No answers or scoring content.",
           "Item IDs are listed for reviewers; they are not part of the prompt.", ""]
    for r in items:
        out += [f"## {r['item_id']}", "", f"Benchmark version: `{r['benchmark_version']}`", "",
                "### Prompt", "", "````text", r["prompt"].rstrip("\n"), "````", "",
                "### Response schema", "", "```json",
                json.dumps(r["response_schema"], indent=2, sort_keys=True, ensure_ascii=False), "```", ""]
    return "\n".join(out)


def _cell(v) -> str:
    return str(v).replace("|", "\\|").replace("\n", " ")


def render_grading_review(keys: list) -> str:
    """GRADING-ONLY review table (gitignored): every item's capability, gold,
    scoring requirements and acceptable clinical qualifications."""
    def labels(d):
        return "; ".join(f"{f}={v['value']}" + ("" if v["source"] == "expert_gold" else f" ({v['source']})")
                         for f, v in d.items())
    out = ["# PhysioBench grading review (GRADING ONLY - do not publish)", "",
           "Generated by `python3 src/build_items.py` from the answer key; do not edit by hand.",
           f"Benchmark version `{keys[0]['benchmark_version']}`, rubric `{keys[0]['rubric_version']}`, "
           f"{len(keys)} items. Every item is scored out of {keys[0]['rubric_total']} "
           "(classification_and_calculation 4: primary classifications 2 + key calculations 2; "
           "scientific_explanation 3; limits_and_uncertainty 1). Critical-error flags are recorded separately.", "",
           "## Summary", "",
           "| Item | Source | Role | Primary capability | Primary classifications (scored) | "
           "Secondary (recorded, 0 points) | Key calculations |",
           "|---|---|---|---|---|---|---|"]
    for k in keys:
        calcs = ", ".join(f"{c['name']}={'null' if c['expected'] is None else format(c['expected'], '.6g')}"
                          for c in k["key_calculations"])
        out.append("| " + " | ".join(_cell(x) for x in (
            k["item_id"], k["source_candidate_id"], k["item_role"], k["capability"],
            labels(k["gold_primary_classifications"]), labels(k["gold_secondary_classifications"]), calcs)) + " |")
    for k in keys:
        out += ["", f"## {k['item_id']} - {k['title']}", "",
                f"- Role: `{k['item_role']}`; capability: `{k['capability']}`; family: `{k['family']}`",
                f"- Objective: {k['question_objective']}",
                f"- Gold summary: {k['gold']['summary']}", "",
                "Scoring requirements (scientific_explanation):", ""]
        out += [f"- {r}" for r in k["required_reasoning"] + k["explanation_requirements"]]
        out += ["", "Acceptable qualifications (limits_and_uncertainty):", ""]
        out += [f"- {q}" for q in k["acceptable_qualifications"]]
        f = k["clinical_interpretation"]["formal_vs_clinical_interpretation"]
        if f:
            formal = {fk: f[fk] for fk in FORMAL_LABELS if fk in f}
            out += ["", "Formal vs clinical interpretation:", ""]
            if formal:
                out.append("- Formal labels (unrounded; checked against gold): "
                           + ", ".join(f"{a}={b}" for a, b in formal.items()))
            if f.get("reason"):
                out.append(f"- Reason: {f['reason']}")
            out += [f"- Not accepted: {x}" for x in f.get("not_accepted", [])]
            out += [f"- Score separately: {x}" for x in f.get("score_separately", [])]
        out += ["", "Critical errors (recorded independently):", ""]
        for e in k["critical_errors"]:
            eff = ", ".join(f"{c} {next(iter(op))} {next(iter(op.values()))}" for c, op in e["affects"].items()) \
                or "recorded only"
            out.append(f"- [{e['severity']}] {e['description']} -> {eff}")
    return "\n".join(out) + "\n"


def load_public_items(path: Path = ITEMS_PATH) -> list:
    """The only loader a model runner may use. Refuses the grading key and any
    record carrying fields beyond the public set."""
    path = Path(path).resolve()
    if path == KEY_PATH.resolve() or "grading" in path.parts:
        raise PermissionError(f"refusing to load grading data for model input: {path}")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in records:
        extra = set(r) - set(PUBLIC_KEYS)
        if extra:
            raise ValueError(f"{r.get('item_id')}: non-public fields in model-facing item: {sorted(extra)}")
    return records


def main(spec_path=SPEC_PATH, template_path=TEMPLATE_PATH, candidates_path=CANDIDATES_PATH,
         items_path=ITEMS_PATH, key_path=KEY_PATH, config_path=bdr.CONFIG_PATH,
         grading_path=GRADING_SPEC_PATH, review_path=REVIEW_PATH, grading_review_path=GRADING_REVIEW_PATH,
         verbose=True) -> int:
    cfg = bdr.load_config(config_path)
    spec = load_yaml(spec_path)
    grading = load_yaml(grading_path)
    validate_specs(spec, cfg)
    validate_grading(spec, grading)
    check_gold(spec, cfg)
    check_candidates(spec, Path(candidates_path))
    items, keys = build(spec, Path(template_path).read_text(), cfg, grading)
    Path(items_path).write_text(dumps_jsonl(items))
    Path(key_path).parent.mkdir(parents=True, exist_ok=True)
    Path(key_path).write_text(dumps_jsonl(keys))
    Path(review_path).write_text(render_review(items))
    Path(grading_review_path).parent.mkdir(parents=True, exist_ok=True)
    Path(grading_review_path).write_text(render_grading_review(keys))
    if verbose:
        print(f"Validated {len(items)} specs (fields, IDs, case data, rubric totals; gold labels re-derived "
              f"by src/bdr.py; case data matches {Path(candidates_path).name}).")
        for i, k in zip(items, keys):
            primary = {f: v["value"] for f, v in k["gold_primary_classifications"].items()}
            print(f"  {i['item_id']:<8} {k['source_candidate_id']}  family={k['family']:<12} primary gold={primary}")
        print(f"Wrote {Path(items_path).relative_to(REPO_ROOT)} (model-facing) and "
              f"{Path(key_path).relative_to(REPO_ROOT)} (grading only).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SpecError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
