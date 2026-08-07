# Event-Driven Wait via `check --wait` (Supersedes Part of 2026-08-06 Round-2+ Relay Design)

**Date:** 2026-08-07

**Scope:** `skills/orca-task-runner/SKILL.md` §5, `skills/orca-workflow/SKILL.md` §2a (round-2+ relay wait
only), `orca-workflows/dispatch-verify.md` (scope note), `orca-workflows/logging.md` (new `self_recovery`
event), `orca-workflows/spawn-failures.md` (#64 row wording), `tests/test_orca_skills.py` (enumerated below).

## 1. Purpose

Both `orca-task-runner` §5 and `orca-workflow` §2a document the same constraint: "`check --wait` 단독 대기
금지 — coordinator가 Orca 터미널 세션이면 `worker_done`이 check 큐에서 누락될 수 있다," and default to
`task-list`/`worker-show` polling on a 20-30s interval instead. This was written against an earlier Orca
orchestration scheduler. It costs real time in every wave and every contract round, and — because the
coordinator here is an LLM agent, not a daemon — every poll tick is also an agent turn, not just wall-clock
cost.

This design replaces that polling default with `orchestration check --wait`, based on live tests against the
current Orca runtime (`appVersion: 1.4.168`), not reasoning from `--help` text alone.

**Supersession note:** `docs/superpowers/specs/2026-08-06-contract-round-relay-design.md` §3 step 1 and its
"New candidate considered, rejected" paragraph both rest on the same now-disproven check-queue-miss claim,
and codified it into `orca-workflow` §2a's round-2+ protocol one day before this investigation. §5 of this
document supersedes that step 1 specifically; the rest of the 2026-08-06 design (new-task-per-round, no
`--deps`, `reportPath` as the path-only relay channel) is unaffected and stays as-is.

## 2. Empirical findings

All tests ran against a live Orca runtime in this repo's own worktree, coordinated from this Claude Code
session's own terminal (`term_2b4072f1-...`) — itself an Orca-managed terminal in the `sleeptimegrt-skills`
worktree, i.e. exactly the "coordinator running inside an Orca terminal session" configuration the retired
workaround was written for.

**Test 1 — manual sender, no ack.** Created a Run, a task, dispatched (plain `dispatch`, no `--inject`) to a
throwaway bash terminal, sent `orchestration send --type worker_done` by hand. `check --wait --timeout-ms
60000` returned in ~23s (dominated by the tester's own retry after an initial `--subject`-missing error, not
by the wait mechanism), `timedOut:false`, message delivered correctly.

**Test 2 — the `--ack` trap.** Started a real Claude Code worker via `worker-start --agent claude
--worktree new-child`, then called `check --wait` again on the same Run without acking Test 1's delivery.
It returned in 0.23s with `replayed:true`, re-delivering **Test 1's stale message**, not anything from the
new real agent. **A bound Run replays the same unacknowledged delivery on every subsequent `check`/`check
--wait` call.** `--ack <deliveryId>` after processing every batch is not optional — omitting it means the
loop can silently keep re-processing an old message forever, or (as here) mask the fact that the real event
hasn't arrived yet.

**Test 3 — `stage: "input_accepted"` ≠ submitted.** After acking Test 2's stale delivery, `check --wait
--timeout-ms 120000` timed out (`timedOut:true`, 8 keepalives, zero messages). The real agent's terminal
still showed the injected preamble sitting in its input composer, unsubmitted — `worker-start`'s returned
`stage: "input_accepted"` had not meant "the agent started working." A manual `orca terminal send --enter`
(no `--text`) unstuck it; the agent then began processing immediately. **This is the same issue
`dispatch-verify.md` (#43/#58) already documents for raw `dispatch --inject` — it reproduces identically
under `worker-start`.** Whichever dispatch composition is used, the positive-confirmation-and-retry-Enter
procedure stays mandatory; `worker-start`'s own "accepted" status is not a substitute.

**Test 4 — real agent, correct sequence.** After the manual Enter, `check --wait --timeout-ms 90000` returned
in 0.19s with `timedOut:false`, the real agent's `worker_done` correctly delivered.

**Test 5 — the discriminating test (`worker-start --terminal`).** Launched an agent terminal directly with
`terminal create --command "claude --model claude-sonnet-5 --dangerously-skip-permissions"` (i.e.
`orca-task-runner` §3's existing exact launch pattern, unchanged), in an explicit (non-`new-child`) worktree,
then called `worker-start --task <id> --worktree <that same explicit worktree> --terminal <that handle>`.
Result: `"action":"reused"` for both the worktree and the terminal — no new agent spawned, no new worktree
created — plus a `dispatchId` and (visible in the injected preamble) a `dcap_...` capability token, giving
`worker-show`/`worker-read` supervision on top of a launch this repo's skills fully control. `check --wait`
again delivered the resulting `worker_done` correctly (0.19s after the agent's shell command completed).

**Test 6 — `worker_done` via `check --wait` implies `completed`, not just "probably."** Cross-checked
`task-list`/`dispatch-show` for all three real-worker tasks after their `worker_done` messages were received:
in every case, `task.status`/`dispatch.status` were already `"completed"`, and `task.result.completedAt`
matched the message's timestamp exactly. Receiving a task's `worker_done` via `check`/`check --wait` is
sufficient evidence that task's dispatch has reached `completed` server-side — no confirming `task-list` read
is needed afterward. (This directly answers the open question the 2026-08-06 design didn't ask: the round-2+
gate's real requirement is "prior dispatch is `completed` so the next dispatch isn't rejected with `already
has an active dispatch`" — `worker_done` observed via `check --wait` already proves that.)

**Other confirmations:** `orca agent hooks status --json` shows hooks enabled for `claude` on this machine,
so `worker-read`'s default "hook-reported transcript" path is live rather than degraded to plain terminal
scraping. `orca orchestration coordinator-start` now returns "Retired: load the current orchestration
skill" — the legacy scheduler this workaround targeted no longer exists as a live code path. `orca-evaluate`
was checked and does not have an equivalent wait/poll site (its internal launches use `terminal wait --for
tui-idle` for boot-readiness only) — it is out of scope for this change.

## 3. Scope correction from the approved plan

The initially approved scope was "migrate dispatch composition to `worker-start` everywhere, not just the
wait mechanism." That is narrowed here to **only the two sites whose wait mechanism actually changes**:
`orca-task-runner` §5 (subtask dispatch) and `orca-workflow` §2a round-2+ relay dispatch. `orca-workflow`
§1d (retro) and the initial §2a task-runner/evaluator dispatch keep raw `dispatch --task ... --to ...
--inject` unchanged.

Reason: `tests/test_orca_skills.py` has literal-pattern assertions keyed to `dispatch --task ... --inject`
(`_DISPATCH_INJECT_RE`, `total == 8` site count, per-site logging.md/dispatch-verify.md pointer checks, the
`orca_call_with_retry`-wrapping bare-call scan). Converting a site with no polling problem to `worker-start`
breaks those tests for zero behavioral benefit — §1d's completion signal is a direct terminal read of the
retro summary (a different, unaffected design), and the initial §2a dispatches aren't a documented polling
site on their own (only the round-2+ gate is). Confining the swap to the two sites that actually change wait
behavior keeps the test churn proportional to the actual change.

## 4. The replacement loop

Each coordinator (an `orca-task-runner` session, and `orca-workflow`'s §2a relay) creates and binds its own
Run once, at the start of that role's work:

```bash
orca orchestration run-create --objective "<short description>" --from <own handle> --json
```

All subsequent dispatch/wait calls for that coordinator's own workers use this `run_id`. Dispatch to a
worker terminal already created (per each skill's existing launch template — unchanged) uses:

```bash
orca orchestration worker-start --task <task_id> --worktree <explicit worktree selector, e.g. active> \
  --terminal <impl_handle> --run <run_id> --from <own handle> --json
```

followed by the **unchanged** `dispatch-verify.md` positive-confirmation-and-retry procedure (Test 3 proved
this is still required after `worker-start`, not only after raw `dispatch --inject`).

Waiting for completion:

```
loop:
  result = orca orchestration check --run <run_id> --wait \
    --types worker_done,escalation --timeout-ms 3600000 --json
    # 1-hour timeout: inside it, this is one blocking RPC call — near-zero agent-turn cost.

  if result.timedOut:
    # The only "polling" in this design: a single liveness check, not a repeated tick.
    read = orca terminal read --terminal <worker_handle> --json
    log self_recovery event (schema below): waited_ms=3600000, terminal_status, action_taken
    if terminal looks alive: continue                      # straight back to check --wait
    else: existing spawn-failures.md procedure (dead shell / stuck unsubmitted draft)
    continue

  for msg in result.messages:                                # a --wait batch can hold >1 message
    if msg.type == worker_done: match task_id/dispatch_id, remove from this wave/round's pending set
    if msg.type == escalation:  route immediately (decision_gate reply, or escalate to orca-workflow) —
                                 do not wait for the rest of the pending set first
  orca orchestration check --run <run_id> --ack <result.deliveryId> --peek --json   # mandatory (Test 2)
  if pending set empty: break
```

`orca-task-runner` §5's pending set has one entry per subtask terminal in the current wave (N-way fan-in).
`orca-workflow`'s §2a round-2+ gate has exactly one entry (the terminal currently holding the active
dispatch) — per Test 6, receiving that one `worker_done` is itself sufficient; no follow-up `task-list` read
is needed.

**1-hour timeout is a starting default, not a validated constant** — none of the six tests above ran a
`--timeout-ms` above 180000. Whether Orca's connection/keepalive machinery holds a `check --wait` call open
for a full hour without dropping should be spot-checked once during implementation, not assumed from the
180s-scale tests here. If it doesn't hold, this is the one number in this design that needs revisiting; the
loop structure itself does not change.

**Logging carve-out for the self-recovery read:** the liveness `orca terminal read` above is, like
`dispatch-verify.md`'s existing probe, a bounded check of terminal aliveness — not a content read for
judgment. Per `logging.md` §2's carve-out precedent, it does not count as "already reads that terminal's
output" and should log no `recv` line.

## 5. `self_recovery` logging event (new)

Added to `orca-workflows/logging.md` §1, same precedent as `assign`/`outcome`/`wave_start`/`wave_end`:

```bash
printf '{"ts":"%s","event":"self_recovery","skill":"<skill>","issue":"<issue-num>","task_id":"<task_id>","dispatch_id":"<dispatch_id>","terminal":"<handle>","waited_ms":<n>,"terminal_status":"<alive|dead|stuck_draft>","action_taken":"<resumed_wait|retried_enter|escalated_spawn_failure>"}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
```

Written to `waves-<date>.jsonl` for `orca-task-runner` (add `wave_index` as an extra field, joinable with
existing `wave_start`/`wave_end` records) and to `assignments-<date>.jsonl` for `orca-workflow` (no
`wave_index`). Purpose: the 1-hour timeout above is an unvalidated guess: this log is what lets a future
session re-derive a real distribution (per subtask type, or per provider) instead of guessing again, and
lets `orca-retro`'s "repeated FAIL attributable to skill prose" lens notice if a particular signature
recurs — without that data existing yet, neither adjustment can be evidence-based.

## 6. Changes required

### 6a. `skills/orca-task-runner/SKILL.md` §5

Replace the dispatch line (`orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json`)
with the `worker-start --terminal <impl_handle> --worktree active ... --run <run_id> --json` form (§4).
Replace the "`check --wait` 단독 대기 금지... 기본 대기 = `task-list --brief --json` 상태 폴링" bullet with
the loop in §4 (delete the retired-scheduler reasoning outright per this repo's no-history-in-skills
convention — it belongs in this design doc, not in `SKILL.md` prose). Add a `run-create` step to §0 (once
per `orca-task-runner` session, binding this coordinator's own Run — distinct from whatever Run, if any, the
`orca-workflow` session that dispatched to it owns).

### 6b. `skills/orca-workflow/SKILL.md` §2a

Replace the round-2+ dispatch line (line 179, `dispatch --task <new_task_id> --to <handle> --inject --json`)
with `worker-start --terminal <handle> --worktree active ... --run <run_id> --json`. Replace the "`task-list
--json` 폴링(20-30s 간격)... `check --wait`을 1차 수단으로 쓰지 않는다" bullet (lines 185-187) with: wait via
`check --run <run_id> --wait --types worker_done,escalation --timeout-ms 3600000 --json` for the single
pending dispatch; per Test 6, the received `worker_done` is itself the completion signal — no follow-up
`task-list` read. Add a `run-create` step to §0 (once per `orca-workflow` invocation, distinct from whatever
Run `orca-task-runner`/`orca-evaluate` create for their own internal fan-out).

### 6c. `orca-workflows/dispatch-verify.md`

Widen the framing sentence ("Shared post-`dispatch --inject` verification procedure") to also name
`worker-start`, since Test 3 confirmed the same unsubmitted-draft failure mode reproduces there. No procedure
change — the bash is identical regardless of which command injected the text.

### 6d. `orca-workflows/spawn-failures.md`, issue #64 row

The row's `fix` column currently reads "poll `task-list` for the prior round's task reaching `completed`."
Replace with: wait via `check --wait` for that dispatch's `worker_done` (§4/§6b) — receiving it is itself
proof of `completed` (Test 6).

### 6e. `orca-workflows/logging.md`

Add the `self_recovery` event recipe (§5 above) to §1, alongside the existing `assign`/`outcome`/
`wave_start`/`wave_end` recipes.

## 7. Test changes required (`tests/test_orca_skills.py`)

Enumerated so no assertion silently drifts out of sync with the edited prose:

- **`test_orca_workflow_documents_round2_relay_protocol`** (line ~703): delete `assert "task-list" in
  text, "round-2+ completion check must poll task-list, not terminal read"` — this assertion directly
  enforces the disproven design. Replace with an assertion pinning the new mechanism, e.g. `assert
  "check --wait" in text` and `assert "3600000" in text` (or whatever the finalized timeout constant is)
  scoped to §2a, mirroring how this test already pins other load-bearing phrases.
- **`test_dispatch_site_count_and_section0_exception_shape`**: `total == 8` should drop to `6` — both
  converted sites (`orca-task-runner` §5's wave dispatch, `orca-workflow` §2a's round-2+ dispatch) stop
  matching `_DISPATCH_INJECT_RE` once they read `worker-start` instead of `dispatch --task ... --inject`.
  Recompute and confirm against the actually-edited text rather than trusting this arithmetic blind — the
  wave loop in `orca-task-runner` §5 dispatches to multiple terminals per wave but from one prose call site,
  so it should still count as exactly one regex match today, same as before.
- **`test_dispatch_sites_are_followed_by_logging_pointer`** / **`test_dispatch_sites_are_followed_by_
  dispatch_verify_pointer`**: these iterate `_dispatch_positions` (the `--inject` regex), so the two
  converted sites simply stop being scanned by these tests once they no longer match — add equivalent
  pointer coverage for `worker-start` sites (new regex or extend the existing one to match either verb) so
  the logging.md/dispatch-verify.md pointer requirement doesn't silently stop applying to the converted
  sites.
- **`_bare_wrapped_call_line_numbers`**'s `patterns` tuple: add `"orca orchestration worker-start --task"`
  so the two converted sites remain subject to the `orca_call_with_retry`-wrapping requirement.
- **`EXPECTED_RETRY_WRAP_COUNTS`**: both `orca-workflow` and `orca-task-runner` counts likely change (the
  round-2+ site drops its `task-list`-poll retry-wrap and gains an `--ack` retry-wrap; recompute after
  editing rather than predicting the delta here).
- **`test_orca_terminal_read_counts_per_skill_file`**: both expected counts move up by 1 — `orca-task-runner`
  from `1` to `2`, `orca-workflow` from `0` to `1` — since §4's self-recovery liveness read is added to both
  skills' wait loops (§6a, §6b), each contributing one new literal `orca terminal read` occurrence.
- New test recommended (not currently present): assert the retired-scheduler reasoning text ("coordinator가
  Orca 터미널 세션이면... 놓칠 수 있다") is absent from both `SKILL.md` files post-edit, mirroring
  `test_logging_no_longer_flags_round2_relay_as_unresolved`'s pattern for a resolved question.

## 8. Edge cases / open items

- **1-hour `check --wait` durability is unverified** (§4) — first real invocation after implementation should
  be watched for a dropped connection over a long wait, not assumed safe from the ≤180s tests here.
- **Run ownership across nested coordinators**: `orca-task-runner` and `orca-workflow` each create their own
  Run for their own fan-out; a `worker-start`/`check --wait` call must never accidentally reuse the *parent*
  coordinator's Run (e.g. `orca-workflow`'s), since that would mix an `orca-task-runner` wave's `worker_done`
  messages into `orca-workflow`'s own mailbox and vice versa. Each skill's §0 must state which Run it owns.
- **Test artifacts from this investigation** (`run_ae10c5a7b3fa` and its test tasks/deliveries) were
  acknowledged and their throwaway terminals/worktrees closed/removed during the session; the Run/task
  records themselves have no delete operation in the current `orca` CLI and are left as inert history,
  isolated by `run_id` from any real workflow run.

## 9. Validation

1. Recount and fix every test enumerated in §7 against the actually-edited text — do not hardcode predicted
   numbers in this document as if they were pre-verified.
2. Grep both edited `SKILL.md` files to confirm the retired "check --wait 단독 대기 금지" reasoning is fully
   removed, not merely annotated as outdated (per this repo's no-history-in-skills convention).
3. Before closing whatever issue tracks this change, run one real `orca-task-runner` wave (≥2 parallel
   subtasks) and one real `orca-workflow` round-2+ negotiation end-to-end, confirming: no `self_recovery`
   fires under normal completion latency, `--ack` is called exactly once per drained batch, and no stale
   message replay occurs across the run's lifetime.
4. `skills/orca-task-runner`, `skills/orca-workflow` require `bash scripts/deploy-skills.sh orca-task-runner
   orca-workflow` after commit. The `orca-workflows/` edits (dispatch-verify.md, logging.md,
   spawn-failures.md) go live on merge to main with no separate deploy step (symlink-tracks-main
   convention) — call this out when merging so the `skills/` deploy step isn't forgotten (same caution the
   2026-08-06 doc already flagged for its own cross-file scope).
