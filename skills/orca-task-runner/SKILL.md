---
name: orca-task-runner
description: Use when generating the implementation for one task (issue) — proposes an implementation-and-verification contract to orca-evaluate, then fans out subtasks across Claude Code/Codex/agy terminals in dependency-ordered waves (cap 3). Subtask gates are mechanical only (typecheck/unit test/lint/format) — never an agent reviewer; task-level review belongs to orca-evaluate. Self-relative — works identically whichever provider is the coordinator.
---

# Orca Task Runner

하나의 task(issue)를 구현한다. **생성만** 한다 — 평가는 이 스킬의 책임이 아니다(`orca-evaluate`가 담당). subtask 단위 리뷰어 역할은 두지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- feature worktree에서 실행 중이어야 한다(main 체크아웃에서 금지). 워커는 전부 `--worktree active`에 생성.
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. 기본 posture는 `-a never -s workspace-write`이며, 필요한 권한이 이를 넘으면 조용히 완화하지 말고 작업 범위와 권한을 다시 확인한다.
- 모델·effort는 매 launch 전 아래 문서에서 subtask 유형(전사·기계적 / 통합·판단 / 아키텍처)에 맞게 고른다. 값을 이 스킬에 복제하지 않는다.
  - `~/.agents/orca-workflows/model-selection.md`
  - `~/.agents/orca-workflows/models/claude-code.md`
  - `~/.agents/orca-workflows/models/codex.md`
  - `~/.agents/orca-workflows/models/agy.md`

## 1. Contract 제안 (generator 역할)

`orca-workflow`가 이 task를 넘기면, 코드를 쓰기 전에 **제안서**를 먼저 쓴다:

- 구현 범위(무엇을 만들 것인가, 어떤 파일을 건드릴 것인가)
- 검증 방법(구체적인 파일/함수/테스트로 — issue의 `## Acceptance criteria`를 어떻게 커버할지)
- (schema/migration 파일을 건드리는 경우) **의도된 destructive 오퍼레이션 목록.** 없으면
  명시적으로 "없음"이라고 쓴다(공란은 "언급 안 함"이지 "없음"이 아니므로 구분한다). 이 선언은
  나중에 `orca-evaluate` §3가 diff에서 실제로 flag된 destructive-op와 대조하는 근거가 된다.

`orca-evaluate`가 이 제안을 issue의 원본 acceptance criteria에 대조해 검토한다. 반려되면 수정해서 다시 제안한다. **최대 2 라운드.** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 그 제안대로 진행한다 — evaluator의 이견은 기록에 남기되 진행을 막지 않는다.

## 2. Subtask DAG 구성

합의된 범위로 subtask를 쪼갠다. 각 subtask가 만들/수정할 파일 목록을 비교: **겹치면 `--deps` 순차 의존, 독립이면 같은 wave.** 판정이 애매하면 보수적으로 의존 처리.

```bash
orca orchestration task-create --spec "<subtask 본문 + 아래 필수 항목>" --deps '["task_xxx"]' --json
```

subtask spec 필수 항목: ①구체적 작업 내용(코드 블록 포함 그대로) ②커밋 대상 브랜치·worktree 명시 ③resolved provider/model/effort 기록 ④"막히면 ask로 blocking 질문" ⑤"완료 시 preamble 지시대로 worker_done(payload에 filesModified)" ⑥**병렬 커밋 안전 규칙**(같은 worktree를 공유하는 병렬 워커가 서로의 미완성 변경을 덮어쓰지 않도록): `git add` 명시 경로만·`git commit -m "<msg>" -- <files>` pathspec 필수·index.lock 재시도.

## 3. Wave 준비

wave 크기(**최대 3** — CPU 경합 실측 교훈)만큼 터미널. provider는 자유 선택(claude/codex/agy 아무거나, 토큰 효율을 위해 섞어도 됨) — 모델·effort는 subtask 성격에 맞게 provider 문서에서 고른다.

```bash
# claude
orca terminal create --worktree active --title task-impl-<n> \
  --command "claude --model <model> --effort <effort> --permission-mode bypassPermissions" --json
# codex
orca terminal create --worktree active --title task-impl-<n> \
  --command "codex --model <model> -c model_reasoning_effort=<effort> -s workspace-write -a never" --json
# agy
orca terminal create --worktree active --title task-impl-<n> \
  --command "agy -p '<subtask 지침>' --model <model> --print-timeout 15m" --json
orca terminal wait --terminal <impl-handle> --for tui-idle --timeout-ms 60000 --json   # agy는 --for exit --timeout-ms 960000
```

(구현자는 빌드·테스트 실행이 필요해 Bash 전체 허용 — worktree 격리가 전제. 권한 stall 발견 시 조합을 조정하고 이 스킬에 반영.)

