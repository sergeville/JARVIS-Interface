"""The README's checkable claims, held to the code.

WHY THIS EXISTS. On 2026-08-21 the README carried three false statements at
once, and every one of them had been false for weeks:

  * It said "Three of those absolute paths point specifically at the vault"
    and tabled the exact lines they sat on -- `voice-web-server.py:88`, `:149`,
    `brief-check.py:70` -- forty lines after saying "Nothing in this repository
    contains an absolute path". Both cannot be true. The second one was.
  * It never mentioned the transcript feature at all, while `install.sh` wired
    a Stop hook that starts recording a stranger's conversations to disk the
    first time they run it.
  * It said the only username mentions left were "seven fictional fixtures in
    two test files". There were more than seven, in more than two files, and
    one of them was JavaScript. THIS ONE WAS FOUND BY WRITING THIS FILE.

The through-line is not carelessness. It is that **a document nothing runs is
a document nothing checks**, and every one of those claims was mechanically
checkable the whole time.

WHAT IT WILL NOT DO: read the prose. Nothing here has an opinion about whether
the README is well written, only about whether the things it points at exist
and the properties it promises hold.

AND THE RULE THE README NOW FOLLOWS, pinned by this file: state a PROPERTY, not
a hand-maintained count or a line number. A count goes stale the next time
anyone adds a fixture; a line number goes stale the next time anyone edits
above it. Neither can be enforced. "No shipping file carries an absolute home
path" can.
"""
import json
import re
import unittest
from pathlib import Path

# Self-locate: this file lives in <root>/Jarvis Visual/tests/
VISUAL = Path(__file__).resolve().parent.parent
ROOT = VISUAL.parent
README = ROOT / "README.md"

# Not part of the shipped tree: the vault (gitignored, and yours to write),
# live state, downloaded weights, and the tests' own fixtures.
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".scratch",
    "Jarvis-brain", "transcripts", "uploads", "archive", "references",
    "models", "services", "audio", "logs",
}

# Gitignored by suffix rather than by folder. `*.log` is written BY a running
# process, so of course it names absolute paths -- it is not shipped source
# and must not be read as if it were. This exclusion is the first thing this
# file got wrong about itself.
SKIP_SUFFIXES = {".log", ".pyc"}

# Notes the README tells a reader to CREATE. A fresh clone does not have them,
# by design -- the vault is the one part of this that is not in the repository.
VAULT_NOTES = {
    "VAULT-INDEX.md", "Active Priorities.md", "Session Board.md",
    "How to Start Jarvis.md", "Jarvis-brain/Active Priorities.md",
    "00 - Inbox/Inbox.md", "01 - Daily Notes/Daily Notes.md",
    "01 - Daily Notes/Daily Note Template.md", "02 - Learning AI/Learning AI.md",
}

# A backticked token worth resolving: it ends in an extension this repo uses.
# Deliberately narrow. A test that guesses at what looks like a path produces
# false reds, and an intermittent test is how this project lost an afternoon.
PATHY = re.compile(r"^[\w][\w./ -]*\.(py|js|sh|css|html|json|md|template|toml|lock)$")


def shipped_files():
    """Every file in the repository proper, as paths relative to ROOT."""
    out = []
    stack = [ROOT]
    while stack:
        d = stack.pop()
        for p in d.iterdir():
            if p.name in SKIP_DIRS or p.name.startswith("."):
                continue
            if p.is_dir():
                stack.append(p)
            elif p.is_file() and p.suffix not in SKIP_SUFFIXES:
                out.append(p.relative_to(ROOT))
    return out


class TestReadmeExists(unittest.TestCase):
    def test_the_readme_is_there_and_not_empty(self):
        # Everything below reads it. If this fails, the rest are vacuous
        # rather than passing -- which is the failure mode that made five
        # server assertions pass against a server that was not running.
        self.assertTrue(README.is_file(), "README.md is missing")
        self.assertGreater(len(README.read_text()), 5000,
                           "README.md is suspiciously short")


class TestNoAbsolutePaths(unittest.TestCase):
    """The README's central structural claim, and the reason it has no
    find-and-replace install step."""

    def test_no_shipping_file_carries_an_absolute_home_path(self):
        offenders = []
        for rel in shipped_files():
            # The tests are where the fictional fixtures live, by design --
            # they stand in for process command lines and settings payloads.
            if rel.parts[:2] == ("Jarvis Visual", "tests"):
                continue
            if rel.name == "README.md":
                continue     # it quotes the pattern in order to forbid it
            try:
                text = (ROOT / rel).read_text(errors="replace")
            except OSError:
                continue
            if "/Users/" in text:
                offenders.append(str(rel))
        self.assertEqual(offenders, [],
                         "README says nothing in this repository contains an "
                         "absolute path; these files do: " + ", ".join(offenders))

    def test_the_claim_is_a_property_and_not_a_count(self):
        # The version of this sentence that named "seven fictional fixtures in
        # two test files" was wrong on both counts, and nothing could have
        # caught it, because nobody can enforce a number typed into prose.
        # QUOTED TEXT IS NOT A CLAIM, and this test failed on its own fix for
        # exactly that reason. The corrected README quotes the stale sentence
        # in order to explain why it was wrong, and a bare substring search
        # cannot tell an assertion from a post-mortem of one.
        #
        # This project has now made that mistake seven times in different
        # files -- `"stdin" in src` flagging a hook whose rule says STDIN IS
        # NOT READ, and `!/urlopen/` flagging the comment that explains why
        # urlopen is gone. The rule is always the same: ask the structure,
        # not the substring. Here the structure is quotation.
        text = re.sub(r'["\u201c\u201d][^"\u201c\u201d]{0,200}["\u201c\u201d]',
                      " ", README.read_text())
        found = [s for s in ("seven fictional", "in two test files") if s in text]
        if found:
            self.fail("README pins a hand-maintained count "
                      f"({', '.join(repr(f) for f in found)}); state the "
                      "property instead -- a number typed into prose is a "
                      "number nothing can enforce")


