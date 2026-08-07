"""Tests for install.sh -- the installer a future user runs, not Serge.

WHY THIS FILE EXISTS. On 2026-08-07 `install.sh` was found to ABORT, exit 1,
on any machine where the stack already worked: line 335 read `$OLD_ROOT`, a
variable the file's own header says was deliberately removed. Under `set -u`
an undefined variable is fatal, so the script died mid-step -- before the
vault step, the verify step and the report -- and said nothing but a bash
error. It worked on a first install (nothing on port 8880 yet) and broke on
every re-run, which is exactly the idempotence its header promises first.

Nothing tested install.sh at all. `bash -n` would not have caught it either:
an undefined variable is a RUNTIME error, and the line only executes when
Kokoro is listening. So these tests are STATIC and structural -- they read
the script the way the shell will read it, without running a single line of
it, because running an installer to test it is the one thing you cannot do.

THE RULE THIS FILE ENFORCES, and it is the day's lesson in another costume:
the header makes three promises -- idempotent, --check changes nothing, never
destroys. Each was a sentence with no mechanism behind it. A promise a test
does not hold is a wish.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"


def source():
    return INSTALL.read_text(encoding="utf-8")


def strip_comments_and_quotes(text):
    """Lines as the shell sees them, minus comments and single-quoted text.

    Single-quoted runs are dropped because `$FOO` inside them is a literal,
    and a heredoc marked <<'X' is likewise inert -- counting those as reads
    is how a guard starts punishing prose, which this project has already
    paid for repeatedly.

    ⚠ `#` IS NOT ALWAYS A COMMENT, AND THE FIRST VERSION OF THIS FUNCTION
    ASSUMED IT WAS. In bash `#` is also the prefix-strip operator, and this
    script uses it inside a double-quoted string: `${d#* - }`. Cutting at
    the first `#` therefore ATE REAL CODE -- the reviewer showed that
    `idx="$VAULT/$d/${d#* - }-$OLD_ROOT.md"` survives the old stripper as
    `idx="$VAULT/$d/${d`, so the very bug this file exists to pin could be
    reintroduced on that line with every test green.

    A `#` opens a comment only at the START OF A WORD and OUTSIDE quotes.
    So this walks the line character by character, tracking single quotes,
    double quotes and `${...}`, rather than reaching for one more regex --
    the previous three attempts here were each a cleverer regex, and each
    lost to the same class of input.
    """
    out = []
    heredoc_end = None
    for line in text.splitlines():
        if heredoc_end is not None:
            if line.strip() == heredoc_end:
                heredoc_end = None
            continue
        m = re.search(r"<<'([A-Za-z_][A-Za-z0-9_]*)'", line)
        if m:
            heredoc_end = m.group(1)
            line = line[:m.start()]

        res = []
        sq = dq = False          # inside '...' / "..."
        brace = 0                # depth of ${ ... }
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\" and i + 1 < len(line):
                res.append("" if sq else line[i:i + 2])
                i += 2
                continue
            if c == "'" and not dq:
                sq = not sq
                res.append("''" if not sq else "")
                i += 1
                continue
            if c == '"' and not sq:
                dq = not dq
                res.append(c)
                i += 1
                continue
            if not sq and not dq and c == "$" and line[i:i + 2] == "${":
                brace += 1
            elif not sq and not dq and c == "}" and brace:
                brace -= 1
            if c == "#" and not sq and not dq and brace == 0:
                # A comment only when it opens a word: `a#b` is not one, and
                # neither is `${d#* - }` (brace > 0 above).
                if not res or res[-1] and res[-1][-1] in " \t":
                    break
            if not sq:
                res.append(c)
            i += 1
        out.append("".join(res))
    return "\n".join(out)


# Names the shell or the environment provides. Anything read but not in here
# and not assigned in the file is the OLD_ROOT bug.
BUILTIN = {
    "BASH_SOURCE", "HOME", "PATH", "PWD", "IFS", "USER", "SHELL", "TMPDIR",
    "VIRTUAL_ENV", "LINENO", "FUNCNAME", "RANDOM", "SECONDS", "OSTYPE",
    "BASH_VERSION", "UID", "EUID", "PPID", "HOSTNAME", "LANG", "TERM",
}


class TestNoUndefinedVariables(unittest.TestCase):
    """THE REGRESSION TEST FOR THE BUG THAT SHIPPED."""

    def test_the_script_parses(self):
        r = subprocess.run(["bash", "-n", str(INSTALL)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_it_runs_under_set_u(self):
        """`set -u` is what makes an undefined read fatal rather than empty.

        If a future edit drops it, every test below still passes while the
        failure mode quietly becomes a silent empty string -- which is worse
        than the crash, not better.
        """
        self.assertRegex(source(), r"(?m)^set -u")

    def test_a_function_local_is_not_treated_as_defined_everywhere(self):
        """⚠ THE REVIEWER'S SECOND FINDING, and its shape IS the shipped bug.

        The first version built one flat set of every name assigned
        anywhere -- including `local`s -- so `sz`, declared local inside
        kokoro_ok, counted as defined at the top level too. A line like
        `note "kokoro weights: $sz bytes"` outside that function is green
        and fatal under `set -u`. OLD_ROOT was only ever caught because it
        happened to be assigned in NO scope at all.

        A name defined SOMEWHERE treated as defined EVERYWHERE is exactly
        the "correct by topology" error from this morning's registry work,
        one file over. So locals are attributed to their own function and
        the top level is checked against top-level names only.
        """
        top, locals_by_fn = self.scopes()
        self.assertTrue(locals_by_fn,
                        "no `local` declarations found -- the scope split "
                        "is not being exercised and this test proves nothing")
        leaked = sorted(n for names in locals_by_fn.values() for n in names
                        if n in top)
        self.assertEqual(
            leaked, [],
            "these names are declared `local` inside a function AND assigned "
            f"at the top level, so the scope split cannot see a misuse: {leaked}")

    def scopes(self):
        """(top-level assigned names, {function: its local names}).

        Crude but honest: bash functions here are all `name() {` ... `\\n}`
        at column 0, and the test asserts it found some, so a change in
        style fails loudly instead of silently returning nothing.
        """
        src = strip_comments_and_quotes(source())
        locals_by_fn, spans = {}, []
        for m in re.finditer(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", src):
            end = src.find("\n}", m.end())
            end = len(src) if end == -1 else end
            spans.append((m.start(), end))
            body = src[m.end():end]
            names = set()
            for decl in re.findall(r"\blocal\s+(.+)", body):
                names |= set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", decl))
                names |= set(re.findall(r"\blocal\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
                                        "local " + decl))
            locals_by_fn[m.group(1)] = names
        top = src
        for s, e in sorted(spans, reverse=True):
            top = top[:s] + top[e:]
        return set(self.assigned_in(top)), locals_by_fn

    @staticmethod
    def assigned_in(src):
        BOUNDARY = r"(?:^|[;&|{(]|\bthen\b|\bdo\b|\belse\b)\s*"
        names = set(re.findall(BOUNDARY + r"([A-Za-z_][A-Za-z0-9_]*)=", src, re.M))
        names |= set(re.findall(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", src))
        names |= set(re.findall(r"\bread\s+-r\s+([A-Za-z_][A-Za-z0-9_]*)", src))
        for decl in re.findall(r"\blocal\s+(.+)", src):
            names |= set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", decl))
        return names

    def test_positional_parameters_are_only_read_inside_functions(self):
        """`$1` outside a function is unset and fatal under `set -u`.

        The reviewer's third finding: the name regex below never matches
        `$1`, so this class was invisible. Inside a function `$1` is its
        argument and perfectly fine; at the top level there is nothing to
        bind it to.
        """
        src = strip_comments_and_quotes(source())
        spans = [(m.start(), (src.find("\n}", m.end()) + 1) or len(src))
                 for m in re.finditer(r"(?m)^[A-Za-z_][A-Za-z0-9_]*\(\)\s*\{", src)]
        top = src
        for s, e in sorted(spans, reverse=True):
            top = top[:s] + top[e:]
        # "$@" in the arg-parsing for-loop is legitimate at the top level.
        top = top.replace('"$@"', "")
        stray = re.findall(r"\$\{?[1-9]", top)
        self.assertEqual(stray, [],
                         "a positional parameter is read at the top level, "
                         "where nothing binds it -- fatal under `set -u`")

    def test_a_top_level_read_cannot_borrow_a_function_local(self):
        """The scope split, applied to READS -- which is the half that bites.

        The `leaked` test above only compares the two assignment sets. It
        stays green while `note "... $sz"` sits at the top level reading a
        name that only exists inside kokoro_ok -- proven by injection R2,
        which the first version of this file did not catch. Checking where
        a name is DEFINED is not the same as checking where it is READ.
        """
        top_src, fns = self.regions()
        top_assigned = self.assigned_in(top_src)
        undefined = sorted({
            m.group(1) for m in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)",
                                            top_src)
        } - top_assigned - BUILTIN)
        self.assertEqual(
            undefined, [],
            "read at the TOP LEVEL but only ever defined inside a function -- "
            f"under `set -u` each is fatal when its line runs: {undefined}")
        for name, body in fns.items():
            visible = top_assigned | self.assigned_in(body) | BUILTIN
            bad = sorted({m.group(1) for m in
                          re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", body)}
                         - visible)
            self.assertEqual(bad, [], f"{name}() reads undefined: {bad}")

    def regions(self):
        """(top-level source, {function name: its body}). Asserts it found some."""
        src = strip_comments_and_quotes(source())
        fns, spans = {}, []
        for m in re.finditer(r"(?m)^([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{", src):
            end = src.find("\n}", m.end())
            end = len(src) if end == -1 else end + 2
            spans.append((m.start(), end))
            fns[m.group(1)] = src[m.end():end]
        self.assertTrue(fns, "no shell functions found -- the region split "
                             "silently matched nothing and proves nothing")
        top = src
        for s, e in sorted(spans, reverse=True):
            top = top[:s] + top[e:]
        return top, fns

    def test_every_variable_read_is_one_the_script_defines(self):
        src = strip_comments_and_quotes(source())

        # ⚠ AN ASSIGNMENT DOES NOT HAVE TO START A LINE. The first version of
        # this test anchored at ^ and reported six false positives -- DIM,
        # GRN, RED, RST, YEL, FAILED -- every one of them genuinely assigned,
        # just after a `;` on a shared line (`B=...; DIM=...; GRN=...`) or in
        # the array run `INSTALLED=(); PRESENT=(); FAILED=()`. The test was
        # wrong, not the script. Left recorded because a guard that cries
        # wolf gets switched off, and then the real OLD_ROOT walks past it.
        BOUNDARY = r"(?:^|[;&|{(]|\bthen\b|\bdo\b|\belse\b)\s*"
        assigned = set(re.findall(BOUNDARY + r"([A-Za-z_][A-Za-z0-9_]*)=",
                                  src, re.M))
        assigned |= set(re.findall(r"\blocal\s+([A-Za-z_][A-Za-z0-9_]*)", src))
        assigned |= set(re.findall(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", src))
        assigned |= set(re.findall(r"\bread\s+-r\s+([A-Za-z_][A-Za-z0-9_]*)", src))
        # `local a=0 b=0` assigns both.
        for line in re.findall(r"\blocal\s+(.+)", src):
            assigned |= set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", line))

        read = set()
        for m in re.finditer(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", src):
            read.add(m.group(1))

        undefined = sorted(read - assigned - BUILTIN)
        self.assertEqual(
            undefined, [],
            "install.sh reads variables it never defines; under `set -u` each "
            f"one is a fatal error the moment its line executes: {undefined}")

    def test_OLD_ROOT_specifically_is_gone(self):
        """The exact bug, pinned by name.

        ⚠ THIS TEST FAILED ON ITS FIRST RUN AGAINST A CORRECT FILE, and the
        reason is this project's oldest trap in its fifth costume: it
        searched the raw source for `$OLD_ROOT` and matched THE COMMENT
        EXPLAINING WHY OLD_ROOT IS GONE. Grepping source punishes the prose
        that documents the decision -- written into Engineering Lessons
        after the fourth time, and walked into again here while writing the
        guard against exactly this.

        So it reads the CODE, not the file, and asserts the stripper
        actually removed something -- otherwise a change to the comment
        syntax would quietly turn this into a test of nothing.
        """
        raw = source()
        code = strip_comments_and_quotes(raw)
        self.assertLess(len(code), len(raw),
                        "the comment stripper removed nothing -- this test "
                        "would now pass by looking at everything")
        self.assertIn("OLD_ROOT", raw,
                      "the note explaining why the path rewrite was removed "
                      "is gone; keep the reason, it is why this test exists")
        for spelling in ("$OLD_ROOT", "${OLD_ROOT"):
            self.assertNotIn(spelling, code,
                             f"{spelling} is READ by the script again -- under "
                             "`set -u` that line is fatal when it executes")


class TestCheckModeChangesNothing(unittest.TestCase):
    """`--check` says in the usage text that it installs NOTHING and changes
    NOTHING. That has to be enforced somewhere, not merely stated."""

    def test_would_install_is_the_single_gate(self):
        self.assertIn("CHECK_ONLY -eq 1", source())

    def test_every_write_to_settings_is_behind_the_gate(self):
        """The config step ran BEFORE the gate and created files in --check.

        ⚠ BOTH ASSERTIONS HERE WERE UNCAUGHT BY THEIR OWN INJECTIONS FIRST
        TIME, and for the reason this file already documents twice: they
        read the raw body, and the body carries a COMMENT naming
        would_install. Replacing the real call with `true` left the comment
        behind, so the test passed while the --check gate was gone. Third
        time in one file. The body is stripped now, and the strip is
        asserted to have done something.
        """
        body = self.render_body()
        self.assertIn("would_install", body,
                      "render_settings writes settings.json without consulting "
                      "the --check gate")
        # The gate must GUARD the write, not merely precede it in the text:
        # `if false; then would_install ...` reads in the right order and
        # gates nothing, which is exactly how injection G4 walked past this.
        self.assertRegex(
            body,
            r"if \[\[ ! -f \"\$dest\" \]\] \|\| grep -q [^\n]*\n\s*would_install",
            "the write must be reached only when the gate says so -- a gate "
            "behind a constant-false condition is decoration")
        self.assertLess(body.index("would_install"), body.index("sed "),
                        "the --check gate must come BEFORE the first write")

    def render_body(self):
        raw = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        code = strip_comments_and_quotes(raw)
        self.assertLess(len(code), len(raw),
                        "the comment stripper removed nothing -- these "
                        "assertions would be reading the prose again")
        return code

    def test_the_verifier_tolerates_a_file_check_mode_declined_to_create(self):
        # Deliberately the RAW body, not the stripped one: the verifier lives
        # inside a <<'PYCHK' heredoc, and the stripper drops quoted heredocs
        # because to the SHELL they are inert text. To this assertion they are
        # the code -- just in another language. Same reasoning, opposite
        # answer, which is why it is written down rather than left to look
        # like an inconsistency.
        body = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("if not p.exists():", body,
                      "the verifier reads both settings files unconditionally; "
                      "under --check one may legitimately not exist yet")


class TestItDoesNotDisturbARunningStack(unittest.TestCase):
    """Serge, 2026-08-07: 'if Jarvis is already there, I don't want to have
    everything rewritten.' The installer inspects; it does not rebuild."""

    def test_the_kokoro_import_probe_is_skipped_while_kokoro_is_running(self):
        """The probe was the hazard the script warns about eight lines later.

        `import api.src.main` loads PyTorch onto the GPU. The script's own
        warning says two PyTorch/MPS processes competing took down a healthy
        Kokoro -- so running the probe against a live stack could kill the
        voice, and `--check` was the worst case because it promises to be
        harmless.
        """
        body = source().split("kokoro_ok() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("kokoro_listening", body)
        self.assertLess(
            body.index("kokoro_listening"), body.index("import api.src.main"),
            "the listening check must short-circuit BEFORE the import probe")

    def test_no_branch_claims_an_import_it_may_have_skipped(self):
        """⚠ THE REVIEWER'S THIRD FINDING, and injection R4 proves it.

        The fresh-install branch printed "AND api.src.main imports"
        unconditionally, so with something already on 8880 it asserted a
        check `kokoro_ok` had deliberately skipped. One branch was made
        honest and the other left lying.

        The wording now lives in ONE function, `kokoro_report`, and this
        test says so: the sentence may not appear at a call site at all.
        A single source for a claim is the only version that cannot drift
        one branch at a time.
        """
        src = strip_comments_and_quotes(source())
        body = src.split("kokoro_report() {", 1)
        self.assertEqual(len(body), 2, "kokoro_report() is gone")
        inside = body[1].split("\n}", 1)[0]
        outside = body[0] + body[1].split("\n}", 1)[1]
        self.assertIn("api.src.main imports", inside)
        self.assertNotIn(
            "api.src.main imports", outside,
            "a call site spells out the import claim for itself; it must "
            "call kokoro_report so the claim cannot drift one branch at a time")
        self.assertEqual(
            outside.count("kokoro_report"), 2,
            "both the already-installed and the fresh-install paths must "
            "report through kokoro_report")

    def test_the_listening_check_itself_touches_nothing(self):
        body = source().split("kokoro_listening()", 1)[1].split("\n", 1)[0]
        for destructive in ("rm ", "sed -i", "curl", "git clone", "brew "):
            self.assertNotIn(destructive, body)

    def test_an_existing_vault_is_never_written(self):
        """A vault is somebody's writing and a clobbered one is unrecoverable."""
        body = source().split('step "The vault', 1)[1].split("step \"Verify", 1)[0]
        self.assertIn("VAULT-INDEX.md", body)
        self.assertIn("left untouched", body)
        # The skeleton branch must be unreachable when a vault already exists.
        self.assertLess(body.index("VAULT-INDEX.md"), body.index("mkdir -p"),
                        "the existence check must precede any mkdir")

    def test_an_existing_settings_file_is_never_clobbered(self):
        body = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("Never clobber", body)
        self.assertIn("left untouched", body)


class TestThePromisesInTheHeader(unittest.TestCase):
    """Each of the header's three rules, held to a mechanism in the file."""

    def test_the_step_count_matches_the_steps(self):
        src = source()
        declared = re.search(r"\[%d/(\d+)\]", src)
        self.assertIsNotNone(declared, "the step counter's total is not literal")
        actual = len(re.findall(r'^step "', src, re.M))
        self.assertEqual(
            int(declared.group(1)), actual,
            "the step counter promises a total the script does not deliver")

    def test_help_prints_the_real_header(self):
        r = subprocess.run(["bash", str(INSTALL), "--help"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        for promise in ("IDEMPOTENT", "IT VERIFIES", "IT NEVER DESTROYS",
                        "--check"):
            self.assertIn(promise, r.stdout)

    def test_an_unknown_option_is_refused_rather_than_ignored(self):
        r = subprocess.run(["bash", str(INSTALL), "--wat"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
