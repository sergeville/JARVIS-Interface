#!/usr/bin/env python3
"""Tests for the WALK ME THROUGH IT button's server half.

Run:  ./tests/run-tests.sh          (from Jarvis Visual/)
   or  python3 tests/test_walkthrough.py

Why this file exists. Serge, 2026-08-07 ~10:30 AM, reading the Review column:
*"I thought yesterday we were talking about having some kind of button, that if
I press, you will help me review it together."* He was right that we discussed
it and right that it did not exist -- approve and send back are both VERDICTS,
final answers that empty the column, and there was no way to open a card and go
through it before deciding.

The two properties worth guarding are not "does it work". They are:

  1. IT WRITES NOTHING. It moves no card and sets no status. A walk-through
     that quietly moved his card would make asking a question indistinguishable
     from giving an answer -- and he would never see the difference until the
     column was wrong.

  2. THE PAGE'S STRING NEVER REACHES THE BRAIN. The browser posts a title; the
     server matches it against the cards actually sitting in Review in the
     vault and builds the prompt from ITS OWN copy. So the set of strings that
     can travel this path is exactly "titles Serge wrote in his own vault and
     that are in Review right now" -- a closed set, not free text. Same rule as
     the session bus, and for the same reason: anything reaching a model's
     attention is an instruction surface whether or not anyone meant it to be.

These run against fixtures in a temp dir -- the real Active Priorities note is
never read or written here.
"""

import ast
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"


