# Orca Workflows Self-Recovery

> verified_at: 2026-08-07

Shared wait/recovery procedure for `orca-task-runner`/`orca-workflow`
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
so it is not relied on here. Recover via `worker-abandon` (fence, non-destructive) followed by
`worker-start --retry-of` (tracked retry) — never by reading the terminal and deciding the recovery
action by hand. Polling survives only as the rare, explicitly-logged fallback for the one thing Orca's
event system cannot tell you by construction (a worker that will never send anything because it's
dead) — never as the default.

## Preconditions

- The calling coordinator has already created and bound its own Run once, at the start of its own
  session: `orca orchestration run-create --objective "<...>" --from <own handle> --json`. Never reuse
  a *different* coordinator's Run (e.g. `orca-task-runner` must not reuse `orca-workflow`'s Run, and
  vice versa) — mixing Runs cross-delivers `worker_done`/`escalation` messages between unrelated
  mailboxes.
- The worker terminal has already been dispatched via `orca orchestration worker-start --task
  <task_id> --worktree <selector> --terminal <handle> --run <run_id> --from <own handle> --json`,
  followed immediately by `dispatch-verify.md`'s positive-confirmation-and-retry procedure — unchanged,
  and still required after `worker-start`. A live test found the injected preamble sitting unsubmitted
  in the input composer for over two minutes despite a `stage: "input_accepted"` response; `worker-start`
  reports acceptance, not submission.

## The wait/recovery loop

Run this once per pending dispatch. `WORKER_HANDLE`/`TASK_ID`/`DISPATCH_ID`/`MY_HANDLE`/`RUN_ID` are
caller-supplied for that dispatch; `CALLING_SKILL` (`orca-task-runner` or `orca-workflow`) and
`ISSUE_NUM` are caller-supplied constants for the whole session. A wave has one pending-set entry per
subtask, keyed by `task_id` (stable across retries — a `worker_abandon_retry` changes `dispatch_id`, so
update the entry's `dispatch_id` in place rather than adding a second entry). `retry_count` is likewise
tracked per `task_id` in that same pending-set entry, not as one shell scalar shared across a wave's
concurrent subtasks. A contract round has exactly one entry.

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
    # procedure instead of attempting a third worker-abandon/worker-start --retry-of.
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
        orca orchestration worker-abandon --dispatch "$DISPATCH_ID" --json
        # Re-launch per the calling skill's own explicit launch template (fresh terminal), or reuse
        # the existing handle if it is a live process just not answering this dispatch.
        new_result="$(orca orchestration worker-start --task "$TASK_ID" --worktree active \
          --terminal "$NEW_OR_SAME_HANDLE" --retry-of "$DISPATCH_ID" --run "$RUN_ID" \
          --from "$MY_HANDLE" --json)"
        new_dispatch_id="$(printf '%s' "$new_result" | jq -r '.result.dispatchId')"
        # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
        action_taken=worker_abandon_retry
        retry_count=$(( ${retry_count:-0} + 1 ))
        ;;
    esac
  fi
  # Log a self_recovery event exactly per logging.md's recipe, regardless of which branch was
  # taken. DISPATCH_ID here is still the dispatch that timed out; new_dispatch_id is only
  # non-empty when action_taken=worker_abandon_retry (logging.md's schema keeps both fields
  # distinct so a late completion from the old dispatch can't be confused with the retry).
  install -d -m 700 ~/.local/state/orca-workflows/logs
  target="$HOME/.local/state/orca-workflows/logs/waves-$(date -u +%F).jsonl"   # orca-task-runner
  # or: target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"   # orca-workflow
  printf '{"ts":"%s","event":"self_recovery","skill":"%s","issue":"%s","task_id":"%s","dispatch_id":"%s","terminal":"%s","waited_ms":3600000,"terminal_status":"%s","action_taken":"%s","new_dispatch_id":"%s"}\n' \
    "$(date -u +%FT%TZ)" "$CALLING_SKILL" "$ISSUE_NUM" "$TASK_ID" "$DISPATCH_ID" "$WORKER_HANDLE" \
    "$terminal_status" "$action_taken" "$new_dispatch_id" >> "$target"
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
#                                             to orca-workflow) -- do not wait for the rest of the
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

**Retry budget: 2** `worker_abandon_retry` attempts per `task_id`, matching `orca-task-runner` §6's
task-level-gate retry limit and `orca-workflow` §2d's FAIL-retry limit.

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
