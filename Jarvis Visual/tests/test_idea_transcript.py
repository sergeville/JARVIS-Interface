"""read_idea_transcript() -- the spoken words behind an idea.

Serge, 2026-08-07 ~6:12 PM, right after the expand landed: "and then we
figured it would be transcript."

Two of these tests are not about parsing and are the reason the file exists.

The first is the PATH test. This feature reads a date out of a hand-edited
vault note and turns it into a file on disk -- which is the classic shape of
a traversal bug. It does not have one, because no path is ever CONSTRUCTED:
the directory is listed and a parsed date can only match a key already in it.
That is a property of the implementation, not of the input, so it is pinned
here -- the next session to "simplify" this into an f-string will trip it.

The second is the NO-SILENT-CAP test. A bounded answer that does not say it
is bounded reads as the whole conversation, which is worse than no answer.
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "Jarvis Visual" / "voice-web-server.py"

spec = importlib.util.spec_from_file_location("vws_idea_tx", SRC)
vws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vws)

IDEAS_HEAD = "# Ideas\n\n## Open ideas\n\n"


def tx_line(hhmmss, who, text):
    return f"- **{hhmmss} {who}:** {text}"


class Base(unittest.TestCase):
    """Runs the real reader against a temporary note and a temporary day."""

    def run_it(self, note, days=None, index=0):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            ideas = tmp / "Ideas.md"
            ideas.write_text(IDEAS_HEAD + note)
            txdir = tmp / "transcripts"
            txdir.mkdir()
            for day, lines in (days or {}).items():
                (txdir / f"{day}.md").write_text("\n".join(lines) + "\n")
            saved_ideas = vws.IDEAS_FILE
            saved_dir = vws.voice_signals.TRANSCRIPTS_DIR
            vws.IDEAS_FILE = ideas
            vws.voice_signals.TRANSCRIPTS_DIR = txdir
            vws._IDEA_CACHE["mtime"] = None
            try:
                return vws.read_idea_transcript(index)
            finally:
                vws.IDEAS_FILE = saved_ideas
                vws.voice_signals.TRANSCRIPTS_DIR = saved_dir
                vws._IDEA_CACHE["mtime"] = None

    def anchors(self, note, index=0):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ideas = pathlib.Path(tmp) / "Ideas.md"
            ideas.write_text(IDEAS_HEAD + note)
            saved = vws.IDEAS_FILE
            vws.IDEAS_FILE = ideas
            vws._IDEA_CACHE["mtime"] = None
            try:
                return vws._idea_anchors(vws.read_ideas()[index])
            finally:
                vws.IDEAS_FILE = saved
                vws._IDEA_CACHE["mtime"] = None


class Anchors(Base):
    """The times come out of the prose, because that is where they already are."""

    def test_a_time_beside_a_date_is_read_as_that_date(self):
        got = self.anchors("### T\n- raised: 2026-08-01\n\n"
                           "Serge's, 2026-08-07 ~7:56 AM, from an image.\n")
        self.assertEqual(got, [("2026-08-07", 7 * 3600 + 56 * 60)])

    def test_a_bare_time_falls_back_to_the_raised_date(self):
        got = self.anchors("### T\n- raised: 2026-08-03\n\n"
                           "Came off the board ~4:40 PM.\n")
        self.assertEqual(got, [("2026-08-03", 16 * 3600 + 40 * 60)])

    def test_a_bare_time_inherits_the_date_most_recently_named(self):
        # The write-up habit this exists for: name the day once, then keep
        # citing times against it.
        got = self.anchors("### T\n- raised: 2026-08-01\n\n"
                           "On 2026-08-07 he said it at 9:00 AM.\n"
                           "Then, ~1:00 PM, a widening.\n")
        self.assertEqual(got, [("2026-08-07", 9 * 3600),
                               ("2026-08-07", 13 * 3600)])

    def test_noon_and_midnight_are_not_off_by_twelve_hours(self):
        got = self.anchors("### T\n- raised: 2026-08-07\n\n"
                           "at 12:30 AM and again at 12:30 PM.\n")
        self.assertEqual(got, [("2026-08-07", 30 * 60),
                               ("2026-08-07", 12 * 3600 + 30 * 60)])

    def test_the_same_moment_named_twice_is_one_anchor(self):
        got = self.anchors("### T\n- raised: 2026-08-07\n\n"
                           "He said it ~4:40 PM.\nAgain at 4:40 PM.\n")
        self.assertEqual(len(got), 1)

    def test_a_write_up_with_no_time_yields_nothing_rather_than_guessing(self):
        # The failure mode this forbids: falling back to "the whole raised
        # day", which would hand back an entire conversation as though it
        # were about this one idea.
        self.assertEqual(
            self.anchors("### T\n- raised: 2026-08-07\n\nJust prose.\n"), [])

    def test_an_impossible_clock_is_ignored_not_wrapped_around(self):
        self.assertEqual(
            self.anchors("### T\n- raised: 2026-08-07\n\nversion 13:99 PM\n"),
            [])

    def test_the_anchor_count_is_capped(self):
        body = " ".join(f"{h}:00 AM" for h in range(1, 12))
        got = self.anchors(f"### T\n- raised: 2026-08-07\n\n{body}\n")
        self.assertEqual(len(got), vws.IDEA_TX_MAX_ANCHORS)


class Windows(Base):
    def test_it_returns_the_lines_around_the_moment_and_labels_the_window(self):
        r = self.run_it(
            "### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n",
            {"2026-08-07": [tx_line("10:00:05", "Serge", "the idea"),
                            tx_line("10:01:00", "Jarvis", "the answer")]})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["windows"]), 1)
        w = r["windows"][0]
        self.assertEqual([x["text"] for x in w["lines"]],
                         ["the idea", "the answer"])
        self.assertEqual([x["who"] for x in w["lines"]], ["Serge", "Jarvis"])
        # The note's times are approximate, so the stretch of day being shown
        # is stated rather than implied.
        self.assertEqual((w["from"], w["to"]), ("9:55 AM", "10:20 AM"))

    def test_it_reaches_back_before_the_moment_and_forward_after_it(self):
        r = self.run_it(
            "### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n",
            {"2026-08-07": [tx_line("09:56:00", "Serge", "run-up"),
                            tx_line("10:19:00", "Jarvis", "talking it through"),
                            tx_line("09:40:00", "Serge", "too early"),
                            tx_line("10:40:00", "Serge", "too late")]})
        self.assertEqual([x["text"] for x in r["windows"][0]["lines"]],
                         ["run-up", "talking it through"])

    def test_two_nearby_moments_become_one_window_not_two(self):
        # Otherwise the same conversation is served twice under two headings,
        # which reads as two separate discussions of the same idea.
        r = self.run_it(
            "### T\n- raised: 2026-08-07\n\nAt 10:00 AM, then 10:10 AM.\n",
            {"2026-08-07": [tx_line("10:05:00", "Serge", "once")]})
        self.assertEqual(len(r["windows"]), 1)
        self.assertEqual(len(r["windows"][0]["lines"]), 1)

    def test_two_distant_moments_stay_two_windows(self):
        r = self.run_it(
            "### T\n- raised: 2026-08-07\n\nAt 8:00 AM, then 4:00 PM.\n",
            {"2026-08-07": [tx_line("08:01:00", "Serge", "morning"),
                            tx_line("16:01:00", "Serge", "afternoon")]})
        self.assertEqual([w["lines"][0]["text"] for w in r["windows"]],
                         ["morning", "afternoon"])


class BothChannelsOfADay(Base):
    """Serge had two conversations at once all day. One window shows both.

    Added when the typed side started recording itself, on his "so we don't
    lose anything" -- until then an idea thought out at a keyboard had no
    words behind it at all, and the fold said so honestly while showing
    nothing.
    """

    def run_two(self, voice, terminal):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            ideas = tmp / "Ideas.md"
            ideas.write_text(IDEAS_HEAD
                             + "### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n")
            txdir = tmp / "transcripts"
            txdir.mkdir()
            (txdir / "2026-08-07.md").write_text("\n".join(voice) + "\n")
            (txdir / "2026-08-07-terminal.md").write_text(
                "\n".join(terminal) + "\n")
            saved = (vws.IDEAS_FILE, vws.voice_signals.TRANSCRIPTS_DIR)
            vws.IDEAS_FILE = ideas
            vws.voice_signals.TRANSCRIPTS_DIR = txdir
            vws._IDEA_CACHE["mtime"] = None
            try:
                return vws.read_idea_transcript(0)
            finally:
                vws.IDEAS_FILE, vws.voice_signals.TRANSCRIPTS_DIR = saved
                vws._IDEA_CACHE["mtime"] = None

    def test_spoken_and_typed_appear_in_ONE_window(self):
        r = self.run_two([tx_line("10:00:00", "Serge", "said it")],
                         [tx_line("10:01:00", "Serge", "typed it")])
        self.assertEqual(len(r["windows"]), 1,
                         "the two channels came back as two separate windows")
        self.assertEqual([x["text"] for x in r["windows"][0]["lines"]],
                         ["said it", "typed it"])

    def test_they_are_interleaved_by_the_clock_not_stacked_by_file(self):
        # He lived them in one order; that is the order that reads true.
        r = self.run_two([tx_line("10:00:00", "Serge", "spoken first"),
                          tx_line("10:10:00", "Serge", "spoken last")],
                         [tx_line("10:05:00", "Serge", "typed middle")])
        self.assertEqual([x["text"] for x in r["windows"][0]["lines"]],
                         ["spoken first", "typed middle", "spoken last"])

    def test_each_line_says_which_conversation_it_was(self):
        # "He said this" and "he typed this" are different facts.
        r = self.run_two([tx_line("10:00:00", "Serge", "spoken")],
                         [tx_line("10:01:00", "Serge", "typed")])
        self.assertEqual([x["channel"] for x in r["windows"][0]["lines"]],
                         ["voice", "terminal"])

    def test_a_stray_note_in_the_folder_is_not_filed_as_a_day(self):
        r = self.run_it("### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n",
                        {"2026-08-07": [tx_line("10:00:00", "Serge", "real")],
                         "README": [tx_line("10:00:00", "Serge", "not a day")]})
        texts = [x["text"] for w in r["windows"] for x in w["lines"]]
        self.assertEqual(texts, ["real"])


class HonestShortfalls(Base):
    def test_a_missing_day_is_named_never_served_as_silence(self):
        r = self.run_it("### T\n- raised: 2026-08-01\n\nSaid at 10:00 AM.\n",
                        {"2026-08-07": [tx_line("10:00:00", "Serge", "x")]})
        self.assertEqual(r["missing"], ["2026-08-01"])
        self.assertIn("2026-08-01", r["why"])

    def test_a_write_up_naming_no_time_says_so_in_words(self):
        # WITH a real transcript sitting there for the raised day, deliberately.
        # Caught by injection: the parser-level test passes an idea with no
        # anchors, but a fallback bolted on downstream -- "no time? show the
        # whole day" -- sailed past it, because that test never ran the reader
        # against a day there was something to show. A guard only proves what
        # it looks at.
        r = self.run_it("### T\n- raised: 2026-08-07\n\nJust prose.\n",
                        {"2026-08-07": [tx_line("12:00:00", "Serge", "unrelated"),
                                        tx_line("15:00:00", "Serge", "also")]})
        self.assertTrue(r["ok"])
        self.assertEqual(r["windows"], [],
                         "an idea whose write-up names no moment served a "
                         "stretch of the day anyway -- that is a guess "
                         "wearing a timestamp")
        self.assertTrue(r["why"].strip())

    def test_a_quiet_stretch_of_a_real_day_is_distinguished_from_a_lost_day(self):
        r = self.run_it("### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n",
                        {"2026-08-07": [tx_line("23:00:00", "Serge", "later")]})
        self.assertNotIn("missing", r)
        self.assertIn("nothing was recorded", r["why"])

    def test_the_line_cap_is_reported_and_never_silent(self):
        # A capped answer that does not say it is capped reads as the whole
        # conversation. That is the failure this asserts against.
        n = vws.IDEA_TX_MAX_LINES + 5
        # Seconds apart, so every one of them lands inside the window -- the
        # cap is what is being measured here, not the window.
        lines = [tx_line(f"10:{i // 60:02d}:{i % 60:02d}", "Serge", f"line {i}")
                 for i in range(n)]
        r = self.run_it("### T\n- raised: 2026-08-07\n\nSaid at 10:00 AM.\n",
                        {"2026-08-07": lines})
        served = sum(len(w["lines"]) for w in r["windows"])
        self.assertEqual(served, vws.IDEA_TX_MAX_LINES)
        self.assertEqual(r["dropped"], n - vws.IDEA_TX_MAX_LINES)

    def test_an_index_outside_the_list_is_refused(self):
        for bad in (-1, 99):
            r = self.run_it("### T\n- raised: 2026-08-07\n\nx\n", {}, index=bad)
            self.assertFalse(r["ok"], f"index {bad} was accepted")


class NoPathIsEverBuilt(Base):
    """The security shape, pinned as a property of the code.

    A date out of a hand-edited note becoming a filename is the classic
    traversal shape. There is no traversal here because there is no
    construction -- and that is worth a test, because the "simplification"
    that reintroduces it looks like an improvement.
    """

    def test_the_directory_is_listed_never_joined(self):
        import inspect
        src = inspect.getsource(vws._transcript_days)
        self.assertIn("glob", src)
        for build in ("TRANSCRIPTS_DIR /", 'f"{', "+ day", "day +", "%s.md"):
            self.assertNotIn(build, src,
                             "a transcript path is being CONSTRUCTED from a "
                             "parsed date -- list the directory instead")

    def test_the_reader_itself_touches_no_path(self):
        import inspect
        src = inspect.getsource(vws.read_idea_transcript)
        self.assertNotIn("TRANSCRIPTS_DIR", src,
                         "read_idea_transcript reaches for the directory "
                         "directly -- it must go through _transcript_days()")

    def test_a_date_that_climbs_out_of_the_folder_matches_nothing(self):
        # It cannot even be parsed as a date, and if it could it would still
        # only be a dictionary key that is not there. Both belts, tested.
        r = self.run_it(
            "### T\n- raised: 2026-08-07\n\n"
            "On 2026-08-07 at 10:00 AM, see ../../../../etc/passwd\n",
            {"2026-08-07": [tx_line("10:00:00", "Serge", "safe")]})
        self.assertEqual([x["text"] for x in r["windows"][0]["lines"]],
                         ["safe"])


class NotOnTheHotPath(unittest.TestCase):
    def test_the_transcript_is_not_folded_into_signals(self):
        # /signals is polled continuously. Five ideas' worth of raw
        # conversation on every tick pays, all day, for something looked at
        # occasionally -- so this is fetched on the click.
        src = SRC.read_text()
        start = src.index("async def signals(")
        end = src.index("\nasync def ", start + 10)
        self.assertNotIn("read_idea_transcript", src[start:end])

    def test_the_route_is_registered(self):
        self.assertIn('web.get("/idea-transcript", idea_transcript)',
                      SRC.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
