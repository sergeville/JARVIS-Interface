#!/usr/bin/env python3
"""Tests for save_upload() and image_prompt() in voice-web-server.py.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_uploads.py

Why these exist (Serge, 2026-08-05): he dropped a file on the JARVIS page and
it vanished -- no chip, no message, nothing on disk. Two faults were behind it.
The one these guard is the second: an attachment only ever shipped on a TYPED
send, so dropping a file and then TALKING orphaned the image. The fix pulled
the saving and the prompt-building out of the "image" branch into these two
helpers, and the "audio" branch now calls them too.

That refactor is the risk. One saver feeding two call sites is only safe while
it behaves identically for both, so these tests pin the behaviour that the two
branches now share: where the bytes land, what the name becomes, what happens
on collision, and that bad input returns None instead of raising inside a
websocket handler -- an exception there kills the socket, and Serge loses the
conversation rather than one file.

The real module is imported by path, so these can never drift from the code
they guard.
"""

import base64
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / "voice-web-server.py"


def load_server():
    """Import voice-web-server.py by path (its name is not a valid module)."""
    spec = importlib.util.spec_from_file_location("voice_web_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["voice_web_server"] = mod
    spec.loader.exec_module(mod)
    return mod


srv = load_server()

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 64).decode()


class UploadDirMixin(unittest.TestCase):
    """Point UPLOADS_DIR at a temp dir so the real uploads/ is never touched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = srv.UPLOADS_DIR
        srv.UPLOADS_DIR = Path(self._tmp.name) / "uploads"

    def tearDown(self):
        srv.UPLOADS_DIR = self._orig
        self._tmp.cleanup()


class TestSaveUpload(UploadDirMixin):
    def test_saves_the_bytes_and_returns_the_path(self):
        path = srv.save_upload({"name": "shot.png", "data": PNG})
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), base64.b64decode(PNG))

    def test_creates_the_uploads_dir_if_it_is_missing(self):
        self.assertFalse(srv.UPLOADS_DIR.exists())
        path = srv.save_upload({"name": "a.png", "data": PNG})
        self.assertTrue(path.exists())

    def test_the_filename_is_timestamped_and_keeps_the_original_name(self):
        path = srv.save_upload({"name": "shot.png", "data": PNG})
        self.assertTrue(path.name.endswith("shot.png"), path.name)
        # "YYYY-MM-DD HH.MM.SS " prefix -- what makes uploads/ sort by time.
        self.assertRegex(path.name, r"^\d{4}-\d{2}-\d{2} \d{2}\.\d{2}\.\d{2} ")

    def test_a_second_file_in_the_same_second_does_not_overwrite_the_first(self):
        # Two drops inside one second share a timestamp. Losing the first to
        # the second would be the same silent data loss this whole task is about.
        a = srv.save_upload({"name": "shot.png", "data": PNG})
        b = srv.save_upload({"name": "shot.png", "data": PNG})
        self.assertNotEqual(a, b)
        self.assertTrue(a.exists() and b.exists())
        self.assertIn("-2", b.name)

    def test_a_path_in_the_name_cannot_escape_the_uploads_dir(self):
        # The name comes off a websocket. It is a label, never a path.
        path = srv.save_upload({"name": "../../etc/evil.png", "data": PNG})
        self.assertIsNotNone(path)
        self.assertEqual(path.parent, srv.UPLOADS_DIR)
        self.assertNotIn("..", str(path))

    def test_a_missing_name_falls_back_instead_of_failing(self):
        path = srv.save_upload({"data": PNG})
        self.assertIsNotNone(path)
        self.assertTrue(path.name.endswith("pasted.png"))

    def test_empty_data_returns_none_and_writes_nothing(self):
        self.assertIsNone(srv.save_upload({"name": "a.png", "data": ""}))
        self.assertFalse(srv.UPLOADS_DIR.exists())

    def test_undecodable_data_returns_none_rather_than_raising(self):
        # This runs inside the websocket handler: an exception here drops the
        # socket and costs the conversation, not just the file.
        self.assertIsNone(srv.save_upload({"name": "a.png", "data": "!!!not b64"}))

    def test_a_non_dict_payload_returns_none(self):
        for junk in (None, "", [], 7, "a string"):
            self.assertIsNone(srv.save_upload(junk), repr(junk))

    def test_a_missing_data_key_returns_none(self):
        self.assertIsNone(srv.save_upload({"name": "a.png"}))


class TestImagePrompt(unittest.TestCase):
    def test_it_names_the_file_so_the_brain_can_open_it(self):
        p = Path("/tmp/uploads/2026-08-05 10.00.00 shot.png")
        self.assertIn(str(p), srv.image_prompt(p, "what is this"))

    def test_spoken_or_typed_words_are_carried_with_the_image(self):
        p = Path("/tmp/shot.png")
        out = srv.image_prompt(p, "why is this red")
        self.assertIn("why is this red", out)

    def test_no_words_still_produces_a_usable_instruction(self):
        # Dropping an image and saying nothing is a real thing Serge does.
        p = Path("/tmp/shot.png")
        out = srv.image_prompt(p, "")
        self.assertIn(str(p), out)
        self.assertTrue(len(out) > 40)

    def test_whitespace_only_words_are_treated_as_no_words(self):
        p = Path("/tmp/shot.png")
        self.assertEqual(srv.image_prompt(p, "   "), srv.image_prompt(p, ""))

    def test_none_words_do_not_reach_the_prompt_as_the_text_none(self):
        p = Path("/tmp/shot.png")
        self.assertNotIn("None", srv.image_prompt(p, None))

    def test_both_shapes_tell_the_brain_to_open_the_file(self):
        # The whole point of the prompt: without this the brain answers about
        # an image it never opened. The two shapes word the rest differently
        # ("look at it before answering" vs "tell him what you make of it"),
        # so the invariant worth pinning is the instruction they share.
        p = Path("/tmp/shot.png")
        for text in ("", "have a look"):
            self.assertIn("open it", srv.image_prompt(p, text).lower(), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
