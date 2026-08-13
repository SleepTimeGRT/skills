"""Regression coverage for the #118 appendix's 4th-priority candidate: self-recovery.md's
worker-start sub-branch (the dead-dispatch recovery path) combined `--worktree active` with
`--terminal <handle>`, which `orca-task-runner` SKILL.md §0 already documents as an always-failing
combination (`selector_not_found`, confirmed live 2026-08-11) -- `--terminal` calls should omit
`--worktree` entirely since the handle is already pinned to its worktree. #75 (CLOSED) fixed only
`orca-workflow` §2a's relay site; this site in self-recovery.md's dead-case sub-branch was missed.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_RECOVERY = REPO_ROOT / "orca-workflows" / "self-recovery.md"


def _worker_start_retry_block() -> str:
    text = SELF_RECOVERY.read_text()
    start = text.index("--- worker-start sub-branch ---")
    end = text.index("new_dispatch_id=", start)
    return text[start:end]


def test_worker_start_retry_omits_worktree_active():
    block = _worker_start_retry_block()
    command_lines = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )
    assert "--worktree active" not in command_lines


def test_worker_start_retry_still_passes_terminal_handle():
    block = _worker_start_retry_block()
    assert '--terminal "$NEW_OR_SAME_HANDLE"' in block


def test_worker_start_retry_documents_why_worktree_flag_was_dropped():
    block = _worker_start_retry_block()
    assert "selector_not_found" in block
    assert "#118" in block
