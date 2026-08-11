"""Doc-schema regression coverage for issue #113's fresh-REPL boot-quiesce wiring."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
BOOT_START = "# Pre-dispatch boot-quiesce (issue #84)"
BOOT_END = "# End pre-dispatch boot-quiesce"


def _task_runner_window(text: str) -> str:
    start = text.index('orca_call_with_retry "orca-workflow-task" "task-runner"')
    end = text.index("# evaluate 호출", start)
    return text[start:end]


def _evaluator_window(text: str) -> str:
    start = text.index('orca_call_with_retry "orca-workflow-task" "evaluator"')
    end = text.index("**Contract 협상 relay — 라운드 2+", start)
    return text[start:end]


def _assert_boot_quiesce_site(window: str, handle: str) -> None:
    wait = f"orca terminal wait --terminal {handle} --for tui-idle --timeout-ms 60000 --json"
    boot_start = window.index(BOOT_START)
    boot_end = window.index(BOOT_END)
    task_create = window.index("orca orchestration task-create")
    # issue #94 stage 1: these two sites attach the worker with worker-start, not dispatch --inject.
    dispatch = window.index("orca orchestration worker-start")

    assert window.index(wait) < boot_start < boot_end < task_create < dispatch

    boot = window[boot_start:boot_end]
    assert 'boot_deadline=$(( $(date -u +%s) + 60 ))' in boot
    assert f'boot_initial="$(orca_call_with_retry' in boot
    assert f'orca terminal read --terminal {handle} --json)" || exit 1' in boot
    assert "sleep 12" in boot
    assert f'orca terminal read --terminal {handle} --cursor "$cur" --json' in boot
    assert '.result.terminal.returnedLineCount' in boot
    assert 'cur="$(printf \'%s\' "$boot_initial" | jq -r \'.result.terminal.latestCursor\')"' in boot
    assert f'orca terminal read --terminal {handle} --cursor "$cur" --json)" || exit 1' in boot
    assert 'if [ "$(date -u +%s)" -ge "$boot_deadline" ]; then' in boot
    assert "spawn-failures.md" in boot
    assert (
        "# spawn-failures.md의 grep-first 절차를 따른다. task-create/worker-start로 진행하지 않는다.\n"
        "    exit 1"
    ) in boot
    assert "orca orchestration task-create" not in boot
    assert "orca orchestration worker-start" not in boot
    assert "orca orchestration dispatch" not in boot
    assert ".result.terminal.tail" not in boot
    assert "| grep" not in boot


def test_both_fresh_dispatch_sites_include_bounded_cursor_refresh_boot_quiesce():
    text = SKILL.read_text()
    _assert_boot_quiesce_site(_task_runner_window(text), "<run-handle>")
    _assert_boot_quiesce_site(_evaluator_window(text), "<evaluate-handle>")


def test_boot_quiesce_assertions_reject_each_required_site_element_mutation():
    text = SKILL.read_text()
    sites = (
        (_task_runner_window(text), "<run-handle>"),
        (_evaluator_window(text), "<evaluate-handle>"),
    )

    for window, handle in sites:
        _assert_boot_quiesce_site(window, handle)
        wait = f"orca terminal wait --terminal {handle} --for tui-idle --timeout-ms 60000 --json"
        boot = window[window.index(BOOT_START):window.index(BOOT_END)]
        for mutated in (
            window.replace(wait, "", 1),
            window.replace(boot, "", 1),
            window.replace('boot_deadline=$(( $(date -u +%s) + 60 ))', "", 1),
            window.replace(
                "# spawn-failures.md의 grep-first 절차를 따른다. task-create/worker-start로 진행하지 않는다.\n    exit 1",
                "# spawn-failures.md의 grep-first 절차를 따른다. task-create/worker-start로 진행하지 않는다.",
                1,
            ),
        ):
            try:
                _assert_boot_quiesce_site(mutated, handle)
            except (AssertionError, ValueError):
                pass
            else:
                raise AssertionError("required boot-quiesce mutation was not rejected")


def test_boot_quiesce_terminal_calls_use_the_retry_wrapper():
    text = SKILL.read_text()
    for window, handle, role in (
        (_task_runner_window(text), "<run-handle>", "task-runner"),
        (_evaluator_window(text), "<evaluate-handle>", "evaluator"),
    ):
        boot = window[window.index(BOOT_START):window.index(BOOT_END)]
        wrapper = f'orca_call_with_retry "orca-workflow-task" "{role}" -- \\\n  '
        assert wrapper + f"orca terminal read --terminal {handle} --json" in boot
        assert wrapper + f'orca terminal read --terminal {handle} --cursor "$cur" --json' in boot


def test_fresh_dispatch_waits_fail_closed_through_the_retry_wrapper():
    text = SKILL.read_text()
    for window, handle, role in (
        (_task_runner_window(text), "<run-handle>", "task-runner"),
        (_evaluator_window(text), "<evaluate-handle>", "evaluator"),
    ):
        wait = f"orca terminal wait --terminal {handle} --for tui-idle --timeout-ms 60000 --json"
        wait_index = window.index(wait)
        assert f'if ! orca_call_with_retry "orca-workflow-task" "{role}" --' in window[
            window.rfind("orca terminal create", 0, wait_index):wait_index
        ]


def _run_wait_failure(window: str, handle: str, tmp_path, *, guarded: bool) -> tuple[int, list[str]]:
    start = window.index('orca_call_with_retry "orca-workflow-task"')
    prefix = window[start:window.index(BOOT_END)]
    prefix = prefix.replace(handle, "terminal-fake").replace("<n>", "1")
    if not guarded:
        prefix = prefix.replace("if ! ", "", 1).replace("--json; then\n  exit 1\nfi", "--json", 1)
    calls = tmp_path / f"wait-{'guarded' if guarded else 'unguarded'}.calls"
    calls.write_text("")
    script = f'''\
orca_call_with_retry() {{
  printf 'wrapper\\n' >> "$CALLS"
  case "$*" in *"terminal wait"*) return 1 ;; esac
  shift 2
  [ "${{1:-}}" = "--" ] && shift
  "$@"
}}
orca() {{
  printf '%s %s\\n' "$1" "$2" >> "$CALLS"
  if [ "$1 $2" = "terminal read" ]; then
    for arg in "$@"; do
      [ "$arg" = "--cursor" ] && {{
        printf '{{"result":{{"terminal":{{"latestCursor":"cur1","returnedLineCount":0}}}}}}'
        return
      }}
    done
    printf '{{"result":{{"terminal":{{"latestCursor":"cur0","returnedLineCount":0}}}}}}'
    return
  fi
  printf '{{}}'
}}
sleep() {{ :; }}
date() {{ printf '0\\n'; }}
{prefix}
orca orchestration task-create
orca orchestration dispatch
'''
    result = subprocess.run(
        ["bash", "-c", script], env={**os.environ, "CALLS": str(calls)}, capture_output=True, text=True
    )
    return result.returncode, calls.read_text().splitlines()


def test_wait_wrapper_failure_stops_each_site_before_boot_reads_or_dispatch(tmp_path):
    text = SKILL.read_text()
    for window, handle in (
        (_task_runner_window(text), "<run-handle>"),
        (_evaluator_window(text), "<evaluate-handle>"),
    ):
        guarded_code, guarded_calls = _run_wait_failure(window, handle, tmp_path, guarded=True)
        assert guarded_code == 1
        assert guarded_calls == ["wrapper", "terminal create", "wrapper"]

        unguarded_code, unguarded_calls = _run_wait_failure(window, handle, tmp_path, guarded=False)
        assert unguarded_code == 0
        assert "terminal read" in unguarded_calls
        assert "orchestration task-create" in unguarded_calls
        assert "orchestration dispatch" in unguarded_calls


def _run_boot_quiesce(window: str, handle: str, mode: str, tmp_path) -> list[str]:
    boot = window[window.index(BOOT_START):window.index(BOOT_END)].replace(handle, "terminal-fake")
    if mode in {"exhausted", "wrapper_failed"}:
        boot = boot.replace('boot_deadline=$(( $(date -u +%s) + 60 ))', "boot_deadline=0")
    calls = tmp_path / f"{mode}.calls"
    calls.write_text("")
    script = f'''\
orca_call_with_retry() {{
  printf 'wrapper\\n' >> "$CALLS"
  [ "$MODE" = "wrapper_failed" ] && return 1
  shift 2
  [ "${{1:-}}" = "--" ] && shift
  "$@"
}}
orca() {{
  printf '%s %s\\n' "$1" "$2" >> "$CALLS"
  if [ "$1 $2" = "terminal read" ]; then
    for arg in "$@"; do
      [ "$arg" = "--cursor" ] && {{
        if [ "$MODE" = "quiet" ]; then
          printf '{{"result":{{"terminal":{{"latestCursor":"cur1","returnedLineCount":0}}}}}}'
        else
          printf '{{"result":{{"terminal":{{"latestCursor":"cur1","returnedLineCount":1}}}}}}'
        fi
        return
      }}
    done
    printf '{{"result":{{"terminal":{{"latestCursor":"cur0","returnedLineCount":0}}}}}}'
    return
  fi
  printf '{{}}'
}}
sleep() {{ :; }}
date() {{
  printf '60\\n'
}}
{boot}
orca orchestration task-create
orca orchestration dispatch
'''
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "MODE": mode, "CALLS": str(calls)},
        capture_output=True,
        text=True,
    )
    return result.returncode, calls.read_text().splitlines()


def test_boot_quiesce_runs_dispatch_only_after_quiet_output_and_stops_on_exhaustion(tmp_path):
    text = SKILL.read_text()
    for window, handle in (
        (_task_runner_window(text), "<run-handle>"),
        (_evaluator_window(text), "<evaluate-handle>"),
    ):
        quiet_code, quiet_calls = _run_boot_quiesce(window, handle, "quiet", tmp_path)
        assert quiet_code == 0
        assert "orchestration task-create" in quiet_calls
        assert "orchestration dispatch" in quiet_calls

        exhausted_code, exhausted_calls = _run_boot_quiesce(window, handle, "exhausted", tmp_path)
        assert exhausted_code == 1
        assert "orchestration task-create" not in exhausted_calls
        assert "orchestration dispatch" not in exhausted_calls

        wrapper_code, wrapper_calls = _run_boot_quiesce(window, handle, "wrapper_failed", tmp_path)
        assert wrapper_code == 1
        assert wrapper_calls == ["wrapper"]
