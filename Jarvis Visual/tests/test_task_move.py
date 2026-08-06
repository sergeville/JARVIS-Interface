#!/usr/bin/env python3
"""Tests for the approve button: task.py's move() core and the /task-move route.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_task_move.py

WHY THESE EXIST, and why they are the most careful tests in this project.

Serge, 2026-08-06 ~9:26 AM: "all the review, you're waiting for me, but how do
I say I'm done? I approve the review. That's why the list is so long. I cannot
approve, I cannot say nothing. It stays there."

Answering that put an APPROVE button on the board -- and with it, the first
write this page has ever made into the vault. Everything before it was
read-only. So two different things need guarding and they fail in different
ways:

  1. THE WRITE ITSELF (task.py move/save). Active Priorities is edited by
     other live sessions while the server runs. A write that takes a stale
     copy and puts it back silently eats their work, and nobody would find
     out until a task went missing. The guards are: surgical (only one
     task's status/updated/note lines change), mtime-checked (abort, never
     overwrite), and atomic (temp + replace).

  2. THE DOOR (the route). It takes input from a browser, which nothing else
     writing to this vault does. The guards are a closed action vocabulary,
     an exact title match, a length cap, and only_from=('review',) -- so the
     button can move a card OUT OF REVIEW and nothing else. A test here that
     merely proves the happy path would be worthless; most of these prove
     the refusals.

Both modules are imported by path so these cannot drift from what ships. The
note is a FIXTURE in a temp dir -- the real Active Priorities is never touched
by this file, and there is a test at the bottom asserting exactly that.
"""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TASK_PY = ROOT / "vault-tools" / "task.py"
SERVER = HERE.parent / "voice-web-server.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


NOTE_TEMPLATE = """---
status: active
---
# Active Priorities

### Open Tasks

```
- [ ] **Not A Real Task** (example)
  - status: open
```

- [ ] **Alpha the built thing** (learning-ai)
  - status: review
  - owner: voice line
  - priority: P1
  - updated: 2026-08-06 09:00
  - note: built and awaiting his eyes
  - Some prose that must survive untouched. **Bold**, [[links]], colons: here.

- [ ] **Beta in flight** (learning-ai)
  - status: active
  - owner: voice line
  - priority: P2
  - updated: 2026-08-06 09:00
  - note: being worked right now

- [ ] **Alpha the second one** (learning-ai)
  - status: review
  - owner: unassigned
  - priority: P3
  - updated: 2026-08-06 09:00
  - note: also awaiting eyes

### Completed Tasks

- [x] **Alpha an old closed one** (meta) — closed long ago, one line, no fields.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.note = Path(self.tmp.name) / "Active Priorities.md"
        self.note.write_text(NOTE_TEMPLATE)
        self.task = load("_task_under_test", TASK_PY)
        self.task.NOTE = str(self.note)

    def tearDown(self):
        self.tmp.cleanup()

    def status_of(self, title):
        lines = self.note.read_text().splitlines(keepends=True)
        for t, s, e in self.task.blocks(lines):
            if t == title:
                i = self.task.field(lines, s, e, "status")
                return lines[i].split(":", 1)[1].strip()
        return None


class TestTheWrite(Base):
    """The surgical, guarded write -- other sessions edit this note."""

    def test_approve_moves_the_card_to_done(self):
        self.task.move("Alpha the built thing", "done", "APPROVED",
                       exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Alpha the built thing"), "done")

    def test_the_checkbox_follows_the_status(self):
        # The HUD lets the checkbox outrank a stale status field, so the two
        # must never be allowed to disagree.
        self.task.move("Alpha the built thing", "done", "ok",
                       exact=True, only_from=("review",))
        self.assertIn("- [x] **Alpha the built thing**", self.note.read_text())

    def test_send_back_returns_it_to_active_and_unchecks(self):
        self.task.move("Alpha the built thing", "active", "not approved",
                       exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Alpha the built thing"), "active")
        self.assertIn("- [ ] **Alpha the built thing**", self.note.read_text())

    def test_no_other_task_moves(self):
        self.task.move("Alpha the built thing", "done", "ok",
                       exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Beta in flight"), "active")
        self.assertEqual(self.status_of("Alpha the second one"), "review")

    def test_the_prose_survives_byte_for_byte(self):
        before = self.note.read_text()
        self.task.move("Alpha the built thing", "done", "APPROVED",
                       exact=True, only_from=("review",))
        after = self.note.read_text()
        # Every line that is not a field of the moved task is identical.
        self.assertIn("Some prose that must survive untouched. **Bold**, "
                      "[[links]], colons: here.", after)
        self.assertIn("### Completed Tasks", after)
        b = [l for l in before.splitlines() if not l.strip().startswith("- status:")
             and not l.strip().startswith("- updated:")
             and not l.strip().startswith("- note:")
             and not l.startswith("- [")]
        a = [l for l in after.splitlines() if not l.strip().startswith("- status:")
             and not l.strip().startswith("- updated:")
             and not l.strip().startswith("- note:")
             and not l.startswith("- [")]
        self.assertEqual(b, a)

    def test_a_concurrent_write_ABORTS_rather_than_overwrites(self):
        """The one that protects other sessions' work."""
        lines, mtime = self.task.load()
        # Another session writes while we were thinking.
        os.utime(self.note, (0, 0))
        with self.assertRaises(self.task.TaskError):
            self.task.save(lines, mtime)

    def test_the_note_line_records_the_verdict(self):
        self.task.move("Alpha the built thing", "done",
                       "APPROVED by Serge on the board",
                       exact=True, only_from=("review",))
        self.assertIn("APPROVED by Serge on the board", self.note.read_text())


