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
#   log_dispatch --skill <skill> --role <role> --issue <issue-num> --repo <대상 repo> \
#     --task-id <task_id> \
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
#
# ── Canonical enums (issues #105/#116/#125/#127/#138) ──────────────────────────────────────────
# These variables are the MACHINE-CHECKED AUTHORITY for the outcome / self_recovery.action_taken
# value sets; logging.md §1's prose lists are the human-readable mirror. If they ever disagree,
# this file wins. Rationale (issue #105's fix direction, escalated by #138's 5th recurrence):
# the enum was violated by ad-hoc invented values five times (#62 → #69 → #86 → #105 → #138), each
# fix patching one value in prose with no runtime enforcement — per the skills guide
# (docs/references/anthropic-building-skills-for-claude.pdf, Troubleshooting): "For critical
# validations, bundle a script that performs the checks programmatically."
#
# Space-separated (not |-separated) on purpose: it lets the validation below use a portable
# `case " $LIST " in *" $value "*` substring match that behaves identically in bash and zsh (no
# word-splitting dependence — zsh doesn't split unquoted variables), and lets the pytest suite
# extract and compare the set mechanically (tests/test_log_outcome.py).
#
# Membership notes beyond logging.md's original list:
# - skipped: added per issue #138 — orca-workflow-epic's "dependent of a parked task" branch is a
#   real, recurring routing state (9 records in one run) that had no legal value; blocked_by is its
#   conditional companion field (required when outcome=skipped, dropped otherwise).
# - NO_ACCEPTANCE_CRITERIA: added per issue #105 — its fix-direction section concludes this is
#   probably a legitimate branch ("issue body not concrete enough to draft acceptance criteria"
#   at the issue-drain/AC-draft stage), observed live from orca-workflow.
# - CONTRACT_SCHEMA_STALE: added per issue #160 — override.json completed before the proposal-r3
#   requirement itself existed (commit 79b7c3b/#130) is not a recording-contract violation, so it
#   gets its own progress-branch value instead of overloading CONTRACT_ESCALATE's "AC disagreement"
#   meaning. Emitted by orca-workflow-task §1's inline gate and contract_resume.sh's crash-resume
#   mirror (tests/test_contract_resume.py).
# - EPIC_DONE / PR_OPEN_PREMERGE_PASS (observed in #105's recurrence comments) are deliberately
#   NOT added: neither has a decided semantics yet — they hit the UNMAPPED_BRANCH safeguard, which
#   is the designed path for values awaiting a schema decision.
LOG_OUTCOME_ENUM="PASS FAIL ESCALATE GATE_FAIL CONTRACT_ESCALATE CI_GATE_FAIL NO_DONE_TRANSITION CONTRACT_FINALIZED_BY_GENERATOR CONTRACT_APPROVED CONTRACT_SCHEMA_STALE MANUAL_RECOVERY_COMPLETED CI_GATE_TIMEOUT MERGE_CONFLICT RETRO_DONE RETRO_FAIL escalation_parked skipped NO_ACCEPTANCE_CRITERIA UNMAPPED_BRANCH"

# self_recovery.action_taken — mirrors logging.md §1's self_recovery recipe. resume_wait (a typo'd
# variant of resumed_wait, seen 5x in issue #127) is exactly the class the substitution below
# catches: hand-typed near-misses, not just genuinely new branches.
LOG_SELF_RECOVERY_ACTION_ENUM="resumed_wait retried_enter worker_abandon_retry task_recreate_retry escalated_spawn_failure none_decision_gate_self_timed_out_worker_proceeded UNMAPPED_BRANCH"

