"""Doc-schema regression guard for the boot-quiesce gap this session found: `orca-workflow-task`
had the issue #84 fresh-REPL boot-quiesce check at both its round-1 spawn sites, but
`orca-workflow-epic` §3 (task-coordinator spawn) and `orca-workflow` §2 (retro spawn) stopped at
`terminal wait --for tui-idle` and injected immediately after -- the same unprotected window that
made `worker-start --agent codex` lose task prompts (issue #151), reachable here too since both
sites can resolve to a REPL provider with a heavy MCP boot sequence. This guards that both sites
now run the same cursor-scoped quiesce loop before `task-create`/`dispatch --inject`.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"
WORKFLOW_SKILL = REPO_ROOT / "skills" / "orca-workflow" / "SKILL.md"
BOOT_START = "# Pre-dispatch boot-quiesce (issue #84)"
BOOT_END = "# End pre-dispatch boot-quiesce"


def _ordered(text: str, *needles: str) -> None:
    positions = [text.index(n) for n in needles]
    assert positions == sorted(positions), f"expected order {needles}, got positions {positions}"


def test_epic_task_coordinator_site_has_boot_quiesce_before_dispatch():
    text = EPIC_SKILL.read_text()
    _ordered(
        text,
        "orca terminal wait --terminal <coord-handle> --for tui-idle --timeout-ms 60000 --json",
        BOOT_START,
        'boot_deadline=$(( $(date -u +%s) + 60 ))',
        "sleep 12",
        ".result.terminal.returnedLineCount",
        BOOT_END,
        "orca orchestration task-create --spec",
        "orca orchestration dispatch --task",
    )
    boot = text[text.index(BOOT_START):text.index(BOOT_END)]
    assert "<coord-handle>" in boot
    assert 'orca terminal read --terminal <coord-handle> --json)" || exit 1' in boot
    assert "spawn-failures.md" in boot
    assert "orca orchestration task-create" not in boot
    assert "orca orchestration dispatch" not in boot


def test_workflow_retro_site_has_boot_quiesce_before_dispatch():
    text = WORKFLOW_SKILL.read_text()
    # Unlike the epic/task-runner sites, retro's boot-quiesce comment block (and its fail-closed
    # `if orca_call_with_retry ... terminal wait ...; then`) wraps the wait itself, so BOOT_START
    # precedes the wait line here rather than following it.
    _ordered(
        text,
        BOOT_START,
        "orca terminal wait --terminal <retro-handle> --for tui-idle --timeout-ms 60000 --json",
        'boot_deadline=$(( $(date -u +%s) + 60 ))',
        "sleep 12",
        ".result.terminal.returnedLineCount",
        BOOT_END,
        "orca orchestration task-create --spec",
        "orca orchestration dispatch --task",
    )
    boot = text[text.index(BOOT_START):text.index(BOOT_END)]
    assert "<retro-handle>" in boot
    assert "orca orchestration task-create" not in boot
    assert "orca orchestration dispatch" not in boot


def test_workflow_retro_site_routes_quiesce_failure_to_retro_fail_not_exit_1():
    text = WORKFLOW_SKILL.read_text()
    boot = text[text.index(BOOT_START):text.index(BOOT_END)]
    # retro is best-effort (SKILL.md §2): unlike orca-workflow-task/orca-workflow-epic's boot-quiesce
    # sites, a quiesce-deadline miss here must not `exit 1` -- it must fall through to a RETRO_FAIL
    # outcome log and a normal exit, so one flaky retro spawn never fails the whole workflow.
    code_lines = [
        line for line in boot.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.strip() == "exit 1" for line in code_lines)
    after_boot = text[text.index(BOOT_END):]
    guard = 'if [ "$boot_quiesced" != "1" ]; then'
    guard_idx = after_boot.index(guard)
    fail_branch = after_boot[guard_idx + len(guard) : after_boot.index("else", guard_idx)]
    assert '"outcome":"RETRO_FAIL"' in fail_branch
    assert "orca orchestration task-create" not in fail_branch
    assert "orca orchestration dispatch" not in fail_branch


def test_epic_tui_idle_wait_fails_closed_before_boot_quiesce_runs():
    text = EPIC_SKILL.read_text()
    # A bare (unguarded) `terminal wait` lets boot-quiesce false-pass: a terminal whose provider
    # died at launch also produces returnedLineCount==0 immediately, so the first cursor-diff would
    # read as "quiesced" and inject into a dead shell (spawn-failures.md #37's failure shape).
    wait = "orca terminal wait --terminal <coord-handle> --for tui-idle --timeout-ms 60000 --json"
    wait_idx = text.index(wait)
    boot_idx = text.index(BOOT_START)
    guard_window = text[text.rfind("orca terminal create", 0, wait_idx):boot_idx]
    assert 'if ! orca_call_with_retry "orca-workflow-epic" "task-coordinator" -- \\' in guard_window
    assert guard_window.index('if !') < guard_window.index(wait)
    assert "exit 1" in guard_window[guard_window.index(wait):]


def test_workflow_retro_tui_idle_wait_failure_routes_to_retro_fail_not_boot_quiesce():
    text = WORKFLOW_SKILL.read_text()
    wait = "orca terminal wait --terminal <retro-handle> --for tui-idle --timeout-ms 60000 --json"
    boot_start_idx = text.index(BOOT_START)
    boot_end_idx = text.index(BOOT_END)
    window = text[boot_start_idx:boot_end_idx]
    assert wait in window
    # The wait itself is inside the `if orca_call_with_retry ... ; then` guard, so a failed/timed-out
    # wait skips the cursor-diff loop entirely and boot_quiesced stays 0 -- landing in the existing
    # RETRO_FAIL branch below, not treated as "quiesced" the way a bare wait would be.
    guard_idx = window.index('if orca_call_with_retry "orca-workflow" "retro" -- \\')
    wait_idx_in_window = window.index(wait)
    boot_deadline_idx = window.index('boot_deadline=$(( $(date -u +%s) + 60 ))')
    assert guard_idx < wait_idx_in_window < boot_deadline_idx
    assert "boot_quiesced=0" in window[:guard_idx]


def test_epic_and_workflow_boot_quiesce_calls_use_the_retry_wrapper():
    epic_text = EPIC_SKILL.read_text()
    epic_boot = epic_text[epic_text.index(BOOT_START):epic_text.index(BOOT_END)]
    epic_wrapper = 'orca_call_with_retry "orca-workflow-epic" "task-coordinator" -- \\\n  '
    assert epic_wrapper + "orca terminal read --terminal <coord-handle> --json" in epic_boot
    assert epic_wrapper + 'orca terminal read --terminal <coord-handle> --cursor "$cur" --json' in epic_boot

    workflow_text = WORKFLOW_SKILL.read_text()
    workflow_boot = workflow_text[workflow_text.index(BOOT_START):workflow_text.index(BOOT_END)]
    workflow_wrapper = 'orca_call_with_retry "orca-workflow" "retro" -- \\\n'
    assert workflow_wrapper + '    orca terminal read --terminal <retro-handle> --json' in workflow_boot
    assert (
        workflow_wrapper + '        orca terminal read --terminal <retro-handle> --cursor "$cur" --json'
        in workflow_boot
    )
