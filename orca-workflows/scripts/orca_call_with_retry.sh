#!/usr/bin/env bash
# Shared retry-with-backoff wrapper for orca CLI calls that transiently fail when the Orca app
# auto-updates and restarts mid-session (issue #42).
#
#   source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
#   orca_call_with_retry <skill> <role> -- <orca command...>
#
# On success, or on a failure whose combined stdout+stderr doesn't match the known Orca-restart
# signature, the wrapped command's stdout/stderr/exit code pass through unchanged. On a matching
# failure: log one spawn-failures.jsonl occurrence, poll `orca status --json` for
# `.result.runtime.state == "ready"` (bounded), and retry the identical command once ready — up to
# ORCA_RETRY_MAX_CYCLES cycles before giving up and returning the last failure to the caller.
#
# Signature broadened 2026-08-07 (issue #42 reopened): the two original literals missed a real
# recurrence at MediCount#502/child#496 — 3 occurrences across that pair where the actual error
# text matched neither literal, so the call went unretried AND unlogged (no spawn-failures.jsonl
# row at all, since the log-occurrence path only fires on a signature match). Keyword
# alternatives (`not running`, `could not connect`, `reconnect`, `bootstrap`) were added
# case-insensitively (`-i`) to catch that class without requiring every future error string to be
# enumerated as a new literal.
#
# Signature broadened again 2026-08-13 (issue #103): "The Orca runtime closed the connection
# before responding." — observed live at MediCount#513 (2026-08-09, orca-workflow-epic waiting on
# a task-coordinator via `check --wait` during an app auto-update 1.4.176->1.4.177) — matched none
# of the five keywords above, so it went unretried by this wrapper too (recovered only by a human
# manually polling `orca status --json`). Added `closed the connection` case-insensitively.
#
# leftmost-longest assumption: both original literals are longer than any of the new keyword
# alternatives, so under POSIX ERE leftmost-longest matching, `grep -oE` still prefers the
# original literals wherever they're present — `matched_signature` extraction is unchanged for
# the two pre-existing cases (this is what
# `test_logged_failure_signature_is_matched_substring_not_full_output` in
# tests/test_orca_call_with_retry.py asserts exactly).
#
# Fallback contract: if a real worker's `grep` build is observed to violate leftmost-longest (that
# test goes red), switch to two-stage matching instead of trying to fix it in one pattern: decide
# retry-or-not with the broad `grep -qiE` as today, but derive `matched_signature` by trying the
# original narrow 2-literal pattern first and falling back to the broad pattern's match only if
# the narrow one finds nothing.
#
# Log-pollution tradeoff: `not running` (and to a lesser extent the other keywords) can
# coincidentally match wrapped-command output that has nothing to do with Orca transport itself,
# producing a spawn-failures.jsonl row mislabeled `known_issue: 42`. Post-broadening, that field
# means "issue #42-class failure" (a class label), not "confirmed root cause."
#
# Idempotency scope note (out of scope for #42, tracked separately): this function also wraps
# mutating calls (`task-create`/`dispatch`/`worker-start`/`terminal create`). If one of those
# succeeds server-side but the client observes a non-zero exit whose output happens to contain one
# of the broadened keywords, a retry can duplicate the task/dispatch — a pre-existing risk (it
# already existed for the two original literals) that this broadening widens the surface of,
# without introducing it. `task-create`/`dispatch`/`worker-start` support a `--retry-request <id>`
# flag with confirmed server-side dedupe (same key replayed returns `mutation.replayed: true` and
# the same resulting id) — callers that want this call idempotent supply a stable id in the wrapped
# command's own argument vector (this function stays opaque to it; see the three SKILL.md families'
# call sites, `skills/` scope only — `orca-workflows/self-recovery.md`'s unwrapped `worker-start
# --retry-of` call is a separate, already-intentional retry-lineage mechanism and is out of this
# note's scope). `terminal create` has no `--retry-request` flag and remains unprotected.

_ORCA_RETRY_SIGNATURE_RE='Could not connect to the running Orca app|Orca is not running\. Run .orca open. first|not running|could not connect|reconnect|bootstrap|closed the connection'

orca_call_with_retry() {
  local skill="$1" role="$2"
  shift 2
  [ "${1:-}" = "--" ] && shift

  local max_cycles="${ORCA_RETRY_MAX_CYCLES:-2}"
  local poll_interval="${ORCA_RETRY_POLL_INTERVAL:-5}"
  local poll_max="${ORCA_RETRY_POLL_MAX:-6}"
  local cycle=0

  while :; do
    local out err code combined
    out="$(mktemp)"; err="$(mktemp)"
    "$@" >"$out" 2>"$err"
    code=$?
    combined="$(cat "$out" "$err")"

    if [ "$code" -eq 0 ] || ! printf '%s' "$combined" | grep -qiE "$_ORCA_RETRY_SIGNATURE_RE"; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi

    cycle=$((cycle + 1))
    local outcome="retrying"
    [ "$cycle" -ge "$max_cycles" ] && outcome="exhausted"
    local matched_signature
    matched_signature="$(printf '%s' "$combined" | grep -oiE "$_ORCA_RETRY_SIGNATURE_RE" | head -1)"
    _orca_retry_log_occurrence "$skill" "$role" "$matched_signature" "$outcome" "$cycle"

    if [ "$cycle" -ge "$max_cycles" ]; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi

    local n=0 ready=0
    while [ "$n" -lt "$poll_max" ]; do
      if [ "$(orca status --json 2>/dev/null | jq -r '.result.runtime.state // empty')" = "ready" ]; then
        ready=1
        break
      fi
      n=$((n + 1))
      sleep "$poll_interval"
    done

    if [ "$ready" -eq 0 ]; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi
    rm -f "$out" "$err"
    # ready — loop back and retry the identical original command
  done
}

_orca_retry_log_occurrence() {
  local skill="$1" role="$2" failure_signature="$3" outcome="$4" attempts="$5"
  install -d -m 700 "$HOME/.local/state/orca-workflows/logs"
  jq -cn \
    --arg ts "$(date -u +%FT%TZ)" \
    --arg skill "$skill" \
    --arg role "$role" \
    --arg failure_signature "$failure_signature" \
    --argjson known_issue 42 \
    --arg outcome "$outcome" \
    --argjson attempts "$attempts" \
    '{
      ts: $ts,
      skill: $skill,
      role: $role,
      provider: null,
      failure_signature: $failure_signature,
      fix_applied: "retry-backoff",
      known_issue: $known_issue,
      outcome: $outcome,
      attempts: $attempts
    }' >> "$HOME/.local/state/orca-workflows/logs/spawn-failures.jsonl"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/spawn-failures.jsonl"
}
