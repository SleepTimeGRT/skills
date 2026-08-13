"""Doc-schema regression coverage for issues #110/#88/#83 -- three spawn-failure signatures that
were observed and recovered from live, but had no row in spawn-failures.md's Known signatures
table, so a future occurrence would have to re-diagnose from scratch instead of grep-first landing
on an already-known cause/fix.

- #110: `dispatch_capability_invalid` (worker_done rejected, "The Dispatch capability is missing").
  Root cause is an unconfirmed hypothesis, not a settled fix -- the row must say so rather than
  presenting a guess as confirmed, and must carry a next-occurrence instruction (capture spec_text)
  so a future observer can actually confirm it.
- #88: `consumer_fenced` (orchestration calls fail even though the worker terminal is alive). The
  fix direction pins two field is_open observed recovery mechanism verified live: rebind via
  `run-use`, then a task-list-polling fallback if that doesn't clear it. Distinct from #83 below --
  the issue body explicitly says these are not duplicates.
- #83: the orchestration Run itself getting wiped by an app auto-update (not just a transient
  reconnect blip like #42). The critical negative instruction from the issue body must survive:
  do NOT widen `_ORCA_RETRY_SIGNATURE_RE` to swallow this failure text, since retrying against a
  wiped run can never succeed -- retrying wastes time rather than recovering.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPAWN_FAILURES = REPO_ROOT / "orca-workflows" / "spawn-failures.md"


def _known_signatures_table() -> str:
    text = SPAWN_FAILURES.read_text()
    start = text.index("## Known signatures")
    # The #42 pointer row's own cell text mentions "`## Adding a new row` below" as an inline
    # cross-reference -- a naive text.index("## Adding a new row", start) lands on that mention
    # instead of the real heading, truncating the table before any row added after the #42 row.
    # The real heading is preceded by a blank line; the inline mention is preceded by a backtick.
    end = text.index("\n\n## Adding a new row", start)
    return text[start:end]


def _table_rows(table: str) -> list[str]:
    # Row lines start with "| " and are not the header/separator lines.
    rows = [
        line for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| `failure_signature`") and set(line.replace("|", "").replace("-", "").strip()) != set()
    ]
    return rows


def test_dispatch_capability_invalid_row_present_and_marks_root_cause_unconfirmed():
    table = _known_signatures_table()
    assert "dispatch_capability_invalid" in table
    assert "The Dispatch capability is missing" in table
    row = next(r for r in _table_rows(table) if "dispatch_capability_invalid" in r)
    assert row.rstrip().endswith("#110 |")
    assert "Unconfirmed hypothesis" in row or "unconfirmed" in row.lower()
    assert "spec_text" in row  # next-occurrence capture instruction


def test_consumer_fenced_row_present_with_two_step_recovery_and_distinguished_from_83():
    table = _known_signatures_table()
    assert "consumer_fenced" in table
    row = next(r for r in _table_rows(table) if "consumer_fenced" in r)
    assert row.rstrip().endswith("#88 |")
    assert "run-use" in row
    assert "task-list" in row
    assert "#83" in row  # cross-reference distinguishing the two adjacent-looking symptoms


def test_run_wiped_row_present_and_forbids_widening_the_retry_regex():
    table = _known_signatures_table()
    row = next(r for r in _table_rows(table) if "dispatch:null" in r)
    assert row.rstrip().endswith("#83 |")
    assert "run_not_found" in row
    assert "_ORCA_RETRY_SIGNATURE_RE" in row
    assert "Do not retry" in row or "do not retry" in row.lower()
    assert "orphan" in row.lower()  # points at the existing orphaned-result recovery contract


def test_three_new_rows_are_well_formed_table_rows():
    table = _known_signatures_table()
    for needle, issue in (
        ("dispatch_capability_invalid", "#110"),
        ("consumer_fenced", "#88"),
        ("dispatch:null", "#83"),
    ):
        row = next(r for r in _table_rows(table) if needle in r)
        assert row.startswith("| ")
        assert row.count("|") == 5, f"row for {needle!r} does not have exactly 4 pipe-delimited columns: {row!r}"
        assert re.search(rf"\|\s*{re.escape(issue)}\s*\|$", row), f"row for {needle!r} must end with {issue}"
