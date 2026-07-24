---
name: orca-workflow
description: Use when picking up a GitHub issue and driving it through its full lifecycle — branches on issue type (epic vs task), runs issue-drain validation for epics, builds an issue-graph task-queue, and for each task relays the orca-task-runner/orca-evaluate contract negotiation, routes PASS/FAIL/ESCALATE (and GATE_FAIL straight to inspecting), and escalates to a human inspection checkpoint. Never generates or evaluates code directly — pure orchestration, kept context-light. Use for "이슈 가져와", "이슈 처리해", "epic 실행해" style requests. Self-relative.
---

# Orca Workflow

GitHub issue 하나를 받아 끝까지(merge까지) 가져가는 최상위 오케스트레이터다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- `gh issue view <num>`으로 issue 타입 확인(label 또는 body 구조로 epic/task 판별).
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. 기본 posture는 `-a never -s workspace-write`.

## 1. Epic 경로

**1a. issue-drain** — 별도 subagent(이 세션과 다른, 별도로 뜬 세션)에게 child issue 전체 검증을 맡긴다:

- 각 child issue가 self-contained한지(`## What to build` + `## Acceptance criteria`)
- `Blocked by` / `Refs` 관계가 실제로 존재하고 방향이 맞는지
- 그래프상 빠진 child나 순환 의존이 없는지

```bash
gh issue view <epic-num> --json body,title
gh issue list --search "epic:<epic-num> in:body" --json number,title,body   # 또는 epic body에 나열된 child 번호 파싱
```

검증 실패 → 사용자에게 보고하고 멈춘다(수정 후 재호출). 통과 → **1b**.

**1b. task-queue 확정** — child issue 그래프(`Blocked by`/`Refs`/epic body 나열 순서)로 실행 순서를 정한다. file-overlap이 아니라 **issue 그래프 기준**이다(구현 전이라 파일 목록을 아직 모른다).

**1c. 순회** — ready task마다 아래 "2. Task 경로"를 실행. 완료되면 dequeue하고 의존이 풀린 다음 task로 진행. 이번 큐가 비었다고 바로 epic을 닫지 않는다 — 이번 실행 밖에서 처리된 child가 있을 수 있으므로, 닫기 전에 child 전체가 실제로 닫혀 있는지 확인한다(GitHub는 child issue 완료를 자동으로 epic에 반영하지 않으므로 이 확인·종료는 항상 명시적으로 한다):

```bash
gh issue list --search "epic:<epic-num> in:body" --json number,state -q '.[] | select(.state=="OPEN")'
# 위 출력이 비어 있을 때만(=열린 child가 없을 때만) epic을 닫는다
gh issue close <epic-num> --comment "All child tasks complete: <child-num-1>, <child-num-2>, ..."
```

## 2. Task 경로

**2a. Contract 협상 relay** — `orca-task-runner`를 "제안서 작성" 모드로 호출 → 나온 제안서 파일 경로를 `orca-evaluate`에 "검토" 모드로 전달 → 반려면 파일 경로를 다시 `orca-task-runner`에 전달. **파일 내용은 읽지 않고 경로만 중계**한다. 최대 2라운드, 그 이후는 `orca-task-runner`가 결정권을 가지고 진행(그대로 2b로 넘어감).

**"호출"의 실체**: `orca-task-runner`/`orca-evaluate`는 이 스킬(orca-workflow)과 같은 세션에서 도는 게 아니라, 각각 orchestration으로 별도 터미널을 띄워서 넘기는 것이다 — 그래야 이 스킬이 "diff나 report 본문을 직접 읽지 않는다"는 원칙이 실제로 지켜진다.

```bash
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
orca orchestration task-create --spec "<issue 번호 + 제안서/구현 모드>" --json
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 할당 로그 — 스폰하는 쪽이 남긴다. dispatch와 같은 블록에서 즉시 실행(누락 방지);
# orca 상태는 reset으로 소실될 수 있어 할당의 영속 기록은 이 파일이 유일하다.
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-workflow","role":"task-runner","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<run-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl

# evaluate 호출 — 기본 provider는 agy(Gemini): 롱컨텍스트로 agent e2e 실행·판독과 리포트 합성이
# 이 스킬의 핵심 업무라서다(`~/.agents/orca-workflows/model-selection.md`의 Computer Use / Long-Context 축,
# `skills/orca-evaluate/SKILL.md` §0 참고). 이 evaluate 세션이 diff 자체를 판단하지는 않는다 —
# 그건 evaluate가 내부에서 스폰하는 별도 code-reviewer 세션(강한 reasoning 모델)의 몫이다.
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "agy -p '<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문>' --model <token> --print-timeout 15m" --json
orca orchestration task-create --spec "<diff 또는 제안서 경로 + issue 번호 + 요청 모드>" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-workflow","role":"evaluator","issue":"<issue-num>","task_id":"<task_id>","provider":"agy","model":"<model>","effort":"","terminal":"<evaluate-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl
```

