# orca-workflow-task: hitl 경로에 superpowers(brainstorming/writing-plans/SDD) 전면 도입

이슈: 직접 이슈 없음(사용자 요청으로 세션 내 브레인스토밍, 2026-08-22).

## 문제

`orca-workflow-task/SKILL.md` §1 "mode=hitl일 때 generator 역할" 절(issue #180)은 지금 다음처럼
동작한다: hitl에서는 `orca-task-runner`를 "제안서 작성" 모드로 스폰하지 않고, 코디네이터 세션 자신이
사람과 직접 협의해 `proposal-r<n>.json`을 쓴다. 대화 방식은 "`superpowers:brainstorming`의 질문법(한
번에 한 질문, 2-3안 제시 후 추천, 섹션별 승인)을 따르되, **그 스킬 자신의 종료 조건은 따르지 않는다**
— spec 문서 작성·커밋 스텝, `writing-plans` 호출 스텝 둘 다 존재하지 않는다"고 명시돼 있다.

즉 지금은 brainstorming의 질문 스타일만 흉내내고, 그 결과물(스펙 문서, 이어지는 플랜 문서)은 전혀
만들지 않는다. 사람이 어차피 hitl로 개입해 매 라운드를 리뷰하는 경로이므로, 이 흉내내기 대신
`superpowers:brainstorming`/`superpowers:writing-plans`를 실제로 호출해 산출물(스펙·플랜 문서)을
만들고, 그 플랜을 태스크 구현 단계에서도 `superpowers:subagent-driven-development`(이하 SDD)의
패턴(태스크별 implementer + 태스크별 리뷰어 + fix-loop)으로 실행하고 싶다 — 단 SDD 원본은 Claude
Agent tool 전용이라, `orca-task-runner`가 이미 갖고 있는 codex/agy fan-out까지 포함하도록 확장해야
한다.

## 범위

**수정 대상**:
- `skills/orca-workflow-task/SKILL.md` §1(hitl generator 역할), §2(Generate dispatch spec_text)
- `skills/orca-task-runner/SKILL.md`(§1의 proposal 작성 필드 목록에 `plan_path: null` 지시 추가,
  §2 앞에 새 분기 추가, §4/서두의 "리뷰어 없음" 문장에 예외 추가)
- `orca-workflows/contract-schema.md`(`proposal-r<n>.json`에 필수(nullable) `plan_path` 필드 추가)
- `orca-workflows/scripts/log_dispatch.sh`/`orca-workflows/logging.md`/`tests/test_log_outcome.py`
  (신규 outcome `SPIKE_ANSWERED` 등록 — 아래 "설계 1"의 spike 분기가 쓴다)

**범위 밖**:
- `mode=afk` — 전혀 건드리지 않는다. afk에는 사람이 없어 brainstorming의 승인 게이트 자체가 성립하지
  않는다.
- `orca-evaluate`의 내부 로직 — 스폰 방식·판정 기준 전부 무변경. "code-gen ↔ evaluator" 관계(§1
  계약 협상 라운드 한도, §2 감사 게이트, §3 evaluate 호출)는 사용자가 명시적으로 유지를 요청했다.
- `superpowers:subagent-driven-development` 스킬 파일 자체의 수정 — 아래 "설계 4"에서 설명하듯, 이
  변경은 그 스킬을 호출하는 게 아니라 그 **패턴**을 `orca-task-runner`에 포팅하는 것이다.
- `orca-workflow`/`orca-workflow-epic` — mode를 그대로 전달만 하므로 무변경.

## 설계

### 1. 트리거 분기 — brainstorming의 자체 분류를 존중한다

`orca-workflow-task` §1의 "mode=hitl일 때 generator 역할" 절을 다음으로 교체한다. 코디네이터가
이슈 본문을 입력으로 `superpowers:brainstorming`을 실제로 호출하고, 그 스킬 자신의 분류
(spike/bounded/architectural)를 그대로 따른다:

