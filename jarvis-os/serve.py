#!/usr/bin/env python3
"""Serve the JARVIS OS skeleton, and proxy the ONE feed it reads.

Static files, loopback only, on its own port. This is NOT part of the voice
stack: it starts nothing, it kills nothing, and it holds no state of its own.

WHY A PROXY AND NOT A CORS HEADER ON THE VOICE SERVER (decided 2026-08-15,
Serge's go): the OS page is served from :8090 and the signals feed lives on
:8765, so a browser refuses the read as cross-origin. The two ways through
are opening the voice server up with an Access-Control header, or having the
page's OWN dev server fetch the feed and hand it back same-origin. The second
was chosen because the voice server is a live process Serge is talking
through, and widening who may read that payload -- it carries transcripts,
session ids and machine stats -- to every page on this machine is a real
access change to buy a development convenience. This proxy is read-only, is
one hard-coded path, and dies with Ctrl-C.

Deliberate limits, each one load-bearing rather than laziness -- and every
one of them proven by driving a REAL server on a real port, because the first
version of this file was guarded only by regexes over its own source, and an
aliased handler served the entire signals payload over POST while the gate
stayed green (test-adversary, 2026-08-15):
  * READ ONLY. GET and HEAD answer; every writing verb is refused 405. So
    nothing on this port can move a task, answer an approval, or fire an
    alert, whatever it asks for.
  * Exactly one proxied path, to exactly one constant upstream. The target
    is never taken from the request, and the query string is neither matched
    against nor forwarded.
  * Bound to 127.0.0.1, like the thing it proxies.
  * An unreachable OR MERELY SLOW feed answers 502 within a total budget,
    rather than hanging, because the page's honest ERROR state depends on
    getting an answer of some kind -- and a struggling voice server is a far
    likelier failure than a dead one. The budget covers the WHOLE exchange
    including the response HEADERS, which the first version of it did not:
    an upstream that accepted the connection and then dripped its status
    line held this proxy open for 52 seconds while every per-socket timeout
    came back inside 4 (test-adversary, 2026-08-15).
  * Only a bounded number of proxy fetches may be in flight at once. With
    the hang above, thirty concurrent requests put ninety-eight threads on
    this server, each wedged; a cap is what makes "it holds no state of its
    own" survive a bad upstream.
  * It does not serve its own source, and it lists no directories -- asked
    of the FILESYSTEM, not of the request string. The first version compared
    the raw path against a tuple of literals while the static handler
    normalised and unquoted afterwards, so `/./serve.py`, `/%73erve.py`,
    `/serve%2Epy`, `/SERVE.PY` and `/%72un.sh` all returned the file
    (reviewer + test-adversary, 2026-08-15, independently). A single-literal
    check is a grep that costs a socket to run.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

# The one path this server will fetch on the page's behalf, and the only
# upstream it knows. Both are constants on purpose: an open proxy that takes
# its target from the query string is a different and much worse program.
FEED_PATH = "/signals"
# Split into parts so the fetch can be driven by hand rather than through
# urlopen -- see _fetch_upstream for why owning the connection object is what
# makes the total budget real. UPSTREAM is DERIVED from them rather than
# written out a second time: two independent literals for one address is how
# a rename stays green.
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8765
UPSTREAM_PATH = "/signals"
UPSTREAM = f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}{UPSTREAM_PATH}"

# TWO DIFFERENT CEILINGS, because they answer two different questions.
# UPSTREAM_TIMEOUT is the per-socket-operation timeout: it bounds a
# server that never speaks. UPSTREAM_BUDGET bounds the WHOLE exchange, which
# is what a server that speaks slowly needs -- a drip upstream held this
# proxy open past 25 seconds while every per-read call came back inside 4
# (test-adversary, 2026-08-15). The docstring above promises "never hangs";
# only the total budget makes that true.
UPSTREAM_TIMEOUT = 4.0
UPSTREAM_BUDGET = 6.0
# A hard-coded loopback upstream still gets a cap: unbounded read() is how a
# dev tool turns one bad response into an out-of-memory.
UPSTREAM_MAX_BYTES = 8 * 1024 * 1024

# How many proxy fetches may be in flight at once. Past this the answer is an
# immediate 503 rather than another wedged thread: the page's honest ERROR
# state needs AN answer, and "the proxy is saturated" is one.
UPSTREAM_MAX_INFLIGHT = 8
_INFLIGHT = threading.BoundedSemaphore(UPSTREAM_MAX_INFLIGHT)

# Files this server refuses to hand out even though they sit in its own
# directory. A dev server serving its own source and a directory index is
# not a hole on loopback, but it is noise nobody asked for.
#
# THESE ARE FILENAMES, NOT REQUEST PATHS, and the difference is the whole
# bug: the check now resolves the request the way the static handler does
# and asks the filesystem whether it landed on one of these files. A tuple
# of request-path literals only ever refuses the spellings its author
# thought of, and five others walked straight past it.
PRIVATE_NAMES = ("serve.py", "run.sh")


def _private_paths() -> list[str]:
    """The real filesystem paths of the files this server will not hand out."""
    out = []
    for name in PRIVATE_NAMES:
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            out.append(os.path.realpath(p))
    return out


class OSHandler(SimpleHTTPRequestHandler):
    """Static files, plus the single read-only feed proxy."""

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # EVERY WRITING VERB IS REFUSED EXPLICITLY. BaseHTTPRequestHandler
    # already answers 501 for a verb it has no handler for, so these are
    # belt and braces -- but the property "nothing on this port can change
    # anything" is now a behavioural test against a live server rather than
    # a grep for `def do_POST` in this file, which is what let an aliased
    # handler serve the whole signals payload over POST while the gate
    # stayed green (test-adversary, 2026-08-15).
    def _refuse(self) -> None:
        self._json(405, {"error": "this server is read-only; GET and HEAD only"})

    do_POST = _refuse
    do_PUT = _refuse
    do_PATCH = _refuse
    do_DELETE = _refuse
    do_OPTIONS = _refuse

    def _blocked(self) -> bool:
        """Would this request hand out a private file, or a directory index?

        ASKED OF THE FILESYSTEM. `translate_path` is the stdlib's own
        resolution -- it unquotes the percent-encoding and collapses the dot
        segments -- so running the request through it and then comparing by
        INODE (`os.path.samefile`) answers the question the previous version
        only appeared to answer. Inode comparison is also what handles a
        case-insensitive volume, where `/SERVE.PY` and `/serve.py` are one
        file with two spellings and no amount of string work says so.
        """
        path = self.path.split("?", 1)[0]
        if path.endswith("/") and path != "/":
            return True
        try:
            landed = self.translate_path(path)
        except Exception:
            return True
        for private in _private_paths():
            try:
                if os.path.samefile(landed, private):
                    return True
            except OSError:
                # Not an existing file, or not reachable -- the static
                # handler will 404 it on its own merits.
                continue
        return False

    def do_GET(self) -> None:  # noqa: N802  (stdlib's spelling)
        # Compare against the path only -- a query string must not smuggle
        # this past the check, and must not reach the upstream either. The
        # upstream is a module constant and is NEVER taken from the request:
        # a proxy that reads its target from the query string is a different
        # and much worse program.
        if self.path.split("?", 1)[0] == FEED_PATH:
            self._proxy_feed(body=True)
            return
        if self._blocked():
            self._json(404, {"error": "not served"})
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        # HEAD used to fall through to the static handler and 404 on the one
        # path this server exists to serve. It answers the feed's headers now
        # -- without a body, and without asking the upstream for one.
        if self.path.split("?", 1)[0] == FEED_PATH:
            self._proxy_feed(body=False)
            return
        if self._blocked():
            self._json(404, {"error": "not served"})
            return
        super().do_HEAD()

    def _read_bounded(self, r, deadline: float) -> bytes:
        """Read the upstream under a TOTAL budget and a byte cap.

        READ1, NOT READ. `HTTPResponse.read(n)` blocks until it has n bytes
        or the body ends, so against a drip upstream the loop below never
        comes back round and the deadline is never consulted -- the first
        version of this budget was exactly that, and it hung for 30 seconds
        in its own test. `read1` returns whatever has actually arrived, so
        the deadline is checked between real chunks.

        IT IS NO LONGER THE THING THAT SAVES US, AND THE SENTENCE THAT SAID
        SO WAS FALSE. This docstring used to call `read1` "the whole
        difference between this working and only looking like it works".
        That stopped being true the moment the watchdog in `_fetch_upstream`
        started shutting the socket down at the deadline: an injection round
        on 2026-08-21 reverted `read1` to `read` and the gate stayed GREEN,
        because the socket teardown produces the 502 inside the budget
        regardless. So this is now DEFENCE IN DEPTH -- a second, cheaper
        bound that does not need a thread -- and the guarantee is the
        watchdog. Said plainly because prose running ahead of code is the
        fault this project has hit more times than any other, and an
        untested claim of load-bearingness is exactly that fault.

        The deadline is passed IN rather than started here, because by the
        time this runs the headers have already been read and that read is
        where a 52-second hang actually lived.
        """
        chunks: list[bytes] = []
        size = 0
        read_some = getattr(r, "read1", None) or r.read
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"upstream exceeded {UPSTREAM_BUDGET}s total budget")
            chunk = read_some(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > UPSTREAM_MAX_BYTES:
                raise ValueError("upstream response exceeds the byte cap")
            chunks.append(chunk)
        return b"".join(chunks)

    def _fetch_upstream(self) -> bytes:
        """One GET to the one constant upstream, under ONE total budget.

        Driven through `http.client` rather than `urlopen` for a single
        reason: this owns the connection object, and owning it is what makes
        the budget cover the RESPONSE HEADERS. `urlopen` hands back a
        response only once the status line and headers have arrived, so a
        budget started after it returns cannot bound the one phase where an
        upstream dripping its status line held this proxy for 52 seconds --
        every per-socket recv came back well inside 4.

        The watchdog SHUTS THE SOCKET DOWN rather than merely closing it: a
        close from another thread does not reliably wake a blocked recv,
        while a shutdown does. That is what turns the deadline from a
        statement into an event.
        """
        deadline = time.monotonic() + UPSTREAM_BUDGET
        conn = http.client.HTTPConnection(
            UPSTREAM_HOST, UPSTREAM_PORT, timeout=UPSTREAM_TIMEOUT
        )

        def guillotine() -> None:
            sock = getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            try:
                conn.close()
            except Exception:
                pass

        axe = threading.Timer(UPSTREAM_BUDGET, guillotine)
        axe.daemon = True
        axe.start()
        try:
            conn.request("GET", UPSTREAM_PATH)
            r = conn.getresponse()
            if r.status != 200:
                raise ValueError(f"upstream answered {r.status}")
            return self._read_bounded(r, deadline)
        except Exception as e:
            # WHATEVER SURFACES AFTER THE WATCHDOG HAS FIRED IS THE
            # GUILLOTINE LANDING, and it must be reported as the timeout it
            # is. Shutting the socket under a blocked reader leaves stdlib
            # internals in a half-torn-down state, so the exception that
            # escapes is an artefact of HOW we stopped waiting -- a
            # BadStatusLine on a header drip, an AttributeError on a body
            # drip. Naming those types in the catch list downstream would be
            # pinning the shape of a crash; asking the CLOCK is asking the
            # thing we actually mean.
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"upstream exceeded {UPSTREAM_BUDGET}s total budget"
                ) from e
            raise
        finally:
            axe.cancel()
            try:
                conn.close()
            except Exception:
                pass

    def _proxy_feed(self, body: bool = True) -> None:
        # THE CAP IS NON-BLOCKING ON PURPOSE. Queueing here would just move
        # the wedge from the upstream to this server's own accept loop.
        if not _INFLIGHT.acquire(blocking=False):
            self._json(503, {"error": f"more than {UPSTREAM_MAX_INFLIGHT} feed reads in flight"})
            return
        try:
            raw = self._fetch_upstream()
        except (OSError, http.client.HTTPException, ValueError, TimeoutError) as e:
            # The page needs an ANSWER to show ERROR honestly; a hang or a
            # traceback would leave the feed instrument stuck on CONFIGURING,
            # which reads as "still connecting" and is the wrong story.
            self._json(502, {"error": f"signals feed unreachable: {e}"})
            return
        finally:
            _INFLIGHT.release()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        # One line per request is noise for a static skeleton; failures of
        # the proxy are visible on the page itself, which is the point.
        pass


def main(argv: list[str]) -> int:
    port = int(argv[1]) if len(argv) > 1 else 8090
    handler = partial(OSHandler, directory=HERE)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(
        f"JARVIS OS skeleton at http://127.0.0.1:{port}/  "
        f"(proxying {FEED_PATH} from {UPSTREAM}; Ctrl-C stops this server and nothing else)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
