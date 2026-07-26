#!/usr/bin/env python3
"""lifecycle-gate-policy reference implementation — copying is optional; a
repository may implement the same policy any way it likes and declare it in
lifecycle-gate.toml.

Deterministic destructive-op deny-list scan for SQL migration files. Tuned
for recall, not precision: narrowing vs widening ALTER COLUMN TYPE is not
distinguished (both flag), and statement splitting on ';' does not account
for semicolons inside string literals or comments. A flag routes the change
to an intent check (human review, or orca-evaluate contract comparison) — it
never blocks by itself beyond that, so over-flagging is the accepted
trade-off against under-flagging a real destructive operation.

Usage:
    python3 migration-lint.py <file> [<file> ...]

Exit code 0 = clean (no flags), 1 = one or more flags found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("drop-table", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE)),
    ("drop-column", re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)),
    (
        "alter-column-type",
        re.compile(r"\bALTER\s+COLUMN\b.{0,80}?\b(SET\s+DATA\s+)?TYPE\b", re.IGNORECASE | re.DOTALL),
    ),
    ("truncate", re.compile(r"\bTRUNCATE\b", re.IGNORECASE)),
    (
        "rename",
        re.compile(
            r"\bRENAME\s+(TABLE|COLUMN)\b|\bALTER\s+TABLE\b.{0,80}?\bRENAME\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
]

DELETE_FROM = re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)
WHERE = re.compile(r"\bWHERE\b", re.IGNORECASE)


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def snippet_of(text: str, start: int, end: int) -> str:
    return text[start:end].split("\n")[0].strip()[:120]


def statements(text: str) -> list[tuple[str, int]]:
    """Split into (statement_text, start_offset) pairs on ';'. Best-effort —
    does not account for ';' inside string literals or comments."""
    result = []
    start = 0
    for m in re.finditer(";", text):
        result.append((text[start : m.start()], start))
        start = m.end()
    if start < len(text):
        result.append((text[start:], start))
    return result


def scan(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        text = f.read()

    flags = []
    for rule, pattern in RULES:
        for m in pattern.finditer(text):
            flags.append(
                {
                    "file": path,
                    "line": line_of(text, m.start()),
                    "rule": rule,
                    "snippet": snippet_of(text, m.start(), m.end()),
                }
            )

    for statement, offset in statements(text):
        m = DELETE_FROM.search(statement)
        if m and not WHERE.search(statement):
            flags.append(
                {
                    "file": path,
                    "line": line_of(text, offset + m.start()),
                    "rule": "delete-without-where",
                    "snippet": statement.strip().split("\n")[0][:120],
                }
            )

    return flags


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", help="migration files to scan")
    args = parser.parse_args()

    all_flags: list[dict] = []
    for path in args.files:
        all_flags.extend(scan(path))

    print(json.dumps({"clean": not all_flags, "flags": all_flags}, indent=2))
    return 0 if not all_flags else 1


if __name__ == "__main__":
    sys.exit(main())
