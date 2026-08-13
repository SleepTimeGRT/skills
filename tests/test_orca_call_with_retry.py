"""Functional tests for the shared orca_call_with_retry bash wrapper (issue #42).

This wraps executable code, not prose, so it gets real behavioral tests: the script is
sourced and invoked via `bash -c` against stub `orca`/target-command executables placed on
PATH, rather than asserted on via text matching.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

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
    shell: str = "bash",
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
        [shell, "-c", script],
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
              echo '{"result":{"runtime":{"state":"ready"}}}'
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
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
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
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"pending"}}}' && exit 0
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
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
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


def test_poll_timeout_path_keeps_stdout_and_stderr_separate(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"pending"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "PARTIAL-STDOUT-DATA"
            echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
            exit 1
        """,
    }
    result, _ = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "2"},
    )
    assert result.returncode == 1
    assert "PARTIAL-STDOUT-DATA" in result.stdout
    assert "PARTIAL-STDOUT-DATA" not in result.stderr
    assert "Could not connect" in result.stderr


def test_logged_failure_signature_is_matched_substring_not_full_output(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "UNRELATED-STDOUT-NOISE"
            echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
            exit 1
        """,
    }
    _, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "1"},
    )
    logs = _log_lines(home)
    assert len(logs) == 1
    assert logs[0]["failure_signature"] == "Could not connect to the running Orca app"
    assert "UNRELATED-STDOUT-NOISE" not in logs[0]["failure_signature"]


def test_broadened_signature_catches_stale_bootstrap_without_new_literal(tmp_path):
    """issue #42 재발: 기존 리터럴 어느 쪽과도 매칭 안 되던 텍스트가 키워드 매칭으로 잡히는지."""
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            count=0
            [ -f "$COUNTER_FILE" ] && count="$(cat "$COUNTER_FILE")"
            count=$((count + 1))
            echo "$count" > "$COUNTER_FILE"
            if [ "$count" -eq 1 ]; then
              echo "runtime_error: stale_bootstrap detected, dropping connection" >&2
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
    assert "bootstrap" in logs[0]["failure_signature"].lower()


def test_broadened_signature_catches_closed_the_connection_message(tmp_path):
    """issue #103: 실측된 리터럴 그대로("The Orca runtime closed the connection before
    responding.") — 기존 6개 키워드 어느 것과도 매칭 안 됐던 문구가 잡히는지."""
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            count=0
            [ -f "$COUNTER_FILE" ] && count="$(cat "$COUNTER_FILE")"
            count=$((count + 1))
            echo "$count" > "$COUNTER_FILE"
            if [ "$count" -eq 1 ]; then
              echo "The Orca runtime closed the connection before responding. Restart Orca and try again." >&2
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
    assert "closed the connection" in logs[0]["failure_signature"].lower()


def test_broadened_signature_catches_generic_reconnect_message(tmp_path):
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "Orca client: reconnecting after unexpected disconnect" >&2
            exit 1
        """,
    }
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "1"},
    )
    logs = _log_lines(home)
    assert len(logs) == 1
    assert logs[0]["outcome"] == "exhausted"
    assert "reconnect" in logs[0]["failure_signature"].lower()


def test_case_insensitive_match_does_not_alter_known_literal_extraction(tmp_path):
    """-i 추가 + 키워드 대안 추가 후에도 기존 리터럴이 leftmost-longest로 여전히 승리하는지 —
    test_logged_failure_signature_is_matched_substring_not_full_output의 정확 일치 단언과
    같은 조건을 실제 diff에 대해 명시적으로 재확인(승인 조건 2와 직결)."""
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
            exit 1
        """,
    }
    _, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- real-cmd',
        extra_env={"ORCA_RETRY_POLL_INTERVAL": "0", "ORCA_RETRY_POLL_MAX": "1", "ORCA_RETRY_MAX_CYCLES": "1"},
    )
    logs = _log_lines(home)
    assert logs[0]["failure_signature"] == "Could not connect to the running Orca app"


def test_retry_wrapper_header_documents_retry_request_dedupe():
    text = SCRIPT.read_text()
    assert "No idempotency safeguard" not in text, (
        "stale claim -- --retry-request dedupe now exists and must be documented instead (#73)"
    )
    assert "--retry-request" in text
    assert "mutation.replayed" in text


SHELLS = ["bash", "zsh"]


@pytest.mark.parametrize("shell", SHELLS)
def test_retry_request_value_is_identical_across_retry_cycle(tmp_path, shell):
    """A caller embeds --retry-request "$(uuidgen)" in the command line handed to
    orca_call_with_retry, once, before the retry loop starts. This test proves that literal
    value -- not a fresh uuidgen call -- is what reaches the wrapped command on every retry
    attempt, which is exactly the property issue #73/AC1 relies on to make retries
    idempotent server-side. Reproduces the wrapper's real retry path (transient failure ->
    orca status ready -> identical re-exec) rather than asserting on the SKILL.md prose."""
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    stubs = {
        "orca": """
            #!/usr/bin/env bash
            [ "$1" = "status" ] && echo '{"result":{"runtime":{"state":"ready"}}}' && exit 0
            exit 1
        """,
        "real-cmd": """
            #!/usr/bin/env bash
            # record every --retry-request value this invocation was called with
            for a in "$@"; do
              if [ "$prev" = "--retry-request" ]; then echo "$a" >> "$SEEN_FILE"; fi
              prev="$a"
            done
            count=0
            [ -f "$COUNTER_FILE" ] && count="$(cat "$COUNTER_FILE")"
            count=$((count + 1))
            echo "$count" > "$COUNTER_FILE"
            if [ "$count" -eq 1 ]; then
              echo "Could not connect to the running Orca app. Restart Orca and try again." >&2
              exit 1
            fi
            exit 0
        """,
    }
    counter_file = tmp_path / "counter"
    seen_file = tmp_path / "seen"
    # mimic a caller's real call-site: id expanded once via command substitution, at
    # construction time, exactly as skills/*/SKILL.md's proposed edits do
    result, home = _run(
        tmp_path,
        stubs,
        'orca_call_with_retry "test-skill" "test-role" -- '
        'real-cmd --retry-request "$(uuidgen)" --json',
        extra_env={
            "COUNTER_FILE": str(counter_file),
            "SEEN_FILE": str(seen_file),
            "ORCA_RETRY_POLL_INTERVAL": "0",
            "ORCA_RETRY_POLL_MAX": "1",
        },
        shell=shell,
    )
    assert result.returncode == 0
    seen = seen_file.read_text().splitlines()
    assert len(seen) == 2, f"expected real-cmd invoked twice (initial + 1 retry), got {seen}"
    assert seen[0] == seen[1], (
        f"--retry-request value changed across the retry cycle: {seen[0]!r} != {seen[1]!r}"
    )
    assert seen[0] != "", "--retry-request value must not be empty"
