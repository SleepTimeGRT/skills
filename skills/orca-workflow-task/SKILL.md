---
name: orca-workflow-task
description: Single-issue coordinator for one task issue — invoked in-session by `orca-workflow` (entry) or spawned as a separate coordinator terminal by `orca-workflow-epic`; invoke explicitly, do not phrase-match. Owns exactly one relay Run keyed by the issue, drives the orca-task-runner/orca-evaluate contract negotiation relay, generation, evaluation, PR/merge (merge-time verification delegated to repo CI required checks), and issue close. Mode [afk|hitl] (default hitl) governs escalation — hitl raises a blocking question to the caller/human (decision gate), afk preserves the work (worktree, CONTRACT_DIR artifacts, logs) and returns the outcome so the caller can move on. Never generates or evaluates code directly — pure orchestration, kept context-light. Self-relative. Do NOT use for ad-hoc coordination or terminal control (use the `orchestration` or `orca-cli` skills) — this skill runs only as part of the orca-workflow pipeline.
compatibility: Requires the `orca` CLI (skill set last verified against Orca app 1.4.180), the `~/.agents/orca-workflows/` symlink to this repo's orca-workflows/, and the `gh` CLI.
---

# Orca Workflow Task

이슈 하나를 받아 끝까지(merge까지) 가져가는 단일 issue coordinator다. **코드를 생성하지도, 평가하지도 않는다** — 그 일은 각각 `orca-task-runner`, `orca-evaluate`가 한다. 이 스킬의 컨텍스트에는 issue 번호·task 상태·짧은 판정 결과만 남긴다. diff나 report 본문을 직접 읽지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- **이슈 트래커 해석** (실행 시작 시 1회, 캐싱 없이 — 매 실행마다 새로 읽는다): `~/.agents/orca-workflows/issue-trackers/selection.md`가 정의하는 절차로 백엔드를 정하고, 그 백엔드의 `~/.agents/orca-workflows/issue-trackers/{github,jira}.md`가 정의하는 오퍼레이션 중 이 스킬이 쓰는 `get_issue`(§1 evaluator spec의 issue 원문 확보)/`is_open`/`close_issue`/`link_pr_for_close`(§4)를 이후 실행에서 쓴다. 구체 값(project key, transition id 등)은 이 스킬에 복제하지 않는다 — 항상 selection.md가 가리키는 대상 repo의 tracker 문서에서 얻는다.
- **'대상 repo' 값은 무가공 전달(issue #164)**: 호출자(진입 시 직접, 또는 `orca-workflow-epic`이 spawn하는
  경우 spec_text)로부터 받는 "대상 repo" 값은 `~/.agents/orca-workflows/logging.md` §1 repo 필드에 그대로
  쓰일 정본 식별자 문자열이다(예: `owner/name`). 받은 값이 파일시스템 경로처럼 보이거나 예상과 다른
  형태여도 basename 등으로 가공·재해석하지 않고, 아래 §1/§2/§4의 모든 `log_dispatch`/`log_outcome`
  호출과 spec_text의 "대상 repo"에 받은 문자열을 그대로 넘긴다 — 입력 형태가 이상해 보이는 것은 호출자
  스펙의 문제이지 이 스킬이 보정할 대상이 아니다(같은 문자열이 갈라지면 `orca-retro`의 (repo, issue)
  복합 키 필터가 이 스킬이 남긴 이벤트를 조용히 놓친다).
- **Contract 디렉토리**(실행 시작 시 1회) — 이 실행이 처리하는 issue 번호로
  `~/.agents/orca-workflows/contract-schema.md` 규칙대로 `CONTRACT_DIR`를 계산·생성(`install -d -m 700`)해
  §1의 두 spec_text에 절대경로로 넣는다. acceptance criteria는 issue 본문의 사전 섹션이 아니라 §1
  협상에서 초안·승인된다 — 산출물 파일(proposal/verdict/override)과 확정 AC의 정본 위치는 같은
  문서가 정의한다.
