"""vault-audit's mirrored-asset check, and its embed handling.

Serge, 2026-08-07 ~8:00 PM: "do what needs to be done so I don't lose track...
that's going to be a reference point in a near future discussion."

The JarvisOS concept images exist twice — a vault copy so Obsidian can embed
them, and the working original in `Jarvis Visual/references/`. Copies drift.
The rule ("revise in references/, re-copy") was written into the note, and a
rule enforced only by remembering is not enforced — so this is the enforcement,
and these are its tests.

The sharpest one is the LAST: a check that skips a missing file has stopped
being a check, and it fails silently, which is the failure mode this whole
tool exists to prevent.
"""
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "vault-tools" / "vault-audit.py"

spec = importlib.util.spec_from_file_location("vault_audit", SRC)
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


class Mirror(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.vault = root / "Jarvis-brain"
        (self.vault / "02 - Learning AI").mkdir(parents=True)
        (root / "Jarvis Visual" / "references").mkdir(parents=True)
        self.copy = self.vault / "02 - Learning AI" / "pic.png"
        self.origin = root / "Jarvis Visual" / "references" / "pic-original.png"
        self.saved = va.MIRRORED_ASSETS
        va.MIRRORED_ASSETS = [("02 - Learning AI/pic.png",
                               "Jarvis Visual/references/pic-original.png")]
        self.addCleanup(lambda: setattr(va, "MIRRORED_ASSETS", self.saved))

    def test_two_identical_copies_are_quiet(self):
        self.copy.write_bytes(b"same bytes")
        self.origin.write_bytes(b"same bytes")
        self.assertEqual(va.mirror_drift(self.vault), [])

    def test_drift_is_reported(self):
        self.copy.write_bytes(b"the old picture")
        self.origin.write_bytes(b"the revised picture")
        got = va.mirror_drift(self.vault)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "mirror drift")

    def test_it_compares_BYTES_not_size_or_timestamp(self):
        # A re-export changes size and mtime without changing anything that
        # matters; an edit can leave the size identical. Only the bytes answer
        # the question actually being asked.
        self.copy.write_bytes(b"AAAA")
        self.origin.write_bytes(b"BBBB")     # same length, different file
        self.assertEqual(len(va.mirror_drift(self.vault)), 1)

    def test_a_missing_vault_copy_is_REPORTED_not_skipped(self):
        # "It isn't there, so there's nothing to compare" is how a check
        # quietly stops checking.
        self.origin.write_bytes(b"x")
        got = va.mirror_drift(self.vault)
        self.assertEqual([k for k, _ in got], ["mirror missing"])

    def test_a_missing_ORIGINAL_is_reported_too(self):
        self.copy.write_bytes(b"x")
        got = va.mirror_drift(self.vault)
        self.assertEqual([k for k, _ in got], ["mirror missing"])
        self.assertIn("only one left", got[0][1])


class Embeds(unittest.TestCase):
    """`![[picture.png]]` points at a FILE, not a note."""

    def audit(self, note_text, files=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        vault = pathlib.Path(tmp.name) / "Jarvis-brain"
        vault.mkdir(parents=True)
        head = "---\nstatus: active\nproject: meta\ntype: index\n---\n"
        (vault / "VAULT-INDEX.md").write_text(head + "- Note\n")
        (vault / "Note.md").write_text(head.replace("index", "log")
                                       + note_text)
        for f in files:
            (vault / f).write_bytes(b"x")
        saved = va.MIRRORED_ASSETS
        va.MIRRORED_ASSETS = []
        try:
            return va.audit(vault)
        finally:
            va.MIRRORED_ASSETS = saved

    def test_an_embed_of_a_file_that_is_there_is_not_a_broken_link(self):
        # Checking an image against NOTE names reports every picture as
        # broken, which is the fastest way to teach someone to ignore this
        # tool -- and a tool that gets ignored is worse than no tool.
        got = self.audit("![[picture.png]]\n", files=["picture.png"])
        self.assertEqual(got, [], got)

    def test_an_embed_of_a_file_that_is_MISSING_is_caught(self):
        got = self.audit("![[gone.png]]\n")
        self.assertEqual([k for k, _ in got], ["missing file"])

    def test_a_plain_note_link_is_still_checked_the_old_way(self):
        got = self.audit("[[No Such Note]]\n")
        self.assertEqual([k for k, _ in got], ["phantom link"])


class TheRealPairsAreDeclared(unittest.TestCase):
    def test_both_concept_images_are_actually_registered(self):
        # If a third copy is ever made and not listed here, it is unwatched --
        # so the list being right is itself part of the check.
        declared = {v for v, _ in va.MIRRORED_ASSETS}
        self.assertIn("02 - Learning AI/JarvisOS5000-concept.png", declared)
        self.assertIn("02 - Learning AI/JarvisOS5000-concept-v2.png", declared)

    def test_the_live_vault_has_no_drift_right_now(self):
        self.assertEqual(va.mirror_drift(ROOT / "Jarvis-brain"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
