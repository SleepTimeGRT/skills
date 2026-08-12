# Contract Sprint Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 4 evidence-backed defect patterns in the `orca-task-runner`/`orca-evaluate` contract
sprint (vacuous-pass verification, low AC quality, costly round-cap override, no evaluator-verdict
calibration signal) without replacing the generator/evaluator negotiation pattern itself.

**Architecture:** Pure documentation + bash-logic change across 4 orca-set skills
(`orca-task-runner`, `orca-evaluate`, `orca-workflow-task`, `orca-retro`), the shared
`orca-workflows/contract-schema.md` reference, `orca-workflows/scripts/contract_resume.sh`, and
`tests/test_contract_resume.py`. No new files, agents, or schema-field additions except the
`ROUND3_NEGOTIATION_SINCE` constant pattern (mirrors the existing `R3_REQUIRED_SINCE` pattern from
issue #160).

**Tech Stack:** Markdown (SKILL.md / reference docs), POSIX-ish bash (bash+zsh portable subset, no
arrays/`[[ ]]`/`${!var}`, per `contract_resume.sh`'s existing portability constraints), `jq`, Python
`pytest` (`tests/test_contract_resume.py`).

## Global Constraints

- No prose-pinning tests — this repo deliberately doesn't test exact SKILL.md/doc wording
  (`AGENTS.md`). Only `contract_resume.sh`'s executable behavior gets automated tests.
- `contract_resume.sh` is sourced into both `bash` and `zsh` — no arrays, `[[ ]]`, `${!var}`, or
  glob loops (a non-matching glob aborts the command in zsh).
- Never edit an existing round file in place (`proposal-r1` during `r2`, etc.) — append-only across
  rounds. This plan never violates that; it only adds new round numbers (3, 4) and new prose.
- `orca-task-runner`/`orca-evaluate`/`orca-workflow-task`/`orca-retro` are pinned together by
  `skills/orca-set.version` (currently `v1.1.18`) — touching any one requires bumping the set
  version and redeploying the whole set via `scripts/deploy-skills.sh` (dirty-tree refusal applies
  to all seven members).
- `orca-workflows/contract-schema.md` and `orca-workflows/scripts/contract_resume.sh` deploy via
  the `~/.agents/orca-workflows/` symlink — live immediately on merge to `main`, no separate deploy
  step (`AGENTS.md` issue #22 decision).
- Run `python3 -m pytest tests/ -q` after any script change — this repo has no CI, so this is the
  only verification gate (`AGENTS.md` CI philosophy).

---

## Task 1: `contract-schema.md` — vacuity check + AC three principles (Components 1 & 2)

**Files:**
- Modify: `orca-workflows/contract-schema.md:52` (`fails_before_fix` description, inside the
  `proposal-r<n>.json` code block's surrounding prose)
- Modify: `orca-workflows/contract-schema.md:50` (`draft_acceptance_criteria` description)
- Modify: `orca-workflows/contract-schema.md:234-242` (`## 적대적 판정 지침`)

**Interfaces:**
- Consumes: nothing (pure doc edit, no code dependency)
- Produces: prose that Task 4 (orca-evaluate dispatch spec) references and duplicates into the
  evaluator's spawned spec_text

- [ ] **Step 1: Add the AC three-principles requirement**

In `orca-workflows/contract-schema.md`, find the bullet list under `## proposal-r&lt;n&gt;.json`
that starts with `- **모든 필드 필수.**` (around line 58). Add a new bullet immediately after the
existing `verification_plan[].covers` bullet (around line 63-64):

```markdown
- `draft_acceptance_criteria`의 각 항목은 (a) **binary**(판정 가능 — "좋다/나쁘다" 같은 주관적
  기준 금지) (b) **independent**(정확히 한 가지만 검증 — 여러 조건을 접속사로 묶지 않음) (c) 배열에
  쓰는 순서가 곧 **중요도 순서**(ordered by importance)여야 한다. 새 필드를 추가하지 않는다 — 배열
  순서 자체가 우선순위다. evaluator는 이 3원칙 위반을 `ac_fidelity` 반려 사유로 삼을 수 있다(Spec-
  Driven Development 관행 — round1 반려율 88%의 근본 원인이 AC 자체 품질이라는 실측 근거,
  `docs/superpowers/specs/2026-08-12-contract-sprint-improvements-design.md`).
```

- [ ] **Step 2: Add the vacuity-check requirement to `fails_before_fix`**

Find the sentence "`verification_plan[].fails_before_fix`도 같은 규칙이다..." (line 60). Add a new
sentence immediately after it, still inside the same bullet:

```markdown
  **무동작(no-op) 통과 금지**: `fails_before_fix`를 채울 때, 이 검증 방법이 stub/no-op(빈 구현,
  아무 것도 하지 않는 구현)에서도 통과하는지 스스로 점검한다. 통과한다면 그 검증 방법 자체가
  스키마 위반이다 — 구조적 존재 확인(예: 특정 API 호출 문자열이 소스에 있는지)만으로는 무동작
  구현을 배제하지 못하는 경우가 이에 해당한다. 여러 경로를 커버해도 전부 구조적 확인이면 여전히
  무동작을 통과시킨다는 점에 유의한다(happy-path만 커버 금지 규칙과는 별개 축).
```

- [ ] **Step 3: Add the 5th adversarial-review bullet**

In `## 적대적 판정 지침` (around line 234-243), add a 5th bullet after `"결함을 지어내지 않는다..."`:

```markdown
- "무동작(no-op) 구현을 상상해 이 `verification_plan` 항목이 통과하는지 자문한다 — 통과하면 그
  자체로 결함이다."
```

- [ ] **Step 4: Verify the doc reads consistently**

```bash
grep -n "무동작\|binary\|independent\|ordered by importance" orca-workflows/contract-schema.md
```
Expected: 4 matches (Step 1's bullet mentions all three English terms once each on one line, Step
2's sentence, Step 3's bullet).

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/contract-schema.md
git commit -m "contract-schema: vacuity check + AC three principles (Components 1-2)"
```

---

## Task 2: `contract-schema.md` — round-cap conditional extension (Component 3, schema doc half)

**Files:**
- Modify: `orca-workflows/contract-schema.md:90-140` (`## override.json` and
  `## override 후속 라운드` sections)

**Interfaces:**
- Consumes: nothing new
- Produces: the `ROUND3_NEGOTIATION_SINCE` name and semantics that Task 5 (`orca-workflow-task`)
  and Task 7 (`contract_resume.sh`) both cite and must stay in sync with

- [ ] **Step 1: Insert the new conditional-extension section**

Insert a new `##` section immediately before `## override.json` (before line 90):

```markdown
## 라운드 2→3 조건부 연장 (issue: contract-sprint-improvements, 2026-08-12)

`verdict-r2.json`이 `rejected`이고 `reasons[].target`이 전부 `"plan_coverage"`(즉
`"ac_fidelity"`가 하나도 없음)면, 아래 "override" 절의 라운드 한도(2)에 아직 도달한 것으로 보지
않는다 — override 대신 `proposal-r3.json`(정식 협상 라운드, verdict 있음)을 한 번 더 허용한다.

- `verdict-r3.json` → `approved`: 확정 AC = `proposal-r3`("확정 AC의 정본" 절이 이미 라운드
  번호에 열려 있어 별도 처리 불필요), 정상 종료.
- `verdict-r3.json` → `rejected`이고 `reasons[].target`에 `"ac_fidelity"`가 하나라도 있음: 아래
  "override" 절의 `ac_fidelity` 규칙을 그대로 적용 — `CONTRACT_ESCALATE`(단 `round=3`으로 기록).
- `verdict-r3.json` → `rejected`이고 여전히 `plan_coverage`-only: 아래 "override" 절차를 그대로
  한 라운드 밀어서 수행 — `override.json`(`final_round: 3`) 작성 직후 같은 스텝에서
  `proposal-r4.json`(신규 최종 확정 계약, verdict 없음)을 작성한다.

`ac_fidelity`가 라운드2에 이미 있으면 이 연장은 발동하지 않는다 — 아래 "override" 절의 라운드1→2
규칙이 그대로 적용된다(이 연장은 라운드1→2 게이트를 변경하지 않는다).

**`ROUND3_NEGOTIATION_SINCE`**(이 절 도입 시각 — 아래 "override" 절의 `R3_REQUIRED_SINCE`와 동일
패턴, `orca-workflows/scripts/contract_resume.sh`와 `orca-workflow-task` SKILL.md §1이 정의): 이
연장 도입 이전에는 `verdict-r2.json`이 `plan_coverage`-only로 반려되면 항상 즉시 override했다
(`final_round: 2`). 도입 이후에는 이 절의 규칙대로 라운드3을 먼저 시도한다. `override.json`의
`final_round: 2` + `plan_coverage`-only 조합을 만났을 때, 그 `override.json`의 mtime이 이 상수
이전이면 legacy(정상 종료)로, 이후면 이례 상태(코디네이터/생성기 불일치)로 구분한다 — 정확한
비교 메커니즘은 위 `R3_REQUIRED_SINCE`와 동일(`touch -t` + `find -newer`, TZ=Asia/Seoul 고정).
```

- [ ] **Step 2: Update `## override.json`'s intro sentence**

Change (around line 103):
```markdown
- 2라운드에도 rejected일 때만 존재한다. evaluator의 verdict 파일은 수정하지 않는다 — 판정은
```
to:
```markdown
- 2라운드에도 rejected일 때만 존재한다(위 "라운드 2→3 조건부 연장" 절의 조건에 해당하면 3라운드에
  도달할 때까지 미룬다 — 그 경우 `final_round: 3`). evaluator의 verdict 파일은 수정하지 않는다 —
  판정은
```

- [ ] **Step 3: Generalize `## override 후속 라운드`'s round numbers**

At the start of that section (around line 121), change:
```markdown
override는 협상의 종착점이지 계약의 종착점이 아니다 — override 발동 시 generator는
`override.json`을 쓴 **직후, 같은 스텝에서** `proposal-r3.json`을 새로 쓴다(쓰기 순서 고정:
```
to:
```markdown
override는 협상의 종착점이지 계약의 종착점이 아니다 — override 발동 시 generator는
`override.json`을 쓴 **직후, 같은 스텝에서** 확정 계약(`final_round: 2`면 `proposal-r3.json`,
"라운드 2→3 조건부 연장"이 발동해 `final_round: 3`이면 `proposal-r4.json`)을 새로 쓴다(쓰기 순서
고정:
```

- [ ] **Step 4: Verify no other section hardcodes "proposal-r3" as universally-the-final-round**

```bash
grep -n "proposal-r3" orca-workflows/contract-schema.md
```
Read each match — the "확정 AC의 정본" section (around line 227-232) already says "최종
라운드(가장 큰 n)", so it needs no change. Any other match asserting r3 is always final needs the
same "또는 조건부 연장이 발동했으면 r4" caveat as Step 3.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/contract-schema.md
git commit -m "contract-schema: round-cap conditional extension for plan_coverage-only (Component 3)"
```

---

## Task 3: `orca-task-runner/SKILL.md` — acknowledge the conditional 3rd round

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md:111` (end of §1)

**Interfaces:**
- Consumes: `orca-workflows/contract-schema.md`'s "라운드 2→3 조건부 연장" section (Task 2)
- Produces: nothing new (generator behavior is coordinator-driven; this is acknowledgment text so
  the generator recognizes a round-3 dispatch as a normal proposal round, not an error)

- [ ] **Step 1: Add the acknowledgment sentence**

In `skills/orca-task-runner/SKILL.md` §1, after the sentence ending "...이후 모든 단계(§2 subtask
분해 포함)가 참조하는 확정 AC는 최종 라운드(가장 큰 n) proposal의 `draft_acceptance_criteria`다."
(end of the §1 paragraph, line 111), add:

```markdown
**라운드 2→3 조건부 연장**(`contract-schema.md`): 라운드2 반려 사유가 `plan_coverage`뿐이면,
코디네이터가 override 모드 대신 "라운드3 제안서 작성" 모드로 재호출할 수 있다 — 그 경우 이 스킬은
평소 라운드 갱신과 동일하게(§1 본문의 "반려되면...다시 제안") `verdict-r2.json`을 읽고
`proposal-r3.json`을 작성한다(override.json 작성 없음). 라운드3도 반려되면 그때 override
모드로 재호출된다 — 그 경우 `override.json`(`final_round: 3`) + `proposal-r4.json`(최종
확정)을 쓴다(위 override 절차와 동일하되 라운드 번호만 한 칸씩 밀림).
```

- [ ] **Step 2: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "orca-task-runner: acknowledge round-cap conditional extension"
```

---

## Task 4: `orca-evaluate/SKILL.md` — vacuity/AC-principles instructions + round-cap text

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md:55` (§1 dispatch `spec_text`)
- Modify: `skills/orca-evaluate/SKILL.md:72` (§1's "최대 2라운드까지 왕복" sentence)

**Interfaces:**
- Consumes: Task 1's schema prose (vacuity + AC principles), Task 2's schema prose (round-cap
  extension)
- Produces: nothing new (dispatch spec text only)

- [ ] **Step 1: Add vacuity + AC-principles instructions to the contract-review dispatch spec**

In `skills/orca-evaluate/SKILL.md` §1, the `spec_text=` line (line 55) currently ends with
"...verification_plan[]의 각 항목이 fails_before_fix를 비우지 않았고 fix 전후를 실제로
구분함을 확인하라는 지시 + ...". Insert, right after that clause and before the `+
(라운드 2면)` clause:

```
+ verification_plan[]의 각 항목이 stub/no-op 구현에서도 통과하지 않는지, draft_acceptance_criteria가
binary/independent/ordered-by-importance 3원칙을 지키는지 확인하라는 지시
```

(This makes the full line: `...fails_before_fix를 비우지 않았고 fix 전후를 실제로 구분함을
확인하라는 지시 + verification_plan[]의 각 항목이 stub/no-op 구현에서도 통과하지 않는지,
draft_acceptance_criteria가 binary/independent/ordered-by-importance 3원칙을 지키는지 확인하라는
지시 + (라운드 2면) 같은 문서의 '라운드 2 입력 격리' 규칙 그대로 + ...`)

- [ ] **Step 2: Update the round-cap sentence**

Change (line 72):
```markdown
최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.
```
to:
```markdown
최대 2라운드까지 왕복하되, 라운드2 반려 사유가 `plan_coverage`뿐이면 `contract-schema.md`의
"라운드 2→3 조건부 연장"에 따라 라운드3까지 한 번 더 왕복한다. 그 한도(2 또는 3) 안에 합의 안
되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.
```

- [ ] **Step 3: Commit**

```bash
git add skills/orca-evaluate/SKILL.md
git commit -m "orca-evaluate: vacuity/AC-principles review instructions + round-cap extension text"
```

---

## Task 5: `orca-workflow-task/SKILL.md` — round2→3/round3→4 routing blocks (Component 3, live routing)

**Files:**
- Modify: `skills/orca-workflow-task/SKILL.md:90-154` (§1)

**Interfaces:**
- Consumes: Task 2's `ROUND3_NEGOTIATION_SINCE` semantics
- Produces: the exact jq/round-number pattern that Task 7's `contract_resume.sh` mirrors (per the
  file's own existing rule: "이 분기는 §0 재개 분기의 `contract_resume.sh`가 미러링한다 — 여기를
  바꾸면 그쪽도 함께 바꾼다")

- [ ] **Step 1: Insert the round2→3 extension check before the existing round-limit block**

In §1, immediately before the existing ` ```bash ... if [ ! -f "<CONTRACT_DIR>/override.json" ]; then` block (before line 94), insert:

```markdown
**라운드 2→3 조건부 연장** — 위 "라운드 한도 도달 시점" 분기를 태우기 전에, `verdict-r2.json`이
`rejected`이고 `reasons[].target`이 전부 `"plan_coverage"`면(즉 `ac_fidelity`가 하나도 없으면)
아래 분기 대신 이 분기를 태운다 — 아직 라운드 한도(2)에 도달한 것으로 보지 않는다:

```bash
if jq -e '[.reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/verdict-r2.json" >/dev/null; then
  : # ac_fidelity 있음 — 이 연장은 발동하지 않는다, 아래 "라운드 한도 도달 시점" 분기를 그대로 태운다
else
  # plan_coverage뿐 — override 대신 라운드3 제안서 작성 모드로 orca-task-runner를 재호출한다
  # (spec_text에 round=3 + CONTRACT_DIR + "verdict-r2.json을 읽고 proposal-r3.json 작성" 포함).
  # verdict-r3.json이 approved면 §2로(확정 AC=proposal-r3). rejected면 아래 "라운드 한도 도달
  # 시점" 분기와 동일한 구조를 verdict-r2.json→verdict-r3.json, round=2→3, proposal-r3→proposal-r4로
  # 치환해 그대로 적용한다(아래 두 번째 코드 블록):
  :
fi
```

라운드3이 반려됐을 때(`verdict-r3.json` 존재, `rejected`)의 분기 — 위와 동일한 구조를 한 라운드
밀어서:

```bash
if [ ! -f "<CONTRACT_DIR>/override.json" ]; then
  # 라운드3 한도에 도달했는데 override.json이 없다 — fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif [ ! -f "<CONTRACT_DIR>/verdict-r3.json" ]; then
  # override는 있는데 라운드3 verdict가 없다 — fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif [ ! -f "<CONTRACT_DIR>/proposal-r4.json" ]; then
  # override 기록은 있는데 확정 계약(proposal-r4, final_round=3)이 없다 — 쓰다 죽은 것, 다시 태운다.
  # (이 경로는 ROUND3_NEGOTIATION_SINCE 이후에만 존재할 수 있으므로 R3_REQUIRED_SINCE류의
  # predates-게이트가 필요 없다 — 이 확장 자체가 그 게이트 도입과 동시에 생긴 기능이다.)
elif jq -e '[.reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/verdict-r3.json" >/dev/null; then
  # AC 자체에 이견이 남음 — outcome=CONTRACT_ESCALATE, round=3으로 남기고 §5로.
else
  # 최종 verdict(r3)의 반려가 plan_coverage뿐 — outcome=CONTRACT_FINALIZED_BY_GENERATOR, round=3을
  # 남기고 §2로(확정 AC=proposal-r4).
fi
```

**`ROUND3_NEGOTIATION_SINCE`**: `override.json`의 `final_round`가 `2`이고 verdict-r2가
`plan_coverage`-only인데, 그 `override.json`의 mtime이 이 상수(`contract-schema.md` "라운드 2→3
조건부 연장" 절, `contract_resume.sh`와 동일 — 바꾸면 함께 바꾼다) 이전이면 legacy 세션(정상
종료, 위 "라운드 한도 도달 시점" 분기의 기존 `else` 그대로), 이후면 이례 상태
(outcome=CONTRACT_ESCALATE, detail에 "override.json(final_round=2, plan_coverage-only)이 라운드
2→3 조건부 연장 도입 이후 발견됨 — 코디네이터/생성기 불일치" 기록). 비교 메커니즘은 기존
`R3_REQUIRED_SINCE` 블록(위, line 111-138)과 동일한 `touch -t` + `find -newer` 패턴을 상수만
바꿔 재사용한다.
```

- [ ] **Step 2: Update the existing round-limit block's `elif` for ac_fidelity to note it's unchanged**

No code change needed to the existing block (lines 94-153) — it still operates on `verdict-r2.json`
exactly as before, and now only fires when `verdict-r2.json` has `ac_fidelity` (the new Step 1
branch intercepts the `plan_coverage`-only case first). Add one clarifying sentence right after the
block's closing ` ``` ` (after line 154):

```markdown
(이 분기는 위 "라운드 2→3 조건부 연장"이 발동하지 않은 경우 — 즉 `verdict-r2.json`에
`ac_fidelity`가 있는 경우에만 실행된다. 발동한 경우는 위 두 번째 코드 블록을 대신 따른다.)
```

- [ ] **Step 3: Commit**

```bash
git add skills/orca-workflow-task/SKILL.md
git commit -m "orca-workflow-task: round2->3/round3->4 routing for plan_coverage-only extension"
```

---

## Task 6: `orca-retro/SKILL.md` — 6th lens: contract-verdict vs downstream outcome (Component 4)

**Files:**
- Modify: `skills/orca-retro/SKILL.md` (wherever the existing 5 lenses are enumerated)

**Interfaces:**
- Consumes: `verdict-r*.json`/`override.json`/`eval-report-a*.json` file shapes (unchanged by this
  plan)
- Produces: nothing new (adds a 6th lens to an existing enumerated list; reuses the existing
  "invocation당 최대 3건" cap and duplicate-prevention rule)

- [ ] **Step 1: Read the existing 5-lens list to match its exact prose style and structure**

```bash
grep -n "렌즈\|lens" skills/orca-retro/SKILL.md
```

- [ ] **Step 2: Add the 6th lens**

Add a 6th enumerated lens (matching the surrounding numbered-list format found in Step 1) with this
content:

```markdown
6. **contract-verdict 오판 대조**: 이 invocation이 다룬 issue들 중 `verdict-r*.json`이
   `approved` 또는 `plan_coverage`-only `override`로 종결된 것을 골라, 같은 issue의 최종
   `eval-report-a*.json`의 FAIL findings 또는 human escalation 기록과 대조한다. 다운스트림에서
   같은 결함(같은 `ac_id` 또는 같은 지적 내용)이 실제로 재현되면, evidence-backed defect issue로
   파일링한다(기존 "invocation당 최대 3건" 한도, 기존 중복 방지 — open issue에 recurrence 코멘트
   — 규칙 그대로 적용).
```

- [ ] **Step 3: Update any "5개 렌즈" count references elsewhere in the same file or in AGENTS.md**

```bash
grep -rn "5개 렌즈\|five.*lens\|5 lens" skills/orca-retro/SKILL.md AGENTS.md
```
Update any match to "6개 렌즈"/"six lenses".

- [ ] **Step 4: Commit**

```bash
git add skills/orca-retro/SKILL.md
git commit -m "orca-retro: add contract-verdict vs downstream-outcome lens (Component 4)"
```

---

## Task 7: `contract_resume.sh` + `tests/test_contract_resume.py` — round-cap extension (TDD)

**Files:**
- Modify: `orca-workflows/scripts/contract_resume.sh`
- Modify: `tests/test_contract_resume.py`

**Interfaces:**
- Consumes: Task 2/5's `ROUND3_NEGOTIATION_SINCE` semantics (must match exactly — same constant
  name, same touch-t/find-newer mechanism as `R3_REQUIRED_SINCE`)
- Produces: `contract_resume_state()`'s JSON output now recognizes rounds 3 and 4 and the
  `final_round` field on `override.json`

### Step 1: Write the failing tests first

Open `tests/test_contract_resume.py`. **Rename and change the expectation** of the existing test
that will no longer hold once the extension ships:

Replace (lines 176-186):
```python
@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r2_without_override_resumes_override_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3  # the proposal round the override step produces (issue #130)
```
with:
```python
@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r2_plan_coverage_only_resumes_round3_proposal(tmp_path: Path, shell: str) -> None:
    """Round-cap conditional extension: plan_coverage-only at round 2 gets one more negotiated
    round instead of an immediate override (contract-sprint-improvements design, 2026-08-12)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-proposal"
    assert state["round"] == 3


@pytest.mark.parametrize("shell", SHELLS)
def test_rejected_r2_with_ac_fidelity_still_resumes_override_step(tmp_path: Path, shell: str) -> None:
    """ac_fidelity at round 2 is unchanged by the extension -- still goes straight to override."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage", "ac_fidelity"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 3
```

Add new tests after `test_r3_without_override_or_approval_escalates` (after line 375) — first
update that existing test's fixture, since `proposal-r3` without override is now a **legitimate**
in-flight state (waiting for `verdict-r3`), not automatically out-of-contract:

Replace (lines 363-375):
```python
@pytest.mark.parametrize("shell", SHELLS)
def test_r3_without_override_or_approval_escalates(tmp_path: Path, shell: str) -> None:
    """proposal-r3+ may only exist after override — anything else is an out-of-contract state."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"
```
with:
```python
@pytest.mark.parametrize("shell", SHELLS)
def test_r3_proposal_without_verdict_resumes_verdict_step(tmp_path: Path, shell: str) -> None:
    """proposal-r3 without override.json is now legitimate: the round-2->3 extension's negotiated
    round, waiting for verdict-r3 (not the old out-of-contract state)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-1-verdict"
    assert state["round"] == 3


@pytest.mark.parametrize("shell", SHELLS)
def test_r4_without_override_or_approval_escalates(tmp_path: Path, shell: str) -> None:
    """proposal-r4+ may only exist after a final_round=3 override -- anything else is
    out-of-contract (the extension's equivalent of the old r3 guard)."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r4.json", _proposal(4))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_approved_resumes_generate_attempt1(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "approved"))
    state = _state(d, shell)
    assert state["contract"] == "approved"
    assert state["approved_round"] == 3
    assert state["resume"] == "section-2"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_rejected_ac_fidelity_escalates_round3(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["ac_fidelity"]))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_r3_rejected_plan_coverage_only_resumes_override_round4(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 4


def _override_r3(unresolved: list[str] | None = None) -> dict:
    return {
        "schema_version": 1, "issue": "42", "overridden_by": "generator",
        "final_round": 3,
        "unresolved_reasons": [{"target": t, "ac_id": None, "reason": "x"} for t in (unresolved or [])],
    }


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_with_ac_fidelity_escalates(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage", "ac_fidelity"]))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_without_verdict_r3_fails_closed(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_without_r4_reruns_override_step(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override_r3())
    state = _state(d, shell)
    assert state["resume"] == "section-1-override"
    assert state["round"] == 4


@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round3_plan_coverage_only_finalizes(tmp_path: Path, shell: str) -> None:
    d = tmp_path / "issue-42"
    _write(d, "proposal-r3.json", _proposal(3))
    _write(d, "verdict-r3.json", _verdict(3, "rejected", ["plan_coverage"]))
    _write(d, "override.json", _override_r3())
    _write(d, "proposal-r4.json", _proposal(4))
    state = _state(d, shell)
    assert state["contract"] == "finalized"
    assert state["approved_round"] == 4
    assert state["resume"] == "section-2"
```

Now fix the two existing tests that assumed `final_round: 2` + `plan_coverage`-only always
finalizes — under the extension, that combination is only legitimate **before**
`ROUND3_NEGOTIATION_SINCE`. Add the constant and backdate `_finalized_contract`'s `override.json`:

After the existing `R3_REQUIRED_SINCE_EPOCH` constant (line 248), add:
```python
ROUND3_NEGOTIATION_SINCE_EPOCH = <FILL IN AT IMPLEMENTATION TIME, SEE TASK 7 STEP 3>
# mirrors contract_resume.sh's ROUND3_NEGOTIATION_SINCE
```

Change `_finalized_contract` (lines 212-219) to backdate `override.json` before that gate:
```python
def _finalized_contract(d: Path) -> None:
    """Round limit hit, plan_coverage-only rejection, override step completed (override + r3).
    Backdated before ROUND3_NEGOTIATION_SINCE: this is the legacy final_round=2 finalize path --
    post-gate, plan_coverage-only at round 2 goes through the round-3 extension instead (see
    test_rejected_r2_plan_coverage_only_resumes_round3_proposal)."""
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, ROUND3_NEGOTIATION_SINCE_EPOCH - 3600)
    _write(d, "proposal-r3.json", _proposal(3))
```
(`_write`'s default `_age()` call on `proposal-r3.json` is fine — only `override.json`'s mtime
matters for this gate.)

Add a new test for the post-gate anomaly case, right after `test_override_plan_coverage_only_finalizes_and_resumes_generate`:
```python
@pytest.mark.parametrize("shell", SHELLS)
def test_override_final_round2_plan_coverage_after_gate_is_anomalous(tmp_path: Path, shell: str) -> None:
    """final_round=2 + plan_coverage-only found AFTER ROUND3_NEGOTIATION_SINCE should never happen
    if the coordinator routes correctly (post-gate, that case goes through round-3 negotiation
    instead) -- fail closed to CONTRACT_ESCALATE rather than silently finalizing."""
    d = tmp_path / "issue-42"
    _write(d, "proposal-r1.json", _proposal(1))
    _write(d, "verdict-r1.json", _verdict(1, "rejected", ["plan_coverage"]))
    _write(d, "proposal-r2.json", _proposal(2))
    _write(d, "verdict-r2.json", _verdict(2, "rejected", ["plan_coverage"]))
    override_path = _write(d, "override.json", _override(), fresh=True)
    _set_mtime(override_path, ROUND3_NEGOTIATION_SINCE_EPOCH + 3600)
    _write(d, "proposal-r3.json", _proposal(3))
    state = _state(d, shell)
    assert state["resume"] == "section-5"
    assert state["outcome"] == "CONTRACT_ESCALATE"
```

- [ ] **Step 2: Run the new/changed tests to verify they fail against the current script**

```bash
python3 -m pytest tests/test_contract_resume.py -q -k "round3 or round4 or r3_ or r4_ or final_round3 or plan_coverage_after_gate"
```
Expected: multiple FAILs (the script doesn't know about round 3/4 or `final_round` yet) —
`test_r3_approved_resumes_generate_attempt1` may already PASS (it only depends on the generic
top-of-function scanning loop, which is round-number-agnostic) — that's fine, it's a regression
guard, not a new-behavior test.

- [ ] **Step 3: Choose and record the `ROUND3_NEGOTIATION_SINCE` timestamp**

```bash
date -u -v+5M +'%Y-%m-%dT%H:%M:%S' 2>/dev/null || date -u -d '+5 minutes' +'%Y-%m-%dT%H:%M:%S'
```
Convert that UTC instant to Asia/Seoul and to `touch -t` format (`[[CC]YY]MMDDhhmm[.SS]`), matching
`R3_REQUIRED_SINCE`'s format. Fill in the `ROUND3_NEGOTIATION_SINCE_EPOCH` placeholder in the test
file (Unix epoch seconds for that same instant) and the `ROUND3_NEGOTIATION_SINCE` string constant
in the script (Step 4). Commit within 5 minutes of choosing it (Step 6) — if you miss the window,
re-run this step with a fresh timestamp before committing.

- [ ] **Step 4: Implement the script changes**

In `orca-workflows/scripts/contract_resume.sh`:

Generalize the gate-comparison helper (after `_cr_predates_r3_gate`'s closing `}`, currently ending
around line 104) — keep the old name as a thin wrapper so the one existing call site needs no edit:

```bash
_cr_predates_gate() {
  # Generalized form of _cr_predates_r3_gate: $1 = probed file, $2 = cutoff (touch -t format).
  # Same two-failure-mode handling as the original (see _cr_predates_r3_gate's comment above for
  # the full rationale) -- kept as one function so both gates share the one proven mechanism.
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
```

Replace the body of the original `_cr_predates_r3_gate` (lines 62-104) with the two functions above
(the doc comment above it, lines 62-83, stays — it still accurately describes the shared mechanism).

Add the new constant right after `R3_REQUIRED_SINCE='202608120944.57'` (line 60):

```bash
# Round-cap conditional extension (docs/superpowers/specs/2026-08-12-contract-sprint-improvements-design.md):
# before this gate, a round-2 rejection with plan_coverage-only reasons went straight to override
# (final_round=2, finalizing at proposal-r3). After this gate, that same rejection instead gets one
# more negotiated round (proposal-r3/verdict-r3) before override -- and override.json's final_round
# becomes 3, with proposal-r4 the final contract. Same touch -t + find -newer mechanism as
# R3_REQUIRED_SINCE (via _cr_predates_gate above), disambiguates a final_round=2 override.json's
# plan_coverage-only "finalized" reading (legacy, pre-gate) from an inconsistency (post-gate,
# should never happen if orca-workflow-task §1 routes correctly).
# orca-workflow-task SKILL.md §1's identical constant -- bump it together with this one.
ROUND3_NEGOTIATION_SINCE='<FILLED IN AT STEP 3>'
```

Replace the "still in flight" `else` block's tail (the `elif [ "$maxp" -ge 3 ]` through the closing
of that whole `else` clause, lines 234-252) with:

```bash
    elif [ "$maxp" -ge 4 ]; then
      # proposal-r4+ may only exist after a final_round=3 override (write order is
      # override-first, same as the old r3 rule) or never otherwise. Out-of-contract state.
      contract="escalated"; resume="section-5"; outcome='"CONTRACT_ESCALATE"'
      detail='"proposal-r4+ exists without override.json or an approved verdict (out-of-contract state)"'
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
```

Replace the `elif [ "$override_ok" = "1" ]; then ... fi` block (the whole branch, lines 199-229)
with:

```bash
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
```

Update the `cap=20` comment (line 134-135) to reflect the new max:

```bash
  # Counter cap: rounds are limited to 2 (or 3 with the plan_coverage-only conditional extension)
  # and FAIL retries to 2 (max attempt 3) by orca-workflow-task §1/§4, so 20 is unreachable
  # headroom, not a tunable.
```

- [ ] **Step 5: Run the tests again to verify they pass**

```bash
python3 -m pytest tests/test_contract_resume.py -q
```
Expected: all PASS, including every pre-existing test (the legacy paths must not regress).

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/scripts/contract_resume.sh tests/test_contract_resume.py
git commit -m "contract_resume: round-cap conditional extension (rounds 3-4, final_round dispatch)"
```
Immediately after committing, verify the commit landed at/after the chosen timestamp:
```bash
git log -1 --format=%cI
```
If the commit timestamp is **before** the `ROUND3_NEGOTIATION_SINCE`/`ROUND3_NEGOTIATION_SINCE_EPOCH`
values you filled in (Step 3), the gate would treat this very commit's own artifacts as pre-gate —
amend the commit (`git commit --amend --no-edit`) to update its timestamp, or lower the constants to
match the actual commit time and amend, then re-verify.

---

## Task 8: Full validation, version bump, deploy

**Files:**
- Modify: `skills/orca-set.version`

**Interfaces:**
- Consumes: all prior tasks' committed state
- Produces: none (terminal task)

- [ ] **Step 1: Run the full test suite**

```bash
python3 -m pytest tests/ -q
```
Expected: all PASS. This is the only automated gate in this repo (`AGENTS.md` CI philosophy) — do
not skip it.

- [ ] **Step 2: Confirm the working tree is clean per-skill**

```bash
git status --short skills/orca-task-runner skills/orca-evaluate skills/orca-workflow-task skills/orca-retro
```
Expected: empty (everything from Tasks 3-6 already committed).

- [ ] **Step 3: Bump the orca-set version**

Edit `skills/orca-set.version`'s first line from `v1.1.18` to `v1.1.19` (members list on the
following lines is unchanged — same seven skills).

```bash
git add skills/orca-set.version
git commit -m "orca-set: bump to v1.1.19 for contract-sprint-improvements"
```

- [ ] **Step 4: Deploy the orca-set**

```bash
scripts/deploy-skills.sh orca-task-runner
```
(Deploying any one member deploys the whole pinned set at the new version — confirm the script's
own output reports all seven members, and that it refuses if any is dirty.)

- [ ] **Step 5: Report completion**

Summarize for the user: which 4 components shipped, the `ROUND3_NEGOTIATION_SINCE` timestamp
chosen (Task 7 Step 3), and that `orca-workflows/contract-schema.md` +
`orca-workflows/scripts/contract_resume.sh` are already live (symlink deploy, no separate step)
while the orca-set skills just got redeployed via Step 4.
