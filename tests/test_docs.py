"""Documentation check (offline): links, anchors and commands in public Markdown.

Every relative link must point to an existing file, every #anchor to a heading
in the target, and every `python3 <script>` / `Rscript <script>` command to an
existing script. External links are checked for form only (no network).
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "examples/README.md", "benchmark/README.md", "data/README.md", "docs/methodology.md"]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
CMD = re.compile(r"\b(?:python3(?: -I)?|Rscript)\s+((?:src|examples|tests)/[\w./-]+\.(?:py|R))")


def slug(heading: str) -> str:
    """GitHub-style heading anchor."""
    s = re.sub(r"[`*_]", "", heading.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(path: Path) -> set:
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", text, flags=re.M)}


class TestDocs(unittest.TestCase):
    def test_docs_exist(self):
        for d in DOCS:
            self.assertTrue((REPO / d).is_file(), d)

    def test_relative_links_and_anchors(self):
        problems = []
        for d in DOCS:
            src = REPO / d
            for target in LINK.findall(src.read_text()):
                if re.match(r"[a-z]+://", target) or target.startswith("mailto:"):
                    if not target.startswith("https://"):
                        problems.append(f"{d}: non-https link {target}")
                    continue
                path, _, frag = target.partition("#")
                dest = (src.parent / path).resolve() if path else src
                if not dest.exists():
                    problems.append(f"{d}: missing {target}")
                elif frag and dest.suffix == ".md" and frag not in anchors(dest):
                    problems.append(f"{d}: no heading for #{frag} in {dest.relative_to(REPO)}")
        self.assertEqual(problems, [])

    def test_commands_reference_existing_scripts(self):
        problems = []
        for d in DOCS:
            for script in CMD.findall((REPO / d).read_text()):
                if not (REPO / script).is_file():
                    problems.append(f"{d}: {script}")
        self.assertEqual(problems, [])

    def test_readme_does_not_claim_results(self):
        text = (REPO / "README.md").read_text().lower()
        self.assertIn("no model has been run", text)
        for claim in ("leaderboard results", "achieves", "outperforms", "accuracy of", "% accuracy"):
            self.assertNotIn(claim, text)


if __name__ == "__main__":
    unittest.main()
