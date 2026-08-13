"""Functional tests for orca-workflow-task §0's crash-resume section-2 -> section-3 override
(issue #161).

contract_resume_state (issue #156) can only see CONTRACT_DIR artifacts: when maxa==0 (no
eval-report exists) it always returns resume="section-2", unable to distinguish "generation
finished, evaluate was never called" from "generation never started" -- that ambiguity risks
re-dispatching orca-task-runner over already-completed, already-committed work.

The fix lives entirely in §0's prose (not contract_resume.sh, which has no repo/worktree access):
after capturing resume/attempt/retry, a guard fires ONLY on the maxa==0 shape
(resume="section-2" && attempt=="1" && retry=="0" -- the FAIL-retry section-2 shape always has
attempt>=2/retry>=1, so a real retry is never clobbered) and checks two signals, both required,
fail-closed on any lookup failure:
  1. an assign log record for (repo, issue) with skill=orca-workflow-task, role=task-runner
     (the same signal §3's own Generate-audit-gate, issue #128, independently re-verifies with the
     exact attempt number before ever calling evaluate -- this override is not a bypass of that
     gate, it just routes into it instead of around it)
  2. the worktree HEAD has commits ahead of the merge-base with origin/<default-branch>

Per this repo's execution-suite convention (precedent: test_generate_audit_gate.py), the bash is
extracted from SKILL.md verbatim and run as a subprocess against a real git repo + fixture logs +
a stubbed `gh`, parametrized across bash and zsh.
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
CONTRACT_RESUME = REPO_ROOT / "orca-workflows" / "scripts" / "contract_resume.sh"
SHELLS = ["bash", "zsh"]


def _override_block() -> str:
    text = SKILL.read_text()
    idx = text.find("issue #161")
    assert idx != -1, "issue #161 crash-resume override marker missing from SKILL.md §0"
    fence_start = text.rfind("```bash\n", 0, idx)
    assert fence_start != -1, "no enclosing ```bash fence found before the issue #161 marker"
    fence_end = text.index("```", fence_start + len("```bash\n"))
    return text[fence_start + len("```bash\n") : fence_end]


def _substituted(issue: str = "42", repo: str = "own/repo") -> str:
    block = _override_block()
    block = block.replace("<CONTRACT_DIR>", "$CONTRACT_DIR")
    block = block.replace("<issue-num>", issue)
    block = block.replace("<대상 repo>", repo)
    assert "<" not in block.replace("2>/dev/null", ""), f"unsubstituted placeholder left: {block}"
    return block


def _assign(issue: str, repo: str, role: str = "task-runner") -> dict:
    return {
        "ts": "2026-08-14T00:00:00Z", "event": "assign", "skill": "orca-workflow-task",
        "role": role, "issue": issue, "repo": repo, "task_id": "task_x",
        "provider": "claude-code", "model": "opus", "effort": "high", "terminal": "term_x",
        "worktree": "/tmp/wt",
    }


def _init_repo(repo_dir: Path, extra_commits: int) -> None:
    """A bare 'origin' + a clone with a task branch, so `git merge-base HEAD origin/<default>` and
    `git rev-list --count` are exercised against real git state, not stubs."""
    bare = repo_dir / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    work = repo_dir / "work"
    subprocess.run(["git", "clone", str(bare), str(work)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    (work / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "push", "origin", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "checkout", "-b", "task-42"], check=True, capture_output=True)
    for i in range(extra_commits):
        (work / f"file{i}.txt").write_text(f"content {i}\n")
        subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(work), "commit", "-m", f"task commit {i}"],
            check=True, capture_output=True,
        )
    return work


_GH_STUB = """
gh() {
  if [ "$1 $2" = "repo view" ]; then
    echo "main"
    return 0
  fi
  echo "unsupported gh stub call: $*" >&2
  return 1
}
"""


def _run(
    tmp_path: Path,
    shell: str,
    *,
    assigns: list[dict] | None,
    extra_commits: int,
    eval_reports: dict[int, str] | None = None,
    root_name: str = "root",
) -> dict:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    tmp_path = tmp_path / root_name
    tmp_path.mkdir()
    home = tmp_path / "home"
    logs = home / ".local" / "state" / "orca-workflows" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if assigns:
        (logs / "assignments-2026-08-14.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in assigns)
        )

    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    (contract_dir / "proposal-r1.json").write_text(
        json.dumps({"schema_version": 1, "issue": "42", "round": 1})
    )
    (contract_dir / "verdict-r1.json").write_text(
        json.dumps(
            {"schema_version": 1, "issue": "42", "round": 1, "status": "approved", "reasons": []}
        )
    )
    for k, verdict in (eval_reports or {}).items():
        (contract_dir / f"eval-report-a{k}.json").write_text(
            json.dumps({"schema_version": 1, "issue": "42", "attempt": k, "verdict": verdict})
        )

    work = _init_repo(tmp_path, extra_commits)

    out_file = tmp_path / "state_out.json"
    script = (
        "set -u\n"
        f"source '{CONTRACT_RESUME}'\n"
        f"CONTRACT_DIR='{contract_dir}'\n"
        + _GH_STUB
        + _substituted()
        + "\n"
        + f"jq -cn --arg resume \"$resume\" --arg attempt \"$attempt\" --arg retry \"$retry\" "
          f"'{{resume:$resume, attempt:$attempt, retry:$retry}}' > '{out_file}'\n"
    )
    env = {**os.environ, "HOME": str(home)}
    result = subprocess.run(
        [shell, "-c", script], cwd=str(work), env=env, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    return json.loads(out_file.read_text())


@pytest.mark.parametrize("shell", SHELLS)
def test_override_fires_when_assign_and_commits_both_present(tmp_path, shell):
    state = _run(
        tmp_path, shell, assigns=[_assign("42", "own/repo")], extra_commits=2
    )
    assert state["resume"] == "section-3"
    assert state["attempt"] == "1"
    assert state["retry"] == "0"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_does_not_fire_without_assign(tmp_path, shell):
    """Commits alone (e.g. a human's own edits) are not sufficient -- issue #128's boundary means
    only a verified task-runner dispatch may license skipping Generate."""
    state = _run(tmp_path, shell, assigns=None, extra_commits=2)
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_does_not_fire_without_commits(tmp_path, shell):
    """An assign record alone isn't enough either -- task-runner may have been dispatched but died
    before committing anything."""
    state = _run(tmp_path, shell, assigns=[_assign("42", "own/repo")], extra_commits=0)
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_ignores_other_repo_same_issue_number(tmp_path, shell):
    state = _run(tmp_path, shell, assigns=[_assign("42", "other/repo")], extra_commits=2)
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_ignores_non_task_runner_assign(tmp_path, shell):
    state = _run(
        tmp_path, shell, assigns=[_assign("42", "own/repo", role="evaluator")], extra_commits=2
    )
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_fires_with_spaces_in_path(tmp_path, shell):
    """AGENTS.md's validation section names spaces-in-paths explicitly -- the override block
    interpolates CONTRACT_DIR, $HOME, and the git merge-base ref, all of which must survive a
    space in the containing directory name."""
    state = _run(
        tmp_path,
        shell,
        assigns=[_assign("42", "own/repo")],
        extra_commits=2,
        root_name="root with spaces",
    )
    assert state["resume"] == "section-3"


@pytest.mark.parametrize("shell", SHELLS)
def test_fail_retry_shape_is_never_clobbered(tmp_path, shell):
    """The FAIL-retry section-2 shape (attempt>=2, retry>=1) must never match the issue #161
    guard, even when both override signals (assign + commits) are present -- otherwise a real FAIL
    retry would get routed straight back to evaluate on the already-FAILed attempt-1 diff instead
    of dispatching the fix, silently dropping the FAIL feedback."""
    state = _run(
        tmp_path,
        shell,
        assigns=[_assign("42", "own/repo")],
        extra_commits=2,
        eval_reports={1: "FAIL"},
    )
    assert state["resume"] == "section-2"
    assert state["attempt"] == "2"
    assert state["retry"] == "1"
