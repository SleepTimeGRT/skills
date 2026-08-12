"""Functional tests for orca-workflow-task §4's merge loop (issue #135).

The loop is a documented bash procedure, so it is extracted from SKILL.md verbatim (placeholders
substituted, sleep shortened -- duration is not under test) and run against a stub `gh` on PATH in
an isolated TMPDIR, parametrized across bash and zsh.

Issue #135's defect shape: `gh pr merge --squash --delete-branch` succeeded on the remote merge but
exited non-zero in the local branch-cleanup step (`fatal: 'main' is already used by worktree` --
structural in this workflow's default layout), and the loop read the exit code as merge failure,
polling the already-merged PR (mergeStateStatus=UNKNOWN matches no branch) until the 1800s budget.
The fix moves the judgment from command exit code to actual PR state, so both that shape and the
"already merged before the loop even starts" resume case must exit merged=true without polling.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
SHELLS = ["bash", "zsh"]

STUB_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_CALL_LOG"
case "$*" in
  "pr view 7 --json state -q .state")
    cat "$STATE_FILE" ;;
  "pr merge 7 --squash --delete-branch")
    case "$GH_MERGE_BEHAVIOR" in
      merge_ok_cleanup_fails)
        # issue #135's exact shape: the remote merge lands, then local cleanup dies non-zero.
        printf 'MERGED' > "$STATE_FILE"
        echo "fatal: 'main' is already used by worktree at /elsewhere" >&2
        exit 1 ;;
      already_merged)
        echo "! Pull request #7 was already merged" >&2
        exit 1 ;;
      refuse)
        exit 1 ;;
      *) echo "stub gh: GH_MERGE_BEHAVIOR unset" >&2; exit 99 ;;
    esac ;;
  "pr view 7 --json mergeStateStatus -q .mergeStateStatus")
    printf '%s\\n' "$GH_MERGE_STATE_STATUS" ;;
  "pr view 7 --json statusCheckRollup -q "*)
    printf '%s\\n' "$GH_CHECKS" ;;
  "pr update-branch 7")
    exit 0 ;;
  *)
    echo "stub gh: unmatched call: $*" >&2
    exit 99 ;;
esac
"""


def _loop_block() -> str:
    text = SKILL.read_text()
    start = text.index("merge_started_file=")
    end = text.index('rm -f "$merge_started_file"', start)
    end = text.index("\n", end)
    return text[start:end]


def _script() -> str:
    block = _loop_block()
    block = block.replace("<issue-num>", "7")
    # Duration is not under test; keep polling paths fast so a regression to exit-code judgment
    # shows up as a subprocess timeout, not a 30s-per-iteration crawl.
    block = block.replace("sleep 30", "sleep 0.2")
    assert "<" not in re.sub(r"[0-9]?>|<<", "", block), f"unsubstituted placeholder left:\n{block}"
    return f'pr_num=7\n{block}\nprintf \'RESULT merged=%s outcome=%s\\n\' "$merged" "$merge_outcome"\n'


def _run(tmp_path: Path, shell: str, *, state: str, behavior: str,
         merge_state_status: str = "UNKNOWN", checks: str = "success"):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    state_file = tmp_path / "pr-state"
    state_file.write_text(state)
    call_log = tmp_path / "gh-calls.log"
    call_log.write_text("")
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TMPDIR"] = str(tmp_path)
    env["STATE_FILE"] = str(state_file)
    env["GH_CALL_LOG"] = str(call_log)
    env["GH_MERGE_BEHAVIOR"] = behavior
    env["GH_MERGE_STATE_STATUS"] = merge_state_status
    env["GH_CHECKS"] = checks
    result = subprocess.run(
        [shell, "-c", _script()],
        env=env, cwd=tmp_path, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
    )
    return result, call_log.read_text()


@pytest.mark.parametrize("shell", SHELLS)
def test_merged_pr_at_entry_exits_immediately_without_merge_attempt(tmp_path, shell):
    """Resume case (#72 re-run safety): the PR was already merged before this block ran. The loop
    must notice from state alone -- retrying `gh pr merge` against a merged PR only produces the
    'was already merged' non-zero exit that #135 showed matches no routing branch."""
    result, calls = _run(tmp_path, shell, state="MERGED", behavior="already_merged")
    assert "RESULT merged=true outcome=" in result.stdout, result.stdout + result.stderr
    assert "pr merge 7" not in calls


@pytest.mark.parametrize("shell", SHELLS)
def test_remote_merge_with_failed_local_cleanup_is_still_a_merge(tmp_path, shell):
    """Issue #135's exact shape: exit code non-zero, PR actually merged. Must exit merged=true on
    the same iteration instead of polling until the 1800s budget."""
    result, calls = _run(tmp_path, shell, state="OPEN", behavior="merge_ok_cleanup_fails")
    assert "RESULT merged=true outcome=" in result.stdout, result.stdout + result.stderr
    assert calls.count("pr merge 7 --squash --delete-branch") == 1


@pytest.mark.parametrize("shell", SHELLS)
def test_failed_required_check_routes_ci_gate_fail(tmp_path, shell):
    result, _ = _run(tmp_path, shell, state="OPEN", behavior="refuse",
                     merge_state_status="BLOCKED", checks="failure")
    assert "RESULT merged=false outcome=CI_GATE_FAIL" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_dirty_state_routes_merge_conflict(tmp_path, shell):
    result, _ = _run(tmp_path, shell, state="OPEN", behavior="refuse",
                     merge_state_status="DIRTY")
    assert "RESULT merged=false outcome=MERGE_CONFLICT" in result.stdout, result.stdout + result.stderr
