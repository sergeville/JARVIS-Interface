#!/usr/bin/env python3
"""Remove headless Chrome's ghosts from the Dock's recent-apps section.

Serge, 2026-08-06: "can you clean your self after running chrome."

Every headless Chrome that see-page.py spawns runs with its own throwaway
--user-data-dir, and macOS files each one as a freshly "recently used" app --
so three renders put three identical Chrome icons in his Dock. His real Chrome
is PINNED (persistent-apps), which makes a Chrome entry in recent-apps
redundant by definition: removing it can never cost him a way to launch
Chrome.

WHAT THIS TOUCHES, exactly and only:
    the `recent-apps` array of the com.apple.dock domain. It REMOVES entries
    that are Google Chrome; it never adds, never reorders survivors, and it
    never reads or writes `persistent-apps` (the pinned row) or any other key.
    If nothing was removed, nothing is written and the Dock is not restarted,
    so a clean run costs zero flicker.

HOW THE WRITE GOES IN -- through `defaults`, never a hand-edit of the plist.
    cfprefsd caches preferences in memory and can write its cached copy back
    over a directly-edited file; that bit us on the Finder settings and the
    caveat is on the record in the 2026-08-05 daily note. `defaults` talks to
    cfprefsd, so the edit lands in the cache AND the file.

The filter itself is a pure function over the plist data, because that is the
part that can silently go wrong (drop the wrong app, eat a survivor) and a
pure function is the part a test can hold.
"""

import plistlib
import subprocess
import sys

DOCK_DOMAIN = "com.apple.dock"
KEY = "recent-apps"

CHROME_BUNDLE = "com.google.chrome"
CHROME_URL_TAIL = "google%20chrome.app/"


def is_chrome(tile):
    """True if one recent-apps tile is Google Chrome, by bundle id or URL.

    Both spellings are matched because the Dock does not always write both
    fields; case-insensitively, because bundle ids compare that way.
    """
    if not isinstance(tile, dict):
        return False
    data = tile.get("tile-data", {})
    if not isinstance(data, dict):
        return False
    bundle = data.get("bundle-identifier", "")
    if isinstance(bundle, str) and bundle.lower() == CHROME_BUNDLE:
        return True
    url = (data.get("file-data") or {}).get("_CFURLString", "")
    return isinstance(url, str) and url.lower().rstrip().endswith(CHROME_URL_TAIL)


def filter_recents(tiles):
    """Return (survivors, removed_count). Pure -- no Dock, no defaults.

    Everything that is not Chrome survives, in its original order. Garbage
    entries (a non-dict in the array) survive too: this tool removes Chrome
    ghosts, it does not tidy other people's data.
    """
    if not isinstance(tiles, list):
        return [], 0
    survivors = [t for t in tiles if not is_chrome(t)]
    return survivors, len(tiles) - len(survivors)


def read_recents():
    """The current recent-apps array, via `defaults export` so cfprefsd's
    cache is the source, not a possibly-stale file on disk."""
    out = subprocess.run(
        ["defaults", "export", DOCK_DOMAIN, "-"],
        capture_output=True, check=True,
    ).stdout
    return plistlib.loads(out).get(KEY, [])


def write_recents(survivors):
    """Write the filtered array back and restart the Dock so it shows.

    `defaults write` with an XML plist literal, so arbitrarily-shaped tile
    dicts round-trip byte-faithfully. The Dock restart is what makes the
    change visible; it is only reached when something was actually removed.
    """
    xml = plistlib.dumps(survivors).decode()
    subprocess.run(["defaults", "write", DOCK_DOMAIN, KEY, xml], check=True)
    subprocess.run(["killall", "Dock"], check=True)


def clean():
    """Remove Chrome from the Dock recents. Returns how many were removed."""
    tiles = read_recents()
    survivors, removed = filter_recents(tiles)
    if removed:
        write_recents(survivors)
    return removed


def main(argv):
    if argv[1:]:
        print("usage: dock-clean.py   (no arguments; it does one thing)",
              file=sys.stderr)
        return 2
    try:
        removed = clean()
    except Exception as e:      # noqa: BLE001 -- a tool, not a hook; say why
        print(f"could not clean the Dock: {e}", file=sys.stderr)
        return 1
    if removed:
        print(f"removed {removed} Chrome ghost(s) from the Dock recents")
    else:
        print("Dock recents already clean -- nothing touched, no restart")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
