# `project-setup` 스킬 + e2e 도구 선택 절차 설계

이슈: [#140](https://github.com/SleepTimeGRT/skills/issues/140)

## 문제

`skills/orca-evaluate/SKILL.md` §2(agent e2e)가 프로젝트·플랫폼과 무관하게 "Playwright MCP"를 유일한
선택지로 하드코딩한다(L77, L84, 폴백 L194). Playwright는 브라우저(웹) 전용이라 네이티브 모바일 앱에는
애초에 적용 불가능한데, 프로젝트의 실제 플랫폼을 판별해 적합한 e2e 도구를 고르는 절차 자체가 없다.

실측(studio-hevv/selah-android, issue #140 본문): 이 문서 그대로는 네이티브 Android 앱에 못 쓰여서
agy 워커가 Playwright MCP 대신 즉석으로 raw `adb shell` 명령을 조합해 대체 수행 중이었다 — 스킬 문서와
실제 배선이 어긋난 상태였고, 이 대체가 조용히 일어났다(evaluator의 자기 재확인 절차가 "선언된 도구가
실제로 쓰였는지"를 판정 기준으로 갖고 있지 않았기 때문).

## 범위

**수정 대상**: `skills/project-setup/SKILL.md`(신규), `skills/orca-workflow/SKILL.md` §0,
`~/.agents/orca-workflows/issue-trackers/selection.md` §2, `skills/orca-evaluate/SKILL.md` §2 및
폴백(L194), `~/.agents/orca-workflows/models/agy.md` L75, `skills/orca-set.version`.

**하나의 스펙으로 묶는 이유**: `orca-workflow`/`orca-evaluate`의 fail-fast 안내가 `/project-setup`을
가리키므로, `project-setup`이 존재하지 않으면 그 안내가 가리키는 대상이 없는 상태로 머지된다. 세
컴포넌트를 독립적으로 머지하면 중간 상태에서 깨진다 — 함께 설계·구현한다.

**범위 밖**:

- **회귀 테스트 자산화** — 이슈 본문이 "부수적 문제"로 지적한, agent e2e 시나리오가 매 실행 `-p` 프롬프트에
  즉석으로만 담겨 재사용 가능한 회귀 자산으로 남지 않는 문제. 별도 이슈로 다룬다.
- **멀티플랫폼(단일 repo가 web+native 등을 동시에 가짐)** — `docs/agents/e2e-tooling.md`는 단일 target만
  지원한다. 필요해지기 전엔 만들지 않는다(YAGNI, issue-tracker의 Linear adapter와 같은 원칙).
- **e2e-tooling.md 내용의 자동 검증**(예: 선언된 MCP가 실제로 연결되는지 사전 smoke-test) — `project-setup`은
  기존 issue-tracker 온보딩과 동일하게 사람이 답한 내용을 그대로 문서화할 뿐, 값을 검증하지 않는다.

## 검토했으나 기각한 대안

1. **`orca-evaluate` §2 안에서 사람에게 직접 질문(hitl 에스컬레이션)** — evaluate는 파이프라인 깊숙한 곳,
   종종 afk 모드로 실행된다. 매 첫 실행마다 evaluate 단계에서 사람 개입이 막히는 구조는 이미 generation이
   끝난 뒤에야 막혀 낭비가 크고, 기존 ESCALATE 카테고리와 성격이 다른 blocking 질문 메커니즘을 새로
   만들어야 한다 — 기각. 대신 온보딩을 파이프라인 시작 이전, 별도의 수동 스킬로 뺀다.
2. **`docs/agents/e2e-tooling.md`를 JSON 등 구조화 설정 파일로** — 이 저장소는 이미 issue-tracker 설계에서
   같은 대안을 검토·기각한 전례가 있다(`docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`
   "검토했으나 기각한 대안" #3: "LLM이 실행하는 스킬이라 prose 조회가 자연스럽다"). 같은 원칙 재사용 — 기각.
3. **플랫폼 자동 판별(repo 구조로 web/native/desktop 추정) 후 기본값 적용** — 모노레포·혼재 프로젝트에서
   오판 시 evaluate가 스스로 알아채기 어려운 조용한 실패로 이어진다. 사람에게 직접 묻는 쪽이 오탐 없이
   확실하다 — 기각(사용자 판단, Q1).
4. **e2e-tooling 존재 확인을 `orca-workflow`/`-epic`/`-task` 세 SKILL.md에 각각 추가** — 세 스킬 모두
   `selection.md` 절차에 위임돼 있고, `orca-workflow`가 유일한 실제 진입점(`-epic`/`-task`는 세션 내
   in-session 실행 또는 `-epic`의 스폰 대상일 뿐 사람이 직접 부르지 않음)이므로 `orca-workflow` §0
   한 곳에서만 라우팅(§1) 이전에 확인하면 충분하다 — 세 파일 모두 고치는 중복을 기각.

## 설계

### 1. `docs/agents/e2e-tooling.md` 스키마

`docs/agents/issue-tracker.md`와 같은 스타일의 prose 문서(라벨링된 섹션, 자유 텍스트):

```markdown
# E2E Tooling

## Platform
native-android

## Tool
Maestro MCP

## Usage guidance
YAML 기반 시나리오, 재실행 가능. 에뮬레이터가 이미 부팅돼 있어야 연결된다.

## Precondition
- 에뮬레이터가 부팅된 상태여야 한다 (`adb devices`로 확인)
- 앱이 이미 설치돼 있어야 한다 (패키지: com.example.app)
```

- **Platform**: 자유 텍스트(예시: `web`/`native-android`/`native-ios`/`desktop`) — 목록이 전부가 아니다.
- **Tool**: MCP/도구 이름. `orca-evaluate` §2의 트레이스 재확인에서 "선언된 도구가 실제로 쓰였는지"
  판정의 기준값이 된다.
- **Usage guidance**: 기존 §2 L77의 "Playwright MCP(accessibility-tree 기반...)" 같은 도구별 안내 텍스트가
  여기로 옮겨온다. evaluator가 `-p` 구성 시 splice.
- **Precondition**: 인프라 전제조건. §4 기존 ESCALATE "인프라 문제(계정·secret·환경)" 버킷의 예시로
  편입한다 — 새 카테고리를 만들지 않는다.

### 2. `skills/project-setup/SKILL.md`(신규)

`/project-setup`으로 수동 실행하는 범용 온보딩 스킬. 인자 없이 두 섹션을 매번 순서대로 확인하고, 이미
설정된 도메인은 스킵(멱등):

**§1 Issue tracker**: `docs/agents/issue-tracker.md`가 있으면 스킵. 없으면 "이 repo가 GitHub Issues를
쓰나요, 다른 트래커를 쓰나요?"를 묻는다. GitHub면 **문서를 만들지 않고 종료**(숫자 ID 폴백을 그대로
유지 — `selection.md`의 무-온보딩 경로가 안 깨진다). 다른 트래커면 트래커 종류 + 연결 정보(Jira: site·
cloudId·project key 등) + 완료 상태/transition 이름을 물어 초안 작성 → 승인 → 별도의 작은 커밋으로
반영(기존 `orca-workflow` §0 인라인 로직을 그대로 이관, 동작 변경 없음 — AC 섹션 이름은 여기서 묻지
않는다: AC는 저장소 설정 시점의 고정값이 아니라 이슈마다 매번 새로 협상되는 값이고,
`orca-evaluate` §1의 contract negotiation이 이미 소유하고 있다. `jira.md`/`github.md`/
`contract-schema.md` 중 어느 adapter도 tracker 문서에서 AC 섹션 필드를 읽지 않는다).

**§2 E2E tooling**: `docs/agents/e2e-tooling.md`가 있으면 스킵. 없으면 무조건 묻는다(GitHub 같은
무조건-기본값이 없다) — Platform(예시 제시) + Tool + Usage guidance + Precondition. Platform으로
"web"류를 답하면 Tool 기본 제안으로 "Playwright MCP"를 보여준다(이슈 본문의 "웹 프로젝트 기본값" 요건 —
사람이 여전히 최종 승인한다는 점에서 자동 판별과 다르다). 초안 작성 → 승인 → 별도 커밋.

**크로스툴 이식성**: "사람에게 묻는다"를 일반적 표현으로만 쓴다 — `AskUserQuestion` 같은 Claude Code
전용 도구명을 스킬 본문에 넣지 않는다(AGENTS.md 원칙, 플랫폼마다 자기 방식으로 묻는다).

### 3. `~/.agents/orca-workflows/issue-trackers/selection.md` §2 개정

온보딩 트리거 문단을 자체 완결형으로 바꾼다: "`PROJECT-123` 형태인데 문서 없음 → 호출자(`orca-workflow`/
`-epic`/`-task` 중 무엇이든) 사용자에게 `/project-setup` 실행을 안내하며 이번 실행을 중단한다." 기존
"(`skills/orca-workflow/SKILL.md` §0의 온보딩 서브플로우)" 포인터를 제거한다. 세 호출자 모두 이 파일
하나에 위임돼 있으므로(§3 "공통 오퍼레이션 시그니처가 유지되면 실행 단계는 변경하지 않아도 된다" 원칙과
동일), `orca-workflow-epic`/`orca-workflow-task` SKILL.md는 손대지 않는다. **숫자 ID 경로(문서 없어도
GitHub 기본값)는 변경하지 않는다** — 회귀 트랩 지점.

### 4. `skills/orca-workflow/SKILL.md` §0 개정

- 기존 인라인 "**온보딩**: ... 사용자에게 직접 묻는다 ..." 문단을 삭제한다(§3으로 이관돼 중복).
- §1 라우팅 이전에 `docs/agents/e2e-tooling.md` 존재 확인을 추가한다: 없으면 `/project-setup` 안내와
  함께 즉시 중단(§1 자체가 실행되지 않아 generation 낭비 없이 최상단에서 막힌다). 이슈 ID 모양에 따른
  예외는 없다 — e2e-tooling은 파이프라인의 모든 task 평가에 항상 필요하다는 기존 전제(`orca-evaluate` §2가
  이미 무조건 게이트로 문서화) 위에, 이번 이슈는 "무엇을 쓸지"만 다룬다.

### 5. `skills/orca-evaluate/SKILL.md` §2 및 폴백(L194) 개정

**스폰 절차**:
1. 스폰 전에 evaluator가 대상 repo의 `docs/agents/e2e-tooling.md`를 직접 읽는다(script 없이, evaluator
   자신의 판단으로).
2. **없으면**: 이 시점에는 이미 `orca-workflow` §0이 막았어야 하므로 도달은 예외적 경로(폴백 직행 등)다.
   조용히 Playwright로 되돌아가지 않고, §4 기존 ESCALATE("인프라 문제로 판단 불가" 버킷)로 처리하며
   `/project-setup` 실행을 안내한다.
3. **있으면**: Platform/Tool/Usage guidance/Precondition을 읽어 `-p` 문자열을 구성한다. L84의 하드코딩된
   `"Playwright MCP 지침"` 리터럴을 `<e2e-tooling.md의 Tool + Usage guidance + 테스트 시나리오 + 앱 경로
   + precondition 확인 지침 + 실패 요약 저장 지침>`으로 교체한다.
4. Precondition 미충족(에뮬레이터 미부팅 등)은 §4 기존 "인프라 문제(계정·secret·환경)" ESCALATE 버킷
   설명에 예시로 추가한다.

**자기 재확인(§2 L95 문단) 개정**: 기존 "조용히 막히거나 우회한 흔적은 없는지 확인" 지침에 구체 기준을
추가한다 — "트레이스에서 e2e-tooling.md의 `Tool` 필드가 실제로 쓰였는지 확인한다. 다른 방식(예: 선언은
Maestro인데 raw adb로 우회)으로 조용히 대체된 흔적이 있으면 agy의 성공 자기요약을 그대로 신뢰하지
않는다." — selah-android에서 실측된 Playwright→adb 무단 대체 문제를 직접 겨냥한다.

**폴백(L194) 개정**: "Playwright MCP를 붙인 headless agy" → "`docs/agents/e2e-tooling.md`가 선언한
도구를 붙인 headless agy(§2와 동일 도구 선택 절차, 문서 없으면 §2와 동일하게 ESCALATE)".

### 6. `~/.agents/orca-workflows/models/agy.md` L75 개정

"For agent e2e, configure an accessibility-tree Playwright MCP and smoke-test the connection before
relying on it." → "For agent e2e, configure the project-declared e2e tool (resolved by the consuming
skill's `docs/agents/e2e-tooling.md`, not necessarily an MCP — e.g. a raw CLI) and smoke-test the
connection/interface before relying on it."

### 7. `skills/orca-set.version`

`project-setup`을 7번째 멤버로 추가한다 — `orca-workflow`의 fail-fast 안내가 이 스킬을 이름으로
참조하므로 버전-결합 관계다. 구체 버전 넘버링은 구현 시점에 `scripts/deploy-skills.sh` 관례를 따른다
(스펙에서 못박지 않는다).

## 검증

TDD 스테이지 순서: pure(fixture 손 추적) → 통합(실제 스킬 실행) → manual(실제 파이프라인 1회).

1. **Fixture 준비(pure)** — 임시 git repo 3종:
   - (a) `docs/agents/*` 없음 + 숫자 이슈 ID(`123`)
   - (b) `docs/agents/*` 없음 + `PROJECT-123` 형 ID(`VP-456`)
   - (c) `issue-tracker.md`+`e2e-tooling.md` 둘 다 존재
2. **결함 재현(변경 전 프로즈로 추적)** — 오늘은 e2e-tooling 확인 자체가 없으므로 (a)(b) 모두 e2e 게이트를
   그대로 통과해버리는 게 재현돼야 한다(#140이 지적한 결함 그 자체).
3. **최소 구현 후 재추적** — `selection.md`/`orca-workflow` §0 개정 프로즈로 (a)(b)(c) 재추적:
   - (a) issue-tracker 트리거는 **걸리지 않고**(회귀 가드) e2e-tooling만 걸려야 한다.
   - (b) 둘 다 걸려야 한다.
   - (c) 아무것도 안 걸리고 §1로 통과해야 한다.
4. **통합** — 스크래치 fixture repo에 `/project-setup`을 실제로 실행해 질문에 답하고, `docs/agents/
   e2e-tooling.md`(+ 필요시 `issue-tracker.md`)가 초안→승인→별도 커밋으로 반영되는지 확인한다. 이후 그
   repo로 `orca-workflow` §0을 재추적해 더 이상 막히지 않음을 확인한다.
5. **Manual(1회, 실제 파이프라인)** — 실제 `orca-workflow-task`→`orca-evaluate` 1회전을 non-Playwright
   도구 선언(예: native 시나리오)으로 돌려 `-p` 구성과 도구-대체 자기재확인이 실제로 동작하는지 확인한다.
   비용이 크므로 머지 전 1회, 파일럿 성격으로 수행한다(AGENTS.md "대표 파일럿을 먼저 돌린다" 원칙).
6. **회귀 체크리스트** — §2 개정이 기존 안전장치(§0 "MCP 서버 인증 전제", agent e2e 실패 시 §3 스킵
   fail-fast 로직, `dispatch-verify.md`/`logging.md` 호출)를 하나도 빠뜨리지 않았는지 개정 전/후 §2 스텝을
   나란히 대조한다.
