---
name: epic-drain
description: Invoke explicitly via `/epic-drain <epic#>` or `/epic-drain <issue#> [<issue#> ...]` — do not phrase-match. Drives a GitHub epic's child issues end to end — plans every child with the human first (superpowers brainstorming → writing-plans, order and dependencies confirmed, queue recorded in the epic body), then drains the queue unattended — one fresh provider agent (claude/codex/agy, chosen per child) per child issue in an Orca worktree terminal, each running subagent-driven-development → PR → squash merge, with results reported as issue comments. Human input is needed only in the planning phase. Do NOT use for a single ad-hoc change (use superpowers directly), for ad-hoc multi-agent coordination (use `orchestration`), or for raw terminal/worktree control (use `orca-cli`).
compatibility: Claude Code session for the planning/driver phase (superpowers plugin + Agent tool). Child agents run inside Orca terminals — requires the `orca` CLI with orchestration enabled, `gh`, and superpowers installed for each provider used (claude/codex/agy).
---

# Epic Drain

이슈 여러 개를 epic으로 묶어 끝까지(merge까지) 가져가는 스킬. 두 페이즈로 나뉜다:

- **페이즈 A — 계획(사람과 함께)**: 자식 순서·의존을 정하고, 자식마다 superpowers brainstorming으로
  무엇을 만들지 합의하고(architectural이면 spec+plan 문서까지), 큐를 epic 본문에 기록한다.
- **페이즈 B — 실행(무인)**: 큐 순서대로 자식마다 Orca worktree + provider 터미널을 띄워 구현→PR→merge를
  맡기고 결과만 받는다. 이 세션(드라이버)은 코드를 읽지도 쓰지도 않는다.

상태 정본은 GitHub뿐이다 — epic 본문의 큐 블록, 자식 이슈/PR 상태, 자식 이슈의 결과 코멘트, plan 문서.
별도 로그 파일·상태 파일을 만들지 않는다.

## 0. 전제

- 대상 repo = 현재 cwd의 git repo. `gh auth status`가 통과해야 한다. `REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"`.
- 페이즈 B는 `orca status --json`이 ready여야 한다. 아니면 페이즈 A까지만 하고 보고한다.
- 이 스킬의 헬퍼: `QUEUE="$HOME/.agents/skills/epic-drain/scripts/queue.py"` (배포 경로. 이 repo 안에서
  개발 중이면 `skills/epic-drain/scripts/queue.py`). 서브커맨드 `read`/`write`/`state`/`next`.
- Orca 명령 문법은 여기 복제하지 않는다 — 필요한 시점에 `orca skills get orca-cli`(worktree·터미널),
  `orca skills get orchestration`(Run/task/worker-start/check)을 읽고 거기 적힌 현재 구성을 쓴다.
- 입력 해석:
  - `/epic-drain <epic#>` — 그 이슈가 epic. 자식 = (a) 본문에서 참조된 `#N`(체크리스트 포함) ∪ (b) GitHub
    sub-issue(아래 GraphQL) 가운데 **열린 것**. 큐 블록이 이미 있으면 그 블록이 자식 목록의 정본이다(→ §3 재개).
    sub-issue 조회(없거나 필드 오류면 (a)만으로 진행하고 그 사실을 사람에게 한 줄 알린다):

    ```bash
    OWNER="${REPO%/*}"; NAME="${REPO#*/}"
    gh api graphql -f query='query($o:String!,$n:String!,$i:Int!){ repository(owner:$o,name:$n){ issue(number:$i){ subIssues(first:100){ nodes{ number state } } } } }' \
      -f o="$OWNER" -f n="$NAME" -F i="$EPIC" --jq '.data.repository.issue.subIssues.nodes[] | select(.state=="OPEN") | .number'
    ```
  - `/epic-drain <issue#> [<issue#> ...]` — epic이 아직 없다. 제목·자식 체크리스트를 제안하고 사람이 승인하면 `gh issue create`로 epic을 만든 뒤 위 경로로 합류한다.

## 1. 페이즈 A — 계획

사람과 같은 세션에서 한다. 질문은 한 번에 하나, 선택지는 추천 먼저.

### 1.1 순서·의존 제안 → 확정

