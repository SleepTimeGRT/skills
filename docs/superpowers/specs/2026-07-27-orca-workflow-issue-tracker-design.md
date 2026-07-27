# Orca Workflow — Issue Tracker Decoupling — Design

**Date**: 2026-07-27
**Status**: Approved (brainstorming phase) — pending implementation plan

## Context

`orca-workflow`/`orca-task-runner`/`orca-evaluate`(2026-07-22 설계, `2026-07-22-orca-workflow-architecture-design.md`)는
issue tracking을 GitHub Issues로 못박고 만들어졌다 — `gh issue view/list/close`, `## Acceptance criteria`/`## What
to build` 헤딩 리터럴이 `orca-workflow`/`orca-task-runner`/`orca-evaluate` 세 SKILL.md에 직접 박혀 있다.

실사용 repo인 `~/Projects/vprop`은 Jira(`voyagerx.atlassian.net`, `VP-XX`)를 쓴다 — GitHub는 코드·PR 전용이다.
issue tracking과 workflow orchestration은 분리 가능한 축인데 지금은 결합돼 있어 vprop에서 `orca-workflow`를
그대로 못 쓴다. 이 문서는 그 분리를 설계한다.

**세션 중 실측(Jira MCP, 읽기 전용)으로 확인한 사실**:

- vprop의 `docs/agents/issue-tracker.md`/`AGENTS.md`는 "팀이 Jira Epics를 도입하면..."이라고 쓰고 있지만, 실제로 VP
  프로젝트에는 **Epic 타입 이슈가 39개** 있다(`project = VP AND issuetype = Epic` → `totalCount: 39`). 이 문서는
  stale하다 — vprop 쪽에서 별도로 고쳐야 할 사항이며 이번 설계 범위 밖이다.
- Epic→child 연결은 Jira 네이티브 **`parent` 필드**로 되어 있다(`parent = VP-1145` → VP-1144/1146/1147/1148 정상
  반환).
- child 간 **명시적 의존 링크는 안 쓴다**(`VP-1148.issuelinks: []`) — 순서는 epic 설명 본문의 표/목록 순서로만
  암묵적으로 정해진다.
