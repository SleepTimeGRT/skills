# orca-workflow 3-스킬 분리 (router / epic / task) + afk·hitl 모드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현 `orca-workflow` 단일 스킬을 coordinator 계층으로 분리한다 — `orca-workflow`(라우터+retro), `orca-workflow-epic`(큐 coordinator), `orca-workflow-task`(단일 issue coordinator, afk/hitl 모드) — "coordinator 세션 1개 = Run 1개 = issue 1개" 불변식을 성립시킨다.

**Architecture:** 분리는 복제가 아니라 composition이다. `-epic`은 §2(contract/generate/evaluate/merge) 내부를 전혀 모르고, task마다 `-task` coordinator 터미널을 **직렬로 스폰**해 {PASS, escalation outcome, 질문} 세 신호만 소비한다. `-task`는 현 orca-workflow의 §2a–§2d+§3 몸통을 §1–§5로 재번호해 갖고, 자기 issue 번호로 Run·CONTRACT_DIR를 만든다. 라우터는 이슈 타입으로 in-session 분기만 하고, invocation 종료 시 **항상** best-effort retro를 띄운다(기존 "root close 후에만" 규칙 대체 — 사용자 지시 "끝날때마다 retro").

**Tech Stack:** SKILL.md 프로즈(YAML frontmatter + markdown), orca CLI(orchestration run-create/task-create/dispatch/worker-start/check, terminal create/wait), 공유 참조 문서(`orca-workflows/*.md`), `log_dispatch.sh`/`orca_call_with_retry.sh`.

## Global Constraints