자식 이슈 본문을 모두 읽고 표를 제안한다 — 자식마다 한 줄 근거(파일 겹침, 선행 산출물 필요, 독립). 사람이
순서·의존·provider를 고친다. provider는 전부 `claude`로 시작하고 사람이 자식별로 `codex`/`agy`로 바꿀 수
있다(목적은 구독·레이트리밋 풀 분산 — 품질 비교가 아니다). 확정되면 큐 블록을 epic 본문에 쓴다:

```bash
gh issue view "$EPIC" -R "$REPO" --json body -q .body > /tmp/epic-body.md
# rows.json: [{"order":1,"issue":"85","kind":"","depends_on":[],"provider":"claude","plan":""}, ...]
python3 "$QUEUE" write /tmp/epic-body.md /tmp/rows.json > /tmp/epic-body.new.md
gh issue edit "$EPIC" -R "$REPO" --body-file /tmp/epic-body.new.md
```

`kind`는 이 단계에선 비워 둔다 — 1.2가 채운다. 블록 형식(큐 파서가 읽는 형식 그대로):

```
<!-- epic-drain:queue -->
| order | issue | kind | depends_on | provider | plan |
|---|---|---|---|---|---|
| 1 | #85 | architectural | — | claude | docs/superpowers/plans/2026-08-22-subscription-tests.md |
| 2 | #86 | bounded | #85 | codex | (issue comment) |
| 3 | #87 | spike | — | — | — |
<!-- /epic-drain:queue -->
```

### 1.2 자식마다 brainstorming

큐 순서대로 자식 하나씩 `superpowers:brainstorming`을 **실제로 호출**한다. 입력 = 이슈 원문 + 앞 자식들의
확정 plan 요약(의존 관계가 있으면 그 plan 전문). brainstorming 자신의 분류를 그대로 따른다:

- **spike** — 조사 결과를 이슈 코멘트로 남기고 `kind=spike`. 페이즈 B에서 제외. 이슈 닫기는 사람 몫.
- **bounded** — spec/plan 문서 없이 짧은 합의만. 합의 내용을 이슈 코멘트로 남기되 첫 줄을
  `<!-- epic-drain:agreement -->`로 시작한다(자식 에이전트가 이 코멘트를 찾는다). `kind=bounded`,
  `plan=(issue comment)`.
- **architectural** — brainstorming이 spec을 `docs/superpowers/specs/`에 쓰고 이어서
  `superpowers:writing-plans`로 plan을 `docs/superpowers/plans/`에 쓴다. 둘 다 **대상 repo의 default
  브랜치에 직접 커밋·푸시**한다(문서만이라 PR을 만들지 않는다). `kind=architectural`, `plan=<repo 상대경로>`.

자식 하나가 끝날 때마다 큐 블록을 갱신한다(`read` → 해당 row 수정 → `write` → `gh issue edit`).

뒤 자식의 plan은 앞 자식의 *계획*은 알지만 *구현 결과*는 모른다. 이 어긋남은 페이즈 B의 자식 에이전트가
SDD의 ruling으로 흡수한다 — 여기서 미리 맞추려 하지 않는다.

### 1.3 실행 승인

전 자식이 끝나면 큐 블록 최종본을 보여주고 **"이대로 페이즈 B를 시작할까?"** 한 번 묻는다. 승인 뒤
페이즈 B는 사람에게 묻지 않는다. 거절이면 여기서 끝 — 큐는 epic에 남아 있으므로 나중에
`/epic-drain <epic#>`로 이어간다(§3).

## 2. 페이즈 B — 실행

드라이버 = 이 세션(페이즈 A를 끝낸 세션, 또는 §3로 들어온 세션). 루프 한 바퀴 = 자식 하나. 컨텍스트에는
자식당 결과 한 줄만 남긴다 — 자식의 diff·리뷰·plan 본문을 읽지 않는다.

### 2.1 다음 자식 고르기

```bash
gh issue view "$EPIC" -R "$REPO" --json body -q .body > /tmp/epic-body.md
python3 "$QUEUE" read /tmp/epic-body.md > /tmp/rows.json
python3 "$QUEUE" state "$REPO" /tmp/rows.json > /tmp/state.json
python3 "$QUEUE" next /tmp/rows.json /tmp/state.json > /tmp/next.json
```

`next`가 `null`이면 §2.5로. `skipped`에 새로 들어온 자식이 있으면 그 이슈에 코멘트
`<!-- epic-drain:result failed -->` + "skipped: `<reason>`"을 남겨 다음 바퀴에 다시 고르지 않게 한다.

