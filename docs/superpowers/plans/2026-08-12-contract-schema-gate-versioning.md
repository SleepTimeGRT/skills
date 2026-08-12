# contract-schema 게이트 소급 적용 방지(CONTRACT_SCHEMA_STALE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `orca-workflow-task`'s r3 fail-closed gate from misclassifying override sessions that completed *before* the `proposal-r3.json` requirement existed as recording-contract violations — give them a distinct outcome (`CONTRACT_SCHEMA_STALE`) instead of `CONTRACT_ESCALATE`.

**Architecture:** A single hardcoded cutoff timestamp (`R3_REQUIRED_SINCE` = the r3-requirement's introduction commit's timestamp) is compared against `override.json`'s mtime, using the same `touch -t` + `find -newer` mechanism the codebase already uses for its `recent_write` guard. The comparison is duplicated (mirrored, not shared via a sourced function — matching this codebase's existing convention for these two sites) at the two places that currently fail-close on "override present, r3 absent": `orca-workflow-task` SKILL.md §1's live gate, and `contract_resume.sh`'s crash-resume mirror. Both route a pre-cutoff override to a new outcome value, `CONTRACT_SCHEMA_STALE`, registered like any other outcome (`log_dispatch.sh`'s enum, `logging.md`'s docs, `orca-retro`'s preventable-escalation lens carve-out).

**Tech Stack:** POSIX-portable bash/zsh (existing scripts), Python 3 + pytest (existing test suite), Markdown (SKILL.md prose consumed by an LLM agent, not machine-parsed).

## Global Constraints

- `orca-workflows/scripts/contract_resume.sh` and `skills/orca-workflow-task/SKILL.md` §1 must stay portable across bash and zsh — no arrays, no `[[ ]]`, no `${!var}`, no glob loops (existing file header comment, `contract_resume.sh:39-41`).
- The r3-requirement introduction timestamp is `2026-08-12T09:44:57+09:00` (commit `79b7c3b4cb375b42cec65228ab2bf29d702a8d50`). Every place this constant is written must cite that commit and note "change together" — do not let the two copies (SKILL.md prose, `contract_resume.sh`) drift.
- `log_dispatch.sh:79`'s `LOG_OUTCOME_ENUM` is the canonical enum; `logging.md` and `tests/test_log_outcome.py`'s `DOCUMENTED_OUTCOME_ENUM` are mirrors that must stay in sync with it (an existing test, `tests/test_log_outcome.py`, already cross-checks this — do not add the value to only one side).
- No task in this plan may add a mechanism for `contract_resume.sh` to auto-jump straight to evaluation when an implementation already exists in the worktree — that gap is intentionally out of scope (filed as [#161](https://github.com/SleepTimeGRT/skills/issues/161)). The §5 reporting text this plan adds must not imply automatic resume.
- `skills/orca-workflow-task/SKILL.md` and `skills/orca-retro/SKILL.md` are members of `orca-set` (`skills/orca-set.version`, currently `v1.1.17`) — both files changing means one version bump covers both; do not bump per-file.

---

## File Structure

| File | Responsibility |
|---|---|
| `orca-workflows/scripts/contract_resume.sh` | Detects the "override predates the r3 gate" state during crash-resume and reports it via the existing JSON output's `outcome` field. |
| `tests/test_contract_resume.py` | Pins the new detection behavior and confirms the existing "died mid-write, re-run" behavior is unchanged for post-gate overrides. |
| `orca-workflows/scripts/log_dispatch.sh` | Registers `CONTRACT_SCHEMA_STALE` as a legal `--outcome` value (the machine-checked authority). |
| `tests/test_log_outcome.py` | Existing cross-check test; its `DOCUMENTED_OUTCOME_ENUM` list must include the new value or the cross-check fails. |
| `orca-workflows/logging.md` | Human-readable outcome docs — axis placement + explanation paragraph. |
| `skills/orca-workflow-task/SKILL.md` | §1: the live in-session gate that must distinguish stale-override from true violation. §5: the human-facing report text for the new outcome. |
| `orca-workflows/contract-schema.md` | One cross-reference note in the "override 후속 라운드" section pointing at the new escape hatch (does not duplicate the constant). |
| `skills/orca-retro/SKILL.md` | Lens 3 carve-out so `CONTRACT_SCHEMA_STALE` records aren't mistaken for a fresh preventable-escalation defect. |
| `skills/orca-set.version` | Version bump (`v1.1.17` → `v1.1.18`) covering the two `skills/` members touched. |

---

### Task 1: `contract_resume.sh` — detect pre-gate override and report `CONTRACT_SCHEMA_STALE`

**Files:**
- Modify: `orca-workflows/scripts/contract_resume.sh:14-24` (header JSON-shape comment), `:27-37` (fail-closed rules comment), `:44-46` (after `_cr_json_object`, new constant+helper), `:151-158` (the `elif [ "$maxp" -lt 3 ]` branch)
- Test: `tests/test_contract_resume.py`

**Interfaces:**
- Produces: `R3_REQUIRED_SINCE` (string constant, `touch -t` format `'202608120944.57'`) and `_cr_predates_r3_gate()` (shell function: `$1` = file path, echoes `1` if that file's mtime is on/before the cutoff, else `0`). Both are consumed only within this file — Task 3 defines its *own* copy in SKILL.md prose (mirrored, not sourced; see Global Constraints).
- Produces: `contract_resume_state`'s JSON output may now contain `"outcome": "CONTRACT_SCHEMA_STALE"` (in addition to the existing `CONTRACT_ESCALATE|FAIL|ESCALATE|PASS`) when `resume="section-5"`. Task 2 registers this string as a legal outcome elsewhere; this task only needs to emit it correctly.

- [ ] **Step 1: Write the failing test for the stale-override case**

Add to `tests/test_contract_resume.py`, directly after `test_override_without_r3_reruns_override_step` (currently ending at line 220):

```python
R3_REQUIRED_SINCE_EPOCH = 1786495497  # 2026-08-12T09:44:57+09:00 -- mirrors contract_resume.sh's R3_REQUIRED_SINCE


def _set_mtime(path: Path, epoch: float) -> None:
    """Set an absolute mtime (unlike _age, which subtracts a delta from 'now')."""
    os.utime(path, (epoch, epoch))


@pytest.mark.parametrize("shell", SHELLS)
def test_override_predating_r3_gate_reports_contract_schema_stale(tmp_path: Path, shell: str) -> None:
    """override.json completed before the proposal-r3 requirement existed -- not a violation (#160)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH - 3600)  # 1 hour before the gate
    state = _state(d, shell)
    assert state["contract"] == "escalated"
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_SCHEMA_STALE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_after_r3_gate_still_reruns_override_step(tmp_path: Path, shell: str) -> None:
    """Regression guard: an override.json written on/after the gate keeps the pre-existing
    "died mid-write, re-run it" behavior -- only pre-gate overrides get CONTRACT_SCHEMA_STALE."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, R3_REQUIRED_SINCE_EPOCH + 3600)  # 1 hour after the gate
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3
```

This file already `import os` (used by `_age`) and `import pytest`, so no new imports are needed.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python3 -m pytest tests/test_contract_resume.py -k "predating_r3_gate or after_r3_gate" -v`
Expected: `test_override_predating_r3_gate_reports_contract_schema_stale` FAILs (current code has no `CONTRACT_SCHEMA_STALE` branch, so `outcome` comes back `null`/section-1-override instead). `test_override_after_r3_gate_still_reruns_override_step` should already PASS (it exercises unmodified behavior) — if it fails, something about the setup is wrong; fix before proceeding.

- [ ] **Step 3: Add the constant and helper function**

In `orca-workflows/scripts/contract_resume.sh`, immediately after the closing `}` of `_cr_json_object()` (currently lines 44-46), insert:

```bash

# contract-schema.md "override 후속 라운드" 절 도입 시점(commit 79b7c3b, issue #130) -- 이 값을
# 바꾸는 건 그 요구사항 자체가 또 바뀔 때뿐이다(현재 재도입 계획 없음, issue #160).
# orca-workflow-task SKILL.md §1의 동일 상수와 짝이다 -- 바꾸면 함께 바꾼다.
# touch -t 포맷 [[CC]YY]MMDDhhmm[.SS] -- 이 파이프라인이 도는 머신의 로컬 TZ(KST) 기준.
R3_REQUIRED_SINCE='202608120944.57'

_cr_predates_r3_gate() {
  # $1 = probed file. Echoes 1 (mtime on/before R3_REQUIRED_SINCE -> stale) or 0 (after -> not
  # stale) to stdout. Reuses the touch-a-reference-file + find -newer mechanism the recent_write
  # guard below already proves out: stat -f/-c epoch parsing risks a BSD/GNU flag collision (GNU
  # stat -f means "filesystem info", not mtime) silently feeding garbage into a numeric comparison.
  local ref
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-resume-r3gate.XXXXXX")" || return $?
  touch -t "$R3_REQUIRED_SINCE" "$ref" 2>/dev/null
  if [ -n "$(find "$(dirname "$1")" -maxdepth 1 -name "$(basename "$1")" -newer "$ref" 2>/dev/null)" ]; then
    printf '0'
  else
    printf '1'
  fi
  rm -f "$ref"
}
```

- [ ] **Step 4: Branch on the new helper inside the `elif [ "$maxp" -lt 3 ]` block**

Replace (in `orca-workflows/scripts/contract_resume.sh`, currently lines 151-158):

```bash
    elif [ "$maxp" -lt 3 ]; then
      # The override step writes override.json THEN proposal-r3.json (the final contract —
      # contract-schema.md "override 후속 라운드", issue #130). override without r3 on resume
      # means the step died between the two writes — re-burn it. (The in-session §1 gate treats
      # the same file state as a recording-contract violation and escalates instead: there the
      # generator claimed completion via worker_done, so "died mid-write" is ruled out.)
      contract="negotiating"; resume="section-1-override"; round=3
      detail='"override recorded but proposal-r3 (final contract) missing — override step died mid-write; re-run it"'
```

with:

```bash
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
```

(The `else` branch containing `contract="finalized"; approved="$maxp"` two lines below is untouched — only the `elif [ "$maxp" -lt 3 ]` body changes.)

- [ ] **Step 5: Update the header comment's documented outcome values**

In `orca-workflows/scripts/contract_resume.sh`, line 22, change:

```bash
#     "outcome": <string|null>,    // section-4: PASS; section-5: CONTRACT_ESCALATE|FAIL|ESCALATE
```

to:

```bash
#     "outcome": <string|null>,    // section-4: PASS; section-5: CONTRACT_ESCALATE|CONTRACT_SCHEMA_STALE|FAIL|ESCALATE
```

And in the "Fail-closed rules" comment block (lines 27-37), add a fourth bullet after the existing three (before the blank line at 38):

```bash
# - CONTRACT_SCHEMA_STALE (issue #160): override.json without proposal-r3.json is not always a
#   violation — if override.json predates the proposal-r3 requirement itself (R3_REQUIRED_SINCE
#   above), the step legitimately had no r3 to write. That case escalates to section-5 with a
#   distinct outcome instead of being silently re-run or misreported as a recording-contract
#   violation.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_contract_resume.py -v`
Expected: all tests PASS, including the two new ones and every pre-existing test (no regressions).

- [ ] **Step 7: Commit**

```bash
git add orca-workflows/scripts/contract_resume.sh tests/test_contract_resume.py
git commit -m "$(cat <<'EOF'
contract_resume.sh: distinguish pre-gate override sessions from r3 violations

issue #160 -- override.json without proposal-r3.json was unconditionally
misread as either "died mid-write" or (via orca-workflow-task §1) a
recording-contract violation. Neither fits a session that completed override
before the r3 requirement (commit 79b7c3b/#130) existed. Compare
override.json's mtime against the requirement's introduction timestamp and
report CONTRACT_SCHEMA_STALE for the pre-gate case.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Register `CONTRACT_SCHEMA_STALE` as a legal outcome value

**Files:**
- Modify: `orca-workflows/scripts/log_dispatch.sh:68-79` (enum + membership notes)
- Modify: `tests/test_log_outcome.py:36-57` (`DOCUMENTED_OUTCOME_ENUM`)
- Modify: `orca-workflows/logging.md:81-141` (two-axis list + explanation paragraph)

**Interfaces:**
- Consumes: the string literal `"CONTRACT_SCHEMA_STALE"` (Task 1 already emits it from `contract_resume.sh`; Task 3 will emit it from `orca-workflow-task` SKILL.md §1).
- Produces: `log_outcome --outcome CONTRACT_SCHEMA_STALE ...` becomes a valid call (no longer forced to `UNMAPPED_BRANCH`) — every downstream consumer of outcome logs (retro, dashboards, humans grepping `assignments-*.jsonl`) can now rely on this exact string.

- [ ] **Step 1: Write the failing test (extend the existing cross-check list)**

In `tests/test_log_outcome.py`, in the `DOCUMENTED_OUTCOME_ENUM` list (currently lines 36-57), insert `"CONTRACT_SCHEMA_STALE",  # issue #160` in the progress-branch axis section, immediately after `"CONTRACT_APPROVED",` and before `"MANUAL_RECOVERY_COMPLETED",`:

```python
DOCUMENTED_OUTCOME_ENUM = [
    # verdict axis
    "PASS",
    "FAIL",
    "ESCALATE",
    "GATE_FAIL",
    "CONTRACT_ESCALATE",
    "CI_GATE_FAIL",
    # progress-branch axis
    "NO_DONE_TRANSITION",
    "CONTRACT_FINALIZED_BY_GENERATOR",
    "CONTRACT_APPROVED",
    "CONTRACT_SCHEMA_STALE",  # issue #160
    "MANUAL_RECOVERY_COMPLETED",
    "CI_GATE_TIMEOUT",
    "MERGE_CONFLICT",
    "RETRO_DONE",
    "RETRO_FAIL",
    "escalation_parked",
    "skipped",  # issue #138
    "NO_ACCEPTANCE_CRITERIA",  # issue #105
    "UNMAPPED_BRANCH",
]
```

- [ ] **Step 2: Run the cross-check test to verify it fails**

Run: `python3 -m pytest tests/test_log_outcome.py -k "enum" -v`
Expected: FAIL — `_extract_enum("LOG_OUTCOME_ENUM") == set(DOCUMENTED_OUTCOME_ENUM)` (line 522) no longer holds, since the script's enum doesn't have `CONTRACT_SCHEMA_STALE` yet.

- [ ] **Step 3: Add the value to `log_dispatch.sh`'s canonical enum**

In `orca-workflows/scripts/log_dispatch.sh`, in the "Membership notes beyond logging.md's original list" comment block (currently lines 68-78), add a new bullet after the `NO_ACCEPTANCE_CRITERIA` one and before the `EPIC_DONE / PR_OPEN_PREMERGE_PASS` one:

```bash
# - CONTRACT_SCHEMA_STALE: added per issue #160 — override.json completed before the proposal-r3
#   requirement itself existed (commit 79b7c3b/#130) is not a recording-contract violation, so it
#   gets its own progress-branch value instead of overloading CONTRACT_ESCALATE's "AC disagreement"
#   meaning. Emitted by orca-workflow-task §1's inline gate and contract_resume.sh's crash-resume
#   mirror (tests/test_contract_resume.py).
```

Then change line 79 from:

```bash
LOG_OUTCOME_ENUM="PASS FAIL ESCALATE GATE_FAIL CONTRACT_ESCALATE CI_GATE_FAIL NO_DONE_TRANSITION CONTRACT_FINALIZED_BY_GENERATOR CONTRACT_APPROVED MANUAL_RECOVERY_COMPLETED CI_GATE_TIMEOUT MERGE_CONFLICT RETRO_DONE RETRO_FAIL escalation_parked skipped NO_ACCEPTANCE_CRITERIA UNMAPPED_BRANCH"
```

to:

```bash
LOG_OUTCOME_ENUM="PASS FAIL ESCALATE GATE_FAIL CONTRACT_ESCALATE CI_GATE_FAIL NO_DONE_TRANSITION CONTRACT_FINALIZED_BY_GENERATOR CONTRACT_APPROVED CONTRACT_SCHEMA_STALE MANUAL_RECOVERY_COMPLETED CI_GATE_TIMEOUT MERGE_CONFLICT RETRO_DONE RETRO_FAIL escalation_parked skipped NO_ACCEPTANCE_CRITERIA UNMAPPED_BRANCH"
```

- [ ] **Step 4: Run the cross-check test to verify it passes**

Run: `python3 -m pytest tests/test_log_outcome.py -v`
Expected: all tests PASS (the full file, not just the enum test — confirms no other test hardcodes the old enum string).

- [ ] **Step 5: Update `logging.md`'s human-readable docs**

In `orca-workflows/logging.md`, change the 진행-분기 축 list (currently lines 83-85) from:

```markdown
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED`|
  `MANUAL_RECOVERY_COMPLETED`|`CI_GATE_TIMEOUT`|`MERGE_CONFLICT`|`RETRO_DONE`|`RETRO_FAIL`|
  `escalation_parked`|`skipped`|`NO_ACCEPTANCE_CRITERIA`|`UNMAPPED_BRANCH`
```

to:

```markdown
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED`|`CONTRACT_SCHEMA_STALE`|
  `MANUAL_RECOVERY_COMPLETED`|`CI_GATE_TIMEOUT`|`MERGE_CONFLICT`|`RETRO_DONE`|`RETRO_FAIL`|
  `escalation_parked`|`skipped`|`NO_ACCEPTANCE_CRITERIA`|`UNMAPPED_BRANCH`
```

Then, immediately after the `CONTRACT_APPROVED` explanation paragraph (currently lines 134-141, ending "...값 이름(`CONTRACT_APPROVED`) 자체로 구분된다."), insert a new paragraph:

```markdown
`CONTRACT_SCHEMA_STALE`는 `override.json`은 있는데 `proposal-r3.json`이 없고, `override.json`의
mtime이 그 요구사항 도입 시점(commit 79b7c3b, 2026-08-12T09:44:57+09:00)보다 이전인 경우다(issue
#160) — `orca-workflow-task` §1의 기계적 분기든 `contract_resume.sh`의 크래시-재개 미러든 같은
값이다. `CONTRACT_ESCALATE`(기록 계약 위반)와 상호 배타다: 위반이 아니라 그 요구사항 자체가 그
세션이 끝난 뒤에 생겼다는 뜻이므로, 사람에게 "generator가 규칙을 어겼다"고 잘못 전달하지 않기 위해
별도 값으로 분리한다. 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(도달한 라운드 수, 이
게이트 한정 항상 2)와 `detail`(override.json mtime과 게이트 도입 시각을 사람이 읽을 수 있는
형태로)을 더해 남긴다.
```

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/scripts/log_dispatch.sh tests/test_log_outcome.py orca-workflows/logging.md
git commit -m "$(cat <<'EOF'
logging: register CONTRACT_SCHEMA_STALE outcome value

issue #160 -- makes the new outcome (Task 1) a legal --outcome value instead
of being silently forced to UNMAPPED_BRANCH by log_outcome()'s enum guard.
Placed on the progress-branch axis (not verdict) -- it's an exceptional but
handled workflow state, not a judgment about the work's quality.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `orca-workflow-task` SKILL.md — live gate + human report text

**Files:**
- Modify: `skills/orca-workflow-task/SKILL.md:101-106` (§1 fail-closed branch)
- Modify: `skills/orca-workflow-task/SKILL.md:429,432` (§5 outcome list + explanation)

**Interfaces:**
- Consumes: `CONTRACT_SCHEMA_STALE` as a registered outcome (Task 2).
- Produces: none consumed by other tasks — this is the terminal, human-facing documentation change.

No automated test exists for this file's prose content (AGENTS.md: the prose-pinning tests that asserted specific SKILL.md wording were deleted — they froze wording as spec and produced false failures on every intentional edit). Verification for this task is manual re-reading, not `pytest`.

- [ ] **Step 1: Replace the §1 fail-closed branch**

In `skills/orca-workflow-task/SKILL.md`, replace (currently lines 101-106):

```markdown
elif [ ! -f "<CONTRACT_DIR>/proposal-r3.json" ]; then
  # override 기록은 있는데 확정 계약(proposal-r3 — override 스텝이 override.json 직후에 쓴다,
  # contract-schema.md "override 후속 라운드" 절, issue #130)이 없다 — worker_done까지 왔으므로
  # 쓰다 죽은 게 아니라 기록 계약 위반이다. fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
  # (§0 재개 분기는 같은 상태를 "쓰다 죽음"으로 보고 override 스텝을 재-태운다 — worker_done 수신
  # 여부가 두 해석을 가른다.)
```

with:

```markdown
elif [ ! -f "<CONTRACT_DIR>/proposal-r3.json" ]; then
  # override 기록은 있는데 확정 계약(proposal-r3 — override 스텝이 override.json 직후에 쓴다,
  # contract-schema.md "override 후속 라운드" 절, issue #130)이 없다 — worker_done까지 왔으므로
  # 쓰다 죽은 게 아니다. 그렇다고 곧장 "기록 계약 위반"도 아니다 — override.json이 이 r3 요구사항
  # 자체의 도입(commit 79b7c3b, 2026-08-12T09:44:57+09:00) 이전에 완료됐을 수 있다(issue #160).
  # R3_REQUIRED_SINCE 상수(contract_resume.sh와 동일 — 바꾸면 함께 바꾼다)로 override.json의 mtime을
  # 그 시각과 비교한다(recent_write 가드와 같은 touch -t + find -newer 패턴 — stat -f/-c epoch
  # 파싱은 GNU stat -f의 의미 충돌 위험이 있어 쓰지 않는다):
  R3_REQUIRED_SINCE='202608120944.57'
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-r3gate.XXXXXX")"
  touch -t "$R3_REQUIRED_SINCE" "$ref" 2>/dev/null
  if [ -n "$(find "<CONTRACT_DIR>" -maxdepth 1 -name override.json -newer "$ref" 2>/dev/null)" ]; then
    rm -f "$ref"
    # override.json이 게이트 도입 이후 — 기존 판단 그대로: 기록 계약 위반.
    # fail-closed: outcome=CONTRACT_ESCALATE, round=2로 남기고 §5로.
  else
    rm -f "$ref"
    # override.json이 게이트 도입 이전(또는 정확히 동시) — 위반이 아니라 구버전 세션.
    # outcome=CONTRACT_SCHEMA_STALE, round=2, detail에 override.json mtime과
    # $R3_REQUIRED_SINCE를 사람이 읽을 수 있는 형태로 남기고 §5로(§5 문구 참고 — "자동 재개"를
    # 암시하지 않는다).
  fi
  # (§0 재개 분기는 override.json mtime이 게이트 도입 이후인 상태만 "쓰다 죽음"으로 보고 override
  # 스텝을 재-태운다 — worker_done 수신 여부가 그 두 해석을 가른다. 게이트 도입 이전인 상태는 §0도
  # 동일하게 CONTRACT_SCHEMA_STALE로 escalate한다 — contract_resume.sh 미러.)
```

The following line (`elif jq -e '[.reasons[].target] | index("ac_fidelity")' ...`) is unchanged and continues to work as the next `elif` of the *outer* if-chain — the new content above is fully self-contained (its own `if`/`else`/`fi`).

- [ ] **Step 2: Update the §5 outcome list**

In `skills/orca-workflow-task/SKILL.md`, line 429-430, change:

```markdown
그 외 outcome(FAIL 한도 도달·ESCALATE·GATE_FAIL·CONTRACT_ESCALATE·CI_GATE_FAIL·CI_GATE_TIMEOUT·
MERGE_CONFLICT·NO_DONE_TRANSITION)이면 아래 보고 내용을 조립한 뒤 mode로 분기한다:
```

to:

```markdown
그 외 outcome(FAIL 한도 도달·ESCALATE·GATE_FAIL·CONTRACT_ESCALATE·CONTRACT_SCHEMA_STALE·CI_GATE_FAIL·
CI_GATE_TIMEOUT·MERGE_CONFLICT·NO_DONE_TRANSITION)이면 아래 보고 내용을 조립한 뒤 mode로 분기한다:
```

- [ ] **Step 3: Add the CONTRACT_SCHEMA_STALE explanation to the §5 report-content paragraph**

In `skills/orca-workflow-task/SKILL.md`, line 432 (the single long paragraph starting "보고 내용: issue 번호, ..."), two edits:

1. In the enum list at the start of the sentence, change `PASS/FAIL/ESCALATE/GATE_FAIL/CONTRACT_ESCALATE/CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT/NO_DONE_TRANSITION` to `PASS/FAIL/ESCALATE/GATE_FAIL/CONTRACT_ESCALATE/CONTRACT_SCHEMA_STALE/CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT/NO_DONE_TRANSITION`.

2. Immediately after the existing `**CONTRACT_ESCALATE**는 ...generator가 기록 없이 라운드 한도에 도달함 — 을 표시한다.` sentence and before `**CI_GATE_FAIL**은 ...`, insert:

```markdown
**CONTRACT_SCHEMA_STALE**는 override 완료(override.json mtime)가 proposal-r3 요구사항 도입 시각
(commit 79b7c3b, 2026-08-12T09:44:57+09:00)보다 이전이라는 뜻이다 — 위반이 아니라 구버전 세션이므로
이 두 시각을 그대로 표시한다. 사람의 선택지: (a) `verdict-r2.json`의 미해소 `reasons`를 반영해
`proposal-r3.json`을 수동으로 작성한 뒤, worktree에 구현이 이미 있다면 **§2를 재실행하지 말고 §1의
evaluate-dispatch 블록만 그 diff를 가리켜 수동으로 재사용**한다(§2 재실행은 이미 완료된 구현을 다시
만들 위험이 있다 — 별도 공백, issue #161). 구현이 없으면 정상적으로 §2부터 재개한다. (b) 완료된
작업을 폐기하고 재협상을 지시한다.
```

- [ ] **Step 4: Manually re-read the edited sections for consistency**

Re-read §1's full block (now spanning roughly lines 94-138 after the insertion) and §5's outcome list + paragraph. Confirm: the nested `if`/`else`/`fi` is well-formed and indented consistently with the surrounding code fence; every mention of `CONTRACT_SCHEMA_STALE` uses the same casing; the commit hash `79b7c3b` and timestamp `2026-08-12T09:44:57+09:00` are identical everywhere they appear in this file (and match Task 1's copies in `contract_resume.sh`).

- [ ] **Step 5: Commit**

```bash
git add skills/orca-workflow-task/SKILL.md
git commit -m "$(cat <<'EOF'
orca-workflow-task: distinguish CONTRACT_SCHEMA_STALE from CONTRACT_ESCALATE in §1/§5

issue #160 -- mirrors contract_resume.sh's Task 1 change in the live §1 gate,
and tells humans in §5 exactly how to unstick a stale-gate escalation without
implying automatic resume (re-running §2 on an already-implemented diff would
risk redoing finished work -- issue #161 tracks that separate gap).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Supporting docs — `contract-schema.md` cross-reference + `orca-retro` lens 3 carve-out

**Files:**
- Modify: `orca-workflows/contract-schema.md:135` (end of "override 후속 라운드" section)
- Modify: `skills/orca-retro/SKILL.md:101-102` (lens 3)

**Interfaces:**
- Consumes: `CONTRACT_SCHEMA_STALE` as a registered outcome (Task 2).
- Produces: none — both are leaf documentation changes.

- [ ] **Step 1: Add the cross-reference to `contract-schema.md`**

In `orca-workflows/contract-schema.md`, immediately after the existing bullet ending "...`round` 필드만 올린다." (currently line 135) and before the blank line / `## gate-flake-a<k>.json` heading (lines 136-137), insert a new bullet:

```markdown
- **`proposal-r3.json`이 없다고 항상 위반은 아니다** — override.json이 이 절 자체의 도입(commit
  79b7c3b, 2026-08-12T09:44:57+09:00) 이전에 완료된 세션은 규칙이 생기기 전에 끝난 것이므로
  `CONTRACT_SCHEMA_STALE`로 별도 처리한다(issue #160). 도입 시각 상수(`R3_REQUIRED_SINCE`)와 비교
  로직은 `orca-workflows/scripts/contract_resume.sh`와 `orca-workflow-task` SKILL.md §1 양쪽에
  정의돼 있다 — 이 문서는 그 존재만 가리키고 상수 자체를 복제하지 않는다.
```

- [ ] **Step 2: Add the lens 3 carve-out to `orca-retro`**

In `skills/orca-retro/SKILL.md`, change (currently lines 101-102):

```markdown
3. **예방 가능했던 ESCALATE·인간 개입** — `ESCALATE`·`*_HUMAN_DECISION` 계열 outcome 중, 전사를 보면
   스킬 문구 보강으로 막을 수 있었던 것.
```

to:

```markdown
3. **예방 가능했던 ESCALATE·인간 개입** — `ESCALATE`·`*_HUMAN_DECISION` 계열 outcome 중, 전사를 보면
   스킬 문구 보강으로 막을 수 있었던 것. 예외: `outcome`이 `CONTRACT_SCHEMA_STALE`인 레코드는 후보에서
   제외한다 — 이미 스킬 문구가 보강돼 처리되는 마이그레이션 범주다(issue #160, ADR 0001의
   `UNMAPPED_BRANCH` carve-out과 같은 근거).
```

- [ ] **Step 3: Commit**

```bash
git add orca-workflows/contract-schema.md skills/orca-retro/SKILL.md
git commit -m "$(cat <<'EOF'
docs: cross-reference CONTRACT_SCHEMA_STALE from contract-schema.md and orca-retro

issue #160 -- contract-schema.md points at the new escape hatch without
duplicating its constant; orca-retro's lens 3 stops treating expected
migration-category escalations as fresh preventable-defect candidates
(same carve-out shape as ADR 0001's UNMAPPED_BRANCH exception).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Version bump and deploy

**Files:**
- Modify: `skills/orca-set.version`

**Interfaces:**
- Consumes: all prior tasks' committed changes to `skills/orca-workflow-task/SKILL.md` and `skills/orca-retro/SKILL.md` (both `orca-set` members).
- Produces: a deployed, live update at `~/.agents/skills/` for every `orca-set` member (per AGENTS.md: "After committing a skill change, run `scripts/deploy-skills.sh` [skill-name ...]").

- [ ] **Step 1: Confirm the working tree is clean**

Run: `git status --short`
Expected: no output (Tasks 1-4 already committed). `deploy-skills.sh` refuses dirty skills, so this must be clean before proceeding.

- [ ] **Step 2: Bump the version**

In `skills/orca-set.version`, change the first line from `v1.1.17` to `v1.1.18` (the member list below it — `orca-evaluate`, `orca-retro`, `orca-task-runner`, `orca-workflow`, `orca-workflow-epic`, `orca-workflow-task`, `project-setup` — is unchanged; this plan does not add or remove set members).

- [ ] **Step 3: Commit the version bump**

```bash
git add skills/orca-set.version
git commit -m "$(cat <<'EOF'
orca-set v1.1.18 — CONTRACT_SCHEMA_STALE (#160)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Deploy**

Run: `scripts/deploy-skills.sh` (no args — deploys the whole `orca-set`, since `orca-workflow-task` and `orca-retro` are both members and must ship at the same version label).

Expected: the script reports the new commit-pinned copies installed under `~/.agents/skills/` at `v1.1.18`, and confirms `orca-workflows/` needs no separate deploy step (it's a symlink to this repo's main-branch checkout — see AGENTS.md's "`orca-workflows/` deploy path" note — so `contract_resume.sh`, `contract-schema.md`, and `logging.md` go live the moment this branch merges to `main`, independently of this `deploy-skills.sh` run).

This step has a global effect (installs into the user's live `~/.agents/skills/`, consumed by every repo this pipeline runs against) — confirm with the user before running it if executing this plan non-interactively.

---

## Self-Review Notes

**Spec coverage:** every numbered section of the design doc (`docs/superpowers/specs/2026-08-12-contract-schema-gate-versioning-design.md`) maps to a task — §② detection mechanism → Task 1; §③ branch-level changes → Tasks 1 and 3; §④ outcome schema placement → Task 2; §⑤ §5 report text → Task 3; §⑥ orca-retro → Task 4; §⑦ tests → Task 1 (contract_resume) and Task 2 (log_outcome cross-check); §⑧ deploy → Task 5. The design's explicit "범위 밖" items (auto-jump-to-evaluate, auto-migration, general registry, retroactive cleanup of the 20 known directories) have no corresponding task, matching the design.

**Placeholder scan:** no TBD/TODO; every step shows the literal text to write, not a description of it.

**Type/name consistency:** `R3_REQUIRED_SINCE` (constant name) and `_cr_predates_r3_gate` (function name, Task 1 only — Task 3's SKILL.md copy is inline, unnamed prose, per the mirroring decision) are spelled identically everywhere they appear across Tasks 1, 3, and 4. `CONTRACT_SCHEMA_STALE` (outcome string) is spelled identically across Tasks 1-4. The cutoff commit/timestamp (`79b7c3b`, `2026-08-12T09:44:57+09:00`) and its `touch -t` encoding (`202608120944.57`) are identical in both copies (Task 1's `contract_resume.sh`, Task 3's SKILL.md).
