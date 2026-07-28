# Orca Workflow Architecture — Design

**Date**: 2026-07-22
**Status**: Approved (brainstorming phase) — pending implementation plan

## Context

`orca-review-gate`와 `orca-sdd`가 세 agent(Claude Code, Codex, agy)에 각각 중복·분기된 상태를 SSoT로 통합하는 작업에서 시작했으나, 논의 중 사용자가 실제로 원했던 것은 "issue를 pickup한 이후 처리 전체를 관리하는 오케스트레이션"이었음이 드러났다. 이 문서는 그 전체 구조를 다시 설계한다.

기존 `orca-sdd`가 해결했던 문제(superpowers의 subagent-driven-development가 Claude 서브에이전트만 spawn — 토큰 비효율)는 그대로 유지하되, 역할을 세 스킬로 분리한다.

참조: [`references/anthropic-harness-design-long-running-apps.md`](references/anthropic-harness-design-long-running-apps.md) (Anthropic Labs, "Harness design for long-running application development" — 원본은 `toss-space-goldrush/canon/_meta/references/`에 있었으나, 이 레포가 SSoT이므로 여기에 복사해왔다) — planner/generator/evaluator 3-agent 구조, sprint contract 협상, evaluator는 cross-model이 아니라 fresh-context + skeptical 튜닝이 핵심 레버라는 근거.

## Glossary

| 용어 | 정의 |
|---|---|
| issue | GitHub에 등록되는 하나의 ticket. 작업의 단위 |
| epic | issue 타입 — 여러 task를 포함 |
| task | issue 타입 — 시작과 끝이 명확한 작업 단위 |
| subtask | agent가 task를 구현할 때 내부적으로 쪼개는 작은 단위(orca-task-runner 전용, GitHub에 노출 안 됨) |

## 스킬 구조 (최종)

기존 `orca-review-gate`는 폐기하고 `orca-evaluate`에 완전히 흡수한다. `orca-sdd`는 `orca-task-runner`로 이름을 바꾸고 역할을 generate 전용으로 좁힌다.

```
orca-workflow   (top, 조율만 — 코드 생성·평가 직접 안 함)
orca-task-runner (generate — subtask fan-out, 기계적 게이트만)
orca-evaluate    (evaluate — task 1회 평가, diff 리뷰 + e2e/docker 통합)
```

`orca-review-gate`라는 이름의 별도 스킬은 더 이상 존재하지 않는다.

## 제어 흐름

```
orca-workflow(issue #N)
├─ gh issue view #N → 타입 확인
│
├─ epic
│   1. issue-drain: 별도 subagent가 child issue 전수 검증
│      (self-contained 여부, Blocked by/Refs 그래프 정합성, 빠진 child 없는지)
│      → 확정된 task-queue 산출 (순서는 issue 그래프 기준, file-overlap 아님)
│   2. 그래프 순서대로 ready task마다 아래 "task" 흐름을 반복
│   3. task 완료 시 dequeue, 의존 풀린 다음 task 진행
│
└─ task
    1. contract 협상 (orca-task-runner ↔ orca-evaluate, 파일 왕복)
    2. orca-task-runner: 합의된 범위로 subtask fan-out
    3. orca-evaluate: task 1회 평가 → PASS / FAIL+피드백 / ESCALATE
    4. FAIL → orca-task-runner 재-dispatch (최대 N=2회)
       ESCALATE 또는 N회 초과 → inspecting
    5. inspecting: 사람 체크포인트 — 계속 / 재계획(1로 복귀) / 중단
```

`orca-workflow`는 issue 상태 확인, 하위 스킬 호출, 결과 라우팅만 한다. 컨텍스트에는 task ID·상태·짧은 결과만 남긴다 — diff나 report 본문을 직접 읽지 않는다.

## Contract 협상 프로토콜

task 실행 전, "무엇을 만들지"와 "무엇으로 PASS를 판정할지"를 generator(`orca-task-runner`)와 evaluator(`orca-evaluate`)가 합의한다.

1. `orca-task-runner`가 제안서 작성: 구현 범위 + 검증 방법(구체적 파일/함수/테스트).
2. `orca-evaluate`가 issue의 원본 `## Acceptance criteria`에 대조해 검토 — **"제안이 그럴듯한가"가 아니라 "acceptance criteria를 실제로 커버하는가"로 판단**. 부족하면 반려+수정요청.
3. 최대 **2 라운드**까지 파일로 왕복. 2라운드 안에 합의 안 되면 **generator가 결정권을 가지고 그 제안대로 진행**(evaluator의 이견은 기록에 남기되 진행을 막지 않음).

