# Orca Retro (Epic-End Skill-Defect Feedback Loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `orca-retro` skill that, right after `orca-workflow` closes an epic, analyzes that epic's logs and files at most 3 evidence-backed skill-defect issues on sleeptimegrt-skills, closing the layer-3 (environment-improvement) loop.

**Architecture:** One new prose skill (`skills/orca-retro/SKILL.md`), one integration step appended to `orca-workflow` §1 (spawn a retro terminal after `close_issue(epic-num)` succeeds, best-effort), and a two-value extension of the documented `outcome` enum in `orca-workflows/logging.md`. All behavior checks are structural pytest tests (this repo's convention for prose skills) plus a report-only fixture pilot.

**Tech Stack:** Markdown skill prose (Korean body / English frontmatter), pytest structural tests (`tests/test_orca_skills.py`), bash/jq log recipes matching `orca-workflows/logging.md`.

**Spec:** `docs/superpowers/specs/2026-08-01-orca-retro-design.md` — read it before starting any task.

## Global Constraints

- Work on branch `feat/orca-retro` off `main` (create it in Task 1 Step 0 if absent).
- SKILL.md bodies are Korean prose; frontmatter `description` is English, starts with "Use", and `name` equals the directory name (structural tests enforce both).
- **No history in skill bodies**: no dates, no measured-drift statistics, no pilot citations — current execution instructions only. History lives in the spec and issues.
- Shared docs are referenced via `~/.agents/orca-workflows/...` runtime paths, never repo-relative paths, matching the existing orca-* skills.
- All `orca orchestration` / `orca terminal create` calls shown in skill prose are wrapped with `orca_call_with_retry` (issue #42 convention) and followed by the `dispatch-verify.md` unsent-check comment (issue #43 convention).
- Never execute external-write commands while testing: the fixture pilot must not run any real `gh` command (report-only override is part of the pilot prompt).
- Test command: `python3 -m pytest tests/test_orca_skills.py -q` (full file — new tests plus regressions).
- Every commit message ends with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Exact strings matter: several structural tests assert verbatim Korean phrases. Copy skill prose from this plan exactly; if you must rephrase, update the paired test in the same task.

---

### Task 1: `logging.md` outcome enum gains `RETRO_DONE|RETRO_FAIL`

**Files:**
- Modify: `orca-workflows/logging.md` (§1, the `outcome` event recipe around lines 45-53)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Produces: documented enum values `RETRO_DONE`, `RETRO_FAIL` and the extra count fields `filed`/`commented`/`discarded` — Task 3's `orca-workflow` §1d block writes exactly these.

- [ ] **Step 0: Create the branch**

```bash
git checkout -b feat/orca-retro main
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orca_skills.py`:

```python
# --- orca-retro: epic-end skill-defect feedback loop (layer-3) ---


def test_logging_outcome_enum_includes_retro_values():
    text = (WORKFLOWS_DIR / "logging.md").read_text()
    m = re.search(r'"outcome":"<([^>]+)>"', text)
    assert m, "outcome enum line missing in logging.md"
    assert "RETRO_DONE" in m.group(1) and "RETRO_FAIL" in m.group(1), (
        "outcome enum must document the epic-retro results; filing undocumented "
        "values is exactly the drift the retro loop hunts"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orca_skills.py::test_logging_outcome_enum_includes_retro_values -q`
Expected: FAIL with assertion on `RETRO_DONE`

- [ ] **Step 3: Extend the enum**

In `orca-workflows/logging.md`, the `outcome` recipe currently reads:

```
**`outcome`** (`orca-workflow` only — routing result for a task):
```

and its printf enum is `<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION>`.

Make exactly two edits:

1. Replace the enum inside the printf with
   `<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION|RETRO_DONE|RETRO_FAIL>`
2. Directly under that printf block (before the `wave_start`/`wave_end` heading), add:

```markdown
`RETRO_DONE`/`RETRO_FAIL`은 task 라우팅이 아니라 epic retro 결과다 — `orca-workflow` §1d(epic close 직후의
retro 사이트)만 쓴다. `RETRO_DONE` 라인은 per-call-site 추가 필드 규칙에 따라 `filed`/`commented`/`discarded`
정수 카운트를 더해 남기고, `RETRO_FAIL` 라인은 카운트 필드를 생략한다.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_orca_skills.py -q`
Expected: all PASS (regressions included)

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/logging.md tests/test_orca_skills.py
git commit -m "doc(orca-workflows): document RETRO_DONE/RETRO_FAIL outcome values for epic retro

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `skills/orca-retro/SKILL.md` + family registration

**Files:**
- Create: `skills/orca-retro/SKILL.md`
- Modify: `orca-workflows/model-selection.md` (line 9, the orchestration-ownership sentence)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `RETRO_DONE`/`RETRO_FAIL` semantics from Task 1 (the skill's §5 summary is what `orca-workflow` converts into those outcome lines).
- Produces: the skill sections `§0 입력·전제`, `§1 수집`, `§2 결함 후보 — 렌즈 4개`, `§3 증거 기준·상한`, `§4 중복 대조 → 이슈/코멘트`, `§5 보고`, and the §5 summary-line format `RETRO filed=[...] commented=[...] discarded=<n>` — Task 3's dispatch `spec_text` and recv parsing rely on these existing under exactly these section numbers.

- [ ] **Step 1: Write the failing tests**

In `tests/test_orca_skills.py`, change the `NEW_SKILLS` list to:

```python
NEW_SKILLS = ["orca-workflow", "orca-task-runner", "orca-evaluate", "orca-retro"]
```

(This auto-extends the directory/frontmatter/stale-term parametrized checks, and makes
`test_model_selection_references_current_workflow_skills` require `orca-retro` in
`model-selection.md` — handled in Step 3.)

Then append:

```python
def test_orca_retro_files_issues_never_edits_skills():
    text = _read_skill("orca-retro")
    assert "gh issue create" in text, "output channel must be GitHub issues"
    assert "직접 수정하지 않는다" in text, (
        "orca-retro must state it never edits skill files itself"
    )


def test_orca_retro_has_four_defect_lenses():
    text = _read_skill("orca-retro")
    for marker in ("스키마 위반", "반복 FAIL", "ESCALATE", "spawn-failure"):
        assert marker in text, f"orca-retro: defect lens marker missing: {marker}"


def test_orca_retro_evidence_bar_and_issue_cap():
    text = _read_skill("orca-retro")
    assert "원문 인용" in text, "evidence-quote requirement missing"
    assert "최대 3개" in text, "per-epic new-issue cap missing"


def test_orca_retro_dedup_against_open_issues():
    text = _read_skill("orca-retro")
    assert "gh issue list" in text and "--state open" in text, (
        "must check open issues before filing"
    )
    assert "재발 코멘트" in text, "recurrence must become a comment, not a duplicate issue"


def test_orca_retro_schema_lens_scans_unfiltered():
    text = _read_skill("orca-retro")
    assert "issue 필터를 거치지 않고" in text, (
        "lens 1 must scan full dated files — records with a drifted issue field "
        "escape the issue filter"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orca_skills.py -q`
Expected: FAIL — the parametrized `test_skill_directory_exists[orca-retro]`, the five new tests, and `test_model_selection_references_current_workflow_skills`

- [ ] **Step 3: Write the skill and the one-line registration**

In `orca-workflows/model-selection.md`, change line 9 from

```
Workflow orchestration is owned by `orca-workflow`, `orca-task-runner`, and `orca-evaluate`.
```

to

```
Workflow orchestration is owned by `orca-workflow`, `orca-task-runner`, `orca-evaluate`, and `orca-retro`.
```

Create `skills/orca-retro/SKILL.md` with exactly this content:

````markdown
---
name: orca-retro
description: Use right after orca-workflow closes an epic — analyzes only that epic's logs under ~/.local/state/orca-workflows/logs/ (assignments/outcome events, spawn-failures, term transcripts) through four defect lenses (documented-schema violations, repeated FAILs attributable to skill prose, preventable escalations or human interventions, new spawn-failure signatures) and files at most 3 evidence-backed skill-defect issues on the sleeptimegrt-skills repo, deduplicating against open issues via recurrence comments. Never edits skills directly — output is issues only; fixes flow through the normal /orca-workflow pipeline later. Best-effort by contract: no retro failure may block the epic. Self-relative.
---

# Orca Retro

방금 닫힌 epic 하나의 로그만 분석해 **스킬 결함 이슈**를 만든다. 환경(orca-* 스킬군) 자체를 개선하는
피드백 루프의 관측→이슈 단계다. 코드를 만들지 않고, 스킬 파일을 직접 수정하지 않는다 — 산출물은
sleeptimegrt-skills 이슈(또는 기존 이슈의 재발 코멘트)뿐이며, 수정 자체는 나중에 그 이슈를 평소의
`/orca-workflow` 파이프라인이 집어 처리한다.

## 0. 입력·전제

- 입력 3개: epic 이슈 번호, 대상 repo, skills repo(sleeptimegrt-skills)의 GitHub slug.
- child 목록: `~/.agents/orca-workflows/issue-trackers/selection.md` 절차로 백엔드를 정하고
  `list_children(epic-num)`으로 얻는다. epic 자신 + child 전체가 이번 분석의 issue 집합이다.
- 로그 루트 `~/.local/state/orca-workflows/logs/`가 없거나 비어 있으면 §5 요약(filed=0)으로 즉시
  종료한다 — harness 밖에서 처리된 epic은 정상 케이스다.

## 1. 수집

날짜 분할 규칙 때문에 항상 glob으로 읽는다(`~/.agents/orca-workflows/logging.md` §1의
`find | sort | xargs cat` 레시피 — zsh nomatch 회피 포함):

```bash
logs="$HOME/.local/state/orca-workflows/logs"
# issue 집합(epic+children)으로 필터한 assignments/waves 레코드
find "$logs" -name 'assignments*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null \
  | jq -c --argjson set '["<epic-num>","<child-1>","<child-2>"]' 'select(.issue as $i | $set | index($i))'
find "$logs" -name 'waves*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null \
  | jq -c --argjson set '["<epic-num>","<child-1>","<child-2>"]' 'select(.issue as $i | $set | index($i))'
cat "$logs/spawn-failures.jsonl" 2>/dev/null
# term 전사: meta 라인(1행)의 issue가 집합에 드는 파일만 통째로 읽는다
for f in "$logs"/term-*.jsonl; do
  [ -f "$f" ] || continue
  head -1 "$f" | jq -e --argjson set '["<epic-num>","<child-1>","<child-2>"]' \
    'select(.type=="meta" and (.issue as $i | $set | index($i)))' >/dev/null 2>&1 && cat "$f"
done
```

**날짜 범위**: issue 필터에 걸린 레코드의 최소 `ts`부터 현재까지. §2 렌즈 1은 이 범위의 dated 파일
전체 내용을 대상으로 한다(아래).

## 2. 결함 후보 — 렌즈 4개

각 렌즈의 표적은 "스킬 문서를 고치면 사라질 결함"이다. 에이전트의 일회성 실수는 표적이 아니다 —
같은 지점에서 재발했거나, 스킬 문구가 그 실수를 유도·방치했다는 근거가 있어야 한다.

1. **문서화된 스키마 위반** — 각 스킬과 `~/.agents/orca-workflows/logging.md`가 명시한 스키마(enum
   값, 이벤트명, 필드 타입)를 벗어난 로그 레코드. **이 렌즈만은 issue 필터를 거치지 않고** §1 날짜
   범위의 dated 파일 전체를 스캔한다 — `issue` 필드 자체가 드리프트된 레코드는 필터로 잡히지 않는다.
2. **스킬 문구 기인 반복 FAIL** — 같은 FAIL 사유가 task·재시도에 걸쳐 반복되고, term 전사에서
   worker가 스킬 지시를 오독·누락한 정황이 보이는 경우.
3. **예방 가능했던 ESCALATE·인간 개입** — `ESCALATE`·`*_HUMAN_DECISION` 계열 outcome 중, 전사를 보면
   스킬 문구 보강으로 막을 수 있었던 것.
4. **spawn-failure 신규 시그니처** — `spawn-failures.jsonl`에서 `known_issue` 매칭이 없는 항목.

## 3. 증거 기준·상한

- 후보마다 **로그 파일 경로 + 원문 인용(레코드 라인 그대로) 최소 1개**. 인용을 못 붙이는 후보는
  이슈화하지 않고 폐기 카운트에만 넣는다.
- 신규 이슈는 **epic당 최대 3개**. 우선순위: 재발 횟수 → 영향 범위(걸린 스킬·사이트 수). 4번째
  이하 후보는 가장 우선순위 높은 신규 이슈 본문의 "부록" 섹션에 목록으로 넣는다.

## 4. 중복 대조 → 이슈/코멘트

```bash
gh issue list --repo <skills-repo-slug> --state open --json number,title,labels --limit 100
```

- 기존 open 이슈가 같은 결함을 다루면 **새 이슈 대신 그 이슈에 재발 코멘트**를 단다(증거 인용 +
  epic 번호): `gh issue comment <num> --repo <skills-repo-slug> --body "..."`. 재발 코멘트 횟수가
  이 루프의 우선순위 신호다.
- spawn-failure 후보는 `~/.agents/orca-workflows/spawn-failures.md`가 이미 부여한 known_issue
  번호와도 대조한다.
- 신규 결함이면:

```bash
gh issue create --repo <skills-repo-slug> --label retro \
  --title "<대상 스킬>: <결함 한 줄>" \
  --body "<대상 스킬 파일 경로 / 증거 인용(로그 경로+레코드 라인) / epic 번호 / 참조한 로그 경로 / 수정 방향 1문단(diff 금지)>"
```

## 5. 보고

코디네이터에 요약 한 줄만 보낸다(리포트 파일 없음 — 이슈가 곧 산출물):

```
RETRO filed=[#12,#13] commented=[#7] discarded=2
```

수집·분석·gh 어느 단계가 실패해도 가능한 데까지의 카운트와 실패 사실을 같은 형식으로 보고한다 —
이 스킬은 best-effort이며, 실패를 epic 완료로 전파하는 책임은 호출자(`orca-workflow` §1d)에 있다.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orca_skills.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add skills/orca-retro/SKILL.md orca-workflows/model-selection.md tests/test_orca_skills.py
git commit -m "feat(orca-retro): epic-end skill-defect feedback loop skill

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `orca-workflow` §1d retro integration

**Files:**
- Modify: `skills/orca-workflow/SKILL.md` (insert new §1d between the §1c close block, currently ending near line 49, and `## 2. Task 경로`)
- Test: `tests/test_orca_skills.py`

**Interfaces:**
- Consumes: `orca-retro` skill name and its §5 summary format (Task 2); `RETRO_DONE|RETRO_FAIL` + `filed`/`commented`/`discarded` fields (Task 1).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orca_skills.py`:

```python
def test_orca_workflow_runs_retro_after_epic_close():
    text = _read_skill("orca-workflow")
    close_pos = text.index("close_issue(epic-num")
    retro_pos = text.index("orca-retro")
    assert close_pos < retro_pos, (
        "retro must run after close_issue succeeds — running before risks leaving "
        "a fully-done epic open if the coordinator dies mid-retro"
    )


def test_orca_workflow_retro_is_best_effort():
    text = _read_skill("orca-workflow")
    assert "RETRO_FAIL" in text and "RETRO_DONE" in text
    assert "실패시키지 않는다" in text, (
        "retro failures must never fail the workflow"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orca_skills.py -q`
Expected: the two new tests FAIL (`orca-retro` substring absent → ValueError from `.index` counts as failure)

- [ ] **Step 3: Insert §1d**

In `skills/orca-workflow/SKILL.md`, immediately after the §1c code block (the one ending
`close_issue(epic-num, "All child tasks complete: ...")`) and before `## 2. Task 경로`, insert:

````markdown
**1d. Retro (best-effort, epic close 직후)** — 방금 닫힌 epic의 로그를 분석해 스킬 결함 이슈를 만들도록
retro 터미널 1개를 띄워 `orca-retro`를 실행시킨다. close **후**에 실행한다 — close 전에 돌리다
coordinator가 죽으면 child가 전부 닫힌 epic이 열린 채 남는다. retro의 어떤 실패(스폰·dispatch·분석·gh)도
이 워크플로를 실패시키지 않는다: `RETRO_FAIL` outcome만 남기고 정상 종료한다. 이 스킬은 여기서도 로그
본문을 직접 분석하지 않는다 — 분석은 전부 retro 터미널 몫이고, 이 스킬은 §5 요약 한 줄만 받는다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# provider는 model-selection.md 기준 resolve — 판단(judgment) 작업. REPL 필수, agy 제외
# (§2a evaluate 사이트와 같은 제약, 같은 이유).
orca_call_with_retry "orca-workflow" "retro" -- \
  orca terminal create --worktree active --title epic-retro-<epic-num> \
  --command "<REPL 가능, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <retro-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<orca-retro SKILL.md 지침 + epic 번호 + child 목록 + 대상 repo + skills repo(sleeptimegrt-skills) slug>"
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration dispatch --task <task_id> --to <retro-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로, dispatch와 같은 블록에서 즉시:
#  §1 assign 이벤트: role="retro", issue=<epic-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<retro-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-workflow", role="retro", terminal=<retro-handle>, meta 기록 후
#    sent.content=$spec_text. 이 사이트는 §2a의 두 사이트와 달리 요약을 터미널에서 직접 읽으므로,
#    요약 수신 시점에 logging.md §2의 최초-read 레시피(--cursor 없이)로 recv도 기록한다.
# 요약(RETRO filed=[...] commented=[...] discarded=<n>) 수신 후 — 수신 실패·timeout이면 RETRO_FAIL:
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<epic-num>","outcome":"<RETRO_DONE|RETRO_FAIL>","retry":0,"filed":<n>,"commented":<n>,"discarded":<n>}\n' \
  "$(date -u +%FT%TZ)" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
# RETRO_FAIL이면 filed/commented/discarded 필드는 생략한다(logging.md §1). 터미널 close 후 epic 경로 종료.
```
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orca_skills.py -q`
Expected: all PASS — pay attention to the pre-existing `test_orca_workflow_*` regressions

- [ ] **Step 5: Commit**

```bash
git add skills/orca-workflow/SKILL.md tests/test_orca_skills.py
git commit -m "feat(orca-workflow): spawn best-effort orca-retro terminal after epic close

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Fixture pilot (report-only), `retro` label, handoff

**Files:**
- Create (scratchpad only, not committed): `<scratchpad>/retro-fixture/logs/…` fixture files below
- No repo file changes expected unless the pilot exposes a skill-prose defect — then fix `skills/orca-retro/SKILL.md` and its paired tests in this task and commit.

**Interfaces:**
- Consumes: the complete `orca-retro` SKILL.md from Task 2.
- Produces: pilot verdict recorded in the final report to the user; the `retro` label existing on the skills repo.

- [ ] **Step 1: Build the fixture** (epic 500, children 501/502; every path under the session scratchpad)

`retro-fixture/logs/assignments-2026-07-31.jsonl`:

```json
{"ts":"2026-07-31T09:00:00Z","event":"assign","skill":"orca-workflow","role":"task-runner","issue":"999","task_id":"task_zzz","provider":"codex","model":"gpt-5.4-codex","effort":"high","terminal":"term_x9","worktree":"/tmp/wt/issue-999"}
{"ts":"2026-07-31T10:00:00Z","event":"assign","skill":"orca-workflow","role":"task-runner","issue":"501","task_id":"task_aaa","provider":"claude-code","model":"claude-sonnet-5","effort":"high","terminal":"term_r1","worktree":"/tmp/wt/issue-501"}
{"ts":"2026-07-31T10:30:00Z","event":"outcome","skill":"orca-workflow","issue":"501","outcome":"diff-returned","retry":null}
{"ts":"2026-07-31T11:00:00Z","event":"outcome","skill":"orca-workflow","issue":"501","outcome":"FAIL","retry":0}
{"ts":"2026-07-31T11:40:00Z","event":"outcome","skill":"orca-workflow","issue":"501","outcome":"FAIL","retry":1}
{"ts":"2026-07-31T12:00:00Z","event":"recovery","skill":"orca-workflow","issue":"502","terminal":"term_r2"}
{"ts":"2026-07-31T13:00:00Z","event":"outcome","skill":"orca-workflow","issue":"502","outcome":"ESCALATE","retry":0}
{"ts":"2026-07-31T14:00:00Z","event":"outcome","skill":"orca-workflow","issue":"issue-501","outcome":"PASS","retry":0}
```

`retro-fixture/logs/spawn-failures.jsonl`:

```json
{"ts":"2026-07-31T10:05:00Z","skill":"orca-workflow","role":"evaluator","provider":"codex","failure_signature":"error: unexpected argument '--profile'","fix_applied":"manual_relaunch_without_flag"}
```

`retro-fixture/logs/term-term_r1.jsonl`:

```json
{"type":"meta","issue":"501","skill":"orca-workflow","role":"task-runner","terminal":"term_r1","created_at":"2026-07-31T10:00:00Z"}
{"ts":"2026-07-31T10:01:00Z","direction":"sent","content":"issue 501 구현. 게이트: typecheck + unit test. Acceptance Criteria 섹션 기준."}
{"ts":"2026-07-31T11:39:00Z","direction":"recv","content":"typecheck 게이트를 lint로 대체해 실행했습니다. lint 통과, 제출합니다.","cursor_before":null,"cursor_after":120,"dropped":false}
```

`retro-fixture/logs/term-term_r2.jsonl`:

```json
{"type":"meta","issue":"502","skill":"orca-workflow","role":"task-runner","terminal":"term_r2","created_at":"2026-07-31T12:30:00Z"}
{"ts":"2026-07-31T12:31:00Z","direction":"sent","content":"issue 502 구현. Acceptance Criteria 섹션 기준."}
{"ts":"2026-07-31T12:58:00Z","direction":"recv","content":"진행 불가로 escalate: spec에 배포 대상 환경이 명시돼 있지 않아 마이그레이션 대상을 정할 수 없습니다.","cursor_before":null,"cursor_after":88,"dropped":false}
```

Also create an empty directory `retro-fixture-empty/logs/` for the no-logs scenario.

- [ ] **Step 2: Run the report-only pilot (fresh subagent, defect-rich fixture)**

Dispatch a fresh general-purpose subagent with exactly this prompt (fill in the two absolute
paths):

> Read `<repo>/skills/orca-retro/SKILL.md` and execute it as written, with these pilot overrides:
> (1) the log root is `<scratchpad>/retro-fixture/logs` instead of `~/.local/state/orca-workflows/logs`;
> (2) inputs: epic issue 500, children 501 and 502 (do NOT resolve a tracker — take this list as given),
> target repo `example/fixture-target`, skills repo slug `example/sleeptimegrt-skills`;
> (3) run NO `gh` command of any kind. Where the skill says `gh issue list`, use this canned response:
> `[{"number":7,"title":"orca-workflow: outcome 로그가 문서화된 enum 밖 자유 텍스트 값으로 기록되는 드리프트","labels":[{"name":"retro"}]}]`.
> Where the skill says `gh issue create` or `gh issue comment`, print the full would-be command
> including the complete `--body` to stdout instead of executing it.
> End with the §5 summary line.

- [ ] **Step 3: Check the pilot transcript against this checklist**

- (a) Every would-be `gh issue create` body quotes at least one verbatim fixture log line with its file path.
- (b) At most 3 new issues; if more candidates were found, an "부록" section appears in the top-priority issue body.
- (c) The outcome-enum-drift candidate (`diff-returned` / `recovery` / `issue-501` records) became a **comment on #7**, not a new issue.
- (d) Records for issue 999 are cited nowhere except (possibly) lens-1 schema scanning — and since they are schema-clean, they produce no candidate.
- (e) The spawn-failure signature (`--profile`) surfaced via lens 4 (it has no `known_issue`).
- (f) The summary line matches the format `RETRO filed=[...] commented=[...] discarded=<n>`.

Any miss → diagnose whether the defect is in the skill prose; fix `skills/orca-retro/SKILL.md` (and keep paired tests in sync), commit, and re-run this step once.

- [ ] **Step 4: Run the empty-logs pilot**

Same prompt, but log root `<scratchpad>/retro-fixture-empty/logs`, and no canned issue list needed.
Expected: the subagent reports `RETRO filed=[] commented=[] discarded=0` (counts zero) and emits **no**
would-be `gh` command.

- [ ] **Step 5: Create the `retro` label (idempotent)**

```bash
slug="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
gh label list --repo "$slug" --json name -q '.[].name' | grep -qx retro \
  || gh label create retro --repo "$slug" \
       --description "orca-retro가 파일한 스킬 결함" --color 8250df
```

- [ ] **Step 6: Full test run**

Run: `python3 -m pytest tests/ -q`
Expected: all PASS (whole suite, not just the orca file)

- [ ] **Step 7: Finish**

Use superpowers:finishing-a-development-branch to merge `feat/orca-retro` per repo convention (PR
into `main`). After merge, on `main`:

```bash
scripts/deploy-skills.sh orca-retro orca-workflow
```

(`orca-workflows/logging.md` and `model-selection.md` are live immediately via the `~/.agents`
symlink once merged; only `skills/` copies need the deploy script.)
