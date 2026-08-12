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
# - proposal-r3 CAN have its own verdict now (round-cap conditional extension, contract-schema.md
#   "라운드 2→3 조건부 연장"): a negotiated round 3 that fires only when verdict-r2 is valid,
#   rejected, and plan_coverage-only (no ac_fidelity). proposal-r3 without override.json is
#   therefore legitimate ONLY under that same condition (verdict-r2 valid+rejected+plan_coverage-
#   only) -- any other verdict-r2 state (missing/invalid/wrong-round, or ac_fidelity present) means
#   proposal-r3 was written when it shouldn't have been, an out-of-contract state that escalates.
#   proposal-r4+ without override.json is unconditionally out-of-contract and escalates (override
#   follow-up rounds only, contract-schema.md "override 후속 라운드", issue #130): with a valid
#   final_round=3 override.json it is the final contract, not an ambiguous state.
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

# Round-cap conditional extension (docs/superpowers/specs/2026-08-12-contract-sprint-improvements-design.md):
# before this gate, a round-2 rejection with plan_coverage-only reasons went straight to override
# (final_round=2, finalizing at proposal-r3). After this gate, that same rejection instead gets one
# more negotiated round (proposal-r3/verdict-r3) before override -- and override.json's final_round
# becomes 3, with proposal-r4 the final contract. Same touch -t + find -newer mechanism as
# R3_REQUIRED_SINCE (via _cr_predates_gate below), disambiguates a final_round=2 override.json's
# plan_coverage-only "finalized" reading (legacy, pre-gate) from an inconsistency (post-gate,
# should never happen if orca-workflow-task §1 routes correctly).
# This constant exists only in this script (§0/crash-resume) -- orca-workflow-task SKILL.md §1 does
# NOT use it, since the live coordinator (once running the round-cap extension) never produces the
# ambiguous state it disambiguates (see contract-schema.md's "라운드 2→3 조건부 연장" section).
ROUND3_NEGOTIATION_SINCE='202608130052.00'

_cr_predates_gate() {
  # $1 = probed file. $2 = cutoff (touch -t format, e.g. R3_REQUIRED_SINCE or
  # ROUND3_NEGOTIATION_SINCE). Echoes 1 (mtime on/before cutoff -> stale) or 0 (after, OR the
  # mechanism itself failed -> not stale) to stdout. Reuses the touch-a-reference-file + find
  # -newer mechanism the recent_write guard below already proves out: stat -f/-c epoch parsing
  # risks a BSD/GNU flag collision (GNU stat -f means "filesystem info", not mtime) silently
  # feeding garbage into a numeric comparison.
  #
  # Two distinct failure modes, two distinct guards -- do not collapse them into one `find`
  # polarity choice, that was tried and empirically disproven (issue #160 final review):
  #   1. touch -t itself fails (backdating didn't happen): $ref is left at its just-created "now"
  #      mtime instead of the intended cutoff. `-newer $ref` and `! -newer $ref` are pure
  #      complements of each other, and swapping which branch prints which value cancels out --
  #      "if P then 0 else 1" and "if !P then 1 else 0" are the same function of P. Since any
  #      already-written override.json predates "now" virtually always, EITHER polarity says
  #      "not newer than $ref" and reports stale=1 when backdating silently failed -- verified by
  #      forcing touch -t to fail against a known post-gate override.json and observing
  #      CONTRACT_SCHEMA_STALE either way. The only fix for this mode is checking touch -t's own
  #      exit status directly, below -- not any find-polarity trick.
  #   2. find itself errors or matches nothing for reasons unrelated to mtime (probed path
  #      missing, directory unreadable): this is genuine "absence of evidence", where `! -newer`
  #      (require positive proof of "not newer than cutoff") correctly falls through to 0 instead
  #      of the old code's default-to-stale on no match.
  local ref cutoff="$2"
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-resume-gate.XXXXXX")" || return $?
  if ! TZ='Asia/Seoul' touch -t "$cutoff" "$ref" 2>/dev/null; then
    rm -f "$ref"
    printf '0'
    return 0
  fi
  if [ -n "$(find "$(dirname "$1")" -maxdepth 1 -name "$(basename "$1")" ! -newer "$ref" 2>/dev/null)" ]; then
    printf '1'
  else
    printf '0'
  fi
  rm -f "$ref"
}

