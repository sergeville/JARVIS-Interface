"""read_ideas() -- the parser behind the HUD's IDEAS panel.

Ideas.md is the other queue: what Serge has NOT decided yet. The parser
mirrors it exactly the way read_tasks() mirrors Active Priorities, and the
tests here are mostly about the two ways a mirror lies -- showing something
that is not there, and hiding something that is.

The one test that is not about parsing at all is the last class. It pins the
absence of an elapsed-time field, because that absence is a decision Serge
and Jarvis reached deliberately and a future session would otherwise "fix"
it by adding a helpful little age counter.
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "Jarvis Visual" / "voice-web-server.py"

spec = importlib.util.spec_from_file_location("vws_ideas", SRC)
vws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vws)


class Base(unittest.TestCase):
    def parse(self, text):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "Ideas.md"
            f.write_text(text)
            saved = vws.IDEAS_FILE
            vws.IDEAS_FILE = f
            vws._IDEA_CACHE["mtime"] = None
            try:
                return vws.read_ideas()
            finally:
                vws.IDEAS_FILE = saved
                vws._IDEA_CACHE["mtime"] = None


class TheMirrorShowsWhatIsThere(Base):
    def test_an_idea_carries_its_title_gist_and_raised_date(self):
        got = self.parse(
            "## Open ideas\n\n### A better mousetrap\n"
            "- raised: 2026-08-07\n- gist: catch mice, but nicer.\n")
        self.assertEqual(got, [{"title": "A better mousetrap",
                                "raised": "2026-08-07",
                                "gist": "catch mice, but nicer."}])

    def test_several_ideas_keep_the_notes_own_order(self):
        got = self.parse("## Open ideas\n### One\n- raised: 2026-01-01\n"
                         "### Two\n- raised: 2026-01-02\n")
        self.assertEqual([i["title"] for i in got], ["One", "Two"])

    def test_an_idea_with_no_fields_still_appears(self):
        # The block is a courtesy to the panel; the idea is the point. An
        # entry someone typed in a hurry must not vanish for want of a colon.
        got = self.parse("## Open ideas\n### Just a thought\n\nsome prose\n")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["title"], "Just a thought")

    def test_wikilink_brackets_are_stripped(self):
        got = self.parse("## Open ideas\n### T\n- gist: see [[Some Note]] first\n")
        self.assertEqual(got[0]["gist"], "see Some Note first")


class TheMirrorHidesNothingAndInventsNothing(Base):
    def test_the_fenced_EXAMPLE_is_not_read_as_an_idea(self):
        # The note documents its own shape, in a fence, using this exact
        # block. Counting it would put a phantom "Title" idea on the panel
        # forever -- the same trap that once made task.py write new cards
        # INSIDE the legend's code fence where the server could not see them.
        got = self.parse(
            "## The shape of an entry\n\n```\n### Title\n"
            "- raised: YYYY-MM-DD\n- gist: one line\n```\n\n"
            "## Open ideas\n### Real one\n- raised: 2026-08-07\n")
        self.assertEqual([i["title"] for i in got], ["Real one"])

    def test_a_fence_INSIDE_an_idea_does_not_spawn_phantom_ideas(self):
        # THE TEST ABOVE PROVED NOTHING ABOUT FENCES, and an injection said
        # so: its fenced example sits above "## Open ideas", where the
        # section guard already ignores it, so deleting the fence-skip
        # entirely left the suite green. The fence that actually matters is
        # one INSIDE an idea -- an idea whose prose shows a snippet, which
        # is exactly what an idea about this system would do.
        got = self.parse(
            "## Open ideas\n\n### A real idea\n- gist: it has an example\n\n"
            "```\n### Not an idea\n- gist: this is a code sample\n```\n\n"
            "### Another real one\n- gist: still here\n")
        self.assertEqual([i["title"] for i in got],
                         ["A real idea", "Another real one"])

    def test_a_fenced_field_does_not_overwrite_the_real_one(self):
        # The subtler half: even with no phantom heading, a `- gist:` line
        # inside a fence would be read as the open idea's own field and
        # silently replace what Serge actually wrote.
        got = self.parse(
            "## Open ideas\n\n### Real\n- gist: the true one\n\n"
            "```\n- gist: a sample from the docs\n```\n")
        self.assertEqual(got[0]["gist"], "the true one")

    def test_prose_ABOVE_the_open_ideas_heading_is_not_an_idea(self):
        got = self.parse("# Ideas\n\n### Why this is a note\n"
                         "- gist: not an idea, an explanation\n\n"
                         "## Open ideas\n### The only one\n")
        self.assertEqual([i["title"] for i in got], ["The only one"])

    def test_a_LATER_section_ends_the_list(self):
        # Anything filed under a following `##` -- declined ideas, an
        # archive, whatever the note grows -- is not open work-in-waiting
        # and must not be drawn as though it were.
        got = self.parse("## Open ideas\n### Live\n\n"
                         "## Declined\n### Dead\n- gist: no\n")
        self.assertEqual([i["title"] for i in got], ["Live"])

    def test_a_missing_file_is_an_empty_list_not_a_crash(self):
        saved = vws.IDEAS_FILE
        vws.IDEAS_FILE = pathlib.Path("/nonexistent/Ideas.md")
        vws._IDEA_CACHE["mtime"] = None
        try:
            self.assertEqual(vws.read_ideas(), [])
        finally:
            vws.IDEAS_FILE = saved
            vws._IDEA_CACHE["mtime"] = None

    def test_the_real_note_parses_and_every_idea_has_a_title(self):
        # Tests prove the code; only running it against the real thing proves
        # the installation. This file exists and is the panel's actual input.
        vws._IDEA_CACHE["mtime"] = None
        got = vws.read_ideas()
        self.assertTrue(got, "the real Ideas.md yielded nothing")
        for i in got:
            self.assertTrue(i["title"].strip(), f"a titleless idea: {i}")


class ItNeverCountsHowLongAnIdeaHasWaited(Base):
    """The absence that is a decision, not an omission.

    Serge, 2026-08-07: the idea side of this system has to be safe to be
    wrong in. The board is allowed to nag -- that is its job, and its virtue
    is that it cannot be argued with. This panel needs the opposite: the
    moment it starts measuring how long an idea has sat, it is a machine
    telling him he owes it an answer, and he stops saying half-formed things.
    That is where the good ideas start.
    """

    AGE_WORDS = ("age", "days_ago", "elapsed", "stale", "since", "waiting",
                 "overdue", "days")

    def test_no_idea_field_measures_elapsed_time(self):
        got = self.parse("## Open ideas\n### T\n- raised: 2020-01-01\n")
        for key in got[0]:
            self.assertNotIn(key.lower(), self.AGE_WORDS,
                             f"the panel grew an elapsed-time field: {key}")

    def test_the_parser_does_not_reach_for_the_clock(self):
        # A behavioural cousin of the above: an age has to come from
        # somewhere, and there is no clock in this function to get it from.
        import inspect
        body = inspect.getsource(vws.read_ideas)
        for call in ("time.time", "datetime", "strftime", "date.today"):
            self.assertNotIn(call, body,
                             f"read_ideas consults the clock ({call}) -- the "
                             "only date here is the one Serge said out loud")

    def test_the_reason_is_written_where_the_next_person_will_look(self):
        body = vws.read_ideas.__doc__ or ""
        self.assertIn("nag", body.lower(),
                      "the reason for the missing age field is not recorded "
                      "at the function -- a future session will add it back "
                      "as a helpful little counter")


if __name__ == "__main__":
    unittest.main(verbosity=2)
