---
name: orca-workflow-task
description: Single-issue coordinator for one task issue — invoked in-session by `orca-workflow` (entry) or spawned as a separate coordinator terminal by `orca-workflow-epic`; invoke explicitly, do not phrase-match. Owns exactly one relay Run keyed by the issue, drives the orca-task-runner/orca-evaluate contract negotiation relay, generation, evaluation, PR/merge (merge-time verification delegated to repo CI required checks), and issue close. Mode [afk|hitl] (default hitl) governs escalation — hitl raises a blocking question to the caller/human (decision gate), afk preserves the work (worktree, CONTRACT_DIR artifacts, logs) and returns the outcome so the caller can move on. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative.
---

# Orca Workflow Task

이슈 하나를 받아 끝까지(merge까지) 가져가는 단일 issue coordinator다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- **이슈 트래커 해석** (실행 시작 시 1회, 캐싱 없이 — 매 실행마다 새로 읽는다): `~/.agents/orca-workflows/issue-trackers/selection.md`가 정의하는 절차로 백엔드를 정하고, 그 백엔드의 `~/.agents/orca-workflows/issue-trackers/{github,jira}.md`가 정의하는 오퍼레이션 중 이 스킬이 쓰는 `get_issue`(§1 evaluator spec의 issue 원문 확보)/`is_open`/`close_issue`/`link_pr_for_close`(§4)를 이후 실행에서 쓴다. 구체 값(project key, transition id 등)은 이 스킬에 복제하지 않는다 — 항상 selection.md가 가리키는 대상 repo의 tracker 문서에서 얻는다.
- **Contract 디렉토리**(실행 시작 시 1회) — 이 실행이 처리하는 issue 번호로
  `~/.agents/orca-workflows/contract-schema.md` 규칙대로 `CONTRACT_DIR`를 계산·생성(`install -d -m 700`)해
  §1의 두 spec_text에 절대경로로 넣는다. acceptance criteria는 issue 본문의 사전 섹션이 아니라 §1
  협상에서 초안·승인된다 — 산출물 파일(proposal/verdict/override)과 확정 AC의 정본 위치는 같은
  문서가 정의한다.
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. codex posture는 `--dangerously-bypass-approvals-and-sandbox` — 근거·예외(headless read-only 등)는 `~/.agents/orca-workflows/models/codex.md`가 정본이다. 안전 전제는 워크트리 격리다.
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §1의 두 `terminal create` 호출
  모두에 적용된다.
