"""The push guard must catch what it claims, and refuse to be quietly gutted.

This file exists because `git push` stopped asking Serge (2026-08-07 2:25 PM).
The protection moved into a hook, and a guard nobody proves is a guard nobody
has. Two of these tests are about the SCANNER; the rest are about the scanner
not being turned off by an edit that still looks reasonable.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "vault-tools" / "pre-push-check.py"

spec = importlib.util.spec_from_file_location("pre_push_check", SRC)
pp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pp)


def diff(path, *added):
    """The shape git actually emits, so the parser is exercised, not bypassed."""
    body = "".join("+" + a + "\n" for a in added)
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n" + body


class TheScannerCatches(unittest.TestCase):
    def test_every_pattern_fires_on_a_real_example(self):
        # Written as a table so a pattern ADDED without a case fails here.
        cases = {
            "a Gmail address": "contact = 'villeneuve.serge@gmail.com'",
            "an Anthropic key": "K = 'sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA'",
            "an OpenAI key": "K = 'sk-" + "a" * 40 + "'",
            "an AWS access key": "AWS = 'AKIAIOSFODNN7EXAMPLE'",
            "a GitHub token": "T = 'ghp_" + "b" * 36 + "'",
            "a private key block": "-----BEGIN OPENSSH PRIVATE KEY-----",
            "a bearer token": "h = 'Bearer abcdefghij0123456789KLMNOP'",
            "an assigned secret": "password = 'hunter2000'",
        }
        labels = {label for label, _ in pp.PATTERNS}
        self.assertEqual(labels, set(cases),
                         "a pattern exists with no test case, or the reverse")
        for label, line in cases.items():
            found = pp.findings(diff("app.py", line))
            self.assertTrue(any(f[1] == label for f in found),
                            f"{label} was not caught in: {line}")

    def test_the_finding_names_the_file(self):
        f = pp.findings(diff("deep/nested/thing.py", "k = 'AKIAIOSFODNN7EXAMPLE'"))
        self.assertEqual(f[0][0], "deep/nested/thing.py")


class TheScannerDoesNotCryWolf(unittest.TestCase):
    def test_ordinary_prose_about_secrets_is_not_a_finding(self):
        # This repo's comments discuss passwords and tokens constantly. A guard
        # that fires on them gets switched off, and then it protects nothing.
        for line in ["# never write a password into a note",
                     "// the token is stored in the keychain, not here",
                     "print('enter your password:')",
                     "SECRET_HELP = 'ask Serge where the secret lives'"]:
            self.assertEqual(pp.findings(diff("a.py", line)), [],
                             f"false positive on: {line}")

    def test_a_DELETED_secret_is_not_refused(self):
        # The inversion that would matter most: refusing the commit that
        # REMOVES a leaked key would leave the key in place forever.
        d = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
             "-AWS = 'AKIAIOSFODNN7EXAMPLE'\n")
        self.assertEqual(pp.findings(d), [])

    def test_the_scanner_does_not_flag_itself(self):
        real = SRC.read_text()
        added = diff("vault-tools/pre-push-check.py", *real.splitlines())
        self.assertEqual(pp.findings(added), [],
                         "the guard refuses its own file -- it could never ship")


class TheGuardCannotBeQuietlyGutted(unittest.TestCase):
    def test_the_pattern_list_is_not_empty(self):
        self.assertGreaterEqual(len(pp.PATTERNS), 8,
                                "patterns were removed -- the hook still runs "
                                "and still exits 0, which is the worst shape")

    def test_an_unreadable_range_is_refused(self):
        r = subprocess.run(
            [sys.executable, str(SRC)],
            input="refs/heads/main " + "a" * 40 + " refs/heads/main " + "b" * 40,
            capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0,
                            "an unresolvable range must not be waved through")

    def test_it_fails_CLOSED_when_the_scanner_itself_breaks(self):
        # DRIVEN, not grepped -- the grep version passed with the handler
        # changed to sys.exit(0): the message survived and the exit code,
        # which is the only thing git reads, did not.
        #
        # MY FIRST VERSION OF THIS TEST WAS WRONG AND PASSED FOR NO REASON.
        # It fed "not four fields" with a broken PATH, expecting a crash --
        # but a malformed line is SKIPPED before git is ever called, so the
        # script correctly did nothing and exited 0. It proved the opposite
        # of its name. To test the failure path you have to actually reach
        # it, so: run it where git cannot answer, on a WELL-FORMED line.
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(SRC)], cwd=tmp,
                input="refs/heads/main " + "a" * 40 + " refs/heads/main " +
                      "b" * 40,
                capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0,
                            "the scanner could not look and said nothing was "
                            "there -- worse than no scanner, because it is "
                            "trusted")
        self.assertIn("REFUSED", r.stderr)

    def test_the_removal_route_names_all_three_steps(self):
        # Scoped to the removal SECTION, not the whole file. The first
        # version searched the whole docstring, and ".git/hooks/pre-push"
        # also appears in the opening line -- so deleting it from the
        # removal instructions left the test green. A guard that finds its
        # string somewhere else is not checking the place it means to.
        doc = SRC.read_text()
        i = doc.find("HOW TO REMOVE IT ENTIRELY")
        self.assertNotEqual(i, -1, "the removal section is gone entirely")
        section = doc[i:i + 500]
        for step in [".git/hooks/pre-push", "pre-push-check.py",
                     "test_pre_push.py"]:
            self.assertIn(step, section,
                          f"the removal route no longer names {step} -- "
                          "a route nobody can find is the same as none")

    def test_an_unexpected_CRASH_still_refuses(self):
        # F6: the outermost handler changed to sys.exit(0) survived every
        # other test, because nothing here had ever reached it. Reaching it
        # takes a real crash, so: run with git absent from PATH, which makes
        # subprocess raise rather than return a code.
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(SRC)], cwd=tmp,
                input="refs/heads/main " + "a" * 40 + " refs/heads/main " +
                      "b" * 40,
                capture_output=True, text=True,
                env={"PATH": tmp, "HOME": tmp})
        self.assertNotEqual(r.returncode, 0,
                            "the scanner crashed and the push went through")
        self.assertIn("REFUSED", r.stderr)


class ItActuallyBLOCKSAPush(unittest.TestCase):
    """The whole chain, driven for real: commit a secret, try to push it.

    Every source-reading test above passed while `return 1` was changed to
    `return 0` -- the scanner found the key, printed the warning, and exited
    clean. That is this project's oldest failure in a new place: a guard
    proven correct and never proven CALLED. These run git.
    """

    def _repo(self, tmp, line):
        work, bare = pathlib.Path(tmp) / "w", pathlib.Path(tmp) / "r.git"
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp,
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"}
        run = lambda *a, **k: subprocess.run(a, cwd=k.pop("cwd", work), env=env,
                                             capture_output=True, text=True)
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], env=env,
                       capture_output=True)
        work.mkdir()
        run("git", "init", "-q", "-b", "main")
        # The real hook, pointed at the real scanner.
        hooks = work / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        h = hooks / "pre-push"
        h.write_text(f'#!/bin/sh\nexec {sys.executable} "{SRC}"\n')
        h.chmod(0o755)
        (work / "app.py").write_text(line + "\n")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "x")
        run("git", "remote", "add", "origin", str(bare))
        return run("git", "push", "-q", "origin", "main")

    def test_a_push_carrying_a_key_is_REFUSED(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self._repo(tmp, "AWS = 'AKIAIOSFODNN7EXAMPLE'")
        self.assertNotEqual(r.returncode, 0,
                            "a real push published a real key -- the hook did "
                            "not stop it")
        self.assertIn("PUSH REFUSED", r.stderr)

    def test_a_clean_push_is_NOT_blocked(self):
        # The other half, and it is not a formality: a guard that refuses
        # everything is indistinguishable from a broken remote, and the first
        # thing anyone does is delete it.
        with tempfile.TemporaryDirectory() as tmp:
            r = self._repo(tmp, "greeting = 'at your service'")
        self.assertEqual(r.returncode, 0,
                         "an innocent push was refused: " + r.stderr[:400])


class TheHookIsActuallyInstalled(unittest.TestCase):
    def test_the_hook_exists_and_points_at_this_script(self):
        # The lesson that earned its own line on this project's record:
        # tests prove the code, only running it proves the INSTALLATION.
        # 255 passing tests once coexisted with a tool reporting zero sessions.
        hook = ROOT / ".git" / "hooks" / "pre-push"
        self.assertTrue(hook.exists(), "the pre-push hook is not installed -- "
                                       "the scanner exists and never runs")
        self.assertIn("pre-push-check.py", hook.read_text())
        self.assertTrue(hook.stat().st_mode & 0o111, "the hook is not executable")


class PushIsNotSilentlyAllowedWithoutTheGuard(unittest.TestCase):
    def test_the_settings_allow_push_only_while_this_file_exists(self):
        # The trade Serge made: the popup goes away BECAUSE the hook is there.
        # If someone deletes the scanner, this says so loudly rather than
        # leaving an unguarded allow-rule behind.
        import json
        allowed = json.loads((ROOT / ".claude" / "settings.json").read_text())
        rules = allowed["permissions"]["allow"]
        if any("git push" in r for r in rules):
            self.assertTrue(SRC.exists(),
                            "git push is allowed but the secret scanner is gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