## 4. Subtask 게이트 — 기계적인 것만

subtask가 worker_done을 보내기 전에 스스로 실행: typecheck, unit test, formatter, linter, 무거운 환경 구성이 필요 없는 script test. **subtask 단위 agent 리뷰어는 없다.** 게이트를 통과하지 못하면 worker_done을 보내지 않고 스스로 고친다.

## 5. Wave 루프

```bash
orca orchestration task-list --ready --brief --json
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # 최대 3 병렬
# 할당 로그 — dispatch와 같은 블록에서 즉시 실행(누락 방지). orca 상태는 reset으로 소실될 수 있어
# "어떤 subtask가 어떤 provider/model/effort로 갔는지"의 영속 기록은 이 파일이 유일하다.
install -d -m 700 ~/.agents/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-task-runner","role":"subtask-impl","issue":"<issue-num>","task_id":"<task_id>","subtask_type":"<전사|통합|아키텍처>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<impl_handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.agents/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.agents/orca-workflows/logs/assignments.jsonl
```

- ⚠️ **`check --wait` 단독 대기 금지**: coordinator가 Orca 터미널 내부 세션이면 worker_done이 check 큐로 안 잡힐 수 있다(task 상태는 정상 갱신됨). 기본 대기 = `task-list --brief --json` 상태 폴링 또는 커밋/파일 존재 감시(20-30s 간격), `check --wait`는 보조.
- timeout·`count:0` = 체크포인트. `terminal read`로 생사 확인, 활동 중이면 계속 대기.
- decision_gate(워커 ask) → 판단 가능하면 `reply`, 불가하면 `orca-workflow`에 에스컬레이션.
- worker_done 유실 복구: 커밋/산출물 확인 + `task-update --status completed` 수동 복구, 기록.

## 6. Task 레벨 게이트

subtask 전부가 끝나 합쳐진 task 전체 diff 기준으로, 딱 한 번 재검증한다. subtask 게이트(§4)는 같은 wave 안에서 병렬 실행되는 형제 subtask의 커밋을 놓칠 수 있어(race) — 어떤 subtask가 자기 게이트를 실행하는 시점에 같은 wave의 형제가 아직 커밋 전일 수 있다 — 그 어떤 subtask의 통과도 "task 전체가 합쳐진 뒤"를 보장하지 않는다. 이 게이트가 그 구멍을 메운다.

- typecheck / unit test / formatter / linter를 task 전체 diff 기준으로 재실행.
- e2e·pgTAP 실행(결정론적, 모델 개입 없음):

```bash
bash -lc '<repo의 e2e 커맨드> > <worktree 루트>/.gate-e2e.log 2>&1; \
  echo EXIT:$? > <worktree 루트>/.gate-e2e-summary.txt'
bash -lc '<repo의 pgTAP 커맨드, 예: pg_prove> > <worktree 루트>/.gate-pgtap.log 2>&1; \
  echo EXIT:$? > <worktree 루트>/.gate-pgtap-summary.txt; \
  grep -c "not ok" <worktree 루트>/.gate-pgtap.log >> <worktree 루트>/.gate-pgtap-summary.txt'
```

실패 시 subtask 게이트(§4)와 같은 방식으로 스스로 고치고 재시도한다. 단 subtask 게이트와 달리 **재시도 한도 2회**(무한 자가치유가 아니다 — `orca-workflow` §2d의 evaluate-FAIL 재시도 한도와 같은 숫자로 맞췄다). 2회 시도 후에도 통과 못하면 `orca-evaluate`를 호출하지 않고 `orca-workflow`에 **`GATE_FAIL`**을 직접 반환한다 — 기계적으로도 안 돌아가는 코드를 agent e2e·code review 같은 비싼 단계에 태울 이유가 없다.

## 7. 완료

Task 레벨 게이트(§6)를 통과하면 → task 전체 diff를 정리해 `orca-workflow`에 반환한다(diff 경로 + resolved providers/models + wave 구성 기록). **`orca-evaluate`는 이 스킬이 직접 호출하지 않는다** — `orca-workflow`가 호출한다. (§6에서 `GATE_FAIL`을 반환한 경우엔 diff를 넘기지 않는다 — 그 자체가 반환값이다.)

## 폴백

- orca 런타임 불가: `superpowers:subagent-driven-development`로 폴백 — 모델은 provider 문서의 같은 subtask 유형 등급을 Agent tool `model` 인자로. 폴백 발동은 사용자에게 보고.
- 폴백에서도 §5의 할당 로그는 동일하게 남긴다 — `terminal` 필드만 subagent 식별자로 대체.
