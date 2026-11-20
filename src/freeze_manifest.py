"""Freeze manifest for a PhysioBench release: write or check SHA-256 hashes.

Writes two JSON files (deterministic: sorted keys, no timestamps beyond the
fixed freeze date):
  benchmark/version_manifest.json      PRIVATE (gitignored): hashes of every frozen
                                       artifact, incl. prompts, specs, grading spec,
                                       answer key and the item -> candidate mapping
  docs/release_manifest.json           PUBLIC: version, environment, guideline
                                       sources, GLI implementation, data sources,
                                       generation commands, hashes of public inputs

The public manifest deliberately has no hashes of private files: the candidate
pool can be rebuilt from public code and NHANES data, so a hash of, say, the
SEQN mapping could be brute-forced to recover which participants were used.

Usage:
  python3 src/freeze_manifest.py           # write both manifests
  python3 src/freeze_manifest.py --check   # exit 1 if any frozen artifact changed
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PRIVATE_MANIFEST = REPO / "benchmark" / "version_manifest.json"
PUBLIC_MANIFEST = REPO / "docs" / "release_manifest.json"
FREEZE_DATE = "2026-11-20"

# Frozen artifacts: any change fails --check.
FROZEN_PRIVATE = {
    "prompts": "benchmark/items.jsonl",
    "expert_specifications": "benchmark/item_specs.yaml",
    "grading_specification": "benchmark/grading_spec.yaml",
    "answer_key": "grading/answer_key.jsonl",
    "prompt_review_copy": "benchmark/items_review.md",
    "grading_review": "grading/grading_review.md",
    "candidate_cases": "benchmark/candidate_cases.csv",
    "candidate_seqn_mapping": "data/processed/candidate_seqn_mapping.csv",
    "control_registry": "data/processed/benchmark_controls.csv",
    "control_selection_record": "benchmark/control_selection.md",
}
FROZEN_PUBLIC = {
    "prompt_template": "benchmark/prompt_template.txt",
    "guideline_config": "config.yaml",
}
# Generation code: recorded; a change is reported but does not fail --check
# (later tasks may edit code without changing the frozen artifacts).
GENERATION_CODE = ["src/download_nhanes.py", "src/prepare_spirometry.py", "src/gli_reference.R", "src/bdr.py",
                   "src/summarize.py", "src/build_items.py", "src/freeze_manifest.py"]
RAW_DATA = ["data/raw/SPX_G.xpt", "data/raw/DEMO_G.xpt", "data/raw/BMX_G.xpt"]

COMMANDS = [
    "python3 src/download_nhanes.py",
    "python3 src/prepare_spirometry.py",
    "Rscript src/gli_reference.R",
    "python3 src/bdr.py",
    "python3 src/summarize.py        # needs private data/processed/benchmark_controls.csv",
    "python3 src/build_items.py      # needs private benchmark/item_specs.yaml and grading_spec.yaml",
    "python3 src/freeze_manifest.py --check",
    "python3 -m unittest discover -s tests -v",
]
GUIDELINE_SOURCES = {
    "gina_2026": [
        "GINA 2026 Summary Guide, Table 1, p.8: 'Adults: FEV1 or FVC increases by >=12% and by >=200 mL from the "
        "pre-bronchodilator value'. https://ginasthma.org/wp-content/uploads/2026/07/GINA-Summary-Guide-2026-WEB-WMS.pdf",
        "GINA 2026 Strategy Report, Box 1-2, pp.28-29: 'Adults: increase from baseline in FEV1 or FVC of >=12% and "
        ">=200 mL'. https://ginasthma.org/wp-content/uploads/2026/05/GINA-2026-Strategy-Report-WMS.pdf",
    ],
    "ers_ats_2022": [
        "Stanojevic S et al. ERS/ATS technical standard on interpretive strategies for routine lung function tests. "
        "Eur Respir J 2022;60:2101499. doi:10.1183/13993003.01499-2021. Change in FEV1 or FVC >10% of predicted.",
    ],
    "gli_global_2022": [
        "Bowerman C et al. A race-neutral approach to the interpretation of lung function measurements. "
        "Am J Respir Crit Care Med 2023;207:768-774 (GLI Global 2022).",
    ],
}
GLI_IMPLEMENTATION = {
    "equations": "GLI Global 2022, race-neutral",
    "functions": "rspiro::pred_GLIgl, LLN_GLIgl, zscore_GLIgl (src/gli_reference.R)",
    "lln": "5th centile; rspiro uses z = -1.645",
    "age": "RIDAGEYR, whole years; rspiro looks up splines at floor(age*4)/4, exact for whole years; range 3-95",
    "height": "BMXHT / 100 (m); BMIHT = 3 retained and flagged height_not_straight",
    "sex": "RIAGENDR (1 = male, 2 = female)",
    "imputation": "none; predictions NA when age, sex or height unavailable",
    "validation": "Four reference cases (C1-C4) against the ERS GLI calculator (3 dp) and an independent Python "
                  "implementation from the GLI lookup workbook; max |difference| 3e-14 over all participants "
                  "with predictions (docs/methodology.md, Validation)",
}
DATA_SOURCES = {
    "survey": "NHANES 2011-2012 (cycle G), CDC public-use files; unweighted",
    "files": ["https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/SPX_G.xpt",
              "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/DEMO_G.xpt",
              "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2011/DataFiles/BMX_G.xpt"],
}


def sha256(rel: str) -> str | None:
    p = REPO / rel
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def hashes(paths) -> dict:
    items = paths.items() if isinstance(paths, dict) else ((p, p) for p in paths)
    return {name: {"path": rel, "sha256": sha256(rel)} for name, rel in items}


def environment() -> dict:
    import numpy
    import pandas
    try:
        r = subprocess.run(["Rscript", "-e", 'cat(R.version.string, "|", as.character(packageVersion("rspiro")))'],
                           capture_output=True, text=True, timeout=60)
        r_ver, rspiro = [x.strip() for x in r.stdout.split("|")] if r.returncode == 0 else ("unavailable",) * 2
    except (OSError, subprocess.TimeoutExpired, ValueError):
        r_ver, rspiro = "unavailable", "unavailable"
    return {"python": platform.python_version(), "pandas": pandas.__version__, "numpy": numpy.__version__,
            "pyyaml": yaml.__version__, "r": r_ver, "rspiro": rspiro,
            "platform": f"{platform.system()} {platform.release()} {platform.machine()}"}


def guideline_thresholds() -> dict:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text())
    g, a = cfg["bdr"]["gina"], cfg["bdr"]["ats_ers"]
    return {"gina": {"version": g["version"], "pct_baseline": g["pct_baseline"], "abs_change_ml": g["abs_change_ml"],
                     "measures": g["measures"], "population": g["population"]},
            "ers_ats": {"version": a["version"], "pct_predicted": a["pct_predicted"], "measures": a["measures"]},
            "fixed_ratio": cfg["obstruction"]["fixed_ratio"]["fev1_fvc"],
            "lln": cfg["obstruction"]["lln"]["reference"],
            "quality_grades": cfg["quality"]["acceptable_grades"],
            "adult_min_age_years": cfg["population"]["adult_min_age_years"]}


def frozen_facts() -> dict:
    spec = yaml.safe_load((REPO / "benchmark" / "item_specs.yaml").read_text())
    grading = yaml.safe_load((REPO / "benchmark" / "grading_spec.yaml").read_text())
    keys = [json.loads(l) for l in (REPO / "grading" / "answer_key.jsonl").read_text().splitlines()]
    items = [json.loads(l) for l in (REPO / "benchmark" / "items.jsonl").read_text().splitlines()]
    return {
        "benchmark_version": spec["benchmark_version"],
        "rubric_version": grading["rubric_version"],
        "item_versions": sorted({r["benchmark_version"] for r in items + keys}),
        "n_items": len(items),
        "roles": {k["item_id"]: k["item_role"] for k in keys},
        "item_sources": {it["item_id"]: it["source_candidate_id"] for it in spec["items"]},
        "draft_status": sorted({it["draft_status"] for it in spec["items"]}),
    }


def build() -> tuple[dict, dict]:
    f = frozen_facts()
    roles = list(f["roles"].values())
    public = {
        "benchmark": "PhysioBench", "benchmark_version": f["benchmark_version"],
        "rubric_version": f["rubric_version"], "freeze_date": FREEZE_DATE,
        "n_items": f["n_items"],
        "composition": {"challenge_items": roles.count("challenge"),
                        "bdr_controls": len(roles) - roles.count("challenge"),
                        "design": "purposively selected challenge set; not a representative sample",
                        "controls": "one concordant-negative and one concordant-positive BDR control, both selected "
                                    "retrospectively (not pre-registered); not healthy/normal-lung-function controls"},
        "rubric": "8 points per item (classification_and_calculation 4, scientific_explanation 3, "
                  "limits_and_uncertainty 1); critical-error flags recorded independently",
        "guideline_thresholds": guideline_thresholds(),
        "guideline_sources": GUIDELINE_SOURCES,
        "gli_implementation": GLI_IMPLEMENTATION,
        "data_sources": DATA_SOURCES,
        "raw_data_sha256": hashes(RAW_DATA),
        "frozen_public_files": hashes(FROZEN_PUBLIC),
        "generation_code_sha256": hashes(GENERATION_CODE),
        "environment": environment(),
        "generation_commands": COMMANDS,
        "private_artifacts": sorted(FROZEN_PRIVATE.values()),
    }
    private = {**public, "frozen_private_files": hashes(FROZEN_PRIVATE), "item_sources": f["item_sources"],
               "item_roles": f["roles"], "PRIVATE": "Do not publish: hashes and item-to-candidate mapping."}
    return public, private


def dumps(d: dict) -> str:
    return json.dumps(d, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def check(manifest_path: Path = PRIVATE_MANIFEST) -> tuple[list, list]:
    """(errors, warnings). Errors: a frozen artifact, version or mapping changed."""
    m = json.loads(Path(manifest_path).read_text())
    errs, warns = [], []
    for section in ("frozen_private_files", "frozen_public_files", "raw_data_sha256"):
        for name, e in m[section].items():
            now = sha256(e["path"])
            if now != e["sha256"]:
                errs.append(f"{e['path']} ({name}): sha256 {now} != frozen {e['sha256']}")
    f = frozen_facts()
    if f["item_versions"] != [m["benchmark_version"]] or f["benchmark_version"] != m["benchmark_version"]:
        errs.append(f"benchmark_version drift: spec {f['benchmark_version']}, items {f['item_versions']}")
    if f["item_sources"] != m["item_sources"]:
        errs.append(f"item -> source candidate mapping changed: {f['item_sources']} != {m['item_sources']}")
    if f["n_items"] != m["n_items"]:
        errs.append(f"item count {f['n_items']} != frozen {m['n_items']}")
    for name, e in m["generation_code_sha256"].items():
        if sha256(e["path"]) != e["sha256"]:
            warns.append(f"{e['path']}: generation code changed since freeze (re-run build and --check)")
    return errs, warns


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        errs, warns = check()
        for w in warns:
            print(f"WARNING: {w}")
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        print("frozen artifacts verified" if not errs else f"{len(errs)} frozen artifact(s) changed")
        return 1 if errs else 0
    public, private = build()
    PUBLIC_MANIFEST.write_text(dumps(public))
    PRIVATE_MANIFEST.write_text(dumps(private))
    print(f"Wrote {PUBLIC_MANIFEST.relative_to(REPO)} (public) and {PRIVATE_MANIFEST.relative_to(REPO)} (private)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
