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
import re
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


WALK_NOTE = "walking through it with Serge -- the verdict is still his"


class TestTheWalkThroughNarrowing(Base):
    """`note_required_for` -- the narrowing that makes a widening safe.

    (Serge, 2026-08-07 ~1:40 PM.) Pressing "walk me through it" moves the
    card into In Progress, because the thinking is work and a board that
    goes quiet is the failure he keeps catching. His approve and send back
    buttons then have to reach an `active` card, or they vanish out from
    under him mid-decision -- so `only_from` had to widen from ("review",)
    to ("review", "active").

    THAT WIDENING IS THE DANGER, and these are the tests that pay for it.
    An `active` card is reachable ONLY while it carries the exact walk
    note; ordinary work in flight stays untouchable, which is the property
    `only_from` existed for in the first place.
    """

    def walk(self, title):
        """Put a card into the state the walk-through button leaves it in."""
        self.task.move(title, "active", WALK_NOTE,
                       exact=True, only_from=("review",))

    def test_a_walked_through_card_CAN_be_approved_from_active(self):
        self.walk("Alpha the built thing")
        self.task.move("Alpha the built thing", "done", "APPROVED",
                       exact=True, only_from=("review", "active"),
                       note_required_for={"active": WALK_NOTE})
        self.assertEqual(self.status_of("Alpha the built thing"), "done")

    def test_ORDINARY_work_in_flight_still_cannot_be_approved(self):
        # The one that matters. "Beta in flight" is real work with a real
        # note; if this ever stops raising, every card in In Progress has
        # an approve button within reach of a stale or hostile page.
        with self.assertRaises(self.task.TaskError):
            self.task.move("Beta in flight", "done", "APPROVED",
                           exact=True, only_from=("review", "active"),
                           note_required_for={"active": WALK_NOTE})
        self.assertEqual(self.status_of("Beta in flight"), "active")

    def test_a_NEAR_MISS_note_is_refused(self):
        # Absent, truncated, extended and re-cased all fail. A marker matched
        # loosely is the same trap as a title matched loosely.
        for near in (WALK_NOTE + " and more", WALK_NOTE[:-1],
                     WALK_NOTE.upper(), "walking through"):
            self.note.write_text(NOTE_TEMPLATE)
            self.task.move("Alpha the built thing", "active", near,
                           exact=True, only_from=("review",))
            with self.assertRaises(self.task.TaskError, msg=near):
                self.task.move("Alpha the built thing", "done", "APPROVED",
                               exact=True, only_from=("review", "active"),
                               note_required_for={"active": WALK_NOTE})
            self.assertEqual(self.status_of("Alpha the built thing"), "active")

    def test_a_card_with_NO_note_line_is_refused(self):
        # Absent is not a match. Defaulting an unlabelled card to "allowed"
        # would hand the whole In Progress column to the verdict buttons.
        text = self.note.read_text().replace(
            "  - note: being worked right now\n", "")
        self.note.write_text(text)
        with self.assertRaises(self.task.TaskError):
            self.task.move("Beta in flight", "done", "APPROVED",
                           exact=True, only_from=("review", "active"),
                           note_required_for={"active": WALK_NOTE})

    def test_review_is_STILL_reachable_without_any_note(self):
        # The narrowing applies only to the status it names. A card in Review
        # is his to answer whatever its note says -- that never changed, and
        # a guard that quietly broke the ordinary path would be worse than
        # the hole it closed.
        self.task.move("Alpha the second one", "done", "APPROVED",
                       exact=True, only_from=("review", "active"),
                       note_required_for={"active": WALK_NOTE})
        self.assertEqual(self.status_of("Alpha the second one"), "done")

    def test_the_narrowing_is_OFF_when_nobody_asks_for_it(self):
        # Every existing caller passes no note_required_for at all; none of
        # them may start refusing.
        self.walk("Alpha the built thing")
        self.task.move("Alpha the built thing", "review", "dragged",
                       exact=True, only_from=None)
        self.assertEqual(self.status_of("Alpha the built thing"), "review")

    def test_the_check_reads_the_note_from_the_SAME_lines_it_writes(self):
        # Structural: the guard must sit inside move(), after load() and
        # before the write, or it is a check with a race under it.
        src = Path(TASK_PY).read_text()
        body = src[src.index("def move("):src.index("\ndef ", src.index("def move(") + 5)]
        self.assertIn("note_required_for", body)
        self.assertLess(body.index("lines, mtime = load()"),
                        body.index("note_required_for and was in"),
                        "the note guard runs before the file is loaded")
        self.assertLess(body.index("note_required_for and was in"),
                        body.index("- status: {status}"),
                        "the note guard runs after the status is rewritten")
        # ...and ordering is not enough, which an injection proved. Moving the
        # note read onto a SECOND `load()` keeps every index above in order
        # while the guard starts checking a different snapshot than the write
        # uses -- a check-then-write race, reintroduced without moving a line.
        # move() reads the file exactly once, and that is the property.
        self.assertEqual(body.count("load()"), 1,
                         "move() loads the note more than once -- the guard "
                         "and the write can now disagree about the file")
        self.assertIn('field(lines, s, e, "note")', body,
                      "the note guard reads from something other than the "
                      "lines the write is about to use")


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
        # INVERTED AGAIN 2026-08-07 on Serge's go, and inverted rather than
        # deleted -- "a verdict may reach only review" and "a verdict may
        # reach review, or the one active card being walked through" cannot
        # both guard this file, and which one is true is a decision he made
        # out loud. The widening exists because pressing "walk me through it"
        # moves the card into In Progress, and his approve and send back
        # buttons have to follow it there. The narrowing that pays for it is
        # asserted in the same breath, because a widening whose guard is
        # optional is just a widening.
        self.assertIn("exact=True", body)
        self.assertIn('only_from = ("review", "active")', body,
                      "the verdict branch no longer reaches the walk-through")
        self.assertIn('note_required = {"active": WALK_NOTE}', body,
                      "the verdict branch widened to active WITHOUT the note "
                      "guard -- ordinary work in flight is now approvable")
        self.assertIn("only_from=only_from", body,
                      "the narrowing is computed but never passed to the write")
        self.assertIn("note_required_for=note_required", body,
                      "the note guard is computed but never passed to the write")
        # The drag branch must still switch BOTH off together.
        self.assertIn("note_required = None", body,
                      "the drag branch does not clear the note guard")

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


