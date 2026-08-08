#!/usr/bin/env python3
"""Vault audit — find drift between the vault and its own map.

    python3 vault-tools/vault-audit.py            # report
    python3 vault-tools/vault-audit.py --quiet    # only complain if broken

Exit 0 when the vault is clean, 1 when it is not, so it can gate a checkpoint
the same way ./tests/run-tests.sh gates a code change.

Why this exists (Serge, 2026-08-05): two root notes — "How to Start Jarvis" and
the Session Board — had been sitting in the vault unlisted in VAULT-INDEX, and
nobody noticed for days. His words: "ensure that there's no stale MD file
anywhere in the index or in the vault... can you do something about that so it
does not happen again?"

A rule that is only enforced by remembering it is not enforced. The vault rules
say every note is listed in its folder's index and every index entry points at
a note that exists; this file is what makes those rules checkable in one second
instead of by reading twenty-six files.

WHAT IT CHECKS
  1. unlisted note   — a note its folder's index never mentions. The rule it
                       enforces: "a note the map doesn't show is one no future
                       session will find."
  2. phantom entry   — an index (or any note) links to [[something]] that does
                       not exist. The map promising a note that isn't there.
  3. missing index   — a folder with real content and no index note.
  4. no frontmatter  — every note must carry it.
  5. bad field value — status/project/type outside the allowed sets.

WHAT IT DOES NOT DO
  It never edits anything. Drift is reported for a human (or a session) to fix,
  because the right fix is a judgement call: sometimes the index is wrong, and
  sometimes the note should not exist.

A NOTE ON FOLDER INDEXES
  The index is named after the folder with its numeric prefix stripped:
  "02 - Learning AI/" -> "Learning AI.md". Getting that wrong is not
  theoretical — the first pass of this audit did exactly that and reported a
  clean vault while five folders went unchecked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent / "Jarvis-brain"

STATUS = {"active", "completed", "parked", "idea", "archived"}
PROJECT = {"learning-ai", "personal", "meta"}
TYPE = {"index", "reference", "guide", "plan", "log"}

# The root's index is not named after the root folder.
ROOT_INDEX = "VAULT-INDEX"

WIKILINK = re.compile(r"\[\[([^\]|#]+)")

# THE MIRRORED ASSETS -- vault copy, working original.
#
# Serge, 2026-08-07 ~8:00 PM, on the tradeoff being named out loud rather than
# waved past: "do what needs to be done so I don't lose track... that's going
# to be a reference point in a near future discussion."
#
# The concept images exist TWICE on purpose. Obsidian cannot embed a file
# outside the vault, so a vault copy is the only way the picture is visible
# where the idea is read; and the originals stay in `Jarvis Visual/references/`
# because CLAUDE.md names that folder as the home for design references and
# several notes cite that path as a record of what was filed where.
#
# TWO COPIES DRIFT. That is not a maybe, it is what copies do -- and the whole
# point of these images is to be a reference point in a LATER conversation, by
# which time nobody will remember which one was revised. So the rule ("revise
# in references/, re-copy to the vault") is not left to memory: this checks it.
# A rule enforced only by remembering is not enforced.
MIRRORED_ASSETS = [
    ("02 - Learning AI/JarvisOS5000-concept.png",
     "Jarvis Visual/references/JarvisOS5000.png"),
    ("02 - Learning AI/JarvisOS5000-concept-v2.png",
     "Jarvis Visual/references/JarvisOS5000-concept-v2.png"),
]
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def prose(text: str) -> str:
    """Text with code stripped.

    The vault documents its own syntax — VAULT-INDEX explains `[[links]]` and
    `[[old name]]`, Jarvis Conventions shows `[[link]]`. Those are examples in
    backticks, not claims that a note exists. Scanning them produced three
    phantom-link reports on the first run, and a checker that cries wolf is one
    nobody reads.
    """
    return INLINE_CODE.sub("", FENCE.sub("", text))


def index_name(folder: Path) -> str:
    """'02 - Learning AI' -> 'Learning AI'; the numeric prefix is not part of it."""
    return re.sub(r"^\d+\s*-\s*", "", folder.name)


def notes_in(vault: Path) -> list[Path]:
    return sorted(p for p in vault.rglob("*.md") if ".obsidian" not in p.parts)


def frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def audit(vault: Path) -> list[tuple[str, str]]:
    """Return a list of (kind, message). Empty means clean."""
    problems: list[tuple[str, str]] = []
    notes = notes_in(vault)
    stems = {p.stem for p in notes}

    # folder -> its index note
    indexes: dict[Path, Path] = {}
    folders = {p.parent for p in notes}
    for folder in folders:
        want = ROOT_INDEX if folder == vault else index_name(folder)
        cand = folder / f"{want}.md"
        if cand.exists():
            indexes[folder] = cand

    for folder in sorted(folders, key=str):
        others = [p for p in notes if p.parent == folder
                  and p != indexes.get(folder)]
        if folder not in indexes:
            # A folder holding real notes with no map of its own.
            if others:
                rel = folder.relative_to(vault) if folder != vault else Path(".")
                problems.append(("missing index",
                                 f"{rel}/ has {len(others)} note(s) and no "
                                 f"{index_name(folder)}.md"))
            continue
        idx_text = indexes[folder].read_text(encoding="utf-8", errors="replace")
        for p in sorted(others, key=str):
            if p.stem not in idx_text:
                problems.append(("unlisted note",
                                 f"{p.relative_to(vault)} is not mentioned in "
                                 f"{indexes[folder].name}"))

    # Every wikilink anywhere must resolve. An index promising a note that does
    # not exist is the same lie as a note the index never mentions.
    for p in notes:
        text = p.read_text(encoding="utf-8", errors="replace")
        for target in {m.strip() for m in WIKILINK.findall(prose(text))}:
            # Obsidian accepts a path-form link ("06 - Email Inbox/2026-08-04"),
            # which is how two notes sharing a name are told apart. Resolve to
            # the final segment before calling it broken.
            target = target.rstrip("/").split("/")[-1]
            # AN EMBED IS NOT A NOTE LINK. `![[picture.png]]` points at a FILE
            # in the vault, and it resolves if that file is there -- checking
            # it against note stems would report every image as broken, which
            # is the fastest way to teach someone to ignore this tool.
            if "." in target and not target.endswith(".md"):
                if not any(f.name == target for f in vault.rglob("*")
                           if f.is_file()):
                    problems.append(("missing file",
                                     f"{p.relative_to(vault)} embeds "
                                     f"{target}, which is not in the vault"))
                continue
            if target and target not in stems:
                problems.append(("phantom link",
                                 f"{p.relative_to(vault)} links to "
                                 f"[[{target}]], which does not exist"))

    for p in notes:
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm is None:
            problems.append(("no frontmatter", str(p.relative_to(vault))))
            continue
        for key, allowed in (("status", STATUS), ("project", PROJECT),
                             ("type", TYPE)):
            val = fm.get(key)
            if val is None:
                problems.append(("missing field",
                                 f"{p.relative_to(vault)} has no {key}"))
            elif val not in allowed:
                problems.append(("bad field",
                                 f"{p.relative_to(vault)} {key}: {val!r} is "
                                 f"not one of {sorted(allowed)}"))
    problems += mirror_drift(vault)
    return problems


def mirror_drift(vault: Path) -> list[tuple[str, str]]:
    """Report any vault copy that has stopped matching its working original.

    Compared BYTE FOR BYTE, not by size or timestamp: a re-export of the same
    picture changes both of those without changing anything that matters, and
    an edit can leave the size identical. The question being asked is "are
    these still the same file", and only the bytes answer it.
    """
    import hashlib
    root = vault.parent
    out: list[tuple[str, str]] = []
    for vault_rel, origin_rel in MIRRORED_ASSETS:
        copy, origin = vault / vault_rel, root / origin_rel
        # A MISSING FILE IS REPORTED, NEVER SKIPPED. "It isn't there, so
        # there's nothing to compare" is how a check quietly stops checking.
        if not copy.exists():
            out.append(("mirror missing", f"{vault_rel} is gone from the vault "
                                          f"(original still at {origin_rel})"))
            continue
        if not origin.exists():
            out.append(("mirror missing", f"{origin_rel} is gone -- the vault "
                                          f"copy is now the only one left"))
            continue
        digest = [hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in (copy, origin)]
        if digest[0] != digest[1]:
            out.append(("mirror drift",
                        f"{vault_rel} no longer matches {origin_rel} -- "
                        f"revise in references/ and re-copy to the vault"))
    return out


def main() -> int:
    quiet = "--quiet" in sys.argv
    if not VAULT.is_dir():
        print(f"vault not found: {VAULT}")
        return 1
    problems = audit(VAULT)
    if not problems:
        if not quiet:
            n = len(notes_in(VAULT))
            print(f"vault clean — {n} notes, every one listed and linked.")
        return 0
    print(f"VAULT DRIFT — {len(problems)} problem(s):\n")
    kind_w = max(len(k) for k, _ in problems)
    for kind, msg in problems:
        print(f"  {kind.ljust(kind_w)}  {msg}")
    print("\nNothing was changed. Fix the map or the note, then re-run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
