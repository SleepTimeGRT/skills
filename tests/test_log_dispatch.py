"""Functional tests for the shared log_dispatch bash helper (issue #68).

This wraps executable code, not prose, so it gets real behavioral tests: the script is sourced
and invoked via subprocess against an isolated HOME, rather than asserted on via text matching.

Parametrized across bash *and* zsh (contract round 1, issue #68): a bash-only harness structurally
cannot catch shell-dependent defects in a helper that is sourced into whatever shell actually runs
the SKILL.md dispatch block (zsh on this machine, ZSH_VERSION=5.9) -- exactly the class of defect
that sank round 1 (`${!req}` indirect expansion) and a second one found during round-2 review
(`shift 2` on a value-less trailing flag hangs both shells). `timeout` on every subprocess call
exists specifically so a regression of either kind fails the test instead of hanging the suite.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "log_dispatch.sh"
SHELLS = ["bash", "zsh"]

CALL = (
    'log_dispatch --skill orca-workflow --role task-runner --issue 68 --task-id task_abc '
    "--terminal term_x --worktree /tmp/wt --provider claude --model opus --effort high "
    '--spec-text "hello world"'
)


def _run(tmp_path: Path, script: str, shell: str = "bash") -> tuple[subprocess.CompletedProcess[str], Path]:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    full_script = f"source '{SCRIPT}'\n{script}\n"
    result = subprocess.run(
        [shell, "-c", full_script],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    return result, home


def _logs_dir(home: Path) -> Path:
    return home / ".local" / "state" / "orca-workflows" / "logs"


def _assign_lines(home: Path) -> list[dict]:
    lines: list[dict] = []
    for f in sorted(_logs_dir(home).glob("assignments-*.jsonl")):
        lines.extend(json.loads(line) for line in f.read_text().splitlines() if line.strip())
    return lines


def _term_lines(home: Path, handle: str) -> list[dict]:
    f = _logs_dir(home) / f"term-{handle}.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def test_script_exists():
    assert SCRIPT.is_file(), "orca-workflows/scripts/log_dispatch.sh is missing"


@pytest.mark.parametrize("shell", SHELLS)
def test_writes_assign_event_with_all_fields(tmp_path, shell):
    result, home = _run(tmp_path, CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    lines = _assign_lines(home)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["event"] == "assign"
    assert rec["skill"] == "orca-workflow"
    assert rec["role"] == "task-runner"
    assert rec["issue"] == "68"
    assert rec["task_id"] == "task_abc"
    assert rec["provider"] == "claude"
    assert rec["model"] == "opus"
    assert rec["effort"] == "high"
    assert rec["terminal"] == "term_x"
    assert rec["worktree"] == "/tmp/wt"
    assert "relay" not in rec


@pytest.mark.parametrize("shell", SHELLS)
def test_writes_term_meta_and_sent(tmp_path, shell):
    result, home = _run(tmp_path, CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    lines = _term_lines(home, "term_x")
    assert len(lines) == 2
    assert lines[0]["type"] == "meta"
    assert lines[0]["skill"] == "orca-workflow"
    assert lines[0]["role"] == "task-runner"
    assert lines[0]["terminal"] == "term_x"
    assert "created_at" in lines[0]
    assert lines[1]["direction"] == "sent"
    assert lines[1]["content"] == "hello world"


@pytest.mark.parametrize("shell", SHELLS)
def test_idempotent_meta_on_repeated_call_same_handle(tmp_path, shell):
    second_call = CALL.replace("task_abc", "task_def")
    result, home = _run(tmp_path, f"{CALL}\n{second_call}", shell=shell)
    assert result.returncode == 0, result.stderr
    term = _term_lines(home, "term_x")
    metas = [line for line in term if line.get("type") == "meta"]
    sents = [line for line in term if line.get("direction") == "sent"]
    assert len(metas) == 1, "meta must be written once (idempotent guard), not once per round"
    assert len(sents) == 2
    assigns = _assign_lines(home)
    assert [a["task_id"] for a in assigns] == ["task_abc", "task_def"]


@pytest.mark.parametrize("shell", SHELLS)
def test_no_recv_ever_written(tmp_path, shell):
    result, home = _run(tmp_path, CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    term = _term_lines(home, "term_x")
    assert all(line.get("direction") != "recv" for line in term)


@pytest.mark.parametrize("shell", SHELLS)
def test_assign_write_failure_blocks_term_write(tmp_path, shell):
    """AC1's 'first write (assign) fails -> never attempt the second (term)' contract. install -d
    is left to succeed (the logs dir is pre-created) so only the assign file write itself fails --
    forcing that path to fail today's assignments-<date>.jsonl into being a directory."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    logs_dir = _logs_dir(home)
    logs_dir.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (logs_dir / f"assignments-{today}.jsonl").mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    full_script = f"source '{SCRIPT}'\n{CALL}\necho rc=$?\n"
    result = subprocess.run(
        [shell, "-c", full_script],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    assert "rc=0" not in result.stdout
    assert not (logs_dir / "term-term_x.jsonl").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_required_argument_returns_nonzero_and_writes_nothing(tmp_path, shell):
    script = CALL.replace("--effort high ", "")
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode != 0
    assert not _assign_lines(home)
    assert not _term_lines(home, "term_x")


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_task_id_is_not_an_error_and_sets_relay_true(tmp_path, shell):
    script = CALL.replace("--task-id task_abc ", "")
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    lines = _assign_lines(home)
    assert len(lines) == 1
    assert "task_id" not in lines[0]
    assert lines[0]["relay"] is True


@pytest.mark.parametrize("shell", SHELLS)
def test_explicit_empty_task_id_is_an_error(tmp_path, shell):
    """Contract round 2 residual risk #1: an explicitly empty --task-id ("" passed on purpose or by
    a broken call-site substitution) must be rejected, not silently relabeled as a relay dispatch --
    conflating the two would defeat relay:true's whole purpose (distinguishing 'no real task_id, by
    design' from 'forgot to resolve one'), reintroducing a variant of the issue #62 bug."""
    script = CALL.replace("--task-id task_abc ", '--task-id "" ')
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode != 0
    assert not _assign_lines(home)


@pytest.mark.parametrize("shell", SHELLS)
def test_helper_failure_does_not_abort_calling_script(tmp_path, shell):
    """Round-1 rejection's core reproduction: the earlier `${!req}` draft threw 'bad substitution'
    in zsh, and that error unwound the entire sourced script (not just the function), silently
    skipping every later command in the same fenced block -- at issue #68's site 1, that would have
    been the evaluator dispatch following the task-runner log_dispatch call. This pins the failure
    mode itself: call log_dispatch with invalid arguments, then check that a distinct command right
    after it in the same script still runs."""
    script = "log_dispatch --skill x --role y\necho MARKER_AFTER_FAILED_CALL"
    result, _home = _run(tmp_path, script, shell=shell)
    assert "MARKER_AFTER_FAILED_CALL" in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_flag_with_missing_value_returns_nonzero_not_hang(tmp_path, shell):
    """Second shell-portability defect found during round-2 re-validation: a flag with no following
    value (e.g. a truncated call site) previously hit `shift 2` on the last remaining argument,
    which fails without shifting -- $1 never changes, so the arg-parsing while loop hangs forever
    (reproduced directly in both bash and zsh). The `[ $# -lt 2 ]` guard added in response returns
    64 immediately instead. `_run`'s `timeout=10` is what turns a regression here into a test
    *failure* rather than a hung test *run*."""
    script = "log_dispatch --skill\necho rc=$?\necho AFTER"
    result, _home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert "AFTER" in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_written_files_are_chmod_600(tmp_path, shell):
    result, home = _run(tmp_path, CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assign_file = _logs_dir(home) / f"assignments-{today}.jsonl"
    term_file = _logs_dir(home) / "term-term_x.jsonl"
    assert stat.S_IMODE(assign_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(term_file.stat().st_mode) == 0o600
