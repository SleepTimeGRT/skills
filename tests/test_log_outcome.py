"""Functional tests for the shared log_outcome / log_self_recovery bash helpers (issues
#105/#116/#125/#127/#138).

Like test_log_dispatch.py, this wraps executable code, not prose: the script is sourced and
invoked via subprocess against an isolated HOME, parametrized across bash *and* zsh (the helper is
sourced into whatever shell runs a SKILL.md block -- zsh on this machine), with a timeout on every
call so a portability regression fails instead of hanging the suite.

The one contract-shaped exception is the enum-mirror test at the bottom: it extracts the script's
enum variables mechanically and compares them as sets against this file's own copy of the
documented value list -- an executable contract between the script (the machine-checked authority)
and logging.md (the human-readable mirror), not a prose-grep of the .md file.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "orca-workflows" / "scripts" / "log_dispatch.sh"
SHELLS = ["bash", "zsh"]

# The documented outcome value set. Human-readable mirror: orca-workflows/logging.md §1, the
# "outcome" section's two-axis list (verdict axis + progress-branch axis). The machine-checked
# authority is LOG_OUTCOME_ENUM in orca-workflows/scripts/log_dispatch.sh; this test pins the two
# to each other as sets, so either side drifting fails the suite without asserting any specific
# sentence of prose.
DOCUMENTED_OUTCOME_ENUM = [
    # verdict axis
    "PASS",
    "FAIL",
    "ESCALATE",
    "GATE_FAIL",
    "CONTRACT_ESCALATE",
    "CI_GATE_FAIL",
    # progress-branch axis
    "NO_DONE_TRANSITION",
    "CONTRACT_FINALIZED_BY_GENERATOR",
    "CONTRACT_APPROVED",
    "CONTRACT_SCHEMA_STALE",  # issue #160
    "MANUAL_RECOVERY_COMPLETED",
    "CI_GATE_TIMEOUT",
    "MERGE_CONFLICT",
    "RETRO_DONE",
    "RETRO_FAIL",
    "escalation_parked",
    "skipped",  # issue #138
    "unblocked_requeue",  # issue #165
    "NO_ACCEPTANCE_CRITERIA",  # issue #105
    "SPIKE_ANSWERED",  # 직접 이슈 없음, docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md
    "UNMAPPED_BRANCH",
]

# Human-readable mirror: orca-workflows/logging.md §1, the self_recovery recipe's action_taken
# value list. Authority: LOG_SELF_RECOVERY_ACTION_ENUM in log_dispatch.sh.
DOCUMENTED_ACTION_ENUM = [
    "resumed_wait",
    "retried_enter",
    "worker_abandon_retry",
    "task_recreate_retry",
    "escalated_spawn_failure",
    "none_decision_gate_self_timed_out_worker_proceeded",
    "UNMAPPED_BRANCH",
]

OUTCOME_CALL = "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS --retry 0"

SELF_RECOVERY_CALL = (
    "log_self_recovery --skill orca-workflow-epic --repo own/repo --issue 633 --task-id task_abc "
    "--dispatch-id ctx_1 --terminal term_x --waited-ms 3600000 "
    "--terminal-status alive --action-taken resumed_wait"
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


def _raw_lines(home: Path, pattern: str) -> list[str]:
    lines: list[str] = []
    logs = _logs_dir(home)
    if not logs.is_dir():
        return lines
    for f in sorted(logs.glob(pattern)):
        lines.extend(line for line in f.read_text().splitlines() if line.strip())
    return lines


def _records(home: Path, pattern: str = "assignments-*.jsonl") -> list[dict]:
    return [json.loads(line) for line in _raw_lines(home, pattern)]


def _assert_no_empty_string_values(rec: dict) -> None:
    """Issue #127's omission rule: a conditional/optional field must be absent, never ""."""
    empties = [k for k, v in rec.items() if v == ""]
    assert not empties, f"empty-string field values violate the omission rule: {empties}"


def test_script_exists():
    assert SCRIPT.is_file(), "orca-workflows/scripts/log_dispatch.sh is missing"


