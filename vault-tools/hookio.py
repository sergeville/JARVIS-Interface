#!/usr/bin/env python3
"""The one bounded stdin read that every Jarvis hook uses.

WHY THIS MODULE EXISTS. Twice now the same bug has shipped in two different
hooks, written months apart by sessions that each believed they had guarded
against it:

  * `session_record.py` guarded with `sys.stdin.isatty()` and promised in its
    own docblock that a hook must never block. An inherited pipe that is open
    and silent is not a tty, so `json.load` waited forever. Found 2026-08-14
    when the full test suite hung for ten minutes and had to be killed.
  * `board-guard.py` guarded with the SAME isatty check plus a size cap, and
    promised in rule 4 that "it reads stdin with a size cap so a huge payload
    cannot hang it." A size cap bounds MEMORY, not TIME: `read(200_000)` waits
    for two hundred thousand bytes or EOF, whichever comes first, so a small
    payload on a pipe nobody closed blocks exactly as hard. That hook is the
    PostToolUse hook on Edit, Write and Bash -- it fires after nearly every
    tool call -- and it carries no timeout in any settings file.

Both wrote a guard that tested a PROXY -- is this a terminal? is the payload
huge? -- instead of the PROPERTY they promised: is anything actually coming,
and will this call return? Two independent authors reached for the same wrong
proxy, which is the argument for one implementation rather than a third.

WHAT IT DOES. Reads a JSON object from a stream, and RETURNS -- always, on
every path, whatever the caller on the other end does or fails to do.

THE PART THAT IS EASY TO GET WRONG, and did get written wrong twice already:
bounding the wait for the FIRST BYTE is not enough. `json.load` calls `read()`,
which runs to EOF, so a complete and perfectly valid payload still hangs if the
writer holds its end open. The deadline here covers the WHOLE read, and the
read stops as soon as a complete JSON value has ARRIVED -- waiting for a close
that may never come buys nothing.

And "has arrived" has to mean a PREFIX, not the whole buffer. The first version
of this file tested `json.loads(everything_so_far)`, so a perfectly good
payload followed by a single trailing byte -- a stray newline from a wrapper, a
second object, anything -- never parsed, and the read sat out its entire budget
and returned nothing. `raw_decode` answers the question actually being asked:
is there a complete value at the front of this buffer yet?
"""
import io
import json
import os
import select
import sys
import time

# The ceiling on a whole read, first byte to last. It is a ceiling, not a
# delay: a real hook's payload is already waiting, so the read returns at once
# and this costs nothing. Only a silent or slow stdin ever pays it.
#
# Chosen to sit under the SMALLEST timeout any hook in the template is deployed
# with, because that is the real upper bound. It has to be the smallest and not
# this hook's own: the reader is shared, so the next hook to adopt it inherits
# this number. The first version of this constant, in session_record.py, was
# picked against nothing at all; the second was 12.0, picked against the 15s
# Stop hooks while UserPromptSubmit sits at 10s -- caught by a test, not by
# reading.
#
# It is pinned as a BAND, 30%-60% of the smallest timeout, and the band exists
# because the two obvious one-sided pins contradict each other. A floor alone
# ("do not shrink it") permitted 9.9 under a 10s timeout, leaving the hook 0.1s
# to do its actual work. A ceiling alone ("leave room") permitted 0.8, which
# races a real caller. The hook's own work is milliseconds, so the band is
# generous at both ends and still refuses both failures.
DEFAULT_BUDGET = 5.0

# Bounds memory, and ONLY memory. Kept because a hook should not be a way to
# make the machine swap -- but named here so nobody again mistakes it for
# protection against hanging, which is the exact error rule 4 of board-guard.py
# made in writing.
#
# 4MB, and the size is a DECISION with a reason. It was 200_000, which is
# smaller than this repo's own `Jarvis Visual/jarvis.html` (318KB) -- so a
# Write of the project's largest file produced a payload over the cap, and the
# hook dropped it in silence along with the HUD activity record that goes with
# it. Nothing tested that; the old cap was asserted as a VALUE and never as a
# behaviour. `test_the_cap_clears_the_largest_file_a_payload_could_carry` pins
# it against the actual repo rather than against a number typed here.
DEFAULT_MAX_BYTES = 4_000_000

