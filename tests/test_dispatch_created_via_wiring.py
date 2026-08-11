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
# issue #112 eval-report-a3 important 2 -- pin the issue #121 warning (this attempt's fix_direction
# explicitly allows deferring the pending-set-identity fix itself, but requires the newly-exposed gap not
# be left undocumented). Anchored so a later edit can't silently drop it.
# ---------------------------------------------------------------------------


def test_self_recovery_documents_issue_121_warning_before_dispatch_id_carry_forward():
    text = SELF_RECOVERY_MD.read_text()
    assert "issue #121" in text
    warning_idx = text.index("issue #121", text.index("WARNING (issue #121"))
    carry_forward_idx = text.index('[ -n "$new_dispatch_id" ] && DISPATCH_ID="$new_dispatch_id"')
    assert warning_idx < carry_forward_idx


# ---------------------------------------------------------------------------
# issue #112 eval-report-a2 critical -- the write leg (SKILL.md, covered above) alone does not change
# what self-recovery.md's dead-case inject sub-branch actually consumes: attempts 1-2 left the
# `[ -n "$SPEC_TEXT" ]` gate reading whatever value this shell last held, unchanged in substance from
# the shared-scalar bug. The read leg ("The complete form, not just the forbidden form" step 2) must
# load this dispatch's own spec text from its sidecar, keyed by TASK_ID, immediately before that gate.
# ---------------------------------------------------------------------------


def _read_leg_snippet(text: str) -> str:
    start = text.index('spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-$TASK_ID.txt"')
    marker = '[ -s "$spec_sidecar" ] && SPEC_TEXT="$(cat "$spec_sidecar")"\n'
    end = text.index(marker) + len(marker)
    return text[start:end]


def test_self_recovery_read_leg_is_wired_immediately_before_spec_text_gate():
    text = SELF_RECOVERY_MD.read_text()
    read_leg = _read_leg_snippet(text)
    gate = '[ -n "$SPEC_TEXT" ] || inject_recovery_ok=false'
    read_idx = text.index(read_leg)
    gate_idx = text.index(gate)
    assert read_idx < gate_idx
    # No unrelated SPEC_TEXT re-assignment sits between the read leg and the gate it feeds (prose
    # comments mentioning SPEC_TEXT are fine -- only a bare `SPEC_TEXT=` assignment would matter).
    assert "SPEC_TEXT=" not in text[read_idx + len(read_leg) : gate_idx]


