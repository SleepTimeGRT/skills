"""Functional tests for the shared orca_call_with_retry bash wrapper (issue #42).

This wraps executable code, not prose, so it gets real behavioral tests: the script is
sourced and invoked via `bash -c` against stub `orca`/target-command executables placed on
PATH, rather than asserted on via text matching.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "orca_call_with_retry.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(
    tmp_path: Path,
    stubs: dict[str, str],
    command: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in stubs.items():
        _write_executable(bin_dir / name, content)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env.update(extra_env or {})
    script = f"source '{SCRIPT}'\n{command}\n"
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result, home


def _log_lines(home: Path) -> list[dict]:
    log = home / ".local" / "state" / "orca-workflows" / "logs" / "spawn-failures.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_script_exists():
    assert SCRIPT.is_file(), "orca-workflows/scripts/orca_call_with_retry.sh is missing"


def test_pass_through_on_success(tmp_path):
    stubs = {
        "real-cmd": """
            #!/usr/bin/env bash
            echo hello-stdout
            echo hello-stderr >&2
            exit 0
        """,
    }
    result, home = _run(tmp_path, stubs, 'orca_call_with_retry "test-skill" "test-role" -- real-cmd')
    assert result.returncode == 0
    assert "hello-stdout" in result.stdout
    assert "hello-stderr" in result.stderr
    assert _log_lines(home) == []


def test_pass_through_on_unrelated_failure(tmp_path):
    stubs = {
        "real-cmd": """
            #!/usr/bin/env bash
            echo boom >&2
            exit 7
        """,
    }
    result, home = _run(tmp_path, stubs, 'orca_call_with_retry "test-skill" "test-role" -- real-cmd')
    assert result.returncode == 7
    assert "boom" in result.stderr
    assert _log_lines(home) == []
