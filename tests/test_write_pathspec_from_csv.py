"""Functional tests for the write_pathspec_from_csv bash helper (issue #70).

Parametrized across bash *and* zsh, same rationale as test_log_dispatch.py (issue #68): a
bash-only harness cannot catch shell-dependent defects in a helper sourced into whatever shell
actually runs the orca-task-runner SKILL.md dispatch block (zsh on this machine, ZSH_VERSION=5.9).

This script exists specifically because an earlier draft split orca-task-runner's §5 commit-helper
filesModified CSV into a bash array via `IFS=',' read -r -a files_modified <<< "$csv"`, then
guarded the commit step on `${#files_modified[@]} -gt 0`. `read -a` is bash-only: in zsh it fails
with "read:1: bad option: -a" but still exits 0, so the array silently stayed empty and the length
guard treated every codex subtask's changes as "nothing to commit" -- a fail-open (contract round 3
found this: bash produced 2 array elements for a 2-path CSV, zsh produced 0, with no visible
error). `test_regression_nonempty_csv_produces_nonzero_output_in_both_shells` below is the direct
regression guard for that defect class: it demands *identical, non-empty* output from both shells
for the same input, so a shell-dependent silent-empty regression fails the parametrized case for
whichever shell reintroduces it.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "write_pathspec_from_csv.sh"
SHELLS = ["bash", "zsh"]


def _run(tmp_path: Path, script: str, shell: str = "bash") -> subprocess.CompletedProcess[str]:
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    full_script = f"source '{SCRIPT}'\n{script}\n"
    return subprocess.run(
        [shell, "-c", full_script],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )


def test_script_exists():
    assert SCRIPT.is_file(), "orca-workflows/scripts/write_pathspec_from_csv.sh is missing"


@pytest.mark.parametrize("shell", SHELLS)
def test_nonempty_csv_writes_one_line_per_path(tmp_path, shell):
    out = tmp_path / "pathspec.txt"
    result = _run(tmp_path, f'write_pathspec_from_csv "a.txt,b/c d.txt" "{out}"', shell=shell)
    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == ["a.txt", "b/c d.txt"]


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_csv_returns_skip_code_and_writes_nothing(tmp_path, shell):
    out = tmp_path / "pathspec.txt"
    result = _run(tmp_path, f'write_pathspec_from_csv "" "{out}"', shell=shell)
    assert result.returncode == 3, result.stderr
    assert not out.exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_regression_nonempty_csv_produces_nonzero_output_in_both_shells(tmp_path, shell):
    """The exact defect class this script exists to prevent: a shell-dependent split silently
    producing zero paths for a non-empty CSV. bash and zsh must agree, not just each be internally
    consistent -- the old `IFS=',' read -r -a` draft passed on bash alone."""
    out = tmp_path / "pathspec.txt"
    result = _run(tmp_path, f'write_pathspec_from_csv "one.md,two.md" "{out}"', shell=shell)
    assert result.returncode == 0, result.stderr
    lines = out.read_text().splitlines()
    assert len(lines) == 2, f"{shell}: expected 2 paths, got {lines!r}"
    assert lines == ["one.md", "two.md"]


@pytest.mark.parametrize("shell", SHELLS)
def test_caller_style_guard_branches_correctly_on_return_code(tmp_path, shell):
    """Mirrors how orca-task-runner SKILL.md §5 actually calls this: `if write_pathspec_from_csv
    ...; then <commit> ; fi`. Proves the if/else branch itself -- not just the function's raw
    return code -- takes the correct path for both a real CSV and an empty one."""
    out = tmp_path / "pathspec.txt"
    script = f"""
    if write_pathspec_from_csv "a.txt,b.txt" "{out}"; then
      echo WOULD_COMMIT
    else
      echo WOULD_SKIP
    fi
    """
    result = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "WOULD_COMMIT" in result.stdout
    assert "WOULD_SKIP" not in result.stdout

    out2 = tmp_path / "pathspec2.txt"
    script2 = f"""
    if write_pathspec_from_csv "" "{out2}"; then
      echo WOULD_COMMIT
    else
      echo WOULD_SKIP
    fi
    """
    result2 = _run(tmp_path, script2, shell=shell)
    assert result2.returncode == 0, result2.stderr
    assert "WOULD_SKIP" in result2.stdout
    assert "WOULD_COMMIT" not in result2.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_single_path_csv_no_trailing_comma_artifact(tmp_path, shell):
    out = tmp_path / "pathspec.txt"
    result = _run(tmp_path, f'write_pathspec_from_csv "solo.txt" "{out}"', shell=shell)
    assert result.returncode == 0, result.stderr
    assert out.read_text().splitlines() == ["solo.txt"]
