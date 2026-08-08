#!/usr/bin/env bash
# Shared helper that writes both halves of a dispatch log in one call: the assignments-<date>.jsonl
# `assign` event (logging.md §1) and the term-<handle>.jsonl `meta`(idempotent-guarded)+`sent` records
# (logging.md §2). Written for issue #68: orca-workflow's dispatch sites logged assign 11/11 times but
# term-log 0/11 across epic #502 — both writes lived in the same prose comment block, but only the
# one-line assign printf was mechanically simple enough to survive; the multi-line term-log
# instructions (jump to logging.md §2, assemble a meta guard, remember the recv carve-out) were
# reference+exception prose, not an executable command, and got skipped. Folding both into one function
# call makes "assign written, term skipped" structurally impossible.
#
#   source ~/.agents/orca-workflows/scripts/log_dispatch.sh
#   log_dispatch --skill <skill> --role <role> --issue <issue-num> --task-id <task_id> \
#     --terminal <handle> --worktree <worktree 경로> --provider <provider> --model <model> \
#     --effort <effort> --spec-text "$spec_text"
#
# Named flags, not positional args (deviates from issue #68's illustrative positional signature
# `log_dispatch <skill> <role> <issue> <task_id> <handle> <worktree> "$spec_text"`): the assign
# schema requires provider/model/effort (logging.md §1's base fields, not optional extras) that the
# issue's example omitted, and 9+ same-typed positional strings is exactly the kind of
# easy-to-misorder call site this issue is trying to eliminate.
#
# --task-id may be omitted entirely: logging.md §1's documented relay/omit rule applies (a dispatch
# with no real task_id omits the field and sets relay:true, rather than writing an empty string —
# the empty-string form is exactly the issue #62 bug). Passing --task-id with an *explicit* empty
# value is treated as a caller error (not silently relabeled relay:true) — contract round 2 review
# (issue #68) flagged that conflating "flag omitted" with "flag passed empty" would defeat
# relay:true's whole purpose (distinguishing "no real task_id, by design" from "forgot to resolve
# one"), so a separate task_id_set flag tracks whether --task-id appeared at all, independent of
# the value's emptiness.
#
# PORTABILITY (contract round 1 rejected an earlier draft here, issue #68): this function is sourced
# into whatever shell runs the calling SKILL.md block. On this machine that shell is zsh
# (ZSH_VERSION=5.9 observed), not bash. The required-argument check below is therefore written in a
# shell-portable subset only — explicit `[ -n "$var" ]` checks per variable, no bash-only indirect
# expansion (`${!name}`), no arrays, no `[[ ]]` — matching orca_call_with_retry.sh's existing
# portability contract. A bash-only `${!req}` loop was tried first and rejected: in zsh it throws
# "bad substitution", and that error unwinds the entire sourced script (not just this function),
# silently skipping every later command in the same fenced block — including, at this issue's site
# 1, the evaluator dispatch that follows the task-runner log_dispatch call in the shared
# `orca-workflow-task` §1 round-1 block.
#
# Writes, in order: (1) assign event, (2) meta(if first write to this handle)+sent to
# term-<handle>.jsonl. If (1) fails (install -d/chmod/write error), returns non-zero immediately
# and does NOT attempt (2) — this is the "atomic" guarantee AC1 asks for: sequential, fail-fast,
# never partial in the "assign written, term skipped" direction. It is not a transactional rollback
# (a failure inside step 2's meta/sent write can still leave assign written with no term log) —
# sequential-with-fail-fast was judged sufficient because that specific ordering (assign-only) is
# the exact failure mode issue #68 observed; the reverse has no observed occurrence to fix.
#
# recv is NOT written here — logging.md's recv carve-out (dispatch-verify.md's opaque liveness
# probe doesn't count as "already reads the terminal") still applies. Callers that separately read
# a terminal back log recv themselves at that read site, same as today.