- **모드는 2개**: `afk`, `hitl`. 기본값 `hitl` (사용자 확정, 2026-08-08).
- **-epic은 §2를 모른다**: contract/generate/evaluate/merge 용어·경로·판정 로직이 `-epic` SKILL.md에 한 줄도 들어가면 안 된다.
- **coordinator 세션 1개 = Run 1개**: `-task`는 `run-<task-issue>.txt`, `-epic`은 `run-<epic-issue>.txt`, 라우터는 Run을 만들지 않는다(retro dispatch는 하위 스킬이 바인딩한 Run 상속 — 라운드 1 상속 실측과 같은 메커니즘).
- **타입 분기 금지**: 조건은 큐 구조·소속으로 표현한다(2026-08-08 커밋 90039f0의 원칙 유지). 분리 후 각 스킬 내부에는 epic/task 분기 자체가 존재하지 않아야 한다.
- **logging enum 불변**: `outcome` enum에 새 값을 추가하지 않는다. parked/skipped는 `-epic`의 §5 보고 텍스트로만 존재한다. assign 이벤트의 `role`은 per-site 자유 값이므로 `task-coordinator` 신설 가능.
- **미검증 CLI 문법 단정 금지**: ask/reply(decision gate)의 정확한 명령 문법은 SKILL.md에 지어내지 않고 "실행 시점에 `orca skills get orchestration`/`--help`로 확인"으로 지시한다(AGENTS.md "Prefer Orca's current recommended mechanism").
- **skills엔 역사 금지**: 새 파일에 "이전엔 ~였다"류 서술 금지(memory: feedback-no-history-in-skills). 이슈 번호 인용(#42 등)은 근거 앵커로 허용(기존 관례).
- **커밋은 마지막에 1회**: `orca-workflows/`는 main 심볼릭 링크라 중간 커밋이 즉시 라이브된다 — 전 파일 정합 확인 후 단일 커밋. (frequent-commit 기본을 이 이유로 오버라이드.)

## 파일 구조

| 파일 | 책임 |
|---|---|
| `skills/orca-workflow-task/SKILL.md` (신규) | issue 1건: Run·CONTRACT_DIR 생성, §1 contract relay, §2 generate, §3 evaluate, §4 라우팅(merge), §5 escalation·보고(mode 분기) |
| `skills/orca-workflow-epic/SKILL.md` (신규) | 큐: §1 issue-drain, §2 순서, §3 순회(-task 직렬 스폰), §4 root close, §5 보고 |
| `skills/orca-workflow/SKILL.md` (재작성) | §0 전제(트래커·온보딩·스윕·mode), §1 라우팅(in-session), §2 retro(항상) |
| `orca-workflows/{logging,contract-schema,dispatch-verify,self-recovery,spawn-failures,model-selection}.md` (수정) | 스킬명·섹션 번호 참조 갱신 |
| `skills/{orca-task-runner,orca-evaluate,orca-retro}/SKILL.md` (수정) | 호출자 참조 갱신 |
| `AGENTS.md` (수정) | orca-* 스킬 목록·개수 갱신 |

---

### Task 1: `skills/orca-workflow-task/SKILL.md` 작성

**Files:**
- Create: `skills/orca-workflow-task/SKILL.md`
- 원본: `skills/orca-workflow/SKILL.md` (현 HEAD = 90039f0)

**Interfaces:**
- Consumes: 없음 (첫 task).
- Produces: 섹션 번호 §0–§5 — Task 2·4·5가 이 번호로 참조한다. spec 입력 계약: `issue 번호 + mode(afk|hitl) + 대상 repo + (스폰된 경우) "보고 채널=worker_done/ask" 지시`. 반환 계약: worker_done outcome = logging.md §1 enum 값 그대로(PASS 또는 escalation류).

- [ ] **Step 1: 원본에서 이동·삭제·추가 매핑대로 새 파일 작성**

frontmatter:

```yaml
name: orca-workflow-task
description: Single-issue coordinator for one task issue — invoked in-session by `orca-workflow` (entry) or spawned as a separate coordinator terminal by `orca-workflow-epic`; invoke explicitly, do not phrase-match. Owns exactly one relay Run keyed by the issue, drives the orca-task-runner/orca-evaluate contract negotiation relay, generation, evaluation, PR/merge (merge-time verification delegated to repo CI required checks), and issue close. Mode [afk|hitl] (default hitl) governs escalation — hitl raises a blocking question to the caller/human (decision gate), afk preserves the work (worktree, CONTRACT_DIR artifacts, logs) and returns the outcome so the caller can move on. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative.
```

§0 전제 — 현 orca-workflow §0에서 다음 매핑:

| 현 §0 불릿 | 처리 |
|---|---|
| orca status ready | 유지 |
| 이슈 트래커 해석(1회) | 유지 |
| 큐 구성 | **삭제** (라우터/epic 몫) |
| Contract 디렉토리 | 유지하되 재문구: "(실행 시작 시 1회) — 이 실행이 처리하는 issue 번호로 `contract-schema.md` 규칙대로 계산·생성해 §1의 두 spec_text에 절대경로로 넣는다" (큐 언급 삭제 — 이 스킬의 큐는 항상 자기 1건) |
| 온보딩 | **삭제** (라우터 몫 — selection.md 해석 실패는 §5 escalation으로) |
| codex posture | 유지 |
| 스폰 실패 grep-first | 유지 ("§2a의 두 terminal create" → "§1의 두 `terminal create`") |
| auto-update retry 래핑 | 유지 (섹션 참조 §2a→§1) |
| MCP 인증 전제 | 유지 (§2a→§1) |
| 고착 dispatched 스윕 | **삭제** (라우터 몫) |
| Run 생성 | 유지 — `run-<issue 번호>.txt`의 issue = 자기 task issue. "orca-task-runner/orca-evaluate 내부 fan-out Run과 별개" 문단 유지. 추가 1문장: "이 세션을 `orca-workflow-epic`이 스폰했더라도 epic의 Run을 재사용하지 않는다 — coordinator 세션마다 자기 Run 1개(`orca-task-runner` §0의 같은 규칙과 동일한 이유)." |

§0에 신규 불릿 2개 추가:

```markdown
- **Mode** — spec/인자로 `afk` 또는 `hitl`을 받는다(생략 시 `hitl`). 의미는 §5가 정의한다 — §1~§4의
  동작은 mode와 무관하게 동일하다.
- **보고 채널** — spec에 "spawn된 coordinator" 지시가 있으면 최종 outcome은 `worker_done`으로, hitl
  질문은 ask(decision gate)로 호출자에게 보낸다. 그 지시가 없으면(entry 세션) 사람에게 직접 보고한다.
  ask/reply의 정확한 호출 문법은 실행 시점에 `orca skills get orchestration` 또는
  `orca orchestration --help`로 확인한다 — 여기 복제하지 않는다.
```

본문 §1–§4 — 현 §2a/§2b(+2b-1)/§2c/§2d를 그대로 이동, 내부 참조만 치환:
`§2a`→`§1`, `2b`→`§2`, `2b-1`→`§2의 GATE_FAIL 단락`, `2c`→`§3`, `§2d`/`2d`→`§4`, `"3. Inspecting"`/`§3`(Inspecting 의미)→`§5`. 코드 블록(bash) 내용·`orca_call_with_retry "orca-workflow" ...`의 첫 인자는 `"orca-workflow-task"`로 치환(로그 skill 필드). `log_dispatch --skill "orca-workflow"`도 `--skill "orca-workflow-task"`로.

§5 Escalation·보고 — 현 §3 Inspecting을 다음 구조로 확장(보고 항목 리스트·outcome별 근거 설명은 원문 그대로 유지):

```markdown
## 5. Escalation·보고

§4가 PASS로 끝나면(merge + issue close): 보고 채널로 완료를 알린다 — spawn된 세션이면
`worker_done`(outcome=PASS), entry 세션이면 사람에게 보고하고 종료.

그 외 outcome(FAIL 한도 도달·ESCALATE·GATE_FAIL·CONTRACT_ESCALATE·CI_GATE_FAIL·CI_GATE_TIMEOUT·
MERGE_CONFLICT·NO_DONE_TRANSITION)이면 아래 보고 내용을 조립한 뒤 mode로 분기한다:

[← 현 §3의 outcome별 보고 항목·근거 문단 전체를 여기 유지]

- **hitl** — 질문을 올리고 응답까지 block한다: entry 세션이면 사람에게 직접, spawn된 세션이면
  ask(decision gate)로 호출자에게(§0 보고 채널). 선택지: 계속(응답의 피드백을 반영해 §2부터 재시도 —
  사람 지시에 의한 재시도는 §4의 FAIL 재시도 한도와 별개로 센다) / 중단(아래 afk와 같은 보존 절차 후
  outcome 확정). 요구사항 자체를 다시 논의하는 재계획은 이 스킬 범위 밖이다 — issue 수정 후 재호출.
- **afk** — 질문 없이 작업을 보존하고 outcome을 확정한다. 보존 = worktree·branch를 삭제하지 않고,
  CONTRACT_DIR 산출물·eval-report·로그를 그대로 두고(전부 워크스페이스 밖 영속이라 추가 복사 없음),
  §4에서 남긴 outcome 이벤트가 기록의 정본이다. spawn된 세션이면 `worker_done`으로 outcome을 전달하고
  종료. 재개 경로는 같은 issue로의 재호출이다.
```

폴백 섹션: 원문 유지.

- [ ] **Step 2: 검증**

```bash
grep -n "§2a\|§2b\|§2c\|§2d\|2b-1\|Inspecting" skills/orca-workflow-task/SKILL.md
grep -n "epic" skills/orca-workflow-task/SKILL.md | grep -v "orca-workflow-epic"
```
기대: 둘 다 0건 — 구 섹션 번호 없음, "epic" 언급은 스킬명 `orca-workflow-epic`(frontmatter·§0 Run 불릿의 호출자 언급)만 허용. 코드 주석 "epic 순차 merge에서 후속 task의 정상 경로"는 `-epic이 직렬 호출하는 구조에서 후속 task의 정상 경로`로 재문구.

```bash
grep -c "orca_call_with_retry \"orca-workflow\"" skills/orca-workflow-task/SKILL.md   # 기대: 0
grep -n "mode\|afk\|hitl" skills/orca-workflow-task/SKILL.md | head                    # §0·§5 존재 확인
```

---

### Task 2: `skills/orca-workflow-epic/SKILL.md` 작성

**Files:**
- Create: `skills/orca-workflow-epic/SKILL.md`
- 원본(§1·§2·§4용): 현 `skills/orca-workflow/SKILL.md`의 1a·1b·1c 후반

**Interfaces:**
- Consumes: Task 1의 `-task` spec 입력 계약(issue 번호 + mode + "spawn된 coordinator" 지시)과 worker_done outcome 계약.
- Produces: §5 보고 형식(완료/parked/skipped 목록 + 큐 issue 목록) — Task 3의 retro spec이 "큐 issue 목록"으로 소비한다.

- [ ] **Step 1: 새 파일 작성**

frontmatter:

```yaml
name: orca-workflow-epic
description: Queue coordinator for an epic issue — invoked in-session by `orca-workflow`; invoke explicitly, do not phrase-match. Builds the drain queue from the epic's children (issue-drain validation + issue-graph ordering), then serially spawns one `orca-workflow-task` coordinator terminal per queued task (each task coordinator owns its own Run; this skill knows nothing about contract/generation/evaluation internals — it consumes only {PASS, escalation outcome, question} signals), forwards mode [afk|hitl] unchanged, parks afk-escalated tasks and skips their dependents while continuing with independent ready tasks, relays hitl questions to the human, closes the epic only after every child is verified closed, and reports completed/parked/skipped. Self-relative.
```

본문:

```markdown
# Orca Workflow Epic

epic issue 하나를 받아 child 큐를 만들고, task마다 `orca-workflow-task` coordinator를 직렬로 띄운다.
**task 처리 내부(contract·생성·평가·merge)를 전혀 모른다** — 이 스킬이 소비하는 신호는
{PASS, escalation outcome, 질문} 셋뿐이고, 왜 escalate했는지는 `-task`의 보고 파일·로그가 담는다.

## 0. 전제

- `orca status --json` ready. 실패 시 "폴백".
- **이슈 트래커 해석**(실행 시작 시 1회, 캐싱 없이): `~/.agents/orca-workflows/issue-trackers/selection.md`
  절차로 백엔드를 정하고 그 adapter의 오퍼레이션을 쓴다.
- **Mode** — 호출자(`orca-workflow`)로부터 `afk`|`hitl`을 받아 각 `-task` 스폰 spec에 그대로 전달한다.
  이 스킬 자신의 동작 분기는 §3의 outcome 라우팅 한 곳뿐이다.
- CLI 기반 coordinator 스폰 시 approval·sandbox 명시 — codex posture는 `models/codex.md`가 정본.
- 스폰 실패는 재진단하지 않는다 — `~/.agents/orca-workflows/spawn-failures.md` grep-first. §3의
  `terminal create`에 적용.
- 앱 자동 업데이트 재시작 대비: §3의 `orca orchestration`/`orca terminal create` 호출 전부
  `orca_call_with_retry`로 래핑(issue #42).
- **MCP 서버 인증 전제**(세션 시작 시 1회): §3에서 스폰하는 coordinator 터미널의 MCP 서버는 스폰 전에
  인증 완료 또는 비활성이어야 한다(issue #60). 막히면 spawn-failures.md의 해당 row로.
- **Run 생성**(실행 시작 시 1회): `-task` coordinator들의 `worker_done`/질문 수신용. `-task` 각각이
  만드는 자기 Run과는 별개다(coordinator 세션마다 자기 Run 1개).

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<epic 번호> task-coordinator relay" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<epic 번호>.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<epic 번호>.txt"
  ```

## 1. issue-drain

[← 현 orca-workflow 1a 본문 그대로 이동 — "큐의 issue 전체" 문구 유지, size-1 공허 통과 문장은 삭제
(이 스킬의 큐는 child들이므로 해당 없음 — 단일 task는 이 스킬에 도달하지 않는다)]

## 2. task-queue 확정

[← 현 1b 본문 그대로 이동, "size-1 큐면 순서는 자명하다" 문장 삭제]

## 3. 순회 — task마다 `orca-workflow-task` coordinator 직렬 스폰

ready task마다 아래를 실행하고, worker_done 수신 후 다음 task로 넘어간다(동시 스폰 금지 — 순차 merge
전제). 대기는 `~/.agents/orca-workflows/self-recovery.md` 루프 그대로(`check --wait --run "$RUN_ID"` +
`--ack`; task 전체 수명은 길 수 있으므로 alive면 대기를 연장하는 그 규칙에 그대로 의존한다).

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<epic 번호>.txt")"
# provider: model-selection.md 기준 — 판단·orchestration 작업. REPL 필수(one-shot은 dispatch --inject
# 수신 불가), agy 제외(models/agy.md).
orca_call_with_retry "orca-workflow-epic" "task-coordinator" -- \
  orca terminal create --worktree active --title task-coord-<task-issue-num> \
  --command "<REPL 가능, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <coord-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<orca-workflow-task SKILL.md 지침 + task issue 번호 + mode(afk|hitl) + 대상 repo + '너는 spawn된 coordinator다: 최종 outcome은 worker_done으로 보고하고, hitl 질문은 ask(decision gate)로 올려라' + worker_done을 포함해 네가 보내는 orca orchestration/orca terminal 호출은 항상 orca_call_with_retry로 감싸고(issue #42), wrapper가 exhausted를 반환하면 추가 orchestration 호출 없이 .orca-orphaned-result-<task_id>.json에 결과를 저장(커밋 금지)한 뒤 터미널에 ORPHANED_RESULT <task_id> <파일 절대경로> 한 줄을 출력하고 멈추라는 지시(orca-task-runner SKILL.md subtask spec 항목 ⑦과 동일 계약)>"
orca_call_with_retry "orca-workflow-epic" "task-coordinator" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-epic" "task-coordinator" -- \
  orca orchestration dispatch --task <task_id> --to <coord-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — dispatch-verify.md 절차. 로그 — log_dispatch가 §1 assign + §2 meta/sent를 원자 기록:
log_dispatch --skill "orca-workflow-epic" --role "task-coordinator" --issue "<task-issue-num>" \
  --task-id "<task_id>" --terminal "<coord-handle>" --worktree "<worktree 경로>" \
  --provider "<resolved provider>" --model "<resolved model>" --effort "<resolved effort>" \
  --spec-text "$spec_text"
# 이 터미널의 유일한 read는 dispatch-verify probe뿐 — recv는 기록하지 않는다(결과는 check --wait로).
```

**대기 중 질문 수신(hitl)**: `check`에 question/decision_gate 메시지가 도착하면 판단하지 않고 그대로
사람에게 보여주고, 응답을 reply로 전달한다(문법은 실행 시점 `orca skills get orchestration`으로 확인).

**outcome 라우팅** (`worker_done` 수신 후 coordinator 터미널 close):
- `PASS` → dequeue, 의존이 풀린 다음 ready task로.
- 그 외(escalation류 outcome) →
  - mode=afk: 그 task를 **parked** 목록에 기록하고, 그 task에 의존하는 후속 task 전부를 **skipped**
    목록으로 옮긴 뒤, 남은 독립 ready task로 계속한다.
  - mode=hitl: 이 outcome은 `-task`의 질문에 사람이 "중단"을 답한 결과다 — 그 자리에서 사람에게
    "다음 task 계속 / 전체 중단"을 묻고 따른다.

## 4. root close

[← 현 1c의 "root가 큐 밖의 상위 issue면" 불릿 본문 그대로 — child 전수 is_open() 확인, 전부 닫혔을
때만 close_issue. parked/skipped가 있으면 닫히지 않는 것이 정상이다.]

## 5. 보고

호출자(`orca-workflow`)에게: 완료 목록 / parked 목록(각 outcome 값) / skipped 목록(막은 선행 task) /
큐 issue 목록(retro spec용) / resolved providers·models. 이 스킬은 retro를 띄우지 않는다 — 라우터 몫.

## 폴백

[← 현 orca-workflow 폴백 섹션과 동일 문구]
```

- [ ] **Step 2: 검증**

```bash
grep -n "contract\|proposal\|verdict\|evaluate\|merge\|diff\|CONTRACT_DIR\|GATE_FAIL" skills/orca-workflow-epic/SKILL.md
```
기대: 0건 (§2 무지 확인 — "escalation outcome"이라는 추상 명칭만 허용).

---

### Task 3: `skills/orca-workflow/SKILL.md` 라우터로 재작성

**Files:**
- Modify: `skills/orca-workflow/SKILL.md` (전체 교체)

**Interfaces:**
- Consumes: Task 1·2의 스킬명과 §5 보고 형식(큐 issue 목록).
- Produces: retro 사이트(§2)의 outcome `RETRO_DONE|RETRO_FAIL` — Task 4의 logging.md 참조가 이 위치를 가리킨다.

- [ ] **Step 1: 전체 재작성**

frontmatter:

```yaml
name: orca-workflow
description: Invoke explicitly via `/orca-workflow` — do not rely on phrase-matching, which collides with Orca's built-in `orchestration` skill (multi-agent coordination, task dispatch, coordinator loops). Entry point that drives an issue (GitHub Issues or Jira, resolved per repo — see `~/.agents/orca-workflows/issue-trackers/selection.md`) through its full lifecycle: resolves the tracker (with first-run onboarding), routes the issue in-session — children present → `orca-workflow-epic`, none → `orca-workflow-task` — forwarding mode [afk|hitl] (default hitl), and after the routed run finishes, however it ended, always launches a best-effort `orca-retro` over that invocation's logs (issue set = root ∪ queue). Never generates or evaluates code directly — pure orchestration. Self-relative.
```

본문:

```markdown
# Orca Workflow

entry point 라우터다. 이슈 하나를 받아 타입을 판별해 `orca-workflow-epic`(child 있음) 또는
`orca-workflow-task`(단일 task)를 **이 세션에서** 실행하고, 끝나면 retro를 띄운다. 코드 생성·평가·
contract 내용을 모른다.

## 0. 전제

- `orca status --json` ready. 실패 시 하위 스킬의 폴백 규칙을 그대로 따르고 사용자에게 보고한다.
- **이슈 트래커 해석**(실행 시작 시 1회, 캐싱 없이): [← 현 §0 트래커 불릿 그대로]
- **온보딩**: [← 현 §0 온보딩 불릿 그대로 — 사람이 있는 entry 세션이 유일한 온보딩 지점이다]
- **고착 dispatched 스윕**(세션 시작 시 1회, report-only): [← 현 §0 스윕 불릿 그대로]
- **Mode 인자** — `afk`|`hitl`, 생략 시 `hitl`. 하위 스킬에 그대로 전달한다. 의미 정의는
  `orca-workflow-task` §5가 정본이다.
- 이 스킬은 Run을 만들지 않는다 — §2 retro의 task-create/dispatch는 하위 스킬이 이 세션에 바인딩한
  Run을 상속한다(`--run` 생략 시 호출 터미널 바인딩 상속, 실측).

## 1. 라우팅

`get_issue_type(issue-num)`/`list_children(issue-num)` — child가 있으면 `orca-workflow-epic`, 없으면
`orca-workflow-task`를 이 세션에서 로드해 그대로 따른다(별도 스폰 아님 — entry 세션이므로 두 스킬의
보고 채널은 "사람"이다). mode를 전달한다.

## 2. Retro (best-effort, invocation 종료 시 — 항상)

하위 스킬이 어떻게 끝났든(§5 보고가 완료든 parked/escalation이든) invocation 종료 시 1회 실행한다.
[← 현 1d의 나머지 본문·bash 블록 그대로 이동. spec_text의 "큐 issue 목록"은 -epic 경로면 §5 보고의
큐 목록, -task 경로면 root 1건. close 후 순서 근거 문장("coordinator가 죽으면 다 끝난 root가 열린 채
남는다")은 "close 시도가 모두 끝난 뒤에 실행한다"로 유지. "root issue가 닫히지 못하고 §3으로 끝난
실행은 retro 대상이 아니다" 문장은 **삭제**(항상 실행으로 대체). RETRO_DONE/RETRO_FAIL 로깅 블록
그대로.]

## 폴백

[← 현 폴백 섹션 그대로]
```

- [ ] **Step 2: 검증**

```bash
grep -n "§2a\|2b\|2c\|2d\|contract\|CONTRACT_DIR\|worker-start\|check --wait" skills/orca-workflow/SKILL.md
```
기대: 0건 (라우터가 §2 내용을 모름). `orca-retro` 호출 블록과 mode/온보딩/스윕만 존재.

---

### Task 4: 공유 문서 참조 갱신 (`orca-workflows/*.md`)

**Files:**
- Modify: `orca-workflows/logging.md`, `orca-workflows/contract-schema.md`, `orca-workflows/dispatch-verify.md`, `orca-workflows/self-recovery.md`, `orca-workflows/spawn-failures.md`, `orca-workflows/model-selection.md`

**Interfaces:**
- Consumes: Task 1–3의 스킬명·섹션 번호.
- Produces: 없음.

- [ ] **Step 1: 치환 목록 적용** (파일:현재행 — 정확 문자열 치환, python 스크립트로)

`logging.md`:
| 위치 | 치환 |
|---|---|
| L5 | `` `orca-task-runner`/`orca-evaluate`/`orca-workflow`, split out so the three`` → `` `orca-task-runner`/`orca-evaluate`/`orca-workflow-task`/`orca-workflow-epic`/`orca-workflow`, split out so the`` |
| L32 | `` (`orca-workflow`'s three dispatch sites — §2a's task-runner/evaluator round-1 calls and the round-2+\nrelay — `` → `` (`orca-workflow-task`'s three dispatch sites — §1's task-runner/evaluator round-1 calls and the round-2+\nrelay — and `orca-workflow-epic`'s task-coordinator site — `` |
| L59 | `` `orca-workflow` §2a의 라운드 2+ relay`` → `` `orca-workflow-task` §1의 라운드 2+ relay`` |
| L63 | `` (`orca-workflow` only — routing result for a task)`` → `` (coordinator 스킬 전용 — task 라우팅 결과는 `orca-workflow-task`, `RETRO_*`는 `orca-workflow`)`` |
| L74 | `"skill":"orca-workflow"` → `"skill":"<skill>"` + 직후 설명 1행 추가: `skill`은 기록 주체다 — task 라우팅 outcome은 `orca-workflow-task`, `RETRO_*`는 `orca-workflow`. |
| L83 | `` `orca-workflow` §1d(root issue close 직후의\nretro 사이트)`` → `` `orca-workflow` §2(invocation 종료 시의\nretro 사이트)`` |
| L89 | `(2b)` → `(orca-workflow-task §2)` |
| L92 | `retry`는 §2 하단의 → `retry`는 `orca-workflow-task` §4의 |
| L96 | `코드 생성(2b) 없이 곧장 Inspecting으로` → `코드 생성(§2 Generate) 없이 곧장 §5로`; `` (`orca-workflow` §2a의`` → `` (`orca-workflow-task` §1의`` |
| L101 | `2b(Generate)로` → `§2(Generate)로` |
| L104 | `` `skills/orca-workflow/SKILL.md` §2a가 이 분기(승인 시점, 2b로 넘어가기 전)`` → `` `skills/orca-workflow-task/SKILL.md` §1이 이 분기(승인 시점, §2로 넘어가기 전)`` |
| L121 | `` (`orca-task-runner`/`orca-workflow`, per`` → `` (`orca-task-runner`/`orca-workflow-task`/`orca-workflow-epic`, per`` |
| L127 | `# orca-workflow` → `# orca-workflow-task / orca-workflow-epic` |
| L134 | `` `orca-workflow` writes to `assignments-<date>.jsonl` (no`` → `` `orca-workflow-task`/`orca-workflow-epic` write to `assignments-<date>.jsonl` (no`` |
| L183 | `` (`orca-workflow`'s three dispatch sites`` → `` (`orca-workflow-task`'s three dispatch sites and `orca-workflow-epic`'s task-coordinator site`` |

`contract-schema.md`:
| 위치 | 치환 |
|---|---|
| L3 | `` `orca-workflow`(§2a relay, §2d FAIL relay)`` → `` `orca-workflow-task`(§1 relay, §4 FAIL relay)`` |
| L16 | `코디네이터(`orca-workflow`)가` → `코디네이터(`orca-workflow-task`)가` |
| L19 | `그 task의\n  §2a 시작 시(`orca-workflow` §0)` → `그 task의\n  §1 시작 시(`orca-workflow-task` §0)` |
| L103 | `코디네이터(`orca-workflow` §2a)가` → `코디네이터(`orca-workflow-task` §1)가` |
| L127 | `` `orca-workflow`에 반환하는 값`` → `` `orca-workflow-task`에 반환하는 값`` |

`dispatch-verify.md`: L6 스킬 목록에 `-task`/`-epic` 추가; L101 `` `orca-workflow`, "diff/report`` → `` `orca-workflow-task`, "diff/report``.

`self-recovery.md`: L5 목록 → `orca-task-runner`/`orca-workflow-task`/`orca-workflow-epic`; L29 예문 `orca-workflow`'s Run → `orca-workflow-task`'s Run; L42 `CALLING_SKILL` 허용값에 `-task`/`-epic` 추가; L97 주석 `orca-workflow omits it` → `orca-workflow-task`/`orca-workflow-epic` omit it; L115 `to orca-workflow` → `to the coordinator`; L131 `` `orca-workflow` §2d's FAIL-retry limit`` → `` `orca-workflow-task` §4's FAIL-retry limit``.

`spawn-failures.md`: L5·L74·L102의 세 스킬 나열에 `-task`/`-epic` 반영; L75 `orca-workflow SKILL.md §2a's` → `orca-workflow-task SKILL.md §1's`; L76 `(`orca-workflow` §2a round-2+ relay)` → `(`orca-workflow-task` §1 round-2+ relay)`.

`model-selection.md`: L9 owned-by 목록에 `orca-workflow-task`, `orca-workflow-epic` 추가.

- [ ] **Step 2: 검증** — Task 6 Step 1의 전역 grep이 커버(개별 grep 생략 가능).

---

### Task 5: 자매 스킬 참조 갱신

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md:57,63,180,197,241,252`
- Modify: `skills/orca-evaluate/SKILL.md:14,26,32,34,189,190`
- Modify: `skills/orca-retro/SKILL.md:3,16,100,137`

- [ ] **Step 1: 치환**

`orca-task-runner`: L57·L63 `` `orca-workflow`가 `` → `` `orca-workflow-task`가 ``; L180 에스컬레이션 대상 → `orca-workflow-task`; L197 `` `orca-workflow` 자체 relay 터미널`` → `` `orca-workflow-task` 자체 relay 터미널``; L241 `` `orca-workflow` §2d의 evaluate-FAIL 재시도 한도`` → `` `orca-workflow-task` §4의 evaluate-FAIL 재시도 한도`` (같은 행의 GATE_FAIL 반환 대상 `orca-workflow` → `orca-workflow-task`); L252 반환 대상 2곳 → `orca-workflow-task`.

`orca-evaluate`: L14 첫 문장 `` `orca-workflow`가 이 스킬을 orchestration으로 띄운다`` → `` `orca-workflow-task`가 …``; L26·L32·L34 `orca_call_with_retry "orca-workflow" "evaluator"` → `"orca-workflow-task"`; L189 괄호 안 `orca-workflow §2a가` → `orca-workflow-task §1이`; L190 `orca-workflow` 3곳 → `orca-workflow-task`.

`orca-retro`: L3 description `right after orca-workflow closes its root issue (an epic or a standalone task issue)` → `right after an orca-workflow invocation ends (retro runs regardless of how the run ended)`; 본문 L8 `방금 닫힌 root issue 실행` → `방금 끝난 orca-workflow invocation`; L16·L137 `호출자(`orca-workflow` §1d)` → `호출자(`orca-workflow` §2)`; L100 예문 `` skill="orca-workflow",\nrole="task-runner"`` → `` skill="orca-workflow-task",\nrole="task-runner"``.

- [ ] **Step 2: 검증** — Task 6 Step 1의 전역 grep이 커버.

---

### Task 6: AGENTS.md 갱신 + 전역 정합 검증 + 단일 커밋

**Files:**
- Modify: `AGENTS.md` (L~53 "the three `orca-*` skills", L80 스킬 나열)

- [ ] **Step 1: AGENTS.md 치환 후 전역 grep**

L~53: `the three `orca-*` skills` → `the `orca-*` skills`; L80: `For `orca-workflow`/`orca-task-runner`/`orca-evaluate`` → `For `orca-workflow`/`orca-workflow-epic`/`orca-workflow-task`/`orca-task-runner`/`orca-evaluate``.

```bash
# 스킬·공유 문서 전체에서 구 참조 탐지 — 결과가 남으면 각각 판정 후 치환/허용
grep -rn "orca-workflow[^s-]" skills/ orca-workflows/ AGENTS.md \
  | grep -v "orca-workflow-task\|orca-workflow-epic" \
  | grep -v "/orca-workflow\b\|orca-workflow\` 파이프라인\|orca-workflow\`)\|orca-workflow\` §2\|orca-workflow(router)"
grep -rn "§2a\|§2b\|§2c\|§2d\|§1d\|1a\b\|1b\b\|1c\b" orca-workflows/ skills/orca-task-runner skills/orca-evaluate skills/orca-retro
```
기대: 남는 참조는 전부 라우터를 정당하게 가리키는 것(retro 사이트 §2, `/orca-workflow` entry)뿐.

- [ ] **Step 2: 단일 커밋**

```bash
git add skills/orca-workflow skills/orca-workflow-task skills/orca-workflow-epic \
  skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md skills/orca-retro/SKILL.md \
  orca-workflows/ AGENTS.md docs/superpowers/plans/2026-08-08-orca-workflow-split.md
git commit -m "orca-workflow: split into router/epic/task coordinators with afk|hitl modes

- orca-workflow-task: single-issue coordinator (own Run per issue, §1-§5)
- orca-workflow-epic: queue coordinator, serially spawns task coordinators,
  knows nothing about contract/generate/evaluate internals
- orca-workflow: entry router + always-run best-effort retro at invocation end
- mode [afk|hitl] (default hitl): hitl blocks on a decision-gate question,
  afk preserves work and continues with independent ready tasks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: 배포 + playground 동기화 (선택 — 사용자 지시 시)

- [ ] `scripts/deploy-skills.sh orca-workflow orca-workflow-task orca-workflow-epic orca-retro` (커밋 후; `orca-workflows/`는 main 커밋으로 이미 라이브).
- [ ] `scratchpad/orca-workflow-playground.html`에 3-스킬 구조 반영(레이어: router/epic/task coordinator/워커 터미널/산출물; -epic→-task 스폰 edge, mode 분기 노드).

## 미해결 검증 항목 (구현이 아니라 첫 실행 시점에 확인)

1. ask/reply(decision gate)의 정확한 CLI 문법 — SKILL.md는 "실행 시점 확인"으로만 지시했다. 첫 hitl 실행에서 확인 후, 검증된 문법을 스킬에 역기입할지 그때 결정.
2. `-epic`의 task 전체 수명 대기(수 시간)가 self-recovery.md의 alive-연장 규칙으로 실제 커버되는지 — 첫 epic 실행에서 관측. 부족하면 스킬 결함 이슈로(retro 렌즈 대상).