class TestTheOwnerIsStamped(Base):
    """The owner field must be WRITTEN, not remembered.

    Serge, 2026-08-06 ~9:05 PM: he caught a card in In Progress with nobody's
    name on it. The cause was not a stale owner -- `add` hardcoded
    "unassigned" and `move` never touched the field, so EVERY card on the
    board was owner-less by construction and the field was decoration.

    These tests guard the fix at the level his own rule points at: fix the
    generator, not the artefact. They stub owner_label() rather than reading
    the real process table, because a test that reads the live machine is
    flaky on the live machine -- the lesson already on this project's record.
    """

    def owner_of(self, title):
        """The owner line of ONE card.

        THIS EXISTS BECAUSE THE FIRST VERSION OF THESE TESTS WAS WORTHLESS.
        They asserted against the whole file, and the fixture holds three
        cards -- one of which already reads `owner: unassigned` and another
        `owner: voice line`. So "the owner was cleared" passed by matching a
        card the test never touched, and the fault injection proved it: two
        real faults (open no longer clearing, and an unknown identity writing
        over a real name) ran with the suite GREEN. Scope the assertion to
        the card under test, or it is guarding the fixture.
        """
        lines = self.note.read_text().splitlines(keepends=True)
        for t, s, e in self.task.blocks(lines):
            if t == title:
                i = self.task.field(lines, s, e, "owner")
                return lines[i].split(":", 1)[1].strip() if i is not None else None
        return None

    def stub_owner(self, value):
        self.task.owner_label = lambda: value

    def test_taking_a_card_stamps_the_running_session(self):
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Beta in flight", "review", "done, awaiting eyes")
        self.assertEqual(self.owner_of("Beta in flight"), "voice line (pid 4242)")

    def test_every_owned_status_stamps(self):
        # active, review and test all mean somebody is holding the work.
        for status in ("active", "review", "test"):
            with self.subTest(status=status):
                self.note.write_text(NOTE_TEMPLATE)
                self.stub_owner("terminal (Jarvis root) (pid 7)")
                self.task.move("Alpha the second one", status, "x")
                self.assertEqual(self.owner_of("Alpha the second one"),
                                 "terminal (Jarvis root) (pid 7)")

    def test_sending_a_card_back_to_the_backlog_clears_the_owner(self):
        # Back to To Do means held by nobody. Leaving a name on it would
        # claim a session is working something it has put down.
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Beta in flight", "active", "working")
        self.assertEqual(self.owner_of("Beta in flight"), "voice line (pid 4242)")
        self.task.move("Beta in flight", "open", "parked")
        self.assertEqual(self.owner_of("Beta in flight"), "unassigned")

    def test_finishing_a_card_KEEPS_the_owner_as_the_record(self):
        # On a closed card the owner is who did it. Clearing it would throw
        # that away at the moment it becomes history.
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Beta in flight", "active", "working")
        self.task.move("Beta in flight", "done", "shipped")
        self.assertEqual(self.owner_of("Beta in flight"), "voice line (pid 4242)")

    def test_waiting_on_serge_KEEPS_the_owner_too(self):
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Beta in flight", "active", "working")
        self.task.move("Beta in flight", "waiting-on-serge", "needs his go")
        self.assertEqual(self.owner_of("Beta in flight"), "voice line (pid 4242)")

    def test_an_UNKNOWN_identity_leaves_the_field_ALONE(self):
        # The HUD's approve button is the live case: the server is not a
        # Claude Code session, so it has no identity to stamp. Writing
        # "unassigned" over a real name there would DESTROY information --
        # a wrong owner reads as fact, a missing one reads as unknown.
        self.stub_owner(None)
        self.task.move("Beta in flight", "review", "x")
        # The fixture's own value, untouched -- and NOT the string "None".
        self.assertEqual(self.owner_of("Beta in flight"), "voice line")

    def test_a_card_with_no_owner_line_is_not_given_one(self):
        # The write stays surgical: this tool edits fields that exist, it
        # does not restructure someone else's block.
        self.note.write_text(NOTE_TEMPLATE.replace(
            "  - owner: voice line\n  - priority: P2\n", "  - priority: P2\n"))
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Beta in flight", "active", "x")
        self.assertNotIn("owner:", self.note.read_text().split(
            "**Beta in flight**")[1].split("- [ ]")[0])

    def test_the_prose_survives_an_owner_stamp(self):
        self.stub_owner("voice line (pid 4242)")
        self.task.move("Alpha the built thing", "test", "x")
        self.assertIn("Some prose that must survive untouched.",
                      self.note.read_text())

    def test_OWNED_is_a_subset_of_the_real_statuses(self):
        # A typo here would silently stop stamping rather than fail.
        for st in self.task.OWNED:
            self.assertIn(st, self.task.STATUSES)

    def test_OWNED_matches_the_board_page(self):
        # Two lists that must agree get a guard that proves they do -- the
        # same reason the jarvis.sh and sample_stack() patterns have one.
        page = (HERE.parent / "jarvis.html").read_text()
        m = re.search(r"BOARD_OWNED\s*=\s*new Set\(\[(.*?)\]\)", page, re.S)
        self.assertIsNotNone(m, "BOARD_OWNED is gone from the page")
        on_page = tuple(re.findall(r"'([a-z-]+)'", m.group(1)))
        self.assertEqual(on_page, tuple(self.task.OWNED))


