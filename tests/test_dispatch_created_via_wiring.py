"""Doc-schema assertions for issue #112 (self-recovery.md's DISPATCH_CREATED_VIA/SPEC_TEXT wait-loop
inputs were never wired at orca-workflow-task's three dispatch-creation call sites, so a timed-out
dispatch there always fails closed to escalated_spawn_failure instead of attempting recovery).

Confirmed contract: CONTRACT_DIR/proposal-r3.json's draft_acceptance_criteria (ac1-ac7). ac6's
verification is a trigger-phrase audit (not a fixed literal list) per verdict-r2.json's plan_coverage
and ac_fidelity findings on ac6 -- a coordinate list that misses a stale sentence lets that sentence
contradict the wired code silently.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-workflow-task" / "SKILL.md"
SELF_RECOVERY_MD = REPO_ROOT / "orca-workflows" / "self-recovery.md"


# ---------------------------------------------------------------------------
# ac1 + ac2 -- DISPATCH_CREATED_VIA=dispatch-inject wired at each of the task-runner/evaluator
# blocks' own positions, not once via a single shared assignment reused by both.
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


def test_dispatch_created_via_dispatch_inject_wired_exactly_twice_in_disjoint_windows():
    text = SKILL.read_text()
    assert text.count("DISPATCH_CREATED_VIA=dispatch-inject") == 2
    task_runner_window = _task_runner_window(text)
    evaluator_window = _evaluator_window(text)
    assert task_runner_window.count("DISPATCH_CREATED_VIA=dispatch-inject") == 1
    assert evaluator_window.count("DISPATCH_CREATED_VIA=dispatch-inject") == 1


def test_dispatch_created_via_worker_start_wired_in_contract_round_window():
    text = SKILL.read_text()
    window = _contract_round_window(text)
    assert "DISPATCH_CREATED_VIA=worker-start" in window


# ---------------------------------------------------------------------------
# ac4 -- task-runner/evaluator wire SPEC_TEXT by reading back log_dispatch's own term-<handle>.jsonl
# sent.content record and immediately persisting it to a sidecar keyed by that dispatch's own task_id
# (spec-<task_id>.txt) -- never a shell scalar the two blocks' dispatches share (issue #112
# eval-report-a1 critical: a shared SPEC_TEXT= name reused across both blocks in one fenced block is
# exactly what self-recovery.md:81-94 forbids, regardless of what source the value is read from).
# ---------------------------------------------------------------------------


def test_spec_text_persisted_to_per_task_id_sidecar_after_own_log_dispatch_call():
    text = SKILL.read_text()
    task_runner_window = _task_runner_window(text)
    evaluator_window = _evaluator_window(text)

    for window in (task_runner_window, evaluator_window):
        assert '--spec-text "$spec_text"' in window
        # Anchor on the real assignment, not "SPEC_TEXT=" alone -- the surrounding prose comment on
        # the evaluator block also contains that bare substring ("이 블록의 SPEC_TEXT= 대입은 위...").
        spec_text_idx = window.index('SPEC_TEXT="$(jq')
        log_dispatch_idx = window.index('--spec-text "$spec_text"')
        assert spec_text_idx > log_dispatch_idx

        # jq -ers (slurp, so map() sees an array of the JSONL lines) with a type/length guard: a
        # missing sent record or non-string/empty content must fail the jq call outright, not
        # surface as the literal string "null" (issue #112 eval-report-a1 important 1).
        assert "jq -ers" in window
        assert 'type=="string"' in window
        assert "length>0" in window
        assert "jq -rs '" not in window  # the old ungated readback this replaces

        # The read value is persisted to a per-task_id sidecar, not left in the shared SPEC_TEXT name.
        # (The prose comment mentions the same filename earlier for exposition -- anchor on the real
        # redirect target, not the first occurrence of the bare string.)
        sidecar_idx = window.index('> "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"')
        assert sidecar_idx > spec_text_idx
        assert "chmod 600" in window

    # Each block reads back via its own terminal handle, not a variable shared between the two.
    assert "term-<run-handle>.jsonl" in task_runner_window
    assert "term-<evaluate-handle>.jsonl" in evaluator_window
    assert "term-<evaluate-handle>.jsonl" not in task_runner_window
    assert "term-<run-handle>.jsonl" not in evaluator_window

    # The readback is sourced from log_dispatch's own recorded sent record, not a new variable.
    assert 'direction=="sent"' in task_runner_window
    assert 'direction=="sent"' in evaluator_window


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
# ac4 (behavioral) -- issue #112 eval-report-a1 important 2: a text-schema test alone (order,
# handle-string presence, "sent" substring) still passes a shared-scalar-with-different-source
# implementation, because it never actually runs the two blocks' setup and checks which dispatch's
# text survives. Simulate both blocks' term-log fixtures and execute the real jq+sidecar snippets
# extracted from SKILL.md, in the same order they run in the real fenced block, and confirm each
# dispatch's own sidecar holds its own original text -- not the other's.
# ---------------------------------------------------------------------------


def _extract_spec_text_snippet(window: str, handle_placeholder: str, real_handle: str, real_task_id: str) -> str:
    # Anchor on the real assignment (`SPEC_TEXT="$(jq`), not just "SPEC_TEXT=" -- the surrounding
    # prose comment also contains the bare substring "SPEC_TEXT=" ("이 블록의 SPEC_TEXT= 대입은 위...").
    start = window.index('SPEC_TEXT="$(jq')
    end = window.index("fi\n", start) + len("fi\n")
    snippet = window[start:end]
    snippet = snippet.replace(f"term-{handle_placeholder}.jsonl", f"term-{real_handle}.jsonl")
    snippet = snippet.replace("spec-<task_id>.txt", f"spec-{real_task_id}.txt")
    return snippet


def test_spec_text_sidecar_two_dispatch_simulation_has_no_cross_contamination(tmp_path):
    import os
    import subprocess

    text = SKILL.read_text()
    task_runner_window = _task_runner_window(text)
    evaluator_window = _evaluator_window(text)

    fake_home = tmp_path / "home"
    logs_dir = fake_home / ".local" / "state" / "orca-workflows" / "logs"
    logs_dir.mkdir(parents=True)

    (logs_dir / "term-run-fake.jsonl").write_text(
        '{"ts":"2026-01-01T00:00:00Z","type":"meta"}\n'
        '{"ts":"2026-01-01T00:00:01Z","direction":"sent","content":"TASK-RUNNER-ORIGINAL-SPEC"}\n'
    )
    (logs_dir / "term-evaluate-fake.jsonl").write_text(
        '{"ts":"2026-01-01T00:00:00Z","type":"meta"}\n'
        '{"ts":"2026-01-01T00:00:01Z","direction":"sent","content":"EVALUATOR-ORIGINAL-SPEC"}\n'
    )

    task_runner_snippet = _extract_spec_text_snippet(
        task_runner_window, "<run-handle>", "run-fake", "task-A"
    )
    evaluator_snippet = _extract_spec_text_snippet(
        evaluator_window, "<evaluate-handle>", "evaluate-fake", "task-B"
    )

    # Run both blocks' snippets in one shell session, in the same order they execute in the real
    # fenced block (task-runner's setup, then evaluator's setup) -- this is what actually exercises
    # the shared-variable-name reuse the critical finding is about.
    script = "set -eu\n" + task_runner_snippet + "\n" + evaluator_snippet + "\n"
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "HOME": str(fake_home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    task_runner_sidecar = (logs_dir / "spec-task-A.txt").read_text()
    evaluator_sidecar = (logs_dir / "spec-task-B.txt").read_text()

    assert task_runner_sidecar == "TASK-RUNNER-ORIGINAL-SPEC"
    assert evaluator_sidecar == "EVALUATOR-ORIGINAL-SPEC"


def test_spec_text_sidecar_jq_guard_rejects_missing_sent_record(tmp_path):
    # issue #112 eval-report-a1 important 1: a meta-only term log (no sent record yet) must not
    # produce a sidecar containing the literal string "null".
    import os
    import subprocess

    text = SKILL.read_text()
    task_runner_window = _task_runner_window(text)

    fake_home = tmp_path / "home"
    logs_dir = fake_home / ".local" / "state" / "orca-workflows" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "term-run-fake.jsonl").write_text(
        '{"ts":"2026-01-01T00:00:00Z","type":"meta"}\n'
    )

    snippet = _extract_spec_text_snippet(task_runner_window, "<run-handle>", "run-fake", "task-A")
    result = subprocess.run(
        ["bash", "-c", "set -eu\n" + snippet],
        env={**os.environ, "HOME": str(fake_home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not (logs_dir / "spec-task-A.txt").exists()


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
        "`orca-workflow-task` wires `DISPATCH_CREATED_VIA` explicitly per dispatch instead of relying"
        in norm
    )
    assert "all three now reach the `dead` case's inject sub-branch" in norm


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


_ORCA_STUB = r'''
orca() {
  sub="$1 $2"
  printf '%s\n' "$sub" >> "$CALL_LOG"
  if [ "$sub" = "orchestration task-create" ]; then
    while [ $# -gt 0 ]; do
      if [ "$1" = "--spec" ]; then
        printf '%s' "$2" > "$SPEC_ARGV_FILE"
        break
      fi
      shift
    done
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


def _run_inject_subbranch(snippet: str, *, task_id: str, home, preset_spec_text: str = "") -> dict:
    # Stub out every `orca`/`uuidgen`/`sleep` call the inject sub-branch makes so it runs to completion
    # in milliseconds against fake JSON responses, while a real bash interpreter executes the doc's own
    # code verbatim (not a reimplementation of it).
    import os
    import subprocess

    call_log = home / "calls.log"
    spec_argv_file = home / "spec_argv.txt"
    action_taken_file = home / "action_taken.txt"
    call_log.write_text("")

    script = (
        "set -u\n"
        + _ORCA_STUB
        + f'CALL_LOG="{call_log}"\n'
        + f'SPEC_ARGV_FILE="{spec_argv_file}"\n'
        + f'TASK_ID="{task_id}"\n'
        + f'SPEC_TEXT="{preset_spec_text}"\n'
        + 'effective_dispatch_created_via="dispatch-inject"\n'
        + snippet
        + f'\nprintf %s "$action_taken" > "{action_taken_file}"\n'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return {
        "call_log": call_log.read_text(),
        "spec_argv": spec_argv_file.read_text() if spec_argv_file.exists() else None,
        "action_taken": action_taken_file.read_text() if action_taken_file.exists() else "",
    }


def _sidecar_home(tmp_path, task_id: str, content: str | None):
    home = tmp_path / "home"
    logs_dir = home / ".local" / "state" / "orca-workflows" / "logs"
    logs_dir.mkdir(parents=True)
    if content is not None:
        (logs_dir / f"spec-{task_id}.txt").write_text(content)
    return home


def test_self_recovery_inject_subbranch_delivers_sidecar_spec_verbatim_to_task_create(tmp_path):
    text = SELF_RECOVERY_MD.read_text()
    snippet = _inject_subbranch_snippet(text)
    home = _sidecar_home(tmp_path, "task-A", "TASK-RUNNER-ORIGINAL-SPEC")

    result = _run_inject_subbranch(snippet, task_id="task-A", home=home)

    assert "orchestration task-update" in result["call_log"]
    assert result["spec_argv"] == "TASK-RUNNER-ORIGINAL-SPEC"
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
# ac7 -- orca-set.version bump is covered by
# tests/test_log_enum_schema.py::test_orca_set_version_bumped and
# tests/test_contract_schema_fails_before_fix.py::test_orca_set_version_line1_is_v1_1_7.
# ---------------------------------------------------------------------------
