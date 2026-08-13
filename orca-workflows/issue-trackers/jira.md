# Issue Tracker Adapter — Jira

현재 runtime에 설치·연결된 Atlassian connector를 사용한다. 이 adapter가 요구하는 capability는 **issue
조회**, **JQL 검색**, **transition 목록 조회**, **상태 전환**, **comment 추가**다. Claude Code, Codex,
Antigravity가 노출하는 실제 tool namespace와 이름은 다를 수 있으므로, 실행 시 이 capability를 현재
connector tool에 매핑한다.

**repo의 tracker 문서 없이는 이 adapter가 동작하지 않는다.** 각 capability가 요구하는 `cloudId`는 대상
repo의 tracker 문서에만 있다. 이 파일에는 project key·transition ID 같은 repo 고유 값을 넣지 않는다 —
전부 대상 repo의 tracker 문서에서 온다.

## 전제 — repo 문서에서 읽어야 하는 값

- `cloudId` (필수 — 이게 없으면 아래 오퍼레이션을 하나도 호출할 수 없다)
- 정식 워크플로 transition 표, 그중 "완료"에 해당하는 이름

## `get_issue(id)`

```
getJiraIssue(cloudId, issueIdOrKey=id)
```

`fields.issuetype`, `fields.summary`, `fields.description`, `fields.status`를 본다.

## `get_issue_type(id)`

```
fields.issuetype.hierarchyLevel == 1  →  epic
```

프로젝트 지역화(한국어 "에픽"/영어 "Epic" 등)와 무관하게 구조적으로 판별한다 — 이름 문자열을 매칭하지 않는다.

## `list_children(epic_id)`

```
searchJiraIssuesUsingJql(cloudId, jql="parent = <epic_id>")
```

## `get_child_order(epic_id, children)`

명시적 issue link(blocks/is blocked by)가 있으면 그 그래프. 없으면(흔하다 — Jira epic이 의존 링크 없이
설명 본문에 표/목록만 나열하는 경우가 많다) epic description에 나열된 순서 그대로.

## `is_open(id)`

```
getJiraIssue(cloudId, issueIdOrKey=id).fields.status.statusCategory.key != "done"
```

## `close_issue(id, note)`

repo 문서의 워크플로 표에서 "완료" transition 이름을 찾아 그 transition id로 전환한다. 이름→id 변환은 `getTransitionsForJiraIssue`의 결과를 이용한다:

```
getTransitionsForJiraIssue(cloudId, issueIdOrKey=id)를 호출해 현재 available transition 목록을 받는다.
목록에서 name이 repo 문서의 "완료" transition 이름과 일치하는 항목을 찾는다.
그 항목의 id를 사용해 다음을 호출한다:
transitionJiraIssue(cloudId, issueIdOrKey=id, transition={id: <찾은 transition id>})
addCommentToJiraIssue(cloudId, issueIdOrKey=id, comment=note)
```

`getTransitionsForJiraIssue`는 `statusCategory.key == "done"`인 후보를 여러 개 반환할 수 있다(예: 완료/
Duplicate/Won't Do). **repo 문서의 워크플로 표에 없는 transition은 고려하지 않는다.** Duplicate/Won't Do류는
사람이 티켓을 나중에 리뷰하며 "더 이상 안 한다"고 판단할 때 쓰는 것이라, agent의 완료 처리 후보가 아니다 —
매 완료 처리마다 여럿 중 고를 문제가 아니다.

다음 두 실패 케이스에서는 조용히 아무거나 고르지 않고 멈춘다 — 둘 다 `orca-workflow-task` §5
(Escalation·보고)로 보고한다(outcome: `NO_DONE_TRANSITION`), 사람 확인 없이 진행하지 않는다:
- repo 문서의 워크플로 표 자체가 없거나 "완료"에 해당하는 transition 이름이 명시돼 있지 않을 때
- repo 문서가 "완료" 이름을 명시하지만, 그 이름이 `getTransitionsForJiraIssue`가 반환한 현재 상태 기준
  available transition 목록에 없을 때(Jira transition은 현재 status에 따라 달라지므로 발생 가능) —
  가장 비슷한 이름으로 임의 대체하지 않는다

## `find_regressions()`

**컨벤션**: 머지된 task issue가 사후 결함의 원인으로 판명되면, 결함 이슈 description에
`regressed-by <ISSUE-KEY>` 라인을 단다(대소문자 무관). 열린 결함 이슈에서 그 라인을 찾아
(결함 이슈 키, 지목된 task issue 키) 쌍을 반환한다. 소비자는 `orca-retro` §2 렌즈 5(issue #157)다.

```
searchJiraIssuesUsingJql(cloudId, jql='text ~ "regressed-by" AND statusCategory != Done')
```

반환된 각 이슈의 description에서 `regressed-by <ISSUE-KEY>` 라인을 파싱한다 — JQL `text ~`는
토큰 매칭이라 오탐이 있을 수 있으므로 description 원문 확인이 필수다.

## `link_pr_for_close(pr_number, id)`

**merge-magic 없음** — GitHub PR 머지로 Jira 티켓이 자동으로 닫히지 않는다. 이 오퍼레이션 자체는
**no-op**이다(아무것도 하지 않는다). 종료는 이 오퍼레이션이 아니라 호출자(`orca-workflow-task` §4)가
머지 성공 확인 후 별도로 `close_issue(id, note)`를 호출해서 처리한다(`note` 예:
`"Merged via PR #<pr_number>"`).