class TestNoLineNumbersInTables(unittest.TestCase):
    """The exact defect fixed on 2026-08-21: a table naming `file` and `line`.

    A table naming a line number goes stale the next time anyone edits above
    that line, and nothing tells you. A table naming a file and what it reads
    cannot.
    """

    def test_no_table_row_pins_a_source_line_number(self):
        bad = []
        for i, line in enumerate(README.read_text().splitlines(), 1):
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            has_source = any(re.search(r"\.(py|js|sh|css|html)\b", c) for c in cells)
            has_bare_number = any(re.fullmatch(r"`?\d+`?", c) for c in cells)
            if has_source and has_bare_number:
                bad.append(f"{i}: {line.strip()}")
        self.assertEqual(bad, [],
                         "a README table pins a source line number, which goes "
                         "stale the next time anyone edits above it:\n" + "\n".join(bad))


class TestEveryPathItNamesResolves(unittest.TestCase):
    def test_every_backticked_repo_path_exists(self):
        names = {t for t in re.findall(r"`([^`\n]+)`", README.read_text())
                 if PATHY.match(t)}
        shipped = {str(p) for p in shipped_files()}
        missing = []
        for name in sorted(names):
            if name in VAULT_NOTES:
                continue          # yours to write; see step 6 of Install
            if name in shipped or any(s.endswith("/" + name) for s in shipped):
                continue
            missing.append(name)
        self.assertEqual(missing, [],
                         "the README names files that are not in the "
                         "repository: " + ", ".join(missing))

    def test_every_path_in_the_layout_block_exists(self):
        text = README.read_text()
        block = text.split("## Layout", 1)[1].split("```")[1]
        shipped = {str(p) for p in shipped_files()}
        dirs = {str(p.parent) for p in shipped_files()}
        missing = []
        parent = ""
        parent_absent = False
        for line in block.splitlines():
            if not line.strip():
                continue
            token = re.split(r"\s{2,}", line.strip())[0]
            if not token:
                continue
            indented = line.startswith(" ")
            if indented:
                target = parent + token
            else:
                target = token
                parent = token if token.endswith("/") else ""
                parent_absent = "not in git" in line
            target = target.rstrip("/")
            if not target or target in VAULT_NOTES:
                continue
            # Named in the block precisely as NOT in git -- the vault, the
            # weights, Kokoro, the transcripts. The block says so on the line.
            #
            # AND THE MARK HAS TO INHERIT. `Jarvis-brain/` carries "not in git
            # -- yours to write"; its three children do not repeat it. Without
            # this, the test passed on THIS machine only because the author's
            # own vault happened to exist, and would have gone red on every
            # fresh clone. A sandbox copy of the tracked files caught it --
            # which is the argument for running a gate somewhere other than
            # where it was written.
            if "not in git" in line or (indented and parent_absent):
                continue
            if (ROOT / target).exists() or target in shipped or target in dirs:
                continue
            missing.append(target)
        self.assertEqual(missing, [],
                         "the Layout block names things that are not there: "
                         + ", ".join(missing))


class TestTranscriptsSectionIsTrue(unittest.TestCase):
    """Every sentence in the Transcripts section that names a mechanism.

    The section exists because the feature shipped silently. If any of this
    stops being true, the section becomes the same kind of confident wrong
    answer the absolute-path table was.
    """

    TEMPLATE = ROOT / "templates" / "claude-settings.json.template"

    def setUp(self):
        self.text = README.read_text()
        self.assertIn("## Transcripts", self.text,
                      "the Transcripts section is gone; the feature still "
                      "records every conversation to disk")

    def test_the_template_really_wires_the_stop_hook(self):
        cfg = json.loads(self.TEMPLATE.read_text().replace("{{JARVIS_ROOT}}", "/x"))
        stop = cfg.get("hooks", {}).get("Stop", [])
        cmds = [h.get("command", "") for group in stop for h in group.get("hooks", [])]
        self.assertTrue(any("session_record.py" in c for c in cmds),
                        "README says install.sh wires a Stop hook that writes "
                        "transcripts; the template no longer wires it")

    def test_the_recorder_writes_where_the_readme_says(self):
        src = (ROOT / "vault-tools" / "session_record.py").read_text()
        self.assertIn('"Jarvis Visual" / "transcripts"', src,
                      "the recorder no longer writes to Jarvis Visual/"
                      "transcripts, which is the path the README prints")

    def test_the_folder_is_gitignored(self):
        lines = [l.strip() for l in (ROOT / ".gitignore").read_text().splitlines()]
        self.assertIn("transcripts/", lines,
                      "README says the transcripts folder is gitignored and "
                      "must stay that way -- it is not in .gitignore")

    def test_the_spoken_half_lives_where_the_readme_says(self):
        # The README tells a reader that removing the hook stops only the
        # typed half. That sentence is only true while this exists.
        src = (ROOT / "voice-line" / "signals.py").read_text()
        self.assertIn("def log_transcript(", src,
                      "README points at log_transcript in voice-line/"
                      "signals.py for the spoken half; it is not there")

    def test_the_guide_it_links_is_in_the_repository(self):
        self.assertTrue((ROOT / "docs" / "transcript-feature.md").is_file(),
                        "the Transcripts section links docs/"
                        "transcript-feature.md, which is not in the repo -- "
                        "the exact failure that moved it out of the vault")


if __name__ == "__main__":
    unittest.main(verbosity=2)
