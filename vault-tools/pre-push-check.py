#!/usr/bin/env python3
"""Refuse a push that would publish a secret. Installed as .git/hooks/pre-push.

WHY THIS EXISTS, and why it is a HOOK and not a habit.
=======================================================
Serge, 2026-08-07 ~2:25 PM, on being asked to approve a push he had just
ordered: "it's funny because I ask you to do something and then you ask me."
He was right -- the approval popup was not protecting him. He approved it
every time without re-reading the diff, and a gate you always open is a
rubber stamp, not a gate.

So `git push` became an allowed command, and the protection moved HERE. That
trade is only honest if the replacement actually runs. The offer on the table
was "I will scan before every push", and a promise by the thing being guarded
is exactly the shape this project has been burned by:

    A RULE ENFORCED ONLY BY REMEMBERING IT IS NOT ENFORCED.

A pre-push hook is enforced by git. It runs whether Jarvis remembers, whether
Serge pushes by hand, and whether the session that wrote the commit is still
alive. Nothing has to look it up.

WHAT IT COSTS TO BE WRONG, which is what sets the strictness.
=============================================================
The repo is PUBLIC (sergeville/JARVIS-Interface). On 2026-08-06 Serge's real
Gmail address was found in 23 already-published commits, and his call was to
leave them -- because a public commit cannot be recalled, only rewritten, and
the copies are already gone. That is the whole argument for failing closed:
a false alarm costs one --no-verify; a miss cannot be taken back.

WHAT IT CHECKS
==============
Only what is genuinely about to be published: the diff of the commits this
push would send, never the working tree. A pattern hit REFUSES the push and
names the file and line so it can be fixed, never "fixed" silently by this
script -- deciding what a secret should become is a judgement call, and this
tool does not make judgement calls. Same doctrine as vault-audit.py.

Deliberately NOT here:
  - No network. No writes. No subprocess other than git itself.
  - It never reads a file off disk -- only what git hands it.
  - It cannot be made to pass by editing this file, because the suite
    asserts the patterns exist (tests/test_pre_push.py).

HOW TO GET PAST IT when a hit is a false positive: `git push --no-verify`,
which is deliberate, visible, and Serge's to type.

HOW TO REMOVE IT ENTIRELY (written down, because a removal route nobody can
find is the same as none): delete .git/hooks/pre-push, delete
vault-tools/pre-push-check.py, delete Jarvis Visual/tests/test_pre_push.py,
and remove "Bash(git push:*)" from both .claude/settings.json files and the
template -- the allow-rule exists BECAUSE this guard does, so it goes too.
"""
import re
import subprocess
import sys

# Each pattern is a thing that must never reach a public repo. They are
# deliberately narrow: a pattern that fires on ordinary prose gets ignored,
# and an ignored guard is off. "a checker that cries wolf is one nobody reads."
PATTERNS = [
    ("a Gmail address", re.compile(r"[A-Za-z0-9._%+-]+@gmail\.com", re.I)),
    ("an Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("an OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("a private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}")),
    # An assignment, not the bare word -- "password" appears in prose all over
    # this repo's comments, and firing on that is how the guard gets disabled.
    ("an assigned secret",
     re.compile(r"\b(?:password|passwd|secret|api_key|apikey|access_token)\b"
                r"\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']", re.I)),
]

# This file quotes every pattern it looks for, so it would flag itself.
SKIP_PATHS = ("vault-tools/pre-push-check.py",
              "Jarvis Visual/tests/test_pre_push.py")


def findings(diff):
    """Pure, so the part that can silently go wrong is the part a test holds.

    Reads only ADDED lines: a diff that DELETES a leaked key is the fix, and
    refusing it would leave the secret in place -- the exact inversion.
    """
    out, path = [], "?"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if any(path.startswith(s) for s in SKIP_PATHS):
            continue
        for label, rx in PATTERNS:
            if rx.search(line):
                out.append((path, label, line[1:].strip()[:120]))
    return out


def range_for(local_sha, remote_sha):
    """What this push would actually add. A brand-new branch has no remote
    counterpart, so fall back to everything not already on origin -- NOT to
    the whole history, which would refuse forever on the 23 commits Serge
    deliberately kept."""
    zero = "0" * 40
    if remote_sha == zero:
        # ORDER IS LOAD-BEARING and it shipped wrong once: `--not` negates
        # everything that FOLLOWS it, so "--not --remotes=origin <sha>"
        # excludes the very commits being pushed and yields an empty diff --
        # which reads exactly like "clean". The end-to-end test caught it;
        # every source-reading test passed. The sha goes FIRST.
        return [local_sha, "--not", "--remotes=origin"]
    return [f"{remote_sha}..{local_sha}"]


def main():
    hits, checked = [], 0
    for raw in sys.stdin.read().splitlines():
        parts = raw.split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha == "0" * 40:          # a branch deletion pushes nothing
            continue
        cmd = ["git", "log", "-p", "--no-color"] + range_for(local_sha, remote_sha)
        r = subprocess.run(cmd, capture_output=True, text=True)
        # FAIL CLOSED on a git that did not answer. Caught by this file's own
        # test before it ever ran for real: a failed `git log` returns empty
        # stdout, empty stdout finds nothing, and nothing found reads exactly
        # like "clean". THE SCANNER CANNOT TELL "no secrets" FROM "I could not
        # look" -- so it must never collapse them, and the one that costs
        # Serge a published key is the wrong guess.
        if r.returncode != 0:
            print(f"\nPUSH REFUSED -- could not read what this push would "
                  f"send:\n  {' '.join(cmd)}\n  {r.stderr.strip()[:300]}\n"
                  "That is not the same as finding nothing.\n", file=sys.stderr)
            return 1
        checked += 1
        hits.extend(findings(r.stdout))

    if not hits:
        # Silent when there is nothing to say. A hook that speaks on every
        # run becomes wallpaper, and wallpaper is what the eye stops seeing.
        return 0

    print("\nPUSH REFUSED -- this would publish a secret to a PUBLIC repo.\n",
          file=sys.stderr)
    seen = set()
    for path, label, text in hits:
        key = (path, label, text)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {path}: {label}\n    {text}", file=sys.stderr)
    print("\nNothing was changed and nothing was pushed. Fix the line, amend "
          "the commit, and push again.\nIf this is a false alarm, "
          "`git push --no-verify` -- deliberate, visible, and Serge's to type.\n",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        # FAIL CLOSED. Every other hook in this project swallows and exits 0,
        # because a broken hook must not cost a session. This one is the
        # opposite on purpose: a scanner that breaks and waves the push
        # through is worse than no scanner, since it is TRUSTED.
        print(f"\nPUSH REFUSED -- the secret scanner itself failed: {exc}\n"
              "Fix it, or `git push --no-verify` if you accept the risk.\n",
              file=sys.stderr)
        sys.exit(1)
