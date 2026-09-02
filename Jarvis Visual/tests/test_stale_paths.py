"""No shipping file may point at a folder that is not there.

WHY THIS EXISTS. The project moved from ~/Documents/Jarvis to ~/Dev/Jarvis and
five tracked files, ten lines, kept the old address for weeks. Four were help text, which
is bad enough: a drill that tells Serge to `cd` into a folder that does not
exist. The sixth was `run-visual.sh`, whose VL variable hard-coded the
voice-line folder under the old root -- so the ring launcher could not start
the voice-web server at all, and nothing said so until someone ran it.

Found 2026-09-02 while fixing the same stale path in a vault note.

THE FIRST VERSION OF THIS FILE WAS BROKEN BY THE ADVERSARY THE SAME HOUR, and
the properties below are the ones that survived. It had extracted the `VL=`
line with a regex and evaluated it in a harness that supplied its own HERE --
so a second `VL=` assignment lower in the script, or HERE rewritten as $PWD,
both passed. And when the `cd` inside `$(...)` failed, VL came out EMPTY,
`Path("")` is `.`, and the verdict depended on the cwd of whoever ran the
suite. A test that evaluates a copy of the code is not a test of the code.

PROPERTIES, no counts and no line numbers:
  1. No file git would ship -- tracked OR untracked-and-not-ignored, because
     the gate runs before `git add` -- mentions the old root, in any case.
  2. THE REAL `run-visual.sh`, run from a cwd that is NOT its own folder with
     `curl` and `open` stubbed, sets VL exactly once, to an absolute path that
     resolves to <root>/voice-line.
  3. With no voice-line beside it, the same script exits non-zero and names
     the folder -- it does not launch the server in whatever cwd it was
     handed.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE_TESTS = Path(__file__).resolve().parent
VISUAL = HERE_TESTS.parent
ROOT = VISUAL.parent
SCRIPT = VISUAL / "run-visual.sh"
STALE = re.compile(r"documents/jarvis", re.I)


def shippable_files():
    """Everything git would ship: tracked, plus untracked files not ignored."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, check=True, capture_output=True).stdout
    return [ROOT / p for p in out.decode().split("\0") if p]


def stub_bin():
    """A PATH prefix where `curl` says the server is up and `open` does
    nothing, so the real launcher runs its whole path without touching a
    server or a browser."""
    d = Path(tempfile.mkdtemp(prefix="run-visual-stubs-"))
    for name in ("curl", "open"):
        p = d / name
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)
    return d


def run_launcher(script, cwd):
    stubs = stub_bin()
    try:
        env = dict(os.environ, PATH=f"{stubs}:{os.environ.get('PATH', '')}")
        return subprocess.run(["bash", "-x", str(script)], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=30)
    finally:
        shutil.rmtree(stubs, ignore_errors=True)


def traced_assignments(stderr, var):
    """Every `VAR=value` the trace shows actually executing."""
    return [m.group(1) for m in re.finditer(rf"^\+ {var}=(.*)$", stderr, re.M)]


class NoStaleRoot(unittest.TestCase):
    def test_no_shippable_file_names_the_old_root(self):
        hits = []
        for f in shippable_files():
            if f == Path(__file__).resolve():
                continue  # this file quotes the string on purpose
            try:
                text = f.read_text(errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if STALE.search(line):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "stale root still referenced:\n" + "\n".join(hits))

    def test_the_source_assigns_VL_exactly_once(self):
        n = len(re.findall(r"^\s*VL=", SCRIPT.read_text(), re.M))
        self.assertEqual(n, 1, "run-visual.sh must set VL exactly once")

    def test_the_real_launcher_finds_the_voice_line_from_a_foreign_cwd(self):
        # From an unrelated folder, deliberately: a launcher that only works
        # from its own folder is the $PWD bug, and the test must be able to
        # see it. (Not <root>/voice-line either -- from there, $PWD/../voice-line
        # resolves right by accident, which is how the first draft missed it.)
        with tempfile.TemporaryDirectory() as far:
            r = run_launcher(SCRIPT, cwd=far)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        vls = traced_assignments(r.stderr, "VL")
        self.assertEqual(len(vls), 1, f"VL assigned {len(vls)} times: {vls}")
        vl = vls[0].strip("'\"")
        self.assertTrue(vl, "VL is empty")
        self.assertTrue(Path(vl).is_absolute(), f"VL is not absolute: {vl}")
        self.assertEqual(Path(vl).resolve(), (ROOT / "voice-line").resolve())
        self.assertTrue((Path(vl) / "run-voice-line.sh").exists())

    def test_a_missing_voice_line_is_refused_out_loud(self):
        # Copy the script somewhere with no sibling and run it: it must stop
        # and say which folder it wanted, never fall through to `uv run` in
        # whatever cwd it was handed.
        with tempfile.TemporaryDirectory() as d:
            lone = Path(d) / "Jarvis Visual"
            lone.mkdir()
            copy = lone / "run-visual.sh"
            shutil.copy(SCRIPT, copy)
            r = run_launcher(copy, cwd=d)
            self.assertNotEqual(r.returncode, 0, "launched with no voice-line")
            self.assertIn("voice-line", r.stderr)
            self.assertNotIn("+ uv ", r.stderr, "uv ran anyway")
            self.assertNotIn("+ open ", r.stderr, "the browser opened anyway")


if __name__ == "__main__":
    unittest.main()
