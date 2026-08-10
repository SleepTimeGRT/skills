# Orca Workflows Self-Recovery

> verified_at: 2026-08-07

Shared wait/recovery procedure for `orca-task-runner`/`orca-workflow-task`/`orca-workflow-epic`
(`docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md`) — split out so both `SKILL.md`
files point here instead of each repeating the same loop (same precedent as `dispatch-verify.md`/
`logging.md`/`spawn-failures.md`).

## Principle

When detecting or recovering from a worker that isn't responding as expected, default to Orca's own
orchestration primitives for both detection and recovery — never a hand-rolled equivalent (ad hoc
bookkeeping, or falling back to polling as the primary mechanism just because the event path needs a
bit more care). Detect completion via `check --wait` (verified live against Orca 1.4.168/1.4.175).
Diagnose a timeout using the narrowest-scope tool already confirmed to carry a signal: a bounded
`terminal read` probe (the same one `dispatch-verify.md` already uses), not `worker-show`'s
`last_heartbeat_at` — every dispatch checked in the design investigation had `last_heartbeat_at: null`,
so it is not relied on here. Recovery itself branches on how the dispatch was created (Preconditions
below enumerates both paths, and the `dead` case's two sub-branches implement them): for a dispatch
created via `worker-start`, recover via `worker-abandon` (fence, non-destructive) followed by
`worker-start --retry-of` (tracked retry); for a dispatch created via `task-create` + `dispatch --inject`,
`worker-abandon` returns `dispatch_not_found` for that dispatch id (it only fences `worker-start`-created
dispatches, confirmed live — issue #89), so recovery instead marks the stuck task `failed` and
re-dispatches fresh via a new `task-create` + `dispatch --inject`. Neither path decides the recovery
action by reading the terminal and improvising by hand. Polling survives only as the rare,
explicitly-logged fallback for the one thing Orca's event system cannot tell you by construction (a
worker that will never send anything because it's dead) — never as the default.

## Preconditions

- The calling coordinator has already created and bound its own Run once, at the start of its own
  session: `orca orchestration run-create --objective "<...>" --from <own handle> --json`. Never reuse
  a *different* coordinator's Run (e.g. `orca-task-runner` must not reuse `orca-workflow-task`'s Run, and
  vice versa) — mixing Runs cross-delivers `worker_done`/`escalation` messages between unrelated
  mailboxes.
- The worker terminal has already been dispatched via one of two Orca primitives — every caller's own
  call site is fixed to exactly one of the two (see the caller table below), so which primitive applies
  to a given dispatch is a fact about that call site, not something this loop probes or guesses. As of
  this writing, no caller's code actually assigns `DISPATCH_CREATED_VIA` before invoking this loop
  (wiring it in per-dispatch requires editing `skills/**`, out of this contract's scope — see issue #89
  eval-report-a1 finding 1). This loop does not wait on that wiring for the two callers whose call site
  is already unambiguous, though: `CALLING_SKILL` is a caller-supplied constant these callers already set
  (loop preamble below), and per the caller table, `orca-task-runner` never uses anything but
  `worker-start` and `orca-workflow-epic` never uses anything but `dispatch-inject` — so the `dead` case
  derives `DISPATCH_CREATED_VIA`'s effective value from `CALLING_SKILL` for exactly those two callers
  when it reads empty, and both recovery sub-branches are reachable for them today without further
  wiring. `orca-workflow-task` is deliberately excluded from that derivation (its call sites are mixed —
  `task-runner`/`evaluator` via `dispatch-inject`, `contract-round` via `worker-start`, see the caller
  table), so for it `DISPATCH_CREATED_VIA` still reads empty and the `dead` case's fail-closed `else`
  branch (neither `worker-start` nor `dispatch-inject`) still executes, routing straight to
  `escalated_spawn_failure` instead of attempting either recovery sub-branch — until `orca-workflow-task`
  wires `DISPATCH_CREATED_VIA` explicitly per dispatch (issue #89 eval-report-a2 finding 4, tracked
  toward issue #94). `SPEC_TEXT` has no such derivation (there is no analogous per-caller constant for
  spec text) and must still be wired in by the two `dispatch-inject` callers that need it in the `dead`
  case, per the loop preamble below:
  - `orca orchestration worker-start --task <task_id> --worktree <selector> --terminal <handle> --run
    <run_id> --from <own handle> --json`, or
  - `orca orchestration task-create --spec <spec> --json` followed by `orca orchestration dispatch --task
    <task_id> --to <handle> --inject --json` (`task-create` + `dispatch --inject`, for short).
  Either way, dispatch creation is followed immediately by `dispatch-verify.md`'s
  positive-confirmation-and-retry procedure — unchanged, and still required after either primitive. A live
  test found the injected preamble sitting unsubmitted in the input composer for over two minutes despite
  a `stage: "input_accepted"` response; neither primitive's acceptance response guarantees submission.

## Caller dispatch-creation paths

Each caller's dispatch-creation call site is a fixed constant for that call site — not something derived
per dispatch. `DISPATCH_CREATED_VIA` (`worker-start` or `dispatch-inject`) below is what the `dead` case
(`## The wait/recovery loop`) branches on:

| skill | role | call site | `DISPATCH_CREATED_VIA` |
|---|---|---|---|
| `orca-workflow-task` | `task-runner` | §1 round 1 (`task-create` + `dispatch --inject`) | `dispatch-inject` |
| `orca-workflow-task` | `evaluator` | §1 round 1 (`task-create` + `dispatch --inject`) | `dispatch-inject` |
| `orca-workflow-task` | `contract-round` | §1 round 2+ relay (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-epic` | `task-coordinator` | §3 (`task-create` + `dispatch --inject`) | `dispatch-inject` |
| `orca-task-runner` | `subtask-impl` | §5 (`worker-start`) | `worker-start` |

## The wait/recovery loop

Run this once per pending dispatch. `WORKER_HANDLE`/`TASK_ID`/`DISPATCH_ID`/`MY_HANDLE`/`RUN_ID`/
`DISPATCH_CREATED_VIA`/`SPEC_TEXT` are caller-supplied for that dispatch (see the caller table above for
`DISPATCH_CREATED_VIA`'s value per call site); `CALLING_SKILL` (`orca-task-runner`, `orca-workflow-task`,
or `orca-workflow-epic`) and `ISSUE_NUM` are caller-supplied constants for the whole session. A wave has
one pending-set entry per subtask, keyed by `task_id` (stable across retries — a `worker_abandon_retry` or
`task_recreate_retry` retry changes `dispatch_id`, so update the entry's `dispatch_id` in place rather
than adding a second entry). `retry_count` is likewise tracked per `task_id` in that same pending-set
entry, not as one shell scalar shared across a wave's concurrent subtasks. A contract round has exactly
one entry. `SPEC_TEXT` is this specific dispatch's own original spec, stored in that same pending-set
entry at dispatch-creation time — **never** a single shell variable a caller reuses across several
dispatches in one code block. A caller whose own dispatch-creation site assigns a shared `spec_text`
variable more than once before this loop runs (e.g. `orca-workflow-task` §1 round 1's task-runner dispatch
at L95 and evaluator dispatch at L122, both created in the same fenced block) must keep each dispatch's
spec distinctly per pending-set entry. Three `dispatch-inject` callers exist per the caller table above
(`orca-workflow-task` `task-runner`/`evaluator`, both §1 round 1, and `orca-workflow-epic`
`task-coordinator`, §3) — but only `orca-workflow-epic` `task-coordinator` actually reaches the `dead`
case's inject sub-branch today: the `CALLING_SKILL`-based derivation above (`## The wait/recovery loop`)
resolves its effective `DISPATCH_CREATED_VIA` to `dispatch-inject` automatically, while
`orca-workflow-task`'s two roles stay fail-closed to `escalated_spawn_failure` until `orca-workflow-task`
wires `DISPATCH_CREATED_VIA` explicitly (issue #89 eval-report-a2 finding 4, tracked toward issue #94) —
so they cannot reach this sub-branch yet and do not need `SPEC_TEXT` wired for it in the meantime. Until
`orca-workflow-epic` wires `SPEC_TEXT` for its `task-coordinator` dispatches, this sub-branch's first gate
(`[ -n "$SPEC_TEXT" ]`, below) fails and the loop escalates — but it fails *before* the first mutation
(the `task-update --status failed` a few lines down), so that escalation carries zero side effects: no
task marked failed, no orphan (a direct consequence of moving this precondition ahead of the mutation,
see below and issue #89 eval-report-a2 finding 3). Once `orca-workflow-epic` wires it,
`logging.md` §2's `log_dispatch` already writes that exact spec text into that dispatch's own
`term-<handle>.jsonl` as the `sent` record's `content` field, keyed by the terminal handle this loop
already has as `WORKER_HANDLE` — reading it back from there is one valid way to satisfy the requirement.
(`orca-task-runner` §2's `spec-<task_id>.txt` sidecar is a different, `worker-start`-only mechanism used
by a caller that can never reach this sub-branch — do not cite it here.) Any per-dispatch storage works as
long as it is not the shared variable itself (issue #89 eval-report-a1 finding 3 — a shared `$spec_text`
read here after a later dispatch has overwritten it recreates the wrong role's task).

**The complete form, not just the forbidden form.** The paragraph above states what `SPEC_TEXT` wiring must
*not* do (reuse a shared variable across dispatches) but does not by itself specify what a *complete* wiring
looks like — and that gap let two implementation attempts on issue #112 replace the forbidden shared-scalar
with a per-dispatch file that was only ever *written*, never *read back* into `SPEC_TEXT` at the point this
loop actually consumes it (the `[ -n "$SPEC_TEXT" ]` gate below): the loop kept silently reading whatever
value was last assigned outside it, unchanged in substance from the shared-scalar bug (issue #112
eval-report-a1/a2, issue #114). A caller implementing per-dispatch `SPEC_TEXT` storage must wire all three
of:

1. **write** — at dispatch-creation time, store this dispatch's own spec text keyed by an identifier stable
   across retries (e.g. `task_id`);
2. **read** — immediately before this loop's `[ -n "$SPEC_TEXT" ]` gate, for *this* dispatch's pending-set
   entry, load the stored value into `SPEC_TEXT`;
3. **delete** — once the dispatch is no longer pending (`worker_done` received or terminally failed), remove
   the stored value so it cannot leak into an unrelated future dispatch.

`orca-task-runner` §2 (write) / §5 (read via `cat`, then delete) is the reference implementation of this
triad for its `spec-<task_id>.txt` sidecar. A caller may pick a different storage mechanism instead (the
term-log `sent`-record read-back described above for `orca-workflow-epic`'s `task-coordinator` is one such
alternative), but whichever mechanism it picks, all three steps must be present — write alone does not
change what this loop reads.

```bash
result="$(orca orchestration check --run "$RUN_ID" --wait \
  --types worker_done,escalation,question,decision_gate --timeout-ms 3600000 --json)"
timed_out="$(printf '%s' "$result" | jq -r '.result.timedOut')"

if [ "$timed_out" = "true" ]; then
  new_dispatch_id=""
  if [ "${retry_count:-0}" -ge 2 ]; then
    terminal_status=n/a
    action_taken=escalated_spawn_failure
    # Retry budget exhausted for this task_id -- go straight to spawn-failures.md's grep-first
    # procedure instead of attempting a third dead-case retry (either sub-branch).
  else
    # The only "polling" in this design: one liveness probe, not a repeated tick.
    read_json="$(orca terminal read --terminal "$WORKER_HANDLE" --json)"
    # Classify read_json's tail the same way dispatch-verify.md already does, and assign it:
    #   - the worker's own turn still visibly progressing               -> alive
    #   - our own injected spec_prefix still sitting unsubmitted         -> stuck_draft
    #   - dead shell / no process responding                             -> dead
    terminal_status="<alive|stuck_draft|dead, assigned from classifying read_json above>"
    case "$terminal_status" in
      alive)
        action_taken=resumed_wait
        ;;
      stuck_draft)
        orca terminal send --terminal "$WORKER_HANDLE" --enter --json
        action_taken=retried_enter
        ;;
      dead)
        # For the two callers whose dispatch-creation call site is unambiguous (see the caller table
        # above: orca-task-runner only ever uses worker-start; orca-workflow-epic only ever uses
        # dispatch-inject), derive DISPATCH_CREATED_VIA from CALLING_SKILL when the caller left it
        # unset -- CALLING_SKILL is already a caller-supplied constant for the whole session (loop
        # preamble above), so this does not require any skills/** wiring to land first (out of scope,
        # issue #94). orca-workflow-task's call sites are mixed (dispatch-inject in round 1,
        # worker-start in round 2+ -- see the caller table), so it is deliberately left out of this
        # derivation and stays fail-closed to escalation until it wires DISPATCH_CREATED_VIA
        # explicitly per dispatch (issue #89 eval-report-a2 finding 4).
        effective_dispatch_created_via="$DISPATCH_CREATED_VIA"
        if [ -z "$effective_dispatch_created_via" ] && [ "$CALLING_SKILL" = "orca-task-runner" ]; then
          effective_dispatch_created_via=worker-start
        fi
        if [ -z "$effective_dispatch_created_via" ] && [ "$CALLING_SKILL" = "orca-workflow-epic" ]; then
          effective_dispatch_created_via=dispatch-inject
        fi
        if [ "$effective_dispatch_created_via" = "worker-start" ]; then
          # --- worker-start sub-branch ---
          orca orchestration worker-abandon --dispatch "$DISPATCH_ID" --json
          # Re-launch per the calling skill's own explicit launch template (fresh terminal), or reuse
          # the existing handle if it is a live process just not answering this dispatch.
          new_result="$(orca orchestration worker-start --task "$TASK_ID" --worktree active \
            --terminal "$NEW_OR_SAME_HANDLE" --retry-of "$DISPATCH_ID" --run "$RUN_ID" \
            --from "$MY_HANDLE" --json)"
          new_dispatch_id="$(printf '%s' "$new_result" | jq -r '.result.dispatchId')"
          # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
          action_taken=worker_abandon_retry
        else
          # --- inject sub-branch ---
          # This else covers every effective_dispatch_created_via value that is not exactly
          # "worker-start" -- including unset/empty (for orca-workflow-task, which is deliberately
          # excluded from the derivation above) and anything misspelled. Only the recognized
          # "dispatch-inject" value below actually runs the inject recovery procedure; every other
          # value fails closed to escalation instead of silently guessing (issue #89 eval-report-a1
          # finding 1: a worker-start-created dispatch recovered via this procedure would skip the
          # required worker-abandon fence and risk duplicate execution).
          if [ "$effective_dispatch_created_via" = "dispatch-inject" ]; then
            # worker-abandon returns dispatch_not_found for a dispatch created via dispatch --inject
            # (confirmed live, issue #89) -- it only fences worker-start-created dispatches. Do not
            # call it here; there is no fence primitive for this path, so recovery goes straight to
            # replacing the stuck task. Every step below is checked before the next runs --
            # inject_recovery_ok tracks this so a failure anywhere escalates instead of logging a
            # false task_recreate_retry (finding 2).
            inject_recovery_ok=true
            # SPEC_TEXT must be this dispatch's own spec (see the loop preamble above) and non-empty --
            # an empty value here would create a replacement task with no instructions and dispatch a
            # worker at it, silently (issue #89 eval-report-a1 finding 3's failure mode in new clothes).
            # Checked first, before the first mutation below: it is a pure precondition with no side
            # effect of its own, so a failure here must not leave $TASK_ID marked failed for nothing
            # (issue #89 eval-report-a2 finding 3).
            [ -n "$SPEC_TEXT" ] || inject_recovery_ok=false
            [ "$inject_recovery_ok" = true ] && { orca orchestration task-update --id "$TASK_ID" --status failed --json || inject_recovery_ok=false; }
            if [ "$inject_recovery_ok" = true ]; then
              new_task_result="$(orca orchestration task-create --spec "$SPEC_TEXT" --retry-request "$(uuidgen)" --json)"
              # `.result.task.id` is verified live (Orca 1.4.177 -- `.result | keys == ["mutation",
              # "task"]`, `.result.task.id` present, `.result.taskId` ABSENT). The `.result.taskId`
              # fallback is kept anyway since `task-list` (plural) returns each task's id at
              # `.result.tasks[].id` (no "task" wrapper per element) -- a defensive fallback, not a
              # claim it fires for this call.
              new_task_id="$(printf '%s' "$new_task_result" | jq -r '.result.task.id // .result.taskId // empty')"
              [ -n "$new_task_id" ] || inject_recovery_ok=false
            fi  # task-create check
            if [ "$inject_recovery_ok" = true ]; then
              # Fresh terminal per the calling skill's own explicit launch template (its own §3
              # launch template -- same primitive/model/effort as the original dispatch). Target the
              # new terminal below, never the dead $NEW_OR_SAME_HANDLE (finding 4).
              new_terminal_result="$(orca terminal create --worktree active --title "<caller's own naming convention>" \
                --command "<caller's own launch template>" --json)"
              # `.result.terminal.handle` is the field this exact `terminal create --json` call
              # actually returns (verified live, Orca 1.4.177 -- `.result | keys == ["terminal"]`,
              # handle at `.result.terminal.handle`). The `agentTerminalHandle`/`startupTerminal.handle`
              # names below were misattributed in an earlier draft: those belong to `worktree create`
              # (agent-first) responses per `orca skills get orchestration --full`'s "Messaging"
              # section, not to `terminal create` -- kept only as a defensive fallback in case a future
              # runtime adds them to this response, never confirmed to fire for this call. If all three
              # are empty or stale, fall back to `orca terminal list --worktree active --json` filtered
              # by the --title set above.
              new_terminal_handle="$(printf '%s' "$new_terminal_result" | jq -r '.result.terminal.handle // .result.agentTerminalHandle // .result.startupTerminal.handle // empty')"
              [ -n "$new_terminal_handle" ] || inject_recovery_ok=false
            fi  # terminal create check
            if [ "$inject_recovery_ok" = true ]; then
              # Freshly launched REPL: `terminal wait --for tui-idle` alone is not a sufficient
              # precondition for `dispatch --inject` (dispatch-verify.md's "Pre-dispatch -- freshly
              # launched REPL" section, issue #84 -- codex keeps booting MCP servers past tui-idle,
              # and bracketed-paste text injected during that window is dropped, partially or wholly,
              # with no draft left in the composer for a post-dispatch Enter-only retry to recover).
              # Run tui-idle first, then dispatch-verify.md's cursor-scoped boot-quiesce loop (new
              # output settles to 0 lines) against $new_terminal_handle before ever dispatching into
              # it. $NEW_OR_SAME_HANDLE's original launch (worker-start sub-branch above, and every
              # non-recovery dispatch) goes through the calling skill's own launch template, which
              # already carries this same wait -- only this sub-branch inlines `terminal create`
              # directly and so must inline this check too (issue #89 eval-report-a3 finding 1).
              orca terminal wait --terminal "$new_terminal_handle" --for tui-idle --timeout-ms 60000 --json >/dev/null \
                || inject_recovery_ok=false
              if [ "$inject_recovery_ok" = true ]; then
                quiesced=false
                cur="$(orca terminal read --terminal "$new_terminal_handle" --json | jq -r '.result.terminal.latestCursor')"
                for _ in 1 2 3 4 5; do
                  sleep 12
                  new_lines="$(orca terminal read --terminal "$new_terminal_handle" --cursor "$cur" --json | jq -r '.result.terminal.returnedLineCount')"
                  [ "$new_lines" = 0 ] && { quiesced=true; break; }
                  cur="$(orca terminal read --terminal "$new_terminal_handle" --json | jq -r '.result.terminal.latestCursor')"
                done
                [ "$quiesced" = true ] || inject_recovery_ok=false
              fi  # boot-quiesce loop
            fi  # tui-idle + boot-quiesce check (issue #89 eval-report-a3 finding 1)
            if [ "$inject_recovery_ok" = true ]; then
              new_result="$(orca orchestration dispatch --task "$new_task_id" --to "$new_terminal_handle" \
                --retry-request "$(uuidgen)" --inject --json)"
              # `.result.dispatch.id` is what this exact `dispatch --inject --json` call actually
              # returns (verified live, Orca 1.4.177 -- `.result | keys == ["dispatch","injected",
              # "mutation"]`, id at `.result.dispatch.id`); `.result.dispatchId` is kept only as a
              # defensive fallback, never confirmed to fire for this call. (The worker-start
              # sub-branch's own `.result.dispatchId` above is a separate, unverified call site --
              # out of this fix's scope, ac4 requires it stay literally unchanged; see issue #89
              # eval-report-a2 finding 2.)
              new_dispatch_id="$(printf '%s' "$new_result" | jq -r '.result.dispatch.id // .result.dispatchId // empty')"
              [ -n "$new_dispatch_id" ] || inject_recovery_ok=false
            fi  # re-dispatch check
            if [ "$inject_recovery_ok" = true ]; then
              # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
              action_taken=task_recreate_retry
            else
              action_taken=escalated_spawn_failure
              # Orphan state at this point (task-update above only ran once the SPEC_TEXT precondition
              # passed): $TASK_ID is now `failed`, and $new_task_id/$new_terminal_handle are non-empty
              # only as far as their own step succeeded before the failure -- whichever of
              # task-create/terminal-create/dispatch ran and then a later step failed leaves that
              # entity orphaned (created, but no dispatch ever points at it). The hand-off below ("hand
              # off to spawn-failures.md here") must carry $TASK_ID, $new_task_id, and
              # $new_terminal_handle (each as empty string if that step never ran) so whoever picks up
              # the escalation knows exactly what to clean up or resume by hand -- this loop does not
              # attempt automatic compensation (issue #89 eval-report-a2 finding 3).
            fi  # final inject-recovery outcome
          else
            # effective_dispatch_created_via is neither "worker-start" nor "dispatch-inject" -- unset
            # (orca-workflow-task, not covered by the derivation above), empty, or an unrecognized
            # value. Fail closed: no recovery is attempted. terminal_status stays "dead" (already
            # assigned above by the outer case -- that classification is accurate and logging.md's
            # schema only allows alive|stuck_draft|dead here, not a fourth "n/a" value).
            action_taken=escalated_spawn_failure
          fi  # dispatch-inject vs unrecognized
        fi
        [ "$action_taken" != escalated_spawn_failure ] && retry_count=$(( ${retry_count:-0} + 1 ))
        ;;
    esac
  fi
  # Log a self_recovery event exactly per logging.md's recipe, regardless of which branch was
  # taken. DISPATCH_ID here is still the dispatch that timed out; new_dispatch_id is only
  # non-empty when action_taken=worker_abandon_retry or action_taken=task_recreate_retry
  # (logging.md's schema keeps both fields distinct so a late completion from the old dispatch
  # can't be confused with the retry).
  # orca-task-runner adds "wave_index":<n> to the JSON object below as an extra field (same
  # per-call-site extra-field convention logging.md §1 already uses for "assign" events) so it
  # joins with that wave's wave_start/wave_end records; orca-workflow-task/orca-workflow-epic omit it (no wave concept).
  install -d -m 700 ~/.local/state/orca-workflows/logs
  target="$HOME/.local/state/orca-workflows/logs/waves-$(date -u +%F).jsonl"   # orca-task-runner
  # or: target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"   # orca-workflow-task / orca-workflow-epic
  printf '{"ts":"%s","event":"self_recovery","skill":"%s","issue":"%s","task_id":"%s","dispatch_id":"%s","terminal":"%s","waited_ms":3600000,"terminal_status":"%s","action_taken":"%s","new_dispatch_id":"%s","raw_action":"%s","schema_gap_issue":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$CALLING_SKILL" "$ISSUE_NUM" "$TASK_ID" "$DISPATCH_ID" "$WORKER_HANDLE" \
    "$terminal_status" "$action_taken" "$new_dispatch_id" "${raw_action:-}" "${schema_gap_issue:-}" >> "$target"
  chmod 600 "$target"
  # If a retry happened, this pending-set entry's dispatch_id moves forward now (see the opening
  # paragraph above: "update the entry's dispatch_id in place").
  [ -n "$new_dispatch_id" ] && DISPATCH_ID="$new_dispatch_id"
  [ "$action_taken" = escalated_spawn_failure ] && : # hand off to spawn-failures.md here; do not loop back.
  # If this escalation came from the inject sub-branch failing partway through (see that
  # sub-branch's own final-outcome comment above), the hand-off must include
  # $TASK_ID/$new_task_id/$new_terminal_handle so the orphan state (original task marked failed,
  # possibly-orphaned replacement task/terminal) is visible to whoever picks it up -- not just
  # "escalated_spawn_failure" with no identifiers.
  # Loop back to the top (re-issue check --wait) unless escalated above.
fi

# result.timedOut == "false": process every message in the batch, then ack.
# for msg in result.messages: worker_done -> remove this task_id from the pending set;
#                              escalation  -> route immediately (decision_gate reply, or escalate
#                                             to the coordinator) -- do not wait for the rest of the
#                                             pending set first;
#                              question/decision_gate -> relay to the caller/human, then reply via
#                                             `orca orchestration reply --id <msg_id> --body <answer> --json`
#                                             -- routes immediately, before worker_done's pending-set removal, same as escalation.
orca orchestration check --run "$RUN_ID" --ack "<result.deliveryId>" --peek --json   # mandatory
# if pending set non-empty: loop back to the top with the remaining task_ids.
```

`--ack` is not optional: a bound Run replays the same unacknowledged delivery on every subsequent
`check`/`check --wait` call (confirmed live — an unacked stale message was replayed instead of the
awaited new one, `replayed:true`). Skipping it either reprocesses the same message forever or masks
the fact that the real event hasn't arrived yet.

The liveness `terminal read` above does not count as "already reads that terminal's output" for
`logging.md` §2's `recv`-logging rule (same carve-out as `dispatch-verify.md`'s own probe) — log no
`recv` line for it.

**`none_decision_gate_self_timed_out_worker_proceeded`** — 이 값은 위 wait/recovery 루프의 timeout
분기(`alive`/`stuck_draft`/`dead` 케이스)가 아니라, 별개 경로에서 기록된다: 디스패치된 워커가 스스로
`ask`(decision_gate)를 호출했는데, 코디네이터가 그 질문에 워커 자신의 `ask` 타임아웃(기본 600s) 안에
답하지 못해 워커가 자체 판단으로 진행한 경우다. #524 세션(issue #93 수정 이전)에서는 이 문서의
`check --wait --types worker_done,escalation` 호출이 `question`/`decision_gate` 타입 자체를 듣지 않아
질문이 코디네이터에게 전달조차 되지 못하는 것이 원인이었다 — 그 경로는 issue #93에서 `--types` 인자
목록을 `worker_done,escalation,question,decision_gate`로 갱신해 닫았다. 그러나 이 값 자체는
여전히 유효하다: 코디네이터가 질문을 수신하고도(예: caller/human 릴레이 지연) 워커의 `ask` 예산
안에 답하지 못하면 동일한 값이 다시 기록될 수 있다. 기록 주체는 이 상황을 인지한 코디네이터이며,
`waited_ms`는 이 루프의 3600000 고정값이 아니라 워커 자신의 `ask` 타임아웃 예산을 남긴다.

**`UNMAPPED_BRANCH`** — 위 5개 케이스(`resumed_wait`/`retried_enter`/`worker_abandon_retry`/
`task_recreate_retry`/`escalated_spawn_failure`), `none_decision_gate_self_timed_out_worker_proceeded`
어디에도 해당하지 않는 정상 분기를 만나면 즉석 문자열을 발명하지 말고, `sleeptimegrt-skills`에 스키마
구멍 이슈를 열고, 같은 write에서 `action_taken=UNMAPPED_BRANCH`, `raw_action=<실제 관측 문자열>`,
`schema_gap_issue=<추적 이슈 slug>`로 남긴다.

**Retry budget: 2** `worker_abandon_retry`-or-`task_recreate_retry` attempts per `task_id` (a shared
budget across both sub-branches — a `dead`-case retry consumes the same `retry_count` regardless of
which sub-branch handled it), matching `orca-task-runner` §6's task-level-gate retry limit and
`orca-workflow-task` §4's FAIL-retry limit.

**1-hour (`--timeout-ms 3600000`) is a starting default**, spot-checked live only up to ~180 seconds
during the design investigation and once for ~10 minutes during implementation — not proven safe for a
full hour of connection/keepalive durability. If a future session observes `connectionLost` or a
dropped `check --wait` before the configured timeout, that is the first thing to revisit; the loop
structure itself does not need to change.

## Rejected candidate: `worker-release`

`worker-release --dispatch <id>` (Orca 1.4.169+) archives a settled worker's output and closes its
terminal automatically — but only for terminals Orca itself spawned as part of the dispatch
(`worker-start --agent`, `ownershipState: "internal"`). A live test against a real, fully
`worker_done`-completed dispatch whose terminal this repo's own launch template had pre-created
(`terminal create --command "claude ..."`, then attached via `worker-start --terminal`) returned
`state:"retained", reason:"external_terminal", archive:null, processAction:"none"` — it did nothing.
Since both calling skills' explicit model/effort/permission-flag launch control (`orca-task-runner`
§0/§3) requires pre-creating the terminal themselves, every dispatch either skill makes is `external`,
and `worker-release` can never apply. Checked for a way around this rather than assuming none exists:
neither `worker-start --agent` nor `worktree create --agent` exposes a `--model`/`--effort`/
permission-mode equivalent — `--agent <id>` only selects which agent CLI to launch, with whatever that
CLI's own stored defaults are (confirmed live: a bare `--agent claude` spawn ran the process `claude
--dangerously-skip-permissions --model sonnet --effort high --advisor opus`, a fixed per-account
preset, not overridable per dispatch). There is no Orca-native spawn path that gives both full launch
control and `worker-release` eligibility — a structural trade-off in Orca's current feature surface,
not a gap in how either skill happens to call it. Do not re-propose adopting `worker-release` for
either skill without first changing this constraint.