def test_self_recovery_read_leg_prevents_stale_spec_text_reuse(tmp_path):
    import os
    import subprocess

    text = SELF_RECOVERY_MD.read_text()
    read_leg = _read_leg_snippet(text)

    fake_home = tmp_path / "home"
    logs_dir = fake_home / ".local" / "state" / "orca-workflows" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "spec-task-A.txt").write_text("TASK-RUNNER-ORIGINAL-SPEC")

    def run(include_read_leg: bool) -> str:
        script = 'set -eu\nTASK_ID="task-A"\nSPEC_TEXT="EVALUATOR-STALE-SPEC"\n'
        if include_read_leg:
            script += read_leg
        script += 'printf %s "$SPEC_TEXT"\n'
        result = subprocess.run(
            ["bash", "-c", script],
            env={**os.environ, "HOME": str(fake_home)},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert run(True) == "TASK-RUNNER-ORIGINAL-SPEC"
    # fails-before-fix: a write-only sidecar with no read-back leaves the gate reading whatever this
    # shell last held -- here, a different dispatch's stale spec text (issue #112 eval-report-a2 critical).
    assert run(False) == "EVALUATOR-STALE-SPEC"


# ---------------------------------------------------------------------------
# issue #112 eval-report-a3 important 1 -- the two tests above only check the read leg and the gate in
# isolation; neither actually runs the recovery consumer (task-update -> task-create --spec) that the
# gate exists to protect. A regression landing *between* the gate and task-create (or reordering
# task-update ahead of the gate) passed all 11 existing tests green (evaluator's live reproduction).
# Run the real inject sub-branch end to end with `orca` stubbed out, and assert the sidecar's own text
# reaches task-create's `--spec` argv verbatim -- then show each of the three mutations fix_direction
# names actually flips that assertion.
# ---------------------------------------------------------------------------


def _inject_subbranch_snippet(text: str) -> str:
    start = text.index("inject_recovery_ok=true\n")
    marker = "fi  # final inject-recovery outcome\n"
    end = text.index(marker) + len(marker)
    return text[start:end]


def _full_line(text: str, needle: str) -> str:
    idx = text.index(needle)
    line_start = text.rfind("\n", 0, idx) + 1
    line_end = text.index("\n", idx) + 1
    return text[line_start:line_end]


# $ORCA_STUB_FAIL/$ORCA_STUB_EMPTY (env-supplied, "orchestration task-update"-style "$1 $2" strings) let
# a test inject a failure at one specific call site without hand-rolling a second stub: FAIL exits
# nonzero (a transport/API failure), EMPTY exits 0 but omits the id field a caller extracts next (a
# call that "succeeds" but returns nothing usable) -- issue #112 eval-report-a4 important 2, so tests
# can prove the inject sub-branch's per-step `inject_recovery_ok` guards actually stop the chain instead
# of only ever seeing success responses.
_ORCA_STUB = r'''
orca() {
  sub="$1 $2"
  printf '%s\n' "$sub" >> "$CALL_LOG"
  if [ "$sub" = "orchestration task-create" ]; then
    for a in "$@"; do
      printf '%s\0' "$a"
    done > "$TASK_CREATE_ARGV_FILE"
  fi
  if [ "$sub" = "${ORCA_STUB_FAIL:-}" ]; then
    return 7
  fi
  if [ "$sub" = "${ORCA_STUB_EMPTY:-}" ]; then
    case "$sub" in
      "orchestration task-create") printf '{"result":{"task":{}}}' ;;
      "orchestration dispatch")    printf '{"result":{"dispatch":{}}}' ;;
      "terminal create")           printf '{"result":{"terminal":{}}}' ;;
      *)                           printf '{}' ;;
    esac
    return 0
  fi
  case "$sub" in
    "orchestration task-update")
      printf '{"result":{}}' ;;
    "orchestration task-create")
      printf '{"result":{"task":{"id":"new-task-fake"}}}' ;;
    "orchestration dispatch")
      printf '{"result":{"dispatch":{"id":"new-dispatch-fake"}}}' ;;
    "terminal create")
      printf '{"result":{"terminal":{"handle":"new-terminal-fake"}}}' ;;
    "terminal wait")
      printf '{}' ;;
    "terminal read")
      printf '{"result":{"terminal":{"latestCursor":"cur0","returnedLineCount":0}}}' ;;
    *)
      printf '{}' ;;
  esac
}
uuidgen() { printf 'fake-uuid'; }
sleep() { :; }
'''


def _run_inject_subbranch(
    snippet: str,
    *,
    task_id: str,
    home,
    preset_spec_text: str = "",
    stub_fail: str | None = None,
    stub_empty: str | None = None,
) -> dict:
    # Stub out every `orca`/`uuidgen`/`sleep` call the inject sub-branch makes so it runs to completion
    # in milliseconds against fake JSON responses, while a real bash interpreter executes the doc's own
    # code verbatim (not a reimplementation of it). TASK_ID/SPEC_TEXT/the stub-control knobs are passed
    # through the environment, never interpolated into the script text -- the fixtures this harness
    # exercises deliberately contain quotes/`$`/`;`/`|`/`&`, and string-formatting them into bash source
    # would corrupt the harness itself rather than testing self-recovery.md's own quoting.
    import os
    import subprocess

    call_log = home / "calls.log"
    task_create_argv_file = home / "task_create_argv.bin"
    action_taken_file = home / "action_taken.txt"
    call_log.write_text("")

    script = (
        "set -u\n"
        + _ORCA_STUB
        + 'effective_dispatch_created_via="dispatch-inject"\n'
        + snippet
        + f'\nprintf %s "$action_taken" > "{action_taken_file}"\n'
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "TASK_ID": task_id,
        "SPEC_TEXT": preset_spec_text,
        "CALL_LOG": str(call_log),
        "TASK_CREATE_ARGV_FILE": str(task_create_argv_file),
        "ORCA_STUB_FAIL": stub_fail or "",
        "ORCA_STUB_EMPTY": stub_empty or "",
    }
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    task_create_argv: list[str] | None = None
    if task_create_argv_file.exists():
        raw = task_create_argv_file.read_bytes()
        if raw:
            task_create_argv = raw.decode().split("\0")[:-1]  # trailing \0 leaves an empty tail element

    spec_argv = None
    if task_create_argv is not None and "--spec" in task_create_argv:
        spec_argv = task_create_argv[task_create_argv.index("--spec") + 1]

    return {
        "call_log": call_log.read_text(),
        "task_create_argv": task_create_argv,
        "spec_argv": spec_argv,
        "action_taken": action_taken_file.read_text() if action_taken_file.exists() else "",
    }


def _sidecar_home(tmp_path, task_id: str, content: str | None):
    home = tmp_path / "home"
    logs_dir = home / ".local" / "state" / "orca-workflows" / "logs"
    logs_dir.mkdir(parents=True)
    if content is not None:
        (logs_dir / f"spec-{task_id}.txt").write_text(content)
    return home


# A single unbroken token (the old fixture, "TASK-RUNNER-ORIGINAL-SPEC") can't distinguish `--spec
# "$SPEC_TEXT"` from `--spec $SPEC_TEXT` or `--spec "${SPEC_TEXT%% *}"` -- all three deliver the same
# one-word value. Whitespace/newlines force word-splitting to matter; the quotes/`;`/`|`/`&` prove the
# harness's own env-var plumbing (not string-formatted into bash source, see _run_inject_subbranch)
# survives content that would corrupt naive script interpolation (issue #112 eval-report-a4 important 1).
FIXTURE_SPEC_WITH_WHITESPACE_AND_SHELL_METACHARACTERS = (
    "line one two\n  $NOT_A_VAR 'quoted' \"dquoted\" ; | &"
)


def test_self_recovery_inject_subbranch_delivers_sidecar_spec_verbatim_to_task_create(tmp_path):
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    home = _sidecar_home(
        tmp_path, "task-A", FIXTURE_SPEC_WITH_WHITESPACE_AND_SHELL_METACHARACTERS
    )

    result = _run_inject_subbranch(snippet, task_id="task-A", home=home)

    assert "orchestration task-update" in result["call_log"]
    # (a) byte-identical to the sidecar's own text -- not just non-empty, not just its first word.
    assert result["spec_argv"] == FIXTURE_SPEC_WITH_WHITESPACE_AND_SHELL_METACHARACTERS
    # (b) delivered as exactly one argv: an unquoted `--spec $SPEC_TEXT` would word-split this fixture
    # (it embeds whitespace/newlines) into several, shifting --retry-request out of the next slot.
    argv = result["task_create_argv"]
    spec_idx = argv.index("--spec")
    assert argv[spec_idx + 1] == FIXTURE_SPEC_WITH_WHITESPACE_AND_SHELL_METACHARACTERS
    assert argv[spec_idx + 2] == "--retry-request"
    assert result["action_taken"] == "task_recreate_retry"


def test_self_recovery_inject_subbranch_gate_precedes_task_update_when_sidecar_missing(tmp_path):
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    home = _sidecar_home(tmp_path, "task-A", None)  # no sidecar -- SPEC_TEXT must not fall back to
    # whatever this shell already held (a different dispatch's own non-empty value, simulating a caller
    # that hasn't wired the write leg yet -- e.g. orca-workflow-epic's task-coordinator today).

    result = _run_inject_subbranch(
        snippet, task_id="task-A", home=home, preset_spec_text="EVALUATOR-STALE-SPEC"
    )

    # The precondition is a pure check with no side effect (issue #89 eval-report-a2 finding 3) -- a
    # missing sidecar must never let task-update run, let alone with the stale value.
    assert "orchestration task-update" not in result["call_log"]
    assert result["task_create_argv"] is None  # task-create itself never ran, not just --spec-less
    assert result["spec_argv"] is None
    assert result["action_taken"] == "escalated_spawn_failure"


def test_self_recovery_inject_subbranch_mutation_missing_read_leg_leaks_stale_spec_text(tmp_path):
    # Mutation 1 (fix_direction): deleting the read leg.
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    read_leg = _read_leg_snippet(text)
    assert read_leg in snippet
    mutated = snippet.replace(read_leg, "")
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(
        mutated, task_id="task-A", home=home, preset_spec_text="EVALUATOR-STALE-SPEC"
    )

    # fails-before-fix: without the read leg, whatever this shell already held reaches task-create
    # instead of the sidecar's own text (issue #112 eval-report-a2 critical).
    assert result["spec_argv"] == "EVALUATOR-STALE-SPEC"


def test_self_recovery_inject_subbranch_mutation_post_gate_reassignment_reaches_task_create(tmp_path):
    # Mutation 2 (fix_direction): SPEC_TEXT reassigned after the gate.
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    gate_line = _full_line(snippet, '[ -n "$SPEC_TEXT" ] || inject_recovery_ok=false')
    mutated = snippet.replace(gate_line, gate_line + 'SPEC_TEXT="MUTATED-AFTER-GATE"\n', 1)
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(mutated, task_id="task-A", home=home)

    # fails-before-fix: a reassignment landing between the gate and task-create silently overrides the
    # sidecar's own text (issue #112 eval-report-a3 important 1).
    assert result["spec_argv"] == "MUTATED-AFTER-GATE"


def test_self_recovery_inject_subbranch_mutation_gate_after_task_update_causes_side_effect(tmp_path):
    # Mutation 3 (fix_direction): the precondition checked after the first mutation instead of before
    # it -- the inverse of the ordering issue #89 eval-report-a2 finding 3 fixed.
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    gate_line = _full_line(snippet, '[ -n "$SPEC_TEXT" ] || inject_recovery_ok=false')
    task_update_line = _full_line(
        snippet, 'orca orchestration task-update --id "$TASK_ID" --status failed --json'
    )
    assert gate_line + task_update_line in snippet
    mutated = snippet.replace(gate_line + task_update_line, task_update_line + gate_line, 1)
    home = _sidecar_home(tmp_path, "task-A", None)  # no sidecar -- SPEC_TEXT stays empty

    result = _run_inject_subbranch(mutated, task_id="task-A", home=home)

    # fails-before-fix: with the gate moved after the mutation, task-update fires even though SPEC_TEXT
    # is empty (issue #112 eval-report-a3 important 1, mutation class 3).
    assert "orchestration task-update" in result["call_log"]


# ---------------------------------------------------------------------------
# issue #112 eval-report-a4 important 2 -- every test above sees only success responses from the `orca`
# stub, so it can't tell whether the inject sub-branch's per-step `inject_recovery_ok` guards (issue #89
# eval-report-a1 finding 2's safety property: a failed step must not be logged as a successful retry)
# are actually wired, or would silently keep going if a real Orca call failed or came back empty. Inject
# a failure at one call site via $ORCA_STUB_FAIL/$ORCA_STUB_EMPTY and confirm the chain stops there.
# ---------------------------------------------------------------------------


def test_self_recovery_inject_subbranch_task_update_failure_escalates_without_task_create(tmp_path):
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(
        snippet, task_id="task-A", home=home, stub_fail="orchestration task-update"
    )

    assert result["action_taken"] == "escalated_spawn_failure"
    assert "orchestration task-create" not in result["call_log"]


def test_self_recovery_inject_subbranch_mutation_missing_task_update_guard_creates_task_anyway(
    tmp_path,
):
    # Mutation (fix_direction convergence 1/2): `|| inject_recovery_ok=false` removed from the
    # task-update call self-recovery.md:254 -- a failed task-update would no longer stop the chain.
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    guarded = (
        'orca orchestration task-update --id "$TASK_ID" --status failed --json '
        "|| inject_recovery_ok=false; }"
    )
    assert guarded in snippet
    mutated = snippet.replace(
        guarded, 'orca orchestration task-update --id "$TASK_ID" --status failed --json; }', 1
    )
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(
        mutated, task_id="task-A", home=home, stub_fail="orchestration task-update"
    )

    # fails-before-fix: with the guard gone, a failed task-update is silently ignored and the chain
    # continues to create a replacement task anyway (issue #112 eval-report-a4 important 2).
    assert "orchestration task-create" in result["call_log"]


def test_self_recovery_inject_subbranch_dispatch_without_id_escalates(tmp_path):
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(
        snippet, task_id="task-A", home=home, stub_empty="orchestration dispatch"
    )

    # dispatch "succeeded" (exit 0) but returned no dispatch id -- must not be logged as a successful
    # retry (issue #89 eval-report-a1 finding 2).
    assert result["action_taken"] == "escalated_spawn_failure"


def test_self_recovery_inject_subbranch_mutation_naked_new_dispatch_id_guard_reports_success_anyway(
    tmp_path,
):
    # Mutation (fix_direction convergence 2/2): the new_dispatch_id guard self-recovery.md:320 weakened
    # to a naked `[ -n "$new_dispatch_id" ]` with no `|| inject_recovery_ok=false` consequence.
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    guarded = '[ -n "$new_dispatch_id" ] || inject_recovery_ok=false'
    assert guarded in snippet
    mutated = snippet.replace(guarded, '[ -n "$new_dispatch_id" ]', 1)
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(
        mutated, task_id="task-A", home=home, stub_empty="orchestration dispatch"
    )

    # fails-before-fix: with the guard defanged, a dispatch response with no id is still reported as a
    # successful retry (issue #112 eval-report-a4 important 2).
    assert result["action_taken"] == "task_recreate_retry"


# ---------------------------------------------------------------------------
# ac7 -- orca-set.version bump is covered by
# tests/test_log_enum_schema.py::test_orca_set_version_bumped and
# tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_7.
# ---------------------------------------------------------------------------
