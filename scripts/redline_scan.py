#!/usr/bin/env python3
"""Refuse to commit anything that must not become public.

Two layers, because they protect against different things and only one of them
can live in a public repository:

**Layer 1 — generic patterns (committed, runs everywhere including CI).**
Credentials, email addresses and phone numbers. These are recognisable by shape,
so the rules can be public without telling a reader anything.

**Layer 2 — a local term list (``.redline-terms``, gitignored).**
Names that must never appear: an employer, a customer, an internal system. This
list cannot be committed, because committing the list of words you are hiding
publishes the words you are hiding. Hashing them is not a fix either — a short
proper noun falls to a wordlist in seconds.

So layer 2 runs on the machine where the words are known, at ``pre-commit``,
before anything leaves the disk. CI cannot run it, and that is not a gap being
ignored: the commit hook is the enforcement point, and CI is a second opinion on
everything that does not need the secret list.

Usage:
    python scripts/redline_scan.py [paths...]     # defaults to git-tracked files
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = REPO_ROOT / ".redline-terms"

# Data files are only allowed under examples/, which is synthetic by definition.
BLOCKED_SUFFIXES = {".csv", ".tsv", ".xls", ".xlsx", ".jsonl", ".ndjson", ".parquet", ".db"}
DATA_ALLOWED_DIRS = ("examples/",)

SKIP_DIRS = (".git/", ".venv/", "__pycache__/", ".mypy_cache/", ".ruff_cache/", ".pytest_cache/")

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
EMAIL_ALLOWED = ("@example.com", "@example.org", "users.noreply.github.com")

PHONE = re.compile(r"(?<!\d)(?:\+1[ -]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")

CREDENTIALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line]


def load_terms() -> list[str]:
    if not TERMS_FILE.exists():
        return []
    terms = []
    for line in TERMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line.lower())
    return terms


def scan(paths: list[Path], terms: list[str]) -> list[str]:
    findings: list[str] = []

    for path in paths:
        try:
            rel = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = path.as_posix()

        if any(part in rel for part in SKIP_DIRS):
            continue
        if not path.is_file():
            continue

        if path.suffix.lower() in BLOCKED_SUFFIXES and not rel.startswith(DATA_ALLOWED_DIRS):
            findings.append(f"{rel}: data file outside examples/ ({path.suffix})")

        # This scanner defines the patterns it looks for, so it would report
        # itself on every run. Its own literals are shapes, not secrets.
        if rel == "scripts/redline_scan.py":
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        lowered = text.lower()
        for term in terms:
            if term in lowered:
                findings.append(f"{rel}: contains a red-line term from .redline-terms")
                break

        for label, pattern in CREDENTIALS:
            if pattern.search(text):
                findings.append(f"{rel}: looks like a committed {label}")

        for match in EMAIL.finditer(text):
            address = match.group(0)
            if not any(allowed in address for allowed in EMAIL_ALLOWED):
                findings.append(f"{rel}: email address {address!r}")

        if PHONE.search(text):
            findings.append(f"{rel}: phone-number-shaped string")

    return findings


def main(argv: list[str]) -> int:
    paths = [Path(a).resolve() for a in argv[1:]] if len(argv) > 1 else tracked_files()
    terms = load_terms()

    findings = scan(paths, terms)
    if findings:
        print("Red-line scan failed:", file=sys.stderr)
        for finding in sorted(set(findings)):
            print(f"  {finding}", file=sys.stderr)
        return 1

    note = "" if terms else "  (no .redline-terms found — generic patterns only)"
    print(f"Red-line scan clean: {len(paths)} files.{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
