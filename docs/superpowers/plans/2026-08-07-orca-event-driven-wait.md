# Orca Event-Driven Wait + Native Self-Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the retired polling-based wait ("`check --wait` 단독 대기 금지") in `orca-task-runner` §5 and `orca-workflow` §2a's round-2+ relay with an event-driven `check --wait`+`--ack` loop, backed by native Orca self-recovery (`worker-abandon` → `worker-start --retry-of`) instead of a hand-rolled fallback.

**Architecture:** A new shared reference file, `orca-workflows/self-recovery.md`, holds the wait/recovery loop (mirroring how `dispatch-verify.md`/`logging.md`/`spawn-failures.md` are already shared across the three `SKILL.md` files). Both call sites switch their dispatch verb from `dispatch --task ... --inject` to `worker-start --task ... --terminal ...` (adds a `dcap_` capability token and dispatch-lifecycle tracking) and point to `self-recovery.md` for the wait itself instead of inlining a polling loop. `tests/test_orca_skills.py`'s literal-pattern assertions are updated in lockstep — this repo enforces its skill prose with a real pytest suite, so every prose change here has a corresponding test change.

**Tech Stack:** Markdown `SKILL.md` prose (bash code blocks describing `orca` CLI invocations — not executed as a build step, but pinned by pytest string/regex assertions), Python (`pytest`) for the assertion suite, live `orca` CLI (v1.4.175 on this machine) for the manual verification tasks.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md` (approved by user). Every decision below that the spec left open is resolved here; nothing in this plan may silently contradict the spec's empirical findings (Tests 1-8) without saying so explicitly.
- Retry budget for `worker_abandon_retry`: **2** attempts per `task_id` (matches `orca-task-runner` §6's gate-retry limit and `orca-workflow` §2d's FAIL-retry limit — resolves spec §8's open item).
- `check --wait` timeout: **3600000 ms (1 hour)** per the user's explicit instruction. Full 1-hour durability is not provable by a short pytest run — Task 9 below does a live 10-minute spot-check as the practical verification bar (10x further than any test in the spec) and documents the result; it does not claim to prove the full hour.
- Scope is narrowed exactly as the spec's §3 states: only `orca-task-runner` §5 and `orca-workflow` §2a's round-2+ relay switch to `worker-start`. `orca-workflow` §1d (retro) and the initial §2a task-runner/evaluator dispatch keep raw `dispatch --task ... --inject` — do not touch them.
- Per this repo's `feedback-no-history-in-skills` convention: retired reasoning ("coordinator가 Orca 터미널 세션이면...") is deleted outright from `SKILL.md` prose, never left as a commented-out or "previously we thought" note. History lives only in the spec doc and this plan.
- `skills/` changes require `bash scripts/deploy-skills.sh orca-task-runner orca-workflow` after commit and merge — this plan does not run that script (per `AGENTS.md`'s "do not run deploy... merely to measure output"; this is a real deploy, not a measurement, but it is also irreversible-ish and affects a globally-symlinked directory, so leave it for the user to run explicitly after reviewing the merged diff). `orca-workflows/` changes need no separate deploy step (symlink-tracks-main convention).
- Every task that edits a `SKILL.md` or `orca-workflows/*.md` file must re-run the full `tests/test_orca_skills.py` suite (not just the file's own parametrized slice) before committing, since several assertions are cross-file (see Task 1, Task 8).

---

### Task 1: Widen the dispatch-site regex and bare-call scan to recognize `worker-start` (test-infra only, no prose changes yet)

**Files:**
- Modify: `tests/test_orca_skills.py:530` (`_DISPATCH_INJECT_RE`), `tests/test_orca_skills.py:648-652` (`_bare_wrapped_call_line_numbers`'s `patterns` tuple)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_DISPATCH_INJECT_RE` now matches **either** `orca orchestration dispatch --task ... --inject ... --json` **or** `orca orchestration worker-start --task ... --json` (single regex, used by `_dispatch_positions`, which every later task's dispatch/logging/verify-pointer tests depend on). `_bare_wrapped_call_line_numbers`'s `patterns` tuple gains `"orca orchestration worker-start --task"`.

This task exists on its own so a broken regex is caught immediately against the **current, unedited** `SKILL.md` files — before any prose changes muddy the signal. At this point zero `worker-start` sites exist yet, so every test that uses `_dispatch_positions`/`_bare_wrapped_call_line_numbers` must produce **exactly the same result as before** the regex change (this is the test for this task: "widening the net catches the same fish").

- [ ] **Step 1: Run the full suite once to record the current baseline**

Run: `cd /Users/minchul/Projects/sleeptimegrt-skills && python3 -m pytest tests/test_orca_skills.py -v 2>&1 | tail -40`
Expected: all tests pass (this is the pre-change baseline — write down the pass count, e.g. "62 passed", so Step 3 can compare).

- [ ] **Step 2: Widen `_DISPATCH_INJECT_RE`**

In `tests/test_orca_skills.py`, replace:

```python
_DISPATCH_INJECT_RE = re.compile(r"orca orchestration dispatch --task .*? --inject --json")
```

with:

```python
# Matches either the low-level `dispatch --task ... --inject` verb (still used at sites with
# no wait-loop problem: orca-workflow §1d retro, the initial §2a task-runner/evaluator dispatch)
# or its supervised replacement `worker-start --task ...` (orca-task-runner §5's wave dispatch,
# orca-workflow §2a's round-2+ relay dispatch — docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md).
# [\s\S]*? spans the backslash-continued multi-line worker-start invocation; non-greedy so it
# stops at the nearest following --json rather than swallowing later, unrelated blocks.
_DISPATCH_INJECT_RE = re.compile(
    r"orca orchestration (?:dispatch --task .*? --inject|worker-start --task[\s\S]*?)--json"
)
```

- [ ] **Step 3: Add `worker-start` to the bare-call-wrap pattern list**

In `tests/test_orca_skills.py`, in `_bare_wrapped_call_line_numbers`, replace:

```python
    patterns = (
        "orca terminal create",
        "orca orchestration task-create --spec",
        "orca orchestration task-list",
        "orca orchestration dispatch --task",
    )
```

with:

```python
    patterns = (
        "orca terminal create",
        "orca orchestration task-create --spec",
        "orca orchestration task-list",
        "orca orchestration dispatch --task",
        "orca orchestration worker-start --task",
    )
```

- [ ] **Step 4: Run the full suite again and diff against the Step 1 baseline**

Run: `python3 -m pytest tests/test_orca_skills.py -v 2>&1 | tail -40`
Expected: **identical pass count and identical set of passing test names** as Step 1 — zero `worker-start` sites exist in any `SKILL.md` yet, so widening the regex must not change any outcome. If anything now fails, the regex is wrong (most likely the `[\s\S]*?--json` half is matching something unintended in the *current* text) — fix the regex before proceeding, do not carry a broken regex into Task 6/7.

- [ ] **Step 5: Commit**

```bash
git add tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
test(orca-workflows): recognize worker-start as a dispatch site

Widens _DISPATCH_INJECT_RE and the bare-call-wrap scan to match
orca orchestration worker-start --task alongside the existing
dispatch --task ... --inject pattern, ahead of migrating two call
sites to worker-start (docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md).
No SKILL.md prose changes yet — this step only proves the widened
regex is a strict superset of the old one against unedited text.
EOF
)"
```

---

### Task 2: Create `orca-workflows/self-recovery.md`

**Files:**
- Create: `orca-workflows/self-recovery.md`
- Test: `tests/test_orca_skills.py` (new test function, plus a new `WORKFLOWS_DIR` constant already exists — confirm by checking the top of the file for `WORKFLOWS_DIR` and `_read_workflows_file`, both already used by the `dispatch-verify.md` tests)

**Interfaces:**
- Consumes: nothing (this is the new foundational shared reference).
- Produces: `orca-workflows/self-recovery.md`, referenced by name from Task 6 (`orca-task-runner` §5) and Task 7 (`orca-workflow` §2a). Both later tasks must literally contain the substring `self-recovery.md`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py` (near the existing `test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation`):

```python
SELF_RECOVERY_FILE = "self-recovery.md"


def test_self_recovery_file_documents_principle_and_loop():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: pins the load-bearing
    content of the new shared self-recovery reference so a future edit can't silently drop the
    native-primitives principle, the retry budget, the --ack requirement, or the worker-release
    rejection note."""
    text = _read_workflows_file(SELF_RECOVERY_FILE)
    assert "worker-abandon" in text and "--retry-of" in text, (
        "must document the fence-then-retry recovery mechanism"
    )
    assert "check --wait" in text and "--ack" in text, (
        "must document the event-driven wait and the mandatory ack"
    )
    assert "Retry budget: 2" in text or "재시도 예산" in text, (
        "must state a concrete retry budget, not leave it open"
    )
    assert "worker-release" in text and "external_terminal" in text, (
        "must record why worker-release was rejected for this repo's dispatch shape"
    )
    assert "last_heartbeat_at" in text, (
        "must record that heartbeat was observed null and is not relied on as a liveness signal"
    )


def test_self_recovery_file_states_no_process_action_for_abandon():
    """worker-abandon's whole value proposition is that it is non-destructive — pin the exact
    observed evidence so a future edit can't quietly turn this into a claim we didn't verify."""
    text = _read_workflows_file(SELF_RECOVERY_FILE)
    assert "processAction" in text and "none" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_orca_skills.py -k self_recovery -v`
Expected: FAIL — `orca-workflows/self-recovery.md missing` (from `_read_workflows_file`'s own `assert path.is_file()`).

- [ ] **Step 3: Create `orca-workflows/self-recovery.md`**

```markdown
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

Run this once per pending dispatch. A wave has one pending-set entry per subtask, keyed by `task_id`
(stable across retries — a `worker_abandon_retry` changes `dispatch_id`, so update the entry's
`dispatch_id` in place rather than adding a second entry). A contract round has exactly one entry.

```bash
result="$(orca orchestration check --run "$RUN_ID" --wait \
  --types worker_done,escalation --timeout-ms 3600000 --json)"
timed_out="$(printf '%s' "$result" | jq -r '.result.timedOut')"

if [ "$timed_out" = "true" ]; then
  # The only "polling" in this design: one liveness probe, not a repeated tick.
  read_json="$(orca terminal read --terminal "$WORKER_HANDLE" --json)"
  # Classify read_json's tail the same way dispatch-verify.md already does:
  #   - the worker's own turn still visibly progressing               -> alive
  #   - our own injected spec_prefix still sitting unsubmitted         -> stuck_draft
  #   - dead shell / no process responding                             -> dead
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
      DISPATCH_ID="$(printf '%s' "$new_result" | jq -r '.result.dispatchId')"
      # Re-run dispatch-verify.md's positive-confirmation procedure against this NEW dispatch.
      action_taken=worker_abandon_retry
      retry_count=$((retry_count + 1))
      ;;
  esac
  # Log a self_recovery event (see logging.md) regardless of which branch was taken.
  if [ "$action_taken" = worker_abandon_retry ] && [ "$retry_count" -gt 2 ]; then
    # Retry budget exhausted for this task_id -- escalate instead of retrying a third time.
    : # existing spawn-failures.md escalation procedure
  fi
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_orca_skills.py -k self_recovery -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/self-recovery.md tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
feat(orca-workflows): add self-recovery.md shared reference

New shared wait/recovery procedure (check --wait+ack, worker-abandon
-> worker-start --retry-of) for orca-task-runner/orca-workflow,
matching the dispatch-verify.md/logging.md precedent for shared
prose. Not yet referenced by either SKILL.md (Tasks 6-7).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Widen `dispatch-verify.md`'s framing to cover `worker-start`

**Files:**
- Modify: `orca-workflows/dispatch-verify.md:5`
- Test: `tests/test_orca_skills.py` (extend `test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation`)

**Interfaces:**
- Consumes: nothing.
- Produces: `dispatch-verify.md` now explicitly states it also covers `worker-start`, referenced by Task 6/7's prose and by Task 2's `self-recovery.md` preconditions section (already written above assuming this is true).

- [ ] **Step 1: Write the failing assertion**

In `tests/test_orca_skills.py`, extend `test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation`:

```python
def test_dispatch_verify_file_documents_bounded_tail_diff_and_escalation():
    """issue #43: dispatch --inject can land text without Enter registering, and a single
    `terminal read` can't tell that apart from normal post-completion idle. This pins the new
    shared reference file's key content so a future edit can't silently drop the bounded-wait
    check or the escalation path back to spawn-failures.md."""
    text = _read_workflows_file(DISPATCH_VERIFY_FILE)
    assert "tail" in text, "must describe comparing terminal tail output"
    assert "sleep 15" in text, "bounded wait window must be a concrete value, not a placeholder"
    assert "spawn-failures.md" in text, "must document escalation to the existing spawn-failure procedure"
    assert "❯" not in text and "⏺" not in text, (
        "must stay provider-agnostic — no Claude-Code-specific UI markers"
    )
    assert "worker-start" in text, (
        "docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: the same "
        "unsubmitted-draft failure mode was confirmed live under worker-start, not only raw "
        "dispatch --inject — the framing sentence must say so"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py -k dispatch_verify_file -v`
Expected: FAIL on the new `assert "worker-start" in text`.

- [ ] **Step 3: Edit `orca-workflows/dispatch-verify.md`**

Replace line 5:

```markdown
Shared post-`dispatch --inject` verification procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow`
(issue #43) — split out so the three `SKILL.md` files point here instead of each repeating the same bash
(same precedent as `logging.md`/`spawn-failures.md`).
```

with:

```markdown
Shared post-`dispatch --inject`-or-`worker-start` verification procedure for
`orca-task-runner`/`orca-evaluate`/`orca-workflow` (issue #43) — split out so the `SKILL.md` files point
here instead of each repeating the same bash (same precedent as `logging.md`/`spawn-failures.md`). The
same unsubmitted-draft failure mode reproduces identically under `worker-start`
(`docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md`, Test 3) — the bash below is
identical regardless of which command injected the text.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py -k dispatch_verify_file -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/dispatch-verify.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): note worker-start shares dispatch-verify.md's unsubmitted-draft failure mode

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Add the `self_recovery` logging event to `logging.md`

**Files:**
- Modify: `orca-workflows/logging.md` (insert after the `wave_start`/`wave_end` paragraph, ~line 75)
- Test: `tests/test_orca_skills.py` (new test)

**Interfaces:**
- Consumes: the `action_taken`/`terminal_status` vocabulary defined in Task 2's `self-recovery.md`.
- Produces: the `self_recovery` event recipe, which Task 6/7's `SKILL.md` prose will point to by name.

- [ ] **Step 1: Write the failing test**

```python
def test_logging_documents_self_recovery_event():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md: pins the self_recovery
    event schema so a future edit can't silently drop a field the self-recovery.md loop relies on."""
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert '"event":"self_recovery"' in text
    for field in ("task_id", "dispatch_id", "terminal", "waited_ms", "terminal_status", "action_taken"):
        assert f'"{field}"' in text, f"self_recovery event must include the {field} field"
    assert "resumed_wait" in text and "retried_enter" in text and "worker_abandon_retry" in text, (
        "must enumerate the action_taken values self-recovery.md's loop can produce"
    )
    assert "waves-<date>.jsonl" in text or "waves-" in text, (
        "must state orca-task-runner writes this event to its dated waves log"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py -k self_recovery_event -v`
Expected: FAIL — no `self_recovery` text in `logging.md` yet.

- [ ] **Step 3: Insert the recipe into `orca-workflows/logging.md`**

Insert immediately after the existing paragraph `**\`wave_start\`/\`wave_end\`** (\`orca-task-runner\` only): same jq schema as today, written to \`waves-$(date -u +%F).jsonl\` instead of the fixed \`waves.jsonl\`.` (and before the `### Reading across dates` heading):

```markdown
**`self_recovery`** (`orca-task-runner`/`orca-workflow`, per `orca-workflows/self-recovery.md`'s
wait/recovery loop):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/waves-$(date -u +%F).jsonl"   # orca-task-runner
# or: target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"   # orca-workflow
printf '{"ts":"%s","event":"self_recovery","skill":"<skill>","issue":"<issue-num>","task_id":"<task_id>","dispatch_id":"<dispatch_id>","terminal":"<handle>","waited_ms":<n>,"terminal_status":"<alive|dead|stuck_draft>","action_taken":"<resumed_wait|retried_enter|worker_abandon_retry|escalated_spawn_failure>","new_dispatch_id":"<new dispatch_id-or-omit, only when action_taken=worker_abandon_retry>"}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

`orca-task-runner` writes to `waves-<date>.jsonl` (add `wave_index` as an extra field, joinable with
that wave's `wave_start`/`wave_end` records); `orca-workflow` writes to `assignments-<date>.jsonl` (no
`wave_index`). Purpose: `self-recovery.md`'s 3600000ms timeout is an unvalidated starting guess — this
log is what lets a future session re-derive a real distribution instead of guessing again, and lets
`orca-retro`'s "repeated FAIL attributable to skill prose" lens notice if a particular signature
recurs.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py -k self_recovery_event -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/logging.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): add self_recovery event schema to logging.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Update `spawn-failures.md`'s issue #64 row to point at `check --wait`

**Files:**
- Modify: `orca-workflows/spawn-failures.md` (the `already has an active dispatch` row, issue #64)
- Test: `tests/test_orca_skills.py` (new test)

**Interfaces:**
- Consumes: nothing.
- Produces: the corrected `fix` column text.

- [ ] **Step 1: Write the failing test**

```python
def test_spawn_failures_active_dispatch_row_points_to_check_wait():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md supersedes this row's old
    fix text ('poll task-list') -- the row must now describe the event-driven replacement, and must
    not still tell a future reader to poll task-list for this specific failure."""
    text = _read_workflows_file("spawn-failures.md")
    assert "already has an active dispatch" in text
    idx = text.index("already has an active dispatch")
    row_end = text.index("\n", idx)
    row = text[max(0, idx - 200):row_end]
    assert "check --wait" in row, "fix column must now point at the check --wait mechanism"
    assert "poll `task-list`" not in row, (
        "must not still recommend the disproven task-list-polling workaround for this row"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py -k active_dispatch_row -v`
Expected: FAIL on `assert "check --wait" in row`.

- [ ] **Step 3: Edit the row in `orca-workflows/spawn-failures.md`**

Find the table row whose `fix` column currently reads:

```
poll `task-list` for the prior round's task reaching `completed` (the worker's own injected-preamble `worker_done` call drives that transition automatically) before dispatching the next round — don't assume completion
```

Replace it with:

```
wait via `check --wait` (`orca-workflows/self-recovery.md`) for that dispatch's `worker_done` — receiving it via `check`/`check --wait` is itself proof the dispatch reached `completed` server-side (confirmed live: `completedAt` matches the message timestamp exactly), no separate `task-list` confirmation read needed — before dispatching the next round
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py -k active_dispatch_row -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/spawn-failures.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): point issue #64's active-dispatch row at check --wait, not task-list polling

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Migrate `orca-task-runner` §5 to `worker-start` + `self-recovery.md`

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md` §0, §5
- Test: `tests/test_orca_skills.py` (`test_orca_terminal_read_counts_per_skill_file`, `EXPECTED_RETRY_WRAP_COUNTS` — verify unchanged, not edited — plus one new test)

**Interfaces:**
- Consumes: `orca-workflows/self-recovery.md` (Task 2), the widened `_DISPATCH_INJECT_RE`/bare-call patterns (Task 1).
- Produces: `orca-task-runner`'s wave loop now creates its own Run in §0 and dispatches via `worker-start` in §5, pointing to `self-recovery.md` for the wait itself instead of inlining `task-list` polling.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orca_skills.py`:

```python
def test_orca_task_runner_creates_own_run_in_section0():
    text = _read_skill("orca-task-runner")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "run-create" in section0, (
        "orca-task-runner §0 must create and bind its own Run once per session, distinct from "
        "whatever Run orca-workflow owns"
    )


def test_orca_task_runner_section5_points_to_self_recovery():
    text = _read_skill("orca-task-runner")
    section5_start = text.index("## 5.")
    section5_end = text.index("## 6.")
    section5 = text[section5_start:section5_end]
    assert "self-recovery.md" in section5
    assert "worker-start" in section5
    assert "체크 큐로 안 잡힐 수 있다" not in text, (
        "retired scheduler reasoning must be deleted outright, not annotated (no-history-in-skills)"
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_orca_skills.py -k "orca_task_runner_creates_own_run or section5_points_to_self_recovery" -v`
Expected: FAIL (both — §0 has no `run-create` yet, §5 has no `self-recovery.md` pointer yet).

- [ ] **Step 3: Edit `skills/orca-task-runner/SKILL.md` §0**

In §0's bullet list, add a new bullet immediately before the `## 1. Contract 제안` heading:

```markdown
- **Run 생성**(세션 시작 시 1회): `orca orchestration run-create --objective "<issue 번호> task implementation" --from <자기 handle> --json`로 이 세션 전용 Run을 만들고 바인딩한다. 이후 §5의 모든 `worker-start`/`check --wait`/`--ack` 호출은 이 run_id를 쓴다 — `orca-workflow`가 이 세션을 스폰할 때 자기 Run을 갖고 있더라도 그건 재사용하지 않는다(Run이 섞이면 서로 다른 세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md` 참고).
```

- [ ] **Step 4: Edit `skills/orca-task-runner/SKILL.md` §5**

Replace the dispatch line:

```
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
```

with:

```
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration worker-start --task <task_id> --worktree active --terminal <impl_handle> --run "$RUN_ID" --from <자기 handle> --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
```

Immediately below that fenced block, replace the comment line:

```
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43, positive-confirmation
# 방식으로 issue #58에서 교체): 15초 뒤 재-read해서 $spec_text 앞부분이 tail에서 확인 안 되면 Enter만
# 재전송, 그래도 확인 안 되면 spawn-failures.md로.
```

with:

```
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43, positive-confirmation
# 방식으로 issue #58에서 교체 — worker-start에도 동일하게 필요: stage:"input_accepted"는 실제 제출을
# 보장하지 않는다, 실측): 15초 뒤 재-read해서 $spec_text 앞부분이 tail에서 확인 안 되면 Enter만
# 재전송, 그래도 확인 안 되면 spawn-failures.md로.
```

Replace the bullet:

```
- ⚠️ **`check --wait` 단독 대기 금지**: coordinator가 Orca 터미널 내부 세션이면 worker_done이 check 큐로 안 잡힐 수 있다(task 상태는 정상 갱신됨). 기본 대기 = `task-list --brief --json` 상태 폴링 또는 커밋/파일 존재 감시(20-30s 간격), `check --wait`는 보조.
- timeout·`count:0` = 체크포인트. `terminal read`로 생사 확인, 활동 중이면 계속 대기. 생사가 아니라
  셸 에러/no-output이면 스폰 실패 — `~/.agents/orca-workflows/spawn-failures.md` 절차로.
- decision_gate(워커 ask) → 판단 가능하면 `reply`, 불가하면 `orca-workflow`에 에스컬레이션.
- worker_done 유실 복구: 커밋/산출물/worktree 루트의 `.orca-orphaned-result-<task_id>.json`(⑦의 exhausted 폴백 산출물) 확인 + `task-update --status completed` 수동 복구, 기록. orphan 파일은 복구 반영 후 삭제한다.
```

with:

```
- **완료 대기와 self-recovery**: `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery 루프를 그대로 따른다 — 이 wave의 각 subtask `task_id`를 pending set에 넣고, `check --wait`(+`--ack`)로 기다리다 타임아웃되면 그 파일의 alive/stuck_draft/dead 분기(`worker-abandon`→`worker-start --retry-of`)로 복구한다. `dead` 판정 후 재시도할 때는 새 worker 터미널을 §3의 launch 템플릿으로 다시 띄운다(모델·effort는 같은 subtask이므로 재-resolve 없이 그대로 재사용).
- decision_gate(워커 ask) → 판단 가능하면 `reply`, 불가하면 `orca-workflow`에 에스컬레이션.
- **`orca_call_with_retry` exhausted로 인한 worker_done 유실**(위 self-recovery와는 다른 시나리오 — Orca 오케스트레이션 API 자체에 닿을 수 없는 경우, issue #41/#42): 커밋/산출물/worktree 루트의 `.orca-orphaned-result-<task_id>.json`(⑦의 exhausted 폴백 산출물) 확인 + `task-update --status completed` 수동 복구, 기록. orphan 파일은 복구 반영 후 삭제한다.
```

Leave the rest of §5 (the "완료 확인된 subtask 터미널은 즉시 닫는다" block and everything after) untouched — `worker-release` was checked and rejected for this repo's dispatch shape (`self-recovery.md`'s "Rejected candidate" section), so the manual read-then-close block stays exactly as-is.

- [ ] **Step 5: Run the full suite and fix whatever the widened regex/counts reveal**

Run: `python3 -m pytest tests/test_orca_skills.py -v 2>&1 | tail -60`

This will likely surface at least these adjustments — make them based on the **actual** pytest output, not by predicting numbers in advance:

- `test_orca_terminal_read_counts_per_skill_file`: the new self-recovery pointer in §5 does **not** add a literal `orca terminal read` occurrence to `orca-task-runner/SKILL.md` itself (the liveness read now lives only in `self-recovery.md`, which this test does not scan). If the test still expects `1` for `orca-task-runner` and it's still `1`, leave it unchanged. If it fails, read the actual count from the assertion error and update `expected = {"orca-task-runner": 1, ...}` to match — do not guess.
- `test_dispatch_site_count_and_section0_exception_shape`: with the Task 1 regex widened to match either verb, converting this one site from `dispatch --inject` to `worker-start` should **not** change `total` (still counts as one dispatch-style site, just a different verb) — confirm `total == 8` still passes. If it doesn't, the regex from Task 1 has a bug; fix the regex, not this test's expectation.
- `EXPECTED_RETRY_WRAP_COUNTS["orca-task-runner"]`: the wrapped-call count should stay `6` — the dispatch line is still exactly one `orca_call_with_retry "..." -- \` invocation, just wrapping a different command. If pytest disagrees, count the actual `orca_call_with_retry "` line occurrences in the edited file (`grep -c 'orca_call_with_retry "' skills/orca-task-runner/SKILL.md`) and reconcile — don't just bump the number to make the test pass without understanding why it changed.

Iterate: edit → re-run → repeat until every test passes.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-task-runner/SKILL.md tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
feat(orca-task-runner): switch §5 wave dispatch to worker-start + self-recovery.md

Replaces the retired check-queue-miss workaround (task-list polling
every 20-30s) with self-recovery.md's check --wait+ack loop, and the
low-level dispatch --inject call with worker-start --terminal (adds
dispatch-lifecycle tracking, no launch-template change). §0 now
creates this session's own Run.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Migrate `orca-workflow` §2a's round-2+ relay to `worker-start` + `self-recovery.md`

**Files:**
- Modify: `skills/orca-workflow/SKILL.md` §0, §2a (round-2+ subsection only, ~lines 162-190 in the pre-edit file)
- Test: `tests/test_orca_skills.py` (`test_orca_workflow_documents_round2_relay_protocol`, `test_orca_terminal_read_counts_per_skill_file`, `EXPECTED_RETRY_WRAP_COUNTS`, plus new tests)

**Interfaces:**
- Consumes: `orca-workflows/self-recovery.md` (Task 2).
- Produces: `orca-workflow`'s round-2+ relay now creates its own Run in §0, dispatches round-2+ via `worker-start`, and waits via `self-recovery.md` instead of `task-list` polling — but keeps exactly one `task-list` lookup **after** `worker_done` arrives, to fetch `.result.reportPath` (the event payload does not carry it — confirmed live: `worker_done`'s `payload` is only `{"taskId":...,"dispatchId":...,"outcome":...}`).

- [ ] **Step 1: Write the failing tests**

Update `test_orca_workflow_documents_round2_relay_protocol` (currently asserts `"task-list" in text, "round-2+ completion check must poll task-list, not terminal read"`, which directly enforces the disproven design):

```python
def test_orca_workflow_documents_round2_relay_protocol():
    """Issue #64: §2a must name the actual mechanism (new task-create per round, event-driven wait
    via self-recovery.md, dispatched to the same terminal handle via worker-start) rather than
    leaving round 2+ undocumented. Pins the load-bearing phrases so a future rewrite can't silently
    reintroduce task-list polling as the primary wait mechanism or task_id reuse.

    docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md supersedes this test's
    original 'must poll task-list, not terminal read' assertion -- that assertion enforced the
    now-disproven check-queue-miss claim."""
    text = _read_skill("orca-workflow")
    assert "already has an active dispatch" in text, (
        "must document the verified error a premature round-2 dispatch produces"
    )
    assert "is dispatched; only ready tasks can be dispatched" in text, (
        "must document why reusing the round-1 task_id is impossible"
    )
    assert "self-recovery.md" in text, "round-2+ completion wait must point at the shared event-driven loop"
    assert "reportPath" in text, (
        "must name the path-only relay channel (task-list result.reportPath) -- still needed as a "
        "one-shot lookup after worker_done, since the event payload itself doesn't carry it"
    )
    assert "`--deps`는 걸지" in text, "must explicitly instruct against --deps between round tasks"


def test_orca_workflow_round2_uses_worker_start_not_raw_dispatch():
    """docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md §3/§6b: only the
    round-2+ dispatch site migrates to worker-start -- the initial §2a task-runner/evaluator
    dispatch and §1d retro stay on raw dispatch --inject (no polling problem there)."""
    text = _read_skill("orca-workflow")
    round2_idx = text.index("라운드 2+")
    round2_end = text.index("## 3.", round2_idx)
    round2_section = text[round2_idx:round2_end]
    assert "worker-start" in round2_section
    assert "task-list --json` 폴링(20-30s" not in text, (
        "the old 20-30s polling bullet must be gone, not merely superseded in prose"
    )


def test_orca_workflow_creates_own_run_in_section0():
    text = _read_skill("orca-workflow")
    section0_start = text.index("## 0.")
    section0_end = text.index("## 1.")
    section0 = text[section0_start:section0_end]
    assert "run-create" in section0, (
        "orca-workflow §0 must create and bind its own Run once per invocation, distinct from "
        "whatever Run orca-task-runner/orca-evaluate create for their own internal fan-out"
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_orca_skills.py -k "documents_round2_relay_protocol or round2_uses_worker_start or workflow_creates_own_run" -v`
Expected: FAIL on all three (old `task-list` assertion still present; no `worker-start`/`run-create` in the file yet).

- [ ] **Step 3: Edit `skills/orca-workflow/SKILL.md` §0**

Add a bullet before `## 1. Epic 경로`:

```markdown
- **Run 생성**(실행 시작 시 1회): `orca orchestration run-create --objective "<issue 번호> contract round relay" --from <자기 handle> --json`로 이 실행 전용 Run을 만들고 바인딩한다. §2a 라운드 2+ relay의 모든 `worker-start`/`check --wait`/`--ack` 호출은 이 run_id를 쓴다 — `orca-task-runner`/`orca-evaluate`가 각자 내부 fan-out에 쓰는 Run과는 별개다(섞이면 서로 다른 세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md` 참고).
```

- [ ] **Step 4: Edit `skills/orca-workflow/SKILL.md` §2a's round-2+ subsection**

Replace the whole round-2+ subsection (from `**Contract 협상 relay — 라운드 2+ ...` through the `- 오래(예: 30분) ...` bullet at the end of that subsection) with:

```markdown
**Contract 협상 relay — 라운드 2+ (반려된 경우만; 승인이면 곧장 2b)**: 라운드 1과 같은 task_id를 재사용하지
않는다 — `dispatch`는 이미 `dispatched`/`completed` 상태인 task를 거부하고(`"Task ... is dispatched; only ready tasks can be dispatched"`, 실측), 애초에 텍스트를 override하는 인자가 없어 재사용해도 라운드 1과 같은
spec만 재전송된다. 대신 매 라운드 새 task를 만들어 같은 터미널(재-engage 대상은 task-runner면
`<run-handle>`, evaluator면 `<evaluate-handle>`)에 재-dispatch한다 — 단 그 터미널의 직전 dispatch가
`completed` 상태여야 한다(그렇지 않으면 `"Terminal ... already has an active dispatch"`로 거부됨, 실측).
`--deps`는 걸지 않는다 — 걸어도 `dispatch` 자체가 이미 같은 선후관계를 강제하므로 stall 경로만 하나 늘어난다.

직전 라운드가 `completed`인지 확인하는 대기는 `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery
루프를 그대로 따른다(`check --wait`+`--ack`, 타임아웃 시 alive/stuck_draft/dead 분기) — 이 dispatch에 대한
`worker_done`을 `check`/`check --wait`로 수신하는 것 자체가 곧 `completed` 확정이다(실측: 완료 시각이
메시지 타임스탬프와 정확히 일치). `worker_done` 수신 후, 그 결과의 `reportPath`를 읽기 위한 **1회성**
조회만 한다(폴링 아님 — `worker_done` 메시지의 payload 자체엔 `reportPath`가 없어서, 이 조회는 "완료됐는지"
확인용이 아니라 값을 얻기 위한 것뿐이다):

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-list --run "$RUN_ID" --json
# 위 결과에서 직전 라운드 task_id를 찾아 .result(JSON 문자열)를 파싱해 .reportPath를 읽는다 —
# 본문은 읽지 않고 경로만 중계한다는 원칙은 여기서도 유지된다.
spec_text="<round 번호 + 위에서 읽은 reportPath + (evaluator→task-runner 방향이면) 반려 사유 요약>"
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree active \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(worker-start에도 동일하게 필요).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. task_id가 실제 존재하므로 §1의 relay:true/omit
# 규칙은 이 사이트엔 적용되지 않는다(issue #64로 해소).
```

- 오래(예: 30분) `completed`가 안 되면(= self-recovery.md의 재시도 예산까지 소진) 체크포인트 —
  재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차로.
```

- [ ] **Step 5: Run the full suite and fix whatever the widened regex/counts reveal**

Run: `python3 -m pytest tests/test_orca_skills.py -v 2>&1 | tail -60`

Expected adjustments to verify against **actual** output (mirrors Task 6 Step 5's caution):

- `test_dispatch_site_count_and_section0_exception_shape`: `total == 8` should still pass (regex counts the `worker-start` line as a dispatch-style site, same as before). If it doesn't, fix the Task 1 regex.
- `test_orca_terminal_read_counts_per_skill_file`: `orca-workflow`'s expected count should stay `0` — the round-2+ subsection's own liveness read lives in `self-recovery.md`, not inlined here (same reasoning as Task 6). If `_read_skill("orca-workflow")` now contains a literal `orca terminal read` occurrence somewhere unrelated, investigate before changing the expected value.
- `EXPECTED_RETRY_WRAP_COUNTS["orca-workflow"]`: should stay `12` — round-2+ still contributes exactly 3 wrapped calls (`task-list`, `task-create`, `worker-start`), same count as before (`task-list`, `task-create`, `dispatch`). If pytest disagrees, `grep -c 'orca_call_with_retry "' skills/orca-workflow/SKILL.md` and reconcile against the actual number, updating the docstring comment (`# +3 for issue #64's round-2+ relay: task-list poll, task-create, dispatch`) to read `# +3 for issue #64's round-2+ relay: task-list (reportPath lookup), task-create, worker-start`.

Iterate: edit → re-run → repeat until every test passes.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-workflow/SKILL.md tests/test_orca_skills.py
git commit -m "$(cat <<'EOF'
feat(orca-workflow): switch §2a round-2+ relay to worker-start + self-recovery.md

Supersedes 2026-08-06's round-2+ design (docs/superpowers/specs/2026-08-06-contract-round-relay-design.md
§3 step 1), which codified the now-disproven check-queue-miss claim
one day before this investigation. task-list is kept as a one-shot
reportPath lookup after worker_done, not a completion-polling loop.
§0 now creates this invocation's own Run.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Full regression pass and cross-file consistency check

**Files:**
- Modify (if needed): `tests/test_orca_skills.py` only, based on actual failures.

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: a fully green `tests/test_orca_skills.py`, and a manual grep confirming the retired reasoning text is gone.

- [ ] **Step 1: Run the entire suite**

Run: `python3 -m pytest tests/test_orca_skills.py -v 2>&1 | tail -100`
Expected: all tests pass. If any fail, they are almost certainly cross-file assertions (e.g. `test_dispatch_site_count_and_section0_exception_shape` sums across `NEW_SKILLS`) that only stabilize once **both** Task 6 and Task 7 are in place — fix based on the actual failure message, not by re-guessing a number.

- [ ] **Step 2: Grep both edited `SKILL.md` files for the retired reasoning, by hand**

Run: `grep -n "체크 큐로 안 잡힐 수 있다\|check --wait.*단독 대기 금지" skills/orca-task-runner/SKILL.md skills/orca-workflow/SKILL.md`
Expected: no output. This is a belt-and-suspenders manual check on top of the Task 6/7 pytest assertions, per the spec's own §9 validation item 2 ("grep... to confirm the retired reasoning is fully removed, not merely annotated as outdated").

- [ ] **Step 3: Confirm both `SKILL.md` files point to `self-recovery.md`**

Run: `grep -c "self-recovery.md" skills/orca-task-runner/SKILL.md skills/orca-workflow/SKILL.md`
Expected: at least 1 occurrence in each file.

- [ ] **Step 4: Commit only if Step 1 required test changes beyond what Tasks 6/7 already committed**

```bash
git add tests/test_orca_skills.py
git commit -m "test(orca-workflows): fix cross-file assertions after both dispatch sites migrated to worker-start

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(Skip this commit if Step 1 passed with no further edits — don't create an empty commit.)

---

### Task 9: Live spot-check — 10-minute `check --wait` durability

**Files:** none (this is a manual verification task against a live Orca runtime, not a code change).

**Interfaces:** none.

This directly answers spec §8's open item ("1-hour `check --wait` durability is unverified... first real invocation should be watched for a dropped connection") with the longest practical spot-check before merging, without tying up a terminal for the full hour.

- [ ] **Step 1: Confirm the Orca runtime is ready**

Run: `orca status --json | python3 -c "import json,sys; d=json.load(sys.stdin)['result']['runtime']; print(d['appVersion'], d['reachable'])"`
Expected: a version string and `True`.

- [ ] **Step 2: Create a scratch Run and task**

```bash
CWD_PATH="$(orca worktree current --json | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['worktree']['path'])")"
MY_HANDLE="$(orca terminal list --json | python3 -c "
import json,sys
d = json.load(sys.stdin)
for t in d['result']['terminals']:
    if t['worktreePath'] == '$CWD_PATH' and t['connected']:
        print(t['handle']); break
")"
orca orchestration run-create --objective "10-minute check --wait durability spot-check" --from "$MY_HANDLE" --json
# note the returned run.id as $RUN_ID
```

- [ ] **Step 3: Start a 10-minute blocking `check --wait` with no matching messages expected, timed**

```bash
date +%s.%N
orca orchestration check --run "$RUN_ID" --wait --timeout-ms 600000 --json
date +%s.%N
```

Expected: after ~600 seconds, the command returns `{"result":{"timedOut":true,"cancelled":false,"connectionLost":false, ...}}` — not an error, not a hang past the timeout, and specifically `connectionLost:false` (a field this design's spec called out as worth watching for).

- [ ] **Step 4: Record the result**

If it returns cleanly as expected, add one line to `docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md`'s §8 "1-hour `check --wait` durability is unverified" bullet, noting the 10-minute spot-check passed cleanly (with the actual elapsed time and `connectionLost` value), and that the full hour remains unverified but this is 10x further than any prior test.

If it does **not** return cleanly (drops early, errors, or `connectionLost:true`), stop — do not proceed to merge. This is exactly the failure mode the spec flagged as the one thing that would require revisiting the design (the loop structure would still hold; only the 3600000ms constant would need lowering, per `self-recovery.md`'s own "if a future session observes `connectionLost`..." note).

- [ ] **Step 5: Commit the spec update (only if Step 3 passed)**

```bash
git add docs/superpowers/specs/2026-08-07-orca-event-driven-wait-design.md
git commit -m "docs(orca-workflows): record 10-minute check --wait durability spot-check result

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Final review checklist (no code changes)

- [ ] **Step 1:** Re-run `python3 -m pytest tests/test_orca_skills.py -v` one final time end-to-end. All green.
- [ ] **Step 2:** Confirm `git log --oneline` shows one commit per task above, each with a clear message — no squashing needed, but check nothing was left uncommitted (`git status --short` is clean).
- [ ] **Step 3:** Post a reminder (in the PR description if one is opened, or directly to the user) that `bash scripts/deploy-skills.sh orca-task-runner orca-workflow` must be run after this merges — this plan intentionally does not run it (Global Constraints).
- [ ] **Step 4:** Do not close whatever issue tracks this change yet — per the spec's §9 validation item 3, a full real `orca-task-runner` wave (≥2 parallel subtasks) and a full real `orca-workflow` round-2+ negotiation should each be run end-to-end at least once post-merge, including one deliberately-forced `worker_abandon_retry`, before considering this fully proven in production use (this plan's live tests in Tasks 6/7/9 exercise the mechanism in isolation, not inside a full real wave/round).
