---
name: orca-task-runner
description: Use when generating the implementation for one task (issue) — proposes an implementation-and-verification contract to orca-evaluate, then fans out subtasks across Claude Code/Codex/agy terminals in dependency-ordered waves. Subtask gates are mechanical only (typecheck/unit test/lint/format) — never an agent reviewer; task-level review belongs to orca-evaluate. Self-relative — works identically whichever provider runs this session. Do NOT use for ad-hoc multi-agent fan-out or terminal control (use the `orchestration` or `orca-cli` skills) — this skill is invoked only by orca-workflow coordinators, never by phrase-matching.
compatibility: Requires the `orca` CLI (skill set last verified against Orca app 1.4.180), the `~/.agents/orca-workflows/` symlink to this repo's orca-workflows/, and the `gh` CLI.
---

# Orca Task Runner

하나의 task(issue)를 구현한다. **생성만** 한다 — 평가는 이 스킬의 책임이 아니다(`orca-evaluate`가 담당). subtask 단위 리뷰어 역할은 두지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- feature worktree에서 실행 중이어야 한다(main 체크아웃에서 금지). `terminal create`(§3, agy pre-create)는
  `--worktree active`로 생성한다(Orca 공식 예시와 일치). `worker-start`는 다르다 — `--worktree active`는
  `--agent`·`--terminal` 두 조합 모두에서 `selector_not_found`로 항상 실패한다(라이브 확인, 2026-08-11).
  `--agent` 호출은 `--worktree current`를 쓰고, `--terminal` 호출은 터미널 핸들이 이미 worktree를
  고정하므로 `--worktree`를 아예 생략한다 — §5 템플릿 참조.
- **격리 가드(issue #136)** — 위 전제는 §2/§3/§5의 fan-out 경로(subtask-impl 워커는 `--worktree active`로
  스폰되므로 항상 격리된다)에는 이미 지켜진다. 사각지대는 **이 세션 자신이 fan-out 없이 직접 커밋하는
  경우**(예: 단일 trivial subtask라 wave를 생략하고 스스로 구현)다 — dispatch가 이 세션을 메인
  체크아웃 위에 얹었는데 fan-out도 안 쓰면, 그 무엇도 격리를 보장하지 않는다(실측: studio-hevv/
  selah-android issue #22, task-runner가 메인 worktree에서 직접 `git checkout -b` + commit해 main의
  HEAD가 feature 브랜치로 전환된 채 커밋까지 진행됨). 이 세션이 첫 `git commit`을 실행하기 **직전에**
  매번 아래를 확인한다 — 메인 체크아웃은 `.git`이 디렉터리, `git worktree add`로 만든 격리 worktree는
  `.git`이 gitdir 포인터 파일이라는 구조적 차이를 쓴다(경로 하드코딩·비교 불필요):
  ```bash
  if [ -d ".git" ]; then
    # 메인 체크아웃 위에서 실행 중 — 격리 없이 커밋하지 않는다. 브랜치를 만들며 즉시 격리 worktree로
    # 옮긴다(이후 이 세션의 나머지 작업은 그 worktree 안에서 계속한다).
    git worktree add "<격리 worktree 절대경로 — 예: ~/worktrees/<repo>/<branch>>" -b "<브랜치명>" origin/main
    cd "<격리 worktree 절대경로>"
  fi
  ```
- claude 워커는 `worker-start --agent`로 스폰한다 — approval/sandbox는 Orca 계정 레벨 Agent 설정
  프리셋이 맡는다. `--permission-mode` 같은 per-dispatch 플래그는 없고, 필요하지도 않다
  (`orca-workflows/self-recovery.md`의 `worker-release` 절, 2026-08-08/2026-08-11 라이브 검증). 이
  결정을 다시 열지 않는다.
- **codex는 `--agent`를 쓰지 않는다(2026-08-11 라이브 재현으로 확정, MCP 부팅 대기와 무관).**
  `worker-start --agent codex`는 codex TUI가 첫 프레임을 그리기도 전에 bracketed-paste로 task
  프롬프트를 흘려보낸다 — 그 시점 터미널엔 아직 codex 프로세스의 alt-screen도 없으므로 paste는
  스크롤백 잡음으로 사라지고 composer는 계속 빈 placeholder로 남는다(직접 `terminal read`로 확인,
  이후 40초+ 관찰해도 회복 안 됨). `worker-show`는 이 상태에서도 `stage:"input_accepted"`를 반환한다
  — 이 필드는 제출은커녕 **도달**도 보장하지 않는다. 반대로 터미널을 미리 만들어 완전히 정착시킨
  뒤(§3 pre-create + `dispatch-verify.md`의 boot-quiesce 확인) `worker-start --terminal`로 배정하면
  같은 프롬프트가 정상 전달되고 codex가 실제로 작업을 시작한다(같은 세션에서 직접 검증). 그러므로
  codex는 agy와 같은 `--terminal` pre-create 경로를 쓴다 — 단 이유는 다르다: agy는 `--agent agy`가
  구조적으로 없어서(아래), codex는 `--agent codex`가 있지만 그 내부 injection 타이밍이 codex TUI 준비
  전이라 신뢰할 수 없어서다. `worker-release`는 codex에는 쓰지 않는다 — `--terminal` 경로로 배정한
  dispatch는 provider와 무관하게 `ownershipState: "external"`이 되고, 그 상태의 `worker-release`는
  `releaseState: "not_requested"`로 아무 것도 안 하는 형식적 no-op이다(라이브 확인, 2026-08-11 —
  release 호출 후에도 터미널이 `terminal list`에 그대로 남음). agy도 원래부터 같은 이유로
  `worker-release`를 쓰지 않았다 — codex가 새로 그 그룹에 합류한 것뿐이다.