log_dispatch() {
  local skill="" role="" issue="" task_id="" task_id_set=0 terminal="" worktree="" \
        provider="" model="" effort="" spec_text=""
  while [ $# -gt 0 ]; do
    # Guard against a flag with no following value (e.g. a truncated call site) *before* the case's
    # `shift 2`: without this check, `shift 2` on the last remaining argument fails (out-of-range)
    # without shifting, $1 never changes, and the loop hangs forever — confirmed by direct
    # reproduction in both bash and zsh during contract review. This is the same failure class the
    # round-1 rejection found (a shell-dependent difference silently breaking the calling block),
    # just a different trigger, so it gets the same fix philosophy: check first, never rely on
    # shift's failure mode.
    if [ $# -lt 2 ]; then
      echo "log_dispatch: $1 requires a value" >&2
      return 64
    fi
    case "$1" in
      --skill) skill="$2"; shift 2 ;;
      --role) role="$2"; shift 2 ;;
      --issue) issue="$2"; shift 2 ;;
      --task-id) task_id="$2"; task_id_set=1; shift 2 ;;
      --terminal) terminal="$2"; shift 2 ;;
      --worktree) worktree="$2"; shift 2 ;;
      --provider) provider="$2"; shift 2 ;;
      --model) model="$2"; shift 2 ;;
      --effort) effort="$2"; shift 2 ;;
      --spec-text) spec_text="$2"; shift 2 ;;
      *) echo "log_dispatch: unknown argument: $1" >&2; return 64 ;;
    esac
  done

  # Portable required-argument check — see the PORTABILITY note above. --task-id is deliberately
  # excluded here: it is optional (relay/omit rule), not a bug if never passed.
  local missing=""
  [ -n "$skill" ]     || missing="$missing --skill"
  [ -n "$role" ]      || missing="$missing --role"
  [ -n "$issue" ]     || missing="$missing --issue"
  [ -n "$terminal" ]  || missing="$missing --terminal"
  [ -n "$worktree" ]  || missing="$missing --worktree"
  [ -n "$provider" ]  || missing="$missing --provider"
  [ -n "$model" ]     || missing="$missing --model"
  [ -n "$effort" ]    || missing="$missing --effort"
  [ -n "$spec_text" ] || missing="$missing --spec-text"
  if [ -n "$missing" ]; then
    echo "log_dispatch: missing required argument(s):$missing" >&2
    return 64
  fi

  # --task-id explicitly passed but empty is a caller error, not a relay dispatch — see the
  # task_id_set note above (contract round 2 residual risk #1).
  if [ "$task_id_set" = "1" ] && [ -z "$task_id" ]; then
    echo "log_dispatch: --task-id was passed an empty value — omit the flag entirely for a relay" \
      "dispatch (logging.md §1's relay/omit rule), or pass a real task_id" >&2
    return 64
  fi

  local logs_dir="$HOME/.local/state/orca-workflows/logs"
  install -d -m 700 "$logs_dir" || return $?

  local assign_target="$logs_dir/assignments-$(date -u +%F).jsonl"
  if [ "$task_id_set" = "1" ]; then
    jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg role "$role" --arg issue "$issue" \
      --arg task_id "$task_id" --arg provider "$provider" --arg model "$model" --arg effort "$effort" \
      --arg terminal "$terminal" --arg worktree "$worktree" \
      '{ts:$ts, event:"assign", skill:$skill, role:$role, issue:$issue, task_id:$task_id,
        provider:$provider, model:$model, effort:$effort, terminal:$terminal, worktree:$worktree}' \
      >> "$assign_target" || return $?
  else
    # logging.md §1's relay/omit rule: no real task_id → omit the field (never an empty string)
    # and flag relay:true.
    jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg role "$role" --arg issue "$issue" \
      --arg provider "$provider" --arg model "$model" --arg effort "$effort" \
      --arg terminal "$terminal" --arg worktree "$worktree" \
      '{ts:$ts, event:"assign", skill:$skill, role:$role, issue:$issue,
        provider:$provider, model:$model, effort:$effort, terminal:$terminal, worktree:$worktree,
        relay:true}' \
      >> "$assign_target" || return $?
  fi
  chmod 600 "$assign_target" || return $?

  local term_log="$logs_dir/term-${terminal}.jsonl"
  if [ ! -s "$term_log" ] || ! head -1 "$term_log" | jq -e '.type == "meta"' >/dev/null 2>&1; then
    local version_file="$HOME/.agents/skills/$skill/.installed-version.json"
    local sv_json="null"
    [ -f "$version_file" ] && sv_json="$(jq -c '{version, commit}' "$version_file" 2>/dev/null || true)"
    [ -z "$sv_json" ] && sv_json="null"

    local owc_raw owc_json="null"
    owc_raw="$(git -C "$HOME/.agents/orca-workflows" rev-parse HEAD 2>/dev/null || true)"
    [ -n "$owc_raw" ] && owc_json="$(printf '%s' "$owc_raw" | jq -R .)"

    local oav_raw oav_json="null"
    oav_raw="$(orca status --json 2>/dev/null | jq -r '.result.runtime.appVersion // empty' 2>/dev/null || true)"
    [ -n "$oav_raw" ] && oav_json="$(printf '%s' "$oav_raw" | jq -R .)"

    jq -cn --arg issue "$issue" --arg skill "$skill" --arg role "$role" --arg terminal "$terminal" \
      --arg created_at "$(date -u +%FT%TZ)" \
      --argjson skill_version "$sv_json" --argjson orca_workflows_commit "$owc_json" \
      --argjson orca_app_version "$oav_json" \
      '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at,
        skill_version:$skill_version, orca_workflows_commit:$orca_workflows_commit,
        orca_app_version:$orca_app_version}' \
      >> "$term_log"
    chmod 600 "$term_log"
  fi

  jq -cn --arg ts "$(date -u +%FT%TZ)" --arg content "$spec_text" \
    '{ts:$ts, direction:"sent", content:$content}' >> "$term_log"
}