# Parses a complete value off the FRONT of a buffer and reports where it ended,
# which is the question this module needs and `json.loads` cannot answer.
_DECODER = json.JSONDecoder()

# "not a complete value yet" -- distinct from "a complete value that is None",
# which is a real payload shape (`null`) that must be refused, not waited on.
_INCOMPLETE = object()

# THE LAST THING THIS MODULE SWALLOWED, so that "always returns" does not
# quietly become "always returns None". `read_json_stdin` is TOTAL by
# contract -- a hook that raises here blocks Serge's session -- but a total
# function with a bare catch is indistinguishable from one that has stopped
# working, and this project has been bitten by exactly that shape more than
# any other. So the swallow is recorded rather than invisible: tests assert
# on it, and a future session debugging "the hook stopped recording" has
# something to read instead of a guess.
LAST_ERROR = None


def read_json_stdin(budget=None, max_bytes=None, stream=None):
    """The JSON object a hook was handed on stdin, or None. TOTAL.

    THIS WRAPPER IS THE CONTRACT. The docstring below has promised "ALWAYS
    RETURNS" since the day this module was written, and on 2026-08-21 it was
    still false in two reproducible ways found by the test-adversary and
    re-proven by hand:

        * a stream with neither `isatty` nor `read` raised AttributeError --
          both specific branches let it through to `json.load`, which needs
          a `.read` nobody checked for;
        * a stream whose `read()` raises RuntimeError propagated it, because
          the fallback caught only (ValueError, TypeError, OSError).

    Every hook in this repo calls this, on SessionStart, SessionEnd, Stop,
    UserPromptSubmit and Notification -- so an exception here is not a hook
    failing, it is Serge's turn failing, on a path he never asked about.
    "For every reason alike" is what the contract already says; this makes
    the code say it too.

    THE BREADTH IS DELIBERATE AND IT IS THE RISKY PART, named rather than
    hidden: `except Exception` would also swallow a genuine bug inside this
    module -- a typo, a bad import -- and report it as "no payload", which is
    the silent-failure shape this project keeps hunting. That is why it sets
    `LAST_ERROR` instead of dropping it on the floor, and why the specific
    branches below are kept: they still say WHY for every reason anyone has
    actually met. This catch is the floor, not the design.
    """
    global LAST_ERROR
    LAST_ERROR = None
    try:
        return _read_json_stdin(budget, max_bytes, stream)
    except Exception as e:                      # noqa: BLE001 -- see above
        LAST_ERROR = f"{type(e).__name__}: {e}"
        return None


