# Orca Orchestration Call Retry-Backoff Design

**Date:** 2026-07-30

**Scope:** `orca orchestration send/dispatch` and `orca terminal create` call sites in `orca-workflow`,
`orca-task-runner`, `orca-evaluate`, plus a new shared `orca-workflows/scripts/orca_call_with_retry.sh` and
worker-side spec instructions. Addresses issue #42.

## 1. Purpose

Orca's own auto-update can restart the Orca app mid-session. Any orchestration CLI call in flight during
that restart window fails with one of:

```
Could not connect to the running Orca app. Restart Orca and try again.
Orca is not running. Run 'orca open' first.
```

This is transient — the app is back to `ready` within seconds. Today nothing recovers from it
automatically: a human (or the coordinator session) has to notice the failure, cross-check `terminal
read`/`orca status --json` to confirm the app actually came back, and manually retype the same command. The
reproduction in issue #42 (a Codex worker completed a 6-minute review and then had its `worker_done` send
fail three times in a row across an app-version bump `1.4.159` → `1.4.161`) shows this happening on live,
otherwise-healthy sessions, not just on already-broken ones.

The user explicitly does not want auto-update disabled — the fix is self-recovery: retry the same call after
a bounded wait for the app to come back, and only escalate to a human once that retry budget is exhausted.

This is a distinct failure category from the acceptance-criteria-adjacent retry counters already documented
elsewhere in these skills (subtask gate retry, evaluate-FAIL retry, GATE_FAIL routing) — those are about
retrying *content* that failed a quality gate; this is about retrying a CLI call that never reached the
server due to a transport-level restart.

## 2. Failure Signature & Detection

Match is done on combined stdout+stderr text, not on exit code alone — the exact exit code Orca's CLI returns
for these two error strings has not been verified in this session and should be confirmed empirically during
implementation (treat as an open item, not an assumption).

```
Could not connect to the running Orca app
Orca is not running. Run 'orca open' first
```

A failure that does not match either substring is not this wrapper's concern — it is returned to the caller
untouched, so existing skill-level retry/escalation logic (subtask gates, `spawn-failures.md`'s other
signatures) is unaffected.

## 3. `orca_call_with_retry` Shared Script

