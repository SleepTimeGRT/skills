#!/usr/bin/env bash
# Shared retry-with-backoff wrapper for orca CLI calls that transiently fail when the Orca app
# auto-updates and restarts mid-session (issue #42).
#
#   source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
#   orca_call_with_retry <skill> <role> -- <orca command...>
#
# On success, or on a failure whose combined stdout+stderr doesn't match the known Orca-restart
# signature, the wrapped command's stdout/stderr/exit code pass through unchanged. On a matching
# failure: log one spawn-failures.jsonl occurrence, poll `orca status --json` for `.state ==
# "ready"` (bounded), and retry the identical command once ready — up to ORCA_RETRY_MAX_CYCLES
# cycles before giving up and returning the last failure to the caller.

_ORCA_RETRY_SIGNATURE_RE='Could not connect to the running Orca app|Orca is not running\. Run .orca open. first'

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

    if [ "$code" -eq 0 ] || ! printf '%s' "$combined" | grep -qE "$_ORCA_RETRY_SIGNATURE_RE"; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi

    cycle=$((cycle + 1))
    local outcome="retrying"
    [ "$cycle" -ge "$max_cycles" ] && outcome="exhausted"
    _orca_retry_log_occurrence "$skill" "$role" "$combined" "$outcome" "$cycle"

    if [ "$cycle" -ge "$max_cycles" ]; then
      cat "$out"
      cat "$err" >&2
      rm -f "$out" "$err"
      return "$code"
    fi
    rm -f "$out" "$err"

    local n=0 ready=0
    while [ "$n" -lt "$poll_max" ]; do
      if [ "$(orca status --json 2>/dev/null | jq -r '.state // empty')" = "ready" ]; then
        ready=1
        break
      fi
      n=$((n + 1))
      sleep "$poll_interval"
    done

    if [ "$ready" -eq 0 ]; then
      printf '%s' "$combined" >&2
      return "$code"
    fi
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
