"""Functional tests for orca-task-runner's SDD-loop entry branch (plan_path presence).

The branch is a documented bash procedure, so per this repo's execution-suite policy it is
extracted from SKILL.md verbatim (placeholder substituted) and run as a subprocess, parametrized
across bash and zsh. A non-empty plan_path must select the SDD loop; empty/absent must select the
existing native DAG/wave path (§2-§5, unchanged).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"
SHELLS = ["bash", "zsh"]


def _entry_branch_block() -> str:
    text = SKILL.read_text()
    section = text[text.index("## SDD 태스크 루프"):]
    m = re.search(r"```bash\n(.*?)```", section, re.DOTALL)
    assert m, "SDD 태스크 루프 진입 분기 fenced bash block missing from SKILL.md"
    return m.group(1)


def _substituted(plan_path: str) -> str:
    block = _entry_branch_block()
    block = block.replace("<spec으로 받은 plan_path — 없으면 빈 문자열>", plan_path)
    assert "<" not in block, f"unsubstituted placeholder left: {block}"
    return block


def _run(script: str, shell: str):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    return subprocess.run(
        [shell, "-c", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_nonempty_plan_path_selects_sdd_loop(shell):
    result = _run(_substituted("/tmp/plans/2026-08-22-foo.md"), shell)
    assert result.stdout.strip() == "SDD_LOOP"


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_plan_path_selects_native_dag(shell):
    result = _run(_substituted(""), shell)
    assert result.stdout.strip() == "NATIVE_DAG"
