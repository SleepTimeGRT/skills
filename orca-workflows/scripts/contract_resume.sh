#!/usr/bin/env bash
# contract_resume_state — reconstruct a crashed coordinator session's progress from CONTRACT_DIR
# artifacts alone (issue #156). Consumer: orca-workflow-task §0's crash-resume branch.
#
# The round/attempt/retry counters used to live only in the coordinator session's conversation
# context, so a dead session's re-invocation restarted from §1 — renegotiating an approved contract
# and re-burning passed generations. The state was already on disk the whole time
# (contract-schema.md: proposal-r<n>/verdict-r<n>/override.json/eval-report-a<k>): filename numbers
# ARE the canonical counters. This helper scans them deterministically and prints one JSON object:
#
#   source ~/.agents/orca-workflows/scripts/contract_resume.sh
#   contract_resume_state <CONTRACT_DIR> [--recent-secs <n>]
#
#   {
#     "schema_version": 1,
#     "contract": "fresh|negotiating|approved|finalized|escalated",
#     "resume":  "section-1-proposal|section-1-verdict|section-1-override|section-2|section-4|section-5",
#     "round": <n|null>,           // section-1-*: the round to (re-)run (for -override: the r3 it produces)
#     "approved_round": <n|null>,  // final contract round: approved verdict round, or max r<n> post-override (#130)
#     "attempt": <k|null>,         // section-2: attempt to run; section-4/5: last evaluated attempt
#     "retry": <n|null>,           // §4 FAIL-retry counter to carry (attempt k runs with retry k-1)
#     "outcome": <string|null>,    // section-4: PASS; section-5: CONTRACT_ESCALATE|CONTRACT_SCHEMA_STALE|FAIL|ESCALATE
#     "detail": <string|null>,
#     "recent_write": true|false   // any artifact modified within --recent-secs (default 600):
#   }                              //   the dead session's worker may still be writing — don't resume
#
# Fail-closed rules (issue #156's fix direction):
# - A file that exists but doesn't parse as a JSON object (died mid-write), or whose status/verdict
#   value is outside its schema enum, is treated as ABSENT — its producing step re-runs. Rewriting
#   the same-numbered file on that re-run is legal: contract-schema.md's append-only rule is a
#   cross-round rule (don't edit r1 during r2), not a crash-resume prohibition.
# - proposal-r3+ never has a verdict by design (override follow-up rounds, contract-schema.md
#   "override 후속 라운드", issue #130): with a valid override.json it is the final contract, not an
#   ambiguous state; without one it is an out-of-contract state and escalates.
# - The override gate below MIRRORS orca-workflow-task §1's inline routing block (verdict-r2.json
#   is the routing input, never override.json's generator-filtered unresolved_reasons). Change them
#   together; tests/test_contract_resume.py pins this side.
# - CONTRACT_SCHEMA_STALE (issue #160): override.json without proposal-r3.json is not always a
#   violation — if override.json predates the proposal-r3 requirement itself (R3_REQUIRED_SINCE
#   above), the step legitimately had no r3 to write. That case escalates to section-5 with a
#   distinct outcome instead of being silently re-run or misreported as a recording-contract
#   violation.
#
# PORTABILITY: sourced into whatever shell runs the SKILL.md block — zsh on this machine, bash in
# tests. Same portable subset as log_dispatch.sh: no arrays, no [[ ]], no ${!var}, no glob loops
# (a non-matching glob aborts the command in zsh); filenames are deterministic, so existence is
# probed by counting up instead of globbing. Requires jq.

_cr_json_object() {
  jq -e 'type=="object"' "$1" >/dev/null 2>&1
}

# contract-schema.md "override 후속 라운드" 절 도입 시점(commit 79b7c3b, issue #130) -- 이 값을
# 바꾸는 건 그 요구사항 자체가 또 바뀔 때뿐이다(현재 재도입 계획 없음, issue #160).
# orca-workflow-task SKILL.md §1의 동일 상수와 짝이다 -- 바꾸면 함께 바꾼다.
# touch -t 포맷 [[CC]YY]MMDDhhmm[.SS], KST(Asia/Seoul) 기준으로 해석되도록 TZ를 아래서 명시
# 고정한다 -- touch -t는 인자 없이 부르면 프로세스의 TZ 환경변수(호스트 로컬 설정)로 해석하므로,
# 고정하지 않으면 이 머신이 KST가 아닌 곳에서 돌 때 최대 수 시간 오차가 생긴다(issue #160 리뷰에서
# 실측: TZ=UTC로 같은 문자열을 해석하면 9시간 차이 나는 다른 epoch가 나옴).
R3_REQUIRED_SINCE='202608120944.57'

