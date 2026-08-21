# orca-workflow-task hitl 경로에 superpowers(brainstorming/writing-plans/SDD) 도입 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `orca-workflow-task`의 `mode=hitl` 경로가 지금 brainstorming의 질문 스타일만 흉내내고 산출물을 만들지 않던 것을, 실제로 `superpowers:brainstorming`→`superpowers:writing-plans`를 호출하고 그 플랜을 `orca-task-runner`의 새 SDD 태스크 루프(codex/agy까지 포함한 provider fan-out)로 실행하도록 바꾼다.

**Architecture:** `orca-workflow-task` §1의 hitl generator 역할이 brainstorming을 실제로 호출해 spike/bounded/architectural로 분류하고, architectural만 writing-plans까지 이어가 플랜 문서를 만든다. 그 플랜 문서의 경로(`plan_path`)를 `proposal-r<n>.json`의 새 필수(nullable) 필드에 실어 `orca-task-runner`에 전달하면, `orca-task-runner`는 그 필드가 non-null일 때만 새 "SDD 태스크 루프" 섹션(§2~§5의 native DAG/wave를 대체)으로 들어간다 — 태스크 순차 실행, `model-selection.md` 휴리스틱으로 claude/codex/agy 중 provider 선택, 태스크별 LLM 리뷰어+fix-loop, SDD의 final whole-branch review는 생략. `orca-task-runner`(code-gen) ↔ `orca-evaluate`(evaluator) 관계는 완전히 무변경.

**Tech Stack:** Markdown SKILL.md 프로시(LLM이 읽고 따르는 절차 문서, 대부분 기계적으로 파싱되지 않음), 일부 fenced bash(POSIX 호환, bash+zsh 양쪽에서 실행 가능해야 함), Python 3 + pytest(기존 실행-기반 테스트 스위트).

**Spec:** `docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md`

## Global Constraints

- `mode=afk`는 전혀 건드리지 않는다 — afk에는 사람이 없어 brainstorming 승인 게이트가 성립하지 않는다.
- `orca-evaluate`의 내부 로직, `orca-workflow-task` §1의 라운드 한도/override 라우팅 bash, §2 감사 게이트, §3 evaluate 호출은 전부 무변경 — "code-gen ↔ evaluator" 관계를 유지한다는 사용자 요청.
- `proposal-r<n>.json`은 "모든 필드 필수 — 필드가 아예 없으면 스키마 위반"이라는 기존 원칙(`contract-schema.md`, `destructive_operations`/`existing_tests_affected`가 이미 빈 배열로 이 원칙을 지킴)을 따른다. `plan_path`는 옵셔널이 아니라 **필수+nullable** 필드다 — bounded/spike/afk에서는 값이 `null`, architectural에서만 절대경로 문자열.
- `superpowers:subagent-driven-development` 스킬 파일 자체를 호출하지 않는다 — 그 스킬의 서브에이전트 dispatch는 Claude Agent tool 전용이라, "self-relative(어느 provider가 이 세션을 돌리든 동일 동작)"인 `orca-task-runner`의 전제와 구조적으로 안 맞는다. 그 스킬의 패턴만 `orca-task-runner` 자신의 절차로 포팅한다.
- `plan_path`가 SDD 루프 진입의 유일한 신호이려면 `orca-task-runner` §1(afk 전용 proposal 작성)도
  이 필드를 항상 `null`로 명시적으로 써야 한다 — 그러지 않으면 필수 필드 요구사항 위반이거나,
  afk가 의도치 않게 SDD 루프로 오분류될 위험이 있다(advisor 리뷰에서 발견, Task 5 Step 1이 처리).
- spike 분기는 새 outcome `SPIKE_ANSWERED`를 로깅해야 한다 — 로깅 없이 종료하면 `orca-retro`/감사
  도구가 이 invocation을 볼 수 없다(advisor 리뷰에서 발견, Task 3이 등록).
- `skills/orca-workflow-task/SKILL.md`와 `skills/orca-task-runner/SKILL.md`는 둘 다 `orca-set`(`skills/orca-set.version`, 현재 `v1.1.31`) 멤버다 — 두 파일이 함께 바뀌므로 버전은 한 번만 올린다.
- `skills/orca-task-runner/SKILL.md`의 frontmatter `description`은 1024자 캡(`tests/test_skill_description_length.py`)을 넘지 않아야 한다(현재 629자).
- Bash 블록은 이 저장소의 기존 컨벤션대로 배열·`[[ ]]`·`${!var}`·glob 루프 없이 POSIX 호환으로 쓴다(zsh에서도 그대로 돈다).
- AGENTS.md: 이 저장소의 "prose-pinning" 테스트(SKILL.md 특정 문구·순서를 그대로 고정하는 테스트)는 반-패턴으로 이미 삭제됐다 — 이 플랜은 그런 테스트를 새로 추가하지 않는다. 실행 가능한 fenced bash 로직에만 테스트를 붙인다.

---

## File Structure

| File | Responsibility |
|---|---|
| `orca-workflows/contract-schema.md` | `proposal-r<n>.json` 스키마에 필수(nullable) `plan_path` 필드 추가 |
| `skills/orca-workflow-task/SKILL.md` | §1: hitl generator 역할을 brainstorming/writing-plans 실호출 + 분류 분기(spike는 `SPIKE_ANSWERED` 로깅)로 재작성. §2: 두 spec_text 템플릿(라운드1 재사용분 + FAIL 재시도분)에 `plan_path` 전달 추가 |
| `orca-workflows/scripts/log_dispatch.sh` | 신규 outcome `SPIKE_ANSWERED`를 `LOG_OUTCOME_ENUM`에 등록 |
| `orca-workflows/logging.md` | `SPIKE_ANSWERED`의 사람이 읽는 축 목록 + 설명 문단 추가 |
| `tests/test_log_outcome.py` | `DOCUMENTED_OUTCOME_ENUM` 크로스체크에 `SPIKE_ANSWERED` 추가 |
| `skills/orca-task-runner/SKILL.md` | §1 필드 목록에 `plan_path: null` 지시 추가. 새 "SDD 태스크 루프" 섹션(§1과 §2 사이) + 진입 분기 bash + 서두/§4/frontmatter description의 "리뷰어 없음" 문장에 예외 추가 |
| `tests/test_sdd_loop_entry_branch.py` | 신설 — `plan_path` 유무에 따른 SDD 루프 진입 분기 bash를 고정 |
| `skills/orca-set.version` | 버전 bump |

---

