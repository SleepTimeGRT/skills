# Contract Round-2+ Relay Mechanism Design

**Date:** 2026-08-06

**Scope:** `skills/orca-workflow/SKILL.md` §2a, `skills/orca-task-runner/SKILL.md` §1, `skills/orca-evaluate/SKILL.md` §1, `orca-workflows/logging.md` §1 (the relay-dispatch note), `orca-workflows/spawn-failures.md` (two new rows)

## 1. Purpose

Issue #64: `orca-workflow` §2a describes contract negotiation as a ping-pong — task-runner proposes,
evaluator reviews, up to 2 rounds — but only documents the **first** dispatch to each of the two terminals.
It never says which `orca` command sends round 2+ to an already-dispatched terminal. In the observed
incident (issue #469 round 2), the session improvised: new `sent` events landed in the same terminal
without a new `terminal create`/`task-create`, and the assignment log recorded `task_id:""` /
`task_id:"terminal-send-fallback"` because there was no real task backing the relay.

Issue #64 explicitly declined to guess a fix and left three candidates open:

- (a) re-dispatch the same round-1 `task_id`
- (b) `task-create` a new task per round, to the same terminal
- (c) `orca terminal send --text --enter`, bypassing the task system

This design resolves the question with a live orca CLI test (two real terminals, real dispatches) rather
than reasoning from `--help` text alone, per user decision.

## 2. Empirical findings

Tested against a live Orca runtime (`orca status` ready) using a real `claude --model
claude-haiku-4-5-20251001` worker terminal, a task-create + dispatch --inject round 1, and round-2 attempts
against each candidate.

**(a) is impossible, confirmed by the CLI itself:**

```
orca orchestration dispatch --task <round1_task_id> --to <handle> --inject
→ {"ok":false,"error":{"code":"runtime_error",
    "message":"Task <id> is dispatched; only ready tasks can be dispatched"}}
```

`dispatch` also carries no text/spec override argument — it always sends the task's original, immutable
`--spec`. Even if re-dispatch were allowed, it could not deliver *different* round-2 content. Option (a) as
stated in the issue does not exist as an orca operation.

**(b) works, but only after the terminal's active dispatch is marked complete:**

```
# immediately after round 1, before worker_done:
orca orchestration dispatch --task <round2_task_id> --to <same-handle> --inject
→ {"ok":false,"error":{"code":"runtime_error",
    "message":"Terminal <handle> already has an active dispatch (ctx_... for task <round1_task_id>)"}}

# after the round-1 dispatch is completed via `orchestration send --type worker_done`:
orca orchestration dispatch --task <round2_task_id> --to <same-handle> --inject
→ {"ok":true, "result":{"injected":true, ...}}
```

Confirmed on the live terminal: the round-2 `TASK ===` block was injected and the real Claude session began
acting on the new spec. This matches the dry-run preamble text verbatim (`orca orchestration dispatch
--dry-run --return-preamble` on round 1 returns this before any real dispatch exists):

> "Do not exit the shell. Your terminal stays available, and if the coordinator has more for you it will
> re-engage this terminal with a fresh preamble + TASK block, which arrives as new input. When that
> happens, reset and start the new task; ignore the previous task's follow-ups."

This is Orca's own documented contract, not a convention this repo is inventing: **one active dispatch per
terminal; re-engagement is a new task, dispatched to the same handle, after the terminal's current dispatch
is marked complete.**

**(c) was not tested — the dry-run preamble text above already rules it out as the answer.** The intended
mechanism is dispatch-based re-engagement, not raw text injection; testing (c) separately would not change
that.

**New candidate considered, rejected on reasoning:** `orca agent-context --json` documents `orca
orchestration send --to dispatch:<id>` as a way to durably relay "attempt-specific coordinator guidance" to
a connected worker. It looked like a plausible fourth option before empirical testing. Rejected: `send`
delivers to a mailbox the recipient must actively poll (`orchestration check`); a worker that just sent
`worker_done` and is idling per the preamble's instruction is not running a poll loop — `dispatch --inject`
is a push, `send` is not. Confirmed no live test needed; the mechanism mismatch is structural, not empirical.

**Relay channel for the artifact path (no terminal read required):** `orca orchestration task-list --run
<id> --json` surfaces each completed task's `result` field, which for a `worker_done`-completed task
includes `reportPath` (`null` if the worker didn't pass `--report-path`). This is the "path only, not body"
channel `orca-workflow` §2a's existing design principle already requires — confirmed present in the live
`task-list` output, not assumed.

## 3. The resolved protocol

For each contract-negotiation round after the first, on both the task-runner and evaluator sides:

1. Poll `orca orchestration task-list --run <run_id> --brief --json` (not `check --wait` — orca-task-runner
   §5 already documents that a coordinator running inside an Orca terminal session can miss `worker_done` on
   the `check` queue even though task status updates correctly; the task-runner's own convention is
   `task-list` polling as primary) until the current round's task reaches `status: "completed"`.
2. Read `result.reportPath` (parse the JSON `result` string) — this is the file path being relayed, and
   reading it does not violate "diff/report body 안 읽음": it is a path string, not diff or report content.
3. `orca orchestration task-create --spec "<next round's content: the other side's file path + round
   number>"` — a brand-new task, **no `--deps` on the prior round's task**. Verified: a `--deps`-linked task
   sits in `status: "pending"` until the dependency task reaches `completed` — which is already the same
   gate `dispatch` enforces server-side ("already has an active dispatch"). `--deps` would only add a second,
   redundant stall path for identical effect, not new ordering guarantees.
4. `orca orchestration dispatch --task <new_task_id> --to <same-handle> --inject` — this succeeds now that
   step 1 confirmed the terminal's prior dispatch is completed.
5. Repeat until round limit (2), then `CONTRACT_FINALIZED_BY_GENERATOR` exactly as `orca-workflow` §2a
   already specifies (issue #63 — unchanged by this design).

This requires the **worker side** (task-runner's proposal-writing step, evaluator's contract-review step) to
call `worker_done` after producing each round's artifact. **This does not require new bash in either
`SKILL.md`, and it is already true today.** Every `dispatch --inject` — confirmed both in the `--dry-run
--return-preamble` output and in the real live-session terminal read — auto-injects a full preamble
*before* the `=== TASK ===` block, containing the complete `worker_done` syntax verbatim (including
`--report-path`), plus explicit instructions to stop after sending it and await re-engagement rather than
loop or poll. This is why none of the three `SKILL.md` files contain a single literal `orchestration send`
call anywhere today, including at `orca-task-runner`'s own §7 final-diff handoff — transport mechanics are
Orca's job via the injected preamble, not something these instruction files re-document. Adding an explicit
`worker_done` call to `orca-task-runner`/`orca-evaluate` would duplicate text Orca already injects and would
be the first literal `orchestration send` line in this file family, breaking that established convention.

The one real risk on the worker side is prose ambiguity, not a missing command: `orca-task-runner` §1's
"반려되면 수정해서 다시 제안한다" and `orca-evaluate` §1's mirrored wording narrate the *overall*
multi-dispatch protocol in a single unbroken sentence, read by an agent that receives it fresh at every
dispatch. A worker could misread it as "wait/poll within this same turn for the other side's response"
rather than "this sentence describes what happens across separate dispatches; end your turn after this
round's artifact, per the injected preamble." See §4b/§4c for the one-sentence fix.

## 4. Changes required

### 4a. `skills/orca-workflow/SKILL.md` §2a

Replace the "미확정" framing in the round-limit paragraph with: round 2+ relay uses the protocol in §3 above
— new `task-create` per round (no `--deps`), gated on a `task-list` poll confirming the prior round's task
is `completed`, then `dispatch --inject` to the same terminal handle. Both round-1 dispatch blocks (lines
107-160) get a short pointer to this new round-2+ subsection rather than duplicating the polling snippet
twice.

### 4b. `skills/orca-task-runner/SKILL.md` §1 (Contract 제안)

No new orca command — see §3's note on why not. One clarifying sentence after "반려되면 수정해서 다시
제안한다": this exchange spans separate dispatches, not a single turn — write the round's proposal, then end
the turn (the injected preamble's own `worker_done` instructions already cover the how); the next round
arrives as a fresh dispatch, not something this turn waits or polls for.

### 4c. `skills/orca-evaluate/SKILL.md` §1 (Contract 검토)

Same one-sentence clarification, mirrored, after the paragraph describing the relay of the verdict back to
`orca-task-runner`.

### 4d. `orca-workflows/logging.md` lines 45-51

Remove "아직 미해결 설계 질문이다, issue #64" — the question is now resolved, and per this repo's own
`skills엔 역사 남기지 말 것` convention, a resolved-question pointer left in place misdirects a future
session that reads it fresh. Keep the `relay:true` / omitted-`task_id` rule itself (it may still apply to
other call sites that lack a real task), but drop the now-incorrect prediction text ("기존 task 재사용
방식으로 확정하면") — the resolution was new-task-per-round, not task reuse, though the practical effect
predicted (a real `task_id` at this call site, making the rule moot here specifically) still holds.

### 4e. `orca-workflows/spawn-failures.md`

Add two rows to the Known signatures table, both observed directly in this investigation. The table's
contract requires a literal, grep-able substring — neither raw message contains one verbatim across every
occurrence (`<id>`/`<handle>` vary), so each signature uses the message's invariant literal portion, with
the full templated message described in the root-cause column:

| `failure_signature` (grep substring) | root cause | fix | known_issue |
|---|---|---|---|
| `is dispatched; only ready tasks can be dispatched` (full message: `Task <id> is dispatched; only ready tasks can be dispatched`) | attempting to re-`dispatch --task` a task that is already in `dispatched`/`completed` status — `dispatch` requires `status: ready` and carries no content-override argument | do not reuse a task_id across rounds; `task-create` a new task per round instead (`orca-workflow` §2a round-2+ protocol) | #64 |
| `already has an active dispatch` (full message: `Terminal <handle> already has an active dispatch (ctx_... for task <id>)`) | a terminal can hold at most one active (non-completed) dispatch at a time; dispatching a new task to it before the current one reaches `completed` is rejected outright | poll `task-list` for the prior round's task reaching `completed` (the worker's own injected-preamble `worker_done` call drives that transition automatically) before dispatching the next round — don't assume completion | #64 |

## 5. Edge cases / open items

- **`dispatch-capability` rotation per round is unverified, and moot for this design.** The live test
  captured round 1's `dcap_...` value from the injected preamble but not round 2's (a real agent consumed it
  faster than the read cadence used). This does not block the design: neither `orca-task-runner` nor
  `orca-evaluate` constructs a `worker_done` call by hand (§3/§4b/§4c), so there is no call site in this
  repo's files that would need to know which dcap to use — Orca's own injected preamble carries whichever
  dcap is current, and the worker copies it from there, not from anything this repo's prose tells it.
- **This design's scope crosses three `SKILL.md` files, not one.** `skills/` deploys via
  `scripts/deploy-skills.sh` after commit; `orca-workflows/` goes live on merge to main with no separate
  deploy step (symlink-tracks-main convention). A PR touching both propagates on two different schedules —
  call this out explicitly when merging so the deploy step for `skills/` isn't forgotten.
- **Test artifacts were left in Orca's own task/run state** (`run_672d51c03cd7` and its five test tasks),
  cleaned up during the investigation (`task-update --status failed` with an explanatory note on every
  leftover `dispatched`/`ready` task, all worker terminals closed). This run is isolated by `run_id` from any
  real `orca-workflow` invocation, so it does not require further cleanup, but is noted here for
  traceability.

## 6. Validation

1. Re-grep `skills/orca-workflow/SKILL.md` §2a after editing to confirm both round-1 dispatch blocks
   (task-runner, evaluator) point to the same shared round-2+ subsection rather than each re-deriving the
   polling snippet.
2. Confirm `skills/orca-task-runner/SKILL.md` §1 and `skills/orca-evaluate/SKILL.md` §1 each gained exactly
   one clarifying sentence (turn boundary, not a new orca command) and that neither file's count of literal
   `orchestration send`/`orca terminal read` occurrences changed from zero.
3. Confirm the two new `spawn-failures.md` rows don't collide with existing rows `#37`/`#43` (both involve
   `dispatch --inject` and a terminal that looks blocked) — the distinguishing detail is that `#37`/`#43`
   involve a terminal in an unexpected *shell* state, while these two are structured `runtime_error` JSON
   responses from `dispatch`/`task-create` itself, not a terminal-content signature.
4. Before closing issue #64, run one real `orca-workflow` task end-to-end through at least a round-2
   negotiation (a task designed to trigger one evaluator rejection) and confirm the round-2 dispatch
   succeeds without falling back to any `terminal-send-fallback`-style placeholder in the assignment log.
5. Recount every test in `tests/test_orca_skills.py` whose expectation is a function of literal text in
   these files (`test_dispatch_site_count_and_section0_exception_shape`, `test_orca_call_with_retry_count_per_skill`,
   `test_orca_terminal_read_counts_per_skill_file`) against the actual edited text, not a number predicted in
   advance — several of that suite's assertions are anchored to exact line-start patterns
   (`_RETRY_INVOCATION_LINE_RE`) that a differently-indented but equivalent snippet could silently miss.

No skill deployment step applies to the `orca-workflows/` edits (symlink-tracks-main convention — live on
merge). The `skills/orca-workflow`, `skills/orca-task-runner`, `skills/orca-evaluate` edits require `bash
scripts/deploy-skills.sh orca-workflow orca-task-runner orca-evaluate` after commit, per this repo's
skill-deployment convention.
