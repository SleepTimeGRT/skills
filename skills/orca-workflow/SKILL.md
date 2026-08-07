---
name: orca-workflow
description: Invoke explicitly via `/orca-workflow` — do not rely on phrase-matching, which collides with Orca's built-in `orchestration` skill (multi-agent coordination, task dispatch, coordinator loops). Picks up an issue (GitHub Issues or Jira, resolved per repo — see `~/.agents/orca-workflows/issue-trackers/selection.md`) and drives it through its full lifecycle — branches on issue type (epic vs task), runs issue-drain validation for epics, builds an issue-graph task-queue, and for each task relays the orca-task-runner/orca-evaluate contract negotiation, routes PASS/FAIL/ESCALATE (and GATE_FAIL straight to inspecting), and escalates to a human inspection checkpoint. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative.
---

# Orca Workflow

이슈 하나를 받아 끝까지(merge까지) 가져가는 최상위 오케스트레이터다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- **이슈 트래커 해석** (실행 시작 시 1회, 캐싱 없이 — 매 실행마다 새로 읽는다): `~/.agents/orca-workflows/issue-trackers/selection.md`가 정의하는 절차로 백엔드를 정하고, 그 백엔드의 `~/.agents/orca-workflows/issue-trackers/{github,jira}.md`가 정의하는 `get_issue`/`get_issue_type`/`list_children`/`get_child_order`/`is_open`/`close_issue`/`link_pr_for_close`를 이후 전체 실행에서 쓴다. 구체 값(project key, transition id 등)은 이 스킬에 복제하지 않는다 — 항상 selection.md가 가리키는 대상 repo의 tracker 문서에서 얻는다.
- **이슈 타입 판별** — `get_issue_type(issue-num)`으로 epic/task를 판별해 아래 "1. Epic 경로"/"2. Task 경로"로 분기한다.
- **acceptance-criteria 섹션명** — 백엔드가 resolve한 tracker 문서(`~/.agents/orca-workflows/issue-trackers/{github,jira}.md`, 또는 온보딩으로 만들어진 대상 repo 문서)가 명시하는 이름을 쓴다. 이 스킬은 그 값을 복제하지 않는다 — 아래 §1·§2a의 "§0에서 해석한 acceptance-criteria 섹션명"은 이 값을 가리킨다.
- **온보딩** — selection.md가 "문서 없음 + GitHub 형식이 아닌 이슈 ID"로 판정하면, 곧바로 GitHub로 넘어가지 않고 사용자에게 직접 묻는다: ①어떤 tracker를 쓰는지 + 그 API를 부르는 데 필요한 최소 정보(Jira라면 site·cloudId·project key) ②"완료" transition/상태 이름, acceptance-criteria 섹션 이름. 받은 답으로 `docs/agents/issue-tracker.md` 형식의 초안을 작성해 보여주고, 승인되면 별도의 작은 커밋으로 대상 repo에 반영한 뒤 이번 실행을 이어간다. 이후 실행부터는 문서가 있으므로 다시 트리거되지 않는다.
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. 기본 posture는 `-a never -s workspace-write`.
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §2a의 두 `terminal create` 호출
  모두에 적용된다.