class TestOwnerLabelIsWired(Base):
    """The label must come from the registry, not be re-derived here.

    A guard nobody calls is not a guard, and a second answer to "which
    channel am I" would drift from the session bus's answer -- which is the
    exact failure the hand-signed board has against the process table.
    """

    def test_owner_label_asks_the_registry(self):
        import types
        fake = types.ModuleType("session_registry")
        fake.whoami = lambda: ("voice line", 99)
        sys.modules["session_registry"] = fake
        try:
            self.assertEqual(self.task.owner_label(), "voice line (pid 99)")
        finally:
            del sys.modules["session_registry"]

    def test_owner_label_is_None_when_the_registry_cannot_say(self):
        import types
        fake = types.ModuleType("session_registry")
        fake.whoami = lambda: None
        sys.modules["session_registry"] = fake
        try:
            self.assertIsNone(self.task.owner_label())
        finally:
            del sys.modules["session_registry"]

    def test_owner_label_survives_a_registry_that_raises(self):
        """A card move is not worth a traceback.

        ⚠ THIS TEST USED TO ASSERT THE OPPOSITE OF ITS OWN NAME -- it said
        "survives" and asserted `assertRaises`, documenting a crash as
        though it were the design. The test-adversary caught it on
        2026-08-07. `owner_label` called whoami() OUTSIDE its try, so a
        registry that threw would take `task.py move` down mid-edit,
        between reading the note and writing it. Every sibling path
        (whoami itself, the bus's _self_identity) swallows and returns
        None; this one now does too, because an identity we cannot compute
        IS the None case, not an error.
        """
        import types
        fake = types.ModuleType("session_registry")
        def boom():
            raise RuntimeError("no process table")
        fake.whoami = boom
        sys.modules["session_registry"] = fake
        try:
            self.assertIsNone(self.task.owner_label())
        finally:
            del sys.modules["session_registry"]

    def test_a_channel_outside_the_vocabulary_is_not_written_to_the_note(self):
        """The board must not trust what the bus refuses.

        This value is f-strung straight into a note Serge reads. The bus
        already vets `channel not in CHANNELS`; the board did not, so the
        two surfaces disagreed about whether the registry's output is
        trusted -- and only one of them renders. Defence in depth today,
        since classify() returns only literals, but the asymmetry is the
        kind that stops being theoretical the moment classify grows a
        branch.
        """
        import types
        fake = types.ModuleType("session_registry")
        fake.whoami = lambda: ("mainframe", 99)
        sys.modules["session_registry"] = fake
        try:
            self.assertIsNone(self.task.owner_label())
        finally:
            del sys.modules["session_registry"]

    def test_a_nonsense_pid_is_not_written_to_the_note(self):
        import types
        for bad in (0, -1, "99", None, True):
            with self.subTest(pid=bad):
                fake = types.ModuleType("session_registry")
                fake.whoami = lambda b=bad: ("voice line", b)
                sys.modules["session_registry"] = fake
                try:
                    self.assertIsNone(self.task.owner_label())
                finally:
                    del sys.modules["session_registry"]



