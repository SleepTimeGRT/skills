#!/usr/bin/env bash
# lifecycle-gate-policy: canonical scripts/token-gate.sh v1 — do not hand-edit in the
# target repository; change the copy in sleeptimegrt-skills and re-apply.
# Source this file from a non-interactive repository gate.

# A non-interactive GUI git client can spawn hooks without an interactive
# shell's PATH, so an nvm-managed pnpm/node can be invisible even though a
# normal terminal push works fine. Resolve it directly here instead of
# depending on the invoking process having sourced the user's shell profile.
# nvm only — no fnm/volta/asdf/mise support without evidence they're in use.
if ! command -v pnpm >/dev/null 2>&1 && [ -s "${HOME}/.nvm/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "${HOME}/.nvm/nvm.sh" --no-use
  nvm use >/dev/null 2>&1 || nvm use default >/dev/null 2>&1 || true
fi

token_gate_begin() {
  if [ "$#" -ne 1 ]; then
    printf '%s\n' "token_gate_begin: expected an entrypoint name" >&2
    return 64
  fi

  TOKEN_GATE_NAME=$1
  TOKEN_GATE_SAFE_NAME=$(printf '%s' "$TOKEN_GATE_NAME" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_')
  TOKEN_GATE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    printf '[%s] FAIL setup — not inside a Git worktree\n' "$TOKEN_GATE_NAME" >&2
    return 2
  }
  TOKEN_GATE_GIT_DIR=$(cd "$TOKEN_GATE_ROOT" && git rev-parse --absolute-git-dir) || return $?
  TOKEN_GATE_WORKTREE_KEY=$(printf '%s\n' "$TOKEN_GATE_GIT_DIR" | git hash-object --stdin) || return $?
  TOKEN_GATE_TMP_BASE=${TMPDIR:-/tmp}
  TOKEN_GATE_TEMP_ROOT=${TOKEN_GATE_TMP_BASE%/}/token-gates-$(id -u)
  TOKEN_GATE_LOG_DIR=$TOKEN_GATE_TEMP_ROOT/$TOKEN_GATE_WORKTREE_KEY/$TOKEN_GATE_SAFE_NAME
  TOKEN_GATE_LOG=$TOKEN_GATE_LOG_DIR/latest.log

  token_gate_old_umask=$(umask)
  umask 077
  mkdir -p "$TOKEN_GATE_LOG_DIR" || return $?
  chmod 700 "$TOKEN_GATE_TEMP_ROOT" "$TOKEN_GATE_TEMP_ROOT/$TOKEN_GATE_WORKTREE_KEY" "$TOKEN_GATE_LOG_DIR" || return $?
  : >"$TOKEN_GATE_LOG" || return $?
  chmod 600 "$TOKEN_GATE_LOG" || return $?
  for token_gate_stale in "$TOKEN_GATE_LOG_DIR"/.stage.*; do
    [ -f "$token_gate_stale" ] && rm -f -- "$token_gate_stale"
  done
  umask "$token_gate_old_umask"

  TOKEN_GATE_PASS_COUNT=0
  TOKEN_GATE_WARN_COUNT=0
  TOKEN_GATE_SKIP_COUNT=0
  TOKEN_GATE_FAIL_COUNT=0
  TOKEN_GATE_STAGE_COUNT=0
  export TOKEN_GATE_NAME TOKEN_GATE_LOG TOKEN_GATE_LOG_DIR
}

_token_gate_discard_log() {
  rm -f -- "$TOKEN_GATE_LOG"
  rmdir "$TOKEN_GATE_LOG_DIR" 2>/dev/null || true
}

_token_gate_print_index() {
  token_gate_index_pattern=$1
  token_gate_index_ignore_case=$2
  if [ "$token_gate_index_ignore_case" -eq 1 ]; then
    token_gate_index_matches=$(LC_ALL=C grep -Ein -m 5 -- "$token_gate_index_pattern" "$TOKEN_GATE_LOG" || true)
  else
    token_gate_index_matches=$(LC_ALL=C grep -En -m 5 -- "$token_gate_index_pattern" "$TOKEN_GATE_LOG" || true)
  fi

  if [ -n "$token_gate_index_matches" ]; then
    printf '%s\n' "$token_gate_index_matches" | awk -v label="$TOKEN_GATE_NAME" '
      {
        separator = index($0, ":")
        line_number = substr($0, 1, separator - 1)
        detail = substr($0, separator + 1)
        gsub(/\033\[[0-9;?]*[ -\/]*[@-~]/, "", detail)
        gsub(/\r/, " ", detail)
        gsub(/[[:space:]]+/, " ", detail)
        sub(/^ /, "", detail)
        sub(/ $/, "", detail)
        if (length(detail) > 180) detail = substr(detail, 1, 179) "…"
        printf "[%s] INDEX L%s: %s\n", label, line_number, detail
      }
    '
    return 0
  fi

  token_gate_index_lines=$(awk 'END { print NR + 0 }' "$TOKEN_GATE_LOG")
  if [ "$token_gate_index_lines" -eq 0 ]; then
    printf '[%s] INDEX log is empty\n' "$TOKEN_GATE_NAME"
    return 0
  fi
  token_gate_index_start=$((token_gate_index_lines - 19))
  [ "$token_gate_index_start" -lt 1 ] && token_gate_index_start=1
  printf '[%s] INDEX no high-confidence marker; inspect L%s-L%s\n' \
    "$TOKEN_GATE_NAME" "$token_gate_index_start" "$token_gate_index_lines"
}

token_gate_capture() {
  token_gate_capture_warn_regex=
  if [ "${1-}" = "--warn-regex" ]; then
    if [ "$#" -lt 5 ]; then
      printf '%s\n' "token_gate_capture: --warn-regex requires a pattern, entrypoint, and command" >&2
      return 64
    fi
    token_gate_capture_warn_regex=$2
    shift 2
  fi
  if [ "$#" -lt 3 ] || [ "${2-}" != "--" ]; then
    printf '%s\n' "token_gate_capture: expected [--warn-regex REGEX] ENTRYPOINT -- COMMAND..." >&2
    return 64
  fi
  token_gate_capture_name=$1
  shift 2

  token_gate_begin "$token_gate_capture_name" || return $?
  token_gate_capture_start=$SECONDS
  if "$@" >"$TOKEN_GATE_LOG" 2>&1; then
    token_gate_capture_status=0
  else
    token_gate_capture_status=$?
  fi
  token_gate_capture_elapsed=$((SECONDS - token_gate_capture_start))

  if [ "$token_gate_capture_status" -eq 0 ]; then
    if [ -n "$token_gate_capture_warn_regex" ] &&
      LC_ALL=C grep -E -q -- "$token_gate_capture_warn_regex" "$TOKEN_GATE_LOG"; then
      printf '[%s] WARN (%ss) — log: %s\n' "$TOKEN_GATE_NAME" "$token_gate_capture_elapsed" "$TOKEN_GATE_LOG"
      _token_gate_print_index "$token_gate_capture_warn_regex" 0
    else
      _token_gate_discard_log
      printf '[%s] PASS (%ss)\n' "$TOKEN_GATE_NAME" "$token_gate_capture_elapsed"
    fi
    return 0
  fi

  token_gate_failure_pattern='(^|[[:space:]:])(error(\[[^]]+\])?|fatal|panic|exception|failed)([[:space:]:]|$)|^not ok([[:space:]]|$)|(^|[[:space:]])(✗|×)[[:space:]]'
  if [ "$token_gate_capture_status" -gt 128 ] && [ "$token_gate_capture_status" -le 192 ]; then
    token_gate_capture_signal_number=$((token_gate_capture_status - 128))
    token_gate_capture_signal_name=$(kill -l "$token_gate_capture_signal_number" 2>/dev/null || printf '%s' "$token_gate_capture_signal_number")
    printf '[%s] FAIL (signal %s, %ss) — log: %s\n' \
      "$TOKEN_GATE_NAME" "$token_gate_capture_signal_name" "$token_gate_capture_elapsed" "$TOKEN_GATE_LOG"
    _token_gate_print_index "$token_gate_failure_pattern" 1
    kill -"$token_gate_capture_signal_number" "$$"
    return "$token_gate_capture_status"
  fi

  printf '[%s] FAIL (exit %s, %ss) — log: %s\n' \
    "$TOKEN_GATE_NAME" "$token_gate_capture_status" "$token_gate_capture_elapsed" "$TOKEN_GATE_LOG"
  _token_gate_print_index "$token_gate_failure_pattern" 1
  return "$token_gate_capture_status"
}

token_gate_stage() {
  token_gate_warn_regex=
  if [ "${1-}" = "--warn-regex" ]; then
    if [ "$#" -lt 4 ]; then
      printf '[%s] FAIL setup — --warn-regex requires a pattern, stage, and command\n' "$TOKEN_GATE_NAME" >&2
      return 64
    fi
    token_gate_warn_regex=$2
    shift 2
  fi
  if [ "$#" -lt 3 ] || [ "${2-}" != "--" ]; then
    printf '[%s] FAIL setup — expected: token_gate_stage [--warn-regex REGEX] STAGE -- COMMAND...\n' "$TOKEN_GATE_NAME" >&2
    return 64
  fi
  token_gate_stage_name=$1
  shift 2

  token_gate_old_umask=$(umask)
  umask 077
  token_gate_stage_log=$(mktemp "$TOKEN_GATE_LOG_DIR/.stage.XXXXXX") || return $?
  umask "$token_gate_old_umask"
  token_gate_start=$SECONDS
  if "$@" >"$token_gate_stage_log" 2>&1; then
    token_gate_status=0
  else
    token_gate_status=$?
  fi
  token_gate_elapsed=$((SECONDS - token_gate_start))

  {
    printf '===== %s =====\n' "$token_gate_stage_name"
    cat "$token_gate_stage_log"
  } >>"$TOKEN_GATE_LOG"
  TOKEN_GATE_STAGE_COUNT=$((TOKEN_GATE_STAGE_COUNT + 1))

  if [ "$token_gate_status" -ne 0 ]; then
    TOKEN_GATE_FAIL_COUNT=$((TOKEN_GATE_FAIL_COUNT + 1))
    if [ "$token_gate_status" -gt 128 ] && [ "$token_gate_status" -le 192 ]; then
      token_gate_signal_number=$((token_gate_status - 128))
      token_gate_signal_name=$(kill -l "$token_gate_signal_number" 2>/dev/null || printf '%s' "$token_gate_signal_number")
      printf '[%s] FAIL %s (signal %s, %ss) — log: %s\n' \
        "$TOKEN_GATE_NAME" "$token_gate_stage_name" "$token_gate_signal_name" "$token_gate_elapsed" "$TOKEN_GATE_LOG"
      rm -f -- "$token_gate_stage_log"
      kill -"$token_gate_signal_number" "$$"
      return "$token_gate_status"
    fi
    printf '[%s] FAIL %s (exit %s, %ss) — log: %s\n' \
      "$TOKEN_GATE_NAME" "$token_gate_stage_name" "$token_gate_status" "$token_gate_elapsed" "$TOKEN_GATE_LOG"
    rm -f -- "$token_gate_stage_log"
    return "$token_gate_status"
  fi

  if [ -n "$token_gate_warn_regex" ] && grep -E -q -- "$token_gate_warn_regex" "$token_gate_stage_log"; then
    TOKEN_GATE_WARN_COUNT=$((TOKEN_GATE_WARN_COUNT + 1))
    printf '[%s] WARN %s (%ss) — log: %s\n' \
      "$TOKEN_GATE_NAME" "$token_gate_stage_name" "$token_gate_elapsed" "$TOKEN_GATE_LOG"
  else
    TOKEN_GATE_PASS_COUNT=$((TOKEN_GATE_PASS_COUNT + 1))
    printf '[%s] PASS %s (%ss)\n' "$TOKEN_GATE_NAME" "$token_gate_stage_name" "$token_gate_elapsed"
  fi
  rm -f -- "$token_gate_stage_log"
}

token_gate_skip() {
  if [ "$#" -ne 2 ]; then
    printf '[%s] FAIL setup — expected: token_gate_skip STAGE REASON\n' "$TOKEN_GATE_NAME" >&2
    return 64
  fi
  token_gate_skip_stage=$1
  token_gate_skip_reason=$(printf '%s' "$2" | tr '\r\n' '  ')
  TOKEN_GATE_SKIP_COUNT=$((TOKEN_GATE_SKIP_COUNT + 1))
  TOKEN_GATE_STAGE_COUNT=$((TOKEN_GATE_STAGE_COUNT + 1))
  printf '===== %s (SKIP) =====\n%s\n' "$token_gate_skip_stage" "$token_gate_skip_reason" >>"$TOKEN_GATE_LOG"
  printf '[%s] SKIP %s — %s\n' "$TOKEN_GATE_NAME" "$token_gate_skip_stage" "$token_gate_skip_reason"
}

token_gate_finish() {
  if [ "${TOKEN_GATE_FAIL_COUNT:-0}" -gt 0 ]; then
    token_gate_result=FAIL
  elif [ "${TOKEN_GATE_WARN_COUNT:-0}" -gt 0 ] || [ "${TOKEN_GATE_SKIP_COUNT:-0}" -gt 0 ]; then
    token_gate_result=WARN
  else
    token_gate_result=PASS
  fi
  if [ "$token_gate_result" = PASS ]; then
    _token_gate_discard_log
    printf '[%s] PASS %s stages\n' "$TOKEN_GATE_NAME" "${TOKEN_GATE_STAGE_COUNT:-0}"
  else
    printf '[%s] %s %s stages — log: %s\n' \
      "$TOKEN_GATE_NAME" "$token_gate_result" "${TOKEN_GATE_STAGE_COUNT:-0}" "$TOKEN_GATE_LOG"
  fi
  [ "${TOKEN_GATE_FAIL_COUNT:-0}" -eq 0 ]
}
