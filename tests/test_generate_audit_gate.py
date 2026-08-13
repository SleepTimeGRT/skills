"""Functional tests for orca-workflow-task §3's Generate audit gate (issue #128).

The gate is a documented bash procedure, so per this repo's execution-suite policy it is extracted
from SKILL.md verbatim (placeholders substituted) and run as a subprocess against fixture logs in an
isolated HOME, parametrized across bash and zsh. Issue #114's defect shape: 4 evaluator assigns,
zero role=task-runner assigns -- indistinguishable from the coordinator editing code itself. The
gate must flag exactly that (no assign for this attempt) and stay quiet when the §2 dispatch logged
properly.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
SHELLS = ["bash", "zsh"]


def _gate_block() -> str:
    text = SKILL.read_text()
    section = text[text.index("Generate 감사 게이트"):]
    m = re.search(r"```bash\n(.*?)```", section, re.DOTALL)
    assert m, "Generate 감사 게이트 fenced bash block missing from SKILL.md §3"
    return m.group(1)


def _substituted(issue: str = "42", repo: str = "own/repo", attempt: str = "2") -> str:
    block = _gate_block()
    block = block.replace("<issue-num>", issue)
    block = block.replace("<대상 repo>", repo)
    block = block.replace("<attempt 번호>", attempt)
    assert "<" not in block.replace("2>/dev/null", ""), f"unsubstituted placeholder left: {block}"
    return block


def _assign(issue: str, repo: str | None, attempt: int | None, role: str = "task-runner") -> dict:
    rec = {
        "ts": "2026-08-12T00:00:00Z", "event": "assign", "skill": "orca-workflow-task",
        "role": role, "issue": issue, "task_id": "task_x", "provider": "claude-code",
        "model": "opus", "effort": "high", "terminal": "term_x", "worktree": "/tmp/wt",
    }
    if repo is not None:
        rec["repo"] = repo
    if attempt is not None:
        rec["attempt"] = attempt
    return rec


def _run(tmp_path: Path, records: list[dict], shell: str, script: str | None = None):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    home = tmp_path / "home"
    logs = home / ".local" / "state" / "orca-workflows" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if records:
        target = logs / "assignments-2026-08-12.jsonl"
        target.write_text("".join(json.dumps(r) + "\n" for r in records))
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [shell, "-c", script if script is not None else _substituted()],
        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_quiet_when_attempt_assign_exists(tmp_path, shell):
    result = _run(tmp_path, [_assign("42", "own/repo", 2)], shell)
    assert "GENERATE-AUDIT-FAIL" not in result.stderr, result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_flags_missing_assign_entirely(tmp_path, shell):
    """Issue #114's exact shape: evaluator assigns exist, task-runner assigns don't."""
    result = _run(tmp_path, [_assign("42", "own/repo", None, role="evaluator")], shell)
    assert "GENERATE-AUDIT-FAIL" in result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_flags_empty_logs_dir(tmp_path, shell):
    result = _run(tmp_path, [], shell)
    assert "GENERATE-AUDIT-FAIL" in result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_flags_wrong_attempt_number(tmp_path, shell):
    result = _run(tmp_path, [_assign("42", "own/repo", 1)], shell)
    assert "GENERATE-AUDIT-FAIL" in result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_ignores_other_repo_same_issue_number(tmp_path, shell):
    """The (repo, issue) composite key from issue #158 applies here too -- a same-numbered issue
    from a different repository must not satisfy this run's audit."""
    result = _run(tmp_path, [_assign("42", "other/repo", 2)], shell)
    assert "GENERATE-AUDIT-FAIL" in result.stderr


@pytest.mark.parametrize("shell", SHELLS)
def test_gate_ignores_legacy_record_without_repo(tmp_path, shell):
    result = _run(tmp_path, [_assign("42", None, 2)], shell)
    assert "GENERATE-AUDIT-FAIL" in result.stderr