class TestTheRefusals(Base):
    """Most of the value is here: what the button CANNOT do."""

    def test_only_from_review__work_in_flight_is_untouchable(self):
        with self.assertRaises(self.task.TaskError):
            self.task.move("Beta in flight", "done", "x",
                           exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Beta in flight"), "active")

    def test_a_stale_tab_cannot_move_an_already_moved_card(self):
        self.task.move("Alpha the built thing", "done", "ok",
                       exact=True, only_from=("review",))
        # His tab still shows it in Review; a second click must refuse.
        with self.assertRaises(self.task.TaskError):
            self.task.move("Alpha the built thing", "active", "x",
                           exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Alpha the built thing"), "done")

    def test_exact_match__a_substring_cannot_select_another_card(self):
        # "Alpha" matches three entries by substring. Exact must find none,
        # rather than the CLI's ambiguity message -- a button has no human
        # to read a refusal and retype it.
        with self.assertRaises(self.task.TaskError):
            self.task.move("Alpha", "done", "x",
                           exact=True, only_from=("review",))
        self.assertEqual(self.status_of("Alpha the built thing"), "review")

    def test_substring_mode_still_refuses_an_ambiguous_match(self):
        with self.assertRaises(self.task.TaskError) as cm:
            self.task.move("Alpha", "done", "x")
        self.assertIn("ambiguous", str(cm.exception))

    def test_an_unknown_status_is_refused(self):
        with self.assertRaises(self.task.TaskError):
            self.task.move("Alpha the built thing", "archived", "x",
                           exact=True, only_from=("review",))

    def test_the_fenced_legend_is_not_a_task(self):
        with self.assertRaises(self.task.TaskError):
            self.task.move("Not A Real Task", "done", "x", exact=True)

    def test_completed_tasks_below_the_line_are_unreachable(self):
        with self.assertRaises(self.task.TaskError):
            self.task.move("Alpha an old closed one", "active", "x",
                           exact=True)

    def test_a_missing_task_changes_nothing(self):
        before = self.note.read_text()
        with self.assertRaises(self.task.TaskError):
            self.task.move("No Such Task", "done", "x", exact=True)
        self.assertEqual(self.note.read_text(), before)


class FakeRequest:
    def __init__(self, payload, raise_it=False):
        self._p, self._raise = payload, raise_it

    async def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._p


class TestTheRoute(unittest.TestCase):
    """The door: closed vocabulary, caps, and never raising at the caller."""

    @classmethod
    def setUpClass(cls):
        cls.srv = load("voice_web_server", SERVER)

    def call(self, payload, raise_it=False):
        r = asyncio.run(self.srv.task_move(FakeRequest(payload, raise_it)))
        return json.loads(r.body.decode())

    def test_the_action_vocabulary_is_closed(self):
        self.assertEqual(set(self.srv.TASK_ACTIONS), {"approve", "send-back"})

    def test_no_action_can_reach_a_status_outside_the_board(self):
        for status, _note in self.srv.TASK_ACTIONS.values():
            self.assertIn(status, ("done", "active"))

    def test_an_unknown_action_is_refused(self):
        d = self.call({"title": "Alpha the built thing", "status": "done"})
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "unknown action")

    def test_a_raw_status_in_the_body_is_ignored(self):
        # There must be NO path from the browser to an arbitrary status.
        d = self.call({"title": "x", "action": "done"})
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "unknown action")

    def test_a_missing_title_is_refused(self):
        for body in ({"action": "approve"},
                     {"title": "", "action": "approve"},
                     {"title": "   ", "action": "approve"},
                     {"title": 12, "action": "approve"}):
            d = self.call(body)
            self.assertFalse(d["ok"], body)
            self.assertEqual(d["error"], "no task named")

    def test_an_overlong_title_is_refused(self):
        d = self.call({"title": "z" * (self.srv.MAX_TITLE + 1),
                       "action": "approve"})
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "title too long")

    def test_a_body_that_is_not_json_never_raises(self):
        d = self.call(None, raise_it=True)
        self.assertFalse(d["ok"])

    def test_a_refusal_from_the_writer_comes_back_as_a_reason(self):
        # Real note, real writer, a title that cannot exist -> ok:false with a
        # readable reason, never an exception through aiohttp.
        d = self.call({"title": "No Such Task At All Anywhere",
                       "action": "approve"})
        self.assertFalse(d["ok"])
        self.assertTrue(d["error"])

    def test_the_route_is_registered_as_a_POST(self):
        src = SERVER.read_text()
        self.assertIn('web.post("/task-move", task_move)', src)
        self.assertNotIn('web.get("/task-move"', src)

    def test_signals_advertises_the_capability(self):
        self.assertIn('"task_move": True', SERVER.read_text())

    def test_the_route_uses_the_ONE_writer_and_does_not_reimplement_it(self):
        """A second writer would eventually disagree with the first."""
        src = SERVER.read_text()
        i = src.index("async def task_move")
        j = src.index("WHISPER_URL", i)
        body = src[i:j]
        self.assertIn("tool.move", body)
        for forbidden in ("open(", "write_text", "os.replace", "tempfile"):
            self.assertNotIn(forbidden, body,
                             f"the route writes for itself via {forbidden!r}")

    def test_the_route_passes_BOTH_narrowing_guards(self):
        # UPDATED 2026-08-06, not loosened. The drag branch made `only_from`
        # a VARIABLE -- ("review",) for a verdict, None for a drag -- so the
        # old literal search for `only_from=("review",)` at the call site went
        # red against a correct file. It was matching a spelling, not the
        # property. Both halves are now asserted where they actually live, and
        # the behavioural guard is TestTheDrag's
        # test_the_verdict_path_is_UNCHANGED_by_the_new_branch.
        src = SERVER.read_text()
        i = src.index("async def task_move")
        body = src[i:src.index("WHISPER_URL", i)]
        self.assertIn("exact=True", body)
        self.assertIn('only_from = ("review",)', body,
                      "the verdict branch no longer narrows to review")
        self.assertIn("only_from=only_from", body,
                      "the narrowing is computed but never passed to the write")

    def test_the_real_note_is_not_modified_by_the_route_tests(self):
        """These exercise the REAL writer, so prove the real note stood still.

        The first version of this test grepped this file for the string
        "PRIORITIES_FILE.write" -- and matched its own assertion, so it failed
        against correct code. Fourth time in this project that searching
        source has punished the text describing the rule rather than a
        violation of it. The honest measure is the file's own mtime.
        """
        note = self.srv.PRIORITIES_FILE
        self.assertTrue(note.exists())
        before = note.stat().st_mtime_ns
        d = self.call({"title": "No Such Task At All Anywhere",
                       "action": "approve"})
        self.assertFalse(d["ok"])
        self.assertEqual(note.stat().st_mtime_ns, before)