def load_server():
    """Import voice-web-server.py by path (its name isn't a valid module name)."""
    spec = importlib.util.spec_from_file_location("vws", SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vws = load_server()
SRC = SERVER.read_text()

NOTE = """---
status: active
---
# Active Priorities

### Open Tasks

- [ ] **Alpha in review** (learning-ai)
  - status: review
  - owner: voice line (pid 1)
  - priority: P2
  - updated: 2026-08-07 10:00
  - note: waiting on his eyes

- [ ] **Beta in progress** (learning-ai)
  - status: active
  - owner: voice line (pid 1)
  - priority: P2
  - updated: 2026-08-07 10:00
  - note: being built

- [ ] **Gamma waiting** (learning-ai)
  - status: waiting-on-serge
  - owner: unassigned
  - priority: P3
  - updated: 2026-08-07 10:00
  - note: blocked on him
"""


class WithNote(unittest.TestCase):
    """Point the server's parser at a fixture, never at the real note."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        f = Path(self._dir.name) / "Active Priorities.md"
        f.write_text(NOTE)
        self._real = vws.PRIORITIES_FILE
        vws.PRIORITIES_FILE = f
        vws._TASK_CACHE.update(mtime=None, tasks=[])

    def tearDown(self):
        vws.PRIORITIES_FILE = self._real
        vws._TASK_CACHE.update(mtime=None, tasks=[])
        self._dir.cleanup()


class FindsOnlyRealReviewCards(WithNote):

    def test_a_card_in_review_is_found(self):
        self.assertEqual(vws.find_review_card("Alpha in review"),
                         "Alpha in review")

    def test_the_returned_title_is_the_VAULTS_copy_not_the_callers(self):
        # The caller's string is thrown away even when it matches. This is the
        # property that makes the prompt's contents provably vault-authored,
        # and it is invisible in behaviour until someone changes it -- so it is
        # asserted by identity against the parsed task, not by equality.
        want = "Alpha in review"
        got = vws.find_review_card(" " + want + " ")
        parsed = [t["title"] for t in vws.read_tasks()
                  if t.get("status") == "review"]
        self.assertIn(got, parsed)
        self.assertIsNot(got, want)

    def test_a_card_NOT_in_review_is_refused(self):
        # He may only walk through what is actually under review. A card in
        # any other column is not his to review, and pretending otherwise
        # would make the button lie about the board.
        self.assertIsNone(vws.find_review_card("Beta in progress"))
        self.assertIsNone(vws.find_review_card("Gamma waiting"))

    def test_a_card_that_does_not_exist_is_refused(self):
        self.assertIsNone(vws.find_review_card("No such card"))

    def test_the_match_is_EXACT_never_a_substring(self):
        # A loose match is how a press on one card quietly selects another --
        # the same trap the /task-move route names in its own header.
        self.assertIsNone(vws.find_review_card("Alpha"))
        self.assertIsNone(vws.find_review_card("Alpha in review and more"))

    def test_junk_shapes_are_refused_rather_than_raising(self):
        for junk in (None, 42, b"Alpha in review", ["Alpha in review"],
                     "", "   ", {"title": "Alpha in review"}):
            self.assertIsNone(vws.find_review_card(junk), repr(junk))

    def test_an_overlong_title_is_refused_before_the_note_is_read(self):
        self.assertIsNone(vws.find_review_card("A" * (vws.MAX_TITLE + 1)))

    def test_the_cap_REFUSES_a_card_that_would_otherwise_MATCH(self):
        # The gap this closes, found by injection 2026-08-07: the test above
        # passes a title that matches no card, so it returns None whether or
        # not the cap exists -- it cannot tell "too long" from "not found",
        # and deleting `len(want) > MAX_TITLE` left the suite green.
        #
        # So: put a genuinely overlong card IN REVIEW in the fixture. Now the
        # only thing that can refuse it is the cap itself.
        long_title = "L" * (vws.MAX_TITLE + 1)
        f = Path(self._dir.name) / "Active Priorities.md"
        f.write_text(NOTE + f"""
- [ ] **{long_title}** (learning-ai)
  - status: review
  - owner: unassigned
  - priority: P3
  - updated: 2026-08-07 10:00
  - note: overlong on purpose
""")
        vws._TASK_CACHE.update(mtime=None, tasks=[])
        # It really is parsed and really is in Review -- otherwise this test
        # would pass for the same wrong reason as the one above.
        self.assertIn(long_title,
                      [t["title"] for t in vws.read_tasks()
                       if t.get("status") == "review"])
        self.assertIsNone(vws.find_review_card(long_title))

    def test_the_cap_is_the_SAME_one_the_write_route_uses(self):
        # Two different caps on two paths into one note is how the smaller one
        # stops being the limit.
        self.assertEqual(vws.MAX_TITLE, 200)


class ThePromptIsFixed(unittest.TestCase):

    def test_the_prompt_names_the_card(self):
        p = vws.review_prompt("Alpha in review")
        self.assertIn("Alpha in review", p)

    def test_the_prompt_forbids_deciding_and_moving(self):
        # The button's entire contract. If this sentence goes, the walk-through
        # becomes a fourth verdict wearing a question's clothes.
        p = vws.review_prompt("Alpha in review").lower()
        self.assertIn("do not approve", p)
        self.assertIn("do not move", p)
        self.assertIn("the verdict is his", p)

    def test_the_prompt_asks_him_at_the_end(self):
        # A walk-through that ends in silence leaves the card exactly where a
        # walk-through was supposed to help.
        self.assertIn("ask", vws.review_prompt("X").lower())

    def test_the_only_variable_is_the_title(self):
        # Everything else must be identical between two cards, or the prompt
        # has grown a second input nobody is guarding.
        a = vws.review_prompt("AAA")
        b = vws.review_prompt("BBB")
        self.assertEqual(a.replace("AAA", "@"), b.replace("BBB", "@"))


class TheBranchWritesOneThingAndNeverAVerdict(unittest.TestCase):
    """Structural: read the websocket handler's `review` branch itself.

    RENAMED 2026-08-07 from TheBranchWritesNothing, on Serge's go, and the
    old name is worth recording because it was too broad. The button now
    writes -- it moves the card to In Progress, since the thinking is work
    and a board that goes quiet is the failure mode he keeps catching. What
    it must never do is render a VERDICT: approve and send back are his.
    """

    @staticmethod
    def branch() -> str:
        i = SRC.index('elif kind == "review":')
        j = SRC.index('elif kind == "image":', i)
        return SRC[i:j]

    def test_the_branch_exists(self):
        self.assertIn('elif kind == "review":', SRC)

    @staticmethod
    def branch_body() -> list:
        """The `review` branch's OWN statements, parsed.

        Text is what let the injection round walk past this class: a grep
        finds the spellings you thought of. The AST lets us enumerate what
        the branch is ALLOWED to do instead.

        The `body` matters, not the node. In an `if/elif` chain every later
        branch hangs off the previous one's `orelse`, so walking the node
        walks the whole rest of the handler -- the image branch's uploads and
        the audio branch's transcription would all read as calls this branch
        makes. That is not a detail: an allowlist scoped one node too wide is
        an allowlist that has to permit everything, which is no allowlist.
        """
        for n in ast.walk(ast.parse(SRC)):
            if not isinstance(n, ast.If):
                continue
            t = n.test
            if (isinstance(t, ast.Compare)
                    and isinstance(t.left, ast.Name) and t.left.id == "kind"
                    and len(t.comparators) == 1
                    and isinstance(t.comparators[0], ast.Constant)
                    and t.comparators[0].value == "review"):
                return n.body
        raise AssertionError("the review branch was not found in the AST")

    @classmethod
    def walk_branch(cls):
        for stmt in cls.branch_body():
            yield from ast.walk(stmt)

    # Everything the branch is permitted to call. An ALLOWLIST, deliberately,
    # and this is the whole lesson of the 2026-08-07 injection round: the old
    # version of this test named the calls it forbade, so `move_task(...)` --
    # a real vault write -- ran inside the branch with the suite green, purely
    # because that spelling was not on anyone's list. A guard that enumerates
    # the forbidden is defeated by the first thing nobody thought of; a guard
    # that enumerates the permitted fails closed. Adding a name here is a
    # deliberate act, which is exactly the point.
    #
    # INVERTED 2026-08-07 ~1:45 PM on Serge's go, and inverted rather than
    # loosened. `_task_tool`, `to_thread` and `move` are on this list because
    # the button now DOES write: it moves the card to In Progress, because
    # the thinking is work and a silent board is the failure he has caught
    # four times. The allowlist proved itself in the same breath -- it went
    # red on this session's own new write, which is what an allowlist is for.
    # The property it guards is no longer "writes nothing"; it is "writes
    # exactly one thing, and never a verdict", pinned by the three tests below.
    ALLOWED_CALLS = frozenset({
        "find_review_card", "review_prompt", "terminal_alive",
        "safe_send", "interrupt", "approval_pending", "run_turn",
        "create_task", "monotonic", "time_ns", "mkdir", "write_text",
        "get", "print", "str",
        "_task_tool", "to_thread", "move", "update",
    })

    def test_the_branch_calls_ONLY_what_it_is_allowed_to(self):
        called = set()
        for n in self.walk_branch():
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if isinstance(f, ast.Name):
                called.add(f.id)
            elif isinstance(f, ast.Attribute):
                called.add(f.attr)
        stray = called - self.ALLOWED_CALLS
        self.assertFalse(stray, f"the review branch calls {sorted(stray)} -- "
                                "not on the allowlist. If it is genuinely "
                                "safe AND writes nothing, add it above on "
                                "purpose.")

    def move_calls(self):
        """Every vault write the review branch makes, normalised.

        The write is handed to a thread rather than called inline:

            asyncio.to_thread(_task_tool().move, matched, "active", WALK_NOTE,
                              exact=True, only_from=(REVIEW_STATUS,))

        so `.move` appears as a bare Attribute REFERENCE and there is no
        `move(...)` Call node anywhere to find. A test looking for the call
        finds zero and reports "no writes", which is the most dangerous
        possible wrong answer for this file -- it would read as the old
        writes-nothing property holding. So match the `to_thread` whose
        first argument is that reference, and return it with the callable
        stripped off, leaving move's own arguments.
        """
        out = []
        for n in self.walk_branch():
            if not (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "to_thread" and n.args):
                continue
            fn = n.args[0]
            if isinstance(fn, ast.Attribute) and fn.attr == "move":
                out.append(ast.Call(func=fn, args=n.args[1:],
                                    keywords=n.keywords))
        return out

    def test_the_branch_makes_EXACTLY_ONE_write(self):
        # The button went from writing nothing to writing something, which is
        # the moment to pin how much. One move, no more.
        self.assertEqual(len(self.move_calls()), 1)

    def test_the_one_write_is_INTO_ACTIVE_and_carries_the_walk_note(self):
        # Serge's actual ask, asserted rather than described: the card lands
        # in In Progress, and it lands wearing the marker that keeps his two
        # verdict buttons reachable there.
        call = self.move_calls()[0]
        self.assertEqual(len(call.args), 3, "move's shape changed")
        self.assertIsInstance(call.args[1], ast.Constant)
        self.assertEqual(call.args[1].value, "active")
        self.assertIsInstance(call.args[2], ast.Name)
        self.assertEqual(call.args[2].id, "WALK_NOTE")

    def test_the_one_write_can_only_come_OUT_OF_REVIEW(self):
        # Without this the button is a general-purpose card mover: anything
        # the page named would be dragged into In Progress. `only_from` is
        # the whole reason it is narrow, so it is asserted at the call.
        call = self.move_calls()[0]
        kw = {k.arg: k.value for k in call.keywords}
        self.assertIn("only_from", kw, "the walk move has no only_from")
        self.assertIs(kw["exact"].value, True, "the walk move is not exact")

    def test_the_branch_writes_NO_VERDICT_STATUS(self):
        # The line that replaced "it writes nothing". `done` is approve and
        # the send-back note is the other verdict; neither may appear here,
        # whatever else this branch grows later.
        b = self.branch()
        for verdict in ('"done"', "'done'", "TASK_ACTIONS", "APPROVED"):
            self.assertNotIn(verdict, b, verdict)

    def test_the_board_move_CANNOT_kill_the_walk_through(self):
        # Serge asked a question. If the vault write fails, he still gets his
        # answer -- trading a quiet board for a dead button is the worse of
        # the two bugs, and a silent button is this whole week's theme.
        # Identity is not usable here: move_calls() rebuilds a node to strip
        # to_thread's callable off, so `is` would never match the real tree
        # and this test would pass by finding nothing. Search the Try nodes
        # for the write itself instead.
        def holds_the_write(node):
            for n in ast.walk(node):
                if (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "to_thread" and n.args
                        and isinstance(n.args[0], ast.Attribute)
                        and n.args[0].attr == "move"):
                    return True
            return False

        tries = [n for n in self.walk_branch()
                 if isinstance(n, ast.Try) and holds_the_write(n)]
        self.assertTrue(tries, "the board move is not inside a try")
        self.assertTrue(any(t.handlers for t in tries),
                        "the board move's try catches nothing")
        # ...and the handler must not swallow it in silence.
        self.assertIn("board move refused", self.branch())

    def test_the_allowlist_admits_no_writer(self):
        # The allowlist is only worth anything if a writer could never be on
        # it by accident, so name the writers and assert their absence here
        # rather than in the branch -- one place, checked once.
        for writer in ("move_task", "task_move", "set_status_of",
                       "set_status", "TASK_ACTIONS"):
            self.assertNotIn(writer, self.ALLOWED_CALLS, writer)

    def test_the_branch_matches_before_it_prompts(self):
        b = self.branch()
        self.assertLess(b.index("find_review_card"), b.index("review_prompt"),
                        "the prompt is built before the title is validated")

    def test_the_prompt_is_built_from_the_MATCHED_title(self):
        # The whole injection boundary in one line: review_prompt must be
        # handed `matched`, never `data.get("title")` or any browser value.
        tree = ast.parse(SRC)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "review_prompt"]
        self.assertTrue(calls, "review_prompt is never called")
        for c in calls:
            self.assertEqual(len(c.args), 1)
            self.assertIsInstance(c.args[0], ast.Name,
                                  "review_prompt was handed an expression, "
                                  "not the matched name")
            self.assertEqual(c.args[0].id, "matched")

    def test_a_miss_is_SAID_not_swallowed(self):
        b = self.branch()
        self.assertIn('"type": "error"', b)
        self.assertIn("continue", b)

    def test_a_miss_never_reaches_the_brain(self):
        b = self.branch()
        self.assertLess(b.index('"type": "error"'), b.index("run_turn"),
                        "an unmatched card still starts a turn")

    def test_the_matched_name_is_the_BARE_call_with_no_fallback(self):
        # THE INJECTION BOUNDARY, and the gap the round of 2026-08-07 walked
        # straight through. The ordering test above still passed when the
        # assignment grew a fallback:
        #
        #     matched = find_review_card(data.get("title")) or data.get("title")
        #
        # The error branch was still textually present and still textually
        # first, so the greps were satisfied while the browser's RAW string
        # went into the prompt. So: assert the SHAPE of the assignment. The
        # right-hand side must be the bare call and nothing else -- no `or`,
        # no conditional, no default.
        assigns = [n for n in self.walk_branch()
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "matched"
                           for t in n.targets)]
        self.assertEqual(len(assigns), 1, "`matched` is assigned more than "
                                          "once -- one of them is unguarded")
        rhs = assigns[0].value
        self.assertIsInstance(rhs, ast.Call, "`matched` is not a bare call")
        self.assertIsInstance(rhs.func, ast.Name)
        self.assertEqual(rhs.func.id, "find_review_card")

    def test_the_guard_on_the_miss_is_NOT_MATCHED_and_nothing_else(self):
        # The companion half: a correct assignment guarded by `if not True:`
        # or `if False:` is the same hole with the check neutered instead of
        # the value. The test must be exactly `not matched`.
        guards = [n for n in self.walk_branch()
                  if isinstance(n, ast.If)
                  and isinstance(n.test, ast.UnaryOp)
                  and isinstance(n.test.op, ast.Not)
                  and isinstance(n.test.operand, ast.Name)
                  and n.test.operand.id == "matched"]
        self.assertEqual(len(guards), 1,
                         "the miss is not guarded by exactly `if not matched:`")
        # ...and that guard's body must leave the branch, never fall through.
        self.assertTrue(
            any(isinstance(n, ast.Continue) for n in ast.walk(guards[0])),
            "the miss guard does not `continue` -- it falls through to a turn")

    def test_it_honours_the_pending_approval_hold(self):
        # Same rule as typed text: a message may not cancel a popup he has not
        # answered. A new entry point that skips this rebuilds a closed bug.
        b = self.branch()
        self.assertIn("approval_pending()", b)
        self.assertIn('"type": "held"', b)

    def test_it_honours_the_terminal_line_owning_the_conversation(self):
        b = self.branch()
        self.assertIn("terminal_alive()", b)
        self.assertIn("INBOX_DIR", b)


class TheMarkerAgreesAcrossTheWIRE(unittest.TestCase):
    """The one string the server writes and the page reads.

    WALK_NOTE is written into the vault by the server and compared, character
    for character, by the page to decide whether an In Progress card still
    carries Serge's verdict buttons. Two copies of one constant in two
    languages is exactly the drift this project has been bitten by before --
    and the failure is silent and cruel: his approve button would simply stop
    being drawn, on the card he is in the middle of deciding.
    """

    PAGE = (HERE.parent / "jarvis.html").read_text()

    def test_the_page_and_the_server_spell_it_identically(self):
        import re
        m = re.search(r"const WALK_NOTE = '([^']*)'", self.PAGE)
        self.assertTrue(m, "the page has no WALK_NOTE constant")
        self.assertEqual(m.group(1), vws.WALK_NOTE)

    def test_the_note_is_what_the_branch_actually_writes(self):
        # Agreement between two constants proves they match; it does not
        # prove the code still USES one. That exact gap ran uncaught on the
        # session bus this morning, so drive the value, not the spelling:
        # the branch's write must name WALK_NOTE, and WALK_NOTE must be the
        # note the verdict route demands of an `active` card.
        self.assertIn("WALK_NOTE", TheBranchWritesOneThingAndNeverAVerdict
                      .branch())
        i = SRC.index("elif action in TASK_ACTIONS:")
        j = SRC.index("try:", i)
        self.assertIn("WALK_NOTE", SRC[i:j],
                      "the verdict route does not demand the walk note")
        self.assertIn('"active"', SRC[i:j])

    def test_the_marker_is_not_a_status_the_board_could_confuse(self):
        # It must never look like something the note's own vocabulary means.
        self.assertNotIn(vws.WALK_NOTE, ("open", "active", "review", "test",
                                         "waiting-on-serge", "done"))
        self.assertTrue(len(vws.WALK_NOTE) > 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
