#!/usr/bin/env python3
"""The version that counts itself -- Phase 0 of the JarvisOS 5000 plan.

Serge, 2026-08-07 ~8:35 AM: *"Before doing any action on this plan we need to
create a snapshot or version of what it is before doing any upgrade. The
upgrade version should increment automatically."*

WHY A SCRIPT AND NOT A HABIT. A version typed by hand is a rule enforced only
by remembering it, and this project's whole record says that is not enforced
at all. So the number is derived from the repo's own tags, stamped into the
page, and tagged in one step that either completes or refuses.

WHAT IT DOES NOT DO, deliberately:

  * It never invents markup. If the page carries no SHIP_VERSION constant it
    REFUSES and says so, rather than editing HTML it was not shown. Adding
    that constant belongs to the phase that builds the brand block, not to
    the tool that fills it in.
  * It never pushes unless asked (--push), and never on a dirty tree. A
    version tag that names a commit nobody else can see is a bookmark to
    nowhere, and stamping a tree with uncommitted work in it dates the wrong
    thing.
  * It does nothing at all without --ship. The default run is a dry report:
    what it would call this version, and what it would touch.

Usage:
    ship-version.py                      # report only -- what would happen
    ship-version.py --minor --ship       # a phase shipped
    ship-version.py --patch --ship       # a fix on a shipped phase
    ship-version.py --minor --ship --push
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "Jarvis Visual" / "jarvis.html"

# The one line the stamper is allowed to rewrite. Anchored on both sides so a
# mention of the name in a comment cannot be mistaken for the constant -- the
# comment-vs-code trap this project has lost to seven times.
STAMP_RE = re.compile(r"(const SHIP_VERSION\s*=\s*')([^']*)(';)")


def git(*args, cwd=ROOT):
    """Run git and return stdout, or raise with git's own words."""
    p = subprocess.run(("git",) + args, cwd=str(cwd),
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git " + " ".join(args) + ": " + p.stderr.strip())
    return p.stdout.strip()


def parse_version(tag):
    """'v1.2.3' -> (1, 2, 3). Anything else -> None, never a guess."""
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def newest(tags):
    """The highest v-tag, compared as NUMBERS, not as text.

    String order would put v1.10.0 before v1.9.0 and the whole scheme would
    walk backwards at the tenth phase. Unparseable tags are ignored rather
    than crashing -- a repo may carry tags this scheme knows nothing about.
    """
    versions = [v for v in (parse_version(t) for t in tags) if v]
    return max(versions) if versions else None


def next_version(tags, part):
    """(tags, 'minor'|'patch') -> the next version string.

    No tags at all means this is the first ship, and the first ship is
    v1.0.0 -- NOT v0.0.1. The original is what v1.0.0 marks, so starting
    anywhere else would make the page claim to be older than its snapshot.
    """
    cur = newest(tags)
    if cur is None:
        return "v1.0.0"
    major, minor, patch = cur
    if part == "minor":
        return f"v{major}.{minor + 1}.0"
    if part == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    if part == "major":
        # A NEW WORLD, not a new phase. Serge, 2026-08-08, on the redesign's
        # first ship: "actually it should be v2.0.0." A major bump is the
        # honest shape for a release that changes what the thing IS, and it
        # has to live in the tool -- a version typed by hand is the rule
        # enforced only by remembering, which is the whole reason this script
        # exists.
        return f"v{major + 1}.0.0"
    raise ValueError("part must be 'major', 'minor' or 'patch', got " + repr(part))


def stamp(text, version):
    """Rewrite the SHIP_VERSION constant. Returns (new_text, old_version).

    Raises if the constant is missing or appears more than once: two
    constants means two answers to the same question, and the page would
    show whichever one happened to run last.
    """
    hits = STAMP_RE.findall(text)
    if not hits:
        raise RuntimeError(
            "the page carries no SHIP_VERSION constant -- refusing to invent "
            "one. Add `const SHIP_VERSION = 'v0.0.0';` to the brand block in "
            "the phase that builds it, then ship.")
    if len(hits) > 1:
        raise RuntimeError(
            f"{len(hits)} SHIP_VERSION constants in the page -- refusing to "
            "guess which one the brand block reads.")
    old = hits[0][1]
    return STAMP_RE.sub(lambda m: m.group(1) + version + m.group(3), text), old


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=True)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--minor", action="store_true", help="a phase shipped")
    g.add_argument("--patch", action="store_true", help="a fix shipped")
    g.add_argument("--major", action="store_true",
                   help="a new world -- resets minor and patch to zero")
    ap.add_argument("--ship", action="store_true",
                    help="actually stamp and tag (default: report only)")
    ap.add_argument("--push", action="store_true",
                    help="push the commit and the tag (implies --ship)")
    args = ap.parse_args(argv)

    part = "major" if args.major else "patch" if args.patch else "minor"
    tags = git("tag", "--list", "v*").splitlines()
    version = next_version(tags, part)
    cur = newest(tags)
    print(f"current  {'v%d.%d.%d' % cur if cur else '(no version tags)'}")
    print(f"next     {version}   ({part} bump)")

    if not (args.ship or args.push):
        print("\nreport only -- nothing was changed. Pass --ship to act.")
        return 0

    # A dirty tree is refused, not tidied. The tag must name a commit that
    # actually contains the shipped work; stamping over uncommitted edits
    # would date a tree nobody can get back to.
    dirty = git("status", "--porcelain")
    if dirty:
        print("\nREFUSING -- the tree is not clean:\n" + dirty, file=sys.stderr)
        return 2

    if git("tag", "--list", version):
        print(f"\nREFUSING -- {version} already exists.", file=sys.stderr)
        return 2

    text = PAGE.read_text()
    try:
        new_text, old = stamp(text, version)
    except RuntimeError as e:
        print("\nREFUSING -- " + str(e), file=sys.stderr)
        return 2

    PAGE.write_text(new_text)
    print(f"stamped  {old or '(empty)'} -> {version} in {PAGE.name}")
    git("add", str(PAGE))
    git("commit", "-m", f"Ship {version}")
    git("tag", "-a", version, "-m", f"JarvisOS {version}")
    print(f"tagged   {version} on {git('rev-parse', '--short', 'HEAD')}")

    if args.push:
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        git("push", "origin", branch)
        git("push", "origin", version)
        print(f"pushed   {branch} and {version}")
    else:
        print("not pushed -- pass --push, or push yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