evaluator가 이 단계에서 자기 검증 기준을 스스로 만드는 게 아니라, issue에 이미 독립적으로 존재하는 acceptance criteria에 앵커링하는 것이 핵심이다 — 그래야 generator의 자기평가 편향이 검증 기준 자체에 스며드는 걸 막는다.

`## Acceptance criteria`가 issue body에 없는 경우의 처리는 별도 후속 이슈로 분리한다(현재 issue 생성 지침에 이를 보장하는 절차가 없음). 임시 fallback: 없으면 `pickup-issue`와 동일하게 `/triage` 리다이렉트, 진행하지 않음.

## orca-task-runner (generate)

- contract에서 generator 역할: 제안서 작성.
- 합의된 범위로 subtask DAG 구성: 파일 목록 겹치면 순차 의존, 독립이면 같은 wave.
- wave당 최대 3개 병렬 dispatch (claude/codex/agy 중 택 — CPU 경합 실측 근거로 3 초과 금지).
  > **2026-07-28 supersede**: 데이터 재수집을 위해 상한 임시 해제.
  > 현재 정책은 skills/orca-task-runner/SKILL.md §3 참고.
- subtask 게이트는 **기계적인 것만**: typecheck, unit test, formatter, linter, 무거운 환경 구성 없는 script test. **subtask 단위 agent 리뷰어는 없다.**
- task 전체 diff를 `orca-evaluate`에 전달.

## orca-evaluate (evaluate)

- contract에서 evaluator 역할: 제안서 검토.
- task 완료 후 **1회** 평가 (subtask마다 하지 않음):
  - diff 리뷰: fresh-context 리뷰 — 같은 provider도 허용(cross-model 강제 없음), skeptical 프롬프트로 튜닝, acceptance criteria 대비 채점. (`/advisor`가 같은 provider로도 효과가 있다는 근거 채택 — cross-model은 폐기.)
  - e2e/docker 등 실제 실행 테스트.
  - 위 둘을 종합해 판정.
- 출력 3종:
  - **PASS**
  - **FAIL** — 구체적 근거 + 수정 방향 (orca-task-runner가 최대 2회까지 재시도)
  - **ESCALATE** — 기준 자체가 애매하거나 스코프 밖 발견 시, 재시도 없이 즉시 inspecting

## Epic 처리 — issue-drain

epic 실행 시작 전, 별도 subagent(coordinator나 각 task 담당자와는 다른, 별도로 뜬 세션)가 child issue 전체를 훑어 다음을 확인한다:

- 각 child issue가 self-contained한지 (What to build + Acceptance criteria)
- `Blocked by` / `Refs` 관계가 실제로 존재하고 방향이 맞는지
- 그래프상 빠진 child나 순환 의존이 없는지

이 검증을 통과해야 task-queue가 확정되고 실행이 시작된다. 실행 순서는 이 issue 그래프를 기준으로 하며, orca-task-runner의 file-overlap 기반 DAG(subtask 레벨)와는 별개다.

## 폐기/변경된 기존 설계

- **cross-model 리뷰 강제 폐기**: `orca-review-gate`가 갖고 있던 "저자 provider를 evaluator에서 제외" 규칙, provider별 evaluator 선택 표, 3-provider launch 매트릭스 전부 폐기. 이유: 최근 판단상 cross-provider 분리가 self-review 편향을 깨는 핵심 레버가 아니었고(참조 문서의 evaluator도 같은 Claude), fresh-context + skeptical 프롬프트만으로 충분한 효과가 있다는 판단(`/advisor` 사례).
- **`orca-review-gate` 스킬 자체를 폐기**하고 diff 리뷰 로직을 `orca-evaluate`에 흡수.
- **`orca-sdd` → `orca-task-runner` 이름 변경** + 역할 축소(evaluate 책임 제거).
- **subtask 단위 cross-model/agent 리뷰 폐기** — task 단위 1회 평가로 통일 (Anthropic 참조 문서의 "sprint 단위 평가가 subtask 단위보다 낫다"는 근거 채택).

## Open follow-ups (이번 설계 범위 밖)

- issue 생성 시 `## Acceptance criteria`를 보장하는 절차/지침 부재 — 별도 이슈로 분리.
- `orca-workflow`/`orca-task-runner`/`orca-evaluate`의 실제 SKILL.md 작성, 세 agent(Claude Code/Codex/agy) 배포는 이 설계의 구현 단계(별도 plan)에서 진행.
