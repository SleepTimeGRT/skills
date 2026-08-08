# Issue Tracker Selection

`orca-workflow`/`orca-workflow-epic`/`orca-workflow-task` 각각의 §0에서 실행 시작 시 1회 수행한다.
**캐싱 없음** — 매 실행마다 새로 읽는다(대상 repo의
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
`orca-workflow-epic`/`orca-workflow-task`는 어느 백엔드가 선택됐는지와 무관하게 같은 이름으로 호출한다
(`orca-task-runner`/`orca-evaluate`는 코드 생성·평가만 하고 tracker 오퍼레이션을 직접 호출하지 않는다):

- `get_issue(id)` — 타입/제목/본문/상태 조회
- `get_issue_type(id)` — epic vs task 판별
- `list_children(epic_id)` — child 목록+상태
- `get_child_order(epic_id, children)` — 실행 순서
- `is_open(id)` — 열림/닫힘 확인
- `close_issue(id, note)` — 종료 처리
- `link_pr_for_close(pr_number, id)` — PR 머지가 issue를 자동으로 닫아주는지

Linear 등 세 번째 백엔드를 추가할 때 adapter 파일만 만들면 끝나지 않는다:

- `linear.md`에 위 공통 오퍼레이션을 구현한다.
- 이 파일 §3의 backend 목록에 Linear를 추가한다.
- Jira와 Linear 모두 `PROJECT-123`형 식별자를 쓸 수 있으므로 §2에서 모양만 보고 둘을 구분하지 않는다.
  tracker 문서가 없으면 기존처럼 온보딩으로 보내고, 온보딩 문서가 backend를 명시하게 한다.

공통 오퍼레이션 시그니처가 유지되면 `orca-workflow`/`orca-workflow-epic`/`orca-workflow-task`의 실행
단계는 변경하지 않아도 된다.
