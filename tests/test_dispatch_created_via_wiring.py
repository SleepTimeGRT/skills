"""Doc-schema assertions for issue #112 (self-recovery.md's DISPATCH_CREATED_VIA/SPEC_TEXT wait-loop
inputs were never wired at orca-workflow-task's three dispatch-creation call sites, so a timed-out
dispatch there always fails closed to escalated_spawn_failure instead of attempting recovery).

Confirmed contract: CONTRACT_DIR/proposal-r3.json's draft_acceptance_criteria (ac1-ac7). ac6's
verification is a trigger-phrase audit (not a fixed literal list) per verdict-r2.json's plan_coverage
and ac_fidelity findings on ac6 -- a coordinate list that misses a stale sentence lets that sentence
contradict the wired code silently.

Updated by issue #94 stage 1 (2026-08-11): the task-runner and evaluator sites now attach their worker
with `worker-start` instead of `task-create` + `dispatch --inject`, so they wire
`DISPATCH_CREATED_VIA=worker-start` and wire no `SPEC_TEXT` at all (the worker-start recovery sub-branch
re-dispatches the same task_id and never needs the original spec text). #112's SPEC_TEXT-sidecar
assertions are replaced by their inverse -- that no sidecar write remains at either site -- rather than
deleted, so a future re-introduction of the shared-scalar pattern still fails a test.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
EPIC_SKILL = REPO_ROOT / "skills" / "orca-workflow-epic" / "SKILL.md"
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"


# ---------------------------------------------------------------------------
# ac1 + ac2 -- DISPATCH_CREATED_VIA wired at each of the task-runner/evaluator blocks' own positions,
# not once via a single shared assignment reused by both. Value is worker-start since issue #94 stage 1.
# ---------------------------------------------------------------------------


def _task_runner_window(text: str) -> str:
    start = text.index('orca_call_with_retry "orca-workflow-task" "task-runner"')
    end = text.index("# evaluate 호출")
    return text[start:end]


def _evaluator_window(text: str) -> str:
    start = text.index('orca_call_with_retry "orca-workflow-task" "evaluator"')
    end = text.index("**Contract 협상 relay — 라운드 2+", start)
    return text[start:end]


def _contract_round_window(text: str) -> str:
    # Widened to the block's own closing fence (not just up to the start of its log_dispatch call)
    # per issue #112 eval-report-a1 minor 1: the two dispatch-inject blocks place their SPEC_TEXT
    # sidecar-write *after* their own log_dispatch call, so an "absent" check for this block must
    # cover that same post-log_dispatch zone too, or a stray SPEC_TEXT= placed there would slip past.
    start = text.index("worker-start --task <방금 만든 task_id> --worktree current")
    end = text.index("```", start)
    return text[start:end]


def test_dispatch_created_via_wired_per_block_and_no_inject_site_remains():
    text = SKILL.read_text()
    # issue #94 stage 1: no call site in this skill creates its dispatch via `dispatch --inject`.
    assert text.count("DISPATCH_CREATED_VIA=dispatch-inject") == 0
    assert "orca orchestration dispatch --task" not in text
    task_runner_window = _task_runner_window(text)
    evaluator_window = _evaluator_window(text)
    assert task_runner_window.count("DISPATCH_CREATED_VIA=worker-start") == 1
    assert evaluator_window.count("DISPATCH_CREATED_VIA=worker-start") == 1
    # Each block attaches its own worker with its own handle -- not one shared call reused by both.
    assert (
        "orca orchestration worker-start --task <task_id> --terminal <run-handle>"
        in task_runner_window
    )
    assert (
        "orca orchestration worker-start --task <task_id> --terminal <evaluate-handle>"
        in evaluator_window
    )


def test_epic_task_coordinator_wires_dispatch_created_via_explicitly():
    # issue #94 stage 1 deleted self-recovery.md's `CALLING_SKILL = orca-workflow-epic ->
    # dispatch-inject` derivation, so this site's explicit assignment is now the ONLY thing that keeps
    # its dead-case recovery reachable. Without it the value reads empty, falls through the one
    # remaining -z check, and the loop fails closed to escalated_spawn_failure with no recovery.
    text = EPIC_SKILL.read_text()
    assert text.count("DISPATCH_CREATED_VIA=worker-start") == 1
    assert "DISPATCH_CREATED_VIA=dispatch-inject" not in text
    assert "orca orchestration dispatch --task" not in text
    worker_start_idx = text.index(
        "orca orchestration worker-start --task <task_id> --terminal <coord-handle>"
    )
    assert text.index("DISPATCH_CREATED_VIA=worker-start") > worker_start_idx


def test_dispatch_created_via_worker_start_wired_in_contract_round_window():
    text = SKILL.read_text()
    window = _contract_round_window(text)
    assert "DISPATCH_CREATED_VIA=worker-start" in window


# ---------------------------------------------------------------------------
# ac4 (as amended by issue #94 stage 1) -- SPEC_TEXT is an input to the dead case's dispatch-inject
# recovery sub-branch only. With both sites on worker-start there is nothing to wire, so the assertion
# is the inverse of #112's: no SPEC_TEXT assignment and no per-task_id sidecar write may reappear at
# either site. #112 eval-report-a1's critical finding was that a shared SPEC_TEXT= name reused across
# both blocks in one fenced block violates self-recovery.md's per-pending-set-entry rule; keeping this
# check inverted means that exact shape still fails a test rather than silently returning.
# ---------------------------------------------------------------------------


def test_no_spec_text_wiring_remains_at_the_migrated_sites():
    text = SKILL.read_text()
    task_runner_window = _task_runner_window(text)
    evaluator_window = _evaluator_window(text)

    for window in (task_runner_window, evaluator_window):
        # log_dispatch still records this dispatch's own spec text -- that is logging.md §2's `sent`
        # record, a different mechanism from the recovery-input sidecar removed here.
        assert '--spec-text "$spec_text"' in window
        assert 'SPEC_TEXT="$(jq' not in window
        assert '> "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"' not in window
        assert "spec-<task_id>.txt" not in window


def test_contract_round_wires_dispatch_created_via_but_not_spec_text():
    text = SKILL.read_text()
    window = _contract_round_window(text)
    assert "DISPATCH_CREATED_VIA=worker-start" in window
    assert "SPEC_TEXT=" not in window


def test_contract_round_absence_check_is_not_vacuous_against_the_real_placement_pattern():
    # Regression guard for issue #112 eval-report-a1 minor 1: the OLD window (ending at the start of
    # this block's own log_dispatch call) would have missed a stray SPEC_TEXT= placed *after*
    # log_dispatch, which is exactly where the other two blocks legitimately place theirs. Splice that
    # exact placement into a copy of the contract-round block and confirm the widened window's absence
    # check would actually catch it (fails-before-fix evidence that this check has teeth).
    text = SKILL.read_text()
    log_dispatch_call = 'log_dispatch --skill "orca-workflow-task" --role "contract-round"'
    insertion_point = text.index(log_dispatch_call)
    # Insert right after the contract-round log_dispatch call's arguments end (its own closing line).
    spec_text_field_end = text.index('--spec-text "$spec_text"\n', insertion_point) + len(
        '--spec-text "$spec_text"\n'
    )
    mutated = (
        text[:spec_text_field_end]
        + 'SPEC_TEXT="$(echo leaked)"\n'
        + text[spec_text_field_end:]
    )
    window = _contract_round_window(mutated)
    assert "SPEC_TEXT=" in window  # the widened window catches the injected line


# ---------------------------------------------------------------------------
# ac4 (behavioral) -- issue #112's two executable simulations (cross-contamination between the two
# blocks' sidecars, and the jq guard against a "null" sidecar) were removed by issue #94 stage 1
# together with the snippets they executed. There is no sidecar-write code left at these sites to run;
# the text-level inverse assertion above is what now prevents that code from returning.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ac6 -- self-recovery.md no longer contains any sentence claiming orca-workflow-task is excluded
# from the DISPATCH_CREATED_VIA derivation or cannot reach a dead-case recovery sub-branch. Verified
# by a trigger-phrase audit (not a fixed coordinate list -- verdict-r2.json's finding on ac6 was that
# a coordinate list keeps missing sentences a pattern-class search would still catch).
# ---------------------------------------------------------------------------

STALE_EXCLUSION_TRIGGER_PHRASES = (
    "deliberately excluded",
    "deliberately left out",
    "not covered by the derivation",
    "cannot reach this sub-branch",
    "do not need `SPEC_TEXT` wired",
    "stay fail-closed to",
    "stays fail-closed to escalation",
    "actually reaches the `dead`",
)


def test_self_recovery_has_no_stale_orca_workflow_task_exclusion_claims():
    text = SELF_RECOVERY_MD.read_text()
    for phrase in STALE_EXCLUSION_TRIGGER_PHRASES:
        assert text.count(phrase) == 0, f"stale trigger phrase still present: {phrase!r}"


def test_self_recovery_documents_orca_workflow_task_wires_dispatch_created_via_explicitly():
    text = SELF_RECOVERY_MD.read_text()
    norm = re.sub(r"\s+", " ", text)
    assert (
        "`orca-workflow-task` and `orca-workflow-epic` assign `DISPATCH_CREATED_VIA` explicitly before "
        "invoking this loop, at every one of their call sites" in norm
    )
    # issue #94 stage 1: the caller table must state outright that no dispatch-inject caller is left,
    # so a reader cannot infer the inject sub-branch is still reachable from live callers.
    assert "현재 `dispatch-inject` caller는 하나도 없다" in norm
    assert "| `dispatch-inject` |" not in text


# ---------------------------------------------------------------------------
# The read-leg and inject-subbranch tests that used to live here (issue #112 eval-report-a2/a3/a4,
# pinning the dead-case dispatch-inject recovery procedure's SPEC_TEXT sidecar and its failure-mode
# guards) were removed by issue #94 stage 3: the procedure they exercised no longer exists in
# self-recovery.md (deleted as provably unreachable -- every wait-loop caller wires `worker-start`, see
# the caller table above). Deleting bugs' own regression tests alongside the dead code they tested is
# correct here, not a coverage loss -- there is nothing left to regress.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ac7 -- orca-set.version bump is covered by
# tests/test_log_enum_schema.py::test_orca_set_version_bumped and
# tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_7.
# ---------------------------------------------------------------------------
