"""Publication audit: private benchmark content must not reach the public repo.

PUBLIC test file. It contains no private content itself: sensitive strings are
read at run time from the private files and searched for in every file Git
would publish (tracked, staged, or untracked and not ignored). The content scan
skips when the private files are absent (e.g. in a public clone).
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import build_items as bi  # noqa: E402

REPO = bi.REPO_ROOT
PRIVATE = [
    "benchmark/item_specs.yaml",                    # expert specs incl. gold
    "benchmark/grading_spec.yaml",                  # rubric anchors, qualifications, error severities
    "benchmark/candidate_cases.csv",                # participant-level candidates
    "benchmark/items.jsonl",                        # real-case prompts (model-facing but private)
    "benchmark/items_review.md",                    # review copy of the prompts
    "benchmark/control_selection.md",               # control selection record (SEQN)
    "benchmark/version_manifest.json",              # private freeze manifest
    "grading/answer_key.jsonl",                     # gold answers
    "grading/grading_review.md",                    # gold review table
    "grading/manual_scores.csv",                    # per-item scores (reveal gold indirectly)
    "data/processed/candidate_seqn_mapping.csv",    # case ID <-> NHANES SEQN
    "data/processed/benchmark_controls.csv",        # control registry (SEQN)
    "data/processed/concordant_candidates_review.csv",
    "tests/private/test_gold_private.py",           # gold-specific tests
    "tests/private/test_control_selection.py",      # control selection rules (SEQN)
]
MIN_LEN = 20          # shorter strings are too generic to indicate a leak


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


def in_git_repo() -> bool:
    return subprocess.run(["git", "rev-parse"], cwd=REPO, capture_output=True).returncode == 0


def publishable_files() -> list:
    """Tracked + staged + untracked-not-ignored files (what `git add -A` would publish)."""
    names = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")) - {""}
    deleted = set(git("ls-files", "--deleted", "-z").split("\0"))
    staged_removed = set(git("diff", "--cached", "--name-only", "--diff-filter=D", "-z").split("\0"))
    return sorted(n for n in names - deleted - staged_removed if (REPO / n).is_file())


def sensitive_strings() -> dict:
    """label -> set of private strings, read from the private files."""
    out = {"gold/grading text": set(), "SEQN": set(), "real-case value": set()}
    spec = bi.load_yaml(bi.SPEC_PATH)
    grading = bi.load_yaml(bi.GRADING_SPEC_PATH)

    def add(v):
        if isinstance(v, str):
            for part in re.split(r"\s*\n\s*", v.strip()):
                if len(part) >= MIN_LEN:
                    out["gold/grading text"].add(part)
        elif isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
    for it in spec["items"]:
        for f in ("title", "question_objective", "gold", "required_reasoning", "critical_errors",
                  "acceptable_clinical_qualifications", "formal_vs_clinical_interpretation"):
            add(it.get(f))
    for it in spec["items"]:      # unrounded reference values and ratios identify the real cases
        for v in it["case_data"].values():
            if isinstance(v, float) and len(repr(v)) >= 8:
                out["real-case value"].add(repr(v))
    for gi in grading["items"].values():
        add(gi.get("acceptable_qualifications"))
        add(gi.get("explanation_requirements"))
        add(list((gi.get("critical_errors") or {}).keys()))
    for p in (REPO / "data/processed/candidate_seqn_mapping.csv", REPO / "data/processed/benchmark_controls.csv"):
        if p.is_file():
            import csv
            with open(p) as fh:
                out["SEQN"] |= {r["SEQN"] for r in csv.DictReader(fh)}
    return out


@unittest.skipUnless(in_git_repo(), "not a git checkout")
class TestReleaseProtection(unittest.TestCase):
    def test_private_paths_are_gitignored(self):
        for path in PRIVATE:
            r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=REPO)
            self.assertEqual(r.returncode, 0, f"{path} is not gitignored")

    def test_private_paths_not_tracked_or_staged(self):
        index = set(git("ls-files", "--cached", "-z").split("\0"))
        staged = set(git("diff", "--cached", "--name-only", "--diff-filter=AMR", "-z").split("\0"))
        for path in PRIVATE:
            self.assertNotIn(path, staged, f"{path} is staged for commit")
            # A staged removal (git rm --cached) leaves it in neither set below.
            self.assertFalse(path in index and (REPO / path).is_file()
                             and path not in git("diff", "--cached", "--name-only", "--diff-filter=D"),
                             f"{path} is tracked; run `git rm --cached {path}`")

    @unittest.skipUnless(bi.SPEC_PATH.is_file() and bi.GRADING_SPEC_PATH.is_file(), "private specs not available")
    def test_no_private_content_in_publishable_files(self):
        secrets = sensitive_strings()
        self.assertTrue(secrets["gold/grading text"])
        leaks = []
        for name in publishable_files():
            p = REPO / name
            if p.stat().st_size > 2_000_000:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            flat = re.sub(r"\s+", " ", text)
            for s in secrets["gold/grading text"]:
                if re.sub(r"\s+", " ", s) in flat:
                    leaks.append(f"{name}: gold/grading text {s[:60]!r}")
            for seqn in secrets["SEQN"]:
                if re.search(rf"(?<![\w.]){seqn}(?![\w.])", text):
                    leaks.append(f"{name}: candidate SEQN")
            for v in secrets["real-case value"]:
                if re.search(rf"(?<![\w.]){re.escape(v)}(?!\d)", text):
                    leaks.append(f"{name}: real-case value {v}")
        self.assertEqual(leaks, [], "private content in publishable files:\n" + "\n".join(leaks))

    def test_public_manifest_has_no_private_hashes(self):
        m = REPO / "docs" / "release_manifest.json"
        if not m.is_file():
            self.skipTest("public manifest not written")
        text = m.read_text()
        import hashlib
        for path in PRIVATE:
            p = REPO / path
            if p.is_file():
                self.assertNotIn(hashlib.sha256(p.read_bytes()).hexdigest(), text, f"hash of {path} in public manifest")
        self.assertNotIn("frozen_private_files", text)
        self.assertNotIn("item_sources", text)

    @unittest.skipUnless(bi.ITEMS_PATH.is_file(), "items not built")
    def test_model_facing_files_have_no_grading_fields(self):
        for line in bi.ITEMS_PATH.read_text().splitlines():
            self.assertEqual(set(json.loads(line)), set(bi.PUBLIC_KEYS))


if __name__ == "__main__":
    unittest.main()
