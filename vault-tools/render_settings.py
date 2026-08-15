#!/usr/bin/env python3
"""Render templates/claude-settings.json.template into a .claude/settings.json.

WHY THIS IS NOT IN install.sh ANY MORE. It used to be nine lines of bash with
one branch that did nothing:

    if grep -q "{{JARVIS_ROOT}}" "$dest"; then  sed -i '' ...   # substitute
    else                                        kept=$((kept+1))  # LEAVE IT
    fi

So a settings.json that had already been rendered once was never looked at
again. Every later template change -- a new hook, a corrected timeout -- was
silently never delivered to any machine that had run the installer before,
and the installer reported "already configured" while saying it. Found
2026-08-14, when board-guard.py's missing `"timeout": 15` was fixed in the
template and both deployed files had to be edited BY HAND, because re-running
the installer would not have delivered it either.

WHY THE OBVIOUS FIX IS WRONG. "Just re-render it" destroys the user's own
`permissions` block -- the allow-list they granted by hand, decision by
decision -- and install.sh's third rule, in its own header, is IT NEVER
DESTROYS. The bash comment that guarded that branch was right about the
danger and wrong about the remedy: it protected the whole file when only one
key needed protecting.

SO: THE TEMPLATE OWNS `hooks`. THE USER KEEPS EVERY OTHER KEY.
And that sentence is deliberately narrower than the one first shipped here,
which said "the user owns everything else" and was FALSE: `hooks` is replaced
WHOLE, so a hook the user added is deleted and a hook they deliberately
removed is restored. Both review agents caught it. That is still the right
boundary -- hooks are machinery, carrying absolute paths and timeouts, and a
clone has no business holding a stale copy -- but it is a REPLACEMENT, it is
said so here, and every run now PRINTS what it changed. The mode that changes
nothing used to name the hook it was about to delete while the mode that
deleted it stayed silent; that was the same "write right, record silent"
failure this whole change exists to end.

EXIT CODES, distinct on purpose. `--check` returns 1 for drift, so an
unhandled crash returning 1 too would be read by install.sh as staleness --
it reported tracebacks as drift detail until this was split out.
    0  nothing to do, or done
    1  drift found (--check only)
    2  the TEMPLATE is unusable -- a repo defect
    3  the DESTINATION is unusable -- left strictly untouched
    4  anything unforeseen

Run:
  render_settings.py --root R --template T --dest D          # write
  render_settings.py --root R --template T --dest D --check   # report only
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

PLACEHOLDER = "{{JARVIS_ROOT}}"

# The template owns exactly this key. A constant so the test can assert the
# boundary rather than re-describe it: widening this silently would start
# overwriting the user's own keys on every install.
TEMPLATE_OWNS = ("hooks",)

# Backups accumulate otherwise. They sit in .claude/ next to a file the user
# cares about, and an unbounded pile of them is its own small mess.
KEEP_BACKUPS = 5


def substitute(text: str, root: str) -> str:
    """Put this clone's root in, JSON-safely.

    The root goes into JSON *source* before it is parsed, so it has to be
    escaped as JSON would escape it. Substituting raw, a home directory
    containing a backslash silently became an escape sequence -- `a\\bc` came
    out as a backspace character inside the rendered command -- and one
    containing a quote made the TEMPLATE look malformed, blaming the repo for
    the user's directory name.
    """
    return text.replace(PLACEHOLDER, json.dumps(root)[1:-1])


def merge(template: dict, existing: dict | None) -> tuple[dict, list]:
    """(what the file should contain, what changed). Keeps every user key."""
    if existing is None:
        return template, ["created from the template"]
    out = dict(existing)
    changes = []
    for key in TEMPLATE_OWNS:
        if existing.get(key) != template[key]:
            out[key] = template[key]
            changes.append(f"{key} replaced from the template")
    return out, changes


# Script suffixes a hook command can name. Anything else is an argument.
_SCRIPT_SUFFIXES = (".py", ".sh", ".js", ".rb", ".pl")


def _script_name(cmd: str) -> str:
    """The basename of the script a hook command runs. Never an argument.

    TWO WRONG ANSWERS CAME FIRST, and both are worth keeping written down.
    `cmd.split("/")[-1]` kept everything after the last slash, so a hook
    invoked with `--token=sk-live-...` printed the token, and a command with
    no slash printed the whole line. Then the correction -- take the FIRST
    whitespace token -- removed the leak and the information with it: every
    hook here is `python3 something`, so every one of them reported as
    "python3" and the report said nothing at all.

    So: the first token that NAMES A SCRIPT and is not a flag, basenamed.
    A flag is excluded explicitly, because `--out=/tmp/secret.py` ends in a
    script suffix and is still an argument.
    """
    tokens = cmd.split()
    for tok in tokens:
        if tok.startswith("-"):
            continue
        if tok.lower().endswith(_SCRIPT_SUFFIXES):
            return tok.rsplit("/", 1)[-1]
    return (tokens or ["?"])[0].rsplit("/", 1)[-1]


def _shape(d):
    """{event:script -> timeout} for a settings dict. Never a command string.

    The name is the FIRST whitespace-separated token's basename, and both
    halves of that matter. Taking `command.split("/")[-1]` alone kept every
    argument after the last slash, so a hook invoked with `--token=sk-live-…`
    printed the token; and for a command with no slash at all the split was a
    no-op and printed the whole line. Both were reproduced against the shipped
    file, and the test fixture -- a command with a slash and no arguments --
    was the one shape that could not reveal either.
    """
    out = {}
    for event, groups in (d.get("hooks") or {}).items():
        for g in groups or []:
            for i, h in enumerate(g.get("hooks", []) or []):
                name = _script_name(str(h.get("command", "?")))
                key = f"{event}:{name}"
                # Two hooks in one event can share a basename; without the
                # index the second overwrote the first and a whole added hook
                # was invisible in the report.
                while key in out:
                    i += 1
                    key = f"{event}:{name}#{i}"
                out[key] = h.get("timeout")
    return out


def describe_hook_drift(template: dict, existing: dict | None) -> list:
    """One line per hook difference, for a human. Shape only, never contents."""
    if existing is None:
        return ["no settings.json yet"]
    a, b = _shape(existing), _shape(template)
    lines = []
    for k in sorted(set(a) | set(b)):
        if k not in a:
            lines.append(f"adding hook {k}")
        elif k not in b:
            lines.append(f"REMOVING hook {k} (not in the template)")
        elif a[k] != b[k]:
            lines.append(f"{k} timeout {a[k]} -> {b[k]}")
    return lines


def _prune_backups(dest: Path) -> None:
    for old in sorted(dest.parent.glob(dest.name + ".backup-*"),
                      key=lambda p: p.name)[:-KEEP_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def _backup_path(dest: Path) -> Path:
    """A name no concurrent run can collide with.

    Second-resolution alone gave ONE backup for two runs in the same second --
    the later copy silently overwrote the earlier, which is a lost original in
    the one file whose whole job is not to lose the original.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = dest.with_name(f"{dest.name}.backup-{stamp}")
    if not base.exists():
        return base
    n = 2
    while base.with_name(f"{base.name}.{n}").exists():
        n += 1
    return base.with_name(f"{base.name}.{n}")


