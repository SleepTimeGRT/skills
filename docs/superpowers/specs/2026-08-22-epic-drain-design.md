# epic-drain: epic 자식 이슈를 superpowers로 일괄 계획 → provider별 자식 에이전트로 순차 구현·머지

2026-08-22. ADR 0002로 orca 파이프라인을 은퇴시킨 뒤, 사용자가 실제로 반복하는 루프 —
"처리할 이슈를 epic으로 묶고 → 순서 정하고 → worktree 만들고 → superpowers로 구현 → PR 리뷰 → 머지"
— 를 감싸는 새 스킬. 사람이 꼭 필요한 지점(brainstorming 의사결정)을 세션 앞부분에 모으고, 나머지
(worktree→구현→PR→머지)는 자식마다 **별도 에이전트 프로세스**로 무인 실행한다.

## 목표·비목표

**목표**
- 사람은 페이즈 A(계획)에만 붙어 있고, 페이즈 B(실행)는 자리를 비워도 끝까지 간다.
- 자식 이슈마다 fresh 컨텍스트의 에이전트가 뜨고 진다 — 드라이버 세션 컨텍스트는 자식당 몇 줄.
- 자식 에이전트의 provider(claude/codex/agy)를 자식별로 고를 수 있다 — 목적은 구독·레이트리밋
  풀 분산(토큰 효율)이지 품질 비교가 아니다.
- 구현·리뷰 방법은 전부 superpowers 것을 재사용한다(brainstorming, writing-plans,
  subagent-driven-development, using-git-worktrees). 자체 리뷰어·계약·로깅을 만들지 않는다.

**비목표(만들지 않음)**
- contract 협상·라운드·override, self-recovery 대기 루프, 로깅 스키마·retro, provider 선택 휴리스틱·
  폴백·헬스체크, Jira, Claude Code 외 하네스에서 페이즈 A 실행.

## 입력·전제

- 호출: `/epic-drain <epic#>` 또는 `/epic-drain <issue#> [<issue#> …]`. 후자는 epic 이슈를 새로 만들어
  자식으로 묶을지 먼저 묻고, 승인 시 만든다(본문: 자식 체크리스트).
- 트래커: GitHub Issues(`gh`). 대상 repo = 현재 cwd의 repo. epic의 자식 = epic 본문에서 참조된
  이슈(`#N`, 체크리스트, 또는 `gh`의 sub-issue API — 구현 시 둘 다 읽는다) 중 **열린 것**.
- 페이즈 A는 Claude Code 세션(superpowers 플러그인 + Agent tool). 페이즈 B의 자식은 Orca 터미널 안의
  대화형 REPL(claude/codex/agy) — 각 하네스에 superpowers가 설치돼 있어야 한다(현재 머신은 설치됨,
  사용자 확인).
- Orca: `orca status --json` ready, orchestration 기능 활성. Orca 관련 명령 문법은 실행 시점에
  `orca skills get orca-cli` / `orca skills get orchestration`에서 읽는다 — 이 스킬에 복제하지 않는다.

## 상태 정본

파일·로그를 새로 만들지 않는다. 상태는 전부 이미 있는 곳에 있다:

| 상태 | 정본 |
|---|---|
| 자식 목록·순서·의존·provider | epic 이슈 본문의 **실행 큐 블록**(아래 형식) |
| 자식의 계획 | 대상 repo `docs/superpowers/specs/`, `docs/superpowers/plans/`(architectural) 또는 이슈 코멘트의 합의(bounded) |
| 자식의 진행 | 이슈 상태(open/closed), 해당 PR 상태(open/merged), 이슈 코멘트 |
| 자식의 실행 결과 | 드라이버가 이슈에 남기는 결과 코멘트 + 최종 요약 코멘트(epic) |

실행 큐 블록(epic 본문, 페이즈 A가 쓰고 페이즈 B가 읽는다):

```
<!-- epic-drain:queue -->
| order | issue | kind | depends_on | provider | plan |
|---|---|---|---|---|---|
| 1 | #85 | architectural | — | claude | docs/superpowers/plans/2026-08-22-subscription-tests.md |
| 2 | #86 | bounded | #85 | codex | (issue comment) |
| 3 | #87 | spike | — | — | — |
<!-- /epic-drain:queue -->
```