- **spike**(드묾 — "이게 가능한가"류 이슈): 코드 변경이 산출물이 아니므로 §1~§2 전체를 건너뛴다.
  조사 결과를 이슈에 코멘트로 남기고 사람에게 다음 행동(이슈 재정의/종료)을 물은 뒤, 새 outcome
  `SPIKE_ANSWERED`를 `log_dispatch`로 남기고 보고 채널로 종료를 알린다 — §5의 일반 "그 외
  outcome"(hitl/afk 재분기, 계속/중단 선택지 등)은 타지 않는다: 사람의 결정은 이미 이 자리에서
  끝났다. §0이 만든 worktree/Run/CONTRACT_DIR는 다른 outcome들과 동일하게 보존한다(§5 afk 보존
  절차와 같은 원칙 — 별도 정리 로직을 새로 만들지 않는다). `orca-task-runner`/`orca-evaluate` 모두
  호출되지 않는다.
- **bounded**(이미 있는 흐름의 작은 범위 수정): brainstorming이 규정한 대로 스펙 문서도 플랜 문서도
  안 쓰고 짧은 합의만 채팅으로 받는다. 이 합의 내용으로 `proposal-r<n>.json`을 쓴다(`plan_path`
  필드 없음). 이후 라운드-한도/override 로직과 evaluator 디스패치는 지금 그대로다. §2에서
  `orca-task-runner`를 구현 모드로 dispatch하면, `plan_path`가 없으므로 지금의 native DAG/wave
  경로(§2~§5, 무변경)를 그대로 탄다.
- **architectural**(구조 변경, 여러 파일에 걸친 작업): brainstorming이 스펙 문서를 대상 repo의
  `docs/superpowers/specs/`에 커밋 → 이어서 `superpowers:writing-plans`를 호출해 플랜 문서를 대상
  repo의 `docs/superpowers/plans/`에 커밋. 이 플랜 문서의 절대경로를 `proposal-r<n>.json`의 새 필드
  `plan_path`에 실어 작성한다.

라운드 재협상(evaluator가 반려한 경우)은 brainstorming을 처음부터 다시 돌리지 않는다 — `verdict-
r<n>.json`의 반려 사유를 반영해 `plan_path`가 가리키는 플랜 문서를 프루닝/보강하는 짧은 재협의만
하고, 그 결과로 다음 라운드 `proposal-r<n+1>.json`을 다시 쓴다(plan_path는 같은 파일을 계속
가리킨다 — writing-plans의 산출물은 `proposal-r<n>.json`처럼 라운드마다 새 파일을 만드는 관례가
아니라 살아있는 문서 하나를 그대로 다듬는 문서다).

질문 전달 경로(entry 세션이면 사람과 직접, spawn된 세션이면 `ask`)는 §0 "보고 채널"을 그대로
따른다 — 지금 절의 서술과 동일.

### 2. `orca-workflow-task` §2 — `plan_path`를 구현 모드 dispatch에 실어 보낸다

§2 "Generate"의 구현 모드 spec_text 구성에 `plan_path`(최종 라운드 `proposal-r<n>.json`에서 추출한
구조 필드 하나)를 추가한다. 이 스킬이 "diff/report 본문을 직접 읽지 않는다"는 원칙과 충돌하지
않는다 — §1이 라운드-한도 분기에서 이미 `reasons[].target` 같은 구조 필드 1개를 추출해 분기하는
것과 정확히 같은 성격이다. 추출한 값이 `null`이면(bounded 분류 또는 afk) spec_text에 `plan_path`를
싣지 않는다 — 이 필드는 `proposal-r<n>.json` 안에서는 항상 존재하지만(스키마 필수), 그걸 다음
단계로 전달하는 spec_text는 이 파이프라인의 기존 관례대로 값이 있을 때만 문구를 추가한다.

