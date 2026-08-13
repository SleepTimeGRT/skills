"""Doc-schema + behavioral regression coverage for issue #136's worktree isolation guard.

orca-task-runner's own session sometimes implements a task directly (no subtask fan-out --
e.g. a single trivial subtask where wave/DAG machinery is skipped). Subtask-impl workers spawned
via §2/§3/§5 are always isolated (`terminal create --worktree active`), but this direct-commit
path had no isolation check at all -- if the dispatching call placed this session's terminal at
the project's main checkout, nothing stopped it from committing there (studio-hevv/selah-android
issue #22: task-runner ran `git checkout -b` + committed directly on the main checkout, moving
its HEAD to a feature branch -- the third recurrence of this class per docs/HANDOFF.md history).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"
GUARD_START = "- **격리 가드(issue #136)**"


def _guard_window(text: str) -> str:
    start = text.index(GUARD_START)
    end = text.index("- claude 워커는 `worker-start --agent`로 스폰한다", start)
    return text[start:end]


def test_isolation_guard_present_before_the_claude_worker_bullet():
    text = SKILL.read_text()
    assert GUARD_START in text
    window = _guard_window(text)
    assert 'if [ -d ".git" ]; then' in window
    assert "git worktree add" in window
    assert "-b" in window
    assert "origin/main" in window
    assert "cd " in window


def _extract_guard_snippet(text: str) -> str:
    window = _guard_window(text)
    start = window.index('if [ -d ".git" ]; then')
    end = window.index("fi\n", start) + len("fi")
    return window[start:end]


def test_guard_snippet_is_syntactically_valid_shell():
    text = SKILL.read_text()
    snippet = _extract_guard_snippet(text)
    # placeholders (<...>) make this non-executable as-is; just check shell syntax with -n.
    result = subprocess.run(["bash", "-n", "-c", snippet], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_guard_triggers_isolation_only_on_a_real_git_directory(tmp_path):
    # Behavioral: run the actual condition against a real main-checkout-shaped dir (.git is a
    # directory) and a real linked-worktree-shaped dir (.git is a gitdir-pointer file), and
    # confirm the branch fires only for the former.
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main_repo, check=True)
    subprocess.run(
        ["git", "-C", str(main_repo), "commit", "--allow-empty", "-q", "-m", "seed"],
        check=True,
    )

    worktree_dir = tmp_path / "isolated-worktree"
    subprocess.run(
        ["git", "-C", str(main_repo), "worktree", "add", str(worktree_dir), "-b", "feature-x"],
        check=True,
        capture_output=True,
    )

    condition = 'if [ -d ".git" ]; then echo MAIN_CHECKOUT; else echo ISOLATED_WORKTREE; fi'

    main_result = subprocess.run(
        ["bash", "-c", condition], cwd=main_repo, capture_output=True, text=True
    )
    assert main_result.stdout.strip() == "MAIN_CHECKOUT"

    worktree_result = subprocess.run(
        ["bash", "-c", condition], cwd=worktree_dir, capture_output=True, text=True
    )
    assert worktree_result.stdout.strip() == "ISOLATED_WORKTREE"


def test_guard_references_the_actual_incident_and_scope():
    text = SKILL.read_text()
    window = _guard_window(text)
    # Scoped to the documented gap (self-implement without fan-out), not a restatement of the
    # already-covered subtask-impl fan-out path.
    assert "fan-out 없이 직접 커밋" in window
    assert "issue #22" in window
    assert "git commit" in window