`kind`는 brainstorming의 분류 그대로. `depends_on`은 페이즈 A에서 사람과 확정한 값(파일 겹침·선후
논리 근거를 제안하되 결정은 사람). `provider` 기본 `claude`, 사람이 자식별로 바꿀 수 있다.

## 페이즈 A — 계획 (사람 + Claude Code 세션)

1. 자식 수집 → 본문 읽고 **순서·의존 제안**(근거 한 줄씩) → 사람 확정 → 큐 블록 초안을 epic 본문에 쓴다
   (provider는 전부 `claude`로 시작, 사람이 여기서 바꾼다).
2. 자식마다 순서대로 `superpowers:brainstorming`을 **실제로 호출**한다. 입력: 이슈 원문 + 앞 자식들의
   확정 plan 요약(의존 관계가 있으면 해당 plan 전문). 분류별 산출물:
   - **spike**: 조사해서 결과를 이슈 코멘트로. 큐에서 `kind=spike`, 페이즈 B 제외. 이슈는 사람이 닫는다.
   - **bounded**: 짧은 합의를 이슈 코멘트(`<!-- epic-drain:agreement -->` 마커)로 기록. plan 문서 없음.
   - **architectural**: spec → `superpowers:writing-plans` → plan. 둘 다 대상 repo `docs/superpowers/`에
     **main에 직접 커밋·푸시**(문서만이라 PR 생략). `plan` 열에 경로.
3. 전 자식 완료 후 큐 블록을 확정 상태로 갱신하고 **실행 승인 1회**("이대로 페이즈 B 시작?")를 받는다.
   이 승인 뒤 페이즈 B에서는 사람에게 묻지 않는다.

뒤 자식의 plan은 앞 자식의 *계획*은 알지만 *구현 결과*는 모른다. 이 어긋남은 자식 에이전트의 SDD가
"rulings, not stalls"로 흡수한다(플랜과 코드가 어긋나면 ruling 기록 후 진행). 수용된 리스크.

## 페이즈 B — 실행 (드라이버 세션 + 자식 에이전트)

드라이버 = 페이즈 A를 끝낸 Claude 세션, 또는 큐가 확정된 epic에 `/epic-drain <epic#>`를 다시 부른 새
세션(재개 — 아래 "재개" 참고). 드라이버는 코드를 읽지도 쓰지도 않는다.

자식마다(큐 순서, `depends_on`이 전부 merged인 것만):

1. **격리** — `orca worktree create --name task-<N>`(Orca 추적 worktree; base는 Orca가 고르는 repo
   default 브랜치). 이미 있으면 재사용.
2. **스폰** — 그 worktree에 `provider` REPL 터미널을 대화형으로 생성(`orca-cli` 스킬 문서의 현재 문법;
   claude → `--dangerously-skip-permissions`, codex → `--dangerously-bypass-approvals-and-sandbox`, agy →
   `--dangerously-skip-permissions`. 모델/effort는 지정하지 않는다 — 각 하네스 기본값).
3. **dispatch 1회** — `orchestration` 스킬 문서의 현재 구성(Run 바인딩 → task-create → worker-start)으로
   아래 자식 프롬프트를 보낸다.
4. **대기** — `worker_done`/`escalation`을 bounded stretch(5~10분)로 기다린다. 한도(기본 3시간)
   초과·터미널 사망·escalation이면 그 자식은 **실패**: 이슈에 상황 코멘트, worktree·터미널·PR 보존,
   `depends_on`으로 걸린 자식은 skip. 재시도·복구 루프 없음 — 다음 자식으로.
