#!/usr/bin/env python3
"""Tests for the /ambient.mp3 route in voice-web-server.py.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_ambient_route.py

Why these exist (Serge, 2026-08-05 ~1:05 PM): "yes, but put a note so if we
want to remove it, I'm scared of security." He is right to be -- this is the
only route in Jarvis that serves a file off disk, and file-serving routes are
where path traversal lives.

The defence is NOT validation, it is construction: the route takes no input at
all. There is no filename parameter, no query string, no path segment -- the
served path is a module constant. A traversal attack needs somewhere to put
"../", and a route with no input has nowhere. These tests assert that property
directly, because a future edit that adds "just one" parameter would look
harmless in a diff and would be the whole risk.

They also assert the removal note he asked for is still in the file, since a
removal route nobody can find is the same as none.

The real module is imported by path, so these cannot drift from the code.
"""

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("voice_web_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["voice_web_server"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeRequest:
    """The handler must not read anything off the request. If it ever starts,
    every attribute access here raises and the test that covers it fails."""

    def __getattr__(self, name):
        raise AssertionError(
            f"the ambient handler read request.{name} -- it must take NO input"
        )


class AmbientRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_server()
        cls.src = SERVER.read_text()

    # ---- the security property, asserted rather than promised ----

    def test_every_handler_reads_nothing_from_the_request(self):
        """The whole defence in one test: no input means no traversal.

        Run against EVERY track handler, not just one -- going from one file to
        four is exactly where a parameter would have crept in.
        """
        for _url, fn, _t in self.mod.AMBIENT_TRACKS:
            asyncio.run(self.mod._serve_ambient(fn)(FakeRequest()))
        asyncio.run(self.mod.ambient_list(FakeRequest()))

    def test_every_served_path_is_a_constant_under_the_jarvis_folder(self):
        self.assertEqual(self.mod.AMBIENT_DIR.parent, self.mod.HERE)
        self.assertEqual(self.mod.AMBIENT_DIR.name, "audio")
        for _url, fn, _t in self.mod.AMBIENT_TRACKS:
            p = (self.mod.AMBIENT_DIR / fn).resolve()
            self.assertTrue(str(p).startswith(str(self.mod.AMBIENT_DIR.resolve())),
                            f"{fn} resolves outside the audio folder")
            self.assertNotIn("..", fn)
            self.assertNotIn("/", fn)

    def test_no_route_has_a_path_parameter(self):
        """aiohttp reads "{name}" in a path as a capture group. ONE of those is
        the difference between this and a file server -- and it is the obvious
        way someone would extend one track to four."""
        for url, _fn, _t in self.mod.AMBIENT_TRACKS:
            self.assertNotIn("{", url, f"{url} takes a path parameter")
            self.assertTrue(url.startswith("/ambient/"))
        self.assertIn('web.get("/ambient-list", ambient_list)', self.src)
        self.assertIn("_serve_ambient(f)) for u, f, _t in AMBIENT_TRACKS", self.src)

    def test_the_handlers_never_touch_request_data(self):
        body = self.src[self.src.index("def _serve_ambient("):]
        body = body[: body.index("\n\nasync def signals(")]
        for bad in ("request.match_info", "request.query", "request.rel_url",
                    "os.path.join"):
            self.assertNotIn(bad, body, f"a handler now touches {bad}")

    def test_the_track_list_has_no_duplicate_urls(self):
        urls = [u for u, _f, _t in self.mod.AMBIENT_TRACKS]
        self.assertEqual(len(urls), len(set(urls)))

    def test_the_list_route_reports_only_files_that_exist(self):
        """A half-downloaded set degrades to what made it, not to a silent gap
        the page cannot explain."""
        import json as _json
        resp = asyncio.run(self.mod.ambient_list(FakeRequest()))
        listed = _json.loads(resp.body.decode())
        on_disk = [t for t in self.mod.AMBIENT_TRACKS
                   if (self.mod.AMBIENT_DIR / t[1]).is_file()]
        self.assertEqual(len(listed), len(on_disk))
        for row in listed:
            self.assertIn("url", row)
            self.assertIn("title", row)

    def test_all_four_tracks_are_actually_on_disk(self):
        missing = [fn for _u, fn, _t in self.mod.AMBIENT_TRACKS
                   if not (self.mod.AMBIENT_DIR / fn).is_file()]
        self.assertEqual(missing, [], f"missing audio files: {missing}")

    def test_the_list_is_ordered_calmest_first(self):
        """Serge, ~1:50 PM: "start with the calmest track... if the thing is
        safer." The page plays entry 0 and shuffles only the tail, so this
        tuple's order decides what he hears every time he switches it on --
        it is not a cosmetic list."""
        first = self.mod.AMBIENT_TRACKS[0]
        self.assertIn("debussy", first[1],
                      "the opener is no longer the calmest track")
        last = self.mod.AMBIENT_TRACKS[-1][1]
        self.assertIn("beethoven", last,
                      "the loudest track moved out of last place")
        # And the intent is written down where the next reader will trip on it.
        note = self.src[self.src.index("AMBIENT MUSIC"):][:3500]
        self.assertIn("CALMEST FIRST", note.upper())

    # ---- it must never take the page down ----

    def test_missing_file_is_a_404_not_an_exception(self):
        resp = asyncio.run(self.mod._serve_ambient("no-such-file.mp3")(FakeRequest()))
        self.assertEqual(resp.status, 404)

    def test_a_directory_where_the_file_should_be_is_also_a_404(self):
        resp = asyncio.run(self.mod._serve_ambient(".")(FakeRequest()))
        self.assertEqual(resp.status, 404)

    def test_a_real_file_is_served_as_audio(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.mp3"
            f.write_bytes(b"\xff\xfb\x00" * 40)
            real = self.mod.AMBIENT_DIR
            try:
                self.mod.AMBIENT_DIR = Path(d)
                resp = asyncio.run(self.mod._serve_ambient("x.mp3")(FakeRequest()))
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.content_type, "audio/mpeg")
                self.assertEqual(resp.body, f.read_bytes())
            finally:
                self.mod.AMBIENT_DIR = real

    def test_each_handler_is_bound_to_its_OWN_file(self):
        """The closure is the security boundary. If every handler somehow
        closed over the same name, three of the four tracks would be wrong and
        nothing else here would notice."""
        with tempfile.TemporaryDirectory() as d:
            real = self.mod.AMBIENT_DIR
            try:
                self.mod.AMBIENT_DIR = Path(d)
                bodies = {}
                for name in ("a.mp3", "b.mp3", "c.mp3"):
                    (Path(d) / name).write_bytes(name.encode() * 10)
                    bodies[name] = self.mod._serve_ambient(name)
                for name, h in bodies.items():
                    resp = asyncio.run(h(FakeRequest()))
                    self.assertEqual(resp.body, name.encode() * 10)
            finally:
                self.mod.AMBIENT_DIR = real

    # ---- the note he actually asked for ----

    def test_the_removal_instructions_are_still_in_the_file(self):
        """Serge asked for the removal route to be written down BEFORE this was
        built. A note that quietly rots is worse than none."""
        self.assertIn("TO REMOVE THIS ENTIRELY", self.src)
        for step in ("app.add_routes", "jarvis.html", "audio"):
            self.assertIn(step, self.src[self.src.index("TO REMOVE THIS ENTIRELY"):]
                          [:1400], f"the removal note stopped mentioning {step}")

    def test_the_server_still_binds_loopback_only(self):
        """Named here because this route is the reason it matters."""
        self.assertEqual(self.mod.HOST, "127.0.0.1")

    def test_the_licence_of_what_is_served_is_recorded(self):
        note = self.src[self.src.index("AMBIENT MUSIC"):][:3000]
        self.assertIn("public domain", note.lower())
        # Every track's source item named, so the licence can be re-checked
        # without trusting this comment.
        for item in ("Mozart_Symphony_40", "gustav-holst-the-planets-op.-32",
                     "01-debussey-clair-de-lune", "BeethovenSymphonyNo.5"):
            self.assertIn(item, note, f"the source of {item} is no longer recorded")


if __name__ == "__main__":
    unittest.main(verbosity=2)
