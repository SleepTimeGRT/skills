# Orca Orchestration Call Retry-Backoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Orca's own auto-update restarts the app mid-session, `orca orchestration send/dispatch` and `orca terminal create` calls in `orca-workflow`/`orca-task-runner`/`orca-evaluate` self-recover instead of needing a human to notice and retype the command (issue #42).

**Architecture:** One new shared bash function, `orca_call_with_retry` (`orca-workflows/scripts/orca_call_with_retry.sh`), wraps every orchestration call site in the three skills and in the spec text given to spawned workers. On the two known connection-failure strings it polls `orca status --json` for `ready` (bounded) and retries the identical call, up to 2 cycles, logging every occurrence to the existing `spawn-failures.jsonl`; any other failure (or eventual exhaustion) passes through untouched to the caller's existing recovery path.

**Tech Stack:** `bash`, `jq` (confirmed installed, 1.7.1), `orca` CLI, Python 3.14 + `pytest` (existing `tests/` convention — plain functions/parametrize for structural checks, `subprocess`-driven functional tests for real bash).

## Global Constraints

- `orca-workflows/` is symlink-tracks-main (AGENTS.md #22) — no separate deploy step; edits go live on merge.
- Log directory stays `~/.local/state/orca-workflows/logs/`, git-untracked. `install -d -m 700` on the directory, `chmod 600` on every written file — matches the existing `spawn-failures.md` convention exactly, do not deviate.
- Retry scope is exactly `orca orchestration send/dispatch`/`task-create`/`task-list` and `orca terminal create` — never wrap `orca terminal wait`, `orca terminal read`, or `orca terminal close` (approved design, §6/§7 of the design doc).
- Defaults: `max_cycles=2`, `poll_interval=5` (seconds), `poll_max=6` (checks) — overridable via `ORCA_RETRY_MAX_CYCLES`/`ORCA_RETRY_POLL_INTERVAL`/`ORCA_RETRY_POLL_MAX` env vars strictly for test speed; production call sites never set these.
- A connection failure is treated as "request never reached the server" — no pre-retry effect-verification step. This assumption is scoped only to the two known signature strings.
- Dead-terminal detection (frozen `lastOutputAt`) is explicitly out of scope for this wrapper — that stays the caller's existing recovery path (re-spawn, `GATE_FAIL`, escalate).
- Every retry cycle (success or exhaustion) appends one `spawn-failures.jsonl` record — this is separate from, and does not replace, any human-facing report the caller makes on exhaustion.

---

## File Structure

- Create: `orca-workflows/scripts/orca_call_with_retry.sh` — the shared retry-with-backoff function + its jsonl-logging helper.
- Create: `tests/test_orca_call_with_retry.py` — functional tests executing the real script via `bash -c` against stub `orca`/target-command executables.
- Modify: `orca-workflows/spawn-failures.md` — new known-signature row.
- Modify: `skills/orca-workflow/SKILL.md` — wrap 6 call sites (task-runner spawn ×3, evaluate spawn ×3), §0 note.
- Modify: `skills/orca-task-runner/SKILL.md` — wrap 6 call sites (§2 task-create, §3 terminal-create ×3, §5 task-list + dispatch), §0 note, ⑦ worker-spec item.
- Modify: `skills/orca-evaluate/SKILL.md` — wrap 10 call sites (§0 ×3, §1 ×3, §2 ×1, §3 ×3), §0 note, worker-spec instructions in §1/§3 `spec_text`.
- Modify: `AGENTS.md` — update the `orca-workflows/` deploy-path note (#22) to mention the new `scripts/` directory.
- Modify: `tests/test_orca_skills.py` — structural regression tests for all of the above (append at end of file, same convention as the existing log-restructure section).

---

### Task 1: `orca_call_with_retry.sh` — pass-through skeleton

**Files:**
- Create: `orca-workflows/scripts/orca_call_with_retry.sh`
- Create: `tests/test_orca_call_with_retry.py`

**Interfaces:**
- Produces: `orca_call_with_retry <skill> <role> -- <command...>` — a sourced bash function. This first version passes stdout/stderr/exit code through unconditionally; Task 2 adds the retry branch without changing this signature.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_orca_call_with_retry.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_call_with_retry.py -v`

Expected: all 3 tests FAIL (`SCRIPT.is_file()` is false / `source` fails because the file doesn't exist).

- [ ] **Step 3: Write the minimal implementation**

Create `orca-workflows/scripts/orca_call_with_retry.sh`:

```bash
#!/usr/bin/env bash
# Shared retry-with-backoff wrapper for orca CLI calls that transiently fail when the Orca app
# auto-updates and restarts mid-session (issue #42).
#
#   source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
#   orca_call_with_retry <skill> <role> -- <orca command...>

orca_call_with_retry() {
  local skill="$1" role="$2"
  shift 2
  [ "${1:-}" = "--" ] && shift

  local out err code
  out="$(mktemp)"; err="$(mktemp)"
  "$@" >"$out" 2>"$err"
  code=$?
  cat "$out"
  cat "$err" >&2
  rm -f "$out" "$err"
  return "$code"
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_call_with_retry.py -v`

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/scripts/orca_call_with_retry.sh tests/test_orca_call_with_retry.py
git commit -m "feat(orca-workflows): add orca_call_with_retry pass-through skeleton (issue #42)"
```

---

### Task 2: `orca_call_with_retry.sh` — retry-with-backoff + jsonl logging

**Files:**
- Modify: `orca-workflows/scripts/orca_call_with_retry.sh`
- Modify: `tests/test_orca_call_with_retry.py`

**Interfaces:**
- Consumes: Task 1's `orca_call_with_retry <skill> <role> -- <command...>` signature (unchanged).
- Produces: on a matching connection-failure signature, appends one record per cycle to `~/.local/state/orca-workflows/logs/spawn-failures.jsonl` with shape `{ts, skill, role, provider:null, failure_signature, fix_applied:"retry-backoff", known_issue:42, outcome:"retrying"|"exhausted", attempts:<cycle>}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_call_with_retry.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_call_with_retry.py -v`

Expected: the 3 Task-1 tests still PASS; the 5 new tests FAIL (no retry/logging behavior exists yet — `real-cmd`'s exit 1 with the connection-failure text just passes straight through today, so e.g. `test_retry_recovers_after_orca_becomes_ready` sees `returncode == 1` instead of `0`).

- [ ] **Step 3: Implement the retry-with-backoff logic**

Replace `orca_call_with_retry`'s body in `orca-workflows/scripts/orca_call_with_retry.sh` and add the logging helper:

```bash
#!/usr/bin/env bash
# Shared retry-with-backoff wrapper for orca CLI calls that transiently fail when the Orca app
# auto-updates and restarts mid-session (issue #42).
#
#   source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
#   orca_call_with_retry <skill> <role> -- <orca command...>
#
# On success, or on a failure whose combined stdout+stderr doesn't match the known Orca-restart
# signature, the wrapped command's stdout/stderr/exit code pass through unchanged. On a matching
# failure: log one spawn-failures.jsonl occurrence, poll `orca status --json` for `.state ==
# "ready"` (bounded), and retry the identical command once ready — up to ORCA_RETRY_MAX_CYCLES
# cycles before giving up and returning the last failure to the caller.

_ORCA_RETRY_SIGNATURE_RE='Could not connect to the running Orca app|Orca is not running\. Run .orca open. first'

orca_call_with_retry() {
  local skill="$1" role="$2"
  shift 2
  [ "${1:-}" = "--" ] && shift

  local max_cycles="${ORCA_RETRY_MAX_CYCLES:-2}"
  local poll_interval="${ORCA_RETRY_POLL_INTERVAL:-5}"
  local poll_max="${ORCA_RETRY_POLL_MAX:-6}"
  local cycle=0

  while :; do
    local out err code combined
    out="$(mktemp)"; err="$(mktemp)"
    "$@" >"$out" 2>"$err"
    code=$?
    combined="$(cat "$out" "$err")"

    if [ "$code" -eq 0 ] || ! printf '%s' "$combined" | grep -qE "$_ORCA_RETRY_SIGNATURE_RE"; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi

    cycle=$((cycle + 1))
    local outcome="retrying"
    [ "$cycle" -ge "$max_cycles" ] && outcome="exhausted"
    _orca_retry_log_occurrence "$skill" "$role" "$combined" "$outcome" "$cycle"

    if [ "$cycle" -ge "$max_cycles" ]; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi
    rm -f "$out" "$err"

    local n=0 ready=0
    while [ "$n" -lt "$poll_max" ]; do
      if [ "$(orca status --json 2>/dev/null | jq -r '.state // empty')" = "ready" ]; then
        ready=1
        break
      fi
      n=$((n + 1))
      sleep "$poll_interval"
    done

    if [ "$ready" -eq 0 ]; then
      printf '%s' "$combined" >&2
      return "$code"
    fi
    # ready — loop back and retry the identical original command
  done
}

_orca_retry_log_occurrence() {
  local skill="$1" role="$2" failure_signature="$3" outcome="$4" attempts="$5"
  install -d -m 700 "$HOME/.local/state/orca-workflows/logs"
  jq -cn \
    --arg ts "$(date -u +%FT%TZ)" \
    --arg skill "$skill" \
    --arg role "$role" \
    --arg failure_signature "$failure_signature" \
    --argjson known_issue 42 \
    --arg outcome "$outcome" \
    --argjson attempts "$attempts" \
    '{
      ts: $ts,
      skill: $skill,
      role: $role,
      provider: null,
      failure_signature: $failure_signature,
      fix_applied: "retry-backoff",
      known_issue: $known_issue,
      outcome: $outcome,
      attempts: $attempts
    }' >> "$HOME/.local/state/orca-workflows/logs/spawn-failures.jsonl"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/spawn-failures.jsonl"
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_call_with_retry.py -v`

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/scripts/orca_call_with_retry.sh tests/test_orca_call_with_retry.py
git commit -m "feat(orca-workflows): add retry-backoff and spawn-failures.jsonl logging to orca_call_with_retry (issue #42)"
```

---

### Task 3: `spawn-failures.md` new known-signature row

**Files:**
- Modify: `orca-workflows/spawn-failures.md`
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing new — this is documentation only.
- Produces: a grep-able row so future spawn-failure triage recognizes this signature (per the file's own "grep-first" procedure).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orca_skills.py`:

```python
def test_spawn_failures_has_orca_restart_retry_row():
    text = (WORKFLOWS_DIR / "spawn-failures.md").read_text()
    assert "Could not connect to the running Orca app" in text
    assert "Orca is not running. Run 'orca open' first." in text
    assert "orca_call_with_retry" in text
    assert "#42" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py::test_spawn_failures_has_orca_restart_retry_row -v`

Expected: FAIL (row doesn't exist yet).

- [ ] **Step 3: Add the row**

In `orca-workflows/spawn-failures.md`, add a new row to the "Known signatures" table, immediately after the existing `#40` row (before the closing of the table, i.e. right before the `## Adding a new row` section):

```markdown
| `Could not connect to the running Orca app` / `Orca is not running. Run 'orca open' first.` | Orca 앱 자동 업데이트가 세션 도중 앱을 재시작시켜, 그 창에 걸린 orchestration 호출이 실패 | `orca_call_with_retry`(`orca-workflows/scripts/orca_call_with_retry.sh`)로 감싼다 — `orca status --json`이 `ready`가 될 때까지 바운드 폴링(5s×6) 후 같은 호출을 재시도, 최대 2사이클 후에도 실패하면 호출부에 그대로 반환 | #42 |
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py::test_spawn_failures_has_orca_restart_retry_row -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/spawn-failures.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): add spawn-failures.md row for Orca auto-update restart (issue #42)"
```

---

### Task 4: Wrap `orca-workflow/SKILL.md` call sites

**Files:**
- Modify: `skills/orca-workflow/SKILL.md:18-20` (§0 note), `:59-93` (task-runner/evaluate spawn block)
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `orca_call_with_retry` from Task 2 (via `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_skills.py`:

```python
def _bare_wrapped_call_line_numbers(text: str) -> list[int]:
    """Line numbers (1-indexed) where an orca terminal-create/task-create/dispatch call appears
    without 'orca_call_with_retry' on the same or immediately preceding line."""
    patterns = (
        "orca terminal create",
        "orca orchestration task-create --spec",
        "orca orchestration task-list",
        "orca orchestration dispatch --task",
    )
    lines = text.splitlines()
    bare = []
    for i, line in enumerate(lines):
        if any(pat in line for pat in patterns):
            window = "\n".join(lines[max(0, i - 1) : i + 1])
            if "orca_call_with_retry" not in window:
                bare.append(i + 1)
    return bare


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_no_bare_wrapped_call_sites(name):
    text = _read_skill(name)
    bare = _bare_wrapped_call_line_numbers(text)
    assert bare == [], (
        f"{name}: orca terminal create/task-create/dispatch call(s) not wrapped by "
        f"orca_call_with_retry at line(s) {bare}"
    )


EXPECTED_RETRY_WRAP_COUNTS = {
    "orca-workflow": 6,
    "orca-task-runner": 6,
    "orca-evaluate": 10,
}


@pytest.mark.parametrize(("name", "expected"), EXPECTED_RETRY_WRAP_COUNTS.items())
def test_orca_call_with_retry_count_per_skill(name, expected):
    actual = _read_skill(name).count("orca_call_with_retry ")
    assert actual == expected, f"{name}: expected {expected} orca_call_with_retry invocations, found {actual}"


@pytest.mark.parametrize("name", NEW_SKILLS)
def test_sources_retry_wrapper_script(name):
    text = _read_skill(name)
    assert "source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh" in text, (
        f"{name}: must source orca_call_with_retry.sh before using the wrapper function"
    )


def test_orca_workflow_section0_notes_retry_wrapping():
    text = _read_skill("orca-workflow")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -k "retry_wrap or bare_wrapped or sources_retry or section0_notes_retry" -v`

Expected: FAIL (`orca-workflow` has 0 wrapped calls today, `orca-task-runner`/`orca-evaluate` will also fail until Tasks 5-6 — that's expected at this point; only `orca-workflow`'s share of these needs to go green by the end of this task, the others go green in Tasks 5/6).

- [ ] **Step 3: Edit `skills/orca-workflow/SKILL.md`**

Replace the §0 bullet block:

```
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §2a의 두 `terminal create` 호출
  모두에 적용된다.
```

with:

```
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §2a의 두 `terminal create` 호출
  모두에 적용된다.
- 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature:
  `~/.agents/orca-workflows/spawn-failures.md`, issue #42), §2a의 `orca orchestration`/
  `orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
  후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
```

Then replace the full §2a bash block:

```bash
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
spec_text="<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 이 스킬은 diff/report 본문을 직접 읽지 않는다
#    (도입부 원칙); term-<run-handle>.jsonl은 orca-workflow 자신이 소유하는 파일이라 task-runner는
#    거기 쓰지 않는다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들
#    (subtask worker마다 하나씩)에 이미 남는다.

# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (agy REPL은 포커스 경합 시 영구 hang — `~/.agents/orca-workflows/models/agy.md`,
# `skills/orca-evaluate/SKILL.md` §0 참고). agy는 evaluate 내부 §2(agent e2e)의 headless
# sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
spec_text="<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<evaluate-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="evaluator", terminal=<evaluate-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 위 task-runner 사이트와 같은 이유.
```

with:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
spec_text="<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드>"
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 이 스킬은 diff/report 본문을 직접 읽지 않는다
#    (도입부 원칙); term-<run-handle>.jsonl은 orca-workflow 자신이 소유하는 파일이라 task-runner는
#    거기 쓰지 않는다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들
#    (subtask worker마다 하나씩)에 이미 남는다.

# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (agy REPL은 포커스 경합 시 영구 hang — `~/.agents/orca-workflows/models/agy.md`,
# `skills/orca-evaluate/SKILL.md` §0 참고). agy는 evaluate 내부 §2(agent e2e)의 headless
# sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
spec_text="<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드>"
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<evaluate-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="evaluator", terminal=<evaluate-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 위 task-runner 사이트와 같은 이유.
```

- [ ] **Step 4: Run tests to verify `orca-workflow`'s share passes**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -k "orca-workflow or section0_notes_retry" -v`

Also run the full dispatch/logging-pointer regression tests to confirm no collateral regression:

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -k "dispatch_site or terminal_read_counts or close_preceded" -v`

Expected: `orca-workflow`'s `test_no_bare_wrapped_call_sites`, its `test_orca_call_with_retry_count_per_skill` (6), `test_sources_retry_wrapper_script`, and `test_orca_workflow_section0_notes_retry_wrapping` PASS. The pre-existing dispatch-site/logging-pointer/terminal-read-count tests still PASS unchanged (this edit doesn't touch trailing comments or terminal-read/close call counts).

- [ ] **Step 5: Commit**

```bash
git add skills/orca-workflow/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-workflow): wrap orchestration call sites in orca_call_with_retry (issue #42)"
```

---

### Task 5: Wrap `orca-task-runner/SKILL.md` call sites + worker preamble item

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md:20-22` (§0 note), `:52-64` (§2 task-create), `:66` (⑦ item), `:72-88` (§3 terminal-create ×3), `:112-126` (§5 task-list + dispatch)
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `orca_call_with_retry` (Task 2).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orca_skills.py`:

```python
def test_orca_task_runner_subtask_spec_required_items_includes_retry_wrapping():
    text = _read_skill("orca-task-runner")
    checklist_idx = text.index("subtask spec 필수 항목")
    sixth_idx = text.index("⑥", checklist_idx)
    seventh_idx = text.index("⑦", sixth_idx)
    assert checklist_idx < sixth_idx < seventh_idx
    para_end = text.index("\n\n", checklist_idx)
    seventh_segment = text[seventh_idx:para_end]
    assert "orca_call_with_retry" in seventh_segment


def test_orca_task_runner_section0_notes_retry_wrapping():
    text = _read_skill("orca-task-runner")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -k "orca_task_runner_subtask_spec_required or orca_task_runner_section0_notes_retry or (orca-task-runner and (bare_wrapped or retry_wrap or sources_retry))" -v`

Expected: FAIL.

- [ ] **Step 3: Edit `skills/orca-task-runner/SKILL.md`**

Replace the §0 bullet:

```
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §3(launch)과 §5(폴링)에서
  이 확인이 걸리는 지점을 표시한다.
```

with:

```
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §3(launch)과 §5(폴링)에서
  이 확인이 걸리는 지점을 표시한다.
- 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature:
  `~/.agents/orca-workflows/spawn-failures.md`, issue #42), §2·§3·§5의 `orca orchestration`/
  `orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
  후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
```

Replace the §2 bash block:

```bash
spec_text="<subtask 본문 + 아래 필수 항목>"
orca orchestration task-create --spec "$spec_text" --deps '["task_xxx"]' --json
# spec_text 사이드카(로그 아님 — 일회성 핸드오프 파일) — logging.md §2의 sent 레시피는 "task-create
# --spec에 쓴 텍스트와 동일한 문자열"을 요구하는데, 그 원문을 코디네이터가 실제로 들고 있는 시점은
# 지금뿐이다(§5 dispatch는 몇 wave, 잠재적으로 긴 시간 뒤). 이 시점엔 아직 dispatch 대상 handle을
# 몰라 term-<handle>.jsonl에 바로 쓸 수 없으므로, task_id로 키를 잡은 사이드카에 남겨 §5가 handle을
# 알게 된 시점에 그대로 읽어 쓰게 한다 — §5가 읽은 직후 지운다(logs/ 아래 다른 파일과 달리 보존
# 대상이 아니다).
install -d -m 700 ~/.local/state/orca-workflows/logs
printf '%s' "$spec_text" > "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
chmod 600 "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
```

with:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
spec_text="<subtask 본문 + 아래 필수 항목>"
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration task-create --spec "$spec_text" --deps '["task_xxx"]' --json
# spec_text 사이드카(로그 아님 — 일회성 핸드오프 파일) — logging.md §2의 sent 레시피는 "task-create
# --spec에 쓴 텍스트와 동일한 문자열"을 요구하는데, 그 원문을 코디네이터가 실제로 들고 있는 시점은
# 지금뿐이다(§5 dispatch는 몇 wave, 잠재적으로 긴 시간 뒤). 이 시점엔 아직 dispatch 대상 handle을
# 몰라 term-<handle>.jsonl에 바로 쓸 수 없으므로, task_id로 키를 잡은 사이드카에 남겨 §5가 handle을
# 알게 된 시점에 그대로 읽어 쓰게 한다 — §5가 읽은 직후 지운다(logs/ 아래 다른 파일과 달리 보존
# 대상이 아니다).
install -d -m 700 ~/.local/state/orca-workflows/logs
printf '%s' "$spec_text" > "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
chmod 600 "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
```

Replace the "subtask spec 필수 항목" line:

```
subtask spec 필수 항목: ①구체적 작업 내용(코드 블록 포함 그대로) ②커밋 대상 브랜치·worktree 명시 ③resolved provider/model/effort 기록 ④"막히면 ask로 blocking 질문" ⑤"완료 시 preamble 지시대로 worker_done(payload에 filesModified)" ⑥**병렬 커밋 안전 규칙**(같은 worktree를 공유하는 병렬 워커가 서로의 미완성 변경을 덮어쓰지 않도록): `git add` 명시 경로만·`git commit -m "<msg>" -- <files>` pathspec 필수·index.lock 재시도.
```

with:

```
subtask spec 필수 항목: ①구체적 작업 내용(코드 블록 포함 그대로) ②커밋 대상 브랜치·worktree 명시 ③resolved provider/model/effort 기록 ④"막히면 ask로 blocking 질문" ⑤"완료 시 preamble 지시대로 worker_done(payload에 filesModified)" ⑥**병렬 커밋 안전 규칙**(같은 worktree를 공유하는 병렬 워커가 서로의 미완성 변경을 덮어쓰지 않도록): `git add` 명시 경로만·`git commit -m "<msg>" -- <files>` pathspec 필수·index.lock 재시도. ⑦**연결 실패 자동 재시도**: worker_done을 포함해 네가 보내는 `orca orchestration`/`orca terminal` 호출은 항상 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` 후 `orca_call_with_retry`로 감싸고, 연결 실패는 wrapper가 exhausted를 반환할 때만 사람에게 ask로 보고한다(issue #42).
```

Replace the §3 bash block:

```bash
# claude
orca terminal create --worktree active --title task-impl-<n> \
  --command "claude --model <model> --effort <effort> --dangerously-skip-permissions" --json
# codex
orca terminal create --worktree active --title task-impl-<n> \
  --command "codex --model <model> -c model_reasoning_effort=<effort> -s workspace-write -a never" --json
# agy — 프롬프트는 파일에 먼저 쓰고 command substitution으로 전달한다(인라인 '<...>' quoting은
# 괄호·따옴표·개행이 있는 프롬프트에서 라이브 셸 파싱 에러를 낸다 — orca-workflows/spawn-failures.md)
prompt_file="$(mktemp "${TMPDIR:-/tmp}/agy-prompt-XXXXXX.txt")"
cat > "$prompt_file" <<'PROMPT_EOF'
<subtask 지침>
PROMPT_EOF
orca terminal create --worktree active --title task-impl-<n> \
  --command "agy -p \"\$(cat '$prompt_file')\" --model <model> --print-timeout 15m --dangerously-skip-permissions" --json
orca terminal wait --terminal <impl-handle> --for tui-idle --timeout-ms 60000 --json   # agy는 --for exit --timeout-ms 960000
```

with:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# claude
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "claude --model <model> --effort <effort> --dangerously-skip-permissions" --json
# codex
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "codex --model <model> -c model_reasoning_effort=<effort> -s workspace-write -a never" --json
# agy — 프롬프트는 파일에 먼저 쓰고 command substitution으로 전달한다(인라인 '<...>' quoting은
# 괄호·따옴표·개행이 있는 프롬프트에서 라이브 셸 파싱 에러를 낸다 — orca-workflows/spawn-failures.md)
prompt_file="$(mktemp "${TMPDIR:-/tmp}/agy-prompt-XXXXXX.txt")"
cat > "$prompt_file" <<'PROMPT_EOF'
<subtask 지침>
PROMPT_EOF
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "agy -p \"\$(cat '$prompt_file')\" --model <model> --print-timeout 15m --dangerously-skip-permissions" --json
orca terminal wait --terminal <impl-handle> --for tui-idle --timeout-ms 60000 --json   # agy는 --for exit --timeout-ms 960000
```

Replace the §5 bash block:

```bash
orca orchestration task-list --ready --brief --json
spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # §2에서 남긴 사이드카
spec_text="$(cat "$spec_sidecar")"   # 지금 재구성하지 않는다 — §2에서 남긴 원문 그대로
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 스폰 실패 재시도나 worker_done
#    유실 수동 복구가 같은 task_id로 이 블록을 다시 태울 수 있어, 삭제는 터미널이 실제로 닫히는
#    시점(§5 마지막 블록)으로 미룬다.
```

with:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration task-list --ready --brief --json
spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # §2에서 남긴 사이드카
spec_text="$(cat "$spec_sidecar")"   # 지금 재구성하지 않는다 — §2에서 남긴 원문 그대로
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 스폰 실패 재시도나 worker_done
#    유실 수동 복구가 같은 task_id로 이 블록을 다시 태울 수 있어, 삭제는 터미널이 실제로 닫히는
#    시점(§5 마지막 블록)으로 미룬다.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -v`

Expected: every test whose parametrization covers `orca-task-runner` now PASSES; `orca-evaluate`'s share of `test_no_bare_wrapped_call_sites`/`test_orca_call_with_retry_count_per_skill`/`test_sources_retry_wrapper_script` still FAILS (fixed in Task 6). All pre-existing tests for `orca-task-runner` (destructive-ops field, close-preceded-by-read, terminal-read count) still PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/orca-task-runner/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-task-runner): wrap orchestration call sites and add ⑦ retry-wrapping worker item (issue #42)"
```

---

### Task 6: Wrap `orca-evaluate/SKILL.md` call sites + worker spec instructions

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md:14` (§0 note), `:18-26` (§0 block), `:36-44` (§1 block), `:66-69` (§2 terminal-create), `:133-141` (§3 block)
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `orca_call_with_retry` (Task 2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_skills.py`:

```python
def test_orca_evaluate_worker_specs_instruct_retry_wrapping():
    text = _read_skill("orca-evaluate")
    for marker in ("제안서 경로", "diff 절대경로"):
        idx = text.index(marker)
        end = text.index('>"', idx)
        segment = text[idx:end]
        assert "orca_call_with_retry" in segment, (
            f"orca-evaluate: spec_text placeholder starting near {marker!r} must instruct the "
            "spawned worker to wrap its own orchestration replies in orca_call_with_retry"
        )


def test_orca_evaluate_section0_notes_retry_wrapping():
    text = _read_skill("orca-evaluate")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "orca_call_with_retry" in section0 and "#42" in section0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -k "orca_evaluate_worker_specs or orca_evaluate_section0_notes or (orca-evaluate and (bare_wrapped or retry_wrap or sources_retry))" -v`

Expected: FAIL.

- [ ] **Step 3: Edit `skills/orca-evaluate/SKILL.md`**

Replace the §0 opening sentence:

```
`orca-workflow`가 이 스킬을 orchestration으로 띄운다 — 별도 터미널을 만들어 넘기는 것이지 자기 세션에서 도는 게 아니다. 스폰 실패 시(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다 — 아래 §1·§2·§3의 `terminal create` 호출에도 동일하게 적용된다.
```

with:

```
`orca-workflow`가 이 스킬을 orchestration으로 띄운다 — 별도 터미널을 만들어 넘기는 것이지 자기 세션에서 도는 게 아니다. 스폰 실패 시(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다 — 아래 §1·§2·§3의 `terminal create` 호출에도 동일하게 적용된다. 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature: 같은 문서, issue #42), 아래 §0·§1·§2·§3의 `orca orchestration`/`orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` 후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
```

Replace the §0 bash block:

```bash
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는 절차를 따른다
# (agy처럼 자동 확정 가능한 provider도 있고 아닐 수도 있다 — 여기서 agy 전용 시퀀스를 가정하지 않는다).
orca orchestration task-create --spec "<이 SKILL.md 지침 + diff 경로 + issue 원문 acceptance criteria + PASS/FAIL/ESCALATE 요청>" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
```

with:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는 절차를 따른다
# (agy처럼 자동 확정 가능한 provider도 있고 아닐 수도 있다 — 여기서 agy 전용 시퀀스를 가정하지 않는다).
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration task-create --spec "<이 SKILL.md 지침 + diff 경로 + issue 원문 acceptance criteria + PASS/FAIL/ESCALATE 요청>" --json
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
```

Replace the §1 bash block:

```bash
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §3 스폰도 동일한 형태(§2 agent-e2e는
# assign만 — term 로그 대상 아님).
#  logging.md §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-evaluate", role="contract-review", terminal=<contract-handle>,
#    meta 기록 후 sent.content=$spec_text. 이 사이트는 dispatch 이후 이 터미널을 다시 read하지
#    않으므로 recv는 기록하지 않는다(판정 결과는 relay로 받는다 — 위 §1 본문 참고).
```

with:

```bash
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시 + 판정 결과를 보낼 orchestration 호출은 orca_call_with_retry로 감싸고 연결 실패를 즉시 사람에게 알리지 말라는 지시>"
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §3 스폰도 동일한 형태(§2 agent-e2e는
# assign만 — term 로그 대상 아님).
#  logging.md §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-evaluate", role="contract-review", terminal=<contract-handle>,
#    meta 기록 후 sent.content=$spec_text. 이 사이트는 dispatch 이후 이 터미널을 다시 read하지
#    않으므로 recv는 기록하지 않는다(판정 결과는 relay로 받는다 — 위 §1 본문 참고).
```

Replace the §2 first two lines:

```bash
report_path="<worktree 루트>/.evaluate-agent-e2e-report.md"
orca terminal create --worktree active --title eval-agent-e2e \
  --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오 + 앱 URL/worktree 경로 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
```

with:

```bash
report_path="<worktree 루트>/.evaluate-agent-e2e-report.md"
orca_call_with_retry "orca-evaluate" "agent-e2e" -- \
  orca terminal create --worktree active --title eval-agent-e2e \
  --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오 + 앱 URL/worktree 경로 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
```

Replace the §3 bash block tail:

```bash
# REPL 필수, one-shot 금지 — 이유는 §1의 동일 주석 참고
orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
spec_text="<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
```

with:

```bash
# REPL 필수, one-shot 금지 — 이유는 §1의 동일 주석 참고
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
spec_text="<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지 + 판정 결과를 보낼 orchestration 호출은 orca_call_with_retry로 감싸고 연결 실패를 즉시 사람에게 알리지 말라는 지시>"
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py -v`

Expected: every test in `tests/test_orca_skills.py` PASSES, including `test_dispatch_site_count_and_section0_exception_shape` (still 6 total dispatch sites, still exactly 1 inside `orca-evaluate`'s §0 span — this task only prefixes those lines, it doesn't move or remove them), `test_orca_evaluate_review_model_selection_is_dynamic_not_fixed_high_risk` and its neighbors (untouched region), and all the `test_gate_safety_*` anchors (untouched — the §3 checklist paragraph precedes the edited lines).

- [ ] **Step 5: Commit**

```bash
git add skills/orca-evaluate/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-evaluate): wrap orchestration call sites and instruct workers to use orca_call_with_retry (issue #42)"
```

---

### Task 7: Update `AGENTS.md` `orca-workflows/` deploy-path note

**Files:**
- Modify: `AGENTS.md` (the `### \`orca-workflows/\` deploy path (decision, #22)` section)
- Modify: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing new — documentation only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orca_skills.py`:

```python
def test_agents_md_orca_workflows_note_mentions_scripts_dir():
    text = (REPO_ROOT / "AGENTS.md").read_text()
    idx = text.index("orca-workflows/` deploy path (decision, #22)")
    remainder = text[idx:]
    section_end_offset = remainder.index("\n## ") if "\n## " in remainder else len(remainder)
    section = remainder[:section_end_offset]
    assert "scripts/" in section and "orca_call_with_retry.sh" in section, (
        "AGENTS.md's orca-workflows/ deploy-path note must mention the new scripts/ directory "
        "now that it holds an executable helper, not just reference docs"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py::test_agents_md_orca_workflows_note_mentions_scripts_dir -v`

Expected: FAIL.

- [ ] **Step 3: Edit `AGENTS.md`**

Replace:

```
`orca-workflows/` is intentionally *not* brought under the commit-pinned mechanism above.
`~/.agents/orca-workflows/` is a plain symlink to this repo's local main-branch checkout
(single machine, single consumer: the three `orca-*` skills that read
`model-selection.md`/`spawn-failures.md`/`logging.md` from it). It isn't installed by other repos via
`npx skills add`, so `skills/`'s N-repo integrity guarantees don't apply here — changes go
live the moment they merge to main, with no separate deploy step to forget.
```

with:

```
`orca-workflows/` is intentionally *not* brought under the commit-pinned mechanism above.
`~/.agents/orca-workflows/` is a plain symlink to this repo's local main-branch checkout
(single machine, single consumer: the three `orca-*` skills that read
`model-selection.md`/`spawn-failures.md`/`logging.md` from it, plus `orca-workflows/scripts/` for
executable helpers such as `orca_call_with_retry.sh` — issue #42 — that call sites `source`
directly and invoke, not just read as reference prose). It isn't installed by other repos via
`npx skills add`, so `skills/`'s N-repo integrity guarantees don't apply here — changes go
live the moment they merge to main, with no separate deploy step to forget.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/test_orca_skills.py::test_agents_md_orca_workflows_note_mentions_scripts_dir -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md tests/test_orca_skills.py
git commit -m "docs(AGENTS): note orca-workflows/scripts/ as an executable departure from the docs-only deploy-path decision (issue #42)"
```

---

### Task 8: Full regression pass

**Files:**
- None (verification only — no source changes expected).

**Interfaces:**
- Consumes: everything from Tasks 1-7.

- [ ] **Step 1: Run the full test suite**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && python3 -m pytest tests/ -v`

Expected: all tests PASS, including every pre-existing test in `test_orca_skills.py` (dispatch-site counts, gate-safety anchors, tracker adapters, log-restructure invariants) and every new test added in Tasks 1-7.

- [ ] **Step 2: Re-grep all three `SKILL.md` files for any remaining bare call site**

Run:

```bash
cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task
for f in skills/orca-workflow/SKILL.md skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md; do
  echo "== $f =="
  grep -n "orca terminal create\|orca orchestration task-create --spec\|orca orchestration dispatch --task\|orca orchestration task-list" "$f"
done
```

Expected: every matched line either starts with `orca_call_with_retry` or is immediately preceded by a line ending in `orca_call_with_retry "<skill>" "<role>" -- \`. This is a manual visual double-check of what `test_no_bare_wrapped_call_sites` already asserts mechanically — confirms the assertion itself isn't missing a call-site pattern.

- [ ] **Step 3: Confirm `git status` shows only the expected files changed**

Run: `cd /Users/minchul/worktrees/sleeptimegrt-skills/issue-42-orca-workflow-task && git status && git log --oneline -8`

Expected: working tree clean (Task 7's commit is the tip), and the last 8 commits are exactly Tasks 1-7's commits plus the design-doc commit from brainstorming.

No commit for this task — it is verification only, per this plan's "Task Right-Sizing" guidance that not every task must produce a diff.
