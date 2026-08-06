# Contract Round-2+ Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the actual `orca` CLI mechanism for relaying contract-negotiation round 2+ between `orca-workflow`'s task-runner and evaluator terminals (issue #64), replacing the ad hoc `terminal-send-fallback` placeholder observed in production with a verified procedure.

**Architecture:** `orca-workflow` §2a gets a new subsection: after round 1, a new `task-create` per round (never reusing the round-1 `task_id` — verified impossible) is dispatched to the *same* terminal handle, gated on a `task-list` poll confirming the prior round's task reached `completed`. No worker-side code changes are needed — `dispatch --inject` already auto-injects the full `worker_done` protocol on every call (verified via live `--dry-run --return-preamble` and a real session), so `orca-task-runner`/`orca-evaluate` only need a one-sentence prose clarification that the negotiation spans separate dispatches, not a single turn. `logging.md`'s now-resolved "unresolved design question" note is removed, and `spawn-failures.md` gains two new rows for the two `runtime_error` JSON responses this investigation produced.

**Tech Stack:** Markdown (`SKILL.md`, `orca-workflows/*.md`), the `orca` CLI, Python/pytest structural regression suite (`tests/test_orca_skills.py`, run via `uvx pytest`).

## Global Constraints

- Baseline before starting: `uvx pytest tests/test_orca_skills.py -q` reports `2 failed, 111 passed` on an
  unmodified tree — `test_no_bare_undated_assignments_or_waves_path[orca-retro]` and
  `test_no_bare_undated_assignments_or_waves_path[logging.md]`. Both are pre-existing and unrelated to issue
  #64 — do not attempt to fix them as part of this plan. Every verification step below expects exactly these
  same 2 failures to persist, plus all-passing for everything this plan touches.
- Never re-dispatch a round-1 `task_id` for round 2 — verified impossible
  (`"Task <id> is dispatched; only ready tasks can be dispatched"`) and `dispatch` carries no
  content-override argument regardless.
- Never add `--deps` between a round-N task and round-N+1's task — verified to just add a redundant
  `pending`-stall path; `dispatch`'s own one-active-dispatch-per-terminal rule already enforces the same
  ordering.
- Do not add any literal `orchestration send`/`worker_done` bash to `orca-task-runner` or `orca-evaluate`
  — `dispatch --inject` already auto-injects that protocol in its preamble on every call (verified twice:
  `--dry-run --return-preamble` output and a real live-session terminal read). Adding it explicitly would be
  the first literal `orchestration send` line in this file family and would duplicate text Orca already
  injects.
- Do not use `orca terminal read` or `orchestration check --wait` as the primary wait mechanism for the new
  round-2+ relay — `orca-task-runner` §5 already documents that a coordinator running inside an Orca
  terminal session can miss `worker_done` on the `check` queue even though task status updates correctly.
  Poll `task-list` instead, matching that same documented convention.
- `orca-workflows/` edits go live on merge to `main` (symlink-tracks-main convention, no separate deploy
  step). `skills/orca-workflow`, `skills/orca-task-runner`, `skills/orca-evaluate` are commit-pinned copies —
  editing them here does nothing live until `scripts/deploy-skills.sh orca-workflow orca-task-runner
  orca-evaluate` runs. Per this repo's own prior plan's sequencing note (`2026-07-30-dispatch-inject-verify.md`),
  run that deploy **after** merging to `main`, not from this branch — deploying early would be harmless here
  (nothing in this change references a not-yet-merged path), but stay consistent with the established
  sequencing rule anyway.

---

## File Structure

- Modify: `skills/orca-workflow/SKILL.md` — new round-2+ relay subsection appended to §2a (between the
  existing round-1 bash block and `**2b. Generate**`)
- Modify: `skills/orca-task-runner/SKILL.md` — one clarifying sentence in §1
- Modify: `skills/orca-evaluate/SKILL.md` — one clarifying sentence in §1
- Modify: `orca-workflows/logging.md` — remove the now-resolved `relay:true`/task_id-omission paragraph
  (lines 45-51), which no longer describes any real call site once this plan lands
- Modify: `orca-workflows/spawn-failures.md` — two new Known-signatures rows + one scoping note explaining
  their signature is found in the calling command's own `--json` response, not a spawned terminal's
  `terminal read` output (every existing row is the latter; these two are not, and the doc should say so
  explicitly rather than let a future reader grep the wrong place)
