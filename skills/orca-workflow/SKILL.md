---
name: orca-workflow
description: >-
  Invoke explicitly via `/orca-workflow` — do not rely on phrase-matching, which collides with Orca's
  built-in `orchestration` skill (multi-agent coordination, task dispatch, coordinator loops). Entry
  point that drives an issue (GitHub Issues or Jira, resolved per repo — see
  `~/.agents/orca-workflows/issue-trackers/selection.md`) through its full lifecycle: gates on
  agent-e2e tooling being declared before routing, resolves the tracker (with first-run onboarding),
  routes the issue in-session — children present → `orca-workflow-epic`, none → `orca-workflow-task` —
  forwarding mode [afk|hitl] (default hitl), and after the routed run finishes, however it ended,
  always launches a best-effort `orca-retro` over that invocation's logs (issue set = root ∪ queue).
  Never generates or evaluates code directly — pure orchestration. Self-relative. Do NOT use it for
  ad-hoc multi-agent coordination, task dispatch, DAGs, or coordinator loops (use the `orchestration`
  skill), nor for raw terminal/worktree control (use `orca-cli`).
compatibility: Requires the `orca` CLI (skill set last verified against Orca app 1.4.180), the `~/.agents/orca-workflows/` symlink to this repo's orca-workflows/, and the `gh` CLI.
---

# Orca Workflow

entry point 라우터다. 이슈 하나를 받아 타입을 판별해 `orca-workflow-epic`(child 있음) 또는
`orca-workflow-task`(단일 task)를 **이 세션에서** 실행하고, 끝나면 retro를 띄운다. 코드 생성·평가·
계약 내용을 모른다.

## 0. 전제

- `orca status --json` ready. 실패 시 하위 스킬의 폴백 규칙을 그대로 따르고 사용자에게 보고한다.
- **이슈 트래커 해석**(실행 시작 시 1회, 캐싱 없이): `~/.agents/orca-workflows/issue-trackers/selection.md`가
  정의하는 절차로 백엔드를 정하고, 그 백엔드의 `~/.agents/orca-workflows/issue-trackers/{github,jira}.md`가
  정의하는 `get_issue`/`get_issue_type`/`list_children`/`get_child_order`/`is_open`/`close_issue`/
  `link_pr_for_close`를 이후 전체 실행에서 쓴다. 구체 값(project key, transition id 등)은 이 스킬에
  복제하지 않는다 — 항상 selection.md가 가리키는 대상 repo의 tracker 문서에서 얻는다.
- **E2E tooling 확인**(실행 시작 시 1회, §1 라우팅 이전): 대상 repo의 `docs/agents/e2e-tooling.md`가
  없으면 §1로 넘어가지 않고 사용자에게 `/project-setup` 실행을 안내하며 이번 실행을 중단한다 —
  generation이 끝난 뒤 evaluate 단계(`orca-evaluate` §2)에서야 막히는 낭비를 피한다. 이슈 ID 모양에
  따른 예외는 없다(GitHub 숫자 ID든 Jira형이든 agent-e2e는 모든 task 평가에 항상 필요하다는 기존
  전제 — `orca-evaluate` §2가 이미 무조건 게이트로 문서화). 문서가 있으면 그대로 §1로 진행한다.