# `repo` (issue #158) is REQUIRED on every event all three helpers write: the logs directory is
# shared by every repository this pipeline runs against, and `issue` numbers collide across repos
# (observed: unrelated sleeptimegrt-skills/toss-* records matched issue="23" during a
# selah-android retro). The value is the issue tracker's repository identifier exactly as the
# pipeline invocation received it as "대상 repo" (GitHub: owner/name) — passed down the spec
# chain, never re-derived per writer (e.g. from `git remote`), so orca-retro's (repo, issue)
# composite filter can rely on string equality.
# `--attempt` (issue #128) is the optional implementation-attempt number for orca-workflow-task
# §2's generate dispatch: it joins the assign record with CONTRACT_DIR's eval-report-a<k>.json, so
# "was attempt k really dispatched to orca-task-runner" is answerable from logs alone (issue #114
# had zero role=task-runner assigns against 4 evaluator rounds — indistinguishable from the
# coordinator editing code itself). Empty value = omit the field entirely (#127's omission rule,
# same policy as log_outcome's optional flags); non-integer = caller error.
log_dispatch() {
  local skill="" role="" issue="" repo="" task_id="" task_id_set=0 terminal="" worktree="" \
        provider="" model="" effort="" spec_text="" attempt=""
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
      --repo) repo="$2"; shift 2 ;;
      --task-id) task_id="$2"; task_id_set=1; shift 2 ;;
      --terminal) terminal="$2"; shift 2 ;;
      --worktree) worktree="$2"; shift 2 ;;
      --provider) provider="$2"; shift 2 ;;
      --model) model="$2"; shift 2 ;;
      --effort) effort="$2"; shift 2 ;;
      --spec-text) spec_text="$2"; shift 2 ;;
      --attempt) attempt="$2"; shift 2 ;;
      *) echo "log_dispatch: unknown argument: $1" >&2; return 64 ;;
    esac
  done

  # Portable required-argument check — see the PORTABILITY note above. --task-id is deliberately
  # excluded here: it is optional (relay/omit rule), not a bug if never passed.
  local missing=""
  [ -n "$skill" ]     || missing="$missing --skill"
  [ -n "$role" ]      || missing="$missing --role"
  [ -n "$issue" ]     || missing="$missing --issue"
  [ -n "$repo" ]      || missing="$missing --repo"
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

  if [ -n "$attempt" ]; then
    case "$attempt" in *[!0-9]*)
      echo "log_dispatch: --attempt must be a non-negative integer (got: \"$attempt\")" >&2
      return 64 ;;
    esac
  fi

  # --task-id explicitly passed but empty is a caller error, not a relay dispatch — see the
  # task_id_set note above (contract round 2 residual risk #1).
  if [ "$task_id_set" = "1" ] && [ -z "$task_id" ]; then
    echo "log_dispatch: --task-id was passed an empty value — omit the flag entirely for a relay" \
      "dispatch (logging.md §1's relay/omit rule), or pass a real task_id" >&2
    return 64
  fi

  # --provider validation (issue #90). The canonical set (claude-code|codex|agy) is (a) a hardcoded
  # mirror of the basenames under ~/.agents/orca-workflows/models/*.md — that directory is the single
  # source of truth for which providers exist. (b) When a new provider doc is added under models/,
  # this hardcoded list must be updated alongside it, or the new provider will be rejected here.
  # (c) It is not derived by globbing models/ at runtime because this script must keep working in
  # contexts where that directory doesn't exist — e.g. the pytest suite sources this file against an
  # isolated $HOME with no ~/.agents tree — and because doing so would add another bash/zsh
  # portability difference on top of the ones the PORTABILITY note above already constrains against.
  case "$provider" in
    claude-code|codex|agy) ;;
    claude)
      echo "log_dispatch: --provider \"claude\" is a deprecated alias — normalizing to" \
        "\"claude-code\"" >&2
      provider="claude-code"
      ;;
    *)
      echo "log_dispatch: --provider must be one of claude-code|codex|agy (got: \"$provider\")" >&2
      return 64
      ;;
  esac

  local logs_dir="$HOME/.local/state/orca-workflows/logs"
  install -d -m 700 "$logs_dir" || return $?

  local assign_target="$logs_dir/assignments-$(date -u +%F).jsonl"
  local assign_line
  if [ "$task_id_set" = "1" ]; then
    assign_line="$(jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg role "$role" --arg issue "$issue" \
      --arg repo "$repo" \
      --arg task_id "$task_id" --arg provider "$provider" --arg model "$model" --arg effort "$effort" \
      --arg terminal "$terminal" --arg worktree "$worktree" \
      '{ts:$ts, event:"assign", skill:$skill, role:$role, issue:$issue, repo:$repo, task_id:$task_id,
        provider:$provider, model:$model, effort:$effort, terminal:$terminal, worktree:$worktree}')" \
      || return $?
  else
    # logging.md §1's relay/omit rule: no real task_id → omit the field (never an empty string)
    # and flag relay:true.
    assign_line="$(jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg role "$role" --arg issue "$issue" \
      --arg repo "$repo" \
      --arg provider "$provider" --arg model "$model" --arg effort "$effort" \
      --arg terminal "$terminal" --arg worktree "$worktree" \
      '{ts:$ts, event:"assign", skill:$skill, role:$role, issue:$issue, repo:$repo,
        provider:$provider, model:$model, effort:$effort, terminal:$terminal, worktree:$worktree,
        relay:true}')" \
      || return $?
  fi
  [ -n "$attempt" ] && { assign_line="$(printf '%s' "$assign_line" | jq -c --argjson v "$attempt" '. + {attempt:$v}')" || return $?; }
  printf '%s\n' "$assign_line" >> "$assign_target" || return $?
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

    jq -cn --arg issue "$issue" --arg repo "$repo" --arg skill "$skill" --arg role "$role" \
      --arg terminal "$terminal" \
      --arg created_at "$(date -u +%FT%TZ)" \
      --argjson skill_version "$sv_json" --argjson orca_workflows_commit "$owc_json" \
      --argjson orca_app_version "$oav_json" \
      '{type:"meta", issue:$issue, repo:$repo, skill:$skill, role:$role, terminal:$terminal,
        created_at:$created_at,
        skill_version:$skill_version, orca_workflows_commit:$orca_workflows_commit,
        orca_app_version:$orca_app_version}' \
      >> "$term_log"
    chmod 600 "$term_log"
  fi

  jq -cn --arg ts "$(date -u +%FT%TZ)" --arg content "$spec_text" \
    '{ts:$ts, direction:"sent", content:$content}' >> "$term_log"
}