- agy만 `--agent` 자체가 없음: `--agent agy`는 구조적으로 지원되지 않으므로(`orca account list`에
  gemini/agy 슬롯 자체가 없음) §3의 `terminal create --command` 템플릿으로 approval/sandbox를
  명시적으로 계속 지정한다 — 근거·예외(headless read-only 등)는
  `~/.agents/orca-workflows/models/codex.md`/`models/agy.md`가 정본이다. codex·agy 둘 다 안전 전제는
  워크트리 격리이므로(§0 첫 불릿의 main 체크아웃 금지와 같은 전제), 격리 밖에서 이 posture로 launch
  하지 않는다.
- 모델·effort는 매 launch 전 아래 문서에서 subtask 유형(전사·기계적 / 통합·판단 / 아키텍처)에 맞게 고른다. 값을 이 스킬에 복제하지 않는다.
  - `~/.agents/orca-workflows/model-selection.md`
  - `~/.agents/orca-workflows/models/claude-code.md`
  - `~/.agents/orca-workflows/models/codex.md`
  - `~/.agents/orca-workflows/models/agy.md`
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §3(launch)과 §5(대기)에서
  이 확인이 걸리는 지점을 표시한다.
- **MCP 서버 인증 전제**(세션 시작 시 1회 확인) — §3/§5에서 스폰하는 워커 터미널이 쓰는 MCP 서버
  (예: Context7)는 스폰 전에 이미 인증이 끝나 있거나, 워커 프로필에서 비활성화돼 있어야 한다. 로그인
  프롬프트가 스폰된 세션을 막으면 주입된 spec이 처리되지 않고 사람이 직접 ESC로 해제해야 한다 —
  dispatch spec마다 그때그때 예방 문구를 덧붙이는 방식은 막지 못하는 것이 실측됐다(issue #60). 막히면
  재진단 없이 `~/.agents/orca-workflows/spawn-failures.md`의 해당 row로.
- 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature:
  `~/.agents/orca-workflows/spawn-failures.md`, issue #42), §2·§3·§5의 `orca orchestration`/
  `orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh`
  후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.
- **이 issue에 대해 이 세션이 처음이 아닐 수 있다면**(이전 세션이 도중에 죽어서 재개하는 경우) 새 wave를 시작하기 전에 orphan부터 정리한다 — §3/§5 wave telemetry는 이 세션이 살아서 markdown 지침을 끝까지 실행해야만 남는 best-effort 기록이라, 세션이 wave 도중 죽으면(그리고 그게 바로 우리가 잡으려는 CPU 경합의 극단적 형태다) `wave_start`만 남고 `wave_end`가 영영 안 남을 수 있다:

  ```bash
  find ~/.local/state/orca-workflows/logs -name 'waves-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null | jq -s --arg issue "<issue-num>" '
    [.[] | select(.issue == $issue)] as $rows
    | ($rows | map(select(.event == "wave_start") | .wave_index)) as $starts
    | ($rows | map(select(.event == "wave_end") | .wave_index)) as $ends
    | $starts - $ends
  '
  ```

  결과가 비어있지 않으면(orphan `wave_index` 존재) 이전 세션이 그 wave 도중 죽었다는 뜻이다. `orca orchestration task-list --json`/`orca terminal list --json`으로 그 wave의 subtask가 실제로 끝났는지 확인한 뒤, §5의 `wave_end` 포맷대로 `outcome:"crash_recovered"`로 채워 넣는다(retry_count는 알 수 없으면 `null`). 이 값 — "wave 크기 N에서 세션이 죽었다" — 이 바로 best-effort 로그가 놓칠 뻔한 가장 중요한 데이터 포인트이므로, 확인 없이 새 wave로 넘어가지 않는다.

- **Run 생성**(세션 시작 시 1회): Run을 만들고 바인딩한 뒤 `run_id`를 사이드카 파일에 남긴다(§5는
  별도 fenced block이라 셸 변수가 그대로 넘어가지 않는다 — 아래 `spec_sidecar`와 같은 이유). 파일명의
  `<project-slug>`는 spec으로 받은 CONTRACT_DIR 경로의 상위 디렉토리명이다(logging.md §3, issue #159):

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<issue 번호> task implementation" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-task-runner.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-task-runner.txt"
  ```

  이후 §5의 모든 `worker-start`/`check --wait`/`--ack` 호출 앞에서
  `RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-task-runner.txt")"`로 다시 읽는다.
  `orca-workflow-task`가 이 세션을 스폰할 때 자기 Run을 갖고 있더라도 그건 재사용하지 않는다(Run이 섞이면
  서로 다른 세션의 `worker_done`이 잘못된 mailbox로 전달된다 — `~/.agents/orca-workflows/self-recovery.md`
  참고).

## 1. Contract 제안 (generator 역할)

`orca-workflow-task`가 이 task를 넘기면, 코드를 쓰기 전에 **제안서**를 먼저 쓴다 — 프리텍스트가 아니라
spec으로 받은 `CONTRACT_DIR`에 `proposal-r<라운드>.json`으로,
`~/.agents/orca-workflows/contract-schema.md`의 스키마 그대로:

- **acceptance criteria 초안**(`draft_acceptance_criteria`) — issue 원문에서 도출한, 판정 가능한
  완료 기준. 항목마다 id를 부여한다. issue 본문에 AC류 섹션이 이미 있으면 초안의 입력으로 쓰되,
  정본은 이 초안이다.
- 구현 범위(`scope`) — 무엇을 만들 것인가, 어떤 파일을 건드릴 것인가. **사실 서술만** — "왜
  충분한가"류 정당화는 어떤 필드에도 넣지 않는다(스키마 문서의 "라운드 2+ 입력 격리" 참고).
- 검증 방법(`verification_plan`) — 구체적인 파일/함수/테스트로, 항목마다 커버하는 ac id를
  `covers`로 참조하고 이 항목이 fix 이전에 어떻게 실패하는지(또는 왜 실패할 수 없는지)를 `fails_before_fix`에 적는다. 어떤 항목도 커버하지 않는 ac id가 남거나 `fails_before_fix`가 비어 있거나 없으면 반려 대상이다.
- 의도된 destructive 오퍼레이션(`destructive_operations`) — 빈 배열이 "명시적 없음"이다. 이 선언은
  나중에 `orca-evaluate` §3가 diff에서 실제로 flag된 destructive-op와 대조하는 근거가 된다.
- 이 변경으로 red가 되거나 갱신이 필요한 기존 테스트·단언(`existing_tests_affected`, file:line) —
  빈 배열이 "명시적 없음"이다. `verification_plan`은 새로 추가할 검증만 담는다 — 기존에 green이던
  단언 중 이 변경으로 red가 될 것은 여기 별도로 열거한다(정확 일치 단언, 게이트 자체를 막는 회귀를
  특히 놓치기 쉽다).

`orca-evaluate`가 이 제안(AC 초안 포함)을 **원본 issue 전문**에 대조해 검토하고 `verdict-r<라운드>.json`으로 판정을 남긴다. 반려되면 그 `reasons`를 읽고 **수정된 사실로** 다시 제안한다(`proposal-r2.json` — 서술형 반박이 아니라 필드 수준의 변경으로 응답한다). 각 라운드는 별도 dispatch로 도착한다: 제안서를 쓰고 나면 이번 턴을 끝낸다(주입된 preamble의 worker_done 지시대로), 같은 턴 안에서 반려 여부를 기다리거나 폴링하지 않는다. **최대 2 라운드(조건부로 3 — 아래 "라운드 2→3 조건부 연장" 문단 참고).** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 진행한다 — evaluator의 verdict 파일은 수정하지 않고, `override.json`(스키마 문서 참고)에 미해소 `reasons`를 복사해 남긴 **직후 같은 스텝에서 `proposal-r3.json`을 새로 쓴다**(`verdict-r2.json`의 reasons 중 해소한 항목을 반영한 최종 확정 계약, `round: 3`, verdict 없음 — 쓰기 순서는 override.json 먼저, 스키마 문서의 "override 후속 라운드" 절이 정본, issue #130). 동결된 이전 라운드 파일(`proposal-r1/r2`)은 절대 제자리 수정하지 않는다. 이후 모든 단계(§2 subtask 분해 포함)가 참조하는 확정 AC는 최종 라운드(가장 큰 n) proposal의 `draft_acceptance_criteria`다.

**라운드 2→3 조건부 연장**(`contract-schema.md`): 라운드2 반려 사유가 `plan_coverage`뿐이면,
코디네이터가 override 모드 대신 "라운드3 제안서 작성" 모드로 재호출할 수 있다 — 그 경우 이 스킬은
평소 라운드 갱신과 동일하게(§1 본문의 "반려되면...다시 제안") `verdict-r2.json`을 읽고
`proposal-r3.json`을 작성한다(override.json 작성 없음). 라운드3도 반려되면 그때 override
모드로 재호출된다 — 그 경우 `override.json`(`final_round: 3`) + `proposal-r4.json`(최종
확정)을 쓴다(위 override 절차와 동일하되 라운드 번호만 한 칸씩 밀림).

## 2. Subtask DAG 구성

합의된 범위로 subtask를 쪼갠다. 각 subtask가 만들/수정할 파일 목록을 비교: **겹치면 `--deps` 순차 의존, 독립이면 같은 wave.** 판정이 애매하면 보수적으로 의존 처리.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
spec_text="<subtask 본문 + 아래 필수 항목>"
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration task-create --spec "$spec_text" --deps '["task_xxx"]' --retry-request "$(uuidgen)" --json
# spec_text 사이드카(로그 아님 — 일회성 핸드오프 파일) — logging.md §2의 sent 레시피는 "task-create
# --spec에 쓴 텍스트와 동일한 문자열"을 요구하는데, 그 원문을 이 세션이 실제로 들고 있는 시점은
# 지금뿐이다(§5 dispatch는 몇 wave, 잠재적으로 긴 시간 뒤). 이 시점엔 아직 dispatch 대상 handle을
# 몰라 term-<handle>.jsonl에 바로 쓸 수 없으므로, task_id로 키를 잡은 사이드카에 남겨 §5가 handle을
# 알게 된 시점에 그대로 읽어 쓰게 한다 — §5가 읽은 직후 지운다(logs/ 아래 다른 파일과 달리 보존
# 대상이 아니다).
install -d -m 700 ~/.local/state/orca-workflows/logs
printf '%s' "$spec_text" > "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
chmod 600 "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"
```

subtask spec 필수 항목: ①구체적 작업 내용(코드 블록 포함 그대로) ②커밋 대상 브랜치·worktree 명시 ③resolved provider/model/effort 기록 ④"막히면 ask로 blocking 질문" ⑤"완료 시 preamble 지시대로 worker_done(payload에 filesModified)" ⑥**병렬 커밋 안전 규칙**(같은 worktree를 공유하는 병렬 워커가 서로의 미완성 변경을 덮어쓰지 않도록): `git add` 명시 경로만·`git commit -m "<msg>" -- <files>` pathspec 필수·index.lock 재시도. Orca의 attribution-trailer 자동 삽입 wrapper는 `git commit -m "<msg>" -- <files>` 실행 시 `-- <pathspec>` 뒤에 `-m`을 추가로 삽입해 pathspec 파싱을 깨뜨리므로, 커밋 메시지에 원하는 trailer를 미리 포함시켜 wrapper의 추가 삽입을 무해화한다. ⑦**연결 실패 자동 재시도 + orphan 폴백**: worker_done을 포함해 네가 보내는 `orca orchestration`/`orca terminal` 호출은 항상 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` 후 `orca_call_with_retry`로 감싼다(issue #42). 호출 형태는 `orca_call_with_retry "<skill>" "<role>" -- <command...>` (예: `orca_call_with_retry "orca-task-runner" "subtask-worker" -- orca orchestration send ...`)이며, skill/role 인자를 생략하면 `"orca"`/`"orchestration"`이 라벨 인자로, `"send"`가 명령어로 잘못 소비된다. wrapper가 exhausted를 반환하면 ask를 포함한 추가 orchestration 호출을 시도하지 않는다 — 같은 죽은 transport를 타므로 똑같이 실패한다(issue #41). 대신 보내려던 결과 전문(worker_done payload, 없으면 현재 상태 요약)을 worktree 루트에 `.orca-orphaned-result-<task_id>.json`으로 저장하고(커밋 금지 — ⑥의 명시 경로 규칙이 이미 이를 배제한다), 터미널에 `ORPHANED_RESULT <task_id> <파일 절대경로>` 한 줄을 출력한 뒤 명확히 멈춘다(이후 도착하는 무관한 프롬프트를 집어삼키지 말 것).

## 3. Wave 준비

wave 크기는 고정 상한 없이 머신 리소스 상황을 보며 판단한다(§5 wave telemetry가 적정치 계측의 근거 데이터다) — 단 무제한이 아니다: 한 wave에서 스폰 실패·timeout 재시도가 2회 이상 발생하면 그 즉시 wave 크기를 3 이하로 제한하고 사용자에게 보고한다. provider는 자유 선택(claude-code/codex/agy 아무거나, 토큰 효율을 위해 섞어도 됨) — 단 `model-selection.md`의 "Quota check before pinning"에서 제외된 provider는 후보에서 뺀다. 모델·effort는 subtask 성격에 맞게 provider 문서에서 고른다.

**claude는 여기서 미리 스폰하지 않는다.** `worker-start --agent`가 터미널 생성과 task 배정을 한
호출로 처리하므로(§0 참고 — approval/sandbox는 계정 프리셋이 맡는다), verbatim 템플릿은 `task_id`를
이미 아는 §5의 wave 루프에 있다. **codex·agy는 여기서 미리 띄운다** — codex는 `--agent codex`의
injection이 TUI 준비 전에 일어나 유실되므로(§0), agy는 `--agent agy` 자체가 없으므로:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# codex
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "codex '--dangerously-bypass-approvals-and-sandbox'" --json
orca terminal wait --terminal <impl-handle> --for tui-idle --timeout-ms 60000 --json
# tui-idle만으로는 부족하다(§0) — dispatch-verify.md "Pre-dispatch — freshly launched REPL은
# boot-quiesce 확인 후에만 inject (issue #84)"의 cursor-diff quiesce 확인을 여기서 실행하고, 통과할
# 때까지(스폰 timeout 예산 내) §5의 worker-start --terminal을 보류한다.

# agy — 프롬프트는 파일에 먼저 쓰고 command substitution으로 전달한다(인라인 '<...>' quoting은
# 괄호·따옴표·개행이 있는 프롬프트에서 라이브 셸 파싱 에러를 낸다 — orca-workflows/spawn-failures.md)
prompt_file="$(mktemp "${TMPDIR:-/tmp}/agy-prompt-XXXXXX.txt")"
cat > "$prompt_file" <<'PROMPT_EOF'
<subtask 지침>
PROMPT_EOF
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "agy -p \"\$(cat '$prompt_file')\" --model <model> --print-timeout 15m --dangerously-skip-permissions" --json
orca terminal wait --terminal <impl-handle> --for tui-idle --timeout-ms 60000 --json   # agy는 --for exit --timeout-ms 960000
```

`terminal wait`가 timeout이거나 생성 직후 `terminal read`에 셸 에러(예: `zsh: parse error`)가 보이면
스폰 실패다 — 처음부터 재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`에서 known
signature부터 확인한다. codex는 이 실패 판정과 별개로, boot-quiesce가 스폰 timeout 예산 안에 끝나지
않으면 자체적으로 재시도하지 않고 그 사실을 로그에 남긴 뒤 §5 dispatch를 보류·보고한다.

(구현자는 빌드·테스트 실행이 필요해 Bash 전체 허용 — worktree 격리가 전제. 권한 stall 발견 시 조합을 조정하고 이 스킬에 반영.)

## 4. Subtask 게이트 — 기계적인 것만

subtask가 worker_done을 보내기 전에 스스로 실행: typecheck, unit test, formatter, linter, 무거운 환경 구성이 필요 없는 script test. **subtask 단위 agent 리뷰어는 없다.** 게이트를 통과하지 못하면 worker_done을 보내지 않고 스스로 고친다.

## 5. Wave 루프

**스폰 커맨드는 아래 템플릿을 verbatim 복사한다 — 손으로 재타이핑·재조립하지 않는다.** placeholder
(`<model>`/`<effort>`/`<n>`/`<task_id>`) 치환 외의 어떤 변형도 금지: 재조립 과정에서 플래그가
누락·변형된 실측 사례가 spawn-failures.md에 known signature로 등록돼 있다(issue #40 — `--permission-mode
acceptEdits`로 틀어진 채 `--effort` 누락).

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
sidecar="$HOME/.local/state/orca-workflows/logs/run-<project-slug>-<issue 번호>-orca-task-runner.txt"
[ -s "$sidecar" ] || { echo "orca-task-runner §0 Run 생성이 실행되지 않음 — 사이드카 없음: $sidecar" >&2; exit 1; }
RUN_ID="$(cat "$sidecar")"   # §0에서 남긴 사이드카
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration task-list --ready --brief --json
spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # §2에서 남긴 사이드카
spec_text="$(cat "$spec_sidecar")"   # 지금 재구성하지 않는다 — §2에서 남긴 원문 그대로
# claude
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration worker-start --task <task_id> --worktree current --agent claude --model <model> --effort <effort> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
# codex — §3에서 이미 만든 터미널에 배정(§0: --agent codex는 TUI 준비 전에 injection해 유실된다, 라이브
# 확인). --worktree 생략 — <impl_handle>이 이미 그 worktree에 고정된 터미널이므로 --worktree active는
# 불필요하고, 지정하면 selector_not_found로 실패한다(라이브 확인). §3의 boot-quiesce 확인을 통과한
# 뒤에만 이 호출을 낸다.
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration worker-start --task <task_id> --terminal <impl_handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
# agy — §3에서 이미 만든 터미널에 배정(agy만 --agent가 없어 pre-create가 여전히 필요, §0). --worktree
# 생략 — <impl_handle>이 이미 그 worktree에 고정된 터미널이므로 --worktree active는 불필요하고, 지정하면
# selector_not_found로 실패한다(라이브 확인).
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration worker-start --task <task_id> --terminal <impl_handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json
# 위 세 갈래 중 이 subtask의 provider에 맞는 하나만 — wave 크기만큼 병렬로, 크기 규칙은 §3.
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58 — worker-start에도
# 동일하게 필요: stage:"input_accepted"는 제출은커녕 **도달**도 보장하지 않는다, 실측 — worker-show가
# stage:"input_accepted"를 반환한 동일 dispatch에서 codex composer가 40초+ 빈 placeholder로 남아있는
# 걸 직접 확인, issue #84/#150). codex는 §3의 boot-quiesce로 사전에 이 레이스를 막으므로, 그 확인을
# 통과한 뒤의 실패는 별도 재시도 없이 self-recovery.md의 `dead` 판정(worker-abandon → worker-start
# --retry-of)에 맡긴다.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, repo=<대상 repo — spec으로 받은 값>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 아래 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 삭제 시점·이유는 §5 마지막 블록.
```

**Wave telemetry(시작)** — 상한 재검토용 데이터를 쌓는다. 이 wave의 모든 subtask에 대해 위 스폰 호출을
전부 낸 직후 1회(claude/codex는 스폰과 dispatch가 한 호출이므로, agy까지 포함해 이 wave가 실제로
"뜬" 시점은 여기다 — §3에서 미리 뜨는 건 agy뿐):

```bash
# wave_start 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로 waves-<오늘 UTC 날짜>.jsonl에 기록.
# event="wave_start", issue=<issue-num>, repo=<대상 repo — spec으로 받은 값>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
# nproc=$(sysctl -n hw.ncpu 2>/dev/null || nproc), ts_epoch=$(date -u +%s)
```

`nproc`(가용 코어 수)을 같이 남기는 이유: wave_size와 소요시간만으로는 CPU 경합 여부를 판단할 수 없다 — 같은 wave_size라도 머신 코어 수·provider 구성(위 `assign` 로그의 `wave_index`와 join)에 따라 경합 여부가 달라지기 때문이다.

- **완료 대기와 self-recovery**: `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery 루프를 그대로 따른다 — 이 wave의 각 subtask `task_id`를 pending set에 넣고, `check --wait`(+`--ack`)로 기다리다 타임아웃되면 그 파일의 alive/stuck_draft/dead 분기(`worker-abandon`→`worker-start --retry-of`)로 복구한다. `dead` 판정 후 재시도할 때는 위 스폰 템플릿(해당 provider 갈래) 그대로 다시 띄운다(모델·effort는 같은 subtask이므로 재-resolve 없이 그대로 재사용).
- decision_gate(워커 ask) → 판단 가능하면 `reply`, 불가하면 `orca-workflow-task`에 에스컬레이션.
- **`orca_call_with_retry` exhausted로 인한 worker_done 유실**(위 self-recovery와는 다른 시나리오 — Orca 오케스트레이션 API 자체에 닿을 수 없는 경우, issue #41/#42): 커밋/산출물/worktree 루트의 `.orca-orphaned-result-<task_id>.json`(⑦의 exhausted 폴백 산출물) 확인 + `task-update --status completed` 수동 복구, 기록. orphan 파일은 복구 반영 후 삭제한다.
- **완료 확인된 subtask 터미널은 즉시 정리한다** — wave 전체를 기다리지 않고, 그 subtask의 `worker_done` 수신(taskId+dispatchId 일치) 또는 위 유실 복구가 끝나는 즉시:

  ```bash
  read_json="$(orca terminal read --terminal <impl_handle> --json)"
  # recv 이벤트 — logging.md §2 "첫 read" 레시피대로 $read_json에서 tail/nextCursor를 뽑아
  # term-<impl_handle>.jsonl에 append(이 터미널은 §5에서 sent만 기록했고 이후 한 번도 read하지
  # 않았으므로, 이 read가 곧 유일한 recv).
  # claude (worker-start --agent로 스폰 -- ownershipState: "owned"):
  orca orchestration worker-release --dispatch <dispatch_id> --json
  # codex/agy (worker-start --terminal로 스폰 -- ownershipState: "external", worker-release는 no-op이라
  # 쓰지 않는다 — 둘 다 라이브로 확인, 2026-08-11):
  orca terminal close --terminal <impl_handle> --tab --json
  rm -f "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # 사이드카 회수는 여기서
  # 한다 — §5 dispatch 블록에서 즉시 지우면, 같은 task_id를 재스폰하는 스폰 실패 재시도나
  # worker_done 유실 수동 복구가 두 번째로 이 블록을 태울 때 spec_text를 못 읽어 sent.content가
  # 빈 문자열이 된다. 터미널이 실제로 닫히는 시점까지 사이드카를 살려 두면 재시도도 원문을 그대로
  # 기록할 수 있다.
  ```

  claude는 `worker-release`가 archive를 먼저 보존한 뒤 정확히 이 dispatch가 소유한 에이전트 터미널만
  닫는다(post-completion cleanup, cancel 아님) — `release_pending`/`release_unknown`이 오면 `terminal
  close`로 대체하지 않고 응답이 지시하는 복구 동작을 그대로 따른다. codex·agy는 `--tab` close를 반드시
  붙인다 — 실측 결과 `--tab` close는 기저 프로세스를 실제로 종료시키고 메모리를 회수하지만
  (`diagnostics memory`에서 세션이 사라짐), `--tab` 없는 close는 pane만 닫고 프로세스가 남을 수 있다.
  정리 전에 `term-<impl_handle>.jsonl`에 마지막 `recv`를 남기는 이유는 클로즈/릴리스 후 스크롤백이
  사라져서, §6 task-레벨 게이트가 나중에 실패했을 때 "이 subtask가 뭘 했는지" 재확인할 방법이
  없어지기 때문이다(단 claude는 `worker-release`의 archive 덕분에 이후에도 `worker-read`로 다시 읽을
  수 있다 — codex·agy는 `--tab` close로 프로세스 자체가 종료되므로 이 archive 경로가 없고, recv 로그가
  유일한 사후 기록이다). worker_done/유실 복구
  둘 다 확인 전에는(단순히 활동이 멈췄다는 이유만으로는) 정리하지 않는다 — 아직 파일 쓰기·커밋이
  끝나지 않은 프로세스를 죽일 위험이 있다. 이 정리는 매 wave 새 터미널을 스폰하는 구조라 재사용
  대상이 없다는 전제 위에서만 안전하다 — 이 스킬 밖(범용 `orchestration`, `orca-workflow-task` 자체
  relay 터미널)에는 적용하지 않는다.

**Wave telemetry(종료)** — 이 wave의 모든 subtask가 완료(worker_done 또는 수동 복구)된 직후 1회, 위 `wave_start`와 같은 `issue`+`wave_index`로 join되도록:

```bash
start_epoch="$(find ~/.local/state/orca-workflows/logs -name 'waves-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null | jq -r --arg issue "<issue-num>" --argjson wi <n> \
  'select(.event == "wave_start" and .issue == $issue and .wave_index == $wi) | .ts_epoch' \
  | tail -1)"
if [ -n "$start_epoch" ]; then
  elapsed_ms=$(( ("$(date -u +%s)" - start_epoch) * 1000 ))
else
  elapsed_ms=null   # 매칭되는 wave_start가 없음 — §0 orphan 확인을 건너뛴 경우거나 데이터 유실
fi
# wave_end 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로 waves-<오늘 UTC 날짜>.jsonl에 기록.
# event="wave_end", issue=<issue-num>, repo=<대상 repo — spec으로 받은 값>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
# retry_count=<이 wave에서 발생한 스폰 실패·timeout 재시도 총 횟수, 알 수 없으면 null>,
# elapsed_ms=$elapsed_ms, outcome="completed"
```

(§0에서 orphan wave를 복구하는 경우는 `outcome`을 `"crash_recovered"`로, `retry_count`를 모르면 `null`로 채운다 — 그 외 필드는 동일 포맷.)

`retry_count`가 이 wave에서 2 이상이면 스폰 실패·timeout이 우연이 아니라 이 wave 크기에서 반복된다는 뜻이다 — 다음 wave부터 크기를 3 이하로 되돌리고(§3) 사용자에게 보고한다. `elapsed_ms`는 완주한 wave에서도 wave 크기가 커질수록 벽시계 시간이 비선형으로 늘어나는지 보는 용도다. "응답이 느려 보인다" 같은 주관적 판단이 아니라 이 숫자들로 판정한다.

## 6. Task 레벨 게이트

subtask 전부가 끝나 합쳐진 task 전체 diff 기준으로, 딱 한 번 재검증한다. subtask 게이트(§4)는 같은 wave 안에서 병렬 실행되는 형제 subtask의 커밋을 놓칠 수 있어(race) — 어떤 subtask가 자기 게이트를 실행하는 시점에 같은 wave의 형제가 아직 커밋 전일 수 있다 — 그 어떤 subtask의 통과도 "task 전체가 합쳐진 뒤"를 보장하지 않는다. 이 게이트가 그 구멍을 메운다.

- typecheck / unit test / formatter / linter를 task 전체 diff 기준으로 재실행.
- e2e·pgTAP 실행(결정론적, 모델 개입 없음). **시도 회차별로 로그 파일명을 분리한다** — 고정 파일명에
  `>`로 쓰면 재시도가 직전 실패 로그를 덮어써, 재시도 후 green을 얻었을 때 그 실패가 "이 diff와
  무관한 flake"였다는 판정을 뒷받침할 증거가 물리적으로 사라진다(실측: issue #57):

```bash
bash -lc '<repo의 e2e 커맨드> > <worktree 루트>/.gate-e2e.attempt<N>.log 2>&1; \
  echo EXIT:$? > <worktree 루트>/.gate-e2e.attempt<N>-summary.txt'
bash -lc '<repo의 pgTAP 커맨드, 예: pg_prove> > <worktree 루트>/.gate-pgtap.attempt<N>.log 2>&1; \
  echo EXIT:$? > <worktree 루트>/.gate-pgtap.attempt<N>-summary.txt; \
  grep -c "not ok" <worktree 루트>/.gate-pgtap.attempt<N>.log >> <worktree 루트>/.gate-pgtap.attempt<N>-summary.txt'
```

`<N>`은 1부터 시작(첫 실행도 포함 — "재시도 로그만" 분리하면 1회차 실패가 여전히 재시도로 덮인다).
어떤 시도든 통과하면 이후 시도는 생략하되, 지금까지의 attempt 로그는 지우지 않는다 — §7 반환값이
필요로 한다.

실패 시 subtask 게이트(§4)와 같은 방식으로 스스로 고치고 재시도한다. 단 subtask 게이트와 달리 **재시도 한도 2회**(무한 자가치유가 아니다 — `orca-workflow-task` §4의 evaluate-FAIL 재시도 한도와 같은 숫자로 맞췄다). 2회 시도 후에도 통과 못하면 `orca-evaluate`를 호출하지 않고 `orca-workflow-task`에 **`GATE_FAIL`**을 직접 반환한다 — 기계적으로도 안 돌아가는 코드를 agent e2e·code review 같은 비싼 단계에 태울 이유가 없다.

**재시도 후 통과("flake"로 재분류)를 기록 없이 조용히 넘기지 않는다.** 1회차가 실패하고 이후
시도가 통과해 게이트를 넘겼다면, `CONTRACT_DIR/gate-flake-a<attempt>.json`을 쓴다(스키마·필드 의미는
`~/.agents/orca-workflows/contract-schema.md`의 해당 절 — 실패 attempt의 spec 파일명·에러 첫 줄을 위
attempt 로그에서 추출하고, 레포에 알려진 flake 목록(예: `.claude/memory/project_known_flaky_e2e.md`,
존재하는 repo에 한함)이 있으면 그 대조 결과 포함). **산문 반환값이 아니라 파일인 이유**: 이 증거의
소비자는 `orca-evaluate` §3의 code-reviewer인데, 반환값은 "본문을 읽지 않는" `orca-workflow-task`를
거치므로 산문에 실으면 소비자에게 도달할 경로가 없다 — evaluator가 결정론적 경로로 직접 읽는다.
이 기록이 없으면 "이 diff와 무관한 flake였다"는 재실행측 판단을 사후에 검증할 방법이 없다 —
재실행-green과 "게이트 통과"를 구분하지 못하게 된다. 첫 시도에 전부 통과했으면 파일을 만들지
않는다(부재 자체가 신호다).

## 7. 완료

Task 레벨 게이트(§6)를 통과하면 → task 전체 diff를 정리해 `orca-workflow-task`에 반환한다(diff 경로 + resolved providers/models + wave 구성 기록). flake 증거는 반환값에 싣지 않는다 — §6이 이미 `CONTRACT_DIR/gate-flake-a<attempt>.json`으로 남겼고, `orca-evaluate`가 그 경로를 직접 읽는다. **`orca-evaluate`는 이 스킬이 직접 호출하지 않는다** — `orca-workflow-task`가 호출한다. (§6에서 `GATE_FAIL`을 반환한 경우엔 diff를 넘기지 않는다 — 그 자체가 반환값이다.)

**Evaluate-FAIL 재시도로 재호출된 경우**(spec에 attempt 번호가 있음): contract 협상(§1)을 다시 하지 않는다 — 확정 AC는 그대로다. `CONTRACT_DIR`의 `eval-report-a<attempt>.json`과 **최종 라운드 proposal**(가장 큰 `proposal-r<n>.json` — 네가 직접 확인)을 이 순서로 직접 읽고(`orca-workflow-task`는 findings 본문도 확정 AC 본문도 중계하지 않는다 — `~/.agents/orca-workflows/contract-schema.md`의 "확정 AC의 정본"), 그 수정에 필요한 만큼만 §2~§5를 다시 태운 뒤 §6 task-레벨 게이트를 전체 재통과시키고 위 §7 반환을 반복한다. findings가 코드가 아니라 **계약 파일 자체의 결함**을 지적하면(override 이후에만 가능 — approved 계약이면 ESCALATE 사안), 동결 파일을 제자리 수정하지 말고 `proposal-r<n+1>.json`을 새로 쓴다(스키마 문서의 "override 후속 라운드" 절, issue #130). 수정 결과에 대한 서술형 해명을 evaluator에게 보내지 않는다 — 재평가의 입력은 diff의 사실 변화뿐이다(같은 문서의 "재시도 입력 격리").

## 폴백

- orca 런타임 불가: `superpowers:subagent-driven-development`로 폴백 — 모델은 provider 문서의 같은 subtask 유형 등급을 Agent tool `model` 인자로. 폴백 발동은 사용자에게 보고.
- 폴백에서도 §5의 할당 로그는 동일하게 남긴다 — `terminal` 필드만 subagent 식별자로 대체.