### 3. `contract-schema.md` — `proposal-r<n>.json`에 `plan_path` 필드 추가

스키마의 "모든 필드 필수 — 필드가 아예 없으면 스키마 위반, '언급 안 함' 상태는 존재할 수 없다"
원칙(`destructive_operations`/`existing_tests_affected`가 이미 이 원칙을 빈 배열 `[]`로 지키고
있다)을 그대로 따른다. `plan_path`는 **필수 필드**로 추가하고, architectural 분류가 아니면(afk
전체, hitl의 bounded/spike) 값을 `null`로 채운다 — 필드를 생략하지 않는다. architectural
분류에서만 실제 절대경로 문자열을 채운다.

### 4. `orca-task-runner` — SDD 루프를 §2 앞에 새 분기로 추가한다

**중요한 구현 판단(기술적 결정, 근거 명시)**: 이 변경은 `superpowers:subagent-driven-development`
스킬 파일을 **호출하지 않는다**. 그 스킬의 서브에이전트 dispatch는 Claude Code의 Agent tool
전용으로 설계돼 있는데, `orca-task-runner`는 "self-relative — 어느 provider가 이 세션을 돌리든
동일하게 동작한다"는 전제(SKILL.md 서두)를 갖고 있다. 이 세션 자신이 Codex나 agy로 돌 수도 있는
이상, Agent tool이 없는 세션에서 그 스킬을 부르는 경로는 구조적으로 성립하지 않는다. 대신 SDD의
**패턴**(태스크브리프 → implementer → 태스크별 리뷰어 → fix-loop, 진행 원장)을 `orca-task-runner`
자신의 절차로 포팅하고, provider fan-out은 이미 갖고 있는 메커니즘(claude: `worker-start --agent`,
codex/agy: `terminal create` 선-생성 + `worker-start --terminal`, §0/§3/§5)을 그대로 재사용한다.

`orca-task-runner`의 §2 "Subtask DAG 구성" 진입 직전에 분기를 추가한다: spec에 `plan_path`가 있으면
아래 SDD 루프로, 없으면 지금의 §2~§5(DAG/wave)로 — 이 새 루프를 마치면 지금의 §6(Task 레벨
게이트)·§7(완료)로 그대로 합류한다(무변경).

**SDD 루프 절차**:

1. `plan_path` 문서를 읽어 태스크 목록을 추출한다(writing-plans의 Files/Interfaces/Step 1-5 형식).
   `orca-task-runner`가 별도로 DAG를 재구성하지 않는다 — writing-plans가 이미 파일 단위로 쪼개놓은
   구조를 그대로 실행 단위로 쓴다.
2. **순차 실행**(SDD 기본값 그대로) — 태스크를 하나씩, 앞 태스크가 끝난 뒤 다음 태스크를 시작한다.
   `orca-task-runner` 기존 §2의 파일-겹침 기반 wave 병렬화는 이 경로에 적용하지 않는다(플랜이 그
   분석을 염두에 두고 만들어지지 않았고, SDD 자신도 순차 실행이 기본값이다).
3. 태스크마다 `~/.agents/orca-workflows/model-selection.md` 휴리스틱으로 provider(claude/codex/agy)·
   model·effort를 고른다 — 새 휴리스틱을 만들지 않고, 기존 native fan-out이 쓰는 것과 동일한 정책을
   재사용한다.
4. 선택된 provider로 implementer를 dispatch한다 — §0/§3/§5의 기존 스폰 메커니즘 그대로(claude:
   `worker-start --agent`, codex/agy: `terminal create` 선-생성 + `worker-start --terminal`).