# Internal: validate a value against a space-separated enum list. Portable across bash/zsh (see
# the PORTABILITY note above): substring match on the padded list instead of word-splitting a
# loop (zsh doesn't split unquoted variables) or a case pattern built from a variable (a `|` in
# an expanded variable is a literal, not alternation, in bash). Values containing characters
# outside [A-Za-z0-9_] are rejected outright — whitespace in particular could false-match across
# adjacent list members.
_log_enum_has() {
  # $1 = space-separated enum list, $2 = candidate value
  case "$2" in
    ''|*[!A-Za-z0-9_]*) return 1 ;;
  esac
  case " $1 " in
    *" $2 "*) return 0 ;;
    *) return 1 ;;
  esac
}

# Internal: append one already-built JSON line to a log file with logging.md §1's dir/permission
# convention. $1 = target file, $2 = JSON line.
_log_append() {
  install -d -m 700 "$HOME/.local/state/orca-workflows/logs" || return $?
  printf '%s\n' "$2" >> "$1" || return $?
  chmod 600 "$1"
}

# log_outcome — the ONLY sanctioned writer of `"event":"outcome"` records (logging.md §1).
# Written for issues #105/#116/#138 (enum values invented ad-hoc, bypassing the documented
# UNMAPPED_BRANCH safeguard, five separate times) and #116 (hand-copied printf dropping the fixed
# `event`/`retry` fields — the same defect log_dispatch already killed for `assign` in issue #68).
#
#   source ~/.agents/orca-workflows/scripts/log_dispatch.sh
#   log_outcome --skill <skill> --issue <issue-num> --repo <대상 repo> --outcome <value> --retry <n> \
#     [--round <n>] [--filed <n>] [--commented <n>] [--discarded <n>] [--detail <text>] \
#     [--blocked-by <issue-num>] [--raw-outcome <text>] [--schema-gap-issue <slug>]
#
# - --skill/--issue/--outcome/--retry are required: they are the recipe's fixed fields, and #116's
#   observed defect was precisely a fixed field (retry) silently dropped at one call site.
# - Optional flags are the documented per-call-site extras (round: CONTRACT_*; filed/commented/
#   discarded: RETRO_DONE; detail: MANUAL_RECOVERY_COMPLETED; blocked_by: skipped, issue #138).
#   Undocumented ad-hoc extras are deliberately NOT accepted — that openness is how field drift
#   starts (#138's blocked_by began as an undocumented invention).
# - An optional flag passed an EMPTY value is treated as "omit the field entirely", never written
#   as "" (issue #127: conditional fields written as empty strings violate the omission rule; the
#   helper makes that mistake impossible). This intentionally differs from log_dispatch's
#   --task-id, where explicit-empty is a caller error — there, emptiness would silently change
#   relay semantics; here it can only mean "nothing to record".
# - Unknown --outcome value: the record is STILL WRITTEN (logging.md: never omit the outcome
#   event) as outcome=UNMAPPED_BRANCH with raw_outcome=<attempted value> and schema_gap_issue
#   (caller-supplied, else "unfiled" — file the schema-gap issue on sleeptimegrt-skills and pass
#   --schema-gap-issue next time). A warning goes to stderr and the function returns 0: enum
#   drift must surface in the log and on stderr, not fail the pipeline mid-run.
# - --raw-outcome/--schema-gap-issue with a valid (non-UNMAPPED_BRANCH) outcome are dropped with
#   a warning — logging.md marks them "only when outcome=UNMAPPED_BRANCH".
log_outcome() {
  local skill="" issue="" repo="" outcome="" retry="" round="" filed="" commented="" discarded="" \
        detail="" blocked_by="" raw_outcome="" schema_gap_issue=""
  while [ $# -gt 0 ]; do
    # Same value-less-trailing-flag guard as log_dispatch (shift 2 on the last argument hangs the
    # loop in both bash and zsh — see the note there).
    if [ $# -lt 2 ]; then
      echo "log_outcome: $1 requires a value" >&2
      return 64
    fi
    case "$1" in
      --skill) skill="$2"; shift 2 ;;
      --issue) issue="$2"; shift 2 ;;
      --repo) repo="$2"; shift 2 ;;
      --outcome) outcome="$2"; shift 2 ;;
      --retry) retry="$2"; shift 2 ;;
      --round) round="$2"; shift 2 ;;
      --filed) filed="$2"; shift 2 ;;
      --commented) commented="$2"; shift 2 ;;
      --discarded) discarded="$2"; shift 2 ;;
      --detail) detail="$2"; shift 2 ;;
      --blocked-by) blocked_by="$2"; shift 2 ;;
      --raw-outcome) raw_outcome="$2"; shift 2 ;;
      --schema-gap-issue) schema_gap_issue="$2"; shift 2 ;;
      *) echo "log_outcome: unknown argument: $1" >&2; return 64 ;;
    esac
  done

  local missing=""
  [ -n "$skill" ]   || missing="$missing --skill"
  [ -n "$issue" ]   || missing="$missing --issue"
  [ -n "$repo" ]    || missing="$missing --repo"
  [ -n "$outcome" ] || missing="$missing --outcome"
  [ -n "$retry" ]   || missing="$missing --retry"
  if [ -n "$missing" ]; then
    echo "log_outcome: missing required argument(s):$missing" >&2
    return 64
  fi

  # Numeric fields go into the JSON via --argjson (so consumers get numbers, not strings) —
  # validate first so a bad value is a clear caller error instead of a cryptic jq failure.
  case "$retry" in *[!0-9]*)
    echo "log_outcome: --retry must be a non-negative integer (got: \"$retry\")" >&2; return 64 ;;
  esac
  local numfield numval
  for numfield in round filed commented discarded; do
    case "$numfield" in
      round) numval="$round" ;; filed) numval="$filed" ;;
      commented) numval="$commented" ;; discarded) numval="$discarded" ;;
    esac
    if [ -n "$numval" ]; then
      case "$numval" in *[!0-9]*)
        echo "log_outcome: --$numfield must be a non-negative integer (got: \"$numval\")" >&2
        return 64 ;;
      esac
    fi
  done

  # Enum validation — the whole point of this helper (issues #105/#138). Unknown value → forced
  # UNMAPPED_BRANCH substitution per logging.md §1's documented safeguard, never a hard failure.
  if ! _log_enum_has "$LOG_OUTCOME_ENUM" "$outcome"; then
    raw_outcome="$outcome"
    outcome="UNMAPPED_BRANCH"
    [ -n "$schema_gap_issue" ] || schema_gap_issue="unfiled"
    echo "log_outcome: WARNING — outcome \"$raw_outcome\" is not in the canonical enum" \
      "(LOG_OUTCOME_ENUM in ${BASH_SOURCE:-log_dispatch.sh}); writing outcome=UNMAPPED_BRANCH with" \
      "raw_outcome preserved and schema_gap_issue=\"$schema_gap_issue\". Do not invent enum values" \
      "(#62/#69/#86/#105/#138) — file a schema-gap issue on sleeptimegrt-skills and pass" \
      "--schema-gap-issue <slug>." >&2
  fi

  if [ "$outcome" = "UNMAPPED_BRANCH" ]; then
    # Explicit --outcome UNMAPPED_BRANCH passthrough: raw_outcome should say what was observed.
    [ -n "$schema_gap_issue" ] || schema_gap_issue="unfiled"
    [ -n "$raw_outcome" ] || echo "log_outcome: WARNING — outcome=UNMAPPED_BRANCH without" \
      "--raw-outcome; the record loses the observed branch string (logging.md §1)" >&2
  else
    if [ -n "$raw_outcome" ] || [ -n "$schema_gap_issue" ]; then
      echo "log_outcome: WARNING — --raw-outcome/--schema-gap-issue only apply when" \
        "outcome=UNMAPPED_BRANCH; dropping them (logging.md §1 conditional-field rule)" >&2
      raw_outcome=""
      schema_gap_issue=""
    fi
  fi

  # blocked_by is conditionally REQUIRED for skipped and dropped otherwise (issue #138).
  if [ "$outcome" = "skipped" ]; then
    [ -n "$blocked_by" ] || echo "log_outcome: WARNING — outcome=skipped without --blocked-by" \
      "(required conditional field, issue #138); writing the record without it" >&2
  elif [ -n "$blocked_by" ]; then
    echo "log_outcome: WARNING — --blocked-by only applies when outcome=skipped; dropping it" >&2
    blocked_by=""
  fi

  local line
  line="$(jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg issue "$issue" \
    --arg repo "$repo" --arg outcome "$outcome" --argjson retry "$retry" \
    '{ts:$ts, event:"outcome", skill:$skill, issue:$issue, repo:$repo, outcome:$outcome, retry:$retry}')" \
    || return $?
  # Optional fields: appended only when non-empty — an empty value can never reach the JSON
  # (issue #127's omission rule, enforced structurally).
  [ -n "$round" ]     && { line="$(printf '%s' "$line" | jq -c --argjson v "$round" '. + {round:$v}')" || return $?; }
  [ -n "$filed" ]     && { line="$(printf '%s' "$line" | jq -c --argjson v "$filed" '. + {filed:$v}')" || return $?; }
  [ -n "$commented" ] && { line="$(printf '%s' "$line" | jq -c --argjson v "$commented" '. + {commented:$v}')" || return $?; }
  [ -n "$discarded" ] && { line="$(printf '%s' "$line" | jq -c --argjson v "$discarded" '. + {discarded:$v}')" || return $?; }
  [ -n "$detail" ]    && { line="$(printf '%s' "$line" | jq -c --arg v "$detail" '. + {detail:$v}')" || return $?; }
  [ -n "$blocked_by" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$blocked_by" '. + {blocked_by:$v}')" || return $?; }
  [ -n "$raw_outcome" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$raw_outcome" '. + {raw_outcome:$v}')" || return $?; }
  [ -n "$schema_gap_issue" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$schema_gap_issue" '. + {schema_gap_issue:$v}')" || return $?; }

  _log_append "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl" "$line"
}

