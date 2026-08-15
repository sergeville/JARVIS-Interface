"""Every hook this project deploys must RETURN. All of them, not a named three.

WHY THIS FILE IS ABOUT THE CLASS AND NOT ABOUT THREE SCRIPTS. The same bug has
now been found five times in four days, in five different files, each written
by somebody who believed they had guarded against it:

  * session_record.py guarded with `sys.stdin.isatty()`     (2026-08-14)
  * board-guard.py    guarded with isatty AND a size cap    (2026-08-14)
  * question_hook.py  guarded with nothing at all           (2026-08-15)
  * session_registry.py  `sys.stdin.read()`, no guard       (2026-08-15)
  * session_mail.py      `sys.stdin.read()`, no guard       (2026-08-15)

Six for six, the last three blocked forever on BOTH a silent pipe and a
complete payload whose writer had not closed. They fire on SessionStart,
SessionEnd, Stop, UserPromptSubmit and Notification -- which is to say on
nearly every turn of every session on this machine.

Each of those was fixed as an instance and the class stayed open, so the next
file inherited it. Twice now a fix has landed and its own author has reopened
the class in a new file the same day. So this test does not name scripts: it
READS THE DEPLOYED TEMPLATE, finds whatever hooks are configured there, and
holds every one of them to the same two properties. A hook added tomorrow is
covered tomorrow, by nobody remembering anything.

WHY IT DRIVES `_read_stdin` AND NOT `main()`. Running the real hooks would
write into the live session registry and post real notices onto the bus -- a
test that pollutes production state is a bug this project has already had, and
caught, once. The stdin boundary is the thing under test; the rest of each
hook has its own file.
"""
import ast
import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "claude-settings.json.template"

# The read must be bounded by hookio.DEFAULT_BUDGET; this is the outer patience
# of the test, generous enough that a slow machine is not a failure.
PATIENCE = 30.0


def deployed_hook_scripts():
    """Every project script the template wires as a hook, from the template.

    Read from the config rather than listed here, because a list here would be
    the second copy that has to be maintained by hand -- the exact shape of
    bug this project keeps being bitten by, applied to its own test.
    """
    if not TEMPLATE.is_file():
        return []
    cfg = json.loads(TEMPLATE.read_text())
    out = {}
    for groups in cfg.get("hooks", {}).values():
        for g in groups or []:
            for h in g.get("hooks", []) or []:
                for tok in str(h.get("command", "")).split():
                    if tok.endswith(".py") and "{{JARVIS_ROOT}}" in tok:
                        rel = tok.split("{{JARVIS_ROOT}}/", 1)[1]
                        out[rel] = (ROOT / rel)
    return sorted(out.items())



