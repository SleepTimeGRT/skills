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
- The worker terminal has already been dispatched via one of two Orca primitives — every caller's own
  call site is fixed to exactly one of the two (see the caller table below), so which primitive applies
  to a given dispatch is a fact about that call site, not something this loop probes or guesses.
  `orca-workflow-task` and `orca-workflow-epic` assign `DISPATCH_CREATED_VIA` explicitly before invoking
  this loop, at every one of their call sites (see `skills/orca-workflow-task/SKILL.md` §1 and
  `skills/orca-workflow-epic/SKILL.md` §3) — all of them `worker-start` since issue #94 stage 1.
  `orca-task-runner` does not wire it; the `dead` case derives `worker-start` from
  `CALLING_SKILL` for that caller when the value reads empty (`CALLING_SKILL` is a caller-supplied
  constant it already sets, loop preamble below), which matches its only call site per the caller table.
  `SPEC_TEXT` has no such derivation (there is no analogous per-caller constant for spec text) and no
  caller wires it any more — it was only ever an input to the `dispatch-inject` recovery sub-branch,
  which no caller reaches now:
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
| `orca-workflow-task` | `task-runner` | §1 round 1 (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-task` | `evaluator` | §1 round 1 (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-task` | `contract-round` | §1 round 2+ relay (`task-create` + `worker-start`) | `worker-start` |
| `orca-workflow-epic` | `task-coordinator` | §3 (`task-create` + `worker-start`) | `worker-start` |
| `orca-task-runner` | `subtask-impl` | §5 (`worker-start`) | `worker-start` |

**현재 `dispatch-inject` caller는 하나도 없다** (issue #94 1단계, 2026-08-11). 아래 `dead` 케이스의
inject sub-branch는 도달하는 caller가 없는 상태로 남아 있다 — 코드 삭제는 issue #94 3단계에서 한다.
새 caller를 추가할 때 `dispatch --inject`를 고르지 말 것: Orca 공식 orchestration 가이드가
`worker-start`를 supervised worker의 표준 경로로, `dispatch --inject`를 "composed start가 표현하지
못하는 topology에만 쓰는" low-level 레시피로 규정한다(`orca skills get orchestration`, 1.4.180).

## The wait/recovery loop

Run this once per pending dispatch. `WORKER_HANDLE`/`TASK_ID`/`DISPATCH_ID`/`MY_HANDLE`/`RUN_ID`/
`DISPATCH_CREATED_VIA`/`SPEC_TEXT` are caller-supplied for that dispatch (see the caller table above for
`DISPATCH_CREATED_VIA`'s value per call site); `CALLING_SKILL` (`orca-task-runner`, `orca-workflow-task`,
or `orca-workflow-epic`), `ISSUE_NUM`, and `REPO_SLUG` (the 대상 repo identifier the invocation received,
passed down the spec chain — logging.md §1's required `repo` field, issue #158) are caller-supplied
constants for the whole session. Set
`prev_delivery_id=""` once, immediately before this loop's first iteration (loop-local, not
caller-supplied) — the loop code below both reads and updates it every iteration. A wave has
one pending-set entry per subtask, keyed by `task_id` (stable across retries for the `worker_abandon_retry`
sub-branch — that retry changes only `dispatch_id`, so update the entry's `dispatch_id` in place rather
than adding a second entry. The inject sub-branch's `task_recreate_retry` is **not** actually stable this
way: it creates a brand-new `task_id` and terminal handle, and only `dispatch_id` gets moved into this
entry afterward — the entry's own `TASK_ID`/`WORKER_HANDLE` keep pointing at the dead original. Not fixed
here; see the warning below the loop code and issue #121). `retry_count` is likewise tracked per `task_id`
in that same pending-set entry, not as one shell scalar shared across a wave's concurrent subtasks. A
contract round has exactly one entry. `transport_stall_count` (issue #103) follows the same per-`task_id`
pending-set-entry rule as `retry_count`, for the same reason: `orca-task-runner` waits on several
concurrent subtasks per wave, and a bare shell scalar would either be shared across their iterations
(one subtask's stall count contaminating another's) or reset on every iteration and never reach its
escalation threshold, depending on how the caller's own loop is structured around this snippet.
`SPEC_TEXT` is this specific dispatch's own original spec, stored in that same pending-set
entry at dispatch-creation time — **never** a single shell variable a caller reuses across several
dispatches in one code block. A caller whose own dispatch-creation site assigns a shared `spec_text`
variable more than once before this loop runs (e.g. `orca-workflow-task` §1 round 1's task-runner and
evaluator dispatches, both created in the same fenced block) must keep each dispatch's
spec distinctly per pending-set entry.

**No caller supplies `SPEC_TEXT` any more** (issue #94 stage 1, 2026-08-11). It was only ever an input to
the `dead` case's `dispatch-inject` sub-branch, and the caller table above now has zero `dispatch-inject`
rows: `orca-workflow-task`'s `task-runner`/`evaluator` and `orca-workflow-epic`'s `task-coordinator` all
wire `DISPATCH_CREATED_VIA=worker-start` explicitly at their own call sites, and the `worker-start`
sub-branch re-dispatches the *same* `TASK_ID` (`worker-abandon` → `worker-start --retry-of`) instead of
recreating the task, so it never needs the original spec text. The `SPEC_TEXT` rules in this section and
in "The complete form, not just the forbidden form" below therefore bind nobody today; they are retained
because the inject sub-branch's code is still present (removal is issue #94 stage 3) and because a future
caller that legitimately needs `dispatch --inject` topology would have to satisfy them again.

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
3. **isolate** — guarantee a stale or wrong-dispatch value can never be silently consumed by a later read. A
   mutable per-dispatch sidecar file must be *deleted* once the dispatch is no longer pending (`worker_done`
   received or terminally failed), since a leftover file would otherwise be readable by a future dispatch
   that reuses the same key.

`orca-task-runner` §2 (write) / §5 (read via `cat`, then delete) is the reference implementation of this
triad for its `spec-<task_id>.txt` sidecar — steps 1–3 all apply to it, including deletion. A caller may
pick a different storage mechanism, but whichever it picks, all three steps must be present — write alone
does not change what this loop reads.

The term-log `sent`-record read-back mentioned above for `orca-workflow-epic`'s `task-coordinator` does
**not**, as written, satisfy step 3: the `sent` record's schema (`logging.md` §2) is `{ts, direction,
content}` — no `dispatch_id` or sequence field ties a record to one specific dispatch, so "reading it back"
can only mean the *latest* `sent` record for that `WORKER_HANDLE`, and a handle reused across retries would
then resolve to a different dispatch's spec. Treat that line as describing where the text physically lives,
not as an endorsed complete mechanism — a caller wiring `SPEC_TEXT` from the term-log still needs its own
answer to step 3 (e.g. capturing the exact log line number/offset at write time and re-reading that specific
line, never "whatever is last") before it satisfies this section. The sidecar triad remains the only
mechanism this document verifies end-to-end.

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
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
action_taken=""
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
  new_dispatch_id=""
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
          # --- inject sub-branch ---
          # This else covers every effective_dispatch_created_via value that is not exactly
          # "worker-start" -- including unset/empty and anything misspelled. Only the recognized
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
            # read -- the write/read/isolate triad's second leg ("The complete form, not just the
            # forbidden form" above). orca-workflow-task's task-runner/evaluator roles (the write leg)
            # already stash this dispatch's own spec text in spec-<task_id>.txt, keyed by this pending-set
            # entry's own TASK_ID; load it back into SPEC_TEXT here, immediately before the gate below
            # consumes it -- writing alone does not change what that gate reads (issue #112
            # eval-report-a2 critical). SPEC_TEXT="" first so a missing sidecar (a caller that has not
            # wired the write leg yet, e.g. orca-workflow-epic's task-coordinator per the paragraph above)
            # fails closed to an empty value instead of leaking whatever this shell last held, rather than
            # a stale value some other dispatch's own setup left behind under the old shared-scalar bug.
            # A caller using a different storage mechanism for step 1 substitutes its own read here.
            spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-$TASK_ID.txt"
            SPEC_TEXT=""
            [ -s "$spec_sidecar" ] && SPEC_TEXT="$(cat "$spec_sidecar")"
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
            # effective_dispatch_created_via is neither "worker-start" nor "dispatch-inject" -- unset,
            # empty, or an unrecognized value (every caller in the caller table above now wires a
            # recognized value, so this branch only fires for a caller not yet in that table, or a
            # typo). Fail closed: no recovery is attempted. terminal_status stays "dead" (already
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
  # paragraph above: "update the entry's dispatch_id in place").
  # WARNING (issue #121, not fixed here): for action_taken=task_recreate_retry (the inject sub-branch
  # above), recovery also created a *new* task_id/terminal handle (new_task_id/new_terminal_handle) --
  # this line only carries DISPATCH_ID forward. The entry's TASK_ID/WORKER_HANDLE keep pointing at the
  # dead original, so a later worker_done or liveness probe can miss the replacement worker's real
  # identity. See issue #121 for the full failure mode and the fix (move the entry's identity, not just
  # dispatch_id).
  [ -n "$new_dispatch_id" ] && DISPATCH_ID="$new_dispatch_id"
  [ "$action_taken" = escalated_spawn_failure ] && : # hand off to spawn-failures.md here; do not loop back.
  # If this escalation came from the inject sub-branch failing partway through (see that
  # sub-branch's own final-outcome comment above), the hand-off must include
  # $TASK_ID/$new_task_id/$new_terminal_handle so the orphan state (original task marked failed,
  # possibly-orphaned replacement task/terminal) is visible to whoever picks it up -- not just
  # "escalated_spawn_failure" with no identifiers.
  # Loop back to the top (re-issue check --wait) unless escalated above.
fi

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
`schema_gap_issue=<추적 이슈 slug>`로 남긴다.

**Retry budget: 2** `worker_abandon_retry`-or-`task_recreate_retry` attempts per `task_id` (a shared
budget across both sub-branches — a `dead`-case retry consumes the same `retry_count` regardless of
which sub-branch handled it), matching `orca-task-runner` §6's task-level-gate retry limit and
`orca-workflow-task` §4's FAIL-retry limit.

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