# ── (a) valid outcome -> correct JSONL line ────────────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_valid_outcome_writes_correct_record(tmp_path, shell):
    result, home = _run(tmp_path, OUTCOME_CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["event"] == "outcome"
    assert rec["skill"] == "orca-workflow-task"
    assert rec["issue"] == "42"
    assert rec["repo"] == "own/repo"
    assert rec["outcome"] == "PASS"
    assert rec["retry"] == 0  # a JSON number, not the string "0"
    assert "ts" in rec
    # UNMAPPED_BRANCH-only fields must not appear on a valid outcome
    assert "raw_outcome" not in rec
    assert "schema_gap_issue" not in rec
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_per_call_site_extra_fields_are_written_as_numbers(tmp_path, shell):
    script = (
        "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome CONTRACT_APPROVED "
        "--retry 0 --round 2\n"
        "log_outcome --skill orca-workflow --repo own/repo --issue 42 --outcome RETRO_DONE --retry 0 "
        "--filed 1 --commented 2 --discarded 0"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 2
    assert recs[0]["outcome"] == "CONTRACT_APPROVED"
    assert recs[0]["round"] == 2
    assert recs[1]["outcome"] == "RETRO_DONE"
    assert (recs[1]["filed"], recs[1]["commented"], recs[1]["discarded"]) == (1, 2, 0)


@pytest.mark.parametrize("shell", SHELLS)
def test_skipped_carries_blocked_by(tmp_path, shell):
    """Issue #138: skipped is a legal enum member with blocked_by as its conditional field."""
    script = (
        "log_outcome --skill orca-workflow-epic --repo own/repo --issue 12 --outcome skipped --retry 0 "
        "--blocked-by 10"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 1
    assert recs[0]["outcome"] == "skipped"
    assert recs[0]["blocked_by"] == "10"
    assert "raw_outcome" not in recs[0]


@pytest.mark.parametrize("shell", SHELLS)
def test_skipped_without_blocked_by_warns_but_still_writes(tmp_path, shell):
    script = "log_outcome --skill orca-workflow-epic --repo own/repo --issue 12 --outcome skipped --retry 0"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "blocked-by" in result.stderr
    recs = _records(home)
    assert len(recs) == 1  # never omit the outcome event
    assert recs[0]["outcome"] == "skipped"
    assert "blocked_by" not in recs[0]


@pytest.mark.parametrize("shell", SHELLS)
def test_unblocked_requeue_carries_blocked_by(tmp_path, shell):
    """Issue #165: unblocked_requeue is skipped's pair -- same blocked_by issue number, logged when
    the previously-parked dependent is re-queued after its blocker resolves."""
    script = (
        "log_outcome --skill orca-workflow-epic --repo own/repo --issue 23 --outcome unblocked_requeue "
        "--retry 0 --blocked-by 20"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 1
    assert recs[0]["outcome"] == "unblocked_requeue"
    assert recs[0]["blocked_by"] == "20"
    assert "raw_outcome" not in recs[0]


@pytest.mark.parametrize("shell", SHELLS)
def test_blocked_by_dropped_for_non_skipped_outcome(tmp_path, shell):
    script = "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS --retry 0 --blocked-by 10"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "blocked-by" in result.stderr
    recs = _records(home)
    assert "blocked_by" not in recs[0]


# ── (b) invalid outcome -> UNMAPPED_BRANCH substitution, not a pipeline failure ───────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_outcome_substituted_with_unmapped_branch(tmp_path, shell):
    """The five-recurrence defect class (#62/#69/#86/#105/#138): an invented value must be forced
    through the documented safeguard at runtime, with exit 0 (never fail the pipeline)."""
    script = "log_outcome --skill orca-workflow-epic --repo own/repo --issue 626 --outcome EPIC_DONE --retry 0\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "rc=0" in result.stdout
    assert "UNMAPPED_BRANCH" in result.stderr and "EPIC_DONE" in result.stderr
    recs = _records(home)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["outcome"] == "UNMAPPED_BRANCH"
    assert rec["raw_outcome"] == "EPIC_DONE"
    assert rec["schema_gap_issue"] == "unfiled"
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_invalid_outcome_uses_caller_supplied_schema_gap_issue(tmp_path, shell):
    script = (
        "log_outcome --skill orca-workflow-epic --repo own/repo --issue 626 --outcome EPIC_DONE --retry 0 "
        "--schema-gap-issue epic-done-enum-gap"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert rec["outcome"] == "UNMAPPED_BRANCH"
    assert rec["schema_gap_issue"] == "epic-done-enum-gap"


@pytest.mark.parametrize("shell", SHELLS)
def test_typo_variant_of_valid_outcome_is_also_substituted(tmp_path, shell):
    """#127 showed the class fires on hand-typed near-misses (resume_wait), not just new
    branches -- a one-character outcome typo must not pass the enum check either."""
    script = "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASSS --retry 0"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert rec["outcome"] == "UNMAPPED_BRANCH"
    assert rec["raw_outcome"] == "PASSS"


@pytest.mark.parametrize("shell", SHELLS)
def test_outcome_with_whitespace_cannot_false_match_the_list(tmp_path, shell):
    """Two adjacent enum members pasted as one value ("PASS FAIL") appear verbatim inside the
    space-separated enum string -- the validator must not be fooled by substring matching."""
    script = 'log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome "PASS FAIL" --retry 0'
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert rec["outcome"] == "UNMAPPED_BRANCH"
    assert rec["raw_outcome"] == "PASS FAIL"


@pytest.mark.parametrize("shell", SHELLS)
def test_conditional_fields_dropped_on_valid_outcome(tmp_path, shell):
    script = (
        "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS --retry 0 "
        "--raw-outcome leftover --schema-gap-issue leftover-slug"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "UNMAPPED_BRANCH" in result.stderr  # the warning names the rule
    rec = _records(home)[0]
    assert rec["outcome"] == "PASS"
    assert "raw_outcome" not in rec
    assert "schema_gap_issue" not in rec


# ── (c) empty optional fields are omitted entirely ─────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_optional_fields_are_omitted_not_empty_strings(tmp_path, shell):
    """Issue #127: conditional fields written as "" violate the omission rule -- the helper must
    make that mistake impossible even when a call site passes the flags unconditionally."""
    script = (
        "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS --retry 0 "
        '--round "" --filed "" --commented "" --discarded "" --detail "" --blocked-by ""'
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 1
    rec = recs[0]
    for field in ("round", "filed", "commented", "discarded", "detail", "blocked_by"):
        assert field not in rec, f"{field} must be omitted when empty, not written"
    _assert_no_empty_string_values(rec)


# ── (d) every written line is valid JSON ───────────────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_all_output_lines_are_valid_json(tmp_path, shell):
    script = (
        f"{OUTCOME_CALL}\n"
        "log_outcome --skill orca-workflow-epic --repo own/repo --issue 626 --outcome EPIC_DONE --retry 0\n"
        'log_outcome --skill orca-workflow --repo own/repo --issue 7 --outcome MANUAL_RECOVERY_COMPLETED '
        '--retry 1 --detail "worker_done lost; verified commit a1b2c3 by hand"'
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    lines = _raw_lines(home, "assignments-*.jsonl")
    assert len(lines) == 3
    for line in lines:
        rec = json.loads(line)  # raises on invalid JSON
        assert rec["event"] == "outcome"
    assert json.loads(lines[2])["detail"] == "worker_done lost; verified commit a1b2c3 by hand"


# ── caller errors: reject, write nothing, don't kill the sourcing script ───────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_required_argument_returns_nonzero_and_writes_nothing(tmp_path, shell):
    script = "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert "--retry" in result.stderr
    assert not _records(home)


@pytest.mark.parametrize("shell", SHELLS)
def test_outcome_missing_repo_returns_nonzero_and_writes_nothing(tmp_path, shell):
    """Issue #158: repo is required on outcome events too -- most outcome records carry
    worktree-free context (worktree:null), so without repo there is no way at all to attribute
    them to a repository after the fact."""
    script = OUTCOME_CALL.replace("--repo own/repo ", "") + "\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert "--repo" in result.stderr
    assert not _records(home)


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_missing_repo_returns_nonzero_and_writes_nothing(tmp_path, shell):
    script = SELF_RECOVERY_CALL.replace("--repo own/repo ", "") + "\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert "--repo" in result.stderr
    assert not _records(home)
    assert not _records(home, "waves-*.jsonl")


@pytest.mark.parametrize("shell", SHELLS)
def test_non_numeric_retry_is_a_caller_error(tmp_path, shell):
    script = "log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome PASS --retry abc\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert not _records(home)


@pytest.mark.parametrize("shell", SHELLS)
def test_helper_failure_does_not_abort_calling_script(tmp_path, shell):
    """Same guarantee test_log_dispatch.py pins for log_dispatch: an invalid call must not unwind
    the sourced script and silently skip the commands after it in the same fenced block."""
    script = "log_outcome --skill x\necho MARKER_AFTER_FAILED_CALL"
    result, _home = _run(tmp_path, script, shell=shell)
    assert "MARKER_AFTER_FAILED_CALL" in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_flag_with_missing_value_returns_nonzero_not_hang(tmp_path, shell):
    script = "log_outcome --skill\necho rc=$?\necho AFTER"
    result, _home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert "AFTER" in result.stdout


@pytest.mark.parametrize("shell", SHELLS)
def test_written_file_is_chmod_600(tmp_path, shell):
    result, home = _run(tmp_path, OUTCOME_CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assign_file = _logs_dir(home) / f"assignments-{today}.jsonl"
    assert stat.S_IMODE(assign_file.stat().st_mode) == 0o600


# ── log_self_recovery (issue #127) ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_valid_action_writes_correct_record(tmp_path, shell):
    result, home = _run(tmp_path, SELF_RECOVERY_CALL, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["event"] == "self_recovery"
    assert rec["skill"] == "orca-workflow-epic"
    assert rec["repo"] == "own/repo"
    assert rec["action_taken"] == "resumed_wait"
    assert rec["waited_ms"] == 3600000  # a JSON number
    assert rec["terminal_status"] == "alive"
    # #127's exact defect shape: these three must be ABSENT on a valid action, never ""
    for field in ("new_dispatch_id", "raw_action", "schema_gap_issue"):
        assert field not in rec
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_empty_conditional_flags_are_omitted(tmp_path, shell):
    """The migrated self-recovery.md call site passes the conditional flags unconditionally with
    possibly-empty values -- the helper must omit them (this is what killed #127's printf)."""
    script = f'{SELF_RECOVERY_CALL} --new-dispatch-id "" --raw-action "" --schema-gap-issue ""'
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    for field in ("new_dispatch_id", "raw_action", "schema_gap_issue"):
        assert field not in rec
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_typo_action_substituted_with_unmapped_branch(tmp_path, shell):
    """#127's literal observed defect: resume_wait (a typo of resumed_wait) written 5x verbatim."""
    script = SELF_RECOVERY_CALL.replace("--action-taken resumed_wait", "--action-taken resume_wait")
    script += "\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "rc=0" in result.stdout
    assert "resume_wait" in result.stderr and "UNMAPPED_BRANCH" in result.stderr
    rec = _records(home)[0]
    assert rec["action_taken"] == "UNMAPPED_BRANCH"
    assert rec["raw_action"] == "resume_wait"
    assert rec["schema_gap_issue"] == "unfiled"
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_new_dispatch_id_kept_for_retry_actions(tmp_path, shell):
    script = (
        "log_self_recovery --skill orca-workflow-task --repo own/repo --issue 633 --task-id task_abc "
        "--dispatch-id ctx_1 --terminal term_x --waited-ms 3600000 --terminal-status dead "
        "--action-taken worker_abandon_retry --new-dispatch-id ctx_2"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert rec["action_taken"] == "worker_abandon_retry"
    assert rec["new_dispatch_id"] == "ctx_2"


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_new_dispatch_id_dropped_for_non_retry_actions(tmp_path, shell):
    script = f"{SELF_RECOVERY_CALL} --new-dispatch-id ctx_2"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "new-dispatch-id" in result.stderr
    rec = _records(home)[0]
    assert "new_dispatch_id" not in rec


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_task_runner_writes_to_waves_with_wave_index(tmp_path, shell):
    script = (
        "log_self_recovery --skill orca-task-runner --repo own/repo --issue 633 --task-id task_abc "
        "--dispatch-id ctx_1 --terminal term_x --waited-ms 3600000 --terminal-status alive "
        "--action-taken resumed_wait --wave-index 2"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert not _records(home, "assignments-*.jsonl")
    waves = _records(home, "waves-*.jsonl")
    assert len(waves) == 1
    assert waves[0]["wave_index"] == 2


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_wave_index_dropped_for_coordinators(tmp_path, shell):
    script = f"{SELF_RECOVERY_CALL} --wave-index 2"
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    assert "wave-index" in result.stderr
    rec = _records(home, "assignments-*.jsonl")[0]
    assert "wave_index" not in rec
    assert not _records(home, "waves-*.jsonl")


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_omitted_waited_ms_is_json_null(tmp_path, shell):
    script = SELF_RECOVERY_CALL.replace("--waited-ms 3600000 ", "")
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert "waited_ms" in rec and rec["waited_ms"] is None


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_accepts_n_a_terminal_status_for_worker_independent_escalation(tmp_path, shell):
    """issue #183: self-recovery.md's escalation branches that are not about worker liveness (retry
    budget exhausted, transport-stall budget exhausted) set terminal_status=n/a -- alive/dead/
    stuck_draft are all worker-liveness classifications and none is accurate when no worker probe
    ran. Validation previously rejected n/a outright (exit 64, nothing written), so every
    escalated_spawn_failure event of this kind silently vanished from assignments-*.jsonl."""
    script = SELF_RECOVERY_CALL.replace("--terminal-status alive", "--terminal-status n/a").replace(
        "--action-taken resumed_wait", "--action-taken escalated_spawn_failure"
    )
    result, home = _run(tmp_path, script, shell=shell)
    assert result.returncode == 0, result.stderr
    rec = _records(home)[0]
    assert rec["terminal_status"] == "n/a"
    assert rec["action_taken"] == "escalated_spawn_failure"
    _assert_no_empty_string_values(rec)


@pytest.mark.parametrize("shell", SHELLS)
def test_self_recovery_invalid_terminal_status_is_a_caller_error(tmp_path, shell):
    """terminal_status has no documented UNMAPPED_BRANCH-style safeguard (no raw_* field), so an
    unknown value is rejected like log_dispatch's --provider (issue #90), never persisted."""
    script = SELF_RECOVERY_CALL.replace("--terminal-status alive", "--terminal-status zombie")
    script += "\necho rc=$?"
    result, home = _run(tmp_path, script, shell=shell)
    assert "rc=64" in result.stdout
    assert not _records(home)


# ── (e) executable enum contract: script authority vs documented mirror ───────────────────────


def _extract_enum(var_name: str) -> set[str]:
    text = SCRIPT.read_text()
    m = re.search(rf'^{var_name}="([^"]+)"$', text, re.MULTILINE)
    assert m, f"{var_name} variable not found in {SCRIPT}"
    return set(m.group(1).split())


def test_outcome_enum_matches_documented_list():
    assert _extract_enum("LOG_OUTCOME_ENUM") == set(DOCUMENTED_OUTCOME_ENUM)


def test_action_enum_matches_documented_list():
    assert _extract_enum("LOG_SELF_RECOVERY_ACTION_ENUM") == set(DOCUMENTED_ACTION_ENUM)


@pytest.mark.parametrize("shell", SHELLS)
def test_every_documented_outcome_value_is_accepted_at_runtime(tmp_path, shell):
    """Set equality on the variable is necessary but not sufficient -- this drives every
    documented value through the actual validation path and asserts none get substituted."""
    calls = "\n".join(
        f"log_outcome --skill orca-workflow-task --repo own/repo --issue 42 --outcome {v} --retry 0"
        for v in DOCUMENTED_OUTCOME_ENUM
        if v != "UNMAPPED_BRANCH"  # legal too, but warns about missing --raw-outcome by design
    )
    result, home = _run(tmp_path, calls, shell=shell)
    assert result.returncode == 0, result.stderr
    recs = _records(home)
    written = [r["outcome"] for r in recs]
    expected = [v for v in DOCUMENTED_OUTCOME_ENUM if v != "UNMAPPED_BRANCH"]
    assert written == expected
    assert all("raw_outcome" not in r for r in recs)
