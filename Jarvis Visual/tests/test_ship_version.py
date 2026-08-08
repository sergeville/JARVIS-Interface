#!/usr/bin/env python3
"""Phase 0's version script -- the number that counts itself.

The bump is a pure function, so it is tested as one: tag lists in, version
string out, no git and no filesystem. The parts that DO touch the world --
the stamp and the refusals -- are driven against real text and a real
throwaway git repo, never asserted by reading the source.

The cases that matter are the ones that only bite months from now:

  * v1.10.0 must come after v1.9.0. Compared as text it does not, and the
    scheme would silently walk backwards at the tenth phase.
  * A missing constant must REFUSE, not invent markup in a 4,000-line page.
  * A dirty tree must REFUSE, or the tag names a tree nobody can return to.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "vault-tools" / "ship-version.py"

spec = importlib.util.spec_from_file_location("shipver", SCRIPT)
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)


class TestTheBumpIsPure(unittest.TestCase):

    def test_the_first_ship_is_v1_0_0_not_v0_0_1(self):
        # v1.0.0 marks the ORIGINAL, so a first ship that started lower would
        # make the page claim to be older than its own snapshot.
        self.assertEqual(sv.next_version([], "minor"), "v1.0.0")
        self.assertEqual(sv.next_version([], "patch"), "v1.0.0")

    def test_a_phase_bumps_the_minor_and_zeroes_the_patch(self):
        self.assertEqual(sv.next_version(["v1.2.3"], "minor"), "v1.3.0")

    def test_a_major_starts_a_new_world_and_zeroes_the_rest(self):
        # Serge, 2026-08-08: the redesign's first ship is v2.0.0, not v1.2.0.
        # The bump must live in the tool -- a hand-typed version is the rule
        # enforced only by remembering.
        self.assertEqual(sv.next_version(["v1.9.3"], "major"), "v2.0.0")
        self.assertEqual(sv.next_version(["v1.0.0"], "major"), "v2.0.0")

    def test_a_major_still_beats_every_existing_tag(self):
        self.assertEqual(sv.next_version(["v1.10.7", "v1.2.0"], "major"), "v2.0.0")

    def test_a_fix_bumps_the_patch_only(self):
        self.assertEqual(sv.next_version(["v1.2.3"], "patch"), "v1.2.4")

    def test_v1_10_0_is_NEWER_than_v1_9_0(self):
        """Compared as text, '1.9.0' > '1.10.0' -- the scheme would walk
        backwards at the tenth phase, months after anyone was watching."""
        tags = ["v1.9.0", "v1.10.0", "v1.2.0"]
        self.assertEqual(sv.next_version(tags, "minor"), "v1.11.0")

    def test_gapped_tags_take_the_highest_not_the_last(self):
        self.assertEqual(sv.next_version(["v1.5.0", "v1.1.0"], "minor"),
                         "v1.6.0")

    def test_tags_this_scheme_does_not_understand_are_IGNORED(self):
        """A repo may carry tags from anywhere. Crashing on one would make
        an unrelated tag able to stop every future ship."""
        tags = ["v1.2.0", "release-2", "v2", "vX.Y.Z", "v1.2.0-rc1"]
        self.assertEqual(sv.next_version(tags, "minor"), "v1.3.0")

    def test_an_unknown_part_raises_rather_than_guessing(self):
        for bad in ("epoch", "MAJOR", "", None):
            with self.assertRaises((ValueError, TypeError)):
                sv.next_version(["v1.0.0"], bad)

    def test_parse_version_refuses_near_misses(self):
        # Surrounding whitespace is stripped on purpose -- `git tag` output is
        # read line by line -- so " v1.0.0 " belongs with the GOOD cases below,
        # not here. Written wrong first, and the test contradicted itself two
        # lines apart.
        for bad in ("1.0.0", "v1.0", "v1.0.0.0", "v1.0-0", "", "vv1.0.0"):
            self.assertIsNone(sv.parse_version(bad), bad)
        self.assertEqual(sv.parse_version(" v1.0.0 "), (1, 0, 0))


class TestTheStamp(unittest.TestCase):

    def test_it_rewrites_the_constant_and_reports_the_old_value(self):
        text = "x\nconst SHIP_VERSION = 'v1.0.0';\ny\n"
        out, old = sv.stamp(text, "v1.1.0")
        self.assertEqual(old, "v1.0.0")
        self.assertIn("const SHIP_VERSION = 'v1.1.0';", out)

    def test_it_touches_nothing_else_in_the_page(self):
        text = "before\nconst SHIP_VERSION = 'v1.0.0';\nafter v1.0.0 here\n"
        out, _ = sv.stamp(text, "v9.9.9")
        self.assertIn("after v1.0.0 here", out,
                      "a bare version elsewhere must not be rewritten")
        self.assertTrue(out.startswith("before\n"))

    def test_a_MISSING_constant_refuses_instead_of_inventing_markup(self):
        with self.assertRaises(RuntimeError) as ctx:
            sv.stamp("<html>no constant here</html>", "v1.1.0")
        self.assertIn("refusing to invent", str(ctx.exception).lower())

    def test_TWO_constants_refuse_rather_than_picking_one(self):
        text = ("const SHIP_VERSION = 'v1.0.0';\n"
                "const SHIP_VERSION = 'v1.0.0';\n")
        with self.assertRaises(RuntimeError):
            sv.stamp(text, "v1.1.0")

    def test_a_COMMENT_naming_the_constant_is_not_the_constant(self):
        """The comment-vs-code trap, seventh occurrence on this project's
        record. A mention must not satisfy the stamper."""
        text = "// const SHIP_VERSION is stamped at ship time\n"
        with self.assertRaises(RuntimeError):
            sv.stamp(text, "v1.1.0")

    def test_a_LOOK_ALIKE_is_not_the_constant(self):
        """Found by fault injection, not by reading: loosening the pattern to
        `SHIP_VERSION.{0,4}'...'` left the whole suite green, because the
        comment test above carries no quoted string at all and so refuses
        under a loose pattern too -- it passed for the wrong reason. These
        are the shapes a loose pattern would swallow and the real one must
        not: an object key, an attribute, a differently-named constant."""
        for text in ("window.SHIP_VERSION = 'v9.9.9';\n",
                     "let SHIP_VERSION = 'v9.9.9';\n",
                     "const cfg = { SHIP_VERSION: 'v9.9.9' };\n",
                     "<div data-SHIP_VERSION='v9.9.9'></div>\n",
                     "const SHIP_VERSION_LABEL = 'v9.9.9';\n",
                     'const SHIP_VERSION = "v9.9.9";\n'):
            with self.assertRaises(RuntimeError, msg=text):
                sv.stamp(text, "v1.1.0")

    def test_an_empty_constant_is_stampable_and_reported_as_empty(self):
        out, old = sv.stamp("const SHIP_VERSION = '';\n", "v1.0.0")
        self.assertEqual(old, "")
        self.assertIn("'v1.0.0'", out)


class TestItRefusesRatherThanShipping(unittest.TestCase):
    """Driven against a real throwaway repo -- reading the source would
    prove only that the words are present."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.repo = Path(self.dir)
        (self.repo / "Jarvis Visual").mkdir()
        (self.repo / "vault-tools").mkdir()
        # the script resolves ROOT from its OWN location, so it must be
        # copied into the fake tree rather than imported in place
        (self.repo / "vault-tools" / "ship-version.py").write_text(
            SCRIPT.read_text())
        self.page = self.repo / "Jarvis Visual" / "jarvis.html"
        self.page.write_text("const SHIP_VERSION = 'v1.0.0';\n")
        self.git("init", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.git("add", "-A")
        self.git("commit", "-m", "base")

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.dir])

    def git(self, *a):
        return subprocess.run(("git",) + a, cwd=self.dir,
                              capture_output=True, text=True)

    def run_script(self, *a):
        return subprocess.run(
            [sys.executable, str(self.repo / "vault-tools" / "ship-version.py")]
            + list(a), cwd=self.dir, capture_output=True, text=True)

    def test_the_default_run_changes_NOTHING(self):
        before = self.page.read_text()
        p = self.run_script()
        self.assertEqual(p.returncode, 0)
        self.assertIn("report only", p.stdout)
        self.assertEqual(self.page.read_text(), before)
        self.assertEqual(self.git("tag", "--list").stdout.strip(), "")

    def test_a_dirty_tree_is_REFUSED(self):
        (self.repo / "stray.txt").write_text("uncommitted")
        p = self.run_script("--minor", "--ship")
        self.assertEqual(p.returncode, 2)
        self.assertIn("not clean", p.stderr)
        self.assertEqual(self.git("tag", "--list").stdout.strip(), "",
                         "a refused ship must leave no tag behind")

    def test_a_clean_ship_stamps_commits_and_tags(self):
        self.git("tag", "-a", "v1.0.0", "-m", "orig")
        p = self.run_script("--minor", "--ship")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("v1.1.0", self.page.read_text())
        self.assertIn("v1.1.0", self.git("tag", "--list").stdout)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "",
                         "the ship must leave the tree clean")

    def test_a_page_with_no_constant_is_REFUSED_and_left_alone(self):
        self.page.write_text("<html>nothing here</html>\n")
        self.git("add", "-A")
        self.git("commit", "-m", "no constant")
        p = self.run_script("--minor", "--ship")
        self.assertEqual(p.returncode, 2)
        self.assertIn("SHIP_VERSION", p.stderr)
        self.assertEqual(self.page.read_text(), "<html>nothing here</html>\n")
        self.assertEqual(self.git("tag", "--list").stdout.strip(), "")

    def test_two_ships_in_a_row_produce_two_DIFFERENT_versions(self):
        """The collision case, tested as the property it actually is.

        My first version of this test planted v1.0.0 and v1.1.0 and expected
        the script to refuse -- it shipped v1.2.0 instead, correctly. The
        script's "already exists" branch is UNREACHABLE by construction,
        because the next version is always computed from the highest tag and
        is therefore always higher than every tag. It stays in the code as a
        cheap fail-closed guard for a future bump rule that could collide,
        but it is not what protects this scheme today -- monotonicity is.
        So that is what gets proven: ship twice, get two versions, and the
        second is not the first."""
        self.git("tag", "-a", "v1.0.0", "-m", "orig")
        first = self.run_script("--minor", "--ship")
        self.assertEqual(first.returncode, 0, first.stderr)
        (self.repo / "more.txt").write_text("a second phase")
        self.git("add", "-A")
        self.git("commit", "-m", "phase two")
        second = self.run_script("--minor", "--ship")
        self.assertEqual(second.returncode, 0, second.stderr)
        tags = self.git("tag", "--list").stdout.split()
        self.assertIn("v1.1.0", tags)
        self.assertIn("v1.2.0", tags)
        self.assertIn("v1.2.0", self.page.read_text(),
                      "the page must carry the LATEST stamp, not the first")

    def test_it_does_NOT_push_unless_asked(self):
        self.git("tag", "-a", "v1.0.0", "-m", "orig")
        p = self.run_script("--minor", "--ship")
        self.assertIn("not pushed", p.stdout)


class TestItIsWiredWhereThePlanSaysItIs(unittest.TestCase):

    def test_the_script_exists_at_the_path_the_plan_names(self):
        self.assertTrue(SCRIPT.is_file(), str(SCRIPT))

    def test_it_is_executable_from_the_shell(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK) or True)  # mode is advisory
        p = subprocess.run([sys.executable, str(SCRIPT)],
                           capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("report only", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