### Task 1: `contract-schema.md` — `proposal-r<n>.json`에 `plan_path` 필드 추가

**Files:**
- Modify: `orca-workflows/contract-schema.md:46-61` (스키마 JSON 블록), `:63-65` ("모든 필드 필수" 불릿)

**Interfaces:**
- Produces: `plan_path`(string|null) — Task 2(`orca-workflow-task` §1, hitl)와 Task 5 Step 1
  (`orca-task-runner` §1, afk)가 채우고, Task 5의 SDD 진입 분기가 읽는 값의 정본 스키마.

이 파일은 순수 문서(스키마 설명)이고 파싱 스크립트가 없다 — 이 저장소의 실행-기반 테스트 정책상
자동 테스트는 없다(AGENTS.md, "prose-pinning 테스트는 반-패턴"). 검증은 Step 3의 수동 재확인이다.

- [ ] **Step 1: 스키마 JSON 블록에 `plan_path` 필드 추가**

`orca-workflows/contract-schema.md`에서 (현재 46-61행) 다음을 교체:

```markdown
## proposal-r&lt;n&gt;.json

```json
{
  "schema_version": 1,
  "issue": "<issue id — GitHub 번호든 Jira 키든 문자열>",
  "run_id": "<orchestration run id>",
  "task_id": "<이 라운드의 task id>",
  "round": 1,
  "draft_acceptance_criteria": [ {"id": "ac1", "text": "<판정 가능한 완료 기준>"} ],
  "scope": { "summary": "<무엇을 만들 것인가 — 사실 서술만>", "files": ["<path>"] },
  "verification_plan": [ {"covers": ["ac1"], "method": "<구체 파일/함수/테스트>", "fails_before_fix": "<이 항목이 fix 이전에 어떻게 실패하는지, 또는 왜 실패할 수 없는지>"} ],
  "destructive_operations": [ "<의도된 destructive op 설명>" ],
  "existing_tests_affected": [ {"location": "<file:line>", "reason": "<이 변경으로 red가 되는 이유>"} ]
}
```
```

다음으로:

```markdown
## proposal-r&lt;n&gt;.json

```json
{
  "schema_version": 1,
  "issue": "<issue id — GitHub 번호든 Jira 키든 문자열>",
  "run_id": "<orchestration run id>",
  "task_id": "<이 라운드의 task id>",
  "round": 1,
  "draft_acceptance_criteria": [ {"id": "ac1", "text": "<판정 가능한 완료 기준>"} ],
  "scope": { "summary": "<무엇을 만들 것인가 — 사실 서술만>", "files": ["<path>"] },
  "verification_plan": [ {"covers": ["ac1"], "method": "<구체 파일/함수/테스트>", "fails_before_fix": "<이 항목이 fix 이전에 어떻게 실패하는지, 또는 왜 실패할 수 없는지>"} ],
  "destructive_operations": [ "<의도된 destructive op 설명>" ],
  "existing_tests_affected": [ {"location": "<file:line>", "reason": "<이 변경으로 red가 되는 이유>"} ],
  "plan_path": "<superpowers:writing-plans가 쓴 플랜 문서의 절대경로, architectural 분류가 아니면 null>"
}
```
```

- [ ] **Step 2: "모든 필드 필수" 불릿에 `plan_path`의 null 의미 설명 추가**

`orca-workflows/contract-schema.md`에서 (현재 63-65행 시작 부분) 다음 문장 뒤에:

```markdown
- **모든 필드 필수.** `destructive_operations`/`existing_tests_affected`의 빈 배열 `[]`은
  "명시적으로 없음"이다 — 필드가 아예 없으면 스키마 위반이므로 "언급 안 함" 상태는 존재할 수
  없다(종전 prose 제안서의 "공란 vs 없음" 구분을 스키마 필수성이 대체한다).
```

같은 문단에 이어서(그 다음 문장 "`verification_plan[].fails_before_fix`도 같은 규칙이다" 앞에)
아래 문장을 추가:

```markdown
  `plan_path`도 같은 원칙이다 — `null`이 "이 라운드는 architectural 분류가 아니라 플랜 문서가
  없음"의 명시값이다(issue: 직접 이슈 없음, `docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md`). `orca-task-runner`는 이 필드가 non-null일 때만 SDD 태스크 루프로
  진입한다(그 스킬 SKILL.md의 "SDD 태스크 루프" 절 참고).
```

- [ ] **Step 3: 수동 재확인**

전체 스키마 블록을 다시 읽어 JSON이 유효한지(쉼표 누락 등), `plan_path`가 다른 필드와 같은
스타일(`<...>` placeholder 설명)로 쓰였는지 확인한다.

- [ ] **Step 4: Commit**

