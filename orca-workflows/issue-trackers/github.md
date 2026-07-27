# Issue Tracker Adapter — GitHub Issues

기본값 — repo에 별도 tracker 문서가 없고 issue 식별자가 숫자 형태이거나, 문서가 GitHub Issues를 명시할 때
쓴다. `gh` CLI만 사용, repo 고유 값 없음(label/body 컨벤션은 있지만 이건 GitHub Issues 자체의 구조적 한계지
특정 repo의 값이 아니다 — GitHub Issues엔 애초에 네이티브 계층 필드가 없다).

## `get_issue(id)`

```bash
gh issue view <id> --json number,title,body,state,labels
```

## `get_issue_type(id)`

GitHub Issues엔 네이티브 epic/task 계층이 없다 — `get_issue`가 반환한 `labels`/`body`로 판별한다(예: `epic`
label, 또는 body에 하위 이슈 목록 섹션이 있는지).

## `list_children(epic_id)`

```bash
gh issue list --search "epic:<epic_id> in:body" --json number,title,state
```

search가 못 잡으면 epic body에 나열된 child 번호를 직접 파싱하는 것도 동일 정보다.

## `get_child_order(epic_id, children)`

명시적 의존(`Blocked by #N`/`Refs #N`)이 있으면 그 그래프 순서. 없으면 epic body에 나열된 순서 그대로.

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
gh pr view "<pr_number>" --json body -q .body | grep -qiE "(closes|fixes|resolves) #<id>" \
  || gh pr edit "<pr_number>" --body "$(gh pr view "<pr_number>" --json body -q .body)

Closes #<id>"
```

키워드가 확인/보강되면 그걸로 충분하다. 단 base가 default branch가 아니면 키워드가 동작하지 않으므로,
`close_issue`로 머지 후 상태를 한 번 더 확인하는 것이 안전망이 된다(호출자인 `orca-workflow` §2d 참고).
