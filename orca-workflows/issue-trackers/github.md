# Issue Tracker Adapter — GitHub Issues

기본값 — repo에 별도 tracker 문서가 없고 issue 식별자가 숫자 형태이거나, 문서가 GitHub Issues를 명시할 때
쓴다. `gh` CLI와 `gh api`만 사용하며 repo 고유 값은 없다. GitHub의 native issue type/sub-issue 관계를
우선하고, 이를 사용하지 않는 기존 repo에서만 label/body 컨벤션으로 fallback한다.

## `get_issue(id)`

```bash
gh issue view <id> --json number,title,body,state,labels
gh api "repos/{owner}/{repo}/issues/<id>" --jq '{type: .type, parent: .parent_issue_url}'
```

## `get_issue_type(id)`

다음 순서로 `epic` vs `task`를 판별한다:

1. native sub-issue가 하나 이상이면 `epic`;
2. native issue type이 repo 문서에서 epic으로 지정한 type이면 `epic`;
3. native metadata를 쓰지 않는 repo에서만 `get_issue`의 `labels`/`body`를 확인한다(예: `epic` label,
   또는 하위 이슈 목록 섹션).

이름이 지역화되거나 조직별로 다를 수 있으므로, repo 문서가 없는데 native type 이름만 보고 임의로 epic을
추측하지 않는다. native sub-issue 관계는 type 이름과 무관한 구조적 근거다.

## `list_children(epic_id)`

native sub-issue가 source of truth다:

```bash
gh api --paginate "repos/{owner}/{repo}/issues/<epic_id>/sub_issues" \
  --jq '.[] | {number, title, state}'
```

native 결과가 비어 있고 repo가 legacy body convention을 사용한다고 문서화한 경우에만 fallback한다:

```bash
gh issue list --search "epic:<epic_id> in:body" --json number,title,state
```

legacy search가 못 잡으면 epic body에 나열된 child 번호를 직접 파싱한다.

## `get_child_order(epic_id, children)`

명시적 의존(`Blocked by #N`/`Depends on #N`)이 있으면 그 그래프 순서. `Refs #N`은 관련성만 나타내므로
의존 edge로 취급하지 않는다. 의존이 없으면 native sub-issue 순서, legacy fallback이면 epic body 순서다.

## `is_open(id)`

```bash
gh issue view <id> --json state -q .state
```

`"OPEN"`이면 열림.

## `close_issue(id, note)`

```bash
gh issue close <id> --comment "<note>"
```

## `link_pr_for_close(pr_number, id)`

**merge-magic 있음** — PR 머지가 "Closes #id" 키워드로 issue를 자동으로 닫아준다.

```bash
gh pr view "<pr_number>" --json body -q .body \
  | grep -qiE "(^|[[:space:]])(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#<id>([^0-9]|$)" \
  || gh pr edit "<pr_number>" --body "$(gh pr view "<pr_number>" --json body -q .body)

Closes #<id>"
```

끝 경계 `([^0-9]|$)`는 `id=12`가 `#123`에 잘못 매칭되는 것을 막는다. 키워드가 확인/보강되면 그걸로
충분하다. 단 base가 default branch가 아니면 키워드가 동작하지 않으므로,
`close_issue`로 머지 후 상태를 한 번 더 확인하는 것이 안전망이 된다(호출자인 `orca-workflow` §2d 참고).

## acceptance-criteria 섹션명

기본값은 `## Acceptance criteria`뿐이다 — fallback 없음. `## What to build`는 별개의 독립된 섹션이다
(`orca-workflow` §1a가 둘을 각각 확인하는 것과 일치 — "무엇을 만들지"와 "acceptance criteria"는 서로
다른 개념이라 하나가 다른 하나를 대신하지 않는다). `## Acceptance criteria`가 issue body에 없으면 이
섹션은 "없음"으로 취급된다 — `orca-workflow`가 `orca-task-runner`를 dispatch하기 전에 이를 gate로
확인한다. repo가 다른 컨벤션을 쓴다면 그건 그 repo 자체의 tracker 문서(있다면)가 이 기본값을 오버라이드한다.