_cr_predates_r3_gate() {
  # $1 = probed file. Echoes 1 (mtime on/before R3_REQUIRED_SINCE -> stale) or 0 (after -> not
  # stale) to stdout. Reuses the touch-a-reference-file + find -newer mechanism the recent_write
  # guard below already proves out: stat -f/-c epoch parsing risks a BSD/GNU flag collision (GNU
  # stat -f means "filesystem info", not mtime) silently feeding garbage into a numeric comparison.
  local ref
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-resume-r3gate.XXXXXX")" || return $?
  TZ='Asia/Seoul' touch -t "$R3_REQUIRED_SINCE" "$ref" 2>/dev/null
  if [ -n "$(find "$(dirname "$1")" -maxdepth 1 -name "$(basename "$1")" -newer "$ref" 2>/dev/null)" ]; then
    printf '0'
  else
    printf '1'
  fi
  rm -f "$ref"
}

contract_resume_state() {
  local dir="" recent_secs=600
  while [ $# -gt 0 ]; do
    case "$1" in
      --recent-secs)
        if [ $# -lt 2 ]; then
          echo "contract_resume_state: --recent-secs requires a value" >&2
          return 64
        fi
        recent_secs="$2"; shift 2 ;;
      *)
        if [ -n "$dir" ]; then
          echo "contract_resume_state: unexpected argument: $1" >&2
          echo "usage: contract_resume_state <CONTRACT_DIR> [--recent-secs <n>]" >&2
          return 64
        fi
        dir="$1"; shift ;;
    esac
  done
  if [ -z "$dir" ]; then
    echo "usage: contract_resume_state <CONTRACT_DIR> [--recent-secs <n>]" >&2
    return 64
  fi
  case "$recent_secs" in ''|*[!0-9]*)
    echo "contract_resume_state: --recent-secs must be a non-negative integer (got: \"$recent_secs\")" >&2
    return 64 ;;
  esac

  # Counter cap: rounds are limited to 2 and FAIL retries to 2 (max attempt 3) by
  # orca-workflow-task §1/§4, so 20 is unreachable headroom, not a tunable.
  local cap=20

  # ── scan negotiation rounds ──────────────────────────────────────────────────────────────
  # maxp/maxv = highest round with a VALID proposal/verdict; approved_round = highest approved.
  local n=1 maxp=0 maxv=0 approved_round=0 vstatus=""
  while [ "$n" -le "$cap" ]; do
    { [ -f "$dir/proposal-r$n.json" ] || [ -f "$dir/verdict-r$n.json" ]; } || break
    if [ -f "$dir/proposal-r$n.json" ] && _cr_json_object "$dir/proposal-r$n.json"; then
      maxp=$n
    fi
    if [ -f "$dir/verdict-r$n.json" ]; then
      vstatus="$(jq -r 'if type=="object" then (.status // "") else "" end' "$dir/verdict-r$n.json" 2>/dev/null || printf '')"
      case "$vstatus" in
        approved) maxv=$n; approved_round=$n ;;
        rejected) maxv=$n ;;
        *) : ;;   # unparseable or out-of-enum status → treated absent (verdict step re-runs)
      esac
    fi
    n=$((n+1))
  done

  local override_ok=0
  if [ -f "$dir/override.json" ] && _cr_json_object "$dir/override.json"; then
    override_ok=1
  fi

  # ── scan implementation attempts ─────────────────────────────────────────────────────────
  # ev is declared here, not inside the loop: in zsh, re-running `local ev` on an already-set
  # local PRINTS `ev=<value>` to stdout (typeset's re-declaration behavior), corrupting the JSON
  # output from iteration 2 onward.
  local k=1 maxa=0 last_eval="" ev=""
  while [ "$k" -le "$cap" ]; do
    [ -f "$dir/eval-report-a$k.json" ] || break
    ev="$(jq -r 'if type=="object" then (.verdict // "") else "" end' "$dir/eval-report-a$k.json" 2>/dev/null || printf '')"
    case "$ev" in
      PASS|FAIL|ESCALATE) maxa=$k; last_eval="$ev" ;;
      *) : ;;   # died mid-write → that attempt's evaluation re-runs via generation re-burn
    esac
    k=$((k+1))
  done

  # ── recent-write guard ───────────────────────────────────────────────────────────────────
  # find -newer against a backdated reference file: portable across BSD (macOS: date -v) and
  # GNU (date -d) userlands, unlike stat's -f/-c split.
  local recent_write=false
  if [ -d "$dir" ] && [ "$recent_secs" -gt 0 ]; then
    local ref ts
    ref="$(mktemp "${TMPDIR:-/tmp}/contract-resume-ref.XXXXXX")" || return $?
    ts="$(date -v-"${recent_secs}"S +%Y%m%d%H%M.%S 2>/dev/null || date -d "-${recent_secs} seconds" +%Y%m%d%H%M.%S)"
    touch -t "$ts" "$ref" 2>/dev/null
    if [ -n "$(find "$dir" -maxdepth 1 -name '*.json' -newer "$ref" 2>/dev/null | head -1)" ]; then
      recent_write=true
    fi
    rm -f "$ref"
  fi

  # ── decide resume point ──────────────────────────────────────────────────────────────────
  local contract="" resume="" round="null" approved="null" attempt="null" retry="null" \
        outcome="null" detail="null"

  if [ "$approved_round" -gt 0 ]; then
    contract="approved"
    approved="$approved_round"
  elif [ "$override_ok" = "1" ]; then
    # Round limit reached with a recorded override — run the §1 mechanical gate (mirror; see
    # the header note). Routing input is evaluator-owned verdict-r2.json, fail-closed when it
    # is missing/invalid.
    if [ ! -f "$dir/verdict-r2.json" ] || ! _cr_json_object "$dir/verdict-r2.json"; then
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"override.json exists without a valid verdict-r2.json (fail-closed)"'
    elif jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r2.json" >/dev/null 2>&1; then
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"ac_fidelity disagreement unresolved at the round limit"'
    elif [ "$maxp" -lt 3 ]; then
      if [ "$(_cr_predates_r3_gate "$dir/override.json")" = "1" ]; then
        # override.json predates the proposal-r3 requirement itself (issue #160) — not a
        # recording-contract violation and not "died mid-write" either: the step legitimately had
        # no r3 to write under the rules that existed when it ran. Escalate distinctly so a human
        # doesn't misread this as generator misconduct.
        contract="escalated"; resume="section-5"; outcome='"CONTRACT_SCHEMA_STALE"'
        detail='"override.json predates the proposal-r3 requirement (commit 79b7c3b, 2026-08-12T09:44:57+09:00) — not a violation, a pre-gate session"'
      else
        # The override step writes override.json THEN proposal-r3.json (the final contract —
        # contract-schema.md "override 후속 라운드", issue #130). override without r3 on resume
        # means the step died between the two writes — re-burn it. (The in-session §1 gate treats
        # the same file state as a recording-contract violation and escalates instead: there the
        # generator claimed completion via worker_done, so "died mid-write" is ruled out.)
        contract="negotiating"; resume="section-1-override"; round=3
        detail='"override recorded but proposal-r3 (final contract) missing — override step died mid-write; re-run it"'
      fi
    else
      contract="finalized"
      approved="$maxp"   # correction rounds (r4+, #130) supersede r3 as the final contract
    fi
  else
    # Negotiation still in flight — resume at the first missing/invalid artifact's producer.
    if [ "$maxp" -eq 0 ] && [ "$maxv" -eq 0 ]; then
      contract="fresh"; resume="section-1-proposal"; round=1
    elif [ "$maxp" -ge 3 ]; then
      # proposal-r3+ may only exist after an override (write order is override-first) or...
      # never otherwise — an approved verdict was handled above. Out-of-contract state.
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"proposal-r3+ exists without override.json or an approved verdict (out-of-contract state)"'
    elif [ "$maxp" -gt "$maxv" ]; then
      contract="negotiating"; resume="section-1-verdict"; round="$maxp"
    else
      # last valid verdict is rejected (approved handled above); maxv >= maxp covers the
      # pathological valid-verdict-over-invalid-proposal case with the same fail-closed result
      contract="negotiating"
      if [ "$maxv" -ge 2 ]; then
        # The override step produces override.json + proposal-r3, so round names its output.
        resume="section-1-override"; round=3
        detail='"round limit reached, rejected, no override recorded — re-dispatch the generator override step"'
      else
        resume="section-1-proposal"; round=$((maxv+1))
      fi
    fi
  fi

  if [ -z "$resume" ]; then
    # Contract resolved (approved or finalized) — route on the last valid eval-report.
    # Attempt k runs with retry=k-1; §4 allows a FAIL re-dispatch while retry < 2 (max attempt 3).
    if [ "$maxa" -eq 0 ]; then
      resume="section-2"; attempt=1; retry=0
    else
      case "$last_eval" in
        PASS)
          resume="section-4"; outcome='"PASS"'; attempt="$maxa"; retry=$((maxa-1)) ;;
        ESCALATE)
          resume="section-5"; outcome='"ESCALATE"'; attempt="$maxa"; retry=$((maxa-1)) ;;
        FAIL)
          if [ "$maxa" -le 2 ]; then
            resume="section-2"; attempt=$((maxa+1)); retry="$maxa"
          else
            resume="section-5"; outcome='"FAIL"'; attempt="$maxa"; retry=2
            detail='"FAIL retry budget exhausted"'
          fi ;;
      esac
    fi
  fi

  jq -cn \
    --arg contract "$contract" --arg resume "$resume" \
    --argjson round "$round" --argjson approved_round "$approved" \
    --argjson attempt "$attempt" --argjson retry "$retry" \
    --argjson outcome "$outcome" --argjson detail "$detail" \
    --argjson recent_write "$recent_write" \
    '{schema_version: 1, contract: $contract, resume: $resume, round: $round,
      approved_round: $approved_round, attempt: $attempt, retry: $retry,
      outcome: $outcome, detail: $detail, recent_write: $recent_write}'
}
