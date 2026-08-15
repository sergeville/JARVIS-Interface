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

import json
import re
import shutil
import subprocess
import sys
import tempfile
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
        # NAMED THE WRITE, and the write moved. This used to say `sed `,
        # which WAS the write until 2026-08-15: the substitution now happens
        # inside vault-tools/render_settings.py, so `sed ` no longer appears
        # in this function and the assertion raised ValueError rather than
        # failing. Recorded rather than quietly repointed, because "the test
        # was edited to match the code" is the exact move that must never
        # happen unwatched.
        #
        # THE FIRST VERSION OF THIS COMMENT ENDED "-- and --check returns
        # before any write can be reached at all (asserted separately below)".
        # NOTHING BELOW ASSERTED IT. Both agents caught it: no test set
        # CHECK_ONLY=1, the harness hardcoded 0, and the --check tests drove
        # the helper rather than install.sh. A repointed test justifying
        # itself with coverage that does not exist is the very move the
        # sentence above condemns. That coverage now exists --
        # test_check_mode_through_install_sh_writes_NOTHING -- and this
        # sentence names it because it can be grepped and found.
        self.assertLess(body.index("would_install"), body.index("render_settings.py"),
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
        """THIS TEST USED TO GREP FOR THE WORDS "Never clobber".

        That is a prose check standing in for a behaviour, and it passed
        happily for eight days while the branch it guarded did nothing at all:
        an already-rendered settings.json was skipped entirely, so no template
        change ever reached a machine that had run the installer before. The
        words were true and the behaviour was wrong, and only the words were
        tested. The real property is asserted behaviourally in
        TestRenderSettingsMergesWithoutDestroying below; what is left here is
        the structural half -- that install.sh delegates rather than
        re-implementing a JSON merge in bash.
        """
        body = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("render_settings.py", body,
                      "install.sh no longer delegates the merge")
        self.assertNotIn("sed -i", body,
                         "an in-place sed over a user's settings.json is the "
                         "clobber this delegation exists to prevent")
        self.assertTrue((ROOT / "vault-tools" / "render_settings.py").is_file(),
                        "install.sh calls a helper that is not in the repo")


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



class TestRenderSettingsMergesWithoutDestroying(unittest.TestCase):
    """The behaviour the "Never clobber" comment described and did not have.

    These RUN the helper, against temp files. The rest of this file is static
    on purpose -- you cannot run an installer to test it -- but that reasoning
    covers install.sh, not a pure function it shells out to, and treating the
    two the same is how the merge went eight days with only its prose checked.
    """

    HELPER = ROOT / "vault-tools" / "render_settings.py"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.tpl = self.d / "tpl.json"
        self.dest = self.d / "settings.json"
        # The registry hook is here because install.sh's own verifier demands
        # it -- "assert any(session_registry.py in c)". A fixture template
        # without it makes render_settings fail for a reason that has nothing
        # to do with what is being tested, which is a fixture bug wearing a
        # code bug's clothes.
        self.tpl.write_text(json.dumps({
            "permissions": {"allow": ["FROM_TEMPLATE"]},
            "hooks": {
                "SessionStart": [{"hooks": [
                    {"type": "command",
                     "command": "python3 {{JARVIS_ROOT}}/voice-line/session_registry.py start",
                     "timeout": 15}]}],
                "Stop": [{"hooks": [
                    {"type": "command",
                     "command": "python3 {{JARVIS_ROOT}}/vault-tools/x.py",
                     "timeout": 15}]}]}}, indent=2))

    def run_helper(self, *extra):
        return subprocess.run(
            [sys.executable, str(self.HELPER), "--root", "/REAL/ROOT",
             "--template", str(self.tpl), "--dest", str(self.dest), *extra],
            capture_output=True, text=True)

    def write_dest(self, obj):
        self.dest.write_text(json.dumps(obj, indent=2) + "\n")

    def rendered_hooks(self):
        return json.loads(self.tpl.read_text().replace(
            "{{JARVIS_ROOT}}", "/REAL/ROOT"))["hooks"]

    # ---------------------------------------------------------------- create
    def test_a_missing_file_is_created_with_the_root_substituted(self):
        r = self.run_helper()
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(self.dest.read_text())
        self.assertNotIn("{{JARVIS_ROOT}}", self.dest.read_text())
        self.assertIn("/REAL/ROOT", json.dumps(got))

    # ------------------------------------------------------- THE ACTUAL BUG
    def test_a_STALE_hook_block_IS_updated(self):
        # The whole defect in one test. Before 2026-08-15 this file was skipped
        # and counted as "already configured", so board-guard's missing timeout
        # -- and every other template fix -- never reached any machine that had
        # run the installer before.
        self.write_dest({"permissions": {"allow": ["MINE"]},
                         "hooks": {"Stop": [{"hooks": [
                             {"type": "command",
                              "command": "python3 /REAL/ROOT/vault-tools/x.py"}]}]}})
        r = self.run_helper()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.dest.read_text())["hooks"],
                         self.rendered_hooks(),
                         "a settings.json behind the template was left behind")

    def test_the_users_permissions_survive_that_update_EXACTLY(self):
        # The reason the naive "just re-render it" fix is wrong, and the reason
        # the old branch existed at all. install.sh's third rule is IT NEVER
        # DESTROYS, and an allow-list is granted by hand, decision by decision.
        mine = {"allow": ["Bash(git status)", "Read(//Users/me/**)"],
                "deny": ["Bash(rm -rf /)"]}
        self.write_dest({"permissions": mine, "hooks": {}})
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertEqual(json.loads(self.dest.read_text())["permissions"], mine,
                         "the user's own permission grants were altered")

    def test_a_key_the_template_has_never_heard_of_survives(self):
        self.write_dest({"permissions": {"allow": []}, "hooks": {},
                         "env": {"MY_VAR": "1"}, "model": "opus"})
        self.assertEqual(self.run_helper().returncode, 0)
        got = json.loads(self.dest.read_text())
        self.assertEqual(got.get("env"), {"MY_VAR": "1"})
        self.assertEqual(got.get("model"), "opus")

    def test_anything_it_changes_is_backed_up_first(self):
        self.write_dest({"permissions": {"allow": ["MINE"]}, "hooks": {}})
        before = self.dest.read_bytes()
        self.assertEqual(self.run_helper().returncode, 0)
        backups = list(self.d.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 1, "no backup was taken before writing")
        self.assertEqual(backups[0].read_bytes(), before,
                         "the backup is not what was there")

    # ------------------------------------------------------------- untouched
    def test_a_current_file_is_not_rewritten_at_all(self):
        self.write_dest({"permissions": {"allow": ["MINE"]},
                         "hooks": self.rendered_hooks()})
        before, mtime = self.dest.read_bytes(), self.dest.stat().st_mtime_ns
        r = self.run_helper()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "current")
        self.assertEqual(self.dest.read_bytes(), before)
        self.assertEqual(self.dest.stat().st_mtime_ns, mtime,
                         "an up-to-date file was rewritten -- 'kept' must mean "
                         "untouched, not rewritten with identical bytes")
        self.assertEqual(list(self.d.glob("settings.json.backup-*")), [])

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.write_dest({"permissions": {"allow": ["MINE"]}, "hooks": {}})
        self.assertEqual(self.run_helper().returncode, 0)
        after = self.dest.read_bytes()
        r = self.run_helper()
        self.assertEqual(r.stdout.strip(), "current", "not idempotent")
        self.assertEqual(self.dest.read_bytes(), after)

    # ----------------------------------------------------------------- check
    def test_check_reports_the_drift_and_writes_NOTHING(self):
        self.write_dest({"permissions": {"allow": ["MINE"]}, "hooks": {}})
        before = self.dest.read_bytes()
        r = self.run_helper("--check")
        self.assertEqual(r.returncode, 1, "--check did not report the drift")
        self.assertIn("drift", r.stdout)
        self.assertEqual(self.dest.read_bytes(), before,
                         "--check promises to change nothing")
        self.assertEqual(list(self.d.glob("settings.json.backup-*")), [])

    def test_check_on_a_current_file_is_silent_and_exits_zero(self):
        self.write_dest({"permissions": {"allow": ["MINE"]},
                         "hooks": self.rendered_hooks()})
        r = self.run_helper("--check")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("drift", r.stdout)

    def test_the_drift_report_never_prints_a_command_string(self):
        # It is read out into a terminal and into a bug report. A command
        # carries an absolute path from somebody's machine; the SHAPE -- event,
        # script name, timeout -- says everything needed without it.
        self.write_dest({"permissions": {}, "hooks": {"Stop": [{"hooks": [
            {"type": "command",
             "command": "python3 /Users/SOMEONE_ELSE/secret/x.py"}]}]}})
        out = self.run_helper("--check").stdout
        self.assertNotIn("SOMEONE_ELSE", out)
        self.assertNotIn("/Users/", out)

    # ----------------------------------------------------------- refuse, safely
    def test_an_unparseable_settings_file_is_left_alone(self):
        self.dest.write_text("{ this is not json")
        before = self.dest.read_bytes()
        r = self.run_helper()
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.dest.read_bytes(), before,
                         "a file someone was midway through editing was "
                         "overwritten")

    def test_a_malformed_template_writes_nothing(self):
        self.tpl.write_text("{ broken")
        self.write_dest({"permissions": {"allow": ["MINE"]}, "hooks": {}})
        before = self.dest.read_bytes()
        r = self.run_helper()
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.dest.read_bytes(), before,
                         "half a broken template was written over a working "
                         "config")

    # ------------------------------------------------ install.sh, actually run
    def build_clone(self, stale=True):
        n = len(list(Path(self.tmp.name).glob("clone*")))
        fake = Path(self.tmp.name) / f"clone{n}"
        (fake / ".claude").mkdir(parents=True)
        (fake / "Jarvis Visual" / ".claude").mkdir(parents=True)
        (fake / "templates").mkdir()
        (fake / "vault-tools").mkdir()
        shutil.copy2(self.HELPER, fake / "vault-tools" / "render_settings.py")
        (fake / "templates" / "claude-settings.json.template").write_text(
            self.tpl.read_text())
        hooks = ({"Stop": [{"hooks": [
                    {"type": "command", "command": "python3 /old/x.py"}]}]}
                 if stale else self.rendered_hooks_for(str(fake)))
        for d in (fake / ".claude", fake / "Jarvis Visual" / ".claude"):
            (d / "settings.json").write_text(json.dumps(
                {"permissions": {"allow": ["MINE"]}, "hooks": hooks}, indent=2))
        return fake

    def drive_install_sh(self, fake, check=0):
        """Extract render_settings() from install.sh and RUN it, with stubs."""
        body = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        harness = f'''
set -u -o pipefail
ROOT="{fake}"
VISUAL="{fake}/Jarvis Visual"
CHECK_ONLY={check}
FAILED=(); PRESENT=(); INSTALLED=(); SKIPPED=()
would_install() {{ return 0; }}
fail() {{ echo "FAIL:$1"; FAILED+=("$1"); }}
warn() {{ echo "WARN:$1"; }}
note() {{ echo "NOTE:$1"; }}
did()  {{ echo "DID:$1"; }}
have() {{ echo "HAVE:$1"; }}
ok()   {{ echo "OK:$1"; }}
render_settings() {{{body}
}}
render_settings
echo "FAILED_COUNT=${{#FAILED[@]}}"
for f in "${{FAILED[@]:-}}"; do echo "FAILED_ITEM:$f"; done
'''
        return subprocess.run(["bash", "-c", harness], capture_output=True,
                              text=True, cwd=str(fake))

    def settings_files(self, fake):
        return [fake / ".claude" / "settings.json",
                fake / "Jarvis Visual" / ".claude" / "settings.json"]

    def test_install_sh_ACTUALLY_INVOKES_the_helper_on_the_write_path(self):
        """MY OWN INJECTION ROUND FOUND THIS HOLE: replacing the non-check call
        with a hardcoded `out="current"; rc=0` left every test GREEN. The
        helper's behaviour was pinned thoroughly and the WIRING by a substring
        the --check branch still matched.
        """
        fake = self.build_clone(stale=True)
        r = self.drive_install_sh(fake, check=0)
        self.assertIn("FAILED_COUNT=0", r.stdout, r.stdout + r.stderr)
        # AND IT MUST SAY SO. Collapsing the result check to `elif true` still
        # updated both files but reported "already configured" -- the write
        # right and the record silent, the pair that hid this bug for a week.
        self.assertIn("DID:", r.stdout,
                      "install.sh updated the files and reported them as "
                      "already configured")
        self.assertNotIn("HAVE:", r.stdout)
        for f in self.settings_files(fake):
            got = json.loads(f.read_text())
            self.assertEqual(got["hooks"], self.rendered_hooks_for(str(fake)),
                             f"{f} was not actually updated")
            self.assertEqual(got["permissions"], {"allow": ["MINE"]},
                             "the user's permissions did not survive install.sh")

    def test_check_mode_through_install_sh_writes_NOTHING(self):
        """BOTH AGENTS' TOP FINDING. The --check branch this change ADDED had
        no behavioural coverage at all: four separate injections into it left
        the suite green at 32/32, and driving one of them proved
        `install.sh --check` REWROTE both live config files, took backups, and
        reported them untouched with zero failures. That is the silent write
        plus the false record -- the exact pair this change exists to kill --
        reintroduced by the change itself, in a branch no test executed.
        """
        fake = self.build_clone(stale=True)
        before = {f: f.read_bytes() for f in self.settings_files(fake)}
        r = self.drive_install_sh(fake, check=1)
        for f, was in before.items():
            self.assertEqual(f.read_bytes(), was,
                             f"--check REWROTE {f}")
            self.assertEqual(list(f.parent.glob("settings.json.backup-*")), [],
                             "--check took a backup, so it wrote")
        self.assertIn("WARN:", r.stdout, "--check did not report the drift")
        self.assertNotIn("DID:", r.stdout)
        self.assertIn("FAILED_ITEM:settings.json out of date", r.stdout,
                      "--check found drift and did not record it as a failure, "
                      "so the installer would exit 0 on a stale machine")

    def test_check_mode_on_a_current_clone_is_quiet(self):
        # The mirror: a --check that cries drift on a clean tree is a --check
        # nobody reads, which is how this branch would rot.
        fake = self.build_clone(stale=False)
        r = self.drive_install_sh(fake, check=1)
        self.assertIn("FAILED_COUNT=0", r.stdout, r.stdout + r.stderr)
        self.assertNotIn("WARN:", r.stdout)
        self.assertIn("HAVE:", r.stdout)

    def test_the_check_gate_is_inside_the_function_not_merely_in_the_file(self):
        # `assertIn("CHECK_ONLY -eq 1", source())` reads the WHOLE script and
        # still matches three other lines after this branch is broken -- the
        # same substring-that-survives defect as the wiring pin above.
        raw = source().split("render_settings() {", 1)[1].split("\n}", 1)[0]
        code = strip_comments_and_quotes(raw)
        self.assertLess(len(code), len(raw), "the stripper removed nothing")
        self.assertIn("CHECK_ONLY -eq 1", code)

    def test_a_dest_carrying_a_placeholder_is_repaired_end_to_end(self):
        # The shipped template puts {{JARVIS_ROOT}} inside `permissions`, a
        # USER-OWNED key. Carrying that key across verbatim left the
        # placeholder in place, and install.sh's own verifier then failed
        # forever, in both modes, with no way to self-heal.
        fake = self.build_clone(stale=False)
        for f in self.settings_files(fake):
            d = json.loads(f.read_text())
            d["permissions"] = {"allow": ["Edit(/{{JARVIS_ROOT}}/Jarvis-brain/**)"]}
            f.write_text(json.dumps(d, indent=2))
        r = self.drive_install_sh(fake, check=0)
        self.assertIn("FAILED_COUNT=0", r.stdout, r.stdout + r.stderr)
        for f in self.settings_files(fake):
            self.assertNotIn("{{JARVIS_ROOT}}", f.read_text())
            self.assertIn(str(fake), f.read_text())

    def rendered_hooks_for(self, root):
        return json.loads(self.tpl.read_text().replace(
            "{{JARVIS_ROOT}}", root))["hooks"]

    # ------------------------------------------- the class, closed this time
    def test_every_file_install_sh_shells_out_to_is_TRACKED(self):
        """YESTERDAY'S FINDING, ONE FILE OVER, ONE DAY LATER.

        `hookio.py` shipped untracked on 2026-08-14 and the remedy was written
        into test_board_guard.py the same night. Then this change added
        `render_settings.py`, install.sh began shelling out to it, and it too
        was untracked -- on a fresh clone python exits 2, install.sh fails, and
        the installer exits 1 HAVING WRITTEN NO settings.json AT ALL: no
        registry hook, no board-guard, no session recorder, from the one script
        whose entire job is a fresh clone. The whole suite was green throughout,
        because `.is_file()` is satisfied by an untracked file forever.

        Asserted here rather than remembered, because it has now been learned
        twice and a rule enforced only by remembering is not enforced.
        """
        for dep in re.findall(r"vault-tools/([\w.-]+\.py)", source()):
            with self.subTest(dep=dep):
                r = subprocess.run(
                    ["git", "-C", str(ROOT), "ls-files", "--error-unmatch",
                     f"vault-tools/{dep}"], capture_output=True)
                self.assertEqual(r.returncode, 0,
                                 f"install.sh shells out to vault-tools/{dep}, "
                                 "which is not in the repo -- a fresh clone "
                                 "gets no settings.json at all")

    def test_the_backups_this_writes_are_gitignored(self):
        # A byte copy of a file .gitignore deliberately excludes, carrying the
        # user's allow-list and absolute home path, in a PUBLIC repo -- and the
        # existing ignore rules are literal filenames with no glob.
        for d in (".claude", "Jarvis Visual/.claude"):
            name = f"{d}/settings.json.backup-20260815-000000"
            r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", name],
                               capture_output=True)
            self.assertEqual(r.returncode, 0, f"{name} is committable")

    # -------------------------------------------------- refuse, with a reason
    def test_a_destination_that_is_not_an_object_is_refused_untouched(self):
        for payload in ("null", "[]", '"hi"', "5", "true"):
            with self.subTest(payload=payload):
                self.dest.write_text(payload)
                before = self.dest.read_bytes()
                r = self.run_helper()
                self.assertEqual(r.returncode, 3,
                                 f"{payload} was not refused cleanly")
                self.assertEqual(self.dest.read_bytes(), before)

    def test_a_template_that_lost_its_hooks_key_is_refused_not_called_current(self):
        # `if key not in template: continue` reported "current", install.sh
        # printed "already configured", and the verifier passed on the stale
        # deployed hooks. Eight days of silence, reproduced inside the fix.
        self.tpl.write_text(json.dumps({"permissions": {}, "hookz": {}}))
        self.write_dest({"permissions": {"allow": ["MINE"]}, "hooks": {}})
        r = self.run_helper()
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("current", r.stdout)

    def test_a_destination_that_is_a_directory_gets_its_OWN_exit_code(self):
        # Not 1. install.sh reads 1 as "behind the template" and was printing
        # traceback lines as drift detail -- a crash reported as staleness.
        self.dest.mkdir()
        for extra_args in ([], ["--check"]):
            with self.subTest(mode=extra_args):
                r = self.run_helper(*extra_args)
                self.assertEqual(r.returncode, 3,
                                 "a broken destination is indistinguishable "
                                 "from drift")

    # ------------------------------------------------------------- integrity
    def test_a_root_containing_a_backslash_survives_verbatim(self):
        r = subprocess.run(
            [sys.executable, str(self.HELPER), "--root", r"/Users/me/a\bc",
             "--template", str(self.tpl), "--dest", str(self.dest)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        cmds = json.dumps(json.loads(self.dest.read_text())["hooks"])
        self.assertIn(r"/Users/me/a\\bc", cmds,
                      "a backslash in the user's path became an escape "
                      "sequence inside the rendered command")

    def test_non_ascii_in_the_users_block_round_trips_as_itself(self):
        self.write_dest({"permissions": {"allow": ["Read(/Users/josé/**)"]},
                         "hooks": {}})
        self.assertEqual(self.run_helper().returncode, 0)
        raw = self.dest.read_text()
        self.assertIn("josé", raw,
                      "the user's own text was rewritten into \\uXXXX escapes, "
                      "so 'carried across untouched' is false byte-wise")

    def test_two_runs_in_the_same_second_keep_BOTH_originals(self):
        self.write_dest({"permissions": {"allow": ["A"]}, "hooks": {}})
        self.assertEqual(self.run_helper().returncode, 0)
        self.write_dest({"permissions": {"allow": ["B"]}, "hooks": {}})
        self.assertEqual(self.run_helper().returncode, 0)
        backups = list(self.d.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 2,
                         "second-resolution names collided and the earlier "
                         "original was overwritten by its own backup")

    def test_the_backups_do_not_accumulate_without_bound(self):
        import importlib.util as u
        spec = u.spec_from_file_location("rs", self.HELPER)
        rs = u.module_from_spec(spec); spec.loader.exec_module(rs)
        for i in range(rs.KEEP_BACKUPS + 4):
            self.write_dest({"permissions": {"allow": [f"v{i}"]}, "hooks": {}})
            self.assertEqual(self.run_helper().returncode, 0)
        self.assertLessEqual(len(list(self.d.glob("settings.json.backup-*"))),
                             rs.KEEP_BACKUPS)

    # ----------------------------------------------------------- say it aloud
    def test_the_write_path_NAMES_the_hook_it_removes(self):
        # --check named the hook it was about to delete; the write path printed
        # only "hooks updated" and deleted it in silence. Same "write right,
        # record silent" shape this whole change exists to end, committed by
        # the fix itself.
        self.write_dest({"permissions": {}, "hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": "python3 /me/my-private-hook.py"}]}]}})
        out = self.run_helper().stdout
        self.assertIn("my-private-hook.py", out,
                      "a hook of the user's was deleted without being named")
        self.assertIn("REMOVING", out)

    def test_the_drift_report_never_prints_a_commands_ARGUMENTS(self):
        # The earlier fixture -- a command with a slash and NO arguments -- was
        # the one shape that could not reveal either leak: split("/")[-1] keeps
        # everything after the last slash, and for a command with no slash at
        # all it is a no-op that prints the whole line.
        for cmd in ("python3 /h/hook.py --token=sk-live-ABC123 --user v@e.com",
                    "echo SUPER-SECRET-TOKEN-abc123"):
            with self.subTest(cmd=cmd):
                self.write_dest({"permissions": {}, "hooks": {"Stop": [
                    {"hooks": [{"type": "command", "command": cmd}]}]}})
                out = self.run_helper("--check").stdout
                self.assertNotIn("sk-live-ABC123", out)
                self.assertNotIn("SUPER-SECRET-TOKEN", out)
                self.assertNotIn("v@e.com", out)

    def test_an_UNFORESEEN_error_exits_4_and_never_1(self):
        """MY OWN INJECTION ROUND FOUND THIS: turning the catch-all `return 4`
        back into `return 1` shipped green. install.sh reads 1 as "behind the
        template", so any unhandled crash would again be reported to the user
        as staleness, with the traceback printed as drift detail. The
        directory case above exits 3 through a deliberate path and therefore
        never exercises the handler at all.

        A parent that exists as a FILE makes mkdir raise -- an error the code
        does not anticipate, which is exactly the point.
        """
        blocked = self.d / "not-a-dir"
        blocked.write_text("i am a file")
        r = subprocess.run(
            [sys.executable, str(self.HELPER), "--root", "/R",
             "--template", str(self.tpl), "--dest", str(blocked / "settings.json")],
            capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 1,
                            "an unforeseen crash exits 1, which install.sh "
                            "reports as 'behind the template'")
        self.assertEqual(r.returncode, 4, r.stderr[-300:])
        self.assertIn("Traceback", r.stderr,
                      "exit 4 without a traceback tells nobody what broke")

    def test_the_template_owns_hooks_and_nothing_else(self):
        # The boundary is the whole design, so it is asserted rather than
        # described: widening TEMPLATE_OWNS silently would start overwriting
        # the user's own keys on every install.
        import importlib.util as u
        spec = u.spec_from_file_location("rs", self.HELPER)
        rs = u.module_from_spec(spec)
        spec.loader.exec_module(rs)
        self.assertEqual(tuple(rs.TEMPLATE_OWNS), ("hooks",))

if __name__ == "__main__":
    unittest.main(verbosity=2)
