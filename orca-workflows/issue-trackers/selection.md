# Issue Tracker Selection

`orca-workflow` §0에서 실행 시작 시 1회 수행한다. **캐싱 없음** — 매 실행마다 새로 읽는다(대상 repo의
tracker 컨벤션이 바뀌어도 즉시 반영하기 위해서. 근거: `docs/superpowers/specs/2026-07-27-orca-workflow-issue-tracker-design.md`).

## 1. 문서에서 백엔드 찾기

대상 repo의 AGENTS.md/CLAUDE.md에서 "Issue tracker" 섹션(예: `### Issue tracker` 헤딩, 별도 문서를 가리키는
링크 — vprop의 `docs/agents/issue-tracker.md` 패턴)을 찾는다. 있으면 그 문서가 명시하는 백엔드를 쓴다 —
아래 3으로.

## 2. 문서가 없을 때 — issue 식별자 모양으로 판단

곧바로 GitHub 기본값으로 넘어가지 않고, 먼저 이슈 식별자의 모양을 본다:

- 순수 숫자(`123`) → GitHub Issues 기본값(현재 동작과 동일). 아래 3의 `github.md`로.
- `PROJECT-숫자` 형태(`VP-456`, `ENG-789`)인데 tracker 문서가 없음 → **온보딩**으로 넘어간다
  (`skills/orca-workflow/SKILL.md` §0의 온보딩 서브플로우). cloudId 같은 값은 추측으로 채울 수 없다 —
  여기서 GitHub로 조용히 넘어가면 안 된다. 온보딩이 끝나면(문서가 생기면) 다시 1로 돌아가 해석한다.

## 3. 백엔드별 adapter 로드

- GitHub → `github.md`
- Jira → `jira.md`

adapter가 정의하는 오퍼레이션은 모든 백엔드에서 이름과 시그니처가 동일하다 — `orca-workflow`/
`orca-task-runner`/`orca-evaluate`는 어느 백엔드가 선택됐는지와 무관하게 같은 이름으로 호출한다:

- `get_issue(id)` — 타입/제목/본문/상태 조회
- `get_issue_type(id)` — epic vs task 판별
- `list_children(epic_id)` — child 목록+상태
- `get_child_order(epic_id, children)` — 실행 순서
- `is_open(id)` — 열림/닫힘 확인
- `close_issue(id, note)` — 종료 처리
- `link_pr_for_close(pr_number, id)` — PR 머지가 issue를 자동으로 닫아주는지

Linear 등 세 번째 백엔드가 필요해지면 이 파일의 1·2·3은 그대로 두고 `linear.md`만 추가한다 — 이 문서와
`orca-workflow` 쪽 변경은 필요 없다.
