#!/usr/bin/env python3
"""Tests for vault-tools/dock-clean.py -- the Dock recent-apps cleaner.

The filter is pure and gets the coverage; the apply path is held to its
promises structurally (defaults-only, never a hand-edit of the plist, Dock
restarted only when something was removed) plus one live round-trip through a
SCRATCH defaults domain -- never com.apple.dock, whose only live proof is
Serge's own Dock and has already been run in his hands twice today.
"""

import ast
import importlib.util
import os
import plistlib
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, "vault-tools", "dock-clean.py")


def load():
    spec = importlib.util.spec_from_file_location("dock_clean", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def source():
    with open(TOOL, encoding="utf-8") as f:
        return f.read()


def chrome_tile(bundle="com.google.Chrome",
                url="file:///Applications/Google%20Chrome.app/"):
    return {"tile-data": {"bundle-identifier": bundle,
                          "file-label": "Google Chrome",
                          "file-data": {"_CFURLString": url}}}


def other_tile(label="Obsidian", bundle="md.obsidian",
               url="file:///Applications/Obsidian.app/"):
    return {"tile-data": {"bundle-identifier": bundle,
                          "file-label": label,
                          "file-data": {"_CFURLString": url}}}


class TestTheFilterIsSurgical(unittest.TestCase):

    def setUp(self):
        self.m = load()

    def test_chrome_ghosts_are_removed(self):
        tiles = [chrome_tile(), chrome_tile(), chrome_tile()]
        survivors, removed = self.m.filter_recents(tiles)
        self.assertEqual(survivors, [])
        self.assertEqual(removed, 3)

    def test_everything_else_survives_in_order(self):
        a, b = other_tile("Obsidian"), other_tile("Preview", "com.apple.Preview",
                                                  "file:///System/Applications/Preview.app/")
        survivors, removed = self.m.filter_recents([a, chrome_tile(), b])
        self.assertEqual(survivors, [a, b])
        self.assertEqual(removed, 1)

    def test_an_empty_list_stays_empty_and_removes_nothing(self):
        self.assertEqual(self.m.filter_recents([]), ([], 0))

    def test_chrome_is_matched_by_url_when_the_bundle_id_is_missing(self):
        t = {"tile-data": {"file-data":
             {"_CFURLString": "file:///Applications/Google%20Chrome.app/"}}}
        survivors, removed = self.m.filter_recents([t])
        self.assertEqual((survivors, removed), ([], 1))

    def test_the_match_is_case_insensitive(self):
        t = chrome_tile(bundle="com.google.CHROME", url="x")
        self.assertEqual(self.m.filter_recents([t])[1], 1)

    def test_a_lookalike_is_not_chrome(self):
        # "Google Chrome Canary.app" and a bundle-id prefix must both survive:
        # removing the wrong app is the failure a surgical tool cannot have.
        canary = other_tile("Chrome Canary", "com.google.Chrome.canary",
                            "file:///Applications/Google%20Chrome%20Canary.app/")
        survivors, removed = self.m.filter_recents([canary])
        self.assertEqual((survivors, removed), ([canary], 0))

    def test_garbage_entries_survive_untouched(self):
        # This tool removes Chrome ghosts; it does not tidy other data.
        junk = ["not-a-dict", {"tile-data": "also wrong"}]
        survivors, removed = self.m.filter_recents(list(junk))
        self.assertEqual(survivors, junk)
        self.assertEqual(removed, 0)

    def test_a_non_list_is_treated_as_empty(self):
        self.assertEqual(self.m.filter_recents(None), ([], 0))

    def test_the_filter_never_adds(self):
        tiles = [other_tile(), chrome_tile()]
        survivors, _ = self.m.filter_recents(tiles)
        for s in survivors:
            self.assertIn(s, tiles)


class TestTheApplyPathKeepsItsPromises(unittest.TestCase):
    """Structural: the write goes through `defaults`, never a hand-edit; the
    Dock restarts only when something was removed; nothing else is touched."""

    def setUp(self):
        self.m = load()
        self.tree = ast.parse(source())

    def test_no_direct_plist_file_write_anywhere(self):
        # cfprefsd caches preferences and can write its cache back over a
        # hand-edited file -- the Finder lesson. So: no open() for writing,
        # no plistlib.dump-to-file, no path into ~/Library/Preferences.
        src = source()
        self.assertNotIn("Library/Preferences", src)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    self.fail("dock-clean.py must not open files at all")
                if (isinstance(node.func, ast.Attribute)
                        and node.func.attr == "dump"):
                    self.fail("plistlib.dump writes a file; only dumps/loads")

    def test_every_subprocess_is_defaults_or_killall_dock(self):
        allowed_first = {"defaults", "killall"}
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"):
                arglist = node.args[0]
                self.assertIsInstance(arglist, ast.List,
                                      "subprocess argv must be a literal list")
                first = arglist.elts[0]
                self.assertIsInstance(first, ast.Constant)
                self.assertIn(first.value, allowed_first,
                              f"unexpected command {first.value!r}")
                if first.value == "killall":
                    self.assertEqual(arglist.elts[1].value, "Dock",
                                     "killall may only ever name the Dock")

    def test_only_the_recent_apps_key_is_ever_written(self):
        # Structural, not a grep -- a text search here would punish the
        # docstring prose that explains why the pinned row is safe (and did,
        # on this test's first run). Every `defaults` call must be an export,
        # or a write naming exactly DOCK_DOMAIN and KEY.
        self.assertEqual(self.m.KEY, "recent-apps")
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run"
                    and isinstance(node.args[0], ast.List)
                    and node.args[0].elts[0].value == "defaults"):
                elts = node.args[0].elts
                verb = elts[1].value
                self.assertIn(verb, ("export", "write"),
                              f"defaults {verb!r} is not export or write")
                if verb == "write":
                    self.assertIsInstance(elts[2], ast.Name)
                    self.assertEqual(elts[2].id, "DOCK_DOMAIN")
                    self.assertIsInstance(elts[3], ast.Name)
                    self.assertEqual(elts[3].id, "KEY",
                                     "a write must name KEY and only KEY")

    def test_clean_does_not_write_when_nothing_was_removed(self):
        calls = []
        self.m.read_recents = lambda: [other_tile()]
        self.m.write_recents = lambda s: calls.append(s)
        removed = self.m.clean()
        self.assertEqual(removed, 0)
        self.assertEqual(calls, [], "a clean Dock must not be rewritten")

    def test_clean_writes_exactly_the_survivors_when_chrome_is_present(self):
        keep = other_tile()
        calls = []
        self.m.read_recents = lambda: [chrome_tile(), keep, chrome_tile()]
        self.m.write_recents = lambda s: calls.append(s)
        removed = self.m.clean()
        self.assertEqual(removed, 2)
        self.assertEqual(calls, [[keep]])

    def test_unknown_arguments_are_refused(self):
        self.assertEqual(self.m.main(["dock-clean.py", "--force"]), 2)


class TestLiveRoundTripThroughAScratchDomain(unittest.TestCase):
    """The defaults-write-XML-literal mechanism, proven against a scratch
    domain so the test can never touch the real Dock."""

    DOMAIN = "com.jarvis.dock-clean-test"

    def tearDown(self):
        subprocess.run(["defaults", "delete", self.DOMAIN],
                       capture_output=True)

    def test_an_array_of_tiles_round_trips_through_defaults(self):
        m = load()
        tiles = [other_tile(), chrome_tile()]
        xml = plistlib.dumps(m.filter_recents(tiles)[0]).decode()
        subprocess.run(["defaults", "write", self.DOMAIN, "probe", xml],
                       check=True)
        out = subprocess.run(["defaults", "export", self.DOMAIN, "-"],
                             capture_output=True, check=True).stdout
        back = plistlib.loads(out)["probe"]
        self.assertEqual(back, [other_tile()],
                         "the XML literal did not round-trip faithfully")


if __name__ == "__main__":
    unittest.main(verbosity=2)