5. 태스크 완료(`worker_done`) 후 같은 model-selection.md 휴리스틱으로 고른 태스크별 리뷰어(스펙+
   품질 검토)를 **implementer와는 별도의 워커로** 스폰한다 — self-review 편향을 막기 위해 같은
   워커가 자기 결과를 검토하는 경로는 두지 않는다. 반려되면 SDD의
   fix-loop(최대 5라운드: 1-3라운드는 같은 implementer 재개, 4-5라운드는 model-selection.md의 다음
   상위 tier로 fresh implementer)를 태운다. 5라운드를 다 써도 그린이 안 되면 이 태스크에서 멈추고
   §6에 진입하지 않은 채 곧장 `GATE_FAIL`을 `orca-workflow-task`에 반환한다(§6의 "2회 재시도 후
   GATE_FAIL" 원칙과 같은 결 — 기계적으로도 안 되는 걸 비싼 단계에 태우지 않는다).
6. **SDD의 final whole-branch review 단계는 생략한다** — 모든 태스크가 끝나면 `finishing-a-
   development-branch` 호출 없이 곧장 §6(Task 레벨 게이트)로 넘어간다. `orca-evaluate`가 같은
   issue에서 이미 diff 전체 code-review를 수행하므로 중복이다.
7. **진행 원장(progress ledger)의 위치** — SDD 기본값(`<repo-root>/.superpowers/sdd/<plan-basename>/
   progress.md`, git-ignored)을 쓰지 않고, `CONTRACT_DIR` 아래에 둔다. 근거: 이 파이프라인의
   crash-resume은 이미 `CONTRACT_DIR` 아티팩트 스캔이 정본이고(§0 재개 분기), target repo마다
   gitignore 항목을 추가로 관리하게 만들 이유가 없다. 원장 갱신은 `logging.md`의 기존 assign/outcome
   레시피를 재사용한다(`role="sdd-implementer"`/`"sdd-reviewer"`) — 새 로그 포맷을 만들지 않는다.

**리뷰어 예외 문구 추가** — SKILL.md 서두("subtask 단위 리뷰어 역할은 두지 않는다")와 §4("subtask
단위 agent 리뷰어는 없다") 두 자리에 각각: "단, `plan_path`가 있는 SDD 루프 경로에서는 태스크별 LLM
리뷰어가 예외적으로 허용된다(hitl 전용 — 사람이 최종적으로 리뷰하므로) — 지금의 native DAG/wave
경로(§2~§5)는 이 예외와 무관하게 리뷰어 없음 그대로다."

### 5. `orca-workflow-task` §5(에스컬레이션) — 무변경, 합류 지점만 명시

SDD 루프 내부에서 실패해도 `orca-task-runner`가 반환하는 값(`GATE_FAIL` 또는 diff 경로)은 지금의
enum을 그대로 타므로, §4 라우팅·§5 에스컬레이션 로직 자체는 수정하지 않는다. 이 사실만 스펙에
명시해 "SDD 루프가 새 에스컬레이션 경로를 만든다"는 오해를 막는다.

## 검토했으나 기각한 대안

1. **`orca-task-runner`가 `mode` 플래그를 직접 받아 분기** — `plan_path` 존재 여부 대신 명시적
   `mode=hitl` 인자로 분기하는 안. 기각: `plan_path`는 afk 경로에서 절대 채워지지 않으므로(afk는
   brainstorming/writing-plans를 호출하지 않음) 이미 충분한 신호다. `orca-task-runner`에 `mode`
   개념을 새로 알리면 이 스킬의 self-relative 원칙(어느 provider가 돌든 같은 입력에 같은 동작)에
   불필요한 결합을 추가한다. **주의(advisor 리뷰에서 발견)**: 이 신호가 실제로 충분하려면
   `orca-task-runner` §1(proposal 작성, afk 전용 호출 경로)이 자기가 쓰는 `proposal-r<n>.json`에
   `plan_path`를 항상 `null`로 채워야 한다 — 스키마가 이 필드를 필수로 만들었으므로(설계 3),
   §1이 이 필드를 언급하지 않으면 afk 제안서가 스키마 위반이 되거나, §1이 스스로 무언가를 채워
   넣어 의도치 않게 SDD 루프로 오분류될 위험이 있다. §1의 필드 목록에 "plan_path — 항상 null,
   이 §1은 afk 전용이라 플랜 문서가 존재하지 않는다"를 명시적으로 추가한다(수정 대상에 반영).
2. **orca-retro가 `SPIKE_ANSWERED`를 예방 가능한 escalate로 오인할 가능성** — 검토 결과 기각(=
   carve-out 불필요): `orca-retro` lens 3은 문자열이 정확히 `ESCALATE` 또는 `*_HUMAN_DECISION`
   suffix인 outcome만 대상으로 하고(`skills/orca-retro/SKILL.md` §해당 lens), `SPIKE_ANSWERED`는
   둘 다 아니다 — 이미 사람이 결정을 마친 정상 종료이므로 애초에 그 lens의 대상 패턴에 안 걸린다.
3. **`plan_path` 태스크에도 파일-겹침 기반 wave 병렬화 적용** — 브레인스토밍 중 논의했으나, 플랜이
   그 분석을 염두에 두고 쪼개진 게 아니라 오판정(태스크가 실은 파일을 공유하는데 독립으로 오분류)
   위험이 병렬화 이득보다 크다고 판단해 기각. 순차 실행으로 시작하고, 실제로 비용이 문제가 되면
   별도로 재검토한다.
4. **SDD의 final whole-branch review 유지** — `orca-evaluate`의 diff 전체 code-review와 중복이라
   기각(섹션 3에서 이미 사용자와 합의).

## 에러 처리

- **brainstorming 오분류(bounded인데 architectural감, 또는 반대)**: brainstorming은 분류를 사람에게
  제시하고 승인받는 절차를 거치므로(브레인스토밍 스킬 자체의 게이트), 최종 책임은 hitl 대화 중인
  사람에게 있다. bounded로 잘못 분류돼도 native 경로(기계적 게이트만)로 진행될 뿐 안전성 문제는
  아니다 — SDD의 태스크별 리뷰어라는 추가 안전망만 못 받는 것뿐이다.
- **`plan_path` 문서가 라운드 중 갱신되어도 파일 경로는 그대로**: writing-plans 산출물은 라운드마다
  새 파일을 만들지 않고 같은 문서를 다듬으므로, `proposal-r<n>.json`이 라운드마다 갈아치워지는
  것과 달리 `plan_path` 값 자체는 변하지 않는다. 다만 원장(progress ledger)이 이미 일부 태스크를
  완료로 기록한 상태에서 플랜 문서 내용이 재협의로 바뀌면, 원장이 가리키는 태스크 식별자와 새 플랜의
  태스크 목록이 어긋날 수 있다 — 이 경우 원장을 폐기하고 처음부터 다시 진행한다(재협의는 구현 착수
  전에만 일어나므로 실제로는 원장이 비어있는 상태에서만 발생한다).
- **SDD 루프 내 5라운드 fix-loop 소진**: 위 "설계 4"의 5항목대로 `GATE_FAIL` 직행 — 추가 재시도
  없이 §6을 건너뛰고 `orca-workflow-task`에 반환, 이후는 기존 §4/§5 라우팅 그대로 처리된다.
- **크래시 재개**: SDD 루프의 태스크별 assign/outcome 로그가 `orca-task-runner` §0의 기존 orphan
  감지 패턴(waves-*.jsonl과 같은 스캔 방식)을 그대로 따르므로, 새 복구 메커니즘을 만들지 않는다.

## 마이그레이션/롤아웃

`orca-set.version`이 묶는 orca-* 스킬 세트에 `orca-workflow-task`/`orca-task-runner`가 모두 포함되므로,
구현 완료 후 `scripts/deploy-skills.sh`로 세트 전체를 배포해야 실제 반영된다(AGENTS.md "Skill
deployment" 절차 그대로).
