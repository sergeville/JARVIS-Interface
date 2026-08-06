#!/usr/bin/env python3
"""Tests for read_tasks() -- the Active Priorities parser behind the HUD task card.

Run:  ./tests/run-tests.sh          (from Jarvis Visual/)
   or  python3 tests/test_read_tasks.py

Why this file exists: on 2026-08-05 the card reported the parked palette task
as "done". A completed "- [x]" entry neither started a new task nor closed the
open one above it, so every "- status: done" under a finished entry attached
itself to the last open task. The card was lying about the queue. Serge's rule
from that morning: every change gets a test, and passing tests are the gate.

These run against fixtures in a temp dir -- the real Active Priorities note is
never read or written here.
"""

import importlib.util
import tempfile
import time
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


def parse(note_text: str) -> list[dict]:
    """Run the real read_tasks() against a fixture, leaving the real file alone."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "Active Priorities.md"
        f.write_text(note_text)
        real = vws.PRIORITIES_FILE
        vws.PRIORITIES_FILE = f
        vws._TASK_CACHE.update(mtime=None, tasks=[])   # defeat the mtime cache
        try:
            return vws.read_tasks()
        finally:
            vws.PRIORITIES_FILE = real
            vws._TASK_CACHE.update(mtime=None, tasks=[])


HEADER = "### Open Tasks\n\n"


class TestCompletedTaskBleed(unittest.TestCase):
    """The regression this file was created for."""

    def test_done_task_does_not_overwrite_the_open_task_above_it(self):
        tasks = parse(HEADER + (
            "- [ ] **Still open** (learning-ai)\n"
            "  - status: open\n"
            "  - priority: P3\n"
            "  - note: parked on Serge's word\n"
            "\n"
            "- [x] **Finished thing** (learning-ai)\n"
            "  - status: done\n"
            "  - priority: P1\n"
            "  - note: closed yesterday\n"))
        self.assertEqual(len(tasks), 1, "a [x] entry must not become a card")
        self.assertEqual(tasks[0]["title"], "Still open")
        self.assertEqual(tasks[0]["status"], "open", "bled from the [x] below")
        self.assertEqual(tasks[0]["priority"], "P3")
        self.assertEqual(tasks[0]["note"], "parked on Serge's word")

    def test_open_task_after_a_done_task_still_parses(self):
        tasks = parse(HEADER + (
            "- [x] **Finished** (meta)\n"
            "  - status: done\n"
            "\n"
            "- [ ] **Live one** (meta)\n"
            "  - status: active\n"
            "  - owner: voice line\n"))
        self.assertEqual([t["title"] for t in tasks], ["Live one"])
        self.assertEqual(tasks[0]["status"], "active")
        self.assertEqual(tasks[0]["owner"], "voice line")

    def test_prose_bullets_under_a_done_task_are_ignored(self):
        """A [x] entry's loose prose bullets must not reattach upward either."""
        tasks = parse(HEADER + (
            "- [ ] **Open one** (meta)\n"
            "  - status: waiting-on-serge\n"
            "\n"
            "- [x] **Closed one** (meta)\n"
            "  - **PROVEN 8:04 PM: it worked** — details here\n"
            "  - status: done\n"
            "  - owner: someone else\n"))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "waiting-on-serge")
        self.assertEqual(tasks[0]["owner"], "unassigned")


