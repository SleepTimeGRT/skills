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


def test_retry_recovers_after_orca_becomes_ready(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            if [ "$1" = "status" ]; then
              echo '{"state":"ready"}'
              exit 0
            fi
            echo "unsupported orca stub call: $*" >&2
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            count=0
            [ -f "$COUNTER_FILE" ] && count="$(cat "$COUNTER_FILE")"
            count=$((count + 1))
            echo "$count" > "$COUNTER_FILE"
            if [ "$count" -eq 1 ]; then
              echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
              exit 1
            fi
            echo recovered-ok
            exit 0
        """,
    }
    counter_file = tmp_path / "counter"
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={
            "COUNTER_FILE": str(counter_file),
            "ORCA_RETRY_POLL_INTERVAL": "0",
            "ORCA_RETRY_POLL_MAX": "1",
        },
    )
    assert result.returncode == 0
    assert "recovered-ok" in result.stdout
    logs = _log_lines(home)
    assert len(logs) == 1
    assert logs[0]["outcome"] == "retrying"
    assert logs[0]["attempts"] == 1
    assert logs[0]["known_issue"] == 42
    assert logs[0]["skill"] == "test-skill"
    assert logs[0]["role"] == "test-role"
    assert logs[0]["fix_applied"] == "retry-backoff"


def test_exhausts_after_max_cycles_when_signature_persists(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"state":"ready"}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "Orca is not running. Run 'orca open' first." >&2
            exit 1
        """,
    }
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "2"},
    )
    assert result.returncode == 1
    assert "Orca is not running" in result.stderr
    logs = _log_lines(home)
    assert [line["outcome"] for line in logs] == ["retrying", "exhausted"]
    assert [line["attempts"] for line in logs] == [1, 2]


def test_returns_failure_when_orca_never_becomes_ready(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"state":"pending"}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
            exit 1
        """,
    }
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "2", "ORCA_RETRY_MAX_CYCLES": "2"},
    )
    assert result.returncode == 1
    assert "Could not connect" in result.stderr
    logs = _log_lines(home)
    assert len(logs) == 1
    assert logs[0]["outcome"] == "retrying"
    assert logs[0]["attempts"] == 1


def test_log_file_is_chmod_600(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"state":"ready"}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "Orca is not running. Run 'orca open' first." >&2
            exit 1
        """,
    }
    _, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "1"},
    )
    log = home / ".local" / "state" / "orca-workflows" / "logs" / "spawn-failures.jsonl"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_default_backoff_parameters_match_issue_42_spec():
    text = SCRIPT.read_text()
    assert "ORCA_RETRY_MAX_CYCLES:-2" in text
    assert "ORCA_RETRY_POLL_INTERVAL:-5" in text
    assert "ORCA_RETRY_POLL_MAX:-6" in text
