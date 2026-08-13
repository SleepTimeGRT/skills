"""Functional tests for issue #103's fix to self-recovery.md's "## The wait/recovery loop":
the raw `check --wait` call was unwrapped, so an Orca-app-restart mid-wait (observed live as
"The Orca runtime closed the connection before responding.") left $result holding garbage/empty
JSON. The un-wrapped code then silently read that as timed_out=false (zero messages this batch),
dropping prev_delivery_id with no escalation and no log trail.

The fix wraps the call in orca_call_with_retry with ORCA_RETRY_MAX_CYCLES=1 (so the wrapper only
detects+logs the signature once, never silently re-waits the full --timeout-ms itself) and gives
the loop its own transport-stall branch, distinct from the pre-existing timed_out=true branch:
a transport failure must not run the worker-liveness probe (`orca terminal read`) that branch
starts with, since that probe would fail for the same reason and could misclassify a healthy
worker as "dead" (see self-recovery.md's inline comments at the branch itself for the full
rationale).

These tests run the real, unmodified bash extracted from self-recovery.md against stubbed
`orca`/`sleep`, following this repo's established convention of exercising the document's own code
verbatim rather than a reimplementation of it (precedent: the now-removed
tests/test_dispatch_created_via_wiring.py inject-subbranch tests, deleted alongside their dead code
by issue #94 stage 3).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"
ORCA_CALL_WITH_RETRY = REPO_ROOT / "orca-workflows" / "scripts" / "orca_call_with_retry.sh"
LOG_DISPATCH = REPO_ROOT / "orca-workflows" / "scripts" / "log_dispatch.sh"


def _wait_loop_snippet() -> str:
    text = SELF_RECOVERY_MD.read_text()
    start = text.index("source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh")
    end = text.index("# if pending set non-empty: loop back to the top") + len(
        "# if pending set non-empty: loop back to the top with the remaining task_ids (re-issue check --wait,\n"
        "# never check --peek, for the next batch).\n"
    )
    return text[start:end]


# The snippet's own `source ~/.agents/orca-workflows/scripts/...sh` lines are left in place
# verbatim (not stripped) -- under an isolated $HOME with no ~/.agents tree they simply fail to
# find the file and no-op (bash `source` on a missing file errors without side effects), which is
# harmless because the harness below sources the real, repo-relative copies of both scripts first,
# so the functions are already defined by the time the snippet's own source lines are reached.
_STUBS = r'''
sleep() { :; }
orca() {
  if [ "$1" = "status" ]; then
    if [ "${STUB_ORCA_READY:-1}" = "1" ]; then
      echo '{"result":{"runtime":{"state":"ready"}}}'
    else
      echo '{"result":{"runtime":{"state":"restarting"}}}'
    fi
    return 0
  fi
  if [ "$1 $2" = "orchestration check" ]; then
    echo "$CHECK_CALL_MARKER" >> "$CHECK_CALL_LOG"
    if [ "${STUB_CHECK_FAILS:-1}" = "1" ]; then
      echo "The Orca runtime closed the connection before responding." >&2
      return 1
    fi
    echo '{"result":{"timedOut":false,"deliveryId":"delivery-new","messages":[]}}'
    return 0
  fi
  echo "unsupported orca stub call: $*" >&2
  return 1
}
'''


def _run_wait_loop(
    tmp_path: Path,
    *,
    prev_delivery_id: str = "",
    retry_count: int = 0,
    transport_stall_count: int = 0,
    stub_orca_ready: bool = True,
    stub_check_fails: bool = True,
    stale_action_taken: str = "",
) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    check_call_log = tmp_path / "check_calls.log"
    out_file = tmp_path / "state.json"

    script = (
        "set -u\n"
        f"source '{ORCA_CALL_WITH_RETRY}'\n"
        f"source '{LOG_DISPATCH}'\n"
        + _STUBS
        + f'prev_delivery_id="{prev_delivery_id}"\n'
        + f'retry_count={retry_count}\n'
        + f'transport_stall_count={transport_stall_count}\n'
        + f'action_taken="{stale_action_taken}"\n'
        + 'RUN_ID="run_fake"; CALLING_SKILL="orca-workflow-task"; ISSUE_NUM="180"; '
          'REPO_SLUG="owner/repo"; TASK_ID="task_fake"; DISPATCH_ID="dispatch_fake"; '
          'WORKER_HANDLE="term_fake"\n'
        + _wait_loop_snippet()
        + '\n'
        + 'jq -cn --arg action_taken "${action_taken:-}" --arg terminal_status "${terminal_status:-}" '
          '--arg prev_delivery_id "$prev_delivery_id" --argjson transport_stall_count '
          '"${transport_stall_count:-0}" --argjson retry_count "${retry_count:-0}" '
          '\'{action_taken:$action_taken, terminal_status:$terminal_status, '
          'prev_delivery_id:$prev_delivery_id, transport_stall_count:$transport_stall_count, '
          f"retry_count:$retry_count}}' > '{out_file}'\n"
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "STUB_ORCA_READY": "1" if stub_orca_ready else "0",
        "STUB_CHECK_FAILS": "1" if stub_check_fails else "0",
        "CHECK_CALL_LOG": str(check_call_log),
        "CHECK_CALL_MARKER": "called",
    }
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    state = json.loads(out_file.read_text())
    state["check_call_count"] = (
        len(check_call_log.read_text().splitlines()) if check_call_log.exists() else 0
    )
    state["spawn_failures"] = _spawn_failures(home)
    state["self_recovery_events"] = _self_recovery_events(home)
    return state


def _spawn_failures(home: Path) -> list[dict]:
    log = home / ".local" / "state" / "orca-workflows" / "logs" / "spawn-failures.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _self_recovery_events(home: Path) -> list[dict]:
    logs_dir = home / ".local" / "state" / "orca-workflows" / "logs"
    events: list[dict] = []
    if not logs_dir.exists():
        return events
    for f in logs_dir.glob("assignments-*.jsonl"):
        events.extend(json.loads(line) for line in f.read_text().splitlines() if line.strip())
    return events


def test_transport_stall_recovers_without_worker_liveness_probe_or_self_recovery_log(tmp_path):
    # Orca comes back on the first status poll (STUB_ORCA_READY=1). The check --wait call itself
    # is invoked exactly once (ORCA_RETRY_MAX_CYCLES=1 in the snippet suppresses the wrapper's own
    # retry) -- proving no silent double-wait. retry_count/prev_delivery_id must be untouched, and
    # no self_recovery event should be written (this sub-case is already durably recorded in
    # spawn-failures.jsonl by the wrapper itself).
    state = _run_wait_loop(
        tmp_path,
        prev_delivery_id="delivery-prior",
        retry_count=1,
        stub_orca_ready=True,
        stub_check_fails=True,
    )
    assert state["check_call_count"] == 1, "the wrapped check --wait call must run exactly once"
    assert state["action_taken"] == ""
    assert state["prev_delivery_id"] == "delivery-prior", "must be preserved, not cleared or re-parsed"
    assert state["retry_count"] == 1, "worker-liveness retry_count must not be touched by a transport stall"
    assert state["transport_stall_count"] == 1
    assert len(state["spawn_failures"]) == 1
    assert state["spawn_failures"][0]["outcome"] == "exhausted"
    assert state["self_recovery_events"] == []


def test_transport_stall_escalates_when_orca_never_becomes_ready(tmp_path):
    state = _run_wait_loop(
        tmp_path,
        prev_delivery_id="delivery-prior",
        stub_orca_ready=False,
        stub_check_fails=True,
    )
    assert state["action_taken"] == "escalated_spawn_failure"
    assert state["terminal_status"] == "n/a"
    assert state["prev_delivery_id"] == "delivery-prior", "still preserved on escalation"
    # Two independent fixes both had to land for this event to appear: issue #183 (log_self_recovery
    # rejected --terminal-status n/a with exit 64) and issue #186 (this branch's action_taken was set
    # but control never reached the log_self_recovery call at all -- it was scoped inside the elif
    # branch only). The event must actually land, carrying the same terminal_status/action_taken this
    # test already asserts above.
    assert len(state["self_recovery_events"]) == 1
    event = state["self_recovery_events"][0]
    assert event["terminal_status"] == "n/a"
    assert event["action_taken"] == "escalated_spawn_failure"


def test_transport_stall_escalates_after_repeated_consecutive_stalls_even_if_orca_is_ready(tmp_path):
    # transport_stall_count preset to 2 simulates the 3rd consecutive stall about to happen --
    # the escalation path must fire immediately instead of polling/looping again, even though Orca
    # itself is reachable (STUB_ORCA_READY=1) -- the budget, not current reachability, decides.
    state = _run_wait_loop(
        tmp_path,
        prev_delivery_id="delivery-prior",
        transport_stall_count=2,
        stub_orca_ready=True,
        stub_check_fails=True,
    )
    assert state["action_taken"] == "escalated_spawn_failure"
    assert state["transport_stall_count"] == 3
    # issue #186: this escalation site (transport_stall_count >= 3) is the other of the two
    # call_status!=0 sites that a since-fixed structural bug (the shared log_self_recovery tail was
    # scoped inside the elif branch only, see self-recovery.md's inline comment at the `fi`
    # relocation) used to leave completely unlogged.
    assert len(state["self_recovery_events"]) == 1
    event = state["self_recovery_events"][0]
    assert event["terminal_status"] == "n/a"
    assert event["action_taken"] == "escalated_spawn_failure"


def test_successful_call_after_prior_stall_processes_normally(tmp_path):
    # transport_stall_count preset to 1 (as if the previous iteration stalled once and recovered);
    # this iteration's call succeeds outright -- must reset transport_stall_count to 0 and take the
    # ordinary non-timeout path (no action_taken set, prev_delivery_id parsed from the real result).
    state = _run_wait_loop(
        tmp_path,
        prev_delivery_id="delivery-prior",
        transport_stall_count=1,
        stub_check_fails=False,
    )
    assert state["check_call_count"] == 1
    assert state["action_taken"] == ""
    assert state["transport_stall_count"] == 0
    assert state["prev_delivery_id"] == "delivery-new"
    assert state["self_recovery_events"] == []
    assert state["spawn_failures"] == []


def test_stale_action_taken_from_a_prior_iteration_does_not_leak_into_a_plain_success_iteration(
    tmp_path,
):
    # Regression for an advisor-flagged gap in the #103 fix itself: the shared log_self_recovery
    # call (guarded on `[ -n "$action_taken" ]`) sits *outside* the call_status/timed_out branch
    # structure, so it runs every iteration regardless of which (if any) branch fired. Before this
    # fix, a plain-success iteration (neither branch entered) never touched action_taken at all, so
    # it silently carried forward whatever a *previous* iteration's outcome was -- e.g. "resumed_wait"
    # left over from an earlier timed-out-then-recovered iteration -- and would wrongly re-log that
    # stale outcome against this iteration's unrelated dispatch state. Presetting action_taken here
    # simulates exactly that leftover value; the loop must clear it unconditionally at its own top
    # before the plain-success path is reached, regardless of what an earlier iteration left behind.
    state = _run_wait_loop(
        tmp_path,
        prev_delivery_id="delivery-prior",
        stub_check_fails=False,
        stale_action_taken="resumed_wait",
    )
    assert state["action_taken"] == ""
    assert state["self_recovery_events"] == []
    assert state["spawn_failures"] == []