# log_self_recovery — the ONLY sanctioned writer of `"event":"self_recovery"` records
# (logging.md §1). Written for issue #127: the hand-copied printf in self-recovery.md always
# emitted new_dispatch_id/raw_action/schema_gap_issue as "%s" — so valid-action records carried
# forbidden empty-string conditional fields (8x observed), and a hand-typed action_taken typo
# (resume_wait, 5x) bypassed the UNMAPPED_BRANCH safeguard. Same defect class as #105/#138, per
# #127's fix direction ("extend the helper's enum + conditional-field validation to
# self_recovery").
#
#   log_self_recovery --skill <skill> --issue <issue-num> --repo <대상 repo> --task-id <task_id> \
#     --dispatch-id <dispatch_id> --terminal <handle> --terminal-status <alive|dead|stuck_draft> \
#     --action-taken <value> [--waited-ms <n>] [--new-dispatch-id <id>] [--raw-action <text>] \
#     [--schema-gap-issue <slug>] [--wave-index <n>]
#
# - Target file is derived from --skill per logging.md §1: orca-task-runner → waves-<date>.jsonl
#   (with --wave-index as its documented join key), everything else → assignments-<date>.jsonl
#   (--wave-index dropped with a warning — those skills have no wave concept).
# - --waited-ms omitted/empty → JSON null (a fixed field whose value can genuinely be unknown —
#   observed null in real records), NOT omitted; all other empty optionals are omitted (#127).
# - --terminal-status has no documented substitution safeguard (logging.md defines no raw_* field
#   for it), so an unknown value is a hard caller error (return 64) — same policy as
#   log_dispatch's --provider validation (issue #90) — rather than silently persisting a typo.
# - --action-taken outside LOG_SELF_RECOVERY_ACTION_ENUM gets the same UNMAPPED_BRANCH
#   substitution as log_outcome (raw_action=<attempted>, schema_gap_issue default "unfiled",
#   stderr warning, exit 0) because logging.md documents exactly that safeguard for this field.
# - --new-dispatch-id is only legal when action_taken is worker_abandon_retry|task_recreate_retry
#   (dropped with a warning otherwise; warned-if-missing when it is one of those two).
log_self_recovery() {
  local skill="" issue="" repo="" task_id="" dispatch_id="" terminal="" waited_ms="" terminal_status="" \
        action_taken="" new_dispatch_id="" raw_action="" schema_gap_issue="" wave_index=""
  while [ $# -gt 0 ]; do
    if [ $# -lt 2 ]; then
      echo "log_self_recovery: $1 requires a value" >&2
      return 64
    fi
    case "$1" in
      --skill) skill="$2"; shift 2 ;;
      --issue) issue="$2"; shift 2 ;;
      --repo) repo="$2"; shift 2 ;;
      --task-id) task_id="$2"; shift 2 ;;
      --dispatch-id) dispatch_id="$2"; shift 2 ;;
      --terminal) terminal="$2"; shift 2 ;;
      --waited-ms) waited_ms="$2"; shift 2 ;;
      --terminal-status) terminal_status="$2"; shift 2 ;;
      --action-taken) action_taken="$2"; shift 2 ;;
      --new-dispatch-id) new_dispatch_id="$2"; shift 2 ;;
      --raw-action) raw_action="$2"; shift 2 ;;
      --schema-gap-issue) schema_gap_issue="$2"; shift 2 ;;
      --wave-index) wave_index="$2"; shift 2 ;;
      *) echo "log_self_recovery: unknown argument: $1" >&2; return 64 ;;
    esac
  done

  local missing=""
  [ -n "$skill" ]           || missing="$missing --skill"
  [ -n "$issue" ]           || missing="$missing --issue"
  [ -n "$repo" ]            || missing="$missing --repo"
  [ -n "$task_id" ]         || missing="$missing --task-id"
  [ -n "$dispatch_id" ]     || missing="$missing --dispatch-id"
  [ -n "$terminal" ]        || missing="$missing --terminal"
  [ -n "$terminal_status" ] || missing="$missing --terminal-status"
  [ -n "$action_taken" ]    || missing="$missing --action-taken"
  if [ -n "$missing" ]; then
    echo "log_self_recovery: missing required argument(s):$missing" >&2
    return 64
  fi

  if [ -n "$waited_ms" ]; then
    case "$waited_ms" in *[!0-9]*)
      echo "log_self_recovery: --waited-ms must be a non-negative integer (got: \"$waited_ms\")" >&2
      return 64 ;;
    esac
  fi
  if [ -n "$wave_index" ]; then
    case "$wave_index" in *[!0-9]*)
      echo "log_self_recovery: --wave-index must be a non-negative integer (got: \"$wave_index\")" >&2
      return 64 ;;
    esac
  fi

  case "$terminal_status" in
    alive|dead|stuck_draft) ;;
    *)
      echo "log_self_recovery: --terminal-status must be one of alive|dead|stuck_draft (got:" \
        "\"$terminal_status\")" >&2
      return 64
      ;;
  esac

  if ! _log_enum_has "$LOG_SELF_RECOVERY_ACTION_ENUM" "$action_taken"; then
    raw_action="$action_taken"
    action_taken="UNMAPPED_BRANCH"
    [ -n "$schema_gap_issue" ] || schema_gap_issue="unfiled"
    echo "log_self_recovery: WARNING — action_taken \"$raw_action\" is not in the canonical enum" \
      "(LOG_SELF_RECOVERY_ACTION_ENUM); writing action_taken=UNMAPPED_BRANCH with raw_action" \
      "preserved and schema_gap_issue=\"$schema_gap_issue\" (#127 — do not hand-type enum values;" \
      "file a schema-gap issue and pass --schema-gap-issue <slug>)." >&2
  fi

  if [ "$action_taken" = "UNMAPPED_BRANCH" ]; then
    [ -n "$schema_gap_issue" ] || schema_gap_issue="unfiled"
    [ -n "$raw_action" ] || echo "log_self_recovery: WARNING — action_taken=UNMAPPED_BRANCH" \
      "without --raw-action; the record loses the observed action string (logging.md §1)" >&2
  else
    if [ -n "$raw_action" ] || [ -n "$schema_gap_issue" ]; then
      echo "log_self_recovery: WARNING — --raw-action/--schema-gap-issue only apply when" \
        "action_taken=UNMAPPED_BRANCH; dropping them (logging.md §1 conditional-field rule)" >&2
      raw_action=""
      schema_gap_issue=""
    fi
  fi

  case "$action_taken" in
    worker_abandon_retry|task_recreate_retry)
      [ -n "$new_dispatch_id" ] || echo "log_self_recovery: WARNING — action_taken=$action_taken" \
        "without --new-dispatch-id (logging.md §1 expects the retry's new dispatch id here)" >&2
      ;;
    *)
      if [ -n "$new_dispatch_id" ]; then
        echo "log_self_recovery: WARNING — --new-dispatch-id only applies when" \
          "action_taken=worker_abandon_retry|task_recreate_retry; dropping it" >&2
        new_dispatch_id=""
      fi
      ;;
  esac

  # Target routing per logging.md §1: only orca-task-runner writes self_recovery to the waves
  # file (joinable with wave_start/wave_end via wave_index); coordinators use assignments.
  local target
  if [ "$skill" = "orca-task-runner" ]; then
    target="$HOME/.local/state/orca-workflows/logs/waves-$(date -u +%F).jsonl"
  else
    target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
    if [ -n "$wave_index" ]; then
      echo "log_self_recovery: WARNING — --wave-index only applies to orca-task-runner" \
        "(waves-<date>.jsonl); dropping it" >&2
      wave_index=""
    fi
  fi

  local waited_json="null"
  [ -n "$waited_ms" ] && waited_json="$waited_ms"

  local line
  line="$(jq -cn --arg ts "$(date -u +%FT%TZ)" --arg skill "$skill" --arg issue "$issue" \
    --arg repo "$repo" \
    --arg task_id "$task_id" --arg dispatch_id "$dispatch_id" --arg terminal "$terminal" \
    --argjson waited_ms "$waited_json" --arg terminal_status "$terminal_status" \
    --arg action_taken "$action_taken" \
    '{ts:$ts, event:"self_recovery", skill:$skill, issue:$issue, repo:$repo, task_id:$task_id,
      dispatch_id:$dispatch_id, terminal:$terminal, waited_ms:$waited_ms,
      terminal_status:$terminal_status, action_taken:$action_taken}')" || return $?
  [ -n "$wave_index" ] && { line="$(printf '%s' "$line" | jq -c --argjson v "$wave_index" '. + {wave_index:$v}')" || return $?; }
  [ -n "$new_dispatch_id" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$new_dispatch_id" '. + {new_dispatch_id:$v}')" || return $?; }
  [ -n "$raw_action" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$raw_action" '. + {raw_action:$v}')" || return $?; }
  [ -n "$schema_gap_issue" ] && { line="$(printf '%s' "$line" | jq -c --arg v "$schema_gap_issue" '. + {schema_gap_issue:$v}')" || return $?; }

  _log_append "$target" "$line"
}
