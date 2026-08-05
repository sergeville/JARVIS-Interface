#!/usr/bin/env python3
"""Tests for save_uploads() and images_prompt() in voice-web-server.py.

Run:  ./tests/run-tests.sh   (from Jarvis Visual/)
   or  python3 tests/test_multi_upload.py

Why these exist (Serge, 2026-08-05): "when I add two images side-by-side or
back-to-back, it only catches the last image." The page held ONE attachment
slot and this end took ONE image per turn to match. Both became lists.

What is actually at risk in that change:

  ORDER.        Serge says "the first one" and "the second one". A saver that
                reorders, de-duplicates, or drops a middle failure silently
                would make the prompt lie about which image is which.
  THE OLD SHAPE. The page reaches an open tab the moment the file changes, but
                the server only changes on a restart -- and a stale tab can
                outlive a restart in the other direction. A bare top-level
                image (the pre-2026-08-05 shape) must still work, or the fix
                for losing images becomes a new way to lose them.
  THE BOUND.    An unbounded list is an unbounded write into uploads/. The
                page caps at six; this end must cap independently, because the
                page is not the only thing that can reach the socket.
  ONE IMAGE.    By far the common case. Its wording is proven in daily use and
                must come out byte-identical to what image_prompt() produced
                before any of this existed.

The real module is imported by path, so these can never drift from the code
they guard, and UPLOADS_DIR is redirected to a temp dir so the real uploads/
is never touched.
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


def img(name, body=b"x" * 32):
    """One image in the shape the page puts on the socket."""
    return {"name": name, "mime": "image/png",
            "data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + body).decode()}


class TempUploads(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = srv.UPLOADS_DIR
        srv.UPLOADS_DIR = Path(self._tmp.name) / "uploads"

    def tearDown(self):
        srv.UPLOADS_DIR = self._orig
        self._tmp.cleanup()


class SaveUploads(TempUploads):
    def test_saves_every_image(self):
        paths = srv.save_uploads([img("a.png"), img("b.png"), img("c.png")])
        self.assertEqual(len(paths), 3)
        for p in paths:
            self.assertTrue(p.exists())

    def test_keeps_serges_order(self):
        # THE regression. Order is the whole point: he refers to them by
        # position, so the list that comes back must be the list he added.
        paths = srv.save_uploads([img("first.png"), img("second.png"),
                                  img("third.png")])
        self.assertEqual([p.name.split(" ", 2)[-1] for p in paths],
                         ["first.png", "second.png", "third.png"])

    def test_two_in_the_same_second_do_not_overwrite(self):
        # The filename stamp has one-second resolution and a queue sends its
        # images in one burst, so this collision is the NORMAL case here, not
        # an edge one. Distinct bytes prove neither clobbered the other.
        paths = srv.save_uploads([img("shot.png", b"AAAA"),
                                  img("shot.png", b"BBBB")])
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])
        self.assertNotEqual(paths[0].read_bytes(), paths[1].read_bytes())

    def test_a_bad_image_is_skipped_not_fatal(self):
        # One corrupt payload must not cost the other images in the turn.
        bad = {"name": "bad.png", "mime": "image/png", "data": "!!!not base64"}
        paths = srv.save_uploads([img("good1.png"), bad, img("good2.png")])
        self.assertEqual(len(paths), 2)
        self.assertEqual([p.name.split(" ", 2)[-1] for p in paths],
                         ["good1.png", "good2.png"])

    def test_caps_at_max_images(self):
        paths = srv.save_uploads([img(f"{i}.png") for i in range(20)])
        self.assertEqual(len(paths), srv.MAX_IMAGES)

    def test_empty_and_junk_return_empty(self):
        for junk in ([], None, "not a list", 42, {}):
            self.assertEqual(srv.save_uploads(junk), [])

    def test_a_list_of_junk_returns_empty(self):
        self.assertEqual(srv.save_uploads([None, "x", 7, {}]), [])

    def test_does_not_raise_on_anything(self):
        # This runs inside the websocket handler. An exception there costs the
        # conversation, not just the file.
        for junk in ([{"data": None}], [{"name": "x"}], [[]], [b"bytes"]):
            try:
                srv.save_uploads(junk)
            except Exception as e:      # noqa: BLE001 - that is the point
                self.fail(f"save_uploads raised on {junk!r}: {e}")

    def test_a_path_in_the_name_cannot_escape_uploads(self):
        paths = srv.save_uploads([{"name": "../../evil.png", "mime": "image/png",
                                   "data": base64.b64encode(b"pwn").decode()}])
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].parent, srv.UPLOADS_DIR)


class ImagesPrompt(unittest.TestCase):
    def test_one_image_is_byte_identical_to_the_old_wording(self):
        # The proven single-image phrasing must not have moved a comma.
        p = Path("/tmp/uploads/one.png")
        for text in ("", "what is this"):
            self.assertEqual(srv.images_prompt([p], text),
                             srv.image_prompt(p, text))

    def test_several_images_are_all_named(self):
        ps = [Path("/tmp/a.png"), Path("/tmp/b.png"), Path("/tmp/c.png")]
        out = srv.images_prompt(ps, "")
        for p in ps:
            self.assertIn(str(p), out)

    def test_several_images_are_named_in_order(self):
        ps = [Path("/tmp/a.png"), Path("/tmp/b.png"), Path("/tmp/c.png")]
        out = srv.images_prompt(ps, "")
        self.assertLess(out.index("/tmp/a.png"), out.index("/tmp/b.png"))
        self.assertLess(out.index("/tmp/b.png"), out.index("/tmp/c.png"))
        self.assertIn("in the order he added them", out)

    def test_several_images_state_the_count(self):
        ps = [Path("/tmp/a.png"), Path("/tmp/b.png")]
        self.assertIn("2 images", srv.images_prompt(ps, ""))

    def test_his_words_come_first_when_he_typed_some(self):
        out = srv.images_prompt([Path("/tmp/a.png"), Path("/tmp/b.png")],
                                "compare these")
        self.assertTrue(out.startswith("compare these"))

    def test_no_images_falls_back_to_the_plain_text(self):
        self.assertEqual(srv.images_prompt([], "  just talking  "),
                         "just talking")
        self.assertEqual(srv.images_prompt([], ""), "")


class SocketPayloadShapes(TempUploads):
    """The two shapes the socket branches actually build a list from."""

    def test_the_list_shape(self):
        data = {"type": "image", "images": [img("a.png"), img("b.png")]}
        self.assertEqual(len(srv.save_uploads(data.get("images") or [data])), 2)

    def test_the_old_bare_shape_still_works(self):
        # A stale tab from before this change sends the image at the top level.
        data = dict(img("legacy.png"), type="image", text="hi")
        paths = srv.save_uploads(data.get("images") or [data])
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].name.endswith("legacy.png"))

    def test_the_audio_branch_shapes(self):
        # images list wins; a bare "image" is the older spoken-turn shape.
        for data, want in (({"images": [img("a.png"), img("b.png")]}, 2),
                           ({"image": img("a.png")}, 1),
                           ({}, 0)):
            imgs = data.get("images")
            if not imgs and data.get("image"):
                imgs = [data["image"]]
            self.assertEqual(len(srv.save_uploads(imgs or [])), want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