- 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature:
  `~/.agents/orca-workflows/spawn-failures.md`, issue #42), §1의 `orca orchestration`/
  `orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
  후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
- **orphan-폴백 계약** — §1의 세 spec_text가 공통으로 포함하는 지시문. 각 spec 조립 시 아래 문구를
  전문 그대로 삽입한다(`orca-task-runner` SKILL.md subtask spec 항목 ⑦과 동일 계약):
  "worker_done을 포함해 네가 보내는 orca orchestration/orca terminal 호출은 항상
  orca_call_with_retry로 감싸고(issue #42), wrapper가 exhausted를 반환하면 ask를 포함한 추가
  orchestration 호출을 시도하지 말고(같은 죽은 transport) 즉시 사람에게 알리지 말고
  .orca-orphaned-result-<task_id>.json에 결과를 저장(커밋 금지)한 뒤 터미널에
  ORPHANED_RESULT <task_id> <파일 절대경로> 한 줄을 출력하고 멈춰라."
- **MCP 서버 인증 전제**(세션 시작 시 1회 확인) — §1에서 스폰하는 워커/평가자 터미널이 쓰는 MCP 서버
  (예: Context7)는 스폰 전에 이미 인증이 끝나 있거나, 그 프로필에서 비활성화돼 있어야 한다. 로그인
  프롬프트가 스폰된 세션을 막으면 주입된 spec이 처리되지 않고 사람이 직접 ESC로 해제해야 한다 —
  dispatch spec마다 "로그인 프롬프트 뜨면 익명으로 계속"류 문구를 즉석으로 덧붙이는 방식은 막지
  못하는 것이 실측됐다(4회 스폰 중 2회 여전히 블록). 막히면 재진단 없이
  `~/.agents/orca-workflows/spawn-failures.md`의 해당 row로(issue #60).
- **Run 생성**(실행 시작 시 1회): Run을 만들고 바인딩한 뒤 `run_id`를 사이드카 파일에 남긴다(§1의
  라운드 2+ relay 코드 블록은 별도 fenced block이라 셸 변수가 그대로 넘어가지 않는다):

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<issue 번호> contract round relay" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt"
  ```

  이후 §1 라운드 2+ relay의 모든 `worker-start`/`check --wait`/`--ack` 호출 앞에서
  `RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt")"`로 다시 읽는다 —
  `orca-task-runner`/`orca-evaluate`가 각자 내부 fan-out에 쓰는 Run과는 별개다(섞이면 서로 다른
  세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md`
  참고). 라운드 1의 `task-create`/`dispatch`(§1 상단)는 `--run`을 명시하지 않지만, `task-create`가
  `--run` 생략 시 호출 터미널에 바인딩된 Run을 그대로 물려받는 것으로 실측 확인했다(`--run` 없이 만든
  task의 `.run_id`가 이미 바인딩돼 있던 Run과 일치) — 따라서 라운드 2+의 `check --wait --run "$RUN_ID"`와
  `task-list --run "$RUN_ID"`는 라운드 1의 결과도 정상적으로 찾는다. 이 세션을 `orca-workflow-epic`이 스폰했더라도 epic의 Run을 재사용하지 않는다 — coordinator 세션마다 자기 Run 1개(`orca-task-runner` §0의 같은 규칙과 동일한 이유).
- **Mode** — spec/인자로 `afk` 또는 `hitl`을 받는다(생략 시 `hitl`). 의미는 §5가 정의한다 — §1~§4의
  동작은 mode와 무관하게 동일하다.
- **보고 채널** — spec에 "spawn된 coordinator" 지시가 있으면 최종 outcome은 `worker_done`으로, hitl
  질문은 ask(decision gate)로 호출자에게 보낸다. 그 지시가 없으면(entry 세션) 사람에게 직접 보고한다.
  ask/reply의 정확한 호출 문법은 실행 시점에 `orca skills get orchestration` 또는
  `orca orchestration --help`로 확인한다 — 여기 복제하지 않는다.

## 1. Contract 협상 relay

`orca-task-runner`를 "제안서 작성" 모드로 호출(제안서 = `contract-schema.md` 스키마의 `proposal-r<n>.json`, **AC 초안 포함**) → `orca-evaluate`에 "검토" 모드로 전달(판정 = `verdict-r<n>.json`) → 반려면 다시 `orca-task-runner`에 전달. 산출물 경로는 §0의 `CONTRACT_DIR`와 라운드 번호로 결정론적이므로 **이 스킬은 파일을 읽지도, 경로를 추출하지도 않고 CONTRACT_DIR·라운드 번호만 중계**한다. 최대 2라운드, 그 이후는 `orca-task-runner`가 결정권을 가질 수 있다(`override.json` 존재가 그 기록이다) — 단 무조건 §2로 가는 것이 아니다. **라운드 한도 도달 시점에** — §2로 넘어가기 전에 — 다음 기계적 분기를 먼저 태운다(구조 필드 1개 추출이라 "diff/report 본문을 읽지 않는다" 원칙과 충돌하지 않는다 — dispatch-verify의 불투명 비교와 같은 결):

```bash
if [ ! -f "<CONTRACT_DIR>/override.json" ]; then
  # 라운드 한도에 도달했는데 override.json이 없다 — generator가 §1의 기록 계약을 어긴 것.
  # 기록 없는 진행을 허용하지 않는다(fail-closed): outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif jq -e '[.unresolved_reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/override.json" >/dev/null; then
  # AC 자체("무엇을 만들지")에 이견이 남음 — 생성 비용을 쓰기 전에 사람에게 보낸다.
  # logging.md §1 outcome 레시피대로 outcome=CONTRACT_ESCALATE, round=<도달한 라운드 수>를 남기고
  # §2 없이 곧장 §5로.
else
  # plan_coverage 이견만 남음 — 검증 방법 이견은 §3 리뷰·e2e가 최종 AC 기준으로 재검증하므로 진행.
  # logging.md §1 outcome 레시피대로 outcome=CONTRACT_FINALIZED_BY_GENERATOR,
  # round=<도달한 라운드 수>를 남기고 §2로 (issue #63).
fi
```

**계약이 승인된 시점에도(몇 라운드에서 승인되든)** — 마찬가지로 §2로 넘어가기 전에 — 같은 레시피대로 `outcome=CONTRACT_APPROVED, round=<승인된 라운드 수>`를 남긴다(issue #69, #86).

**"호출"의 실체**: `orca-task-runner`/`orca-evaluate`는 이 스킬(orca-workflow-task)과 같은 세션에서 도는 게 아니라, 각각 orchestration으로 별도 터미널을 띄워서 넘기는 것이다 — 그래야 이 스킬이 "diff나 report 본문을 직접 읽지 않는다"는 원칙이 실제로 지켜진다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
spec_text="<issue 번호 + CONTRACT_DIR 절대경로 + 제안서/구현 모드(제안서 모드면: contract-schema.md 스키마대로 AC 초안을 포함한 proposal-r<라운드>.json을 CONTRACT_DIR에 작성) + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca orchestration dispatch --task <task_id> --to <run-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58 — "diff/report
# 본문을 직접 읽지 않는다" 원칙과 충돌하지 않는 근거도 그 문서에 있다).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 터미널에 대한 유일한 read는 위 dispatch-verify.md의 liveness probe(불투명 payload-echo 확인 —
#   issue #58)뿐이므로 recv는 기록하지 않는다(logging.md의 carve-out 규칙 — 실제
#   결과는 이 스킬이 직접 읽지 않고 다른 채널로 도착한다). term-<run-handle>.jsonl은 orca-workflow-task
#   자신이 소유하는 파일이다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들에
#   이미 남는다.
log_dispatch --skill "orca-workflow-task" --role "task-runner" --issue "<issue-num>" --task-id "<task_id>" \
  --terminal "<run-handle>" --worktree "<worktree 경로>" --provider "<resolved provider>" \
  --model "<resolved model>" --effort "<resolved effort>" --spec-text "$spec_text"

# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (사유는 `~/.agents/orca-workflows/models/agy.md`가 정본). agy는 evaluate 내부 §2(agent e2e)의
# headless sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
spec_text="<orca-evaluate SKILL.md 지침 + CONTRACT_DIR 절대경로와 대상 라운드 번호(검토 대상 proposal-r<n>.json·판정 산출 verdict-r<n>.json — 스키마·적대적 판정 지침·라운드 2 입력 격리 규칙은 contract-schema.md) + issue 원문 + issue 번호 + 요청 모드 + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration dispatch --task <task_id> --to <evaluate-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 터미널에 대한 유일한 read도 마찬가지로 dispatch-verify.md의 liveness probe뿐이라
#   recv는 기록하지 않는다(위 task-runner 사이트와 같은 이유).
log_dispatch --skill "orca-workflow-task" --role "evaluator" --issue "<issue-num>" --task-id "<task_id>" \
  --terminal "<evaluate-handle>" --worktree "<worktree 경로>" --provider "<resolved provider>" \
  --model "<resolved model>" --effort "<resolved effort>" --spec-text "$spec_text"
```

**Contract 협상 relay — 라운드 2+ (반려된 경우만; 승인이면 곧장 §2)**: 라운드 1과 같은 task_id를 재사용하지
않는다 — `dispatch`는 이미 `dispatched`/`completed` 상태인 task를 거부하고(`"Task ... is dispatched; only ready tasks can be dispatched"`, 실측), 애초에 텍스트를 override하는 인자가 없어 재사용해도 라운드 1과 같은
spec만 재전송된다. 대신 매 라운드 새 task를 만들어 같은 터미널(재-engage 대상은 task-runner면
`<run-handle>`, evaluator면 `<evaluate-handle>`)에 재-dispatch한다 — 단 그 터미널의 직전 dispatch가
`completed` 상태여야 한다(그렇지 않으면 `"Terminal ... already has an active dispatch"`로 거부됨, 실측).
`--deps`는 걸지 않는다 — 걸어도 `dispatch` 자체가 이미 같은 선후관계를 강제하므로 stall 경로만 하나 늘어난다.

직전 라운드가 `completed`인지 확인하는 대기는 `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery
루프를 그대로 따른다(`check --wait`+`--ack`, 타임아웃 시 alive/stuck_draft/dead 분기) — 이 dispatch에 대한
`worker_done`을 `check`/`check --wait`로 수신하는 것 자체가 곧 `completed` 확정이다(실측: 완료 시각이
메시지 타임스탬프와 정확히 일치). 산출물 경로는 `CONTRACT_DIR`와 라운드
번호로 결정론적이므로 `worker_done` 수신 후 `.result`/`reportPath` 파싱을 위한 추가 조회는 하지
않는다 — 반려 사유도 이 스킬이 요약해 넘기지 않는다(generator가 `verdict-r<n>.json`을 직접 읽는다):

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt")"   # §0에서 남긴 사이드카
spec_text="<round 번호 + CONTRACT_DIR 절대경로(파일명은 contract-schema.md 컨벤션으로 결정론적 — task-runner행이면 직전 verdict-r<n-1>.json을 읽고 proposal-r<n>.json 작성, evaluator행이면 라운드 2 입력 격리 규칙대로 원본 issue·proposal-r<n>.json·자신의 직전 verdict만 입력) + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "contract-round" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree current \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(worker-start에도 동일하게 필요).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 사이트도 recv는 기록하지 않는다(위 두 사이트와 같은 이유 — 결과는 check --wait으로 수신).
log_dispatch --skill "orca-workflow-task" --role "contract-round" --issue "<issue-num>" \
  --task-id "<방금 만든 task_id>" --terminal "<재-engage 대상 handle>" --worktree "<worktree 경로>" \
  --provider "<라운드 1에서 resolve한 provider — 재-resolve 없이 재사용>" \
  --model "<라운드 1에서 resolve한 model — 재사용>" --effort "<라운드 1에서 resolve한 effort — 재사용>" \
  --spec-text "$spec_text"
```

- self-recovery.md의 재시도 예산까지 소진해도(최초 대기 1회 + `worker_abandon_retry` 최대 2회, 각
  최대 1시간 — 최악의 경우 약 3시간) `completed`가 안 되면 체크포인트 — 재진단하지 않고
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차로.

## 2. Generate

`orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6). §4의 FAIL 재시도로 돌아온 호출이면 spec에 직전 attempt 번호를 넣는다 — generator가 `CONTRACT_DIR`의 `eval-report-a<attempt>.json`을 직접 읽는다(이 스킬은 feedback 본문을 중계하지 않는다).

**GATE_FAIL 라우팅** — `orca-evaluate`를 호출하지 않고 바로 §5로 간다. `orca-task-runner`가 이미 자기 재시도 예산을 다 썼으므로 여기서 추가 재시도를 걸지 않는다(이중 카운팅 방지). §5 보고에 "evaluate 호출 안 됨(GATE_FAIL) — 기계적 게이트 실패"를 명시해 아래 FAIL/ESCALATE와 구분한다. 이때도 §4의 outcome 로그 라인을 `outcome:"GATE_FAIL"`로 남긴다(§4를 거치지 않으므로 여기서 직접).

## 3. Evaluate

(§2가 diff 경로를 반환했을 때만) `orca-evaluate` 호출(diff 경로 + attempt 번호 전달 — attempt는 1부터, FAIL 재시도마다 +1), PASS / FAIL / ESCALATE 중 하나를 결과로 받는다. evaluator는 판정을 `CONTRACT_DIR`의 `eval-report-a<attempt>.json`으로도 남긴다(스키마는 `contract-schema.md` — 이 스킬은 그 파일을 읽지 않는다).

## 4. 라우팅

- PASS → PR 생성/보강, merge, issue 종료(§2가 반환하는 건 diff 경로일 뿐 PR이 아니므로 이 단계에서 처음 PR을 만들거나 기존 PR을 찾아 보강한다):

  ```bash
  # task 브랜치에 열린 PR이 있는지 확인 — 없으면 여기서 만든다(할당 로그의 worktree/branch 사용)
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  if [ -z "$pr_num" ]; then
    gh pr create --head "<task-branch>" --title "<task 제목>" --body "<task 설명 — 트래커별 텍스트는 아래 link_pr_for_close가 처리하므로 여기선 안 넣는다>"
    pr_num="$(gh pr view "<task-branch>" --json number -q .number)"  # gh pr create는 URL만 출력, --json 미지원
  fi
  ```

  PR이 확보되면(신규든 기존이든) **`link_pr_for_close(pr_num, task-issue-num)`를 호출**한다 — 이건 질의가 아니라
  액션이다: GitHub adapter는 그 안에서 "Closes #N" 키워드 존재를 확인·보강하고, Jira adapter는 아무것도 안
  한다(no-op, merge-magic 없음). 그 구체 로직(grep 패턴, 키워드 문자열 등)은 각 adapter 파일이 소유하므로
  `orca-workflow-task`는 어느 백엔드인지 몰라도 되고 그 로직을 여기 복제하지 않는다.

  ```bash
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  # merge — stale-main·게이트-무결성 검증은 이 스킬이 하지 않는다:
  # 그 검증은 대상 repo의 CI required check(e2e gate)와 branch protection 설정(required check 지정 +
  # "Require branches to be up to date" 또는 merge queue) 몫이다. 그 설정이 없는 repo에서는 이 merge가
  # 추가 검증 없이 통과한다 — 이 스킬이 임의로 로컬 게이트를 되살리지 않는다.
  # 아래 루프는 required check가 있는 repo에서 merge가 거부되는 경우의 bounded 처리다. 재시작 안전:
  # budget 기준 시각은 로컬 변수가 아니라 파일의 벽시계 값이다(#72 — harness의 단일 명령 타임아웃/
  # 무출력 kill로 이 블록이 도중에 죽어도, 그대로 다시 실행해 벽시계 기준으로 이어받는다).
  merge_started_file="${TMPDIR:-/tmp}/merge-<issue-num>.started"
  [ -f "$merge_started_file" ] || date -u +%s > "$merge_started_file"
  merge_budget=1800   # CI e2e 완주까지 기다릴 수 있는 예산
  merged=false; merge_outcome=""
  while :; do
    if gh pr merge "$pr_num" --squash --delete-branch; then merged=true; break; fi
    state="$(gh pr view "$pr_num" --json mergeStateStatus -q .mergeStateStatus)"
    if [ "$state" = "DIRTY" ]; then
      merge_outcome=MERGE_CONFLICT; break        # base와 텍스트 충돌 — 자동 해소하지 않는다
    elif [ "$state" = "BEHIND" ]; then
      # base가 전진 + up-to-date 강제 설정(orca-workflow-epic이 직렬 호출하는 구조에서 후속 task의 정상
      # 경로) — 브랜치를 갱신하고 CI 재실행을 기다린다. 갱신 자체가 실패하면(충돌) 사람 몫이다.
      gh pr update-branch "$pr_num" || { merge_outcome=MERGE_CONFLICT; break; }
    fi
    if gh pr view "$pr_num" --json statusCheckRollup -q '.statusCheckRollup[] | (.conclusion // .state)' \
        | grep -qiE 'failure|error|timed_out|cancelled|action_required'; then
      merge_outcome=CI_GATE_FAIL; break          # required check 실패 확정
    fi
    merge_elapsed=$(( $(date -u +%s) - $(cat "$merge_started_file") ))
    printf 'merge poll: %ss/%ss elapsed (state=%s)\n' "$merge_elapsed" "$merge_budget" "$state"
    [ "$merge_elapsed" -ge "$merge_budget" ] && { merge_outcome=CI_GATE_TIMEOUT; break; }
    sleep 30
  done
  rm -f "$merge_started_file"   # 어느 분기로 끝나든 회수
  # merge_outcome이 비어있지 않으면 merge되지 않은 것이다 — logging.md §1 outcome 레시피대로 그 값을
  # 남기고(GATE_FAIL과 같은 원칙: 추가 재시도 없이) 바로 §5로 분기한다. printf가 남긴
  # 마지막 state와 실패 check 이름·링크(gh pr checks "$pr_num")를 §5 보고에 첨부한다.
  ```

  머지 성공 시(`merged=true`) **`is_open(task-issue-num)`이 true면 `close_issue(task-issue-num, "Merged via PR #$pr_num")`를 호출**한다 — 코드호스팅(PR 머지)은 GitHub 전용이라 미변경이고, issue 종료는 트래커 무관하게 이 한 경로로 처리된다: GitHub는 위 `link_pr_for_close`가 보통 이미 닫아둬서 여기선 안전망(no-op)이고, Jira 등 merge-magic이 없는 트래커는 이 호출이 유일한 종료 경로다. (`is_open`/`close_issue`/`link_pr_for_close`는 실제 셸 커맨드가 아니라 tracker adapter 오퍼레이션이다 — 문자 그대로 셸에 붙여넣지 말 것.) `close_issue`가 "완료" transition을 찾지 못하면 그 시점에서 `outcome=NO_DONE_TRANSITION`을 직접 로깅하고 §5로 간다.

  task 종료(`merge_outcome`이 남은 경우는 예외 — 아래 CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT 참고, task 종료가 아니라 §5로 간다).
- FAIL → 재시도 카운터 확인. **2회 미만이면** `orca-task-runner`에 재-dispatch(§2로 — spec에 방금 FAIL한 attempt 번호만 넣는다; feedback 정본은 `eval-report-a<attempt>.json`이고 generator가 직접 읽는다, §1 라운드 2+ relay와 같은 원칙). **2회 도달하면** §5로.
- ESCALATE → 재시도 카운트 무관하게 즉시 §5.
- CI_GATE_FAIL → (PASS 라우팅 안에서만 발생 — 위 참고) repo의 CI required check 실패 확정 — 추가 재시도
  없이 즉시 §5. `orca-evaluate`는 이미 PASS를 냈으므로 재-dispatch 대상이 아니다 — merge 앞
  게이트가 별도로 막은 것.
- CI_GATE_TIMEOUT → (같은 위치) budget 안에 required check가 완주하지 못했거나 merge 거부 원인이
  판별되지 않았다는 뜻이다(코드 실패로 확정된 것이 아니다) — 추가 재시도 없이 즉시 §5.
- MERGE_CONFLICT → (같은 위치) base와의 텍스트 충돌(`mergeStateStatus=DIRTY`) 또는
  `gh pr update-branch` 실패 — 자동 rebase/충돌 해소를 시도하지 않고 즉시 §5.

라우팅 판정마다 outcome 이벤트를 할당 로그와 같은 파일에 남긴다 — `issue`/`task_id`로 assign 이벤트와 join해야 "어떤 할당이 어떤 결과를 냈는지"를 사후 감사할 수 있다(할당 기록만으로는 품질 판정 불가). 로그 — `~/.agents/orca-workflows/logging.md` §1 `outcome` 레시피 그대로 실행(enum 값은 그쪽이 정본 — 여기 복제하지 않는다): `skill="orca-workflow-task"`, `issue=<issue-num>`, `outcome=<위 라우팅 분기에서 결정된 값>`, `retry=<재시도 횟수>`.

## 5. Escalation·보고

§4가 PASS로 끝나면(merge + issue close): 보고 채널로 완료를 알린다 — spawn된 세션이면
`worker_done`(outcome=PASS), entry 세션이면 사람에게 보고하고 종료.

그 외 outcome(FAIL 한도 도달·ESCALATE·GATE_FAIL·CONTRACT_ESCALATE·CI_GATE_FAIL·CI_GATE_TIMEOUT·
MERGE_CONFLICT·NO_DONE_TRANSITION)이면 아래 보고 내용을 조립한 뒤 mode로 분기한다:

보고 내용: issue 번호, PASS/FAIL/ESCALATE/GATE_FAIL/CONTRACT_ESCALATE/CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT/NO_DONE_TRANSITION 중 어느 것으로 왔는지와 그 근거, 재시도 횟수, resolved providers/models. GATE_FAIL은 `orca-evaluate`가 아예 호출되지 않았다는 뜻이므로 그 사실을 반드시 표시한다. **CONTRACT_ESCALATE**는 contract 협상이 라운드 한도에도 `ac_fidelity` 이견으로 끝났다는 뜻이다 — 코드 생성 전이므로 diff가 없다. `override.json`의 `unresolved_reasons`를 그대로 표시한다(무엇을 만들지에 대한 generator/evaluator의 이견 — 사람이 issue를 명확히 하거나 방향을 정한다). §1의 fail-closed 분기(override.json 자체가 없음)로 온 경우면 이견 내용 대신 그 사실 — generator가 기록 없이 라운드 한도에 도달함 — 을 표시한다. **CI_GATE_FAIL**은 `orca-evaluate`가 PASS를 냈는데도 repo의 CI required check가 merge를 막았다는 뜻이므로, 실패한 check 이름과 로그 링크(`gh pr checks <pr_num>`)를 그대로 표시한다 — 사람이 다시 조회하지 않게. **CI_GATE_TIMEOUT**은 budget 안에 check가 완주하지 못했거나 merge 거부 원인이 판별되지 않았다는 뜻이므로(코드 실패로 확정 아님), 마지막 `mergeStateStatus`와 check 상태 스냅샷을 표시한다. **MERGE_CONFLICT**는 base와의 충돌로 자동 merge가 불가능하다는 뜻이다 — 충돌 지점 정보를 표시하고, rebase/충돌 해소 여부는 사람이 결정한다. **NO_DONE_TRANSITION**은 tracker adapter의 `close_issue`가 "완료" transition을 찾지 못했다는 뜻이다(트래커 문서에 명시 없음, 또는 명시된 이름이 현재 상태의 available transition 목록에 없음) — 발생 지점은 §4의 merge 성공 후 close 단계이고, outcome 로깅은 그 시점에 §4가 직접 한다.

- **hitl** — 질문을 올리고 응답까지 block한다: entry 세션이면 사람에게 직접, spawn된 세션이면
  ask(decision gate)로 호출자에게(§0 보고 채널). 선택지: 계속(응답의 피드백을 반영해 §2부터 재시도 —
  사람 지시에 의한 재시도는 §4의 FAIL 재시도 한도와 별개로 센다) / 중단(아래 afk와 같은 보존 절차 후
  outcome 확정). 요구사항 자체를 다시 논의하는 재계획은 이 스킬 범위 밖이다 — issue 수정 후 재호출.
- **afk** — 질문 없이 작업을 보존하고 outcome을 확정한다. 보존 = worktree·branch를 삭제하지 않고,
  CONTRACT_DIR 산출물·eval-report·로그를 그대로 두고(전부 워크스페이스 밖 영속이라 추가 복사 없음),
  §4에서 남긴 outcome 이벤트가 기록의 정본이다. spawn된 세션이면 `worker_done`으로 outcome을 전달하고
  종료. 재개 경로는 같은 issue로의 재호출이다.

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-task-runner`/`orca-evaluate`의 폴백 규칙을 그대로 따르며, 이 스킬은 두 결과를 이어주는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만 대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