New file: `orca-workflows/scripts/orca_call_with_retry.sh` (this repo's git-tracked main checkout — reachable
at the fixed machine path `~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` via the existing
symlink documented in AGENTS.md's `orca-workflows/` deploy-path decision, #22). One bash function:

```bash
# usage: orca_call_with_retry <skill> <role> -- <orca command...>
# stdout of the underlying command is passed through on success; on exhaustion, the last
# attempt's stdout/stderr and exit code are passed through unchanged.
orca_call_with_retry() {
  local skill="$1" role="$2"; shift 2; [ "$1" = "--" ] && shift
  local cycle=0 max_cycles=2 poll_interval=5 poll_max=6
  while :; do
    local out err code combined
    out=$(mktemp); err=$(mktemp)
    "$@" >"$out" 2>"$err"; code=$?
    combined="$(cat "$out" "$err")"
    if [ $code -eq 0 ] || ! printf '%s' "$combined" | grep -qE \
        'Could not connect to the running Orca app|Orca is not running\. Run .orca open. first'; then
      cat "$out"; cat "$err" >&2
      rm -f "$out" "$err"
      return $code
    fi
    cycle=$((cycle + 1))
    local outcome="retrying"; [ $cycle -ge $max_cycles ] && outcome="exhausted"
    _orca_retry_log_occurrence "$skill" "$role" "$combined" "$outcome" "$cycle"
    rm -f "$out" "$err"
    if [ $cycle -ge $max_cycles ]; then
      return $code
    fi
    local n=0 ready=0
    while [ $n -lt $poll_max ]; do
      if [ "$(orca status --json 2>/dev/null | jq -r '.state // empty')" = "ready" ]; then
        ready=1
        break
      fi
      n=$((n + 1)); sleep "$poll_interval"
    done
    [ $ready -eq 0 ] && return $code
    # loop: retry the original command
  done
}
```

Behavior, in order:

1. Run the original command as given.
2. Success, or a failure that doesn't match the known signature → pass through unchanged. This wrapper never
   masks or reinterprets an unrelated failure.
3. Signature match → this is cycle N (1-indexed). Append a `spawn-failures.jsonl` occurrence record (§5)
   before doing anything else, so an occurrence is recorded even if the process is killed mid-poll.
4. If this is the 2nd cycle already (`max_cycles=2`, matching this repo's existing 2-retry convention used
   elsewhere — see `orca-task-runner` §6 evaluate-FAIL retry cap, `orca-workflow` §2d) → return the failure as-is.
   The caller decides what "exhausted" means for it (GATE_FAIL, inspecting routing, human `ask`, etc.) —
   this wrapper does not itself notify a human.
5. Otherwise, poll `orca status --json` every 5s up to 6 times (≤30s) for `.state == "ready"`.
6. If it comes back ready, loop and retry the exact same original command once. If not, return the failure
   as-is (do not spend a full second cycle waiting on an app that isn't coming back within budget).

Worst-case wall-clock before returning failure to the caller: two failed calls + one ~30s poll ≈ under a
minute, matching the issue's own back-of-envelope estimate.

## 4. Failure Idempotency Assumption

A connection failure (either error string) means the request never reached the Orca server — it is not a
"request succeeded, response lost" case. This was confirmed as an explicit design decision for this issue:
retrying the identical command (same `--task-id`/`--dispatch-id`) is safe without a pre-retry
verification step (e.g. checking `task-list`/`terminal read` for prior effect). This assumption is scoped to
these two specific error strings; it does not generalize to arbitrary orca CLI failures.

## 5. Logging Integration

Every retry cycle (regardless of eventual success) appends one record to the existing
`~/.local/state/orca-workflows/logs/spawn-failures.jsonl` using the format already defined in
`orca-workflows/spawn-failures.md`:

```jsonl
{"ts":"<ISO8601>","skill":"<skill>","role":"<role>","provider":null,"failure_signature":"<matched substring>","fix_applied":"retry-backoff","known_issue":42,"outcome":"retrying"|"exhausted","attempts":<cycle>}
```

This reuses the install/chmod/jq append pattern already documented there — no new log file, no new schema
beyond adding an `outcome`/`attempts` pair consistent with how `orca-task-runner` already logs
`retry_count`/`outcome:"crash_recovered"` in its wave telemetry. The point is purely evidentiary: this makes
it possible to later answer "how often does the auto-update window actually clip a live call" from data
instead of anecdote, without adding human-visible noise on every occurrence (only `exhausted` triggers any
caller-side human-facing report).

## 6. Integration Points

**Call sites wrapped** (every one becomes `source .../orca_call_with_retry.sh` then
`orca_call_with_retry <skill> <role> -- <original command>`). The `source` line is repeated at the
top of every independently-executed fenced ```bash block that uses the wrapper — not once per
`SKILL.md` file — since separate fenced blocks in these docs represent separate shell
invocations/spawned terminals that don't share a sourced function across block boundaries:

- `orca-workflow/SKILL.md`: lines 61, 64, 65 (task-runner spawn + task-create + dispatch), 80, 86, 87
  (evaluate spawn + task-create + dispatch)
- `orca-task-runner/SKILL.md`: line 54 (task-create), 74/77/85 (terminal create, one per provider branch),
  113 (task-list), 116 (wave dispatch)
- `orca-evaluate/SKILL.md`: lines 19, 24, 25 (evaluate-session spawn), 39, 43, 44 (contract-review spawn),
  68 (agent-e2e terminal create), 134, 140, 141 (code-review spawn)

**Worker-side (spawned coding agent) instructions** — any orchestration call the spawned worker itself runs
back toward its coordinator (chiefly `worker_done`, or a contract/review verdict relay) must go through the
same `orca_call_with_retry` function — `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
then wrap the call — and the worker must not raise a blocking `ask` about a connection failure until the
wrapper itself returns exhausted. This is the same script as §3, not a re-implementation — coordinator and
worker share one locus. Concretely:

- `orca-task-runner`'s "subtask spec 필수 항목" list (§2, currently ①–⑥) gains a ⑦ for this — it already has
  an explicit numbered list that every subtask spec text includes verbatim.
- `orca-evaluate` has no equivalent numbered list; the same instruction is added to the `spec_text` composed
  at its two round-trip spawn points (§1 contract-review, §3 code-review — both explicitly do "다회 왕복"
  back to the evaluator). §2's agent-e2e spawn is headless/one-shot and reports by writing a file
  (`report_path`), not by any orchestration call back to the coordinator, so it needs no such instruction.

**`spawn-failures.md` new row:**

| `failure_signature` | root cause | fix | known_issue |
|---|---|---|---|
| `Could not connect to the running Orca app` / `Orca is not running. Run 'orca open' first.` | Orca app auto-update restarts the app mid-session; any orchestration call in flight during that window fails | wrap the call in `orca_call_with_retry` (`orca-workflows/scripts/orca_call_with_retry.sh`) — polls `orca status --json` for `ready`, then retries the identical call, bounded to 2 cycles before surfacing to the caller | #42 |

## 7. Non-Goals / Edge Cases

- **A fully dead terminal is out of scope.** Issue #42 also observed a case where the *target terminal's*
  process died during the restart (`terminal read` showing `oldestCursor`/`nextCursor`/`latestCursor` all
  `0`, `lastOutputAt` frozen) — the Orca app itself was back to `ready`, but that specific worker process was
  gone. No amount of connection retry recovers this. `orca_call_with_retry` only owns the
  connection-level retry; if the underlying call keeps failing after exhausting its 2 cycles, the caller's
  existing recovery path (re-spawn a new terminal, `GATE_FAIL`, escalate to inspecting) applies unchanged —
  this wrapper does not attempt to detect or special-case a dead terminal.
- **No pre-retry effect verification** (§4) — deliberately not implemented, to keep the wrapper from adding
  an extra API round-trip (and a call, like `dispatch --inject`, that has no cheap way to check "did this
  already apply") to every retry.
- **No skill deployment step.** Matches `orca-workflows/`'s existing symlink-tracks-main convention (AGENTS.md
  #22) — once merged to `main`, the new script and the three `SKILL.md` edits are live immediately.

## 8. AGENTS.md Update

`AGENTS.md`'s `orca-workflows/` deploy-path decision note currently frames that directory as effectively
docs-only ("single machine, single consumer... reads model-selection.md/spawn-failures.md/logging.md from
it"). Adding `scripts/orca_call_with_retry.sh` — an executable file that call sites actually `source` and
invoke, not just read as reference prose — is a real departure from that framing and should be noted in the
same section rather than left implicit.

## 9. Validation

1. Confirm the actual exit code and combined stdout/stderr text Orca's CLI produces for both known error
   strings (§2's open item) before finalizing the `grep -qE` pattern — do this against a real restart window
   if one can be captured, otherwise via the exact strings already observed in issue #42's reproduction.
2. Re-grep all three `SKILL.md` files for `orca orchestration` / `orca terminal create` after editing to
   confirm no call site listed in §6 was missed and no new call site introduced elsewhere lacks the wrapper.
3. Exercise `orca_call_with_retry` against a deliberately-failing stub command (not live Orca) to confirm:
   pass-through on unrelated failure, pass-through on success, 2-cycle exhaustion behavior, and that
   `spawn-failures.jsonl` gets one record per cycle with correct `outcome`.
4. Confirm no other text in `orca-task-runner/SKILL.md` cross-references the ①–⑥ list by count (e.g. "6개
   항목") in a way that would go stale once it becomes ①–⑦.
5. Confirm `spawn-failures.md`'s new row's `failure_signature` column stays a literal grep-able substring,
   consistent with that document's own authoring guidance.