def _read_json_stdin(budget=None, max_bytes=None, stream=None):
    """The JSON object a hook was handed on stdin, or None.

    ALWAYS RETURNS, and returns within `budget`. Not "never blocks" -- that was
    the previous wording and it is the exact promise this codebase has now
    broken twice, so it is worth being literal: this waits, but it waits a
    bounded amount and then gives up.

    None means "there is nothing here to act on", for every reason alike: no
    payload, a terminal, an unreadable stream, a caller that went quiet, bytes
    that are not a JSON object, or a payload over `max_bytes`. That last one is
    the only case where data really was there and is discarded, which is why
    the cap is sized against this repo's largest file rather than guessed.
    """
    # Resolved HERE, not in the signature. A default argument is bound once
    # at definition time, so `hookio.DEFAULT_BUDGET = 0.5` after import had no
    # effect whatever -- which is how a test meant to prove boundedness sat
    # waiting out the real budget and failed. A constant nobody can override
    # is a constant nobody can test around.
    budget = DEFAULT_BUDGET if budget is None else budget
    max_bytes = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    stream = sys.stdin if stream is None else stream
    # A terminal is never a hook caller. This is NOT redundant with the
    # readiness check below: a tty with a line typed and no Ctrl-D is "ready"
    # as far as select is concerned, so dropping it puts an interactive run
    # straight back into a read waiting for an EOF the human has not sent.
    try:
        if stream is None or stream.isatty():
            return None
    except AttributeError:
        # A duck-typed stand-in with only .read() -- which is how
        # session_registry.py's own tests drive their hook, and how this was
        # found. It cannot be a terminal, so carry on rather than treating a
        # missing method as a reason to drop the payload. The `fileno` branch
        # below already had this; the isatty branch did not, and the whole
        # hook silently stopped recording.
        pass
    except (ValueError, OSError):
        return None

    try:
        fd = stream.fileno()
    except (io.UnsupportedOperation, ValueError, OSError, AttributeError):
        # No real descriptor -- an in-memory stream, which is how these hooks
        # get tested in-process. It cannot block, so read it directly.
        # Returning None here instead would turn a working read into a silent
        # drop: io.UnsupportedOperation subclasses BOTH ValueError and OSError,
        # so a plain `except (ValueError, OSError)` swallows it and nothing
        # anywhere reports the loss.
        try:
            return _object_or_none(json.load(stream))
        except (ValueError, TypeError, OSError):
            return None

    deadline = time.monotonic() + budget
    chunks = []
    size = 0
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            if not select.select([fd], [], [], left)[0]:
                break            # nothing is coming
            chunk = os.read(fd, 65536)
        except (ValueError, OSError):
            break                # a stream that raises is a stream to give up on
        if not chunk:
            break                # EOF, the ordinary case
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            return None          # not a hook payload; refuse it rather than parse it
        got = _decode_prefix(b"".join(chunks))
        if got is not _INCOMPLETE:
            return _object_or_none(got)
    got = _decode_prefix(b"".join(chunks))
    return None if got is _INCOMPLETE else _object_or_none(got)


def _decode_prefix(buf):
    """The first complete JSON value at the front of `buf`, or _INCOMPLETE.

    _INCOMPLETE means "keep reading" and is the ONLY thing that keeps the loop
    going, so every other outcome -- malformed, too deep, not yet valid UTF-8
    at a chunk boundary -- has to resolve one way or the other rather than
    spin.
    """
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError:
        return _INCOMPLETE       # a multi-byte character split across reads
    try:
        # STRIP A BOM AS WELL AS WHITESPACE. `lstrip()` does not remove
        # U+FEFF, so a payload written by any wrapper that prepends a byte
        # order mark never parsed -- and, worse, never RESOLVED: raw_decode
        # raised ValueError, which this function reports as _INCOMPLETE,
        # which means "keep reading". A permanently malformed payload was
        # therefore waited on for the entire budget and then dropped. On a
        # hook deployed with a 10s timeout that is half its life spent on
        # something that could never have worked. (test-adversary,
        # 2026-08-15; reproduced 2026-08-21 -- exactly 1.00s of a 1.0s
        # budget.)
        #
        # A TRUNCATED PAYLOAD IS NOT THE SAME CASE AND IS NOT FIXED HERE,
        # deliberately. A genuine prefix may be completed by the next chunk,
        # so waiting is the correct behaviour and the budget is the designed
        # cost of it. The card that raised this named both; only one of them
        # is a bug.
        value, _end = _DECODER.raw_decode(text.lstrip("\ufeff \t\r\n"))
        return value
    except ValueError:
        return _INCOMPLETE       # not a whole value at the front yet
    except RecursionError:
        # Nesting deeper than the interpreter will parse. This ESCAPED the
        # function before it was caught here, out of the one whose docstring
        # promises it always returns -- and both callers only survived it by
        # wrapping everything in `except Exception`. A contract kept by the
        # caller is not a contract.
        return None


def _object_or_none(data):
    """A hook payload is an object. `null`, a list and a bare string are not.

    Every one of those is valid JSON that `json.load` returns happily, and
    every one of them made `.get` raise AttributeError in the caller -- an
    uncaught traceback and a non-zero exit on every turn, reproduced in
    session_record.py before this existed.
    """
    return data if isinstance(data, dict) else None
