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
so it is not relied on here. **Parent-side liveness confirmation is this `terminal read` probe, never
`heartbeat` messages** (issue #142) — a spawned worker's `heartbeat`/`status` sends to its parent Run
have no consumer here, but each one still interrupts the parent REPL with a runtime notification
regardless of `check --wait`'s own `--types` filter, costing a full-context turn for zero signal. Since
this file's own liveness mechanism never reads heartbeat, every dispatch spec built by a caller of this
loop should explicitly instruct the spawned worker not to send them (`orca-workflow-task`/
`orca-workflow-epic` SKILL.md's heartbeat-suppression contract). Recovery itself branches on how the
dispatch was created (Preconditions
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
- The worker terminal has already been dispatched via `orca orchestration worker-start --task <task_id>
  --worktree <selector> --terminal <handle> --run <run_id> --from <own handle> --json` — the sole
  primitive every caller uses today (see the caller table below). `orca-workflow-task` and
  `orca-workflow-epic` assign `DISPATCH_CREATED_VIA` explicitly before invoking this loop, at
  every one of their call sites (see `skills/orca-workflow-task/SKILL.md` §1 and
  `skills/orca-workflow-epic/SKILL.md` §3). `orca-task-runner` does not wire it; the `dead` case derives
  `worker-start` from `CALLING_SKILL` for that caller when the value reads empty (`CALLING_SKILL` is a
  caller-supplied constant it already sets, loop preamble below), which matches its only call site per the
  caller table. Dispatch creation is followed immediately by `dispatch-verify.md`'s
  positive-confirmation-and-retry procedure — required regardless of caller. A live test found the injected
  preamble sitting unsubmitted in the input composer for over two minutes despite a `stage:
  "input_accepted"` response; the primitive's acceptance response does not guarantee submission.
  (History: a second primitive, `task-create` + `dispatch --inject`, existed alongside `worker-start` and
  fed a `dispatch-inject` recovery sub-branch below — retired in issue #94 once every caller had migrated
  to `worker-start`; see that issue and the caller table's own note for what to restore if a topology ever
  needs it again.)

## Caller dispatch-creation paths

Each caller's dispatch-creation call site is a fixed constant for that call site — not something derived
per dispatch. `DISPATCH_CREATED_VIA` below is what the `dead` case (`## The wait/recovery loop`) branches
on:

| skill | role | call site | `DISPATCH_CREATED_VIA` |
|---|---|---|---|
| `orca-workflow-task` | `task-runner` | §1 round 1 (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-task` | `evaluator` | §1 round 1 (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-task` | `contract-round` | §1 round 2+ relay (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-epic` | `task-coordinator` | §3 (`task-create` + `worker-start`) | `worker-start` |
| `orca-task-runner` | `subtask-impl` | §5 (`worker-start`) | `worker-start` |

**현재 `dispatch-inject` caller는 하나도 없다** (issue #94 1단계, 2026-08-11). 이 실증을 근거로 issue #94
3단계(2026-08-13)가 `dead` 케이스의 inject sub-branch(~130줄)를 삭제했다 — 그 절차가 안고 있던 세 결함
(#121/#144/#145)은 죽은 코드의 버그였으므로 고치는 대신 moot로 close했다. 새 caller를 추가할 때
`dispatch --inject`를 고르지 말 것: Orca 공식 orchestration 가이드가 `worker-start`를 supervised
worker의 표준 경로로, `dispatch --inject`를 "composed start가 표현하지 못하는 topology에만 쓰는"
low-level 레시피로 규정한다(`orca skills get orchestration`, 1.4.180). 그런 topology가 실제로 필요해지면
이 삭제 이전 커밋에서 절차를 복원할 것 — SPEC_TEXT write/read/isolate triad와 단계별 검증은 다시
설계하기보다 되살리는 편이 낫다.

## The wait/recovery loop

Run this once per pending dispatch. `WORKER_HANDLE`/`TASK_ID`/`DISPATCH_ID`/`MY_HANDLE`/`RUN_ID`/
`DISPATCH_CREATED_VIA` are caller-supplied for that dispatch (see the caller table above for
`DISPATCH_CREATED_VIA`'s value per call site); `CALLING_SKILL` (`orca-task-runner`, `orca-workflow-task`,
or `orca-workflow-epic`), `ISSUE_NUM`, and `REPO_SLUG` (the 대상 repo identifier the invocation received,
passed down the spec chain — logging.md §1's required `repo` field, issue #158) are caller-supplied
constants for the whole session. Set
`prev_delivery_id=""` once, immediately before this loop's first iteration (loop-local, not
caller-supplied) — the loop code below both reads and updates it every iteration. A wave has
one pending-set entry per subtask, keyed by `task_id` (stable across retries — a `worker_abandon_retry`
changes only `dispatch_id`, so update the entry's `dispatch_id` in place rather than adding a second
entry; issue #94 stage 3 removed the one code path that used to break this stability, the inject
sub-branch's `task_recreate_retry`, which minted a brand-new `task_id`/terminal handle instead of reusing
the existing one). `retry_count` is likewise tracked per `task_id` in that same pending-set entry, not as
one shell scalar shared across a wave's concurrent subtasks. A contract round has exactly one entry.
`transport_stall_count` (issue #103) follows the same per-`task_id` pending-set-entry rule as
`retry_count`, for the same reason: `orca-task-runner` waits on several concurrent subtasks per wave, and
a bare shell scalar would either be shared across their iterations (one subtask's stall count
contaminating another's) or reset on every iteration and never reach its escalation threshold, depending
on how the caller's own loop is structured around this snippet.

**`SPEC_TEXT` no longer exists in this loop** (issue #94 stage 3, 2026-08-13, following the stage-1
migration on 2026-08-11 that stopped anyone from supplying it). It was only ever an input to the
`dispatch-inject` recovery sub-branch, which stage 3 deleted outright once proven live-unreachable — every
caller wires `DISPATCH_CREATED_VIA=worker-start`, and the `worker-start` sub-branch re-dispatches the
*same* `TASK_ID` (`worker-abandon` → `worker-start --retry-of`), so it never needed the original spec
text. The write/read/isolate sidecar triad this section used to specify for `SPEC_TEXT` (issue #112) is
gone along with that code; if a future caller legitimately needs `dispatch --inject` topology again,
restore both the procedure and its triad from before this commit rather than redesigning them from
scratch — they were hard-won across several regressions (issue #112's own eval reports).

```bash
# prev_delivery_id="" before this loop's first iteration -- nothing to ack yet. Every iteration
# after the first carries forward whatever this same variable held (see the tail of this loop):
# combining that batch's ack into the very call that waits for the next one is Orca's own
# documented idiom ("check --ack <id> --wait acknowledges, checks, and waits in one operation",
# `orca skills get orchestration`, confirmed live against 1.4.180) -- not two separate round trips.
# zsh does not word-split an unquoted ${var:+...} expansion the way bash/POSIX sh do (confirmed
# live: it collapses "--ack $id" into one malformed argv word), so this is an explicit if/else, not
# a one-line conditional flag (same portability constraint as scripts/log_dispatch.sh).
#
# This blocking call is wrapped in orca_call_with_retry (issue #103) -- an Orca-app-restart mid-wait
# ("The Orca runtime closed the connection before responding.") previously produced no error
# signature this loop recognized, so $result held garbage/empty JSON and `jq -r '.result.timedOut'`
# silently returned empty, which this loop's un-wrapped code then treated as timed_out=false --
# i.e. a total transport failure was silently read as "zero messages this batch", quietly dropping
# prev_delivery_id (see tail of this loop) with no escalation and no log trail.
#
# ORCA_RETRY_MAX_CYCLES=1 (scoped to only this call, confirmed live not to leak to the rest of this
# shell) deliberately disables the wrapper's own internal retry-with-full-timeout: with max_cycles=1,
# the wrapper's `[ "$cycle" -ge "$max_cycles" ]` check fires immediately after the first failure,
# before it would ever poll `orca status --json` or re-invoke the command -- so it does exactly one
# thing here: detect a matching failure signature and log one consistently-shaped
# spawn-failures.jsonl occurrence (this is what issue #103's report flagged as missing -- the two
# real incidents it cites were hand-labeled after the fact because this call was never wrapped).
# Retrying the identical `--timeout-ms 3600000` call at the wrapper level would silently restart the
# full 1-hour window on every retry, invisible to this loop's own `retry_count` accounting below (that
# counter already bounds total wait to ~3x this timeout before escalating) -- letting the wrapper also
# retry would multiply that bound without this loop ever seeing it happen.
#
# Cleared unconditionally here, before either branch below runs (issue #103 review): every branch
# that has an outcome assigns action_taken directly (resumed_wait, retried_enter,
# worker_abandon_retry, task_recreate_retry, escalated_spawn_failure, or "" for the transport-stall
# recover-and-reloop sub-case), but the *plain success* path (call_status=0 and timed_out=false)
# enters neither the `call_status -ne 0` nor the `timed_out = true` branch at all, so without this
# line it would silently carry forward whatever the *previous* iteration's outcome was --
# and the guarded `log_self_recovery` call below is reached unconditionally every iteration
# (outside the branch structure), so a stale non-empty value here would wrongly re-log a prior
# iteration's already-logged event against this iteration's (unrelated) dispatch state.
# new_dispatch_id needs the same unconditional clear (issue #186 fix): only the call_status!=0 and
# timed_out=true branches ever assign it (below), so the plain-success path used to leave it
# completely unset -- invisible until #186's `fi` relocation below made this tail run every
# iteration instead of only inside the `elif` branch. Now an unset var here is a `set -u` crash, and
# a stale non-empty value would wrongly advance DISPATCH_ID using a prior iteration's retry id
# against this iteration's unrelated dispatch state -- the same staleness risk action_taken has,
# just for the sibling field.
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
action_taken=""
new_dispatch_id=""
if [ -n "$prev_delivery_id" ]; then
  result="$(ORCA_RETRY_MAX_CYCLES=1 orca_call_with_retry "$CALLING_SKILL" "wait-loop" -- \
    orca orchestration check --run "$RUN_ID" --ack "$prev_delivery_id" --wait \
    --types worker_done,escalation,question,decision_gate --timeout-ms 3600000 --json)"
  call_status=$?
else
  result="$(ORCA_RETRY_MAX_CYCLES=1 orca_call_with_retry "$CALLING_SKILL" "wait-loop" -- \
    orca orchestration check --run "$RUN_ID" --wait \
    --types worker_done,escalation,question,decision_gate --timeout-ms 3600000 --json)"
  call_status=$?
fi
if [ "$call_status" -ne 0 ]; then
  # The call itself failed (wrapper already logged+gave up above) -- do not compute timed_out from
  # $result, it is not valid JSON. Do not treat this the same as timed_out=true either: that branch's
  # first step is a worker liveness probe (`orca terminal read`), which would fail for the same
  # transport-down reason and could misclassify a perfectly healthy worker as "dead", wrongly firing
  # worker-abandon during what is actually an Orca app restart, not a stuck worker (issue #103 review).
  timed_out=""
  transport_stall_count=$(( ${transport_stall_count:-0} + 1 ))
else
  timed_out="$(printf '%s' "$result" | jq -r '.result.timedOut')"
  transport_stall_count=0   # a live call came back -- reset, this counter tracks *consecutive* stalls
fi

if [ "$call_status" -ne 0 ]; then
  # The check --wait call itself failed (transport down), not a normal timeout -- tested directly on
  # $call_status (still in scope from just above), not inferred from $timed_out being empty: a
  # successful call (call_status=0) whose JSON happens to be malformed in some other way would also
  # leave $timed_out empty, and that must not be routed here. Recover by polling Orca's own readiness (same bounded pattern the wrapper itself would
  # have used, but owned here so this loop's own counter -- not the wrapper's -- decides when to stop
  # and escalate) and re-issuing the identical call; do not touch retry_count (that counter is about
  # worker liveness, orthogonal to Orca runtime availability) and do not run the worker liveness probe
  # (see the comment above this call for why that probe is unsafe here). Same escalate-on-the-3rd-
  # occurrence cadence as retry_count's own convention above (2 recovery attempts, then escalate
  # instead of a 3rd), for the same reason: bound total time before handing off to a human -- the
  # threshold below reads `-ge 3` rather than retry_count's `-ge 2` only because this counter
  # increments *before* the check on the same iteration (so it already reads 3 on the would-be-3rd
  # stall), whereas retry_count increments *after* a completed recovery attempt and is checked at the
  # top of the *next* iteration (so it still reads 2, not 3, when that next attempt would be the 3rd).
  if [ "${transport_stall_count:-0}" -ge 3 ]; then
    terminal_status=n/a
    action_taken=escalated_spawn_failure
    # Orca itself hasn't come back after repeated attempts -- spawn-failures.md's grep-first
    # procedure, not a worker-recovery sub-branch (there is no worker-side problem here to recover).
  else
    n=0; ready=0
    while [ "$n" -lt 6 ]; do
      if [ "$(orca status --json 2>/dev/null | jq -r '.result.runtime.state // empty')" = "ready" ]; then
        ready=1
        break
      fi
      n=$((n + 1))
      sleep 5
    done
    if [ "$ready" -eq 0 ]; then
      terminal_status=n/a
      action_taken=escalated_spawn_failure
    else
      # Orca is back. Explicitly clear action_taken (not just "leave it unset" -- a prior loop
      # iteration may have set it, and this is a loop, so a stale non-empty value here would wrongly
      # satisfy the log_self_recovery guard below with a previous iteration's outcome) so that guard
      # correctly skips logging for this sub-case. retry_count and prev_delivery_id (tail of this
      # loop) both stay untouched, so the next iteration re-issues check --wait with the same --ack
      # (idempotent if it already landed server-side despite the dropped connection).
      terminal_status=n/a
      action_taken=""
    fi
  fi
elif [ "$timed_out" = "true" ]; then
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
        # orca-task-runner is the one caller that does not wire DISPATCH_CREATED_VIA per dispatch, and
        # its only call site is worker-start (see the caller table above) -- derive that from
        # CALLING_SKILL when the value reads empty. CALLING_SKILL is already a caller-supplied constant
        # for the whole session (loop preamble above). orca-workflow-task and orca-workflow-epic wire
        # DISPATCH_CREATED_VIA explicitly at every call site (skills/orca-workflow-task/SKILL.md §1,
        # skills/orca-workflow-epic/SKILL.md §3), so effective_dispatch_created_via is already non-empty
        # for them before the -z check runs. The former epic -> dispatch-inject derivation was removed
        # with issue #94 stage 1: epic now wires worker-start explicitly, and leaving the derivation in
        # would silently route a worker-start dispatch into the inject recovery sub-branch whenever the
        # explicit assignment was dropped.
        effective_dispatch_created_via="$DISPATCH_CREATED_VIA"
        if [ -z "$effective_dispatch_created_via" ] && [ "$CALLING_SKILL" = "orca-task-runner" ]; then
          effective_dispatch_created_via=worker-start
        fi
        if [ "$effective_dispatch_created_via" = "worker-start" ]; then
          # --- worker-start sub-branch ---
          orca orchestration worker-abandon --dispatch "$DISPATCH_ID" --json
          # Re-launch per the calling skill's own explicit launch template (fresh terminal), or reuse
          # the existing handle if it is a live process just not answering this dispatch.
          # --worktree active는 여기서 쓰지 않는다(issue #118 부록) -- --terminal과 함께 쓰면
          # selector_not_found로 항상 실패한다(orca-task-runner SKILL.md §0). <impl_handle>이 이미
          # 그 worktree에 고정된 터미널이므로 --worktree 자체가 불필요하다.
          new_result="$(orca orchestration worker-start --task "$TASK_ID" \
            --terminal "$NEW_OR_SAME_HANDLE" --retry-of "$DISPATCH_ID" --run "$RUN_ID" \
            --from "$MY_HANDLE" --json)"
          new_dispatch_id="$(printf '%s' "$new_result" | jq -r '.result.dispatchId')"
          # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
          action_taken=worker_abandon_retry
        else
          # effective_dispatch_created_via is not "worker-start" -- unset, empty, or an unrecognized
          # value. Every caller in the caller table above now wires "worker-start" explicitly (or,
          # for orca-task-runner, has it derived above), so this branch only fires for a caller not
          # yet in that table, or a typo -- there is no second recognized primitive to route to any
          # more. (Issue #94 stage 3 removed the ~130-line `dispatch-inject` recovery procedure that
          # used to live here -- task-create+terminal-create+dispatch--inject recreate -- once it was
          # proven live-unreachable: every wait-loop caller had migrated to `worker-start`, so that
          # path could never fire. Its own long-standing bugs -- #121 [pending-set identity never
          # followed the new task_id/terminal handle], #144 [no spec sidecar under the replacement
          # task_id], #145 [replacement identity never reached the log] -- were closed as moot rather
          # than fixed, since fixing dead code has no observable effect. If a topology that composed
          # `worker-start` genuinely cannot express ever needs `dispatch --inject` again, restore the
          # procedure from before this commit rather than reinventing it -- its SPEC_TEXT
          # write/read/isolate triad and staged-check discipline were hard-won.) Fail
          # closed here: no recovery is attempted. terminal_status stays "dead" (already assigned
          # above by the outer case from a real liveness probe -- that classification is accurate,
          # so there is no reason to override it to "n/a"; issue #183's 4th schema value is for
          # escalations that never ran a liveness probe at all, which this one did).
          action_taken=escalated_spawn_failure
        fi
        [ "$action_taken" != escalated_spawn_failure ] && retry_count=$(( ${retry_count:-0} + 1 ))
        ;;
    esac
  fi
fi
# issue #186 fix: the block below (log_self_recovery through the loop-back comment) must sit
# *outside* the `if call_status -ne 0 / elif timed_out = true` chain above -- this `fi` used to be
# the only one closing that chain, positioned after this whole tail instead of here, so the tail
# was silently scoped to the `elif` branch only and the `call_status != 0` (transport-stall)
# branch's two escalation sites could set action_taken=escalated_spawn_failure but never reach the
# log_self_recovery call below them.
# Log a self_recovery event exactly per logging.md's recipe, regardless of which branch was
# taken. DISPATCH_ID here is still the dispatch that timed out; new_dispatch_id is only
# non-empty when action_taken=worker_abandon_retry or action_taken=task_recreate_retry
# (logging.md's schema keeps both fields distinct so a late completion from the old dispatch
# can't be confused with the retry).
# Written via log_self_recovery(), never a hand-copied printf (issue #127: the printf this
# replaced always emitted new_dispatch_id/raw_action/schema_gap_issue as "%s", so valid-action
# records carried forbidden empty-string conditional fields, and a hand-typed action_taken typo
# bypassed the UNMAPPED_BRANCH safeguard). The helper validates action_taken against the
# canonical enum, omits empty conditional fields entirely, and picks the target file from
# --skill: orca-task-runner -> waves-<date>.jsonl (pass --wave-index <n> so it joins that
# wave's wave_start/wave_end records); orca-workflow-task/orca-workflow-epic ->
# assignments-<date>.jsonl (no wave concept, no --wave-index).
# Guarded on non-empty action_taken (issue #103's transport-stall branch above explicitly clears
# it for its "Orca came back within budget, just re-loop" sub-case): that sub-case isn't a
# self_recovery-schema event at all -- no worker-liveness decision was made, nothing for
# logging.md's schema to describe -- and it's already durably recorded at the spawn-failures.jsonl
# level by orca_call_with_retry itself (which orca-retro already consumes), so logging it again
# here under an invented/misapplied action_taken would be redundant at best and, if forced into an
# existing enum value like resumed_wait, actively misleading (that value specifically means "we
# probed the worker and found it alive" -- no worker probe happened here).
if [ -n "$action_taken" ]; then
  source ~/.agents/orca-workflows/scripts/log_dispatch.sh
  log_self_recovery --skill "$CALLING_SKILL" --issue "$ISSUE_NUM" --repo "$REPO_SLUG" --task-id "$TASK_ID" \
    --dispatch-id "$DISPATCH_ID" --terminal "$WORKER_HANDLE" --waited-ms 3600000 \
    --terminal-status "$terminal_status" --action-taken "$action_taken" \
    --new-dispatch-id "$new_dispatch_id" --raw-action "${raw_action:-}" \
    --schema-gap-issue "${schema_gap_issue:-}"
fi
# If a retry happened, this pending-set entry's dispatch_id moves forward now (see the opening
# paragraph above: "update the entry's dispatch_id in place"). The `worker_abandon_retry` sub-branch
# above is the only one that can set new_dispatch_id today (issue #94 stage 3 removed the inject
# sub-branch that used to also mint new_task_id/new_terminal_handle -- the identity-drift failure
# mode issue #121 tracked no longer has a code path that reaches it).
[ -n "$new_dispatch_id" ] && DISPATCH_ID="$new_dispatch_id"
[ "$action_taken" = escalated_spawn_failure ] && : # hand off to spawn-failures.md here; do not loop back.
# Loop back to the top (re-issue check --wait) unless escalated above.

# result.timedOut == "false": process every message in the batch.
# for msg in result.messages: worker_done -> remove this task_id from the pending set;
#                              escalation  -> route immediately (decision_gate reply, or escalate
#                                             to the coordinator) -- do not wait for the rest of the
#                                             pending set first;
#                              question/decision_gate -> relay to the caller/human, then reply via
#                                             `orca orchestration reply --id <msg_id> --body <answer> --json`
#                                             -- routes immediately, before worker_done's pending-set removal, same as escalation.

# Set what the *next* iteration's check --wait (top of this loop) must --ack. Whatever this
# iteration itself passed as --ack (if prev_delivery_id was non-empty) has already been applied
# server-side by this point -- ack happens before the wait portion of the same call, so this holds
# whether or not this iteration also timed out. Overwriting prev_delivery_id here, unconditionally,
# is therefore correct for both outcomes, not just the non-timeout path. The transport-failure case
# (call_status != 0, issue #103) is neither: $result is not valid JSON there, and whether this
# iteration's --ack was actually applied server-side before the connection dropped is unknown, so
# prev_delivery_id is left exactly as it was (untouched) -- the next iteration retries the same
# --ack, which is safe if it already landed (idempotent) and correct if it didn't.
if [ "$call_status" -ne 0 ]; then
  : # prev_delivery_id untouched -- see above
elif [ "$timed_out" = "true" ]; then
  prev_delivery_id=""
else
  prev_delivery_id="$(printf '%s' "$result" | jq -r '.result.deliveryId')"
fi
# if pending set non-empty: loop back to the top with the remaining task_ids (re-issue check --wait,
# never check --peek, for the next batch).
```

`--ack` is not optional: a bound Run replays the same unacknowledged delivery on every subsequent
`check`/`check --wait` call (confirmed live — an unacked stale message was replayed instead of the
awaited new one, `replayed:true`). Skipping it either reprocesses the same message forever or masks
the fact that the real event hasn't arrived yet.

**Never combine `--ack` with `--peek`, and never try to `--ack` a `--peek` response.**
`--peek` returns unread messages without marking them read, so its response carries no `deliveryId`
(confirmed live, Orca 1.4.178: `.result` keys are `count`/`messages`/`runId`/`acknowledged` only) —
there is no delivery to ack. Passing a message id (`msg_...`) instead fails closed with
`stale_delivery: "Delivery msg_... does not belong to this Run"`, not a partial success. Every
`--ack` this loop ever sends targets a `deliveryId` this same loop's own prior `check --wait`
returned (carried forward as `prev_delivery_id`) — never a `--peek` response, and never a message
id. `check --wait` is the only call in this loop that ever exposes a `deliveryId`; `--peek` is not
used anywhere in this loop's mandatory path. A caller that wants to inspect pending messages
without consuming them (outside this loop) may still use `check --peek` for that — it is a
legitimate read-only operation — but must never expect an ack target from its response (issue #134:
an earlier revision of this loop combined `--ack "<result.deliveryId>" --peek` on one line, which
silently discarded the peeked batch's ability to ever be acked and caused it to replay).

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
`schema_gap_issue=<추적 이슈 slug>`로 남긴다. `task_recreate_retry`는 issue #94 stage 3(2026-08-13)로
이 루프가 더 이상 만들어내지 않는다 — `logging.md`/`log_dispatch.sh`의 스키마에는 과거 로그를 위해
남아 있을 뿐이니, 새 코드가 이 값을 다시 만들어낼 이유로 삼지 말 것.

**Retry budget: 2** `worker_abandon_retry` attempts per `task_id` (matching `orca-task-runner` §6's
task-level-gate retry limit and `orca-workflow-task` §4's FAIL-retry limit). `task_recreate_retry` used
to share this budget before issue #94 stage 3 removed the sub-branch that produced it.

**1-hour (`--timeout-ms 3600000`) is a starting default**, spot-checked live only up to ~180 seconds
during the design investigation and once for ~10 minutes during implementation — not proven safe for a
full hour of connection/keepalive durability. A dropped `check --wait` before the configured timeout
(observed live, issue #103 — "The Orca runtime closed the connection before responding." mid app
auto-update) is now handled by this loop's own transport-stall branch above (`orca_call_with_retry`
wrapping the call + a dedicated `transport_stall_count`, distinct from worker-liveness `retry_count`);
the loop structure itself did not need to change beyond that. What remains open: a *silent* early
return with no error signature at all — `check --wait --timeout-ms 3600000` observed returning
`timedOut:true` after only ~10 minutes, with nothing for the transport-stall branch to detect since the
call itself succeeded — is a distinct, still-unfixed gap (issue #103 comment, 2026-08-11 recurrence,
studio-hevv/selah-android#20).

## `worker-release` (re-verified 2026-08-10, Orca 1.4.178 — no longer a rejected candidate)

`worker-release --dispatch <id>` (Orca 1.4.169+) archives a settled worker's output and closes its
terminal automatically — but only for terminals Orca itself spawned as part of the dispatch
(`worker-start --agent`, `ownershipState: "owned"`; an external, pre-created terminal attached via
`worker-start --terminal` instead gets `ownershipState: "external"` and `worker-release` is a no-op
on it, `state:"retained", reason:"external_terminal", archive:null, processAction:"none"` — confirmed
live).

**Both original objections are resolved. Neither model/effort nor permission-mode blocks adoption —
this is decided, not open for re-litigation.**

- **Model/effort**: `worker-start --agent` gained `--model <id>`/`--effort <level>` at Orca 1.4.176,
  still present at 1.4.178. Verified end-to-end: `worker-start --agent claude --model
  claude-haiku-4-5-20251001 --effort low` (2026-08-10, dispatch `ctx_0d26ff46702c`) produced
  `launch.effective` identical to `launch.requested` — the terminal's own model banner read "Haiku
  4.5", not the account default.
- **Permission-mode**: handled by Orca's account-level Agent-launch preset, not a per-dispatch flag —
  by design, decided 2026-08-08. With the account's Agent settings configured once (Claude: no forced
  `--advisor`; Codex: `--dangerously-bypass-approvals-and-sandbox`), a live `worker-start --agent codex
  --model gpt-5.6-terra --effort medium` launch reproduced `orca-task-runner` §3's exact required
  posture with zero flags. There is no `--permission-mode` flag on `worker-start`, none is expected,
  and its absence is not a blocker.

After that worker sent `worker_done`, `worker-release --dispatch ctx_0d26ff46702c` returned
`state:"released", processAction:"closed_agent_terminal", archive:{source:"transcript",status:"captured"}`,
and a subsequent `worker-read` on the same dispatch still returned the full transcript — a real
`worker_done` → `worker-release` round trip (not synthetic/chat-injected), closing the "happy path
never actually observed" gap from the 2026-08-08 investigation.

**Known characteristic, not a blocker**: the account preset is a GUI-only setting, unversioned and
unreadable from the CLI (no `orca settings` command exists). `orca-task-runner`'s launch templates
(`skills/orca-task-runner/SKILL.md`) currently still bake the permission posture into explicit
skill-owned argv per agent instead of using `--agent`+the account preset — that migration simply
has not been done yet, not because anything blocks it. If a future session picks it up, the account
preset already does the job (verified above); nothing else needs to happen first.