# ---------------------------------------------------------------------------
# THE BOARD CATCHES ITS OWN STALE CARDS
# ---------------------------------------------------------------------------
#
# Found 2026-08-21 by getting it wrong. A card sat in `test` for SIX DAYS
# under "terminal (Jarvis root) (pid 2330)" while nobody proved anything.
# Sweeping by hand found it -- and then I checked whether that session was
# alive with `ps -p 2330`, got a hit, and reported ALIVE. 2330 had become
# `spotlightknowledged`, started that morning. A pid is a number the OS
# RECYCLES; checking that SOMETHING holds it is not checking that the SESSION
# does, and the board's own header has said so since 2026-08-05.
#
# So the rule became code. `active` and `test` are the two statuses that
# claim work is happening NOW, and a claim that can rot unwatched is exactly
# what this project keeps learning must be checked rather than remembered.
#
# THE THIRD ANSWER IS THE POINT. "stale", "ok" and "unknown" are kept apart,
# because an unreadable registry rendering as "the session is dead" would be
# a confident wrong answer -- the failure mode every honesty rule in this
# repo exists to refuse.


STALE_BOARD = """---
status: active
project: meta
type: plan
---
# Active Priorities

### Open Tasks

- [ ] **Ghost the abandoned thing** (learning-ai)
  - status: active
  - owner: terminal (Jarvis root) (pid 2330)
  - priority: P1
  - updated: 2026-08-15 10:10
  - note: nobody has touched this in six days

- [ ] **Live the worked thing** (learning-ai)
  - status: active
  - owner: voice line (pid 4242)
  - priority: P1
  - updated: 2026-08-21 11:00
  - note: genuinely in flight

- [ ] **Backlog the untaken thing** (learning-ai)
  - status: open
  - owner: unassigned
  - priority: P3
  - updated: 2026-08-21 11:00
  - note: nobody claims it and it does not pretend to

- [ ] **Reviewed the finished thing** (learning-ai)
  - status: review
  - owner: terminal (Jarvis root) (pid 2330)
  - priority: P2
  - updated: 2026-08-15 10:10
  - note: built, waiting on his eyes -- the owner is history, not a worker
"""


