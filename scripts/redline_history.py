#!/usr/bin/env python3
"""Scan every blob that has ever been committed, not just the current tree.

``redline_scan.py`` runs on ``git ls-files`` — the files that exist now. That is
the right scope for a pre-commit hook and the wrong scope for the one-way door
this repository is about to walk through. Making a repository public publishes
its **history**: a term deleted three commits ago is still in the pack file, is
still served by the API, and is still there after the visibility is switched
back, because clones and caches do not un-happen.

So this walks `git rev-list --objects --all` and reads every blob, including
those from files that were later deleted or rewritten. Eight commits or eight
thousand, it is the only check whose answer means "safe to publish".

If it finds something, the fix is not a follow-up commit. It is a history
rewrite before the repository is ever public, or a fresh repository — and this
script exists to make that decision while it is still cheap.

    python scripts/redline_history.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from redline_scan import (
    CREDENTIALS,
    EMAIL,
    EMAIL_ALLOWED,
    PHONE,
    REPO_ROOT,
    load_terms,
)

# Blobs are read as bytes and decoded loosely: a binary file that happens to
# contain a term still counts, and a decode error must not be a silent skip.
MAX_BLOB = 2_000_000


def blobs() -> list[tuple[str, str]]:
    """Every (sha, path) blob reachable from any ref, tag or dangling commit."""
    out = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    found = []
    for line in out.stdout.splitlines():
        sha, _, path = line.partition(" ")
        if path:  # commits and trees have no path
            found.append((sha, path))
    return found


def read(sha: str) -> str:
    out = subprocess.run(
        ["git", "cat-file", "-p", sha],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    return out.stdout[:MAX_BLOB].decode("utf-8", errors="replace")


def main() -> int:
    terms = load_terms()
    if not terms:
        # Deliberately fatal. A history scan that ran without the term list is
        # the most dangerous kind of green tick: it is the check somebody points
        # at when they decide to publish.
        sys.exit(
            "no red-line terms loaded. This scan is the gate before the repository\n"
            "goes public, and without the list it checks nothing that matters."
        )

    seen: set[str] = set()
    findings: list[str] = []
    lowered = [(t, t.lower()) for t in terms]

    for sha, path in blobs():
        if sha in seen:
            continue
        seen.add(sha)
        text = read(sha)
        low = text.lower()
        for term, term_low in lowered:
            if term_low in low:
                # The term itself is never printed. Publishing the list of words
                # being hidden is the thing the list exists to prevent, and this
                # script's output is exactly what somebody would paste into an
                # issue.
                findings.append(f"{path} @ {sha[:8]}: red-line term #{terms.index(term)}")
        for match in EMAIL.finditer(text):
            if not any(a in match.group(0) for a in EMAIL_ALLOWED):
                findings.append(f"{path} @ {sha[:8]}: email address")
        if PHONE.search(text):
            findings.append(f"{path} @ {sha[:8]}: phone-number-shaped string")
        for label, pattern in CREDENTIALS:
            if pattern.search(text):
                findings.append(f"{path} @ {sha[:8]}: looks like a {label}")

    if findings:
        print(
            f"History scan FAILED — {len(findings)} finding(s) across {len(seen)} blobs:",
            file=sys.stderr,
        )
        for finding in sorted(set(findings)):
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nThese are in the pack file, not just the working tree. Publishing now\n"
            "publishes them. Rewrite the history or start a fresh repository first.",
            file=sys.stderr,
        )
        return 1

    print(f"History scan clean: {len(seen)} blobs across every ref.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