### 2.2 격리 + 스폰

`orca skills get orca-cli`가 정의하는 현재 문법으로: 이름이 `task-<N>`인 Orca 추적 worktree를 만들거나(이미 있으면 그대로 재사용 — 같은 문서의 worktree 조회 명령으로 확인) → 그 worktree에 provider REPL 터미널을 **대화형으로** 만든다.
provider별 launch는 permission-bypass 플래그를 인라인으로 넣는다: claude `--dangerously-skip-permissions`,
codex `--dangerously-bypass-approvals-and-sandbox`, agy `--dangerously-skip-permissions`. model/effort는
지정하지 않는다(하네스 기본값). REPL이 idle이 될 때까지 기다린 뒤 다음으로(orca-cli 문서의 wait 구성).

### 2.3 dispatch 1회

`orca skills get orchestration`의 현재 구성(Run 생성/바인딩 → `task-create` → `worker-start`)으로
`references/child-prompt.md`를 채운 프롬프트를 한 번 보낸다. 이 세션의 Run 하나를 페이즈 B 내내 재사용한다.

### 2.4 대기 → 기록

`worker_done` 또는 `escalation`을 orchestration 문서의 wait 구성으로 5~10분 단위 bounded stretch로 기다린다.
재시도·복구 루프는 없다:

| 관측 | 처리 |
|---|---|
| `worker_done` (payload 첫 줄이 `merged #<PR>` / `pr-open: <사유>` / `failed: <사유>`) | 그 줄을 자식 이슈 코멘트로(첫 줄 `<!-- epic-drain:result <status> -->`). merged면 터미널 종료, pr-open/failed면 터미널·worktree·PR 보존(사람이 이어서 볼 수 있게) |
| `escalation` | `failed: escalation — <내용>` 코멘트, 터미널·worktree·PR 보존 |
| 누적 대기 3시간 초과 / 터미널 사망(`orca terminal` 조회 실패) | `failed: timeout|terminal dead` 코멘트, 보존 |

기록 후 §2.1로 돌아간다(의존 자식 skip은 `next`가 계산한다).

### 2.5 종료

큐에 고를 자식이 없으면 epic에 요약 코멘트 — 자식별 `merged/pr-open/failed/skipped/spike` + 사람이 볼 것
(열린 PR, failed 사유). 전 자식이 `merged`/`closed`/`spike`면 `gh issue close "$EPIC"`. 아니면 열어 둔다.

## 3. 재개

`/epic-drain <epic#>`를 다시 부르면:

- 큐 블록이 있으면 §1.1을 건너뛴다. `kind`가 비었거나, `architectural`인데 `plan` 파일이 repo에 없는
  자식만 §1.2를 다시 탄다. 그 외 자식은 §1.3 승인만 다시 받고 §2로.
- §2.1의 `state`가 `merged`/`closed`/`spike`인 자식은 자동으로 건너뛴다. `failed`/`pr-open`인 자식은 사람에게
  "재시도 / 그대로 둠" 한 번 묻는다 — 재시도면 그 이슈에 `<!-- epic-drain:result retry -->`가 아니라
  새 코멘트 없이 상태를 `pending`으로 취급하도록, 이전 결과 코멘트를 **편집**해 마커를 지운다(`gh api`
  PATCH). 그대로 두면 그 자식과 의존 자식은 이번 실행에서 빠진다.
- 이전 실행의 Orca 터미널·Run은 재사용하지 않는다. worktree(`task-<N>`)는 재사용한다.

## 4. 에러 처리

| 상황 | 처리 |
|---|---|
| `orca status` 불가 | 페이즈 A만 수행, 페이즈 B 진입 전에 멈추고 보고 |
| worktree 생성 실패 / 터미널 스폰 실패 | 그 자식 `failed: spawn — <메시지>` 코멘트, 다음 자식 |
| `gh` 호출 실패 | 그 자식은 `pending`으로 보고 다음 바퀴에 재시도(헬퍼가 stderr에 남김) |
| 드라이버 세션 크래시 | 상태는 GitHub에 있다 — §3 |
| 자식이 사람 질문을 올림(ask) | 답하지 않는다. SDD의 4가지 stop 조건은 `escalation`으로 오므로 그 경로로 처리 |
