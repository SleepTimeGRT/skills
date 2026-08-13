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

## `add_comment(id, note)`

```bash
gh issue comment <id> --body "<note>"
```

`close_issue`와 달리 상태를 건드리지 않는다 — issue가 이미 닫혀 있어도(다른 채널로 닫혔든, 정상
`link_pr_for_close`로 닫혔든) 그냥 코멘트만 남긴다. 이미 닫힌 issue에 감사 코멘트를 남겨야 할 때
(`orca-workflow-task` §4의 머지-후 라우팅, issue #115) `close_issue` 대신 이걸 쓴다.

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
`close_issue`로 머지 후 상태를 한 번 더 확인하는 것이 안전망이 된다(호출자인 `orca-workflow-task` §4 참고).

**auto-close 채널은 PR 본문 하나가 아니다(issue #115, MediCount#540 실측)**: `gh pr merge --squash`가
커밋 메시지를 지정받지 않으면, 브랜치에 커밋이 1개뿐인 PR은 그 원 커밋의 메시지(본문 포함)를 그대로
스쿼시 커밋 메시지로 쓴다 — 이 함수가 관리하는 PR 본문이 아니다. 그 원 커밋에 `Closes #N` 트레일러가
실려 있으면(흔한 커밋 메시지 컨벤션), PR 본문에서 keyword를 의도적으로 뺐어도 이 두 번째 채널을 통해
issue가 그대로 자동 종료된다. 그래서 `orca-workflow-task` §4는 merge 시 `--subject`/`--body`를 명시해
스쿼시 커밋 메시지를 이 함수가 관리하는 PR 본문으로 고정한다 — auto-close 채널이 이 함수 하나로
좁혀지도록. 호출자가 그 인자를 빠뜨리면 이 두 번째 채널이 다시 열린다.

## `find_regressions()`

**컨벤션**: 머지된 task issue가 사후 결함의 원인으로 판명되면, 결함 이슈 본문에
`regressed-by #<task-issue>` 라인을 단다(대소문자 무관 — 사람이 결함을 접수하며 원인 커밋/PR을
추적했을 때). 이 오퍼레이션은 그 trailer가 달린 열린 결함 이슈를 찾아 (결함 이슈 번호, 지목된
task issue 번호) 쌍을 반환한다. 소비자는 `orca-retro` §2 렌즈 5(false-PASS 관측, issue #157)다.

```bash
gh issue list --state open --search '"regressed-by" in:body' --json number,title,body \
  | jq -c '.[] | select(.body | test("(?i)regressed-by[[:space:]]+#[0-9]+"))
      | {defect: .number, title: .title,
         task: (.body | capture("(?i)regressed-by[[:space:]]+#(?<n>[0-9]+)").n)}'
```

`capture`는 첫 매치만 잡는다 — 결함 하나가 여러 task를 지목하면(드묾) 본문을 직접 읽어 쌍을 늘린다.

## acceptance criteria

issue body의 AC 섹션은 전제가 아니다 — acceptance criteria는 contract 협상에서 초안·승인되며
(`~/.agents/orca-workflows/contract-schema.md`), issue body에 `## Acceptance criteria`류 섹션이
있으면 그 초안의 입력(issue 원문의 일부)이 될 뿐이다. 섹션 존재를 gate로 확인하지 않는다.