- Modify: `tests/test_orca_skills.py` — update the two count assertions this plan's new content shifts, and
  add four new structural tests pinning the new content

---

## Task 1: `orca-workflow` §2a round-2+ relay protocol

**Files:**
- Modify: `skills/orca-workflow/SKILL.md:160-162` (insert between the closing ` ``` ` of the existing round-1
  bash block and `**2b. Generate**`)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing from other tasks in this plan (self-contained; the shared `orca_call_with_retry.sh`,
  `dispatch-verify.md`, `logging.md` pointers it references already exist).
- Produces: nothing other tasks in this plan consume — `logging.md`'s Task 4 edit references this task's
  outcome ("round 2+ now always carries a real `task_id`") but does not read anything from the new SKILL.md
  text programmatically.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_orca_skills.py`, after `test_orca_call_with_retry_count_per_skill` (currently ending
around line 687):

```python
def test_orca_workflow_documents_round2_relay_protocol():
    """Issue #64: §2a must name the actual mechanism (new task-create per round, gated on a task-list
    poll for the prior round's completion, dispatched to the same terminal handle) rather than leaving
    round 2+ undocumented. Pins the load-bearing phrases so a future rewrite can't silently drop the
    poll-before-dispatch gate or reintroduce task_id reuse."""
    text = _read_skill("orca-workflow")
    assert "already has an active dispatch" in text, (
        "must document the verified error a premature round-2 dispatch produces"
    )
    assert "is dispatched; only ready tasks can be dispatched" in text, (
        "must document why reusing the round-1 task_id is impossible"
    )
    assert "task-list" in text, "round-2+ completion check must poll task-list, not terminal read"
    assert "reportPath" in text, "must name the path-only relay channel (task-list result.reportPath)"
    no_deps_idx = text.find("--deps는 걸지")
    assert no_deps_idx != -1, "must explicitly instruct against --deps between round tasks"


def test_orca_workflow_round2_relay_has_no_deploy_placeholder():
    """The production incident this issue traces to used a `terminal-send-fallback` task_id placeholder
    — the fixed procedure must never reintroduce it."""
    text = _read_skill("orca-workflow")
    assert "terminal-send-fallback" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uvx pytest tests/test_orca_skills.py -k "documents_round2_relay_protocol or round2_relay_has_no_deploy_placeholder" -v`
Expected: both new tests FAIL (`AssertionError` — none of the asserted substrings exist yet in
`skills/orca-workflow/SKILL.md`).

- [ ] **Step 3: Insert the round-2+ relay subsection**

In `skills/orca-workflow/SKILL.md`, insert the following between the ` ``` ` that closes the existing round-1
bash block (currently line 160) and the blank line before `**2b. Generate**` (currently line 162):

```markdown

**Contract 협상 relay — 라운드 2+ (반려된 경우만; 승인이면 곧장 2b)**: 라운드 1과 같은 task_id를 재사용하지
않는다 — `dispatch`는 이미 `dispatched`/`completed` 상태인 task를 거부하고(`"Task ... is dispatched; only
ready tasks can be dispatched"`, 실측), 애초에 텍스트를 override하는 인자가 없어 재사용해도 라운드 1과 같은
spec만 재전송된다. 대신 매 라운드 새 task를 만들어 같은 터미널(재-engage 대상은 task-runner면
`<run-handle>`, evaluator면 `<evaluate-handle>`)에 재-dispatch한다 — 단 그 터미널의 직전 dispatch가
`completed` 상태여야 한다(그렇지 않으면 `"Terminal ... already has an active dispatch"`로 거부됨, 실측).
`--deps`는 걸지 않는다 — 걸어도 `dispatch` 자체가 이미 같은 선후관계를 강제하므로 stall 경로만 하나 늘어난다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-list --json
# 위 결과에서 직전 라운드 task_id의 .status가 "completed"인지 확인하고, .result(JSON 문자열)를 파싱해
# .reportPath를 읽는다 — 본문은 읽지 않고 경로만 중계한다는 원칙은 여기서도 유지된다.
spec_text="<round 번호 + 위에서 읽은 reportPath + (evaluator→task-runner 방향이면) 반려 사유 요약>"
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration dispatch --task <round N task_id> --to <재-engage 대상 handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. task_id가 실제 존재하므로 §1의 relay:true/omit
# 규칙은 이 사이트엔 적용되지 않는다(issue #64로 해소).
```

- `task-list --json` 폴링(20-30s 간격)으로 직전 라운드가 `completed`인지 확인한다 — `check --wait`을 1차
  수단으로 쓰지 않는다(coordinator가 Orca 터미널 세션이면 `worker_done`이 check 큐에서 누락될 수 있다, task
  상태는 정상 갱신됨 — `orca-task-runner` §5와 같은 이유).
- 오래(예: 30분) `completed`가 안 되면 체크포인트 — 재진단하지 않고
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차로.
```

- [ ] **Step 4: Update the two pinned count assertions this insertion shifts**

In `tests/test_orca_skills.py`:

Replace (around line 571-574):
```python
    assert total == 7, (
        f"expected 7 `dispatch --task ... --inject` sites across the NEW_SKILLS family's "
        f"SKILL.md files combined, found {total}"
    )
```
with:
```python
    assert total == 8, (
        f"expected 8 `dispatch --task ... --inject` sites across the NEW_SKILLS family's "
        f"SKILL.md files combined (7 pre-#64 + 1 new round-2+ relay site in orca-workflow §2a), "
        f"found {total}"
    )
```

Replace (around line 674-678):
```python
EXPECTED_RETRY_WRAP_COUNTS = {
    "orca-workflow": 9,
    "orca-task-runner": 6,
    "orca-evaluate": 10,
}
```
with:
```python
EXPECTED_RETRY_WRAP_COUNTS = {
    "orca-workflow": 12,  # +3 for issue #64's round-2+ relay: task-list poll, task-create, dispatch
    "orca-task-runner": 6,
    "orca-evaluate": 10,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uvx pytest tests/test_orca_skills.py -k "documents_round2_relay_protocol or round2_relay_has_no_deploy_placeholder or dispatch_site_count or orca_call_with_retry_count" -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite to confirm no other regression**

Run: `uvx pytest tests/test_orca_skills.py -q`
Expected: `2 failed, 113 passed` (the same 2 pre-existing failures from Global Constraints, plus the 2 new
tests from Step 1 now passing on top of the 111 baseline).

- [ ] **Step 7: Commit**

```bash
git add skills/orca-workflow/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-workflow): document contract round-2+ relay protocol (#64)

New task-create per round, gated on a task-list poll for the prior
round's completion, dispatched to the same terminal handle. Reusing
the round-1 task_id is impossible (dispatch rejects non-ready
tasks); --deps between round tasks is redundant with dispatch's own
one-active-dispatch-per-terminal rule. Both verified live."
```

## Task 2: `orca-task-runner` §1 turn-boundary clarification

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md` (§1, the sentence "반려되면 수정해서 다시 제안한다.")
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, after Task 1's new tests:

```python
def test_orca_task_runner_states_contract_round_is_a_new_dispatch_not_a_wait():
    """Issue #64: §1's "반려되면 수정해서 다시 제안한다" narrates the whole multi-dispatch protocol in one
    sentence — a fresh dispatched worker could misread it as "wait/poll in this same turn" instead of "end
    the turn; the next round arrives as a new dispatch." No new orca command is needed here (dispatch
    --inject already auto-injects the full worker_done protocol on every call) — only this one sentence
    of turn-boundary prose."""
    text = _read_skill("orca-task-runner")
    assert "이번 턴을 끝낸다" in text, (
        "orca-task-runner §1 must clarify that each contract round ends the current turn "
        "(worker_done, per the injected preamble) rather than waiting/polling in-turn for the next round"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uvx pytest tests/test_orca_skills.py -k orca_task_runner_states_contract_round -v`
Expected: FAIL (`AssertionError` — phrase not present yet).

- [ ] **Step 3: Insert the clarifying sentence**

In `skills/orca-task-runner/SKILL.md` §1, replace:
```
`orca-evaluate`가 이 제안을 issue의 원본 acceptance criteria에 대조해 검토한다. 반려되면 수정해서 다시 제안한다. **최대 2 라운드.** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 그 제안대로 진행한다 — evaluator의 이견은 기록에 남기되 진행을 막지 않는다.
```
with:
```
`orca-evaluate`가 이 제안을 issue의 원본 acceptance criteria에 대조해 검토한다. 반려되면 수정해서 다시 제안한다 — 각 라운드는 별도 dispatch로 도착한다: 제안서를 쓰고 나면 이번 턴을 끝낸다(주입된 preamble의 worker_done 지시대로), 같은 턴 안에서 반려 여부를 기다리거나 폴링하지 않는다. **최대 2 라운드.** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 그 제안대로 진행한다 — evaluator의 이견은 기록에 남기되 진행을 막지 않는다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uvx pytest tests/test_orca_skills.py -k orca_task_runner_states_contract_round -v`
Expected: PASS.

- [ ] **Step 5: Confirm no bash/count regression**

Run: `uvx pytest tests/test_orca_skills.py -k "orca_call_with_retry_count or orca_terminal_read_counts or no_bare_wrapped" -v`
Expected: all PASS unchanged — this task is pure prose, no new orca calls.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-task-runner/SKILL.md tests/test_orca_skills.py
git commit -m "docs(orca-task-runner): clarify contract round is a new dispatch, not an in-turn wait (#64)"
```

## Task 3: `orca-evaluate` §1 turn-boundary clarification

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md` (§1, the sentence describing relaying the verdict back)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, after Task 2's new test:

```python
def test_orca_evaluate_states_contract_round_is_a_new_dispatch_not_a_wait():
    """Mirrors test_orca_task_runner_states_contract_round_is_a_new_dispatch_not_a_wait for the
    evaluator side of the same round."""
    text = _read_skill("orca-evaluate")
    assert "이번 턴을 끝낸다" in text, (
        "orca-evaluate §1 must clarify that relaying the verdict ends the current turn "
        "(worker_done, per the injected preamble) rather than waiting/polling in-turn for the next round"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uvx pytest tests/test_orca_skills.py -k orca_evaluate_states_contract_round -v`
Expected: FAIL.

- [ ] **Step 3: Insert the clarifying sentence**

In `skills/orca-evaluate/SKILL.md` §1, replace:
```
이 evaluator 세션은 그 판정 결과(승인/반려+사유)를 받아 `orca-task-runner`로 relay한다(파일 내용을 새로 읽거나 재해석하지 않고 판정 결과만 전달). 최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.
```
with:
```
이 evaluator 세션은 그 판정 결과(승인/반려+사유)를 받아 `orca-task-runner`로 relay한다(파일 내용을 새로 읽거나 재해석하지 않고 판정 결과만 전달) — 각 라운드는 별도 dispatch로 도착한다: 판정 결과를 relay하고 나면 이번 턴을 끝낸다(주입된 preamble의 worker_done 지시대로), 같은 턴 안에서 다음 제안을 기다리거나 폴링하지 않는다. 최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uvx pytest tests/test_orca_skills.py -k orca_evaluate_states_contract_round -v`
Expected: PASS.

- [ ] **Step 5: Confirm no bash/count regression**

Run: `uvx pytest tests/test_orca_skills.py -k "orca_call_with_retry_count or orca_terminal_read_counts or no_bare_wrapped" -v`
Expected: all PASS unchanged.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-evaluate/SKILL.md tests/test_orca_skills.py
git commit -m "docs(orca-evaluate): clarify contract round is a new dispatch, not an in-turn wait (#64)"
```

## Task 4: Remove the now-resolved `relay:true` paragraph from `logging.md`

**Files:**
- Modify: `orca-workflows/logging.md:45-51`
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: the fact established by Task 1 — round 2+ now always dispatches a brand-new task, so it always
  carries a real `task_id`. No programmatic dependency; this is a documentation consequence.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, after Task 3's new test:

```python
def test_logging_no_longer_flags_round2_relay_as_unresolved():
    """Issue #64 is resolved as of this plan — logging.md must not keep pointing a future reader at it
    as an open design question, nor keep the disproven "task 재사용" prediction, nor the ad hoc
    'terminal-send-fallback' placeholder the unresolved state produced in production."""
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    assert "아직 미해결 설계 질문" not in text
    assert "terminal-send-fallback" not in text
    assert "기존 task 재사용 방식으로 확정하면" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uvx pytest tests/test_orca_skills.py -k no_longer_flags_round2_relay -v`
Expected: FAIL (all three phrases are currently present in `logging.md`).

- [ ] **Step 3: Remove the paragraph**

In `orca-workflows/logging.md`, delete the following block entirely (currently lines 45-52, between the
`assign` recipe's closing code fence and the `**outcome**` heading) — remove the paragraph text and the
blank line immediately after it, leaving the file reading directly from the `assign` section's closing
"Extra fields..." sentence to the `**outcome**` heading:

```
**`task-create`가 새 task를 만들지 않은 relay dispatch** (예: `orca-workflow` §2a 계약 협상의 2라운드
이후 — 어떤 orca 명령으로 라운드 2+를 relay할지는 아직 미해결 설계 질문이다, issue #64): 이런 dispatch에는
진짜 `task_id`가 없는 경우가 있다. `task_id` 필드는 기존 `<task_id-or-omit>` 규칙대로 그대로 생략한다 — 빈
문자열(`""`)이나 `"terminal-send-fallback"` 같은 즉석 placeholder를 넣지 않는다. 대신 extra field로
`"relay":true`를 추가해 "몰라서 생략"과 "relay라서 없음"을 로그에서 구분한다(observed in practice: issue
#62). issue #64가 라운드 2+ 전송을 기존 task 재사용 방식으로 확정하면 그 경로엔 진짜 `task_id`가 생겨 이
규칙 자체가 적용되지 않게 될 수 있다 — 이 규칙은 task_id가 실제로 없는 dispatch에만 적용된다.

```

Removed entirely — no replacement text. After this plan, every dispatch site in this file family carries a
real `task_id` (round 1 via the pre-existing `task-create`, round 2+ via Task 1's new `task-create`), so
this rule no longer describes any call site to attach to.

- [ ] **Step 4: Run test to verify it passes**

Run: `uvx pytest tests/test_orca_skills.py -k no_longer_flags_round2_relay -v`
Expected: PASS.

- [ ] **Step 5: Confirm no other logging.md-scoped test regressed**

Run: `uvx pytest tests/test_orca_skills.py -k "logging or bare_undated" -v`
Expected: all PASS except the pre-existing, unrelated
`test_no_bare_undated_assignments_or_waves_path[logging.md]` failure from Global Constraints (confirm it
fails for the *same* reason as the baseline — an undated `logs/assignments.jsonl` mention elsewhere in the
file — not a new one introduced here).

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/logging.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): remove resolved relay-dispatch task_id note from logging.md (#64)

Every dispatch site in this file family now carries a real task_id
after issue #64's fix — the relay:true/omitted-task_id rule no
longer describes any call site."
```

## Task 5: Two new `spawn-failures.md` rows

**Files:**
- Modify: `orca-workflows/spawn-failures.md`
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orca_skills.py`, after Task 4's new test:

```python
def test_spawn_failures_has_round2_relay_rejection_rows():
    """Issue #64's live investigation produced two verified `runtime_error` JSON responses from
    `dispatch`/`task-create` themselves — not a spawned terminal's `terminal read` output, unlike every
    prior row in this table. Pins both signatures, the issue link, and the scoping note distinguishing
    their detection channel from the table's default convention."""
    text = _read_workflows_file("spawn-failures.md")
    assert "is dispatched; only ready tasks can be dispatched" in text
    assert "already has an active dispatch" in text
    assert text.count("#64") >= 2, "both new rows must link issue #64"
    assert "calling command's own" in text or "호출 자신의" in text, (
        "must scope-note that these two signatures appear in dispatch/task-create's own --json response, "
        "not a spawned terminal's `terminal read` output (every other row in this table is the latter)"
    )
    header_count = text.count("| `failure_signature` (grep substring) |")
    assert header_count == 1, (
        f"expected exactly one 'Known signatures' table (one header line), found {header_count}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uvx pytest tests/test_orca_skills.py -k round2_relay_rejection_rows -v`
Expected: FAIL.

- [ ] **Step 3: Add the scoping note and two rows**

In `orca-workflows/spawn-failures.md`, insert a new paragraph directly after the existing "Adding a new row"
section's closing paragraph (after the line ending "...default to the literal-substring form whenever one
exists.", currently line 88), before the two new table rows below:

```markdown

**Exception (caller-side signature, not terminal-read):** the two `#64` rows below are the one case in this
table where `failure_signature` does not appear in a spawned terminal's `terminal read` output — every other
row is from reading a target terminal that `orca-workflow`/`orca-task-runner`/`orca-evaluate` spawned.
These two are `runtime_error` JSON responses returned directly by `orca orchestration dispatch`/`task-create`
themselves, visible in the calling command's own `--json` stdout at the moment it is issued — grep that
output, not a later `terminal read`.
```

Then append these two rows to the end of the "Known signatures" table (currently after the `#60` row on
line 71):

```markdown
| `is dispatched; only ready tasks can be dispatched` (full message: `Task <id> is dispatched; only ready tasks can be dispatched`) | attempting to re-`dispatch --task` a task that is already in `dispatched`/`completed` status — `dispatch` requires `status: ready` and carries no content-override argument | do not reuse a task_id across rounds; `task-create` a new task per round instead (`orca-workflow` §2a round-2+ relay) | #64 |
| `already has an active dispatch` (full message: `Terminal <handle> already has an active dispatch (ctx_... for task <id>)`) | a terminal can hold at most one active (non-completed) dispatch at a time; dispatching a new task to it before the current one reaches `completed` is rejected outright | poll `task-list` for the prior round's task reaching `completed` (the worker's own injected-preamble `worker_done` call drives that transition automatically) before dispatching the next round — don't assume completion | #64 |
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uvx pytest tests/test_orca_skills.py -k round2_relay_rejection_rows -v`
Expected: PASS.

- [ ] **Step 5: Confirm no other spawn-failures.md-scoped test regressed**

Run: `uvx pytest tests/test_orca_skills.py -k spawn_failures -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/spawn-failures.md tests/test_orca_skills.py
git commit -m "docs(orca-workflows): add spawn-failures rows for the two round-2+ dispatch rejections (#64)

Both are runtime_error JSON responses from dispatch/task-create
themselves, not a spawned terminal's terminal-read output — first
exception of that kind in this table, called out explicitly."
```

## Task 6: Cross-file validation sweep

**Files:** none modified — verification only

**Interfaces:**
- Consumes: the combined result of Tasks 1-5.
- Produces: final sign-off for this plan.

- [ ] **Step 1: Full suite run**

Run: `uvx pytest tests/test_orca_skills.py -q`
Expected: `2 failed, 117 passed` — the same 2 pre-existing, unrelated failures from Global Constraints
(`test_no_bare_undated_assignments_or_waves_path[orca-retro]` and `[logging.md]`), plus all 111 previously
passing tests still passing, plus the 6 new tests added across Tasks 1-5 (2 in Task 1, 1 each in Tasks 2-5)
now passing (111 + 6 = 117).

- [ ] **Step 2: Confirm no stray issue-#64 "unresolved" language survives anywhere in the touched files**

Run: `grep -rn "아직 미해결 설계 질문\|기존 task 재사용 방식으로 확정하면" orca-workflows/ skills/`
Expected: no output.

- [ ] **Step 3: Confirm the round-2+ site's pointers are both present within its own block**

Run: `grep -A30 'Contract 협상 relay — 라운드 2+' skills/orca-workflow/SKILL.md | grep -c "logging.md\|dispatch-verify.md"`
Expected: `2` (one line matching each).

- [ ] **Step 4: Confirm `terminal-send-fallback` is gone from every file this plan touches**

Run: `grep -rn "terminal-send-fallback" orca-workflows/ skills/`
Expected: no output (this was the ad hoc placeholder issue #64 traces to; its disappearance from
`logging.md`'s prose, confirmed structurally in Task 4, is re-confirmed here across the whole touched set).

- [ ] **Step 5: Record the deploy-sequencing note for whoever merges this branch**

No command to run — this is a reminder for the merge step, not a task-level action (per Global Constraints
and the established sequencing precedent): after merging to `main`, run
`scripts/deploy-skills.sh orca-workflow orca-task-runner orca-evaluate` so the commit-pinned
`~/.agents/skills/` copies pick up these changes. `orca-workflows/logging.md` and
`orca-workflows/spawn-failures.md` need no separate deploy step — they go live immediately on merge via the
existing symlink-tracks-main convention.

- [ ] **Step 6: Close out**

No commit for this task (verification only). If any step above fails, return to the corresponding task above
rather than patching ad hoc here — every substantive change in this plan has its own task and its own test.

**Not covered by this plan, left for issue #64's actual closure:** the design doc's validation item 4 — run
one real `orca-workflow` task end-to-end through at least a round-2 negotiation (a task designed to trigger
one evaluator rejection) and confirm the round-2 dispatch succeeds without falling back to any
`terminal-send-fallback`-style placeholder in the assignment log. This plan only documents and structurally
pins the protocol; a live epic run costs real orchestration/agent time and belongs to whoever next runs
`orca-workflow` against a real issue, not to this documentation-only implementation pass.
