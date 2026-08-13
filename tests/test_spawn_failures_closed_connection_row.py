"""Doc-schema regression coverage for issue #103 -- the "closed the connection" literal
(full observed message: "The Orca runtime closed the connection before responding. Restart Orca
and try again.") matched none of the six keywords `_ORCA_RETRY_SIGNATURE_RE` had before this fix,
so it went both unretried by orca_call_with_retry.sh and unregistered in spawn-failures.md's
grep-first table (MediCount#513, 2026-08-09, orca-workflow-epic waiting via `check --wait` during
an app auto-update). This only covers the two independent sub-fixes (regex keyword + registry
row) -- wrapping self-recovery.md's own raw `check --wait` call is deliberately left out of this
change; the issue itself flags a double-wait design question there that needs separate review.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPAWN_FAILURES = REPO_ROOT / "orca-workflows" / "spawn-failures.md"
RETRY_SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "orca_call_with_retry.sh"


def _known_signatures_table() -> str:
    text = SPAWN_FAILURES.read_text()
    start = text.index("## Known signatures")
    end = text.index("\n\n## Adding a new row", start)
    return text[start:end]


def _table_rows(table: str) -> list[str]:
    return [
        line for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| `failure_signature`")
        and set(line.replace("|", "").replace("-", "").strip()) != set()
    ]


def test_closed_the_connection_row_present_and_distinguished_from_83():
    table = _known_signatures_table()
    row = next(r for r in _table_rows(table) if "closed the connection" in r)
    assert row.rstrip().endswith("#103 |")
    assert "#83" in row
    assert "#42" in row


def test_retry_signature_regex_includes_closed_the_connection():
    text = RETRY_SCRIPT.read_text()
    assert "closed the connection" in text
    # The literal must actually be part of the live regex variable, not just a comment mention.
    re_line = next(line for line in text.splitlines() if line.startswith("_ORCA_RETRY_SIGNATURE_RE="))
    assert "closed the connection" in re_line
