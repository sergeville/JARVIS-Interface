"""The review/test agents exist in BOTH config locations and cannot drift.

Agents load from the session's own cwd, and this project has two project
config locations (the Jarvis root and `Jarvis Visual/`) -- the exact gap
that made the session registry silently miss a whole launch point on
2026-08-05. Same doctrine as the settings-file guard in
test_session_registry.py: two copies that must agree get a test proving
they do.
"""
import sys
import unittest
from pathlib import Path

# Self-locate: this file lives in <root>/Jarvis Visual/tests/
VISUAL = Path(__file__).resolve().parent.parent
ROOT = VISUAL.parent

AGENTS = ["reviewer.md", "test-adversary.md"]
LOCATIONS = [ROOT / ".claude" / "agents", VISUAL / ".claude" / "agents"]


class TestAgentFiles(unittest.TestCase):
    def test_both_locations_exist(self):
        for loc in LOCATIONS:
            self.assertTrue(loc.is_dir(), f"missing agents folder: {loc}")

    def test_both_agents_in_both_locations(self):
        for loc in LOCATIONS:
            for name in AGENTS:
                self.assertTrue((loc / name).is_file(),
                                f"missing {name} in {loc}")

    def test_copies_are_byte_identical(self):
        # Two copies that drift is worse than one copy -- each looks
        # complete alone, and which one a session gets depends on its cwd.
        for name in AGENTS:
            a = (LOCATIONS[0] / name).read_bytes()
            b = (LOCATIONS[1] / name).read_bytes()
            self.assertEqual(a, b, f"{name} differs between the two "
                             "config locations -- they must be identical")

    def test_frontmatter_carries_name_and_description(self):
        for name in AGENTS:
            text = (LOCATIONS[0] / name).read_text()
            self.assertTrue(text.startswith("---\n"), f"{name}: no frontmatter")
            fm = text.split("---", 2)[1]
            self.assertIn("name:", fm, f"{name}: frontmatter lacks name")
            self.assertIn("description:", fm,
                          f"{name}: frontmatter lacks description")

    def test_verdict_verbatim_doctrine_present(self):
        # The structural hole: a subagent reports to Jarvis, so a
        # reviewer's verdict reaches the person being reviewed first.
        # Serge confirmed the fix -- the verdict is written into the
        # record verbatim before he is spoken to. Both agents must say so.
        for name in AGENTS:
            text = (LOCATIONS[0] / name).read_text().lower()
            self.assertIn("verbatim", text,
                          f"{name}: the verdict-verbatim doctrine is gone")

    def test_reviewer_is_read_only(self):
        text = (LOCATIONS[0] / "reviewer.md").read_text()
        fm = text.split("---", 2)[1]
        tools = next(l for l in fm.splitlines() if l.startswith("tools:"))
        for banned in ("Write", "Edit"):
            self.assertNotIn(banned, tools,
                             f"reviewer must not carry the {banned} tool")
        self.assertIn("Read-only", text,
                      "reviewer.md lost its read-only hard limit")

    def test_adversary_is_not_the_author(self):
        # Serge's rule: the test ships with the change, written by the
        # author. An adversary that writes the shipping tests moves the
        # gate to after the code reaches his tab.
        text = (LOCATIONS[0] / "test-adversary.md").read_text()
        self.assertIn("not the author", text.lower(),
                      "test-adversary.md lost the not-the-author doctrine")
        self.assertIn("COPIES", text,
                      "test-adversary.md lost the probe-only-copies limit")

    def test_adversary_audits_injections_by_exit_code(self):
        # The method lesson of 2026-08-06: counting FAIL lines is not how
        # you measure an injection -- no-ops and crashes both read wrong.
        text = (LOCATIONS[0] / "test-adversary.md").read_text()
        self.assertIn("EXIT CODE", text,
                      "test-adversary.md lost the exit-code measure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
