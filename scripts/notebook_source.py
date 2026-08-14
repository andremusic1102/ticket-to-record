#!/usr/bin/env python3
"""Dump this repository's source as one file, for reading alongside the notes.

The project's study material lives in four documents: what was decided, what was
found, what the numbers are, and this — the code itself. The first three are
written once and barely change; the code changes constantly. Keeping them apart
means a refresh replaces this file and leaves the reasoning alone, which is the
whole reason for the split.

Generated rather than maintained, because a hand-copied source dump is stale the
day after it is written and there is no way to tell by looking.

**Only this repository.** The private sibling holds an employer's data and never
goes near a third-party service; nothing here reaches across to it, and the
absence of a path argument is the enforcement.

    python scripts/notebook_source.py > path/to/04-source.md
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Order matters: a reader following this top to bottom should meet the schema
# before the things that use it, and the tests last.
ORDER = (
    "README.md",
    "src/ticket_to_record/models.py",
    "src/ticket_to_record/config.py",
    "src/ticket_to_record/prompts.py",
    "src/ticket_to_record/llm/base.py",
    "src/ticket_to_record/llm/fake.py",
    "src/ticket_to_record/llm/gemini.py",
    "src/ticket_to_record/llm/factory.py",
    "src/ticket_to_record/synth/generate.py",
    "src/ticket_to_record/pipeline/extract.py",
    "src/ticket_to_record/eval/score.py",
    "src/ticket_to_record/cli.py",
    "scripts/redline_scan.py",
    "scripts/redline_history.py",
    "docs/demo.md",
)

SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".ico", ".svg"}


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def main() -> None:
    files = tracked()
    known = set(ORDER)
    # Anything tracked but not in ORDER still gets included, after the ordered
    # part. A file that exists and is silently left out of the study material is
    # worse than one in an odd position.
    rest = sorted(
        f
        for f in files
        if f not in known and Path(f).suffix not in SKIP_SUFFIXES and not f.startswith(".")
    )

    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    print("# Source, in full\n")
    print(f"> Generated from commit `{head}`. This is the only one of the four")
    print("> study documents that goes stale; regenerate it with")
    print("> `python scripts/notebook_source.py`.\n")
    print("> This repository only. The private sibling holds an employer's data")
    print("> and does not go near a third-party service.\n")

    for name in [f for f in ORDER if f in files] + rest:
        path = REPO_ROOT / name
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lang = {
            "py": "python",
            "md": "markdown",
            "toml": "toml",
            "jsonl": "json",
            "yaml": "yaml",
            "yml": "yaml",
        }.get(name.rsplit(".", 1)[-1], "")
        print(f"\n---\n\n## `{name}`\n")
        print(f"```{lang}")
        print(body.rstrip())
        print("```")

    print(f"\n{len([f for f in ORDER if f in files]) + len(rest)} files.", file=sys.stderr)


if __name__ == "__main__":
    main()