class TestTheDrag(Base):
    """The drag, added 2026-08-06 when Serge unparked it.

    The verdict path is a closed table of WRITES. A drag cannot be -- its whole
    point is that Serge picks the column -- so the closure moves to the STATUS
    SET. These tests are about that boundary holding, because this is the moment
    the page went from writing two values to writing six.
    """

    @classmethod
    def setUpClass(cls):
        cls.srv = load("voice_web_server_drag", SERVER)

    def setUp(self):
        super().setUp()
        # ⚠ THE ROUTE'S OWN TESTS ABOVE ONLY EVER PROVOKE REFUSALS, so they can
        # safely run against the real note. These tests WRITE, so the server's
        # task tool is pinned to this test's temp copy -- a suite that edits
        # Serge's live queue would be a far worse bug than any it could catch.
        self.srv._task_tool = lambda: self.task

    def call(self, payload):
        r = asyncio.run(self.srv.task_move(FakeRequest(payload)))
        return json.loads(r.body.decode())

    def test_the_drag_status_set_is_exactly_the_board(self):
        # If a seventh column is ever added, this fails until someone decides
        # on purpose whether a drag may reach it.
        self.assertEqual(
            list(self.srv.DRAG_STATUSES),
            ["open", "active", "review", "test", "waiting-on-serge", "done"],
        )

    def test_a_drag_moves_a_card_to_any_board_column(self):
        d = self.call({"title": "Beta in flight", "action": "drag",
                       "status": "test"})
        self.assertTrue(d.get("ok"), d)
        self.assertEqual(self.status_of("Beta in flight"), "test")

    def test_a_drag_may_start_ANYWHERE__only_from_does_not_apply(self):
        # The actual widening, asserted rather than assumed: a verdict may only
        # touch a card in Review; a drag is Serge moving his own work.
        self.assertEqual(self.status_of("Beta in flight"), "active")
        d = self.call({"title": "Beta in flight", "action": "drag",
                       "status": "waiting-on-serge"})
        self.assertTrue(d.get("ok"), d)
        self.assertEqual(self.status_of("Beta in flight"), "waiting-on-serge")

    def test_a_status_outside_the_board_is_refused(self):
        for bad in ("archived", "DONE", "", None, 7, "open ", "../../etc"):
            d = self.call({"title": "Beta in flight", "action": "drag",
                           "status": bad})
            self.assertFalse(d.get("ok"), f"accepted {bad!r}")
            self.assertEqual(d["error"], "unknown column")
        self.assertEqual(self.status_of("Beta in flight"), "active")

    def test_a_drag_with_no_status_at_all_is_refused(self):
        d = self.call({"title": "Beta in flight", "action": "drag"})
        self.assertFalse(d.get("ok"))
        self.assertEqual(d["error"], "unknown column")

    def test_a_drag_still_matches_the_title_EXACTLY(self):
        # The verdict path's protection must not be lost on the new branch.
        d = self.call({"title": "Beta", "action": "drag", "status": "test"})
        self.assertFalse(d.get("ok"), "a substring selected a card")
        self.assertEqual(self.status_of("Beta in flight"), "active")

    def test_a_refused_drag_does_not_touch_the_note(self):
        note = self.note.stat().st_mtime_ns
        self.call({"title": "Beta in flight", "action": "drag",
                   "status": "nonsense"})
        self.assertEqual(self.note.stat().st_mtime_ns, note)

    def test_the_note_line_says_who_moved_it(self):
        self.call({"title": "Beta in flight", "action": "drag",
                   "status": "review"})
        body = self.note.read_text()
        self.assertIn("moved by Serge on the board", body)

    def test_the_verdict_path_is_UNCHANGED_by_the_new_branch(self):
        # A drag must not have loosened approve/send-back on the way past.
        d = self.call({"title": "Beta in flight", "action": "approve"})
        self.assertFalse(d.get("ok"), "approve reached a card outside review")
        self.assertEqual(self.status_of("Beta in flight"), "active")


if __name__ == "__main__":
    unittest.main(verbosity=2)
