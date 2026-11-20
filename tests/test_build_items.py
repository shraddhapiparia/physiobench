"""Tests for src/build_items.py (Task 8): structure, determinism and leakage.

PUBLIC test file: it must not contain gold answers, critical-error wording or
expected calculations for any item. Item-specific gold checks live in the
gitignored tests/private/ suite. Everything item-specific here is read
dynamically from the private specs, and the tests skip when those are absent
(e.g. in a public clone).
"""

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import bdr  # noqa: E402
import build_items as bi  # noqa: E402

REPO = bi.REPO_ROOT
HAVE_SPECS = bi.SPEC_PATH.is_file() and bi.GRADING_SPEC_PATH.is_file()
SPEC = bi.load_yaml(bi.SPEC_PATH) if HAVE_SPECS else None
GRADING = bi.load_yaml(bi.GRADING_SPEC_PATH) if HAVE_SPECS else None
CFG = bdr.load_config()
HAVE_CANDIDATES = bi.CANDIDATES_PATH.is_file()
N_ITEMS = 10
# Model-visible text must never mention why an item was chosen or what it is.
ROLE_WORDS = ("control", "concordant", "challenge", "sanity", "expected classification")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def first_item(pred):
    return next(i for i, it in enumerate(SPEC["items"]) if pred(it))


@unittest.skipUnless(HAVE_SPECS, "private item/grading specs not available")
class TestSpecValidation(unittest.TestCase):
    def test_current_spec_is_valid(self):
        bi.validate_specs(SPEC, CFG)
        bi.check_gold(SPEC, CFG)

    def assertSpecError(self, spec, fragment):
        with self.assertRaises(bi.SpecError) as cm:
            bi.validate_specs(spec, CFG)
            bi.check_gold(spec, CFG)
        self.assertIn(fragment, str(cm.exception))

    def test_duplicate_item_id(self):
        s = copy.deepcopy(SPEC)
        s["items"][1]["item_id"] = s["items"][0]["item_id"]
        self.assertSpecError(s, "duplicate item_id")

    def test_duplicate_source_candidate(self):
        s = copy.deepcopy(SPEC)
        s["items"][-1]["source_candidate_id"] = s["items"][0]["source_candidate_id"]
        self.assertSpecError(s, "duplicate source_candidate_id")

    def test_missing_field(self):
        s = copy.deepcopy(SPEC)
        del s["items"][2]["critical_errors"]
        self.assertSpecError(s, "missing fields ['critical_errors']")

    def test_missing_case_measurement(self):
        s = copy.deepcopy(SPEC)
        del s["items"][0]["case_data"]["gli_fev1_pred"]
        self.assertSpecError(s, "case_data missing ['gli_fev1_pred']")

    def test_inconsistent_rubric_total(self):
        s = copy.deepcopy(SPEC)
        s["items"][3]["scoring"]["scientific_explanation"] = 5
        self.assertSpecError(s, "rubric totals differ")

    def test_any_flipped_gold_label_is_caught(self):
        flip = {"positive": "negative", "negative": "positive", "not_assessable": "positive",
                True: False, False: True, None: True, "not_applicable_pediatric": "positive"}
        for i, it in enumerate(SPEC["items"]):
            for k, v in it["gold"]["pipeline_labels"].items():
                s = copy.deepcopy(SPEC)
                s["items"][i]["gold"]["pipeline_labels"][k] = flip[v]
                with self.assertRaises(bi.SpecError, msg=f"{it['item_id']}.{k}"):
                    bi.validate_specs(s, CFG)
                    bi.check_gold(s, CFG)

    def test_post_value_without_grade(self):
        s = copy.deepcopy(SPEC)
        i = first_item(lambda it: it["case_data"]["fev1_post_L"] is not None)
        s["items"][i]["case_data"]["SPXBQFV1"] = None
        self.assertSpecError(s, "must both be present or both null")

    def test_ratio_must_match_measurements(self):
        s = copy.deepcopy(SPEC)
        s["items"][0]["case_data"]["fev1fvc_pre_ratio"] = 0.6
        self.assertSpecError(s, "fev1fvc_pre_ratio does not equal")

    def test_unknown_item_field_rejected(self):
        s = copy.deepcopy(SPEC)
        s["items"][0]["acceptable_qualificatons"] = ["typo must not be silently ignored"]
        self.assertSpecError(s, "unknown fields ['acceptable_qualificatons']")

    def test_unknown_top_level_field_rejected(self):
        s = copy.deepcopy(SPEC)
        s["interpretation_polcy"] = {}
        self.assertSpecError(s, "top level: unknown fields")

    def test_item_role_must_be_known_and_match_gold(self):
        i = first_item(lambda it: "item_role" in it)
        s = copy.deepcopy(SPEC)
        s["items"][i]["item_role"] = "random_control"
        self.assertSpecError(s, "item_role 'random_control' not in")
        s = copy.deepcopy(SPEC)
        other = next(r for r in bi.ITEM_ROLES if r != SPEC["items"][i]["item_role"])
        s["items"][i]["item_role"] = other
        self.assertSpecError(s, f"item_role {other} needs gold")

    def test_formal_label_must_match_gold(self):
        i = first_item(lambda it: any(k in (it.get("formal_vs_clinical_interpretation") or {})
                                      for k in bi.FORMAL_LABELS))
        f = SPEC["items"][i]["formal_vs_clinical_interpretation"]
        k = next(k for k in bi.FORMAL_LABELS if k in f)
        s = copy.deepcopy(SPEC)
        s["items"][i]["formal_vs_clinical_interpretation"][k] = \
            "positive" if f[k] != "positive" else "negative"
        self.assertSpecError(s, f"formal_vs_clinical_interpretation.{k}=")

    def test_qualification_lists_must_be_text(self):
        i = first_item(lambda it: "acceptable_clinical_qualifications" in it)
        s = copy.deepcopy(SPEC)
        s["items"][i]["acceptable_clinical_qualifications"] = []
        self.assertSpecError(s, "acceptable_clinical_qualifications must be a non-empty list")

    def test_release_requires_expert_approval(self):
        s = copy.deepcopy(SPEC)
        s["benchmark_version"] = "9.9.9"
        for it in s["items"]:
            it["draft_status"] = bi.APPROVED_STATUS
        bi.validate_specs(s, CFG)                                   # all approved: valid
        s["items"][0]["draft_status"] = "expert_review_required"
        self.assertSpecError(s, "release 9.9.9: draft_status must be 'expert_approved'")

    def test_release_rubric_version_must_match(self):
        if not bi.is_release(SPEC["benchmark_version"]):
            self.skipTest("spec is not a release")
        g = copy.deepcopy(GRADING)
        g["rubric_version"] = "0.0.1-draft"
        with self.assertRaises(bi.SpecError) as cm:
            bi.validate_grading(SPEC, g)
        self.assertIn("rubric_version must equal", str(cm.exception))

    @unittest.skipUnless(HAVE_CANDIDATES, "benchmark/candidate_cases.csv not built")
    def test_case_data_must_match_candidates(self):
        s = copy.deepcopy(SPEC)
        s["items"][0]["case_data"]["height_cm"] += 1.0
        with self.assertRaises(bi.SpecError) as cm:
            bi.check_candidates(s, bi.CANDIDATES_PATH)
        self.assertIn(f"{s['items'][0]['item_id']}: case_data.height_cm=", str(cm.exception))