class TestFieldParsing(unittest.TestCase):

    def test_all_fields_and_defaults(self):
        tasks = parse(HEADER + (
            "- [ ] **Bare task** (personal)\n"
            "\n"
            "- [ ] **Full task** (learning-ai)\n"
            "  - status: active\n"
            "  - owner: voice line\n"
            "  - priority: P2\n"
            "  - updated: 2026-08-05 08:26\n"
            "  - note: one line of state\n"))
        bare, full = tasks
        self.assertEqual(bare["status"], "open")
        self.assertEqual(bare["owner"], "unassigned")
        self.assertEqual(bare["priority"], "")
        self.assertEqual(bare["project"], "personal")
        self.assertEqual(full["status"], "active")
        self.assertEqual(full["updated"], "2026-08-05 08:26")
        self.assertEqual(full["note"], "one line of state")
        self.assertEqual(full["project"], "learning-ai")

    def test_wikilinks_are_stripped(self):
        tasks = parse(HEADER + (
            "- [ ] **Linked** (meta)\n"
            "  - note: see [[Voice Line]] and [[Jarvis Conventions]]\n"))
        self.assertEqual(tasks[0]["note"],
                         "see Voice Line and Jarvis Conventions")

    def test_note_keeps_text_after_a_colon(self):
        """partition() splits on the FIRST colon -- the rest must survive."""
        tasks = parse(HEADER + (
            "- [ ] **Colons** (meta)\n"
            "  - note: Serge, 8:20 AM: they're too big\n"))
        self.assertEqual(tasks[0]["note"], "Serge, 8:20 AM: they're too big")

    def test_unknown_keys_are_ignored(self):
        tasks = parse(HEADER + (
            "- [ ] **Task** (meta)\n"
            "  - status: open\n"
            "  - somethingelse: ignore me\n"))
        self.assertNotIn("somethingelse", tasks[0])


class TestBoundaries(unittest.TestCase):

    def test_stops_at_completed_tasks_section(self):
        tasks = parse(HEADER + (
            "- [ ] **Real** (meta)\n"
            "  - status: open\n"
            "\n"
            "### Completed Tasks\n\n"
            "- [ ] **Should not appear** (meta)\n"))
        self.assertEqual([t["title"] for t in tasks], ["Real"])

    def test_code_fence_contents_are_skipped(self):
        """The note's own legend is a fenced example -- it must not become a task."""
        tasks = parse(HEADER + (
            "```\n"
            "- [ ] **Title** (project)\n"
            "  - status: open | active\n"
            "```\n\n"
            "- [ ] **Actual** (meta)\n"
            "  - status: active\n"))
        self.assertEqual([t["title"] for t in tasks], ["Actual"])

    def test_empty_and_missing_files(self):
        self.assertEqual(parse(""), [])
        real = vws.PRIORITIES_FILE
        vws.PRIORITIES_FILE = Path("/nonexistent/nope.md")
        vws._TASK_CACHE.update(mtime=None, tasks=[])
        try:
            self.assertEqual(vws.read_tasks(), [])   # falls back, never raises
        finally:
            vws.PRIORITIES_FILE = real
            vws._TASK_CACHE.update(mtime=None, tasks=[])


class TestAgainstTheRealNote(unittest.TestCase):
    """Guards the live file: the card is only as good as what it parses."""

    def test_real_priorities_note_serves_no_STALE_done_task(self):
        """Inverted 2026-08-06, deliberately, not loosened.

        This used to assert that NOTHING is ever served as done -- which was
        right while a finished task could only reach the card by bleeding its
        status upward. Serge then asked for finished work to be visible for
        the rest of its day, so `done` is now a legitimate state to serve and
        the old assertion would forbid the feature.

        What is still worth guarding is the half that was never about the
        checkbox: a served `done` task must carry TODAY's stamp. Anything
        else is either the old bleed bug or an expiry that stopped working,
        and both look identical from the card.
        """
        tasks = vws.read_tasks()
        vws._TASK_CACHE.update(mtime=None, tasks=[])
        self.assertTrue(tasks, "Active Priorities should have open tasks")
        today = time.strftime("%Y-%m-%d")
        for t in tasks:
            if t["status"] == "done":
                self.assertEqual(
                    t["updated"][:10], today,
                    f"'{t['title']}' is served as done but was not closed "
                    "today -- either it is bleeding its status from an entry "
                    "below, or the expiry has stopped running")
            self.assertTrue(t["title"], "every task needs a title")


