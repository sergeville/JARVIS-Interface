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

    def test_real_priorities_note_yields_only_open_tasks(self):
        tasks = vws.read_tasks()
        vws._TASK_CACHE.update(mtime=None, tasks=[])
        self.assertTrue(tasks, "Active Priorities should have open tasks")
        for t in tasks:
            self.assertNotEqual(
                t["status"], "done",
                f"'{t['title']}' is served as done -- it should be checked off "
                "with [x] in the note, or its status is bleeding from below")
            self.assertTrue(t["title"], "every task needs a title")


if __name__ == "__main__":
    unittest.main(verbosity=2)