class TestTheStaleOwnerVerdict(unittest.TestCase):
    """The pure decision, every square of the matrix."""

    def setUp(self):
        self.task = load("_task_stale", TASK_PY)

    def test_a_working_card_owned_by_a_dead_session_is_STALE(self):
        self.assertEqual(
            self.task.stale_owner("active", "voice line (pid 999)", {1, 2}), "stale")

    def test_a_working_card_owned_by_a_live_session_is_ok(self):
        self.assertEqual(
            self.task.stale_owner("active", "voice line (pid 2)", {1, 2}), "ok")

    def test_TEST_counts_as_working_too(self):
        # The six-day card was in `test`, not `active`. Missing this status
        # would have left the exact bug this exists for.
        self.assertEqual(
            self.task.stale_owner("test", "voice line (pid 999)", {1}), "stale")

    def test_REVIEW_is_deliberately_not_working(self):
        # Its owner is the record of who built it. Nobody is expected to be
        # mid-keystroke, so a dead owner there is history, not a lie.
        self.assertEqual(
            self.task.stale_owner("review", "voice line (pid 999)", {1}), "ok")

    def test_open_and_done_and_waiting_are_never_stale(self):
        for st in ("open", "done", "waiting-on-serge"):
            self.assertEqual(
                self.task.stale_owner(st, "voice line (pid 999)", {1}), "ok", st)

    def test_unassigned_is_honest_rather_than_stale(self):
        self.assertEqual(self.task.stale_owner("active", "unassigned", {1}), "ok")
        self.assertEqual(self.task.stale_owner("active", "", {1}), "ok")
        self.assertEqual(self.task.stale_owner("active", None, {1}), "ok")

    def test_AN_UNREADABLE_REGISTRY_IS_UNKNOWN_AND_NEVER_STALE(self):
        # The whole reason the third answer exists. Collapsing None into an
        # empty set would mark EVERY working card dead the moment the
        # registry hiccups -- a confident wrong answer at the worst moment.
        self.assertEqual(
            self.task.stale_owner("active", "voice line (pid 5)", None), "unknown")

    def test_an_owner_naming_no_pid_is_unknown_not_stale(self):
        self.assertEqual(
            self.task.stale_owner("active", "some human", {1}), "unknown")

    def test_the_pid_is_read_from_the_label_not_guessed(self):
        self.assertEqual(self.task.owner_pid("voice line (pid 29186)"), 29186)
        self.assertIsNone(self.task.owner_pid("unassigned"))
        self.assertIsNone(self.task.owner_pid(None))

    def test_a_pid_INSIDE_the_channel_name_does_not_fool_it(self):
        # The label is built by owner_label(); this is the shape it makes.
        self.assertEqual(self.task.owner_pid("terminal (Jarvis root) (pid 7)"), 7)

    def test_IT_READS_THE_PID_NOT_MERELY_A_NUMBER(self):
        # My own injection round found this one MISSED: loosening the regex
        # to r"(\d+)" left every test above green, because none of their
        # labels carried a digit anywhere else. A number in the channel name
        # would then be read AS the pid -- and the pid is the entire basis
        # for deciding a session is gone, so a wrong one condemns a live
        # card or blesses a dead one.
        self.assertEqual(self.task.owner_pid("voice line 2 (pid 29186)"), 29186)
        self.assertEqual(self.task.owner_pid("terminal 3 (Jarvis Visual) (pid 7)"), 7)
        # ...and a bare number with no "pid" is not a pid at all.
        self.assertIsNone(self.task.owner_pid("session 4242"))

    def test_A_MALFORMED_OWNER_RETURNS_None_AND_NEVER_RAISES(self):
        # Second miss my own round found: loosening \d+ to \d* leaves the
        # regex MATCHING with an empty group, and int("") raises. This runs
        # inside `task.py list`, which Serge types -- a traceback there means
        # he cannot see his board at all, over one malformed line. The board
        # going blank is a strictly worse failure than the stale card it was
        # written to catch.
        for junk in ("voice line (pid )", "voice line (pid", "(pid: 12)",
                     "pid", "", "   "):
            self.assertIsNone(self.task.owner_pid(junk), junk)

    def test_the_whole_verdict_survives_a_malformed_owner(self):
        # And the caller must degrade to "unknown", not explode.
        self.assertEqual(
            self.task.stale_owner("active", "voice line (pid )", {1}), "unknown")