5. **기록** — `worker_done`의 결과 한 줄(merged PR# / PR-open 사유 / failed 사유)을 이슈 코멘트로,
   드라이버 컨텍스트엔 같은 한 줄만. 성공 시 자식 터미널 종료.

**자식 프롬프트**(드라이버가 조립, 한 덩어리):
- 이슈 번호·원문, `kind`, plan 경로(architectural) 또는 합의 코멘트 링크(bounded), worktree 경로,
  base 브랜치.
- 할 일: architectural → `superpowers:subagent-driven-development`로 plan 실행(SDD의 final review 포함);
  bounded → implementer subagent 1회 + task-reviewer 1회(SDD의 per-task 절차만) — 둘 다
  `superpowers:using-git-worktrees`는 호출하지 않는다(이미 격리됨).
- 끝나면 `superpowers:finishing-a-development-branch`의 메뉴를 **띄우지 말고** 고정 경로: 푸시 → PR
  생성(본문에 `Closes #N`) → repo의 required check/premerge 게이트가 있으면 완료 대기 → squash merge
  → 결과 한 줄로 `worker_done` 보고. 게이트 실패·충돌·미해소 리뷰 finding이면 merge하지 않고 PR은
  열어둔 채 사유와 함께 `worker_done`.
- 사람에게 묻지 않는다(SDD의 4가지 stop 조건만 예외 — 그때는 `escalation`으로 보고하고 멈춘다).
- 하네스별 주의: agy 자식은 `agy` REPL이 과거 unfocused hang을 보인 기록이 있으므로 첫 사용은
  파일럿으로 취급한다(스킬 본문이 아니라 이 스펙의 검증 절에만 둔다).

**종료** — 큐를 다 돌면 epic에 요약 코멘트(자식별 merged/PR-open/failed/skipped/spike + 사람이 볼 것).
전 자식이 merged(또는 spike)면 epic을 닫는다. 아니면 열어둔다.

## 재개

`/epic-drain <epic#>`를 다시 부르면: 큐 블록이 있으면 페이즈 A를 건너뛴다(단 `plan`이 비어 있거나
파일이 없는 architectural 자식은 그 자식만 페이즈 A 2단계를 다시 탄다). 페이즈 B는 이슈 closed 또는 PR
merged인 자식을 건너뛰고, `failed` 코멘트가 있는 자식은 사람에게 "재시도/skip" 한 번 묻고 시작한다.
이전 실행의 Orca 터미널·Run은 재사용하지 않는다.

## 에러 처리 요약

| 상황 | 처리 |
|---|---|
| Orca 런타임 없음 | 페이즈 A만 수행 가능 — 페이즈 B 진입 시 중단하고 보고 |
| 자식 터미널 스폰 실패 | 그 자식 failed, 계속 |
| 대기 한도 초과 / 터미널 사망 | failed(보존), 의존 자식 skip |
| `escalation` 수신 | failed(사유 = escalation 내용), 의존 자식 skip |
| 자식이 PR 열고 merge 못 함 | PR-open(사유), 의존 자식 skip |
| 드라이버 세션 크래시 | 상태는 GitHub에 있음 → 재개 경로 |

## 검증

- `tests/`: 큐 블록 파서/갱신(마커 사이 표 읽기·쓰기)과 "실행 가능 자식 선택"(depends_on 평가)을
  python 스크립트로 빼서 fixture 테스트. Orca 호출·SDD는 테스트하지 않는다(문서 재사용).
- 파일럿: `studio-hevv/selah` epic #91 잔여 자식(#87~#90)으로 페이즈 A→B 1회. codex·agy 자식은 각 1회
  성공 후에 SKILL.md에 "지원"으로 표기.
- 트리거 테스트·성능 비교는 기존대로 미커버(AGENTS.md 원칙).

## 검토했으나 기각

- **페이즈 B를 같은 세션에서 SDD로 순차 실행** — 자식당 15~40k 토큰이 드라이버에 누적(추정), 10개면
  한 세션에 못 담음. 기각.
- **자식을 `claude -p`/`codex exec`/`agy -p` headless로** — 배관이 가장 적지만 headless에서 SDD의
  subagent 스폰이 미검증이고, 사용자가 대화형+Orca를 지정. 기각(claude 한정 대안으로 남김).
- **셸 스크립트 드라이버** — Orca 대화형 터미널을 쓰는 이상 `orchestration` 스킬을 아는 에이전트
  세션이 드라이버인 편이 단순. 기각.
- **자식별 interleave(brainstorm→구현→다음 brainstorm)** — plan 정확도는 높지만 사람이 매 자식마다
  돌아와야 함. 기각.
- **자식 PR을 사람이 일괄 merge** — stacked PR 문제. 기각.