def reads_stdin(src: str) -> bool:
    """Does this script actually touch sys.stdin? By AST, never by substring.

    THE FIRST VERSION OF THIS ASKED `"stdin" in src`, AND IT WAS WRONG IN
    EXACTLY THE WAY THIS WHOLE FILE EXISTS TO CATCH. `vault-tools/brief-check.py`
    reads no stdin at all -- its rule 3 is the sentence "STDIN IS NOT READ",
    and that sentence is what the substring matched. The test demanded a
    bounded reader from a file whose documented security property is that it
    never opens the channel.

    Prose is not code. Ask the syntax tree.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "stdin"
                and isinstance(node.value, ast.Name) and node.value.id == "sys"):
            return True
    return False


class TestEveryDeployedHookIsBounded(unittest.TestCase):

    def test_the_template_actually_wires_some_hooks(self):
        # Without this, every test below passes vacuously on an empty list --
        # which is how a discovery-driven suite quietly stops testing anything.
        self.assertGreaterEqual(len(deployed_hook_scripts()), 4,
                                "no hooks discovered; the rest of this file "
                                "would pass by testing nothing")

    def test_every_hook_script_exists(self):
        for rel, path in deployed_hook_scripts():
            with self.subTest(hook=rel):
                self.assertTrue(path.is_file(),
                                f"the template wires {rel}, which is not here")

    def test_every_hook_that_touches_stdin_routes_through_the_shared_reader(self):
        for rel, path in deployed_hook_scripts():
            src = path.read_text()
            if not reads_stdin(src):
                continue
            with self.subTest(hook=rel):
                self.assertIn(
                    "hookio", src,
                    f"{rel} reads stdin without the shared bounded reader -- "
                    "this is the bug five files have now had")
                # The raw calls, by AST so a docstring explaining the old bug
                # cannot trip it -- a guard a comment can break is a guard that
                # gets weakened until it stops tripping.
                import ast
                bad = []
                for n in ast.walk(ast.parse(src)):
                    if not isinstance(n, ast.Call):
                        continue
                    f = n.func
                    if (isinstance(f, ast.Attribute) and f.attr == "read"
                            and isinstance(f.value, ast.Attribute)
                            and f.value.attr == "stdin"):
                        bad.append("sys.stdin.read")
                    if (isinstance(f, ast.Attribute) and f.attr in ("load", "loads")
                            and any(isinstance(a, ast.Attribute) and a.attr == "stdin"
                                    for a in n.args)):
                        bad.append("json.load(sys.stdin)")
                self.assertEqual(bad, [], f"{rel} still reads stdin directly")

    # ------------------------------------------------------------- behaviour
    def _returns(self, path, payload, close_writer, budget=0.5):
        """(returned, stdout) for this hook's _read_stdin, in a subprocess.

        A subprocess because a parent that blocks cannot report that it
        blocked -- which is why every in-process test of these hooks passed
        while all six real invocations hung.
        """
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT / 'vault-tools')!r})\n"
            "import hookio\n"
            "hookio.DEFAULT_BUDGET = %r\n" % budget +
            "import importlib.util as u\n"
            f"s = u.spec_from_file_location('h', {str(path)!r})\n"
            "m = u.module_from_spec(s); s.loader.exec_module(m)\n"
            # Whichever name this hook gives its reader. session_record.py
            # calls it _read_payload; the rest _read_stdin. Asserting one
            # spelling would have quietly excluded a hook from the sweep,
            # which is the failure mode a discovery test exists to avoid.
            "fn = getattr(m, '_read_stdin', None) or getattr(m, '_read_payload')\n"
            "print(repr(fn()))\n"
        )
        r, w = os.pipe()
        if payload is not None:
            os.write(w, payload)
        if close_writer:
            os.close(w)
        p = subprocess.Popen([sys.executable, "-c", code], stdin=r,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            out, _ = p.communicate(timeout=PATIENCE)
            returned = True
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            out, returned = b"", False
        os.close(r)
        if not close_writer:
            os.close(w)
        return returned, out.decode().strip()

    def _stdin_hooks(self):
        return [(rel, path) for rel, path in deployed_hook_scripts()
                if reads_stdin(path.read_text())]

    def test_a_silent_stdin_never_hangs_any_hook(self):
        for rel, path in self._stdin_hooks():
            with self.subTest(hook=rel):
                returned, out = self._returns(path, None, close_writer=False)
                self.assertTrue(returned, f"{rel} never returned on a silent "
                                          "stdin -- it hangs every turn")
                self.assertEqual(out, "None")

    def test_a_COMPLETE_payload_on_a_pipe_nobody_closes_never_hangs_any_hook(self):
        # The half that `isatty` could never have caught, and the half that the
        # first fix for session_record.py got wrong: json/read run to EOF, so a
        # perfectly good payload hangs just as hard if the writer holds on.
        payload = json.dumps({"session_id": "abcdef12",
                              "transcript_path": "/tmp/none.jsonl"}).encode()
        for rel, path in self._stdin_hooks():
            with self.subTest(hook=rel):
                returned, out = self._returns(path, payload, close_writer=False)
                self.assertTrue(returned, f"{rel} never returned on a complete "
                                          "payload whose writer stayed open")
                self.assertIn("abcdef12", out,
                              f"{rel} returned without reading the payload")

    def test_a_normal_hook_call_still_reads_its_payload(self):
        # The one that stops "return None always" from passing everything else.
        payload = json.dumps({"session_id": "abcdef12"}).encode()
        for rel, path in self._stdin_hooks():
            with self.subTest(hook=rel):
                returned, out = self._returns(path, payload, close_writer=True)
                self.assertTrue(returned)
                self.assertIn("abcdef12", out,
                              f"{rel} dropped a normal hook payload")

    def test_the_budget_is_bounded_by_the_smallest_configured_timeout(self):
        import importlib.util as u
        spec = u.spec_from_file_location(
            "hookio", str(ROOT / "vault-tools" / "hookio.py"))
        hookio = u.module_from_spec(spec)
        spec.loader.exec_module(hookio)
        cfg = json.loads(TEMPLATE.read_text())
        timeouts = [h.get("timeout") for groups in cfg["hooks"].values()
                    for g in groups for h in g.get("hooks", [])
                    if h.get("timeout") is not None]
        self.assertTrue(timeouts, "the hooks lost their configured timeouts")
        # The band, not a floor and not a ceiling: a floor alone permitted a
        # budget that left the hook 0.1s to work, a ceiling alone permitted one
        # that raced real callers.
        self.assertGreaterEqual(hookio.DEFAULT_BUDGET, 0.3 * min(timeouts))
        self.assertLessEqual(hookio.DEFAULT_BUDGET, 0.6 * min(timeouts))


if __name__ == "__main__":
    unittest.main(verbosity=2)