@unittest.skipUnless(HAVE_SPECS and HAVE_CANDIDATES, "private specs or candidate_cases.csv not available")
class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        watched = sorted((REPO / "data" / "processed").glob("*.csv")) + [
            bi.SPEC_PATH, bi.CANDIDATES_PATH, bdr.CONFIG_PATH, bi.TEMPLATE_PATH, bi.GRADING_SPEC_PATH]
        cls.before = {p: md5(p) for p in watched}
        cls.runs = []
        for i in (1, 2):
            paths = {"items_path": t / f"items{i}.jsonl", "key_path": t / f"key{i}.jsonl",
                     "review_path": t / f"review{i}.md", "grading_review_path": t / f"grading_review{i}.md"}
            bi.main(verbose=False, **paths)
            cls.runs.append(paths)
        cls.after = {p: md5(p) for p in watched}
        cls.items = [json.loads(line) for line in cls.runs[0]["items_path"].read_text().splitlines()]
        cls.keys = [json.loads(line) for line in cls.runs[0]["key_path"].read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exactly_ten_items_with_unique_ids(self):
        self.assertEqual(len(self.items), N_ITEMS)
        ids = [r["item_id"] for r in self.items]
        self.assertEqual(len(set(ids)), N_ITEMS)
        self.assertEqual(ids, [it["item_id"] for it in SPEC["items"]])     # spec order kept
        self.assertEqual(len(self.keys), N_ITEMS)

    def test_byte_identical_and_matches_committed_output(self):
        r1, r2 = self.runs
        current = {"items_path": bi.ITEMS_PATH, "key_path": bi.KEY_PATH, "review_path": bi.REVIEW_PATH,
                   "grading_review_path": bi.GRADING_REVIEW_PATH}
        for name, path in current.items():
            self.assertEqual(r1[name].read_bytes(), r2[name].read_bytes(), f"{name} not deterministic")
            self.assertEqual(r1[name].read_bytes(), path.read_bytes(), f"{path.name} is stale")

    def test_review_file_has_every_prompt_and_no_grading_content(self):
        review = self.runs[0]["review_path"].read_text()
        for r in self.items:
            self.assertIn(r["prompt"].rstrip("\n"), review)
        for k in self.keys:
            for text in self.grading_texts(k):
                self.assertNotIn(text, review, f"{k['item_id']}: grading text in review file")
        for word in ("severity", "rubric", "gold", "primary_classifications") + ROLE_WORDS:
            self.assertNotIn(word, review.lower())

    @staticmethod
    def grading_texts(k):
        f = k["clinical_interpretation"]["formal_vs_clinical_interpretation"] or {}
        return ([k["title"], k["question_objective"], k["gold"]["summary"], k["capability"]]
                + k["required_reasoning"] + k["acceptable_qualifications"] + k["explanation_requirements"]
                + [e["description"] for e in k["critical_errors"]]
                + ([f["reason"]] if "reason" in f else []) + f.get("not_accepted", []) + f.get("score_separately", []))

    def test_grading_review_covers_every_item(self):
        g = self.runs[0]["grading_review_path"].read_text()
        self.assertIn("GRADING ONLY", g)
        for k in self.keys:
            self.assertIn(f"## {k['item_id']} - ", g)
            for q in k["acceptable_qualifications"] + k["required_reasoning"]:
                self.assertIn(q.replace("\n", " "), g)

    def test_source_to_item_mapping(self):
        expected = {it["item_id"]: it["source_candidate_id"] for it in SPEC["items"]}
        self.assertEqual({k["item_id"]: k["source_candidate_id"] for k in self.keys}, expected)
        self.assertEqual([k["item_id"] for k in self.keys], [r["item_id"] for r in self.items])

    def test_public_items_have_only_public_fields(self):
        for r in self.items:
            self.assertEqual(set(r), set(bi.PUBLIC_KEYS))

    def test_no_gold_leakage(self):
        for r, it, k in zip(self.items, SPEC["items"], self.keys):
            text = json.dumps(r, ensure_ascii=False)
            forbidden = self.grading_texts(k) + [it["source_candidate_id"],
                         "required_reasoning", "critical_errors", "acceptable_qualifications", "item_role",
                         "formal_vs_clinical", "clinical_qualifications", "pipeline_labels", "gold", "severity",
                         "rubric"]
            for f in forbidden:
                self.assertNotIn(f, text, f"{r['item_id']} leaks {f!r}")
            for w in ROLE_WORDS:
                self.assertNotIn(w, text.lower(), f"{r['item_id']} reveals selection/role ({w!r})")
            # Expected calculations, as a grader would write them, must not appear
            # as standalone numbers (the pre-BD ratio itself is input data). The
            # RULES section is excluded: it prints the guideline thresholds
            # (e.g. 200 mL), which can equal a case's value without leaking it.
            pre, rest = r["prompt"].split("\nRULES\n", 1)
            searched = pre + rest.split("\nQUESTION\n", 1)[1]
            for name, v in k["reference_calculations"].items():
                if v is None or name == "fev1fvc_pre_ratio":
                    continue
                if name.endswith("change_mL"):
                    forms = [f"{v:+.0f}", f"{abs(v):.0f} mL"]
                elif name == "fev1fvc_pre_minus_lln":
                    forms = [f"{v:.6f}", f"{abs(v):.6f}", f"{abs(v):.4f}"]
                else:
                    forms = [f"{v:.2f}", f"{v:.1f}%"]
                for s in forms:
                    pattern = rf"(?<![\d.]){re.escape(s)}(?![\d])"
                    self.assertIsNone(re.search(pattern, searched), f"{r['item_id']} leaks {name} as {s!r}")
            # The rules section itself must be identical text for items of the same family.
            self.assertEqual(rest.split("\nQUESTION\n", 1)[0].strip().split("\n\nGeneral conventions")[0],
                             bi.render_rules(k["family"], CFG))

    def test_same_family_items_differ_only_in_case_data(self):
        """Controls and challenge items in one family get identical rules, question and schema."""
        by_family = {}
        for r, k in zip(self.items, self.keys):
            by_family.setdefault(k["family"], []).append(r)
        for fam, rs in by_family.items():
            tails = {r["prompt"].split("\nRULES\n", 1)[1] for r in rs}
            self.assertEqual(len(tails), 1, f"family {fam}: prompts differ outside the participant data")
            self.assertEqual(len({json.dumps(r["response_schema"], sort_keys=True) for r in rs}), 1)

    def test_input_precision_preserved(self):
        for r, it in zip(self.items, SPEC["items"]):
            for f in bi.CASE_NUMERIC + bi.CASE_POST:
                v = it["case_data"][f]
                if v is None or f == "age_years":
                    continue
                self.assertIn(repr(v), r["prompt"], f"{r['item_id']}.{f}")

    def test_missing_post_values_rendered_as_not_available(self):
        by_id = {r["item_id"]: r for r in self.items}
        for it in SPEC["items"]:
            block = by_id[it["item_id"]]["prompt"].split("PARTICIPANT DATA")[1].split("RULES")[0]
            for bad in ("None", "null", "nan", "NaN"):
                self.assertNotIn(bad, block)
            if it["case_data"]["fev1_post_L"] is None:
                self.assertIn("FEV1 post: not available", block)
                self.assertIn("FVC post: not available", block)

    def test_not_assessable_always_allowed(self):
        for r in self.items:
            for allowed in r["response_schema"]["classifications"].values():
                if "positive" in allowed:
                    self.assertIn("not_assessable", allowed)

    def test_rules_present_by_family(self):
        for r, k in zip(self.items, self.keys):
            p, fam = r["prompt"], k["family"]
            self.assertIn("≥12% of that same measurement's pre-bronchodilator value AND ≥200 mL", p)
            self.assertIn(">10% of that same measurement's predicted value", p)
            self.assertIn("Apply every threshold to unrounded values", p)
            self.assertEqual("Fixed ratio: positive if FEV1/FVC < 0.70" in p,
                             fam in ("obstruction", "missing_bdr"))
            self.assertEqual("Primary-analysis eligibility" in p, fam == "quality")
            self.assertEqual("Secondary question:" in p, fam in ("obstruction", "missing_bdr"))

    def test_family_not_public(self):
        for r in self.items:
            self.assertNotIn("family", r)
            # Family names must not appear as standalone values (field names such
            # as "fixed_ratio_obstruction" legitimately contain the word).
            for fam in ("bdr", "missing_bdr", "obstruction", "quality"):
                self.assertNotIn(f'"{fam}"', json.dumps(r))

    def test_item_id_not_in_prompt(self):
        for r in self.items:
            self.assertNotIn(r["item_id"], r["prompt"])
            self.assertNotIn("Item:", r["prompt"])

    def test_schema_consistent_with_family(self):
        for r, k in zip(self.items, self.keys):
            s = r["response_schema"]
            fields = set(s["classifications"])
            # Scoring weights are grading-only: the public schema does not say which fields are scored.
            self.assertNotIn("primary_classifications", s)
            self.assertNotIn("secondary_classifications", s)
            prim, sec = set(k["gold_primary_classifications"]), set(k["gold_secondary_classifications"])
            self.assertEqual(fields, prim | sec)
            self.assertFalse(prim & sec)
            for f in fields:      # every classification field is printed in the prompt skeleton
                self.assertIn(f'"{f}"', r["prompt"])
            for c in s["calculations"]:
                self.assertIn(f'"{c}"', r["prompt"])

    def test_answer_key_carries_qualification_fields(self):
        for k, it in zip(self.keys, SPEC["items"]):
            self.assertEqual(k["item_role"], it.get("item_role", bi.DEFAULT_ROLE))
            for q in bi.clinical_qualifications(it):
                self.assertIn(q, k["acceptable_qualifications"])
            self.assertEqual(k["clinical_interpretation"]["formal_vs_clinical_interpretation"],
                             it.get("formal_vs_clinical_interpretation"))
            self.assertEqual(k["interpretation_policy"], SPEC.get("interpretation_policy"))
            self.assertTrue(k["acceptable_qualifications"])

    def test_task_1_to_6_inputs_unchanged(self):
        self.assertEqual(self.before, self.after)


@unittest.skipUnless(HAVE_SPECS, "private item/grading specs not available")
class TestGradingSpecStructure(unittest.TestCase):
    """Validator behaviour, using whichever items and errors the private spec has."""

    def test_current_grading_spec_is_valid(self):
        bi.validate_grading(SPEC, GRADING)

    def assertGradingError(self, g, fragment):
        with self.assertRaises(bi.SpecError) as cm:
            bi.validate_grading(SPEC, g)
        self.assertIn(fragment, str(cm.exception))

    def any_error(self):
        iid = SPEC["items"][0]["item_id"]
        return iid, next(iter(GRADING["items"][iid]["critical_errors"]))

    def test_every_item_has_a_grading_entry(self):
        for iid in GRADING["items"]:
            g = copy.deepcopy(GRADING)
            del g["items"][iid]
            self.assertGradingError(g, "grading_spec items")

    def test_severity_must_cover_each_critical_error(self):
        iid, err = self.any_error()
        g = copy.deepcopy(GRADING)
        g["items"][iid]["critical_errors"].pop(err)
        self.assertGradingError(g, f"{iid}: critical_errors keys must match")

    def test_unknown_severity(self):
        iid, err = self.any_error()
        g = copy.deepcopy(GRADING)
        g["items"][iid]["critical_errors"][err]["severity"] = "fatal"
        self.assertGradingError(g, "unknown severity 'fatal'")

    def test_flag_may_not_remove_classification_or_calculation_credit(self):
        iid, err = self.any_error()
        for crit in ("primary_classifications", "key_calculations", "classification_and_calculation"):
            g = copy.deepcopy(GRADING)
            g["items"][iid]["critical_errors"][err]["affects"] = {crit: {"max": 0}}
            self.assertGradingError(g, "may not change")

    def test_flag_consequence_must_be_cap_or_deduction_in_range(self):
        iid, err = self.any_error()
        g = copy.deepcopy(GRADING)
        g["items"][iid]["critical_errors"][err]["affects"] = {"scientific_explanation": {"max": 7}}
        self.assertGradingError(g, "must be {max: n} or {deduct: n}")

    def test_anchors_must_cover_every_score(self):
        g = copy.deepcopy(GRADING)
        del g["criteria"]["scientific_explanation"]["anchors"][1]
        self.assertGradingError(g, "scientific_explanation: anchors must cover every score 0..3")

    def test_key_calculation_must_be_in_schema(self):
        iid = SPEC["items"][0]["item_id"]
        g = copy.deepcopy(GRADING)
        g["items"][iid]["key_calculations"] = ["not_a_calc"]
        self.assertGradingError(g, f"{iid}: key_calculations must be unique names")

    def test_primary_designation_must_match_family(self):
        iid = SPEC["items"][0]["item_id"]
        g = copy.deepcopy(GRADING)
        g["items"][iid]["primary_classifications"] = ["primary_analysis_eligibility"]
        self.assertGradingError(g, f"{iid}: primary_classifications must be")

    def test_clinical_interpretation_policy_required(self):
        g = copy.deepcopy(GRADING)
        del g["clinical_interpretation_policy"]
        self.assertGradingError(g, "clinical_interpretation_policy")

    def test_qualifications_required_from_one_source(self):
        i = first_item(lambda it: not bi.clinical_qualifications(it))
        iid = SPEC["items"][i]["item_id"]
        g = copy.deepcopy(GRADING)
        del g["items"][iid]["acceptable_qualifications"]
        self.assertGradingError(g, f"{iid}: no acceptable_qualifications")

    def test_rubric_is_eight_points(self):
        self.assertEqual(GRADING["total_points"], 8)
        for it in SPEC["items"]:
            self.assertEqual(sum(it["scoring"].values()), 8)

    def test_no_blanket_zero(self):
        for it in GRADING["items"].values():
            for e in it["critical_errors"].values():
                self.assertLessEqual(set(e["affects"] or {}), set(bi.FLAG_CRITERIA))


class TestPublicLoader(unittest.TestCase):
    def test_refuses_answer_key(self):
        with self.assertRaises(PermissionError):
            bi.load_public_items(bi.KEY_PATH)

    def test_refuses_records_with_key_fields(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "items.jsonl"
            p.write_text(json.dumps({"item_id": "X-01", "prompt": "p", "gold": {}}) + "\n")
            with self.assertRaises(ValueError):
                bi.load_public_items(p)

    @unittest.skipUnless(bi.ITEMS_PATH.is_file() and bi.ITEMS_PATH.stat().st_size, "items not built")
    def test_loads_model_facing_items(self):
        self.assertEqual(len(bi.load_public_items()), N_ITEMS)


if __name__ == "__main__":
    unittest.main()