- **고착 dispatched 스윕**(세션 시작 시 1회, report-only): `bash
  ~/.agents/orca-workflows/scripts/sweep_stale_dispatched.sh`를 실행해 임계(기본 1시간)를 넘긴 `dispatched`
  task 목록을 확보하고, 발견되면(exit 3 — 전제 실패가 아니다, 진행은 계속한다) 사용자 보고에 그대로
  포함한다. 복구는 이 스킬이 직접 하지 않는다 — worker_done 유실 복구는 `orca-task-runner` §5 절차
  (worktree의 `.orca-orphaned-result-<task_id>.json` 확인 포함)를 해당 run의 소유자가 수행한다(issue #41).
- **Mode 인자** — `afk`|`hitl`, 생략 시 `hitl`. 하위 스킬에 그대로 전달한다. 의미 정의는
  `orca-workflow-task` §5가 정본이다.
- 이 스킬은 Run을 만들지 않는다 — §2 retro의 task-create/dispatch는 하위 스킬이 이 세션에 바인딩한
  Run을 상속한다(`--run` 생략 시 호출 터미널 바인딩 상속, 실측). 하위 스킬이 Run을 바인딩하기 전에
  종료된 경우 §2의 task-create/dispatch는 실패할 수 있다 — 그 경우도 §2의 best-effort 규칙대로
  `RETRO_FAIL` outcome만 남기고 정상 종료한다(라우터가 Run을 만들어 복구하지 않는다).

## 1. 라우팅

`get_issue_type(issue-num)`/`list_children(issue-num)` — child가 있으면 `orca-workflow-epic`, 없으면
`orca-workflow-task`를 이 세션에서 로드해 그대로 따른다(별도 스폰 아님 — entry 세션이므로 두 스킬의
보고 채널은 "사람"이다). mode를 전달한다.

## 2. Retro (best-effort — §1 라우팅이 실행된 invocation마다 1회)

§1이 하위 스킬을 실제로 실행했다면, 하위 스킬이 어떻게 끝났든(§5 보고가 완료든 parked/escalation
이든) invocation 종료 시 retro를 1회 실행한다. §0에서 끝난 실행(트래커 해석 실패, 온보딩 중단 등)은
분석할 하위 실행 로그 자체가 없다 — retro 없이 그 사실만 사용자에게 보고하고 종료한다.
방금 끝난 실행의 로그를 분석해 스킬 결함 이슈를 만들도록 retro 터미널 1개를 띄워 `orca-retro`를
실행시킨다. close 시도가 모두 끝난 뒤에 실행한다 — close 전에 돌리다 coordinator가 죽으면 일이 다
끝난 root issue가 열린 채 남는다. retro의 어떤 실패(스폰·dispatch·분석·gh)도 이 워크플로를 실패시키지
않는다: `RETRO_FAIL` outcome만 남기고 정상 종료한다. 이 스킬은 여기서도 로그 본문을 직접 분석하지
않는다 — 분석은 전부 retro 터미널 몫이고, 이 스킬은 `orca-retro` §5 요약 한 줄만 받는다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh   # log_outcome — outcome enum의 기계-검증 정본(raw printf 금지, logging.md §1)
# provider는 model-selection.md 기준 resolve — 판단(judgment) 작업. REPL 필수, agy 제외
# (`orca-workflow-task` §1의 evaluate 스폰과 같은 제약 — 사유는 `~/.agents/orca-workflows/models/agy.md`).
orca_call_with_retry "orca-workflow" "retro" -- \
  orca terminal create --worktree active --title retro-<root-issue-num> \
  --command "<REPL 가능, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
# Pre-dispatch boot-quiesce (issue #84)
# freshly launched REPL은 tui-idle 뒤에도 MCP boot 출력이 남을 수 있으므로, cursor-scoped 새 출력이
# 멈출 때까지 확인한다. 전체 scrollback grep은 TUI repaint 잔재를 boot 출력으로 오판하므로 쓰지 않는다.
# retro는 best-effort(§0) — 다른 스폰 사이트처럼 exit 1로 빠지지 않는다. tui-idle wait 자체의 실패도
# 여기서 fail-closed로 걸러야 한다: wait가 timeout/실패한 채로 넘어가면 첫 cursor-diff가 정적인(=이미
# 죽은) 터미널을 "boot 출력 정지"로 오판해 quiesced로 확정해버린다(spawn-failures.md #37과 같은 모양의
# 죽은-셸 오탐). 실패하면 아래 boot_quiesced=0 분기가 RETRO_FAIL만 남기고 정상 종료한다(워크플로
# 전체를 실패시키지 않는다).
boot_quiesced=0
if orca_call_with_retry "orca-workflow" "retro" -- \
  orca terminal wait --terminal <retro-handle> --for tui-idle --timeout-ms 60000 --json; then
  boot_deadline=$(( $(date -u +%s) + 60 ))
  boot_initial="$(orca_call_with_retry "orca-workflow" "retro" -- \
    orca terminal read --terminal <retro-handle> --json)" || boot_initial=""
  if [ -n "$boot_initial" ]; then
    cur="$(printf '%s' "$boot_initial" | jq -r '.result.terminal.latestCursor')"
    while :; do
      sleep 12
      boot_read="$(orca_call_with_retry "orca-workflow" "retro" -- \
        orca terminal read --terminal <retro-handle> --cursor "$cur" --json)" || break
      new="$(printf '%s' "$boot_read" | jq -r '.result.terminal.returnedLineCount')"
      if [ "$new" = "0" ]; then
        boot_quiesced=1
        break
      fi
      cur="$(printf '%s' "$boot_read" | jq -r '.result.terminal.latestCursor')"
      if [ "$(date -u +%s)" -ge "$boot_deadline" ]; then
        break
      fi
    done
  fi
fi
# End pre-dispatch boot-quiesce
if [ "$boot_quiesced" != "1" ]; then
  # boot-quiesce 확인에 실패(터미널 read 불가 또는 60s 안에 MCP boot 출력이 멈추지 않음) — task-create/
  # dispatch --inject로 진행하지 않는다. RETRO_FAIL만 남기고 정상 종료(터미널 close 후 실행 종료).
  log_outcome --skill orca-workflow --issue "<root-issue-num>" --outcome RETRO_FAIL --retry 0
else
spec_text="<orca-retro SKILL.md 지침 + root issue 번호 + 큐 issue 목록(orca-workflow-epic 경로면 §5 보고의 큐 목록, orca-workflow-task 경로면 root 1건 — 분석 issue 집합 = root ∪ 큐, 중복 제거) + 대상 repo + skills repo(sleeptimegrt-skills) slug>"
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow" "retro" -- \
  orca orchestration dispatch --task <task_id> --to <retro-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로, dispatch와 같은 블록에서 즉시:
#  §1 assign 이벤트: role="retro", issue=<root-issue-num>, task_id=<task_id>, provider(claude-code|codex|agy 중 하나)/model/effort=resolved 값,
#    terminal=<retro-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-workflow", role="retro", terminal=<retro-handle>, meta 기록 후
#    sent.content=$spec_text. 이 사이트는 하위 스킬의 dispatch 사이트들과 달리 요약을 터미널에서
#    직접 읽으므로, 요약 수신 시점에 logging.md §2의 최초-read 레시피(--cursor 없이)로 recv도 기록한다.
# 요약(RETRO filed=[...] commented=[...] discarded=<n>) 수신 후 — 수신 실패·timeout이면 RETRO_FAIL:
log_outcome --skill orca-workflow --issue "<root-issue-num>" --outcome "<RETRO_DONE|RETRO_FAIL>" --retry 0 \
  --filed <n> --commented <n> --discarded <n>
# RETRO_FAIL이면 --filed/--commented/--discarded를 넘기지 않는다(logging.md §1 — 빈 값은 헬퍼가 필드를
# 생략하지만, 애초에 셀 것이 없다는 뜻이므로 플래그 자체를 생략). 터미널 close 후 실행 종료.
fi
```

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-task-runner`/`orca-evaluate`의 폴백 규칙을 그대로 따르며, 이 스킬은 두 결과를 이어주는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만 대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
