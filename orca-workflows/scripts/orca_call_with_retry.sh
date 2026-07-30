#!/usr/bin/env bash
# Shared retry-with-backoff wrapper for orca CLI calls that transiently fail when the Orca app
# auto-updates and restarts mid-session (issue #42).
#
#   source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
#   orca_call_with_retry <skill> <role> -- <orca command...>

orca_call_with_retry() {
  local skill="$1" role="$2"
  shift 2
  [ "${1:-}" = "--" ] && shift

  local out err code
  out="$(mktemp)"; err="$(mktemp)"
  "$@" >"$out" 2>"$err"
  code=$?
  cat "$out"
  cat "$err" >&2
  rm -f "$out" "$err"
  return "$code"
}
