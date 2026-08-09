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
  this writing, however, no caller's code actually assigns `DISPATCH_CREATED_VIA`/`SPEC_TEXT` before
  invoking this loop (wiring them in requires editing `skills/**`, out of this contract's scope — see
  issue #89 eval-report-a1 finding 1). Until that wiring lands, both variables read empty at runtime, and
  the `dead` case's fail-closed `else` branch (neither `worker-start` nor `dispatch-inject`) is what
  actually executes for every caller today, routing straight to `escalated_spawn_failure` instead of
  attempting either recovery sub-branch:
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
spec distinctly per pending-set entry. For the two `dispatch-inject` callers that actually need `SPEC_TEXT`
in the `dead` case (`orca-workflow-task` `task-runner`/`evaluator`, both §1 round 1 — see the caller table
above), `logging.md` §2's `log_dispatch` already writes that exact spec text into that dispatch's own
`term-<handle>.jsonl` as the `sent` record's `content` field, keyed by the terminal handle this loop
already has as `WORKER_HANDLE` — reading it back from there is one valid way to satisfy the requirement.
(`orca-task-runner` §2's `spec-<task_id>.txt` sidecar is a different, `worker-start`-only mechanism used
by a caller that can never reach this sub-branch — do not cite it here.) Any per-dispatch storage works as
long as it is not the shared variable itself (issue #89 eval-report-a1 finding 3 — a shared `$spec_text`
read here after a later dispatch has overwritten it recreates the wrong role's task).

```bash
result="$(orca orchestration check --run "$RUN_ID" --wait \
  --types worker_done,escalation --timeout-ms 3600000 --json)"
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
        if [ "$DISPATCH_CREATED_VIA" = "worker-start" ]; then
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
          # This else covers every DISPATCH_CREATED_VIA value that is not exactly "worker-start" --
          # including unset/empty and anything misspelled. Only the recognized "dispatch-inject"
          # value below actually runs the inject recovery procedure; every other value fails closed
          # to escalation instead of silently guessing (issue #89 eval-report-a1 finding 1: a
          # worker-start-created dispatch recovered via this procedure would skip the required
          # worker-abandon fence and risk duplicate execution).
          if [ "$DISPATCH_CREATED_VIA" = "dispatch-inject" ]; then
            # worker-abandon returns dispatch_not_found for a dispatch created via dispatch --inject
            # (confirmed live, issue #89) -- it only fences worker-start-created dispatches. Do not
            # call it here; there is no fence primitive for this path, so recovery goes straight to
            # replacing the stuck task. Every step below is checked before the next runs --
            # inject_recovery_ok tracks this so a failure anywhere escalates instead of logging a
            # false task_recreate_retry (finding 2).
            inject_recovery_ok=true
            orca orchestration task-update --id "$TASK_ID" --status failed --json || inject_recovery_ok=false
            # SPEC_TEXT must be this dispatch's own spec (see the loop preamble above) and non-empty --
            # an empty value here would create a replacement task with no instructions and dispatch a
            # worker at it, silently (issue #89 eval-report-a1 finding 3's failure mode in new clothes).
            [ -n "$SPEC_TEXT" ] || inject_recovery_ok=false
            if [ "$inject_recovery_ok" = true ]; then
              new_task_result="$(orca orchestration task-create --spec "$SPEC_TEXT" --retry-request "$(uuidgen)" --json)"
              # task-create's response shape is not documented by `orca orchestration task-create
              # --help` or `orca skills get orchestration --full` as of Orca 1.4.177, and this exact
              # call could not be tested live in this session (task-create requires a bound Run, and
              # the only side-effect-free way to test it is to actually create a task). `.result.task.id`
              # is not blind guessing, though: every other single-entity orchestration response checked
              # live this session follows the same "singular key wrapping the entity, entity has a plain
              # `id` field" shape -- `run-create` returns `.result.run.id`, `dispatch-show` returns
              # `.result.dispatch.id`. `task-list` (plural) returns each task's id at `.result.tasks[].id`
              # (no extra "task" wrapper per element), which is why the `.result.taskId` fallback is kept
              # below rather than dropped. Still UNVERIFIED for task-create specifically -- a future
              # session with a disposable task to create should confirm and drop this comment
              # (finding 4).
              new_task_id="$(printf '%s' "$new_task_result" | jq -r '.result.task.id // .result.taskId // empty')"
              [ -n "$new_task_id" ] || inject_recovery_ok=false
            fi  # task-create check
            if [ "$inject_recovery_ok" = true ]; then
              # Fresh terminal per the calling skill's own explicit launch template (its own §3
              # launch template -- same primitive/model/effort as the original dispatch). Target the
              # new terminal below, never the dead $NEW_OR_SAME_HANDLE (finding 4).
              new_terminal_result="$(orca terminal create --worktree active --title "<caller's own naming convention>" \
                --command "<caller's own launch template>" --json)"
              # agentTerminalHandle / startupTerminal.handle are the two field names orchestration's
              # own skill guide names for a create response, in that documented preference order
              # (`orca skills get orchestration --full`, "Messaging" section). If both are empty or
              # stale, that guide's own fallback is `orca terminal list --worktree active --json`
              # filtered by the --title set above.
              new_terminal_handle="$(printf '%s' "$new_terminal_result" | jq -r '.result.agentTerminalHandle // .result.startupTerminal.handle // empty')"
              [ -n "$new_terminal_handle" ] || inject_recovery_ok=false
            fi  # terminal create check
            if [ "$inject_recovery_ok" = true ]; then
              new_result="$(orca orchestration dispatch --task "$new_task_id" --to "$new_terminal_handle" \
                --retry-request "$(uuidgen)" --inject --json)"
              new_dispatch_id="$(printf '%s' "$new_result" | jq -r '.result.dispatchId // empty')"
              [ -n "$new_dispatch_id" ] || inject_recovery_ok=false
            fi  # re-dispatch check
            if [ "$inject_recovery_ok" = true ]; then
              # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
              action_taken=task_recreate_retry
            else
              action_taken=escalated_spawn_failure
            fi  # final inject-recovery outcome
          else
            # DISPATCH_CREATED_VIA is neither "worker-start" nor "dispatch-inject" -- unset, empty,
            # or an unrecognized value. Fail closed: no recovery is attempted. terminal_status stays
            # "dead" (already assigned above by the outer case -- that classification is accurate and
            # logging.md's schema only allows alive|stuck_draft|dead here, not a fourth "n/a" value).
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
  [ "$action_taken" = escalated_spawn_failure ] && : # hand off to spawn-failures.md here; do not loop back
  # Loop back to the top (re-issue check --wait) unless escalated above.
fi

# result.timedOut == "false": process every message in the batch, then ack.
# for msg in result.messages: worker_done -> remove this task_id from the pending set;
#                              escalation  -> route immediately (decision_gate reply, or escalate
#                                             to the coordinator) -- do not wait for the rest of the
#                                             pending set first.
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
`ask`(decision_gate)를 호출했는데, 이 문서의 `check --wait --types worker_done,escalation` 호출이
`question` 타입을 듣지 않아 코디네이터에게 전달되지 못하고, 워커 자신의 `ask` 타임아웃(기본 600s)까지
응답이 오지 않아 워커가 자체 판단으로 진행한 경우다(#524 세션에서 최초 관측, 근본 원인은 별도 추적:
issue #93 — 이 문서의 `--types worker_done,escalation` 인자 목록 자체는 이 값 도입으로 바뀌지 않는다).
기록 주체는 이 상황을 인지한 코디네이터이며, `waited_ms`는 이 루프의 3600000 고정값이 아니라 워커
자신의 `ask` 타임아웃 예산을 남긴다.

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