class TestDoneTimeToLive(unittest.TestCase):
    """Serge, 2026-08-06: "it should be a time to live before it does
    disappear, so the user would see it done. Maybe the next day it's
    disappeared."

    The rule: a finished task stays for the rest of the day it was closed and
    is gone at the next day's rollover. These fix that in place, because the
    whole value of the feature is the window -- too short and he never sees
    it land, too long and DONE quietly becomes an archive.
    """

    TODAY = time.strftime("%Y-%m-%d")

    def test_a_task_closed_TODAY_is_served_as_done(self):
        tasks = parse(HEADER + (
            "- [x] **Shipped this morning** (learning-ai)\n"
            "  - status: done\n"
            "  - priority: P2\n"
            f"  - updated: {self.TODAY} 06:40\n"
            "  - note: proven in his own eyes\n"))
        self.assertEqual(len(tasks), 1, "a task closed today must be visible")
        self.assertEqual(tasks[0]["title"], "Shipped this morning")
        self.assertEqual(tasks[0]["status"], "done")
        self.assertEqual(tasks[0]["priority"], "P2")

    def test_a_task_closed_YESTERDAY_is_gone(self):
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        tasks = parse(HEADER + (
            "- [x] **Shipped yesterday** (learning-ai)\n"
            "  - status: done\n"
            f"  - updated: {yesterday} 22:10\n"))
        self.assertEqual(tasks, [], "yesterday's work is still on the board")

    def test_a_finished_task_with_NO_stamp_is_dropped(self):
        """The condensed one-liners under Completed Tasks have no fields.

        Defaulting an undated finished item to *visible* would slowly fill
        the column with everything ever finished -- the exact opposite of
        what he asked for.
        """
        tasks = parse(HEADER + "- [x] **Closed long ago** (meta) — details\n")
        self.assertEqual(tasks, [])

    def test_the_CHECKBOX_outranks_a_stale_status_field(self):
        """A checked entry whose status line was never updated is still done.

        Otherwise a closed task reappears in WAITING ON YOU, which is worse
        than not showing it at all: it asks him for something twice.
        """
        tasks = parse(HEADER + (
            "- [x] **Closed but the field says otherwise** (meta)\n"
            "  - status: waiting-on-serge\n"
            f"  - updated: {self.TODAY} 09:00\n"))
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "done")

    def test_a_done_task_still_does_not_bleed_into_the_one_above(self):
        """The 2026-08-05 regression, re-asserted under the new behaviour.

        This is the case that could quietly come back: the [x] branch now
        CREATES a task instead of clearing the pointer, so if it ever stopped
        reassigning `task`, every field below would land on the open entry
        above -- the original bug, wearing the new feature's clothes.
        """
        tasks = parse(HEADER + (
            "- [ ] **Still open** (learning-ai)\n"
            "  - status: open\n"
            "  - priority: P3\n"
            "\n"
            "- [x] **Finished today** (learning-ai)\n"
            "  - status: done\n"
            "  - priority: P1\n"
            f"  - updated: {self.TODAY} 06:00\n"))
        by_title = {t["title"]: t for t in tasks}
        self.assertEqual(by_title["Still open"]["status"], "open")
        self.assertEqual(by_title["Still open"]["priority"], "P3")
        self.assertEqual(by_title["Finished today"]["priority"], "P1")

    def test_the_private_flag_never_reaches_the_page(self):
        """`_closed` is an implementation detail of the expiry pass."""
        tasks = parse(HEADER + (
            "- [x] **Done today** (meta)\n"
            f"  - updated: {self.TODAY} 07:00\n"))
        self.assertNotIn("_closed", tasks[0])

    def test_completed_section_entries_are_still_never_read(self):
        """Belt and braces: expiry is the second line of defence, not the first."""
        tasks = parse(HEADER + (
            "- [ ] **Open** (meta)\n"
            "\n"
            "### Completed Tasks\n\n"
            "- [x] **Closed today somehow** (meta)\n"
            f"  - updated: {self.TODAY} 05:00\n"))
        self.assertEqual([t["title"] for t in tasks], ["Open"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
