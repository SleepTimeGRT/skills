---
name: orca-workflow-epic
description: Queue coordinator for an epic issue — invoked in-session by `orca-workflow`; invoke explicitly, do not phrase-match. Builds the drain queue from the epic's children (issue-drain validation + issue-graph ordering), then serially spawns one `orca-workflow-task` coordinator terminal per queued task (each task coordinator owns its own Run; this skill knows nothing about contract/generation/evaluation internals — it consumes only {PASS, escalation outcome, question} signals), forwards mode [afk|hitl] unchanged, parks afk-escalated tasks and skips their dependents while continuing with independent ready tasks, relays hitl questions to the human, closes the epic only after every child is verified closed, and reports completed/parked/skipped. Self-relative.
---

# Orca Workflow Epic

epic issue 하나를 받아 child 큐를 만들고, task마다 `orca-workflow-task` coordinator를 직렬로 띄운다.
**task 처리 내부를 전혀 모른다** — 이 스킬이 소비하는 신호는
{PASS, escalation outcome, 질문} 셋뿐이고, 왜 escalate했는지는 `-task`의 보고 파일·로그가 담는다.

## 0. 전제

- `orca status --json` ready. 실패 시 "폴백".
- **이슈 트래커 해석**(실행 시작 시 1회, 캐싱 없이): `~/.agents/orca-workflows/issue-trackers/selection.md`
  절차로 백엔드를 정하고 그 adapter의 오퍼레이션을 쓴다.
- **Mode** — 호출자(`orca-workflow`)로부터 `afk`|`hitl`을 받아 각 `-task` 스폰 spec에 그대로 전달한다.
  이 스킬 자신의 동작 분기는 §3의 outcome 라우팅 한 곳뿐이다.
- CLI 기반 coordinator 스폰 시 approval·sandbox 명시 — codex posture는 `models/codex.md`가 정본이다.
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
  run_json="$(orca orchestration run-create --objective "<root-num> task-coordinator relay" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<root-num>.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<root-num>.txt"
  ```

## 1. issue-drain

별도 subagent(이 세션과 다른, 별도로 뜬 세션)에게 큐의 issue 전체 검증을 맡긴다:

- 큐의 각 issue가 self-contained한지("무엇을 만들지"가 본문에 있고, 본문만으로 acceptance-criteria 초안을 쓸 수 있을 만큼 요구가 구체적인지 — AC 자체는 이 스킬 밖에서 초안된다)
- 의존 관계가 있다면(`get_child_order`가 참고하는 것과 같은 그래프) 그게 실제로 존재하고 방향이 맞는지 — 의존 링크 자체가 없는 건 실패가 아니다
- 그래프상 빠진 issue나 순환 의존이 없는지

```
get_issue(root-num)
list_children(root-num)
```

검증 실패 → 사용자에게 보고하고 멈춘다(수정 후 재호출). 통과 → **§2**.

## 2. task-queue 확정

`get_child_order(root-num, 큐)`로 실행 순서를 정한다. file-overlap이 아니라 **issue 그래프 기준**이다(구현 전이라 파일 목록을 아직 모른다).

## 3. 순회 — task마다 `orca-workflow-task` coordinator 직렬 스폰

ready task마다 아래를 실행하고, worker_done 수신 후 다음 task로 넘어간다(동시 스폰 금지 — 순차 처리
전제). 대기는 `~/.agents/orca-workflows/self-recovery.md` 루프 그대로(`check --wait --run "$RUN_ID"` +
`--ack`; task 전체 수명은 길 수 있으므로 alive면 대기를 연장하는 그 규칙에 그대로 의존한다).

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<root-num>.txt")"
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
    "다음 task 계속 / 전체 중단"을 묻고 따른다. 전체 중단을 고르면 아직 시도하지 않은 나머지 큐
    항목 전부를 **skipped** 목록에 담되, 막은 선행 task 자리에는 이 중단 사실을 적는다.

## 4. root close

큐가 비었다고 바로 root를 닫지 않는다. 이번 실행 밖에서 처리된 child가 있을 수 있으므로, 닫기 전에
child 전체가 실제로 닫혀 있는지 확인한다(child 완료가 root에 자동 반영되지 않는 tracker일 수 있으므로
이 확인·종료는 항상 명시적으로 한다):

```
list_children(root-num)의 각 항목에 is_open() 확인
# 전부 닫혀 있을 때만(=열린 child가 없을 때만) root를 닫는다
close_issue(root-num, "All child tasks complete: <child-num-1>, <child-num-2>, ...")
```

parked/skipped가 있으면 닫히지 않는 것이 정상이다.

## 5. 보고

호출자(`orca-workflow`)에게: 완료 목록 / parked 목록(각 outcome 값) / skipped 목록(막은 선행 task) /
큐 issue 목록(retro spec용) / resolved providers·models. 이 스킬은 retro를 띄우지 않는다 — 라우터 몫.

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-workflow-task`의 폴백 규칙을 그대로 따르며, 이 스킬은
  task마다 그 결과를 이어받는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만
  대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