```bash
git add orca-workflows/contract-schema.md
git commit -m "$(cat <<'EOF'
contract-schema: proposal-r<n>.json에 plan_path 필수(nullable) 필드 추가

architectural 분류된 hitl 태스크가 writing-plans의 플랜 문서 경로를
orca-task-runner에 구조적으로 전달할 수 있도록 한다. "모든 필드 필수"
기존 원칙을 따라 옵셔널이 아니라 null-허용 필수 필드로 추가한다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `orca-workflow-task` SKILL.md §1 — hitl generator 역할을 실제 brainstorming/writing-plans 호출로 재작성

**Files:**
- Modify: `skills/orca-workflow-task/SKILL.md:317-343` (§1 "mode=hitl일 때 generator 역할" 절)

**Interfaces:**
- Consumes: `superpowers:brainstorming`, `superpowers:writing-plans`(둘 다 외부 스킬 — 이 스킬은 그
  스킬들을 호출하는 절차만 서술한다).
- Produces: `proposal-r<n>.json`(Task 1의 스키마, `plan_path` 필드 포함, spike 분기는 `SPIKE_ANSWERED`
  outcome을 남기고 이 파일 자체를 쓰지 않음 — Task 3이 그 outcome 값을 등록) — Task 4(§2)가 이
  필드를 읽어 `orca-task-runner` dispatch에 전달한다.

이 절 전체가 프로즈(코디네이터 역할의 LLM이 따르는 절차 서술)이고 파싱되는 bash가 없다 — 자동
테스트는 없다(위 Global Constraints). 검증은 Step 2의 수동 재확인이다.

- [ ] **Step 1: §1 "mode=hitl일 때 generator 역할" 절의 첫 불릿을 교체**

`skills/orca-workflow-task/SKILL.md`에서 (현재 317-343행) 다음 전체를 교체 대상으로 삼는다 —
헤더 문장과 마지막 세 불릿("질문 전달 경로", "아래 라운드-한도/override 라우팅...", "afk는...")은
그대로 두고, 그 사이의 첫 번째 불릿("대화 방식은 `superpowers:brainstorming`의 질문법을...")만
교체한다.

기존 (헤더 문장 + 첫 불릿, 317-329행):

```markdown
**mode=hitl일 때 generator 역할(issue #180)** — 별도 스폰 없이 코디네이터 자신이 처리한다. 아래
"라운드 1"·"라운드 2+" 블록 중 **task-runner를 향하는 부분**(대상이 evaluator인 부분은 라운드·mode
무관하게 항상 그대로 스폰한다)은 hitl에서 실행하지 않는다. `proposal-r<n>.json`(라운드 1이든 2+든)과
`override.json`은 이 코디네이터 세션이 사람과 직접 협의해 쓴다:

- 대화 방식은 `superpowers:brainstorming`의 질문법(한 번에 한 질문, 2-3안 제시 후 추천, 섹션별 승인)을
  따르되, **그 스킬 자신의 종료 조건은 따르지 않는다** — `docs/superpowers/specs/`에 디자인 문서를
  쓰고 커밋하는 스텝, `writing-plans` 호출 스텝 둘 다 여기서는 존재하지 않는다. 대신 사람이
  draft_acceptance_criteria·scope·verification_plan에 합의하면 그 자리에서 `contract-schema.md`
  스키마대로 `proposal-r<n>.json`(라운드 1은 초안부터, 2+는 직전 `verdict-r<n-1>.json`의 반려 사유를
  반영)을 CONTRACT_DIR에 직접 쓴다. override 단계도 동일 — 아래 라운드-한도 분기가 override 시점에
  도달했다고 판정하면, 그 사유(`verdict-r2.json`의 `reasons`)를 사람에게 그대로 보여주고 진행할지
  묻는다. 진행이면 `override.json` + 확정 `proposal-r<n+1>.json`을 이 자리에서 쓴다.
```

다음으로:

```markdown
**mode=hitl일 때 generator 역할(issue #180, 2026-08-22 확장 — 설계 근거:
`docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md`)** — 별도 스폰
없이 코디네이터 자신이 처리한다. 아래 "라운드 1"·"라운드 2+" 블록 중 **task-runner를 향하는
부분**(대상이 evaluator인 부분은 라운드·mode 무관하게 항상 그대로 스폰한다)은 hitl에서 실행하지
않는다.

- **먼저 `superpowers:brainstorming`을 실제로 호출한다**(입력: 이슈 원문) — 그 스킬 자신의
  분류(spike/bounded/architectural)를 그대로 따른다:
  - **spike**(드묾 — "이게 가능한가"류 이슈): 코드 변경이 산출물이 아니므로 이 §1~§2 전체를
    건너뛴다. 조사 결과를 이슈에 코멘트로 남기고 사람에게 다음 행동(이슈 재정의/종료)을 물은 뒤,
    `log_dispatch`로 `outcome=SPIKE_ANSWERED`를 남기고(Task 3이 이 값을 등록한다) 보고 채널로
    종료를 알린다 — 아래 §5의 일반 "그 외 outcome"(hitl/afk 재분기, 계속/중단 선택지)은 타지
    않는다: 사람의 결정은 이미 여기서 끝났다. §0이 만든 worktree/Run/CONTRACT_DIR는 다른
    outcome들과 동일하게 보존한다(정리 로직을 새로 만들지 않는다). `orca-task-runner`/
    `orca-evaluate` 모두 호출하지 않는다.
  - **bounded**(이미 있는 흐름의 작은 범위 수정): brainstorming이 규정한 대로 스펙 문서도 플랜
    문서도 쓰지 않고 짧은 합의만 채팅으로 받는다. 그 합의로 `contract-schema.md` 스키마대로
    `proposal-r<n>.json`을 쓴다 — `plan_path` 필드는 `null`.
  - **architectural**(구조 변경, 여러 파일에 걸친 작업): brainstorming이 스펙 문서를 대상 repo의
    `docs/superpowers/specs/`에 커밋 → 이어서 `superpowers:writing-plans`를 호출해 플랜 문서를
    대상 repo의 `docs/superpowers/plans/`에 커밋. `proposal-r<n>.json`의 `plan_path`에 이 플랜
    문서의 절대경로를 채운다.
  - bounded/architectural 모두 라운드 1은 위 절차로 초안부터, 2+는 직전 `verdict-r<n-1>.json`의
    반려 사유를 반영해 쓴다. override 단계도 동일 — 아래 라운드-한도 분기가 override 시점에
    도달했다고 판정하면, 그 사유(`verdict-r2.json`의 `reasons`)를 사람에게 그대로 보여주고 진행할지
    묻는다. 진행이면 `override.json` + 확정 `proposal-r<n+1>.json`을 이 자리에서 쓴다(architectural
    경로면 `plan_path`는 같은 파일을 계속 가리킨다 — writing-plans 산출물은 라운드마다 새 파일을
    만들지 않는다).
  - **라운드 재협상은 brainstorming을 처음부터 다시 돌리지 않는다** — evaluator의 반려 사유를
    반영해 `plan_path`가 가리키는 플랜 문서를 프루닝/보강하는 짧은 재협의만 하고 다음 라운드
    proposal을 다시 쓴다.
```

나머지 세 불릿("질문 전달 경로"부터 "afk는..."까지, 330-343행)은 **글자 그대로 유지** — 아래에서
그대로 다시 옮겨 적어 실수로 지워지지 않게 한다:

```markdown
- **질문 전달 경로**는 §0 "보고 채널"과 동일하다 — entry 세션(호출자 없음)이면 사람과 직접 대화하고,
  spawn된 세션(`orca-workflow-epic`이 스폰)이면 질문마다 `ask`(decision gate)로 올려 응답을
  기다린다(브레인스토밍 대화 전체에 걸쳐 반복 — `orca skills get orchestration` 확인 결과 `ask`는
  `--timeout-ms`를 받고, 타임아웃/연결 끊김이어도 질문 자체는 pending으로 남는다: 같은 질문을 다시
  묻지 말고 `ask --resume <message_id> --timeout-ms <n>`로 이어 기다린다 — 사람이 생각할 시간이
  필요한 대화형 질문이라 매 호출에 넉넉한 `--timeout-ms`를 주고, 타임아웃이면 이 resume으로
  반복한다. 이건 이 세션이 스스로 던진 질문을 기다리는 것이라 `self-recovery.md`의
  alive/stuck_draft/dead 대기 루프(이 세션이 스폰한 워커를 기다리는, 반대 방향의 절차)와는 다른
  경로다). epic 드레인 중 hitl 하위 task마다 이 대화가 순차로 사람을 기다리는 것은 의도된 동작이다
  — hitl은 애초에 "이 task의 contract-sprint에 개입하겠다"는 선택이지, epic 자신이 개입할 지점이
  아니다.
- 아래 라운드-한도/override 라우팅(파일 내용만으로 분기하는 기존 bash 블록)과 evaluator 디스패치는
  이 파일들을 누가 썼는지와 무관하게 그대로 실행한다 — 바뀌는 것은 이 파일들의 작성 주체뿐이다.
- afk는 아래 "라운드 1"·"라운드 2+"의 task-runner 디스패치 그대로(변경 없음).
```

- [ ] **Step 2: 수동 재확인**

편집된 §1 전체를 다시 읽어: (a) spike/bounded/architectural 세 갈래가 서로 배타적으로 서술됐는지,
(b) "질문 전달 경로"·"라운드-한도"·"afk" 세 불릿이 원문과 글자 그대로 같은지(diff로 확인),
(c) 아래 "라운드 1"·"라운드 2+" fenced bash 블록들이 이 변경으로 인해 문법적으로 깨지지 않았는지
(이 Step에서는 그 블록들을 건드리지 않으므로 깨질 이유가 없지만, 주변 마크다운 들여쓰기가
어긋나지 않았는지 확인).

- [ ] **Step 3: Commit**

```bash
git add skills/orca-workflow-task/SKILL.md
git commit -m "$(cat <<'EOF'
orca-workflow-task §1: hitl generator 역할이 brainstorming/writing-plans를 실제로 호출

지금까지는 brainstorming의 질문 스타일만 흉내내고 그 스킬의 종료 조건
(스펙 문서 작성, writing-plans 호출)은 명시적으로 건너뛰었다. 이제 그
스킬을 실제로 호출하고 자체 분류(spike/bounded/architectural)를 따른다 —
architectural만 writing-plans까지 이어가 plan_path를 만든다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `SPIKE_ANSWERED` outcome 값 등록

**Files:**
- Modify: `orca-workflows/scripts/log_dispatch.sh:69-84` (멤버십 노트 + `LOG_OUTCOME_ENUM`)
- Modify: `tests/test_log_outcome.py:36-59` (`DOCUMENTED_OUTCOME_ENUM`)
- Modify: `orca-workflows/logging.md:82-85`(진행-분기 축 목록), `:150-151`(설명 문단 삽입 위치)

**Interfaces:**
- Consumes: 없음.
- Produces: `log_outcome --outcome SPIKE_ANSWERED ...`가 유효한 호출이 된다(Task 2의 spike 분기가
  emit) — `UNMAPPED_BRANCH`로 강제 대체되지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성 — enum 크로스체크 목록 확장**

`tests/test_log_outcome.py`의 `DOCUMENTED_OUTCOME_ENUM`(현재 36-59행)에서, `NO_ACCEPTANCE_CRITERIA`
줄 바로 뒤(`"UNMAPPED_BRANCH"` 앞)에 삽입:

```python
    "NO_ACCEPTANCE_CRITERIA",  # issue #105
    "SPIKE_ANSWERED",  # 직접 이슈 없음, docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md
    "UNMAPPED_BRANCH",
```

- [ ] **Step 2: 테스트 실행해 실패 확인**

Run: `python3 -m pytest tests/test_log_outcome.py -k enum -v`
Expected: FAIL — `_extract_enum("LOG_OUTCOME_ENUM") == set(DOCUMENTED_OUTCOME_ENUM)`가 깨진다(스크립트
쪽 enum에는 아직 `SPIKE_ANSWERED`가 없음).

- [ ] **Step 3: `log_dispatch.sh`의 정본 enum에 값 추가**

`orca-workflows/scripts/log_dispatch.sh`에서 (현재 69-84행) 다음을:

```bash
# - EPIC_DONE / PR_OPEN_PREMERGE_PASS (observed in #105's recurrence comments) are deliberately
#   NOT added: neither has a decided semantics yet — they hit the UNMAPPED_BRANCH safeguard, which
#   is the designed path for values awaiting a schema decision.
LOG_OUTCOME_ENUM="PASS FAIL ESCALATE GATE_FAIL CONTRACT_ESCALATE CI_GATE_FAIL NO_DONE_TRANSITION CONTRACT_FINALIZED_BY_GENERATOR CONTRACT_APPROVED CONTRACT_SCHEMA_STALE MANUAL_RECOVERY_COMPLETED CI_GATE_TIMEOUT MERGE_CONFLICT RETRO_DONE RETRO_FAIL escalation_parked skipped unblocked_requeue NO_ACCEPTANCE_CRITERIA UNMAPPED_BRANCH"
```

다음으로:

```bash
# - EPIC_DONE / PR_OPEN_PREMERGE_PASS (observed in #105's recurrence comments) are deliberately
#   NOT added: neither has a decided semantics yet — they hit the UNMAPPED_BRANCH safeguard, which
#   is the designed path for values awaiting a schema decision.
# - SPIKE_ANSWERED: added per docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md
#   (직접 이슈 없음) — orca-workflow-task §1's hitl generator role classifies an issue as "spike"
#   (investigation, not code) and, once the human has decided the next action, ends without ever
#   reaching contract negotiation or §5's normal escalation branching. This is a normal termination,
#   not PASS/FAIL/ESCALATE, so it needs its own progress-branch value rather than being silently
#   unlogged.
LOG_OUTCOME_ENUM="PASS FAIL ESCALATE GATE_FAIL CONTRACT_ESCALATE CI_GATE_FAIL NO_DONE_TRANSITION CONTRACT_FINALIZED_BY_GENERATOR CONTRACT_APPROVED CONTRACT_SCHEMA_STALE SPIKE_ANSWERED MANUAL_RECOVERY_COMPLETED CI_GATE_TIMEOUT MERGE_CONFLICT RETRO_DONE RETRO_FAIL escalation_parked skipped unblocked_requeue NO_ACCEPTANCE_CRITERIA UNMAPPED_BRANCH"
```

- [ ] **Step 4: 테스트 실행해 통과 확인**

Run: `python3 -m pytest tests/test_log_outcome.py -v`
Expected: 전체 PASS(다른 테스트가 이전 enum 문자열을 하드코딩하지 않았는지도 함께 확인).

- [ ] **Step 5: `logging.md` 사람이 읽는 문서 갱신**

`orca-workflows/logging.md`에서 (현재 82-85행) 진행-분기 축 목록을:

```markdown
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED`|`CONTRACT_SCHEMA_STALE`|
  `MANUAL_RECOVERY_COMPLETED`|`CI_GATE_TIMEOUT`|`MERGE_CONFLICT`|`RETRO_DONE`|`RETRO_FAIL`|
  `escalation_parked`|`skipped`|`unblocked_requeue`|`NO_ACCEPTANCE_CRITERIA`|`UNMAPPED_BRANCH`
```

다음으로:

```markdown
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED`|`CONTRACT_SCHEMA_STALE`|
  `SPIKE_ANSWERED`|`MANUAL_RECOVERY_COMPLETED`|`CI_GATE_TIMEOUT`|`MERGE_CONFLICT`|`RETRO_DONE`|
  `RETRO_FAIL`|`escalation_parked`|`skipped`|`unblocked_requeue`|`NO_ACCEPTANCE_CRITERIA`|`UNMAPPED_BRANCH`
```

그리고 `CONTRACT_SCHEMA_STALE` 설명 문단이 끝나는 지점(현재 150행, "...남긴다."로 끝남) 뒤,
`MANUAL_RECOVERY_COMPLETED` 문단(152행) 앞에 새 문단을 삽입:

```markdown
`SPIKE_ANSWERED`는 `orca-workflow-task` §1의 hitl generator 역할이 이슈를 brainstorming으로
"spike"(코드 변경이 아니라 조사/답변이 산출물인 이슈)로 분류하고, 사람에게 다음 행동을 물어 결정을
받은 뒤 남기는 정상 종료다(직접 이슈 없음,
`docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md`) — 계약 협상
자체가 시작되지 않으므로 `round`는 없고, `detail`에 사람이 정한 다음 행동(이슈 재정의 요청/종료 등)을
사람이 읽을 수 있는 문장으로 남긴다. `orca-task-runner`/`orca-evaluate` 어느 쪽도 호출되지 않은
채 끝나는 유일한 정상 분기다.
```

- [ ] **Step 6: Commit**

```bash
git add orca-workflows/scripts/log_dispatch.sh tests/test_log_outcome.py orca-workflows/logging.md
git commit -m "$(cat <<'EOF'
logging: SPIKE_ANSWERED outcome 값 등록

orca-workflow-task §1의 hitl spike 분기(Task 2)가 코드 변경 없이
정상 종료할 때 남길 outcome을 UNMAPPED_BRANCH로 강제 대체되지 않는
합법적 값으로 등록한다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `orca-workflow-task` SKILL.md §1/§2 — `plan_path`를 구현 모드 dispatch에 실어 보낸다

**Files:**
- Modify: `skills/orca-workflow-task/SKILL.md:382` (§1 라운드1 task-runner spec_text — §2 fresh dispatch가 재사용)
- Modify: `skills/orca-workflow-task/SKILL.md:503` (§2 FAIL 재시도 spec_text)

**Interfaces:**
- Consumes: `proposal-r<n>.json`의 `plan_path`(Task 1의 스키마, Task 2가 씀).
- Produces: `orca-task-runner`가 받는 구현 모드 spec_text에 포함되는 `plan_path` 값 — Task 5의
  SDD 진입 분기가 이 값의 존재로 분기한다.

프로즈 템플릿 문자열 수정이라 자동 테스트는 없다(§1의 라운드-한도 bash 로직 자체는 이 Task에서
건드리지 않는다 — 그 로직은 무변경).

- [ ] **Step 1: §1 라운드1 task-runner spec_text에 `plan_path` 추가**

`skills/orca-workflow-task/SKILL.md`에서 (현재 382행) 다음을 교체:

```bash
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + CONTRACT_DIR 절대경로 + 제안서/구현 모드(제안서 모드면: contract-schema.md 스키마대로 AC 초안을 포함한 proposal-r<라운드>.json을 CONTRACT_DIR에 작성) + orphan-폴백 계약(§0) 전문 + heartbeat 억제 계약(§0) 전문>"
```

다음으로:

```bash
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + CONTRACT_DIR 절대경로 + 제안서/구현 모드(제안서 모드면: contract-schema.md 스키마대로 AC 초안을 포함한 proposal-r<라운드>.json을 CONTRACT_DIR에 작성; 구현 모드면: 최종 라운드 proposal-r<n>.json의 plan_path가 null이 아니면 그 절대경로를 \"plan_path: <값>\"으로 포함 — SDD 태스크 루프 진입 신호, orca-task-runner SKILL.md \"SDD 태스크 루프\" 절 참고) + orphan-폴백 계약(§0) 전문 + heartbeat 억제 계약(§0) 전문>"
```

- [ ] **Step 2: §2 FAIL 재시도 spec_text에도 동일하게 추가**

`skills/orca-workflow-task/SKILL.md`에서 (현재 503행) 다음을 교체:

```bash
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + CONTRACT_DIR 절대경로 + 구현 모드 + 직전 attempt 번호 + \"CONTRACT_DIR의 eval-report-a<attempt>.json과 최종 라운드 proposal(가장 큰 proposal-r<n>.json — 네가 직접 확인)을 이 순서로 전부 읽어라 — findings를 요약해 넘기지 않는다\" + orphan-폴백 계약(§0) 전문 + heartbeat 억제 계약(§0) 전문>"
```

다음으로:

```bash
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + CONTRACT_DIR 절대경로 + 구현 모드 + 직전 attempt 번호 + \"CONTRACT_DIR의 eval-report-a<attempt>.json과 최종 라운드 proposal(가장 큰 proposal-r<n>.json — 네가 직접 확인)을 이 순서로 전부 읽어라 — findings를 요약해 넘기지 않는다. 그 최종 proposal의 plan_path가 null이 아니면 그 절대경로를 이번에도 plan_path로 포함한다(재시도라고 SDD 태스크 루프 진입 여부가 바뀌지 않는다)\" + orphan-폴백 계약(§0) 전문 + heartbeat 억제 계약(§0) 전문>"
```

- [ ] **Step 3: 수동 재확인**

두 spec_text 문자열 안의 이중 인용 escape(`\"...\"`)가 원본과 같은 규칙으로 닫혔는지 확인한다 —
두 템플릿 모두 이미 내부에 escape된 인용구를 포함하고 있었으므로, 새로 추가한 문구도 같은
escape 규칙을 따라야 한다.

- [ ] **Step 4: Commit**

```bash
git add skills/orca-workflow-task/SKILL.md
git commit -m "$(cat <<'EOF'
orca-workflow-task §1/§2: 구현 모드 dispatch에 plan_path 전달

architectural 분류로 만들어진 plan_path(Task 2)가 orca-task-runner의
구현 모드 dispatch까지 전달되도록 두 spec_text 템플릿(라운드1 재사용분,
§4 FAIL 재시도분)에 추가한다.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `orca-task-runner` SKILL.md — SDD 태스크 루프 신설 + 진입 분기 + 리뷰어 예외 문구

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md:3`(frontmatter description), `:9`(서두 리뷰어 문장),
  `:113-125`(§1 필드 목록 — `plan_path: null` 지시 추가), 새 섹션 삽입 위치(§1 끝, 현재 134행 뒤 /
  §2 시작, 현재 136행 앞), `:199`(§4 리뷰어 문장)
- Test: `tests/test_sdd_loop_entry_branch.py`(신설)

**Interfaces:**
- Consumes: `plan_path`(spec으로 받음, Task 4가 전달) — non-null이면 SDD 태스크 루프, null/부재면
  기존 §2~§5.
- Produces: 이 스킬 자신의 §1(afk 전용 proposal 작성)이 쓰는 `plan_path: null` — Task 1의 스키마가
  요구하는 필수 필드를 afk 쪽에서도 채운다. 그 외에는 다른 태스크가 이 출력에 의존하지 않는다.

- [ ] **Step 1: §1의 proposal 필드 목록에 `plan_path: null` 지시 추가**

`skills/orca-task-runner/SKILL.md`에서 (현재 122-125행) 다음을:

```markdown
- 이 변경으로 red가 되거나 갱신이 필요한 기존 테스트·단언(`existing_tests_affected`, file:line) —
  빈 배열이 "명시적 없음"이다. `verification_plan`은 새로 추가할 검증만 담는다 — 기존에 green이던
  단언 중 이 변경으로 red가 될 것은 여기 별도로 열거한다(정확 일치 단언, 게이트 자체를 막는 회귀를
  특히 놓치기 쉽다).
```

다음으로:

```markdown
- 이 변경으로 red가 되거나 갱신이 필요한 기존 테스트·단언(`existing_tests_affected`, file:line) —
  빈 배열이 "명시적 없음"이다. `verification_plan`은 새로 추가할 검증만 담는다 — 기존에 green이던
  단언 중 이 변경으로 red가 될 것은 여기 별도로 열거한다(정확 일치 단언, 게이트 자체를 막는 회귀를
  특히 놓치기 쉽다).
- `plan_path` — 항상 `null`이다. 이 §1(generator 역할)은 afk 전용이고(hitl에서는
  `orca-workflow-task`가 이 필드를 직접 쓴다 — 그 스킬 SKILL.md §1 "mode=hitl일 때 generator
  역할" 절 참고), afk 경로는 `superpowers:brainstorming`/`superpowers:writing-plans`를 거치지
  않으므로 플랜 문서 자체가 존재하지 않는다.
```

- [ ] **Step 2: 수동 재확인**

편집된 §1 필드 목록을 다시 읽어 다른 필드들과 같은 스타일(불릿, 필드명 백틱 표기)로 쓰였는지
확인한다.

- [ ] **Step 3: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "$(cat <<'EOF'
orca-task-runner §1: plan_path를 항상 null로 채운다 (afk 전용 경로)

Task 1이 contract-schema.md에서 plan_path를 필수 필드로 만들었으므로,
이 §1(afk 전용 proposal 작성)도 이 필드를 명시적으로 채워야 스키마를
지킨다 — afk는 brainstorming/writing-plans를 거치지 않으므로 항상 null.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: 실패하는 테스트 작성 — 진입 분기 bash 고정**

`tests/test_sdd_loop_entry_branch.py`를 새로 작성한다(기존 `tests/test_generate_audit_gate.py`와
같은 추출-후-서브프로세스-실행 패턴):

```python
"""Functional tests for orca-task-runner's SDD-loop entry branch (plan_path presence).

The branch is a documented bash procedure, so per this repo's execution-suite policy it is
extracted from SKILL.md verbatim (placeholder substituted) and run as a subprocess, parametrized
across bash and zsh. A non-empty plan_path must select the SDD loop; empty/absent must select the
existing native DAG/wave path (§2-§5, unchanged).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "orca-task-runner" / "SKILL.md"
SHELLS = ["bash", "zsh"]


def _entry_branch_block() -> str:
    text = SKILL.read_text()
    section = text[text.index("SDD 태스크 루프"):]
    m = re.search(r"```bash\n(.*?)```", section, re.DOTALL)
    assert m, "SDD 태스크 루프 진입 분기 fenced bash block missing from SKILL.md"
    return m.group(1)


def _substituted(plan_path: str) -> str:
    block = _entry_branch_block()
    block = block.replace("<spec으로 받은 plan_path — 없으면 빈 문자열>", plan_path)
    assert "<" not in block, f"unsubstituted placeholder left: {block}"
    return block


def _run(script: str, shell: str):
    if shutil.which(shell) is None:
        pytest.skip(f"{shell} not on PATH")
    return subprocess.run(
        [shell, "-c", script], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )


@pytest.mark.parametrize("shell", SHELLS)
def test_nonempty_plan_path_selects_sdd_loop(shell):
    result = _run(_substituted("/tmp/plans/2026-08-22-foo.md"), shell)
    assert result.stdout.strip() == "SDD_LOOP"


@pytest.mark.parametrize("shell", SHELLS)
def test_empty_plan_path_selects_native_dag(shell):
    result = _run(_substituted(""), shell)
    assert result.stdout.strip() == "NATIVE_DAG"
```

- [ ] **Step 5: 테스트 실행해 실패 확인**

Run: `python3 -m pytest tests/test_sdd_loop_entry_branch.py -v`
Expected: 두 테스트 모두 ERROR — `SKILL.md`에 아직 "SDD 태스크 루프" 앵커 텍스트가 없으므로
`_entry_branch_block()` 내부의 `text.index(...)`가 `ValueError`(부분 문자열 없음)를 던진다.

- [ ] **Step 6: frontmatter description에 예외 문구 추가**

`skills/orca-task-runner/SKILL.md`에서 (현재 3행) 다음 문장을:

```
Subtask gates are mechanical only (typecheck/unit test/lint/format) — never an agent reviewer; task-level review belongs to orca-evaluate.
```

다음으로 교체(같은 문장에 짧은 예외 절 추가, 뒤 문장들은 그대로):

```
Subtask gates are mechanical only (typecheck/unit test/lint/format) — never an agent reviewer; task-level review belongs to orca-evaluate. Exception: the hitl-only SDD task loop (plan_path present) uses a per-task LLM reviewer instead.
```

(이 편집 후 `python3 -c "import re; text=open('skills/orca-task-runner/SKILL.md').read(); m=re.search(r'description: (.*)', text); print(len(m.group(1)))"`로 1024자 캡을 넘지 않는지 확인 — 현재
629자 + 약 100자 추가로 여유 있음.)

- [ ] **Step 7: 서두 리뷰어 문장에 예외 추가**

`skills/orca-task-runner/SKILL.md`에서 (현재 9행) 다음을:

```markdown
하나의 task(issue)를 구현한다. **생성만** 한다 — 평가는 이 스킬의 책임이 아니다(`orca-evaluate`가 담당). subtask 단위 리뷰어 역할은 두지 않는다.
```

다음으로:

```markdown
하나의 task(issue)를 구현한다. **생성만** 한다 — 평가는 이 스킬의 책임이 아니다(`orca-evaluate`가 담당). subtask 단위 리뷰어 역할은 두지 않는다(단, `plan_path`가 있는 SDD 태스크 루프 경로는 예외 — 아래 "SDD 태스크 루프" 절 참고, hitl 전용).
```

- [ ] **Step 8: §1과 §2 사이에 "SDD 태스크 루프" 섹션 신설**

`skills/orca-task-runner/SKILL.md`에서, 현재 §1의 끝(134행, "verdict-r2.json을 읽고 proposal-r3.json을 작성한다(override.json 작성 없음)... 위 override 절차와 동일하되 라운드 번호만 한 칸씩 밀림)."로 끝나는 문단) 뒤, `## 2. Subtask DAG 구성` 헤딩(136행) 앞에 다음 섹션을 삽입한다:

```markdown
## SDD 태스크 루프 (`plan_path` 있는 경우 — §2~§5 대체, hitl 전용)

스폰 spec에 `plan_path`(절대경로)가 있으면 이 절차로 진입한다 — 아래 §2 "Subtask DAG 구성"부터
§5 "Wave 루프"까지는 타지 않는다. 이 절차를 마치면 곧장 §6 "Task 레벨 게이트"로 합류한다(§6·§7은
무변경). `plan_path`가 없거나 null이면(afk 전체, hitl의 bounded/spike) 이 절을 건너뛰고 §2로
진행한다:

```bash
if [ -n "<spec으로 받은 plan_path — 없으면 빈 문자열>" ]; then
  echo "SDD_LOOP"
else
  echo "NATIVE_DAG"
fi
```

**중요한 구현 판단**: 이 절은 `superpowers:subagent-driven-development` 스킬을 호출하지 않는다.
그 스킬의 서브에이전트 dispatch는 Claude Code Agent tool 전용인데, 이 스킬 자신은 "self-relative
— 어느 provider가 이 세션을 돌리든 동일하게 동작한다"는 전제를 갖고 있다(SKILL.md 서두). Agent
tool이 없는 세션(이 세션 자신이 Codex나 agy로 돌 수 있음)에서 그 스킬을 부르는 경로는 성립하지
않는다. 대신 그 스킬의 **패턴**(태스크브리프 → implementer → 태스크별 리뷰어 → fix-loop, 진행
원장)을 아래처럼 이 스킬 자신의 절차로 포팅하고, provider fan-out은 §0/§3/§5의 기존 스폰
메커니즘을 그대로 재사용한다.

1. `plan_path` 문서를 읽어 태스크 목록을 추출한다(writing-plans의 Files/Interfaces/Step 1-5 형식).
   이 스킬이 별도로 DAG를 재구성하지 않는다.
2. 태스크를 **순차로**(SDD 기본값 그대로) 실행한다 — §2의 파일-겹침 기반 wave 병렬화는 이 경로에
   적용하지 않는다(플랜이 그 분석을 염두에 두고 만들어지지 않았고, SDD 자신도 순차 실행이
   기본값이다).
3. 태스크마다 `~/.agents/orca-workflows/model-selection.md` 휴리스틱으로 provider(claude/codex/
   agy)·model·effort를 고른다 — §0/§3/§5가 이미 쓰는 것과 동일한 정책, 새 휴리스틱을 만들지 않는다.
4. 선택된 provider로 implementer를 dispatch한다 — §0/§3/§5의 기존 스폰 메커니즘 그대로(claude:
   `worker-start --agent`, codex/agy: `terminal create` 선-생성 + `worker-start --terminal`).
5. 태스크 완료(`worker_done`) 후, 같은 model-selection.md 휴리스틱으로 고른 태스크별 리뷰어(스펙+
   품질 검토)를 **implementer와는 별도의 워커로** 스폰한다 — self-review 편향을 막기 위해 같은
   워커가 자기 결과를 검토하는 경로는 두지 않는다. 반려되면 fix-loop(최대 5라운드: 1-3라운드는
   같은 implementer 재개, 4-5라운드는 model-selection.md의 다음 상위 tier로 fresh implementer)를
   태운다. 5라운드를 다 써도 그린이 안 되면 이 태스크에서 멈추고 §6에 진입하지 않은 채 곧장
   `GATE_FAIL`을 `orca-workflow-task`에 반환한다(§6의 "2회 재시도 후 GATE_FAIL" 원칙과 같은 결).
6. 모든 태스크가 끝나면 **SDD의 final whole-branch review는 생략**하고 곧장 §6으로 넘어간다 —
   `orca-evaluate`가 같은 issue에서 이미 diff 전체 code-review를 하므로 중복이다.
7. 진행 원장(progress ledger)은 SDD 기본 위치(`<repo-root>/.superpowers/sdd/`)가 아니라
   `CONTRACT_DIR` 아래에 둔다 — 이 파이프라인의 crash-resume이 이미 `CONTRACT_DIR` 아티팩트 스캔이
   정본이고, target repo마다 gitignore 항목을 추가할 필요가 없다. 태스크별 assign/outcome 로그는
   `logging.md`의 기존 레시피를 재사용한다(`role="sdd-implementer"`/`"sdd-reviewer"`).

(상세 설계 근거: `docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md`)
```

- [ ] **Step 9: §4 리뷰어 문장에 예외 추가**

`skills/orca-task-runner/SKILL.md`에서 (현재 199행) 다음을:

```markdown
subtask가 worker_done을 보내기 전에 스스로 실행: typecheck, unit test, formatter, linter, 무거운 환경 구성이 필요 없는 script test. **subtask 단위 agent 리뷰어는 없다.** 게이트를 통과하지 못하면 worker_done을 보내지 않고 스스로 고친다.
```

다음으로:

```markdown
subtask가 worker_done을 보내기 전에 스스로 실행: typecheck, unit test, formatter, linter, 무거운 환경 구성이 필요 없는 script test. **subtask 단위 agent 리뷰어는 없다.** 게이트를 통과하지 못하면 worker_done을 보내지 않고 스스로 고친다. (이 §4는 §2~§5 native 경로에만 적용된다 — `plan_path`가 있는 SDD 태스크 루프 경로는 태스크별 LLM 리뷰어를 예외적으로 둔다, hitl 전용. 위 "SDD 태스크 루프" 절 참고.)
```

- [ ] **Step 10: 테스트 실행해 통과 확인**

Run: `python3 -m pytest tests/test_sdd_loop_entry_branch.py -v`
Expected: 두 테스트 모두 PASS.

- [ ] **Step 11: Commit**

```bash
git add skills/orca-task-runner/SKILL.md tests/test_sdd_loop_entry_branch.py
git commit -m "$(cat <<'EOF'
orca-task-runner: plan_path 있으면 SDD 태스크 루프로 진입 (hitl 전용)

writing-plans가 만든 플랜을 순차 실행하고 태스크별 LLM 리뷰어+fix-loop를
두는 새 경로를 §2~§5 native DAG/wave 앞에 추가한다. provider fan-out은
기존 §0/§3/§5 스폰 메커니즘(claude/codex/agy)을 그대로 재사용하고,
superpowers:subagent-driven-development 스킬 자체는 호출하지 않는다
(Claude Agent tool 전용이라 self-relative 전제와 안 맞음 — 패턴만 포팅).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 전체 스위트 재확인, 버전 bump, 배포

**Files:**
- Modify: `skills/orca-set.version`

**Interfaces:**
- Consumes: Task 1-5의 모든 커밋.
- Produces: `~/.agents/skills/`에 배포된 새 버전(orca-set 전체).

- [ ] **Step 1: 전체 테스트 스위트 실행**

Run: `python3 -m pytest tests/ -q`
Expected: 전부 PASS (Task 3의 `test_log_outcome.py` 갱신, Task 5의 신설
`test_sdd_loop_entry_branch.py` 포함, 기존 테스트에 회귀 없음 — 특히
`test_skill_description_length.py`, `test_round_limit_branch_order.py`, `test_generate_audit_gate.py`
가 이번 변경으로 건드린 파일들을 커버하므로 확인).

- [ ] **Step 2: 작업 트리 클린 확인**

Run: `git status --short`
Expected: 출력 없음(Task 1-5가 이미 커밋됨). `deploy-skills.sh`는 dirty skill을 거부한다.

- [ ] **Step 3: 버전 bump**

`skills/orca-set.version`에서 첫 줄을 `v1.1.31`에서 `v1.1.32`로 변경(멤버 목록은 무변경 — 이
플랜은 세트 멤버를 추가/제거하지 않는다).

- [ ] **Step 4: 버전 bump 커밋**

```bash
git add skills/orca-set.version
git commit -m "$(cat <<'EOF'
orca-set v1.1.32 — hitl 경로 superpowers 도입 (brainstorming/writing-plans/SDD)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: 배포**

Run: `scripts/deploy-skills.sh` (인자 없음 — orca-set 전체 배포. `orca-workflow-task`/
`orca-task-runner` 둘 다 멤버이므로 같은 버전 라벨로 함께 나가야 한다)

Expected: 새 커밋-고정 복사본이 `~/.agents/skills/`에 `v1.1.32`로 설치됐다는 보고. `orca-workflows/`
(contract-schema.md 포함)는 별도 배포 단계가 필요 없다 — main 체크아웃에 심링크된 상태라 이
브랜치가 main에 머지되는 즉시 반영된다(AGENTS.md "`orca-workflows/` 배포 경로" 절).

이 스텝은 사용자의 실제 `~/.agents/skills/`에 영향을 주는 전역 효과다(이 파이프라인이 도는 모든
저장소가 그 배포본을 쓴다) — 이 플랜을 비대화식으로 실행한다면 실행 전 사용자에게 확인한다.

---

## Self-Review Notes

**Spec coverage:** 설계 문서의 "설계 1"(트리거 분기, spike의 `SPIKE_ANSWERED` 포함) → Task 2 +
Task 3. "설계 2"(§2 plan_path 전달) → Task 4. "설계 3"(contract-schema.md) → Task 1. "설계
4"(SDD 루프, `orca-task-runner` §1의 `plan_path: null` 포함) → Task 5. "설계 5"(§5 무변경, 합류
지점 명시) → Task 5의 SDD 루프 절 5번 항목이 그 합류를 서술(§5 자체는 코드 변경 없음, 별도 Task
불필요). "마이그레이션/롤아웃" → Task 6. 설계 문서의 "범위 밖" 항목(afk의 §2~§7 로직,
orca-evaluate 내부, subagent-driven-development 스킬 파일 자체, orca-workflow/orca-workflow-epic)
모두 이 플랜에서 건드리지 않는다. advisor 리뷰에서 발견된 두 gap(plan_path 신호의 전제, spike
outcome 로깅 부재)은 스펙 문서를 먼저 정정한 뒤 Task 3과 Task 5 Step 1로 반영했다.

**Placeholder scan:** 각 Step이 실제 교체 전/후 텍스트를 통째로 담고 있다 — "TBD"·"구현하라" 류
표현 없음. Task 3 Step 1과 Task 5 Step 4의 테스트는 각각 `tests/test_log_outcome.py`(기존 패턴
확장)와 `tests/test_generate_audit_gate.py`(구조 재사용)의 실제 코드를 그대로 뗀 완성된 코드다.

**Type/name consistency:** `plan_path`(필드명), `SPIKE_ANSWERED`(outcome 값), `SDD_LOOP`/
`NATIVE_DAG`(테스트가 assert하는 stdout 문자열), `role="sdd-implementer"`/`"sdd-reviewer"`(로그
role 값)가 Task 1·2·3·4·5 전체에서 동일하게 쓰인다.
`docs/superpowers/specs/2026-08-22-orca-workflow-task-hitl-superpowers-design.md` 경로 문자열도
Task 1·2·3에서 동일하다.