- 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature:
  `~/.agents/orca-workflows/spawn-failures.md`, issue #42), §2a의 `orca orchestration`/
  `orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
  후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
- **MCP 서버 인증 전제**(세션 시작 시 1회 확인) — §2a에서 스폰하는 워커/평가자 터미널이 쓰는 MCP 서버
  (예: Context7)는 스폰 전에 이미 인증이 끝나 있거나, 그 프로필에서 비활성화돼 있어야 한다. 로그인
  프롬프트가 스폰된 세션을 막으면 주입된 spec이 처리되지 않고 사람이 직접 ESC로 해제해야 한다 —
  dispatch spec마다 "로그인 프롬프트 뜨면 익명으로 계속"류 문구를 즉석으로 덧붙이는 방식은 막지
  못하는 것이 실측됐다(4회 스폰 중 2회 여전히 블록). 막히면 재진단 없이
  `~/.agents/orca-workflows/spawn-failures.md`의 해당 row로(issue #60).
- **고착 dispatched 스윕(세션 시작 시 1회, report-only)**:
  `bash ~/.agents/orca-workflows/scripts/sweep_stale_dispatched.sh`를 실행해 임계(기본 1시간)를 넘긴
  `dispatched` task 목록을 확보하고, 발견되면(exit 3 — 전제 실패가 아니다, 진행은 계속한다) 사용자
  보고에 그대로 포함한다. 복구는 이 스킬이 직접 하지 않는다 — worker_done 유실 복구는
  `orca-task-runner` §5 절차(worktree의 `.orca-orphaned-result-<task_id>.json` 확인 포함)를 해당
  run의 소유자가 수행한다(issue #41).
- **Run 생성**(실행 시작 시 1회): Run을 만들고 바인딩한 뒤 `run_id`를 사이드카 파일에 남긴다(§2a의
  라운드 2+ relay 코드 블록은 별도 fenced block이라 셸 변수가 그대로 넘어가지 않는다):

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<issue 번호> contract round relay" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt"
  ```

  이후 §2a 라운드 2+ relay의 모든 `worker-start`/`check --wait`/`--ack` 호출 앞에서
  `RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt")"`로 다시 읽는다 —
  `orca-task-runner`/`orca-evaluate`가 각자 내부 fan-out에 쓰는 Run과는 별개다(섞이면 서로 다른
  세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md`
  참고). 라운드 1의 `task-create`/`dispatch`(§2a 상단)는 `--run`을 명시하지 않지만, `task-create`가
  `--run` 생략 시 호출 터미널에 바인딩된 Run을 그대로 물려받는 것으로 실측 확인했다(`--run` 없이 만든
  task의 `.run_id`가 이미 바인딩돼 있던 Run과 일치) — 따라서 라운드 2+의 `check --wait --run "$RUN_ID"`와
  `task-list --run "$RUN_ID"`는 라운드 1의 결과도 정상적으로 찾는다.

## 1. Epic 경로

**1a. issue-drain** — 별도 subagent(이 세션과 다른, 별도로 뜬 세션)에게 child issue 전체 검증을 맡긴다:

- 각 child issue가 self-contained한지(§0에서 해석한 acceptance-criteria 섹션 + "무엇을 만들지"가 본문에 있는지)
- 의존 관계가 있다면(`get_child_order`가 참고하는 것과 같은 그래프) 그게 실제로 존재하고 방향이 맞는지 — 의존 링크 자체가 없는 건 실패가 아니다
- 그래프상 빠진 child나 순환 의존이 없는지

```
get_issue(epic-num)
list_children(epic-num)
```

검증 실패 → 사용자에게 보고하고 멈춘다(수정 후 재호출). 통과 → **1b**.

**1b. task-queue 확정** — `get_child_order(epic-num, children)`로 실행 순서를 정한다. file-overlap이 아니라 **issue 그래프 기준**이다(구현 전이라 파일 목록을 아직 모른다).

**1c. 순회** — ready task마다 아래 "2. Task 경로"를 실행. 완료되면 dequeue하고 의존이 풀린 다음 task로 진행. 이번 큐가 비었다고 바로 epic을 닫지 않는다 — 이번 실행 밖에서 처리된 child가 있을 수 있으므로, 닫기 전에 child 전체가 실제로 닫혀 있는지 확인한다(child 완료가 epic에 자동 반영되지 않는 tracker일 수 있으므로 이 확인·종료는 항상 명시적으로 한다):

```
list_children(epic-num)의 각 항목에 is_open() 확인
# 전부 닫혀 있을 때만(=열린 child가 없을 때만) epic을 닫는다
close_issue(epic-num, "All child tasks complete: <child-num-1>, <child-num-2>, ...")
```

**1d. Retro (best-effort, epic close 직후)** — 방금 닫힌 epic의 로그를 분석해 스킬 결함 이슈를 만들도록
retro 터미널 1개를 띄워 `orca-retro`를 실행시킨다. close **후**에 실행한다 — close 전에 돌리다
coordinator가 죽으면 child가 전부 닫힌 epic이 열린 채 남는다. retro의 어떤 실패(스폰·dispatch·분석·gh)도
이 워크플로를 실패시키지 않는다: `RETRO_FAIL` outcome만 남기고 정상 종료한다. 이 스킬은 여기서도 로그
본문을 직접 분석하지 않는다 — 분석은 전부 retro 터미널 몫이고, 이 스킬은 §5 요약 한 줄만 받는다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# provider는 model-selection.md 기준 resolve — 판단(judgment) 작업. REPL 필수, agy 제외
# (§2a evaluate 사이트와 같은 제약, 같은 이유).
orca_call_with_retry "orca-workflow" "retro" -- \
  orca terminal create --worktree active --title epic-retro-<epic-num> \
  --command "<REPL 가능, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <retro-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<orca-retro SKILL.md 지침 + epic 번호 + child 목록 + 대상 repo + skills repo(sleeptimegrt-skills) slug>"
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration dispatch --task <task_id> --to <retro-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로, dispatch와 같은 블록에서 즉시:
#  §1 assign 이벤트: role="retro", issue=<epic-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<retro-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-workflow", role="retro", terminal=<retro-handle>, meta 기록 후
#    sent.content=$spec_text. 이 사이트는 §2a의 두 사이트와 달리 요약을 터미널에서 직접 읽으므로,
#    요약 수신 시점에 logging.md §2의 최초-read 레시피(--cursor 없이)로 recv도 기록한다.
# 요약(RETRO filed=[...] commented=[...] discarded=<n>) 수신 후 — 수신 실패·timeout이면 RETRO_FAIL:
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<epic-num>","outcome":"<RETRO_DONE|RETRO_FAIL>","retry":0,"filed":<n>,"commented":<n>,"discarded":<n>}\n' \
  "$(date -u +%FT%TZ)" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
# RETRO_FAIL이면 filed/commented/discarded 필드는 생략한다(logging.md §1). 터미널 close 후 epic 경로 종료.
```

## 2. Task 경로

**2. 전제 — acceptance-criteria 섹션 존재 확인**: `orca-task-runner`를 dispatch하기 전에, §0에서 해석한
acceptance-criteria 섹션명이 issue body에 실제로 있는지 먼저 확인한다. 없으면 **`orca-task-runner`를 호출하지
않고** 바로 **3. Inspecting**으로 보고한다(outcome: `NO_ACCEPTANCE_CRITERIA`) — issue 생성 시 이 섹션을
보장하는 절차는 아직 없어서다(별도 후속 이슈; 임시로는 `/triage` 리다이렉트 대상으로 취급). 이 확인은 여기
한 곳에서만 하고 `orca-task-runner`/`orca-evaluate`에 반복하지 않는다.

**2a. Contract 협상 relay** — `orca-task-runner`를 "제안서 작성" 모드로 호출 → 나온 제안서 파일 경로를 `orca-evaluate`에 "검토" 모드로 전달 → 반려면 파일 경로를 다시 `orca-task-runner`에 전달. **파일 내용은 읽지 않고 경로만 중계**한다. 최대 2라운드, 그 이후는 `orca-task-runner`가 결정권을 가지고 진행(그대로 2b로 넘어감). **라운드 한도 도달 시점에** — 2b로 넘어가기 전에 — `~/.agents/orca-workflows/logging.md` §1 `outcome` 레시피대로 `outcome=CONTRACT_FINALIZED_BY_GENERATOR`, `round=<도달한 라운드 수>`를 남긴다(issue #63 — 이전엔 이 분기가 outcome 이벤트를 전혀 남기지 않아 세션마다 즉석 문자열을 만들거나 로그를 누락했다).

**"호출"의 실체**: `orca-task-runner`/`orca-evaluate`는 이 스킬(orca-workflow)과 같은 세션에서 도는 게 아니라, 각각 orchestration으로 별도 터미널을 띄워서 넘기는 것이다 — 그래야 이 스킬이 "diff나 report 본문을 직접 읽지 않는다"는 원칙이 실제로 지켜진다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
spec_text="<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드 + worker_done을 포함해 네가 보내는 orca orchestration/orca terminal 호출은 항상 orca_call_with_retry로 감싸고(issue #42), wrapper가 exhausted를 반환하면 ask를 포함한 추가 orchestration 호출을 시도하지 말고(같은 죽은 transport) 즉시 사람에게 알리지 말고 .orca-orphaned-result-<task_id>.json에 결과를 저장(커밋 금지)한 뒤 터미널에 ORPHANED_RESULT <task_id> <파일 절대경로> 한 줄을 출력하고 멈추라는 지시(orca-task-runner SKILL.md subtask spec 항목 ⑦과 동일 계약)>"
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "task-runner" -- \
  orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43, positive-confirmation
# 방식으로 issue #58에서 교체): 15초 뒤 재-read해서 $spec_text 앞부분이 tail에서 확인 안 되면 Enter만
# 재전송, 그래도 확인 안 되면 spawn-failures.md로. 이 확인은 자기가 주입한 문자열의 존재만 보는
# 불투명 비교라 위 "diff/report 본문을 직접 읽지 않는다" 원칙과 충돌하지 않는다.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. 이 터미널에 대한 유일한 read는 위 dispatch-verify.md의 liveness probe
#    (불투명 payload-echo 확인 — issue #58)뿐이며, 이는 의도적으로 recv로 기록하지 않는다 — 실제 결과(diff/report
#    본문)는 이 스킬이 직접 읽지 않고 다른 채널(relay 또는 report 파일 직접 읽기)로 도착하기 때문이다.
#    term-<run-handle>.jsonl은 orca-workflow 자신이 소유하는 파일이라 task-runner는 거기 쓰지 않는다
#    — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들(subtask worker마다
#    하나씩)에 이미 남는다.

# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (agy REPL은 포커스 경합 시 영구 hang — `~/.agents/orca-workflows/models/agy.md`,
# `skills/orca-evaluate/SKILL.md` §0 참고). agy는 evaluate 내부 §2(agent e2e)의 headless
# sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
spec_text="<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드 + worker_done을 포함해 네가 보내는 orca orchestration/orca terminal 호출은 항상 orca_call_with_retry로 감싸고(issue #42), wrapper가 exhausted를 반환하면 ask를 포함한 추가 orchestration 호출을 시도하지 말고(같은 죽은 transport) 즉시 사람에게 알리지 말고 .orca-orphaned-result-<task_id>.json에 결과를 저장(커밋 금지)한 뒤 터미널에 ORPHANED_RESULT <task_id> <파일 절대경로> 한 줄을 출력하고 멈추라는 지시(orca-task-runner SKILL.md subtask spec 항목 ⑦과 동일 계약)>"
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "evaluator" -- \
  orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43, positive-confirmation
# 방식으로 issue #58에서 교체): 15초 뒤 재-read해서 $spec_text 앞부분이 tail에서 확인 안 되면 Enter만
# 재전송, 그래도 확인 안 되면 spawn-failures.md로. (이 이슈의 실제 발생 사례가 바로 이 dispatch 대상
# 터미널 — task-evaluate-411 — 이었다.)
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<evaluate-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-workflow", role="evaluator", terminal=<evaluate-handle>, meta 기록 후
#    sent.content=$spec_text. 이 터미널에 대한 유일한 read는 위 dispatch-verify.md의 liveness probe
#    (불투명 payload-echo 확인 — issue #58)뿐이며, 이는 의도적으로 recv로 기록하지 않는다 — 위 task-runner 사이트와
#    같은 이유(실제 결과는 relay 또는 report 파일 직접 읽기로 도착).
```

**Contract 협상 relay — 라운드 2+ (반려된 경우만; 승인이면 곧장 2b)**: 라운드 1과 같은 task_id를 재사용하지
않는다 — `dispatch`는 이미 `dispatched`/`completed` 상태인 task를 거부하고(`"Task ... is dispatched; only ready tasks can be dispatched"`, 실측), 애초에 텍스트를 override하는 인자가 없어 재사용해도 라운드 1과 같은
spec만 재전송된다. 대신 매 라운드 새 task를 만들어 같은 터미널(재-engage 대상은 task-runner면
`<run-handle>`, evaluator면 `<evaluate-handle>`)에 재-dispatch한다 — 단 그 터미널의 직전 dispatch가
`completed` 상태여야 한다(그렇지 않으면 `"Terminal ... already has an active dispatch"`로 거부됨, 실측).
`--deps`는 걸지 않는다 — 걸어도 `dispatch` 자체가 이미 같은 선후관계를 강제하므로 stall 경로만 하나 늘어난다.

직전 라운드가 `completed`인지 확인하는 대기는 `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery
루프를 그대로 따른다(`check --wait`+`--ack`, 타임아웃 시 alive/stuck_draft/dead 분기) — 이 dispatch에 대한
`worker_done`을 `check`/`check --wait`로 수신하는 것 자체가 곧 `completed` 확정이다(실측: 완료 시각이
메시지 타임스탬프와 정확히 일치). `worker_done` 수신 후, 그 결과의 `reportPath`를 읽기 위한 **1회성**
조회만 한다(폴링 아님 — `worker_done` 메시지의 payload 자체엔 `reportPath`가 없어서, 이 조회는 "완료됐는지"
확인용이 아니라 값을 얻기 위한 것뿐이다):

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>.txt")"   # §0에서 남긴 사이드카
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-list --run "$RUN_ID" --json
# 위 결과에서 직전 라운드 task_id를 찾아 .result(JSON 문자열)를 파싱해 .reportPath를 읽는다 —
# 본문은 읽지 않고 경로만 중계한다는 원칙은 여기서도 유지된다.
spec_text="<round 번호 + 위에서 읽은 reportPath + (evaluator→task-runner 방향이면) 반려 사유 요약 + worker_done을 포함해 네가 보내는 orca orchestration/orca terminal 호출은 항상 orca_call_with_retry로 감싸고(issue #42), wrapper가 exhausted를 반환하면 ask를 포함한 추가 orchestration 호출을 시도하지 말고(같은 죽은 transport) 즉시 사람에게 알리지 말고 .orca-orphaned-result-<task_id>.json에 결과를 저장(커밋 금지)한 뒤 터미널에 ORPHANED_RESULT <task_id> <파일 절대경로> 한 줄을 출력하고 멈추라는 지시(orca-task-runner SKILL.md subtask spec 항목 ⑦과 동일 계약)>"
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration task-create --spec "$spec_text" --json
orca_call_with_retry "orca-workflow" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree active \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(worker-start에도 동일하게 필요).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. task_id가 실제 존재하므로 §1의 relay:true/omit
# 규칙은 이 사이트엔 적용되지 않는다(issue #64로 해소).
```

- self-recovery.md의 재시도 예산까지 소진해도(최초 대기 1회 + `worker_abandon_retry` 최대 2회, 각
  최대 1시간 — 최악의 경우 약 3시간) `completed`가 안 되면 체크포인트 — 재진단하지 않고
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차로.

**2b. Generate** — `orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6).

**2b-1. GATE_FAIL 라우팅** — `orca-evaluate`를 호출하지 않고 바로 **3. Inspecting**으로 간다. `orca-task-runner`가 이미 자기 재시도 예산을 다 썼으므로 여기서 추가 재시도를 걸지 않는다(이중 카운팅 방지). Inspecting 보고에 "evaluate 호출 안 됨(GATE_FAIL) — 기계적 게이트 실패"를 명시해 아래 FAIL/ESCALATE와 구분한다. 이때도 §2d의 outcome 로그 라인을 `outcome:"GATE_FAIL"`로 남긴다(§2d를 거치지 않으므로 여기서 직접).

**2c. Evaluate** — (§2b가 diff 경로를 반환했을 때만) `orca-evaluate` 호출(diff 경로 전달), PASS / FAIL / ESCALATE 중 하나를 결과로 받는다.

**2d. 라우팅**:
- PASS → PR 생성/보강, merge, issue 종료(§2b가 반환하는 건 diff 경로일 뿐 PR이 아니므로 이 단계에서 처음 PR을 만들거나 기존 PR을 찾아 보강한다):

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
  `orca-workflow`는 어느 백엔드인지 몰라도 되고 그 로직을 여기 복제하지 않는다.

  ```bash
  pr_num="$(gh pr list --head "<task-branch>" --json number -q '.[0].number')"
  # premerge 게이트 — orca-evaluate의 PASS는 "코드가 acceptance criteria를 충족하는가"만 보고,
  # "지금 이 브랜치를 origin/main에 얹어도 안전한가"(stale-main, gate-integrity 자기수정 여부)는
  # 안 본다. 그건 lifecycle-gate-policy의 premerge.sh 몫이라 merge 직전에 따로 불러야 한다.
  # 이 레포가 그 컨벤션을 아직 안 썼으면(scripts/premerge.sh 자체가 없으면) 예전처럼 바로 merge —
  # 여기서 새로 강제하지 않는다.
  # migration/schema 변경이 diff에 있으면 premerge가 MIGRATION_ESCALATE로 막아줄 것이라 가정하지
  # 않는다(#45) — 그 체크는 배포된 템플릿 버전에 따라 아예 없거나(v1), 있어도 기본 꺼짐이다
  # (opt-in MIGRATION_LINT_ENABLED). 대상 repo의 merge policy 문서(AGENTS.md 등)를 exit code와
  # 별개로 직접 확인한 뒤에만 self-merge한다.
  if [ -f scripts/premerge.sh ]; then
    # --review-done: orca-evaluate §3의 code review가 이미 그 review 통과를 의미한다.
    if ! bash scripts/premerge.sh --review-done; then
      premerge_exit=$?
      printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"PREMERGE_FAIL","retry":0,"premerge_exit":%s}\n' \
        "$(date -u +%FT%TZ)" "$premerge_exit" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
      # 여기서 merge하지 않는다 — gh pr merge를 건너뛰고 바로 아래 "3. Inspecting"으로 분기한다
      # (GATE_FAIL과 같은 원칙: 여기서 추가 재시도 걸지 않음).
      # exit code의 의미는 여기 복제하지 않는다 — 대상 repo의 scripts/premerge.sh 헤더 주석이 정본이다
      # (복제한 표가 배포본 구현과 어긋난 실측: #45). Inspecting 보고에 이 exit code + 그 헤더에서
      # 디코드한 의미 + 마지막 stderr 몇 줄을 그대로 첨부한다.
    else
      gh pr merge "$pr_num" --squash --delete-branch
    fi
  else
    gh pr merge "$pr_num" --squash --delete-branch
  fi
  ```

  머지 성공 시(둘 중 어느 분기든) **`is_open(task-issue-num)`이 true면 `close_issue(task-issue-num, "Merged via PR #$pr_num")`를 호출**한다 — 코드호스팅(PR 머지)은 GitHub 전용이라 미변경이고, issue 종료는 트래커 무관하게 이 한 경로로 처리된다: GitHub는 위 `link_pr_for_close`가 보통 이미 닫아둬서 여기선 안전망(no-op)이고, Jira 등 merge-magic이 없는 트래커는 이 호출이 유일한 종료 경로다. (`is_open`/`close_issue`/`link_pr_for_close`는 실제 셸 커맨드가 아니라 tracker adapter 오퍼레이션이다 — 문자 그대로 셸에 붙여넣지 말 것.)

  task 종료(premerge.sh가 있고 실패한 경우는 예외 — 아래 PREMERGE_FAIL 참고, task 종료가 아니라 inspecting으로 간다).
- FAIL → 재시도 카운터 확인. **2회 미만이면** feedback과 함께 `orca-task-runner`에 재-dispatch(2b로). **2회 도달하면** inspecting으로.
- ESCALATE → 재시도 카운트 무관하게 즉시 inspecting.
- PREMERGE_FAIL → (PASS 라우팅 안에서만 발생 — 위 참고) 추가 재시도 없이 즉시 inspecting. `orca-evaluate`는 이미 PASS를 냈으므로 재-dispatch 대상이 아니다 — merge 직전 게이트가 별도로 막은 것.

라우팅 판정마다 outcome 이벤트를 할당 로그와 같은 파일에 남긴다 — `issue`/`task_id`로 assign 이벤트와 join해야 "어떤 할당이 어떤 결과를 냈는지"를 사후 감사할 수 있다(할당 기록만으로는 품질 판정 불가). 로그 — `~/.agents/orca-workflows/logging.md` §1 `outcome` 레시피 그대로 실행(enum 값은 그쪽이 정본 — 여기 복제하지 않는다): `skill="orca-workflow"`, `issue=<issue-num>`, `outcome=<위 라우팅 분기에서 결정된 값>`, `retry=<재시도 횟수>`.

## 3. Inspecting

사람 체크포인트. 보고 내용: issue 번호, PASS/FAIL/ESCALATE/GATE_FAIL/PREMERGE_FAIL/NO_ACCEPTANCE_CRITERIA/NO_DONE_TRANSITION 중 어느 것으로 왔는지와 그 근거, 재시도 횟수, resolved providers/models. GATE_FAIL은 `orca-evaluate`가 아예 호출되지 않았다는 뜻이므로 그 사실을 반드시 표시한다. **PREMERGE_FAIL**은 `orca-evaluate`가 PASS를 냈는데도 merge 직전 게이트에서 막혔다는 뜻이므로, premerge.sh의 exit code와 그 의미(대상 repo `scripts/premerge.sh`의 헤더 주석에서 디코드한다 — 그 헤더 주석이 정본이고, 표를 이 스킬에 복제하지 않는다), 마지막 출력 몇 줄을 그대로 표시한다 — 사람이 그 의미를 다시 유추하지 않게. **NO_ACCEPTANCE_CRITERIA**는 §2 전제 확인에서 acceptance-criteria 섹션이 issue body에 없어 `orca-task-runner`를 아예 호출하지 않았다는 뜻이다. **NO_DONE_TRANSITION**은 tracker adapter의 `close_issue`가 "완료" transition을 찾지 못했다는 뜻이다(트래커 문서에 명시 없음, 또는 명시된 이름이 현재 상태의 available transition 목록에 없음). 두 outcome 모두 §2d를 거치지 않고 발생하므로(GATE_FAIL과 같은 이유), 발생 시점에서 즉시 위 outcome 로그 라인을 해당 outcome 값으로 직접 남긴다. 사람이 고를 수 있는 것: 계속(피드백 반영해 재시도) / 재계획(요구사항 자체를 다시 논의 — 1a 또는 issue 수정으로 복귀) / 중단.

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-task-runner`/`orca-evaluate`의 폴백 규칙을 그대로 따르며, 이 스킬은 두 결과를 이어주는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만 대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