class TestTheStaleCommandGatesIt(unittest.TestCase):
    """Driven end to end against a real board file, with a real exit code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.note = Path(self.tmp.name) / "Active Priorities.md"
        self.note.write_text(STALE_BOARD)
        self.task = load("_task_stale_cmd", TASK_PY)
        self.task.NOTE = str(self.note)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, live):
        import io, contextlib
        self.task.live_pids = lambda: live
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.task.cmd_stale()
        return rc, buf.getvalue()

    def test_IT_GOES_RED_when_a_working_card_has_a_dead_owner(self):
        rc, out = self._run({4242})
        self.assertEqual(rc, 1)
        self.assertIn("Ghost the abandoned thing", out)

    def test_it_names_ONLY_the_dead_one(self):
        rc, out = self._run({4242})
        self.assertNotIn("Live the worked thing", out)
        self.assertNotIn("Backlog the untaken thing", out)
        # review is history, not a worker -- naming it would be noise, and a
        # nag you cannot cheaply satisfy becomes noise, which is this file's
        # own founding lesson.
        self.assertNotIn("Reviewed the finished thing", out)

    def test_it_goes_GREEN_when_every_working_owner_is_alive(self):
        rc, out = self._run({4242, 2330})
        self.assertEqual(rc, 0)
        self.assertIn("live owner", out)

    def test_AN_UNREADABLE_REGISTRY_DOES_NOT_CONDEMN_THE_BOARD(self):
        rc, out = self._run(None)
        self.assertEqual(rc, 0)
        self.assertIn("could not read", out)
        self.assertNotIn("STALE", out)

    def test_list_MARKS_the_stale_card_and_says_so_again_at_the_bottom(self):
        # The marks scroll away on a board this long; a warning nobody sees
        # is not a warning.
        import io, contextlib
        self.task.live_pids = lambda: {4242}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.task.cmd_list()
        out = buf.getvalue()
        self.assertIn("OWNER IS GONE", out)
        self.assertIn("claim a worker who no longer exists", out)

    def test_list_still_prints_every_card(self):
        import io, contextlib
        self.task.live_pids = lambda: {4242}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.task.cmd_list()
        out = buf.getvalue()
        for t in ("Ghost the abandoned thing", "Live the worked thing",
                  "Backlog the untaken thing", "Reviewed the finished thing"):
            self.assertIn(t, out)


class TestLivePidsIsHonest(unittest.TestCase):

    def setUp(self):
        self.task = load("_task_live", TASK_PY)

    def test_it_returns_None_rather_than_an_empty_set_when_it_cannot_look(self):
        saved = sys.modules.pop("session_registry", None)
        try:
            sys.modules["session_registry"] = None   # import raises
            self.assertIsNone(self.task.live_pids())
        finally:
            sys.modules.pop("session_registry", None)
            if saved is not None:
                sys.modules["session_registry"] = saved

    def test_an_ENDED_session_is_not_counted_as_live(self):
        import types
        fake = types.ModuleType("session_registry")
        fake.read_sessions = lambda: [
            {"pid": 1, "ended": False}, {"pid": 2, "ended": True}]
        saved = sys.modules.get("session_registry")
        sys.modules["session_registry"] = fake
        try:
            self.assertEqual(self.task.live_pids(), {1})
        finally:
            if saved is not None:
                sys.modules["session_registry"] = saved
            else:
                del sys.modules["session_registry"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