def _write_atomically(dest: Path, data: dict) -> None:
    """Write via a temp file and rename, never truncate in place.

    Claude Code reads this file. `write_text` truncates first, so a reader
    landing in that window gets an empty or half-written config.
    """
    tmp = dest.with_name(f".{dest.name}.tmp-{os.getpid()}")
    # ensure_ascii=False: the default rewrites a user's non-ASCII path into
    # \\uXXXX escapes, so "carried across untouched" was true semantically and
    # false byte-wise -- and this file is one a person reads and edits.
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, dest)


def run(root: str, template_path: Path, dest: Path, check: bool) -> int:
    if not template_path.is_file():
        print("template is missing", file=sys.stderr)
        return 2
    try:
        template = json.loads(substitute(template_path.read_text(), root))
    except ValueError as exc:
        print(f"template does not parse: {exc}", file=sys.stderr)
        return 2
    if not isinstance(template, dict):
        print("template is not an object", file=sys.stderr)
        return 2
    for key in TEMPLATE_OWNS:
        # A template that has lost the key it owns reported "current" and the
        # installer said "already configured" -- eight days of silence,
        # reproduced inside the fix for eight days of silence.
        if key not in template:
            print(f"template has no {key!r} key", file=sys.stderr)
            return 2

    # A symlinked dest must be written THROUGH, and backed up at its target;
    # otherwise the backup sits beside the link and the rename replaces the
    # link itself.
    if dest.is_symlink():
        dest = dest.resolve()

    existing = None
    placeholder_repaired = False
    if dest.exists():
        if not dest.is_file():
            print("destination is not a regular file", file=sys.stderr)
            return 3
        try:
            raw = dest.read_text()
        except OSError as exc:
            print(f"destination cannot be read: {exc}", file=sys.stderr)
            return 3
        # A dest still carrying the placeholder is exactly what the old `sed`
        # handled and this helper first did not: the shipped template puts
        # {{JARVIS_ROOT}} inside `permissions`, a USER-OWNED key, so carrying
        # that key across verbatim left the placeholder in place and the
        # installer's own verifier then failed forever, in both modes, with no
        # way to self-heal.
        if PLACEHOLDER in raw:
            raw = substitute(raw, root)
            placeholder_repaired = True
        try:
            existing = json.loads(raw)
        except ValueError:
            print("existing settings.json does not parse -- left untouched, "
                  "nothing written", file=sys.stderr)
            return 3
        if not isinstance(existing, dict):
            # Parseable but not an object: `null`, `[]`, `5`, `"hi"`. These
            # used to crash or, worse, write.
            print("existing settings.json is not an object -- left untouched",
                  file=sys.stderr)
            return 3
    merged, changes = merge(template, existing)
    if placeholder_repaired:
        changes.append("an unrendered {{JARVIS_ROOT}} placeholder was resolved")
    if not changes:
        print("current")
        return 0

    detail = describe_hook_drift(template, existing)
    if check:
        for line in detail or changes:
            print(f"drift: {line}")
        return 1

    if dest.exists():
        backup = _backup_path(dest)
        backup.write_text(dest.read_text())
        print(f"backed up: {backup.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(dest, merged)
    _prune_backups(dest)
    # SAY WHAT CHANGED, on this path too. --check named the hook it was about
    # to delete; the write path printed only "hooks updated" and deleted it in
    # silence. Same "write right, record silent" shape the whole change exists
    # to end, committed by the fix itself.
    for line in changes:
        print(line)
    for line in detail:
        print(f"  {line}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    try:
        return run(a.root, Path(a.template), Path(a.dest), a.check)
    except Exception:
        # Exit 4, never 1. install.sh reads 1 as "behind the template" and was
        # printing traceback lines as drift detail.
        traceback.print_exc(file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