- **재개(crash-resume) 분기**(CONTRACT_DIR 계산 직후 1회, issue #156) — round/attempt/retry 카운터의
  정본은 이 세션의 대화 컨텍스트가 아니라 CONTRACT_DIR 아티팩트의 파일명 번호다. 산출물이 하나라도
  있으면 이 실행은 새 시작이 아니라 재개다:

  ```bash
  source ~/.agents/orca-workflows/scripts/contract_resume.sh
  contract_resume_state "<CONTRACT_DIR>"
  ```

  출력 JSON의 `resume` 필드가 가리키는 §로 점프한다 — `section-1-proposal`/`-verdict`/`-override`는
  §1의 해당 스텝부터(`round` 필드의 라운드), `section-2`는 §2부터(`attempt`/`retry` 필드를 §2 spec과
  §4 재시도 카운터로 이어받는다), `section-4`는 §4의 PASS 라우팅부터(PR 확보와
  merge 루프는 재실행-안전 — #72), `section-5`는 `outcome` 필드 값으로 §5로. 규칙:
  - `recent_write`가 true면(기본 10분 내 아티팩트 수정) 이전 세션의 워커가 아직 쓰고 있을 수 있다 —
    점프하지 않는다. hitl이면 사람에게 확인하고, afk면 10분 대기 후 1회 재스캔, 그래도 true면 §5
    afk 보존 절차로 가서 outcome=ESCALATE로 보고한다(근거: "재개 모호 — 이전 세션 워커 생존 의심").
  - 이전 세션의 Run·터미널·task는 재사용하지 않는다 — 아래 "Run 생성"을 새로 수행해 사이드카를
    덮어쓰고, 점프한 §가 요구하는 터미널은 새로 스폰한다.
  - 재개가 §1을 건너뛰는 경우 `CONTRACT_APPROVED`/`CONTRACT_FINALIZED_BY_GENERATOR` outcome 로그를
    다시 남기지 않는다 — 아티팩트가 상태 정본이고, 중복 기록하면 issue당 계약 확정이 2회로 집계된다.
  - `section-1-*` 재개(같은 라운드 재-태움)는 같은 번호 파일을 덮어쓸 수 있다 — append-only는 라운드
    간 규칙이다(`contract-schema.md` 크래시-재개 절).
- CLI 기반 coordinator(Codex/agy)는 launch 시 approval·sandbox를 명시한다. codex posture는 `--dangerously-bypass-approvals-and-sandbox` — 근거·예외(headless read-only 등)는 `~/.agents/orca-workflows/models/codex.md`가 정본이다. 안전 전제는 워크트리 격리다.
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §1의 두 `terminal create` 호출
  모두에 적용된다.
- **이 세션 자신의 호출이 classifier에 거부되면(issue #118)** — 위 항목과 다르다: 위는 스폰한 *워커*
  터미널의 실패고, 이건 이 세션 자신의 `orca orchestration`/`orca terminal` 호출(`task-create`/
  `worker-start`/`terminal create` 등)이 Claude Code auto-mode 분류기에 거부되는 경우다
  (`spawn-failures.md`의 `Permission for this action was denied by the Claude Code auto mode classifier` 행, known_issue #118). 문구를 바꿔 같은 세션에서 재시도하지 않는다 — 거부 이력이
  쌓일수록 분류기 판정 범위가 넓어져 악화된다(실측). 그 자리에서 멈추고 §5로 가 `outcome=ESCALATE`를
  보고하되, `log_outcome --detail`에 (a) 이 실행의 `CONTRACT_DIR` 절대경로, (b) 아직 살아있는 것으로
  확인된 task-runner 터미널 핸들(있다면)을 담는다. 실제 재스폰은 이 세션이 아니라 그 보고를 읽는
  쪽(`orca-workflow-epic` 또는 사람)이 수행한다 — `orca terminal create` 자체가 거부 대상에 포함되므로
  이 세션은 자기 자신을 이관시킬 수 없다. 새 코디네이터가 같은 `CONTRACT_DIR`를 가리키면 위
  재개(crash-resume) 분기가 round/attempt 상태를 자동으로 이어받지만, 그 분기의 "이전 세션의
  Run·터미널·task는 재사용하지 않는다"(위) 기본값은 여기서는 적용하지 않는다 — 보고된 task-runner
  핸들은 크래시가 아니라 이 코디네이터만 접근이 막힌 것뿐이므로 재사용이 맞다(2026-08-09 실측: 이
  재사용이 실제로 회복에 성공한 유일한 조치였다).
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
  라운드 2+ relay 코드 블록은 별도 fenced block이라 셸 변수가 그대로 넘어가지 않는다). 파일명의
  `<project-slug>`는 위 Contract 디렉토리 단계에서 계산한 값을 재사용한다(logging.md §3, issue #159 —
  issue 번호만으로는 저장소 간 사이드카가 충돌한다):

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<issue 번호> contract round relay" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-workflow-task.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-workflow-task.txt"
  ```

  이후 §1의 모든 `worker-start`/`check --wait`/`--ack` 호출 앞에서
  `RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-workflow-task.txt")"`로 다시 읽는다
  (라운드 1 fenced block도 상단에서 한 번 읽는다 — 그 블록의 두 `worker-start`가 쓴다) —
  `orca-task-runner`/`orca-evaluate`가 각자 내부 fan-out에 쓰는 Run과는 별개다(섞이면 서로 다른
  세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md`
  참고). 라운드 1의 `task-create`는 `--run`을 명시하지 않지만(그 블록의 두 `worker-start`는 명시한다),
  `task-create`가 `--run` 생략 시 호출 터미널에 바인딩된 Run을 그대로 물려받는 것으로 실측 확인했다
  (`--run` 없이 만든 task의 `.run_id`가 이미 바인딩돼 있던 Run과 일치) — 따라서 라운드 2+의
  `check --wait --run "$RUN_ID"`와 `task-list --run "$RUN_ID"`는 라운드 1의 결과도 정상적으로 찾는다. 이 세션을 `orca-workflow-epic`이 스폰했더라도 epic의 Run을 재사용하지 않는다 — coordinator 세션마다 자기 Run 1개(`orca-task-runner` §0의 같은 규칙과 동일한 이유).
- **Mode** — spec/인자로 `afk` 또는 `hitl`을 받는다(생략 시 `hitl`). 의미는 §5가 정의한다 — §1~§4의
  동작은 mode와 무관하게 동일하다.
- **보고 채널** — spec에 "spawn된 coordinator" 지시가 있으면 최종 outcome은 `worker_done`으로, hitl
  질문은 ask(decision gate)로 호출자에게 보낸다. 그 지시가 없으면(entry 세션) 사람에게 직접 보고한다.
  ask/reply의 정확한 호출 문법은 실행 시점에 `orca skills get orchestration` 또는
  `orca orchestration --help`로 확인한다 — 여기 복제하지 않는다.

## 1. Contract 협상 relay

`orca-task-runner`를 "제안서 작성" 모드로 호출(제안서 = `contract-schema.md` 스키마의 `proposal-r<n>.json`, **AC 초안 포함**) → `orca-evaluate`에 "검토" 모드로 전달(판정 = `verdict-r<n>.json`) → 반려면 다시 `orca-task-runner`에 전달. 산출물 경로는 §0의 `CONTRACT_DIR`와 라운드 번호로 결정론적이므로 **이 스킬은 파일을 읽지도, 경로를 추출하지도 않고 CONTRACT_DIR·라운드 번호만 중계**한다. 최대 2라운드(조건부로 3 — 아래 "라운드 2→3 조건부 연장" 참고), 그 이후는 `orca-task-runner`가 결정권을 가질 수 있다(`override.json` 존재가 그 기록이다) — 단 무조건 §2로 가는 것이 아니다. **라운드 한도 도달 시점에** — §2로 넘어가기 전에 — 다음 기계적 분기를 먼저 태운다(구조 필드 1개 추출이라 "diff/report 본문을 읽지 않는다" 원칙과 충돌하지 않는다 — dispatch-verify의 불투명 비교와 같은 결). 이 분기는 §0 재개 분기의 `contract_resume.sh`가 미러링한다 — 여기를 바꾸면 그쪽도 함께 바꾼다(`tests/test_contract_resume.py`가 스크립트 쪽을 고정한다):

**라운드 2→3 조건부 연장** — 아래 "라운드 한도 도달 시점" 분기를 태우기 전에, `verdict-r2.json`이
`rejected`이고 `reasons[].target`이 전부 `"plan_coverage"`면(즉 `ac_fidelity`가 하나도 없으면)
아래 분기 대신 이 분기를 태운다 — 아직 라운드 한도(2)에 도달한 것으로 보지 않는다:

```bash
if [ ! -f "<CONTRACT_DIR>/verdict-r2.json" ]; then
  : # 라운드2 verdict가 아직 없다 — 이 시점(라운드2 검토 결과 수신 직후)엔 있어야 정상이다. 없으면
    # 이 분기는 개입하지 않는다 — 아래 "라운드 한도 도달 시점" 분기의 기존 `elif [ ! -f
    # "<CONTRACT_DIR>/verdict-r2.json" ]` 가드가 같은 부재를 fail-closed로 잡는다.
elif jq -e '[.reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/verdict-r2.json" >/dev/null; then
  : # ac_fidelity 있음 — 이 연장은 발동하지 않는다, 아래 "라운드 한도 도달 시점" 분기를 그대로 태운다
else
  # plan_coverage뿐 — override 대신 라운드3 제안서 작성 모드로 orca-task-runner를 재호출한다
  # (spec_text에 round=3 + CONTRACT_DIR + "verdict-r2.json을 읽고 proposal-r3.json 작성" 포함).
  # verdict-r3.json이 approved면 §2로(확정 AC=proposal-r3). rejected면 아래 "라운드 한도 도달
  # 시점" 분기와 동일한 구조를 verdict-r2.json→verdict-r3.json, round=2→3, proposal-r3→proposal-r4로
  # 치환해 그대로 적용한다(아래 두 번째 코드 블록):
  :
fi
```

라운드3이 반려돼 `orca-task-runner`를 override 모드로 재호출한 뒤(`worker_done` 수신 시점) 태우는
분기 — 아래와 동일한 구조를 한 라운드 밀어서:

```bash
if [ ! -f "<CONTRACT_DIR>/override.json" ]; then
  # 라운드3 한도에 도달했는데 override.json이 없다 — fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif [ ! -f "<CONTRACT_DIR>/verdict-r3.json" ]; then
  # override는 있는데 라운드3 verdict가 없다 — fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif [ ! -f "<CONTRACT_DIR>/proposal-r4.json" ]; then
  # override 기록(final_round=3)과 verdict-r3.json은 있는데 확정 계약(proposal-r4)이 없다.
  # worker_done까지 왔으므로 쓰다 죽은 게 아니다 — 기록 계약 위반이다. final_round=3은 이 확장
  # 자체가 도입한 개념이라 legacy 세션이 있을 수 없으므로(R3_REQUIRED_SINCE류의 staleness 구분
  # 자체가 불필요) 곧장 fail-closed: outcome=CONTRACT_ESCALATE, round=3으로 남기고 §5로.
elif jq -e '[.reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/verdict-r3.json" >/dev/null; then
  # AC 자체에 이견이 남음 — outcome=CONTRACT_ESCALATE, round=3으로 남기고 §5로.
else
  # 최종 verdict(r3)의 반려가 plan_coverage뿐 — outcome=CONTRACT_FINALIZED_BY_GENERATOR, round=3을
  # 남기고 §2로(확정 AC=proposal-r4).
fi
```

```bash
if [ ! -f "<CONTRACT_DIR>/verdict-r2.json" ]; then
  # 최종 라운드 verdict 자체가 없다 — evaluator 판정 없이 라운드 한도에 도달한 상태.
  # fail-closed: outcome=CONTRACT_ESCALATE로 남기고 §5로.
elif jq -e '[.reasons[].target] | index("ac_fidelity")' "<CONTRACT_DIR>/verdict-r2.json" >/dev/null; then
  # ac_fidelity 반려는 override.json 존재 여부와 무관하게 곧장 여기로 온다 — 아래 override.json
  # 체크보다 먼저 확인한다(issue #163). AC 자체("무엇을 만들지")에 이견이 남아 애초에 override
  # 단계가 존재한 적이 없는 정상 경로이지 "기록 계약 위반"이 아니다 — 순서가 뒤바뀌어 있으면
  # override.json 부재를 무조건 위반으로 오분류해 사람에게 잘못된 신호("generator가 규칙을
  # 어겼다")를 전달한다(studio-hevv/selah-android#23 T25 실측, 2026-08-12).
  # 라우팅 입력은 generator가 쓴 override.json이 아니라 evaluator 소유의 verdict-r2.json이다
  # (라운드 한도 = 2, §1 상단): override의 unresolved_reasons는 generator가 "해소 못 한" 항목만
  # 골라 담은 자기 필터라, 그걸 기준으로 삼으면 generator가 ac_fidelity 반려를 "해소했다"고
  # 자평하는 순간 이 게이트가 뚫린다 — 2라운드 뒤에는 그 자평을 검증할 evaluator 라운드가 없다
  # (contract-schema.md override 절, docs/references/anthropic-harness-design-long-running-apps.md의
  # self-evaluation 편향).
  # logging.md §1 outcome 레시피대로 outcome=CONTRACT_ESCALATE, round=<도달한 라운드 수>,
  # detail="AC 불일치로 override 단계 스킵, 정상 경로"를 남기고 §2 없이 곧장 §5로.
elif [ ! -f "<CONTRACT_DIR>/override.json" ]; then
  # ac_fidelity는 없다(반려 사유는 plan_coverage뿐)인데 override.json이 없다 — generator가 §1의
  # 기록 계약을 어긴 것. 기록 없는 진행을 허용하지 않는다(fail-closed): outcome=CONTRACT_ESCALATE로
  # 남기고 §5로.
elif [ ! -f "<CONTRACT_DIR>/proposal-r3.json" ]; then
  # override 기록은 있는데 확정 계약(proposal-r3 — override 스텝이 override.json 직후에 쓴다,
  # contract-schema.md "override 후속 라운드" 절, issue #130)이 없다 — worker_done까지 왔으므로
  # 쓰다 죽은 게 아니다. 그렇다고 곧장 "기록 계약 위반"도 아니다 — override.json이 이 r3 요구사항
  # 자체의 도입(commit 79b7c3b, 2026-08-12T09:44:57+09:00) 이전에 완료됐을 수 있다(issue #160).
  # R3_REQUIRED_SINCE 상수(contract_resume.sh와 동일 — 바꾸면 함께 바꾼다)로 override.json의 mtime을
  # 그 시각과 비교한다(recent_write 가드와 같은 touch -t + find -newer 패턴을 기반으로 하되, touch -t
  # 실패를 별도로 체크한다 — 아래 참고. stat -f/-c epoch 파싱은 GNU stat -f의 의미 충돌 위험이 있어
  # 쓰지 않는다). touch -t는 TZ를 명시하지 않으면 호스트 로컬 설정으로 해석하므로(KST가 아닌 머신에서
  # 최대 수 시간 오차 — issue #160 리뷰에서 실측), TZ=Asia/Seoul을 고정한다:
  R3_REQUIRED_SINCE='202608120944.57'
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-r3gate.XXXXXX")"
  # 두 가지 실패 양상을 각각 다른 가드로 막는다 — 하나의 find 극성 반전으로 뭉치면 안 된다는 걸
  # issue #160 최종 리뷰에서 실측으로 확인했다: touch -t 자체가 실패하면 $ref는 의도한 cutoff가
  # 아니라 방금 만든 "지금" mtime에 머문다. 이미 쓰인 override.json은 "지금"보다 newer일 리 거의
  # 없으므로, -newer든 ! -newer든(분기와 printf 값을 맞바꿔도) "cutoff보다 newer 아님"이라는 결과가
  # 똑같이 나온다 — find 극성만 뒤집는 건 이 실패 양상에서 순수 무의미한 재작성이었다(원본과
  # "반전"판 모두 CONTRACT_SCHEMA_STALE을 오보하는 것을 스텁 touch로 직접 재현해 확인). 그래서
  # touch -t의 종료 코드를 직접 확인해 실패 시 비교 자체를 건너뛴다:
  if ! TZ='Asia/Seoul' touch -t "$R3_REQUIRED_SINCE" "$ref" 2>/dev/null; then
    rm -f "$ref"
    # 백데이팅 자체가 실패 — $ref의 mtime은 무의미하므로 비교하지 않는다. 기존 판단 그대로: 기록
    # 계약 위반. fail-closed: outcome=CONTRACT_ESCALATE, round=2로 남기고 §5로.
  elif [ -n "$(find "<CONTRACT_DIR>" -maxdepth 1 -name override.json ! -newer "$ref" 2>/dev/null)" ]; then
    rm -f "$ref"
    # touch -t는 성공했고, override.json이 그 cutoff보다 newer가 아님 = 게이트 도입 이전(또는
    # 정확히 동시)이라는 양성 증거 — 위반이 아니라 구버전 세션. outcome=CONTRACT_SCHEMA_STALE,
    # round=2, detail에 override.json mtime과 $R3_REQUIRED_SINCE를 사람이 읽을 수 있는 형태로
    # 남기고 §5로(§5 문구 참고 — "자동 재개"를 암시하지 않는다).
  else
    rm -f "$ref"
    # touch -t는 성공했고, override.json이 cutoff보다 newer(게이트 도입 이후) — 또는 find 자체가
    # mtime과 무관한 이유로(경로 없음 등) 아무것도 못 찾음 — 둘 다 기존 판단 그대로: 기록 계약
    # 위반. fail-closed: outcome=CONTRACT_ESCALATE, round=2로 남기고 §5로.
  fi
  # (§0 재개 분기는 override.json mtime이 게이트 도입 이후인 상태만 "쓰다 죽음"으로 보고 override
  # 스텝을 재-태운다 — worker_done 수신 여부가 그 두 해석을 가른다. 게이트 도입 이전인 상태는 §0도
  # 동일하게 CONTRACT_SCHEMA_STALE로 escalate한다 — contract_resume.sh 미러.)
else
  # ac_fidelity는 없다(위에서 이미 확인됨 — 반려 사유는 plan_coverage뿐)이고 override.json·
  # proposal-r3.json도 모두 있다 — 검증 방법 이견은 §3 리뷰·e2e가 최종 AC 기준으로 재검증하므로
  # 진행. logging.md §1 outcome 레시피대로 outcome=CONTRACT_FINALIZED_BY_GENERATOR,
  # round=<도달한 라운드 수>를 남기고 §2로 (issue #63).
fi
```

(이 분기는 위 "라운드 2→3 조건부 연장"이 발동하지 않은 경우 — 즉 `verdict-r2.json`에
`ac_fidelity`가 있는 경우에만 실행된다. 발동한 경우는 위 두 번째 코드 블록을 대신 따른다.)

**계약이 승인된 시점에도(몇 라운드에서 승인되든)** — 마찬가지로 §2로 넘어가기 전에 — 같은 레시피대로 `outcome=CONTRACT_APPROVED, round=<승인된 라운드 수>`를 남긴다(issue #69, #86).

**"호출"의 실체**: `orca-task-runner`/`orca-evaluate`는 이 스킬(orca-workflow-task)과 같은 세션에서 도는 게 아니라, 각각 orchestration으로 별도 터미널을 띄워서 넘기는 것이다 — 그래야 이 스킬이 "diff나 report 본문을 직접 읽지 않는다"는 원칙이 실제로 지켜진다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-workflow-task.txt")"   # §0에서 남긴 사이드카 — 아래 두 worker-start가 쓴다
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
if ! orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca terminal wait --terminal <run-handle> --for tui-idle --timeout-ms 60000 --json; then
  exit 1
fi
# Pre-dispatch boot-quiesce (issue #84)
# freshly launched REPL은 tui-idle 뒤에도 MCP boot 출력이 남을 수 있으므로, cursor-scoped 새 출력이
# 멈출 때까지 확인한다. 전체 scrollback grep은 TUI repaint 잔재를 boot 출력으로 오판하므로 쓰지 않는다.
boot_deadline=$(( $(date -u +%s) + 60 ))
boot_initial="$(orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca terminal read --terminal <run-handle> --json)" || exit 1
cur="$(printf '%s' "$boot_initial" | jq -r '.result.terminal.latestCursor')"
while :; do
  sleep 12
  boot_read="$(orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca terminal read --terminal <run-handle> --cursor "$cur" --json)" || exit 1
  new="$(printf '%s' "$boot_read" | jq -r '.result.terminal.returnedLineCount')"
  if [ "$new" = "0" ]; then
    break
  fi
  cur="$(printf '%s' "$boot_read" | jq -r '.result.terminal.latestCursor')"
  if [ "$(date -u +%s)" -ge "$boot_deadline" ]; then
    # spawn-failures.md의 grep-first 절차를 따른다. task-create/worker-start로 진행하지 않는다.
    exit 1
  fi
done
# End pre-dispatch boot-quiesce
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용 — 받은 문자열 그대로, issue #158) + CONTRACT_DIR 절대경로 + 제안서/구현 모드(제안서 모드면: contract-schema.md 스키마대로 AC 초안을 포함한 proposal-r<라운드>.json을 CONTRACT_DIR에 작성) + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "task-runner" -- \
  orca orchestration worker-start --task <task_id> --terminal <run-handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
DISPATCH_CREATED_VIA=worker-start   # self-recovery.md wait 루프의 dead-case 분기 입력 — SPEC_TEXT는 worker-start 복구 분기가 참조하지 않으므로 배선하지 않는다
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58 — "diff/report
# 본문을 직접 읽지 않는다" 원칙과 충돌하지 않는 근거도 그 문서에 있다).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 터미널에 대한 유일한 read는 위 dispatch-verify.md의 liveness probe(불투명 payload-echo 확인 —
#   issue #58)뿐이므로 recv는 기록하지 않는다(logging.md의 carve-out 규칙 — 실제
#   결과는 이 스킬이 직접 읽지 않고 다른 채널로 도착한다). term-<run-handle>.jsonl은 orca-workflow-task
#   자신이 소유하는 파일이다 — task-runner 자신의 왕복 내용은 그쪽이 스폰한 term-<impl_handle>.jsonl들에
#   이미 남는다.
log_dispatch --skill "orca-workflow-task" --role "task-runner" --issue "<issue-num>" --repo "<대상 repo>" \
  --task-id "<task_id>" \
  --terminal "<run-handle>" --worktree "<worktree 경로>" --provider "<resolved provider (claude-code/codex/agy)>" \
  --model "<resolved model>" --effort "<resolved effort>" --spec-text "$spec_text"
# SPEC_TEXT 사이드카는 배선하지 않는다 — worker-start 복구 분기(worker-abandon → worker-start --retry-of)는
# 같은 task_id를 재사용하므로 spec 원문을 다시 필요로 하지 않는다(self-recovery.md의 worker-start
# sub-branch). issue #112가 이 자리에 넣었던 사이드카 쓰기는 dispatch-inject 복구 분기 전용이었고,
# issue #94 1단계로 그 분기를 안 타게 되면서 함께 제거됐다.

# evaluate 호출 — REPL 필수(one-shot은 종료된 프로세스라 worker-start가 넣는 task 입력을 못 받음), agy는 제외한다
# (사유는 `~/.agents/orca-workflows/models/agy.md`가 정본). agy는 evaluate 내부 §2(agent e2e)의
# headless sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
if ! orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json; then
  exit 1
fi
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
# Pre-dispatch boot-quiesce (issue #84)
# freshly launched REPL은 tui-idle 뒤에도 MCP boot 출력이 남을 수 있으므로, cursor-scoped 새 출력이
# 멈출 때까지 확인한다. 전체 scrollback grep은 TUI repaint 잔재를 boot 출력으로 오판하므로 쓰지 않는다.
boot_deadline=$(( $(date -u +%s) + 60 ))
boot_initial="$(orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal read --terminal <evaluate-handle> --json)" || exit 1
cur="$(printf '%s' "$boot_initial" | jq -r '.result.terminal.latestCursor')"
while :; do
  sleep 12
  boot_read="$(orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal read --terminal <evaluate-handle> --cursor "$cur" --json)" || exit 1
  new="$(printf '%s' "$boot_read" | jq -r '.result.terminal.returnedLineCount')"
  if [ "$new" = "0" ]; then
    break
  fi
  cur="$(printf '%s' "$boot_read" | jq -r '.result.terminal.latestCursor')"
  if [ "$(date -u +%s)" -ge "$boot_deadline" ]; then
    # spawn-failures.md의 grep-first 절차를 따른다. task-create/worker-start로 진행하지 않는다.
    exit 1
  fi
done
# End pre-dispatch boot-quiesce
spec_text="<orca-evaluate SKILL.md 지침 + CONTRACT_DIR 절대경로와 대상 라운드 번호(검토 대상 proposal-r<n>.json·판정 산출 verdict-r<n>.json — 스키마·적대적 판정 지침·라운드 2+ 입력 격리 규칙은 contract-schema.md) + issue 원문 + issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + 요청 모드 + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration worker-start --task <task_id> --terminal <evaluate-handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
DISPATCH_CREATED_VIA=worker-start   # self-recovery.md wait 루프의 dead-case 분기 입력 — SPEC_TEXT는 worker-start 복구 분기가 참조하지 않으므로 배선하지 않는다
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 터미널에 대한 유일한 read도 마찬가지로 dispatch-verify.md의 liveness probe뿐이라
#   recv는 기록하지 않는다(위 task-runner 사이트와 같은 이유).
log_dispatch --skill "orca-workflow-task" --role "evaluator" --issue "<issue-num>" --repo "<대상 repo>" \
  --task-id "<task_id>" \
  --terminal "<evaluate-handle>" --worktree "<worktree 경로>" --provider "<resolved provider (claude-code/codex/agy)>" \
  --model "<resolved model>" --effort "<resolved effort>" --spec-text "$spec_text"
# SPEC_TEXT 사이드카는 위 task-runner 블록과 같은 이유로 배선하지 않는다(issue #94 1단계).
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
RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-workflow-task.txt")"   # §0에서 남긴 사이드카
spec_text="<round 번호 + CONTRACT_DIR 절대경로(파일명은 contract-schema.md 컨벤션으로 결정론적 — task-runner행이면 직전 verdict-r<n-1>.json을 읽고 proposal-r<n>.json 작성, evaluator행이면 라운드 2+ 입력 격리 규칙대로 원본 issue·proposal-r<n>.json·자신의 직전 verdict만 입력) + orphan-폴백 계약(§0) 전문>"
orca_call_with_retry "orca-workflow-task" "contract-round" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "contract-round" -- \
  orca orchestration worker-start --task <방금 만든 task_id> --worktree current \
  --terminal <재-engage 대상 handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
DISPATCH_CREATED_VIA=worker-start   # self-recovery.md wait 루프의 dead-case 분기 입력 — SPEC_TEXT는 worker-start 복구 분기가 참조하지 않으므로 배선하지 않는다
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(worker-start에도 동일하게 필요).
# 로그 — logging.md §1 assign + §2 meta/sent를 log_dispatch()가 한 호출로 원자적으로 기록한다(issue #68).
#   이 사이트도 recv는 기록하지 않는다(위 두 사이트와 같은 이유 — 결과는 check --wait으로 수신).
log_dispatch --skill "orca-workflow-task" --role "contract-round" --issue "<issue-num>" --repo "<대상 repo>" \
  --task-id "<방금 만든 task_id>" --terminal "<재-engage 대상 handle>" --worktree "<worktree 경로>" \
  --provider "<라운드 1에서 resolve한 provider (claude-code/codex/agy) — 재-resolve 없이 재사용>" \
  --model "<라운드 1에서 resolve한 model — 재사용>" --effort "<라운드 1에서 resolve한 effort — 재사용>" \
  --spec-text "$spec_text"
```

- self-recovery.md의 재시도 예산까지 소진해도(최초 대기 1회 + `worker_abandon_retry` 최대 2회, 각
  최대 1시간 — 최악의 경우 약 3시간) `completed`가 안 되면 체크포인트 — 재진단하지 않고
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차로.

## 2. Generate

`orca-task-runner` 호출, 결과로 **task 전체 diff 경로** 또는 **`GATE_FAIL`**을 받는다(`orca-task-runner`가 자기 task-레벨 게이트를 재시도 한도(2회) 안에 못 넘긴 경우 — `skills/orca-task-runner/SKILL.md` §6). §4의 FAIL 재시도로 돌아온 호출이면 spec을 아래 템플릿대로 구성한다 — findings를 prose로 요약하지 않고 파일 경로만 넘긴다:

```
spec_text="<issue 번호 + 대상 repo(logging.md §1 repo 필드용, issue #158) + CONTRACT_DIR 절대경로 + 구현 모드 + 직전 attempt 번호 + \"CONTRACT_DIR의 eval-report-a<attempt>.json과 최종 라운드 proposal(가장 큰 proposal-r<n>.json — 네가 직접 확인)을 이 순서로 전부 읽어라 — findings를 요약해 넘기지 않는다\" + orphan-폴백 계약(§0) 전문>"
```

확정 계약 라운드 번호는 이 스킬이 치환하지 않는다 — 확정 AC의 정본은 "최종 라운드(가장 큰 n) proposal"이고(contract-schema.md — override 경로에서는 정정 라운드(r4+)가 나중에 추가될 수 있어 코디네이터가 아는 번호가 낡을 수 있다, issue #130), generator가 CONTRACT_DIR에서 직접 확인한다(이 스킬은 feedback 본문도 확정 AC 본문도 중계하지 않는다).

**Dispatch 실행부**(issue #128 — 이 사이트는 §1의 task-runner 사이트와 동일한 강제를 받는다): 구현
모드 호출은 즉석 경로가 아니라 §1 round-1 task-runner 블록의 레시피 그대로다 — §1 협상에서 쓴
`<run-handle>` 터미널이 살아 있으면 `terminal create`/boot-quiesce만 건너뛰고 `task-create` →
`dispatch --inject` → 미전송 확인(dispatch-verify.md) → `log_dispatch` → SPEC_TEXT 사이드카 →
self-recovery 대기를 같은 순서로 태우고, 죽었거나 없으면 §1 블록 전체(스폰부터)를 태운다.
`orca-task-runner`를 dispatch하지 않고 코디네이터가 직접 코드를 작성·수정해 §3로 가는 경로는
존재하지 않는다(이 스킬 서두의 "코드를 생성하지도, 평가하지도 않는다" — issue #128에서 관측된
이탈이 정확히 이것이거나, 최소한 로그로 반증 불가능했다). 로그는 dispatch와 같은 블록에서 즉시,
`--attempt`를 실어 남긴다(§1 제안서 모드 dispatch와 유일하게 다른 인자 — eval-report-a<attempt>.json과
join되는 키):

```bash
log_dispatch --skill "orca-workflow-task" --role "task-runner" --issue "<issue-num>" --repo "<대상 repo>" \
  --task-id "<task_id>" --terminal "<run-handle>" --worktree "<worktree 경로>" \
  --provider "<resolved provider>" --model "<resolved model>" --effort "<resolved effort>" \
  --spec-text "$spec_text" --attempt <attempt 번호 — 1부터, §4 FAIL 재시도마다 +1>
```

**GATE_FAIL 라우팅** — `orca-evaluate`를 호출하지 않고 바로 §5로 간다. `orca-task-runner`가 이미 자기 재시도 예산을 다 썼으므로 여기서 추가 재시도를 걸지 않는다(이중 카운팅 방지). §5 보고에 "evaluate 호출 안 됨(GATE_FAIL) — 기계적 게이트 실패"를 명시해 아래 FAIL/ESCALATE와 구분한다. 이때도 §4의 outcome 로그 라인을 `outcome:"GATE_FAIL"`로 남긴다(§4를 거치지 않으므로 여기서 직접).

## 3. Evaluate

**Generate 감사 게이트**(issue #128, evaluator dispatch 전에 기계적으로 1회): 이번 attempt의
`role="task-runner"` assign 레코드가 실제로 남아 있는지 확인한다 — 없으면 §2가 정식 dispatch 없이
통과된 것이므로(코디네이터 직접 편집 포함, 어느 쪽이든 §2 위반) evaluate로 넘어가지 않고 §2로
돌아가 레시피대로 실행한다. 직접 만든 변경이 이미 worktree에 있어도 그것을 평가에 넘기는 경로는
없다:

```bash
find "$HOME/.local/state/orca-workflows/logs" -name 'assignments-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null \
  | jq -e -s --arg issue "<issue-num>" --arg repo "<대상 repo>" --argjson k <attempt 번호> \
      '[.[] | select(.event=="assign" and .skill=="orca-workflow-task" and .role=="task-runner"
                     and .issue==$issue and .repo==$repo and .attempt==$k)] | length > 0' >/dev/null \
  || echo "GENERATE-AUDIT-FAIL: attempt <attempt 번호>의 task-runner assign 없음 — §2로 돌아간다" >&2
```

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
  # 스쿼시 커밋 메시지를 이 스킬이 소유한다(issue #115) — 지정하지 않으면 gh pr merge는 커밋이
  # 1개뿐인 브랜치에서 그 원 커밋 메시지를 그대로 스쿼시 메시지로 쓴다. 그 원 커밋에 우연히
  # `Closes #N` 트레일러가 있으면(흔한 커밋 컨벤션), 위 link_pr_for_close가 관리하는 PR 본문에서
  # keyword를 뺐어도 이 두 번째 채널로 issue가 그대로 자동 종료된다(MediCount#540 실측,
  # issue-trackers/github.md의 link_pr_for_close 문서 참고). --subject/--body를 명시해 auto-close
  # 채널을 link_pr_for_close가 관리하는 PR 본문 하나로 고정한다.
  pr_title="$(gh pr view "$pr_num" --json title -q .title)"
  pr_body="$(gh pr view "$pr_num" --json body -q .body)"
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
    # 머지 판정 근거는 gh pr merge의 종료 코드가 아니라 PR의 실제 상태다(issue #135):
    # --squash --delete-branch는 원격 머지에 성공한 뒤 로컬 브랜치 정리에서 비-0 종료할 수 있고
    # (main이 다른 worktree에 체크아웃 — 이 스킬의 기본 배치에서 구조적), 이미 머지된 PR은
    # mergeStateStatus=UNKNOWN이라 아래 어느 분기에도 안 걸려 예산 소진까지 폴링하게 된다.
    # 매 회차 진입 시(재실행 재개 케이스, #72) + merge 시도 직후 두 곳에서 상태로 판정한다.
    if [ "$(gh pr view "$pr_num" --json state -q .state)" = "MERGED" ]; then merged=true; break; fi
    gh pr merge "$pr_num" --squash --delete-branch --subject "$pr_title" --body "$pr_body" || true   # 종료 코드는 판정에 쓰지 않는다
    if [ "$(gh pr view "$pr_num" --json state -q .state)" = "MERGED" ]; then merged=true; break; fi
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
  if [ "$merged" = "true" ]; then
    # 원격 브랜치 정리 — 머지 판정과 분리된 best-effort 후처리(issue #135). --delete-branch가
    # 로컬 정리 단계에서 죽으면 원격 브랜치가 남을 수 있다. 실패해도(이미 삭제됨 포함) outcome에
    # 영향을 주지 않는다.
    git push origin --delete "<task-branch>" 2>/dev/null || true
  fi
  # merge_outcome이 비어있지 않으면 merge되지 않은 것이다 — logging.md §1 outcome 레시피대로 그 값을
  # 남기고(GATE_FAIL과 같은 원칙: 추가 재시도 없이) 바로 §5로 분기한다. printf가 남긴
  # 마지막 state와 실패 check 이름·링크(gh pr checks "$pr_num")를 §5 보고에 첨부한다.
  ```

  머지 성공 시(`merged=true`) **`is_open(task-issue-num)`이 true면 `close_issue(task-issue-num, "Merged via PR #$pr_num")`를 호출**한다 — 코드호스팅(PR 머지)은 GitHub 전용이라 미변경이고, issue 종료는 트래커 무관하게 이 한 경로로 처리된다: GitHub는 위 `link_pr_for_close`가 보통 이미 닫아둬서 여기선 안전망(no-op)이고, Jira 등 merge-magic이 없는 트래커는 이 호출이 유일한 종료 경로다. `close_issue`가 "완료" transition을 찾지 못하면 그 시점에서 `outcome=NO_DONE_TRANSITION`을 직접 로깅하고 §5로 간다.

  **`is_open`이 이미 false면**(issue #115 — GitHub의 정상 케이스가 흔히 이렇다: `link_pr_for_close`가
  관리하는 PR 본문 keyword로 머지 시점에 이미 자동 종료돼 있다) `close_issue`를 부르지 않는 대신
  **`add_comment(task-issue-num, "Merged via PR #$pr_num")`를 호출**한다 — 이 스킬은 그 close가
  정상 채널(위 keyword)로 일어난 건지 다른 원인인지 구분할 수 없으므로, 거짓 no-op으로 감사 코멘트
  자체가 유실되지 않도록 무조건 코멘트만은 남긴다. `close_issue`(전환+코멘트를 한 번에 하는
  adapter 오퍼레이션)와 달리 `add_comment`는 상태를 건드리지 않는다. (`is_open`/`close_issue`/
  `add_comment`/`link_pr_for_close`는 실제 셸 커맨드가 아니라 tracker adapter 오퍼레이션이다 —
  문자 그대로 셸에 붙여넣지 말 것.)

  task 종료(`merge_outcome`이 남은 경우는 예외 — 아래 CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT 참고, task 종료가 아니라 §5로 간다).
- FAIL → 재시도 카운터 확인. **2회 미만이면** `orca-task-runner`에 재-dispatch(§2로 — spec 구성은 §2의 FAIL 재시도 템플릿을 그대로 따른다: 방금 FAIL한 attempt 번호 + `eval-report-a<attempt>.json`·`proposal-r<확정라운드>.json` 두 파일 포인터, §1 라운드 2+ relay와 같은 원칙). **2회 도달하면** §5로.
- ESCALATE → 재시도 카운트 무관하게 즉시 §5.
- CI_GATE_FAIL → (PASS 라우팅 안에서만 발생 — 위 참고) repo의 CI required check 실패 확정 — 추가 재시도
  없이 즉시 §5. `orca-evaluate`는 이미 PASS를 냈으므로 재-dispatch 대상이 아니다 — merge 앞
  게이트가 별도로 막은 것.
- CI_GATE_TIMEOUT → (같은 위치) budget 안에 required check가 완주하지 못했거나 merge 거부 원인이
  판별되지 않았다는 뜻이다(코드 실패로 확정된 것이 아니다) — 추가 재시도 없이 즉시 §5.
- MERGE_CONFLICT → (같은 위치) base와의 텍스트 충돌(`mergeStateStatus=DIRTY`) 또는
  `gh pr update-branch` 실패 — 자동 rebase/충돌 해소를 시도하지 않고 즉시 §5.

라우팅 판정마다 outcome 이벤트를 할당 로그와 같은 파일에 남긴다 — `issue`/`task_id`로 assign 이벤트와 join해야 "어떤 할당이 어떤 결과를 냈는지"를 사후 감사할 수 있다(할당 기록만으로는 품질 판정 불가). 로그 — `~/.agents/orca-workflows/logging.md` §1 `outcome` 레시피 그대로 실행(enum 값은 그쪽이 정본 — 여기 복제하지 않는다): `skill="orca-workflow-task"`, `issue=<issue-num>`, `repo=<대상 repo>`, `outcome=<위 라우팅 분기에서 결정된 값>`, `retry=<재시도 횟수>`.

## 5. Escalation·보고

§4가 PASS로 끝나면(merge + issue close): 보고 채널로 완료를 알린다 — spawn된 세션이면
`worker_done`(outcome=PASS), entry 세션이면 사람에게 보고하고 종료.

그 외 outcome(FAIL 한도 도달·ESCALATE·GATE_FAIL·CONTRACT_ESCALATE·CONTRACT_SCHEMA_STALE·CI_GATE_FAIL·
CI_GATE_TIMEOUT·MERGE_CONFLICT·NO_DONE_TRANSITION)이면 아래 보고 내용을 조립한 뒤 mode로 분기한다:

보고 내용: issue 번호, PASS/FAIL/ESCALATE/GATE_FAIL/CONTRACT_ESCALATE/CONTRACT_SCHEMA_STALE/CI_GATE_FAIL/CI_GATE_TIMEOUT/MERGE_CONFLICT/NO_DONE_TRANSITION 중 어느 것으로 왔는지와 그 근거, 재시도 횟수, resolved providers/models. GATE_FAIL은 `orca-evaluate`가 아예 호출되지 않았다는 뜻이므로 그 사실을 반드시 표시한다. **ESCALATE**가
evaluator의 판정이 아니라 이 코디네이터 자신의 orchestration/terminal 호출이 Claude Code auto-mode
분류기에 거부되어 발생한 경우(§0, `spawn-failures.md`의 classifier 거부 행, issue #118)는 `detail`에
이 실행의 `CONTRACT_DIR` 절대경로와, 확인된 경우 아직 살아있는 task-runner 터미널 핸들을 반드시
담는다 — 재스폰(§0에서 서술한 대로 사람 또는 `orca-workflow-epic`이 수행)이 이 값들로 라운드를 처음부터
다시 돌지 않고 재개하도록. **CONTRACT_ESCALATE**는 contract 협상이 라운드 한도에도 `ac_fidelity` 이견으로 끝났다는 뜻이다 — 코드 생성 전이므로 diff가 없다. `override.json`의 `unresolved_reasons`를 그대로 표시한다(무엇을 만들지에 대한 generator/evaluator의 이견 — 사람이 issue를 명확히 하거나 방향을 정한다). §1의 fail-closed 분기(override.json 자체가 없음)로 온 경우면 이견 내용 대신 그 사실 — generator가 기록 없이 라운드 한도에 도달함 — 을 표시한다. **CONTRACT_SCHEMA_STALE**는 override 완료(override.json mtime)가 proposal-r3 요구사항 도입 시각(commit 79b7c3b, 2026-08-12T09:44:57+09:00)보다 이전이라는 뜻이다 — 위반이 아니라 구버전 세션이므로 이 두 시각을 그대로 표시한다. 사람의 선택지: (a) `verdict-r2.json`의 미해소 `reasons`를 반영해 `proposal-r3.json`을 수동으로 작성한다 — 이때 worktree에 구현이 이미 있어도 **§2를 기계적으로 재실행해 이미 끝난 구현을 덮어쓰지 않도록 주의한다**: §2 "Dispatch 실행부"는 "`orca-task-runner`를 dispatch하지 않고 코디네이터가 직접 코드를 작성·수정해 §3로 가는 경로는 존재하지 않는다"(issue #128)고 명시하므로, 기존 diff를 그대로 §3 evaluate로 넘기는 정식 경로가 이 스킬에 현재 없다 — 이 공백은 별도 issue #161로 추적하며, 사람이 상황을 보고 직접 진행 방식을 정한다. 구현이 없으면 정상적으로 §2부터 재개한다. (b) 완료된 작업을 폐기하고 재협상을 지시한다. **CI_GATE_FAIL**은 `orca-evaluate`가 PASS를 냈는데도 repo의 CI required check가 merge를 막았다는 뜻이므로, 실패한 check 이름과 로그 링크(`gh pr checks <pr_num>`)를 그대로 표시한다 — 사람이 다시 조회하지 않게. **CI_GATE_TIMEOUT**은 budget 안에 check가 완주하지 못했거나 merge 거부 원인이 판별되지 않았다는 뜻이므로(코드 실패로 확정 아님), 마지막 `mergeStateStatus`와 check 상태 스냅샷을 표시한다. **MERGE_CONFLICT**는 base와의 충돌로 자동 merge가 불가능하다는 뜻이다 — 충돌 지점 정보를 표시하고, rebase/충돌 해소 여부는 사람이 결정한다. **NO_DONE_TRANSITION**은 tracker adapter의 `close_issue`가 "완료" transition을 찾지 못했다는 뜻이다(트래커 문서에 명시 없음, 또는 명시된 이름이 현재 상태의 available transition 목록에 없음) — 발생 지점은 §4의 merge 성공 후 close 단계이고, outcome 로깅은 그 시점에 §4가 직접 한다.

- **hitl** — 질문을 올리고 응답까지 block한다: entry 세션이면 사람에게 직접, spawn된 세션이면
  ask(decision gate)로 호출자에게(§0 보고 채널). 선택지: 계속(응답의 피드백을 반영해 §2부터 재시도 —
  사람 지시에 의한 재시도는 §4의 FAIL 재시도 한도와 별개로 센다) / 중단(아래 afk와 같은 보존 절차 후
  outcome 확정). 요구사항 자체를 다시 논의하는 재계획은 이 스킬 범위 밖이다 — issue 수정 후 재호출.
- **afk** — 질문 없이 작업을 보존하고 outcome을 확정한다. 보존 = worktree·branch를 삭제하지 않고,
  CONTRACT_DIR 산출물·eval-report·로그를 그대로 두고(전부 워크스페이스 밖 영속이라 추가 복사 없음),
  §4에서 남긴 outcome 이벤트가 기록의 정본이다. spawn된 세션이면 `worker_done`으로 outcome을 전달하고
  종료. 재개 경로는 같은 issue로의 재호출이다 — 재호출된 세션은 §0의 재개 분기가 CONTRACT_DIR
  아티팩트 스캔으로 진행 상태를 복원해 해당 §부터 이어간다(§1부터 다시 시작하지 않는다).

## 폴백

- orca 런타임 불가: transport만 우회 — `orca-task-runner`/`orca-evaluate`의 폴백 규칙을 그대로 따르며, 이 스킬은 두 결과를 이어주는 역할만 계속한다. assign/outcome 로그도 동일하게 남긴다(`terminal` 필드만 대체 식별자로).
- 폴백 발동은 항상 사용자에게 보고한다.