- `getTransitionsForJiraIssue(VP-1148)`가 반환하는 transition 중 `statusCategory.key == "done"`인 것이
  **3개**다(41=완료, 71=Duplicate, 81=Won't Do) — 즉 Jira의 `statusCategory`는 "정말 끝났다"와 "더 이상 안 하기로
  했다(사람이 나중에 리뷰하면서 결정)"를 구분하지 않는다. 하지만 vprop의 `docs/agents/issue-tracker.md`가 문서화한
  "Status transitions" 표에는 애초에 **11/21/31/41/61만 나열**되어 있고 71/81(Duplicate/Won't Do)은 그 표에
  없다 — repo 문서가 "정식 워크플로 transition"의 범위를 이미 선언해둔 것. Duplicate/Won't Do는 사람이 티켓을
  나중에 리뷰하며 "이건 더 안 한다"고 판단할 때만 쓰는 것이라 agent의 자동 완료 처리 후보에 애초에 들어가지
  않는다 — repo 문서에 문서화된 워크플로 표 밖의 transition은 고려 대상이 아니라는 원칙만 있으면 되고, 매번
  "여럿 중 뭘 고를지" 판단할 필요가 없다.
- vprop은 이미 `create-ticket → plan-ticket → implement-ticket → ship-pr`이라는 repo-native 스킬 세트로 VP-XX
  lifecycle을 처리하고 있다. `orca-workflow`는 이걸 호출하지 않는다 — 각자 다른 실행 모델(멀티 프로바이더
  fan-out vs 단일 에이전트 순차)이고, 겹치는 부분(티켓 조회·상태전환·PR 연동)만 이번 설계로 정리한다.

## 범위

**수정 대상**: `skills/orca-workflow/SKILL.md`, `skills/orca-task-runner/SKILL.md`, `skills/orca-evaluate/SKILL.md`,
그리고 신규 `orca-workflows/issue-trackers/{selection,github,jira}.md`.

**건드리지 않는 것**:

- PR/코드 호스팅(`gh pr create/merge`, CI 체크) — GitHub 전용으로 유지. issue tracking과 code hosting은 별개
  축이고 vprop도 코드는 GitHub(v6x org)에 있다.
- vprop의 `docs/agents/issue-tracker.md`, `create-ticket`/`plan-ticket`/`implement-ticket`/`ship-pr` — 전혀
  건드리지 않는다. `orca-workflow`는 이 문서를 읽기만 한다.
- vprop AGENTS.md의 stale "Jira Epics 도입하면..." 문구 — vprop 쪽에서 별도 수정.
- Linear adapter — 실제로 Linear를 쓰는 repo가 생기기 전까지는 안 만든다(YAGNI). 인터페이스는 3번째 백엔드를
  얹기 쉬운 모양으로 설계하되, 지금 파일을 미리 쓰지는 않는다.
- 이 저장소를 포크하는 안 — 검토했으나 기각(아래 "검토했으나 기각한 대안" 참고).

## 검토했으나 기각한 대안

1. **저장소 포크(`minchul-v6x`)** — vprop 전용으로 이 저장소를 통째로 포크하는 안. 이 저장소 전체(issue tracker와
   무관한 스킬 포함)를 이중 유지보수해야 하고, `orca-workflows/` 배포 경로(AGENTS.md의 기존 결정, #22)가 단일
   머신·단일 체크아웃을 전제로 하고 있어 포크 시 별도 배포 경로 결정이 새로 필요해진다. 사용자 확인 결과 이런
   폭넓은 변경 계획은 없었음 — 기각.
2. **공유 저장소에 repo별 tracker 어댑터를 하드코딩** — `orca-workflows/trackers/jira.md`에 vprop의 project key·
   transition ID를 직접 박아넣는 안. vprop의 `docs/agents/issue-tracker.md`와 내용이 겹쳐 두 출처가 어긋날
   위험이 있고, repo마다 새 파일이 필요해 domain-neutral 목표와 어긋남 — 기각. 대신 아래처럼 **범용 adapter +
   repo-doc 오버라이드**로 대체.
3. **`.orca/issue-tracker.json` 같은 구조화 설정 파일** — LLM이 실행하는 스킬이라 prose 조회가 자연스럽고, vprop에
   이미 있는 prose 문서의 세 번째 사본이 생기는 셈이라 이득 없이 비용만 늚 — 기각.
4. **tracker 해석 결과를 캐싱**(repo 안 gitignore 위치, 또는 `~/.local/state`) — AGENTS.md/tracker 문서를 읽는
   비용 자체가 낮고(e2e 테스트처럼 수 분짜리 비용이 아님), 매번 새로 읽으면 repo의 tracker 컨벤션이 바뀌어도
   즉시 반영된다 — 기각. 캐싱 없이 매 `orca-workflow` 실행 시작 시(§0, 1회) 새로 읽는다.

## 설계 — 3단 해석

`orca-workflow` §0(전제)에 다음 해석 단계를 신설한다. **매 실행 시작 시 1회, 캐싱 없이** 수행하고 그 실행 내내
재사용한다.

**1단 — 백엔드 선택**: 대상 repo의 AGENTS.md/CLAUDE.md에서 "Issue tracker" 섹션(예: vprop의
`### Issue tracker` → `docs/agents/issue-tracker.md` 링크 패턴)을 찾는다. 있으면 그 문서가 명시하는 백엔드를
쓴다. 없으면 GitHub Issues 기본값(현재 동작과 동일, 변경 없음).

Jira의 경우 이 문서 읽기는 선택이 아니라 **필수 전제조건**이다 — `getJiraIssue`/`searchJiraIssuesUsingJql`/
`transitionJiraIssue` 등 Atlassian MCP 툴은 전부 `cloudId`를 필수 파라미터로 받는데, 이 값 자체가 repo 문서
안에만 있다(vprop: `docs/agents/issue-tracker.md`의 `cloudId: fb59360c-...`). 즉 cloudId 없이는 Jira API를
아예 호출할 수 없으므로, 2단 adapter가 동작하려면 이 문서를 이미 읽은 상태여야 한다 — 3단에서 말하는
acceptance-criteria 섹션명·완료 transition 이름도 **그때 이미 열려 있는 같은 파일**에서 같이 얻는 것이지
별도로 한 번 더 조회하는 게 아니다.

**2단 — 범용 adapter**: 선택된 백엔드에 대해 `orca-workflows/issue-trackers/{github,jira}.md`(신규,
`model-selection.md` + `models/*.md`와 같은 역할 분담)가 다음 오퍼레이션을 **repo에 무관하게, 각 플랫폼의 구조적
필드로** 구현한다:

| 오퍼레이션 | 설명 | GitHub | Jira |
|---|---|---|---|
| `get_issue(id)` | 타입/제목/본문/상태 조회 | `gh issue view --json ...` | `getJiraIssue` |
| `get_issue_type(id)` | epic vs task 판별 | label 또는 body 구조(컨벤션 — GitHub엔 네이티브 계층 없음) | `issuetype.hierarchyLevel == 1` |
| `list_children(epic_id)` | child 목록+상태 | `gh issue list --search "epic:<n> in:body"` | `searchJiraIssuesUsingJql`: `parent = <key>` |
| `get_child_order(epic_id, children)` | 실행 순서 | 명시 의존 있으면 그것, 없으면 epic body 나열 순서 | 동일 원칙 — Jira issue link 있으면 그것, vprop처럼 없으면 epic description 순서 |
| `is_open(id)` | 열림/닫힘 확인 | `gh issue view --json state` | `status.statusCategory.key != "done"` |
| `close_issue(id, note)` | 종료 처리 | `gh issue close --comment` | 1단에서 이미 읽은 repo 문서의 워크플로 표에서 "완료" transition을 찾아 `transitionJiraIssue` + `addCommentToJiraIssue` — 추가 조회 아님. `getTransitionsForJiraIssue`가 API 레벨에서 더 많은 후보(Duplicate/Won't Do 등, `statusCategory`만으론 구분 안 됨)를 반환해도 **문서화된 워크플로 표 밖의 transition은 애초에 고려하지 않는다** — 사람이 나중에 리뷰하며 결정하는 것이지 agent가 완료 처리 중 고를 대상이 아님 |
| `link_pr_for_close(pr, id)` | PR 머지가 issue를 자동으로 닫아주는지 | Yes → "Closes #id" 키워드 보장 | No → 머지 직후 `close_issue` 명시 호출로 대체 |

**3단 — repo-doc 오버라이드**: API/구조로 알 수 없는, 진짜 repo 고유의 것만 대상 repo 문서에서 읽는다. Jira의
경우 이건 별도 조회가 아니라 1단에서 cloudId를 얻으려고 이미 읽은 문서에서 **같이** 얻는 값이다:

- acceptance-criteria 섹션 이름 (GitHub 컨벤션: `## Acceptance criteria`/`## What to build` / vprop:
  "완료 조건"/"요구사항")
- 정식 워크플로 표 중 "완료"에 해당하는 transition 이름 (vprop: 11/21/31/41/61 표, 41=완료). Duplicate/Won't
  Do처럼 이 표에 없는 transition은 API가 후보로 반환하더라도 agent가 고를 대상이 아니다 — 사람이 티켓을 나중에
  리뷰하며 "더 이상 안 한다"고 판단할 때 쓰는 것이지, 매 완료 처리마다 agent가 판단할 문제가 아니다.

repo 문서에 정식 워크플로 표/완료 transition이 아예 없으면 adapter는 조용히 아무거나 고르지 않고 사용자에게
확인을 요청한다.

## 파일별 변경

**`orca-workflow` SKILL.md**

- §0 전제: 위 3단 해석 단계 신설(맨 처음, 1회).
- §1 Epic 경로: `gh issue view/list` 호출을 `get_issue`/`list_children`으로, 순서 결정을 `get_child_order`로,
  closing 체크+`gh issue close`를 `is_open`+`close_issue`로 교체.
- §2a Contract 협상 relay: `orca orchestration task-create --spec`에 acceptance-criteria 섹션명을 포함해
  `orca-task-runner`/`orca-evaluate`에 전달.
- §2d PASS 라우팅: PR 생성/머지(`gh pr`)는 미변경. "Closes #N" 키워드 체크·삽입은 `link_pr_for_close`가
  "머지가 자동으로 닫아줌"이라고 답할 때만(GitHub) 실행 — 그 외(Jira)는 건너뛰고 머지 직후 무조건
  `close_issue(...)`를 명시 호출.

**`orca-task-runner` / `orca-evaluate` SKILL.md**

- `## Acceptance criteria`/`## What to build` 리터럴 참조를 "`orca-workflow`가 dispatch spec으로 넘겨준
  acceptance-criteria 섹션명"으로 교체. 두 스킬 다 tracker 접근 방법 자체(gh vs Jira MCP)는 몰라도 된다 — 이슈를
  읽는 건 이 세션 자신이고, 이미 해당 도구에 접근 가능하다고 가정한다.

**신규 — `orca-workflows/issue-trackers/`**

- `selection.md` — 백엔드 결정 알고리즘(`model-selection.md`와 같은 역할).
- `github.md` — 오늘 동작을 그대로 추출/일반화(동작 변화 없음).
- `jira.md` — `issuetype.hierarchyLevel`/`parent`/`statusCategory`/`getTransitionsForJiraIssue` 기반 범용
  adapter. vprop 고유 값(project key, transition ID 등)은 여기 넣지 않는다 — 3단에서 repo 문서를 통해 얻는다.

## 테스트/검증

- **읽기 전용 dry-run** — 이번 설계 세션에서 이미 vprop 실측으로 확인: `get_issue`/`list_children`(VP-1145 →
  VP-1144/1146/1147/1148)/`is_open` 경로, `close_issue`의 transition 후보 모호성.
- **쓰기 경로(`close_issue`, PR 머지)는 미리 실행하지 않는다** — 이 저장소 관례(AGENTS.md "배포·마이그레이션
  등 외부 쓰기 커맨드를 출력 확인 목적으로 실행하지 않는다")에 따라, 실제 검증은 사용자가 지켜보는 첫 실전
  `orca-workflow` 실행에서 한다.
- **GitHub 회귀 확인** — "Issue tracker" 섹션이 없는 repo(이 저장소 자신 포함, 커밋 로그 `#32`/`#31` 등으로
  GitHub Issues 사용 확인됨)에서 오늘과 동일하게 동작하는지 확인.

## Open follow-ups (이번 설계 범위 밖)

- Linear adapter — 실제로 Linear repo가 생기면 추가.
- generator/evaluator 세션(orca-task-runner/orca-evaluate가 스폰하는 코딩 에이전트)이 Jira MCP에 접근 가능한
  provider로 뜨는지 — `model-selection.md`/`models/*.md`와 얽히는 별도 확인 필요.
- vprop의 stale "Jira Epics 도입하면..." 문구 수정 — vprop 저장소 쪽 별도 작업.