**2b. Generate** — `orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6).

**2b-1. GATE_FAIL 라우팅** — `orca-evaluate`를 호출하지 않고 바로 **3. Inspecting**으로 간다. `orca-task-runner`가 이미 자기 재시도 예산을 다 썼으므로 여기서 추가 재시도를 걸지 않는다(이중 카운팅 방지). Inspecting 보고에 "evaluate 호출 안 됨(GATE_FAIL) — 기계적 게이트 실패"를 명시해 아래 FAIL/ESCALATE와 구분한다. 이때도 §2d의 outcome 로그 라인을 `outcome:"GATE_FAIL"`로 남긴다(§2d를 거치지 않으므로 여기서 직접).

**2c. Evaluate** — (§2b가 diff 경로를 반환했을 때만) `orca-evaluate` 호출(diff 경로 전달), PASS / FAIL / ESCALATE 중 하나를 결과로 받는다.

**2d. 라우팅**:
- PASS → PR 생성/보강, merge, issue 종료(§2b가 반환하는 건 diff 경로일 뿐 PR이 아니므로 이 단계에서 처음 PR을 만들거나 기존 PR을 찾아 보강한다):

  ```bash
  # task 브랜치에 열린 PR이 있는지 확인 — 없으면 여기서 만든다(할당 로그의 worktree/branch 사용)
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  if [ -z "$pr_num" ]; then
    gh pr create --head "<task-branch>" --title "<task 제목>" --body "Closes #<task-issue-num>"
    pr_num="$(gh pr view "<task-branch>" --json number -q .number)"  # gh pr create는 URL만 출력, --json 미지원
  fi
  # 기존 PR이면 closing 키워드가 있는지 확인 — 없으면 squash merge로도 issue가 자동으로 닫히지 않는다
  gh pr view "$pr_num" --json body -q .body | grep -qiE "(closes|fixes|resolves) #<task-issue-num>" \
    || gh pr edit "$pr_num" --body "$(gh pr view "$pr_num" --json body -q .body)

  Closes #<task-issue-num>"
  gh pr merge "$pr_num" --squash --delete-branch
  # closing 키워드는 base가 default branch일 때만 자동 종료를 트리거한다(예: task PR이 epic 통합 브랜치로
  # 들어가는 구성이면 키워드가 아예 동작하지 않는다) — 그래서 아래 확인·폴백이 부수적 안전장치가 아니라
  # 실질적으로 issue를 닫는 유일한 경로일 수 있다. 상태 확인 후에도 항상 실행한다.
  [ "$(gh issue view <task-issue-num> --json state -q .state)" = "OPEN" ] \
    && gh issue close <task-issue-num> --comment "Merged via PR #$pr_num"
  ```

  task 종료.
- FAIL → 재시도 카운터 확인. **2회 미만이면** feedback과 함께 `orca-task-runner`에 재-dispatch(2b로). **2회 도달하면** inspecting으로.
- ESCALATE → 재시도 카운트 무관하게 즉시 inspecting.

라우팅 판정마다 outcome 이벤트를 할당 로그와 같은 파일에 남긴다 — `issue`/`task_id`로 assign 이벤트와 join해야 "어떤 할당이 어떤 결과를 냈는지"를 사후 감사할 수 있다(할당 기록만으로는 품질 판정 불가):

```bash
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL>","retry":<재시도 횟수>}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl
```

## 3. Inspecting

사람 체크포인트. 보고 내용: issue 번호, PASS/FAIL/ESCALATE/GATE_FAIL 중 어느 것으로 왔는지와 그 근거, 재시도 횟수, resolved providers/models. GATE_FAIL은 `orca-evaluate`가 아예 호출되지 않았다는 뜻이므로 그 사실을 반드시 표시한다. 사람이 고를 수 있는 것: 계속(피드백 반영해 재시도) / 재계획(요구사항 자체를 다시 논의 — 1a 또는 issue 수정으로 복귀) / 중단.

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-task-runner`/`orca-evaluate`의 폴백 규칙을 그대로 따르며, 이 스킬은 두 결과를 이어주는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만 대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