_cr_predates_r3_gate() {
  _cr_predates_gate "$1" "$R3_REQUIRED_SINCE"
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

  # Counter cap: rounds are limited to 2 (or 3 with the plan_coverage-only conditional extension)
  # and FAIL retries to 2 (max attempt 3) by orca-workflow-task §1/§4, so 20 is unreachable
  # headroom, not a tunable.
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
    local final_round
    final_round="$(jq -r 'if type=="object" then (.final_round // "") else "" end' "$dir/override.json" 2>/dev/null || printf '')"
    if [ "$final_round" = "3" ]; then
      # New-style override after the round-3 extension: routing input is verdict-r3.json,
      # completion artifact is proposal-r4.json.
      if [ ! -f "$dir/verdict-r3.json" ] || ! _cr_json_object "$dir/verdict-r3.json"; then
        contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
        detail='"override.json (final_round=3) exists without a valid verdict-r3.json (fail-closed)"'
      elif jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r3.json" >/dev/null 2>&1; then
        contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
        detail='"ac_fidelity disagreement unresolved at the round-3 extension"'
      elif [ "$maxp" -lt 4 ]; then
        contract="negotiating"; resume="section-1-override"; round=4
        detail='"override recorded (final_round=3) but proposal-r4 (final contract) missing — override step died mid-write; re-run it"'
      else
        contract="finalized"
        approved="$maxp"
      fi
    else
      # Legacy path (final_round=2, or missing/malformed -- fail-closed to the pre-extension
      # behavior). Routing input is evaluator-owned verdict-r2.json.
      if [ ! -f "$dir/verdict-r2.json" ] || ! _cr_json_object "$dir/verdict-r2.json"; then
        contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
        detail='"override.json exists without a valid verdict-r2.json (fail-closed)"'
      elif jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r2.json" >/dev/null 2>&1; then
        contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
        detail='"ac_fidelity disagreement unresolved at the round limit"'
      elif [ "$maxp" -lt 3 ]; then
        if [ "$(_cr_predates_r3_gate "$dir/override.json")" = "1" ]; then
          contract="escalated"; resume="section-5"; outcome='"CONTRACT_SCHEMA_STALE"'
          detail='"override.json predates the proposal-r3 requirement (commit 79b7c3b, 2026-08-12T09:44:57+09:00) — not a violation, a pre-gate session — see the override.json mtime (ls -la or stat) for the exact pre-gate timestamp"'
        else
          contract="negotiating"; resume="section-1-override"; round=3
          detail='"override recorded but proposal-r3 (final contract) missing — override step died mid-write; re-run it"'
        fi
      else
        # plan_coverage-only, final_round=2, proposal-r3 present -- only valid if this predates
        # the round-3-negotiation extension (post-gate, plan_coverage-only should never reach
        # override at round 2 -- it goes through the round-3 extension instead).
        if [ "$(_cr_predates_gate "$dir/override.json" "$ROUND3_NEGOTIATION_SINCE")" = "1" ]; then
          contract="finalized"
          approved="$maxp"   # correction rounds (r4+, #130) supersede r3 as the final contract
        else
          contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
          detail='"override.json (final_round=2, plan_coverage-only) found after the round-3-negotiation extension shipped — expected a round-3 negotiation instead of an immediate override; possible coordinator/generator inconsistency"'
        fi
      fi
    fi
  else
    # Negotiation still in flight — resume at the first missing/invalid artifact's producer.
    if [ "$maxp" -eq 0 ] && [ "$maxv" -eq 0 ]; then
      contract="fresh"; resume="section-1-proposal"; round=1
    elif [ "$maxp" -ge 4 ]; then
      # proposal-r4+ may only exist after a final_round=3 override (write order is
      # override-first, same as the old r3 rule) or never otherwise. Out-of-contract state.
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"proposal-r4+ exists without override.json or an approved verdict (out-of-contract state)"'
    elif [ "$maxp" -eq 3 ] && [ "$maxp" -gt "$maxv" ] && { [ "$maxv" -ne 2 ] || jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r2.json" >/dev/null 2>&1; }; then
      # proposal-r3 without a round-3 verdict decision yet (maxp > maxv, so verdict-r3 doesn't
      # exist/isn't valid) is legitimate ONLY when the round-cap extension actually fired:
      # verdict-r2 valid+rejected+plan_coverage-only (maxv==2, no ac_fidelity -- maxv is only set
      # when verdict-r2 parsed with a valid status, per the scan loop above, so maxv==2 already
      # implies validity). Anything else (verdict-r2 missing/invalid/wrong-round, or ac_fidelity
      # present) means proposal-r3 was written when it shouldn't have been -- out-of-contract,
      # fail-closed. (maxv==3, i.e. a valid round-3 verdict already exists, is excluded by the
      # maxp>maxv guard -- that legitimate state is handled below.)
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"proposal-r3 exists without override.json, but verdict-r2 is missing/invalid or has an ac_fidelity disagreement -- the round-cap extension condition is not met (out-of-contract state)"'
    elif [ "$maxp" -gt "$maxv" ]; then
      contract="negotiating"; resume="section-1-verdict"; round="$maxp"
    else
      # last valid verdict is rejected (approved handled above); maxv >= maxp covers the
      # pathological valid-verdict-over-invalid-proposal case with the same fail-closed result
      contract="negotiating"
      if [ "$maxv" -eq 2 ] && ! jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r2.json" >/dev/null 2>&1; then
        # Round-cap conditional extension: round 2 rejected, plan_coverage-only (maxv==2 already
        # implies verdict-r2.json parsed and status=rejected, per the scan loop above) -- one more
        # negotiated round instead of an immediate override.
        resume="section-1-proposal"; round=3
      elif [ "$maxv" -eq 3 ]; then
        # The extension round (3) also rejected -- now the true round limit for this branch.
        if jq -e '[.reasons[]?.target] | index("ac_fidelity")' "$dir/verdict-r3.json" >/dev/null 2>&1; then
          contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
          detail='"ac_fidelity disagreement unresolved at the round-3 extension"'
        else
          resume="section-1-override"; round=4
          detail='"round limit reached at the extension round, rejected, no override recorded — re-dispatch the generator override step"'
        fi
      elif [ "$maxv" -ge 2 ]; then
        # maxv==2 with ac_fidelity present (the extension didn't fire): unchanged legacy path.
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
