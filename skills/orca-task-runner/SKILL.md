---
name: orca-task-runner
description: Use when generating the implementation for one task (issue) — proposes an implementation-and-verification contract to orca-evaluate, then fans out subtasks across Claude Code/Codex/agy terminals in dependency-ordered waves. Subtask gates are mechanical only (typecheck/unit test/lint/format) — never an agent reviewer; task-level review belongs to orca-evaluate. Self-relative — works identically whichever provider runs this session.
---

# Orca Task Runner

하나의 task(issue)를 구현한다. **생성만** 한다 — 평가는 이 스킬의 책임이 아니다(`orca-evaluate`가 담당). subtask 단위 리뷰어 역할은 두지 않는다.

## 0. 전제

- `orca status --json` ready. 실패 시 아래 "폴백".
- feature worktree에서 실행 중이어야 한다(main 체크아웃에서 금지). 워커는 전부 `--worktree active`에 생성.
- CLI 기반 세션(Codex/agy — 이 세션이든 §4가 스폰하는 워커든)은 launch 시 approval·sandbox를 명시한다. codex posture는 `--dangerously-bypass-approvals-and-sandbox` — 근거·예외(headless read-only 등)는 `~/.agents/orca-workflows/models/codex.md`가 정본이다. 안전 전제는 워크트리 격리이므로(§0 첫 불릿의 main 체크아웃 금지와 같은 전제), 격리 밖에서 이 posture로 launch하지 않는다.
- 모델·effort는 매 launch 전 아래 문서에서 subtask 유형(전사·기계적 / 통합·판단 / 아키텍처)에 맞게 고른다. 값을 이 스킬에 복제하지 않는다.
  - `~/.agents/orca-workflows/model-selection.md`
  - `~/.agents/orca-workflows/models/claude-code.md`
  - `~/.agents/orca-workflows/models/codex.md`
  - `~/.agents/orca-workflows/models/agy.md`
- 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 —
  `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. §3(launch)과 §5(대기)에서
  이 확인이 걸리는 지점을 표시한다.
- **MCP 서버 인증 전제**(세션 시작 시 1회 확인) — §3에서 스폰하는 워커 터미널이 쓰는 MCP 서버
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
  별도 fenced block이라 셸 변수가 그대로 넘어가지 않는다 — 아래 `spec_sidecar`와 같은 이유):

  ```bash
  install -d -m 700 ~/.local/state/orca-workflows/logs
  run_json="$(orca orchestration run-create --objective "<issue 번호> task implementation" --from <자기 handle> --json)"
  printf '%s' "$(printf '%s' "$run_json" | jq -r '.result.run.id')" > "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>-orca-task-runner.txt"
  chmod 600 "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>-orca-task-runner.txt"
  ```

  이후 §5의 모든 `worker-start`/`check --wait`/`--ack` 호출 앞에서
  `RUN_ID="$(cat "$HOME/.local/state/orca-workflows/logs/run-<issue 번호>-orca-task-runner.txt")"`로 다시 읽는다.
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
  충분한가"류 정당화는 어떤 필드에도 넣지 않는다(스키마 문서의 "라운드 2 입력 격리" 참고).
- 검증 방법(`verification_plan`) — 구체적인 파일/함수/테스트로, 항목마다 커버하는 ac id를
  `covers`로 참조하고 이 항목이 fix 이전에 어떻게 실패하는지(또는 왜 실패할 수 없는지)를 `fails_before_fix`에 적는다. 어떤 항목도 커버하지 않는 ac id가 남거나 `fails_before_fix`가 비어 있거나 없으면 반려 대상이다.
- 의도된 destructive 오퍼레이션(`destructive_operations`) — 빈 배열이 "명시적 없음"이다. 이 선언은
  나중에 `orca-evaluate` §3가 diff에서 실제로 flag된 destructive-op와 대조하는 근거가 된다.
- 이 변경으로 red가 되거나 갱신이 필요한 기존 테스트·단언(`existing_tests_affected`, file:line) —
  빈 배열이 "명시적 없음"이다. `verification_plan`은 새로 추가할 검증만 담는다 — 기존에 green이던
  단언 중 이 변경으로 red가 될 것은 여기 별도로 열거한다(정확 일치 단언, 게이트 자체를 막는 회귀를
  특히 놓치기 쉽다).

`orca-evaluate`가 이 제안(AC 초안 포함)을 **원본 issue 전문**에 대조해 검토하고 `verdict-r<라운드>.json`으로 판정을 남긴다. 반려되면 그 `reasons`를 읽고 **수정된 사실로** 다시 제안한다(`proposal-r2.json` — 서술형 반박이 아니라 필드 수준의 변경으로 응답한다). 각 라운드는 별도 dispatch로 도착한다: 제안서를 쓰고 나면 이번 턴을 끝낸다(주입된 preamble의 worker_done 지시대로), 같은 턴 안에서 반려 여부를 기다리거나 폴링하지 않는다. **최대 2 라운드.** 2라운드 안에 합의가 안 되면 이 스킬(generator)이 결정권을 가지고 그 제안대로 진행한다 — evaluator의 verdict 파일은 수정하지 않고, `override.json`(스키마 문서 참고)에 미해소 `reasons`를 복사해 남긴 뒤 진행한다. 이후 모든 단계(§2 subtask 분해 포함)가 참조하는 확정 AC는 최종 라운드 proposal의 `draft_acceptance_criteria`다.

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

subtask spec 필수 항목: ①구체적 작업 내용(코드 블록 포함 그대로) ②커밋 대상 브랜치·worktree 명시 ③resolved provider/model/effort 기록 ④"막히면 ask로 blocking 질문" ⑤"완료 시 preamble 지시대로 worker_done(payload에 filesModified)" ⑥**병렬 커밋 안전 규칙**(같은 worktree를 공유하는 병렬 워커가 서로의 미완성 변경을 덮어쓰지 않도록): `git add` 명시 경로만·`git commit -m "<msg>" -- <files>` pathspec 필수·index.lock 재시도. Orca의 attribution-trailer 자동 삽입 wrapper는 `git commit -m "<msg>" -- <files>` 실행 시 `-- <pathspec>` 뒤에 `-m`을 추가로 삽입해 pathspec 파싱을 깨뜨리므로, 커밋 메시지에 원하는 trailer를 미리 포함시켜 wrapper의 추가 삽입을 무해화한다. ⑦**연결 실패 자동 재시도 + orphan 폴백**: worker_done을 포함해 네가 보내는 `orca orchestration`/`orca terminal` 호출은 항상 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` 후 `orca_call_with_retry`로 감싸고(issue #42) — 호출 형태는 `orca_call_with_retry "<skill>" "<role>" -- <command...>` (예: `orca_call_with_retry "orca-task-runner" "subtask-impl" -- orca orchestration send ...`), skill/role 인자를 생략하면 `"orca"`/`"orchestration"`이 라벨 인자로, `"send"`가 명령어로 잘못 소비된다 — wrapper가 exhausted를 반환하면 ask를 포함한 추가 orchestration 호출을 시도하지 않는다 — 같은 죽은 transport를 타므로 똑같이 실패한다(issue #41). 대신 보내려던 결과 전문(worker_done payload, 없으면 현재 상태 요약)을 worktree 루트에 `.orca-orphaned-result-<task_id>.json`으로 저장하고(커밋 금지 — ⑥의 명시 경로 규칙이 이미 이를 배제한다), 터미널에 `ORPHANED_RESULT <task_id> <파일 절대경로>` 한 줄을 출력한 뒤 명확히 멈춘다(이후 도착하는 무관한 프롬프트를 집어삼키지 말 것).

## 3. Wave 준비

wave 크기는 고정 상한 없이 머신 리소스 상황을 보며 판단한다(§5 wave telemetry가 적정치 계측의 근거 데이터다) — 단 무제한이 아니다: 한 wave에서 스폰 실패·timeout 재시도가 2회 이상 발생하면 그 즉시 wave 크기를 3 이하로 제한하고 사용자에게 보고한다. provider는 자유 선택(claude-code/codex/agy 아무거나, 토큰 효율을 위해 섞어도 됨) — 단 `model-selection.md`의 "Quota check before pinning"에서 제외된 provider는 후보에서 뺀다. 모델·effort는 subtask 성격에 맞게 provider 문서에서 고른다.

**스폰 커맨드는 아래 템플릿을 verbatim 복사한다 — 손으로 재타이핑·재조립하지 않는다.** placeholder(`<model>`/`<effort>`/`<n>`) 치환 외의 어떤 변형도 금지: 재조립 과정에서 플래그가 누락·변형된 실측 사례가 spawn-failures.md에 known signature로 등록돼 있다(issue #40 — `--permission-mode acceptEdits`로 틀어진 채 `--effort` 누락). 같은 이유로 빈 fallback shell을 만들어 거기에 커맨드를 쳐 넣는 경로를 쓰지 않는다 — 터미널은 항상 아래처럼 `terminal create --command`로 launch 문법을 함께 넘겨 생성한다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# claude
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "claude --model <model> --effort <effort> --dangerously-skip-permissions" --json
# codex
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca terminal create --worktree active --title task-impl-<n> \
  --command "codex --model <model> -c model_reasoning_effort=<effort> --dangerously-bypass-approvals-and-sandbox" --json
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

**Wave telemetry(시작)** — 상한 재검토용 데이터를 쌓는다. 이 wave의 모든 터미널이 뜬 직후 1회:

```bash
# wave_start 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로 waves-<오늘 UTC 날짜>.jsonl에 기록.
# event="wave_start", issue=<issue-num>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
# nproc=$(sysctl -n hw.ncpu 2>/dev/null || nproc), ts_epoch=$(date -u +%s)
```

`nproc`(가용 코어 수)을 같이 남기는 이유: wave_size와 소요시간만으로는 CPU 경합 여부를 판단할 수 없다 — 같은 wave_size라도 머신 코어 수·provider 구성(§5 `assign` 로그의 `wave_index`와 join)에 따라 경합 여부가 달라지기 때문이다.

`terminal wait`가 timeout이거나 생성 직후 `terminal read`에 셸 에러(예: `zsh: parse error`)가 보이면
스폰 실패다 — 처음부터 재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`에서 known
signature부터 확인한다.

(구현자는 빌드·테스트 실행이 필요해 Bash 전체 허용 — worktree 격리가 전제. 권한 stall 발견 시 조합을 조정하고 이 스킬에 반영.)

## 4. Subtask 게이트 — 기계적인 것만

subtask가 worker_done을 보내기 전에 스스로 실행: typecheck, unit test, formatter, linter, 무거운 환경 구성이 필요 없는 script test. **subtask 단위 agent 리뷰어는 없다.** 게이트를 통과하지 못하면 worker_done을 보내지 않고 스스로 고친다.

## 5. Wave 루프

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
sidecar="$HOME/.local/state/orca-workflows/logs/run-<issue 번호>-orca-task-runner.txt"
[ -s "$sidecar" ] || { echo "orca-task-runner §0 Run 생성이 실행되지 않음 — 사이드카 없음: $sidecar" >&2; exit 1; }
RUN_ID="$(cat "$sidecar")"   # §0에서 남긴 사이드카
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration task-list --ready --brief --json
spec_sidecar="$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # §2에서 남긴 사이드카
spec_text="$(cat "$spec_sidecar")"   # 지금 재구성하지 않는다 — §2에서 남긴 원문 그대로
orca_call_with_retry "orca-task-runner" "subtask-impl" -- \
  orca orchestration worker-start --task <task_id> --worktree active --terminal <impl_handle> --run "$RUN_ID" --from <자기 handle> --retry-request "$(uuidgen)" --json   # wave 크기만큼 병렬 — 크기 규칙은 §3
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58 — worker-start에도
# 동일하게 필요: stage:"input_accepted"는 실제 제출을 보장하지 않는다, 실측).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  logging.md §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  logging.md §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text(위 사이드카에서 로드한 값). recv는 아래 close 직전에
#    기록한다(§5 마지막 블록). 사이드카는 여기서 지우지 않는다 — 삭제 시점·이유는 §5 마지막 블록.
```

- **완료 대기와 self-recovery**: `~/.agents/orca-workflows/self-recovery.md`의 wait/recovery 루프를 그대로 따른다 — 이 wave의 각 subtask `task_id`를 pending set에 넣고, `check --wait`(+`--ack`)로 기다리다 타임아웃되면 그 파일의 alive/stuck_draft/dead 분기(`worker-abandon`→`worker-start --retry-of`)로 복구한다. `dead` 판정 후 재시도할 때는 새 worker 터미널을 §3의 launch 템플릿으로 다시 띄운다(모델·effort는 같은 subtask이므로 재-resolve 없이 그대로 재사용).
- decision_gate(워커 ask) → 판단 가능하면 `reply`, 불가하면 `orca-workflow-task`에 에스컬레이션.
- **`orca_call_with_retry` exhausted로 인한 worker_done 유실**(위 self-recovery와는 다른 시나리오 — Orca 오케스트레이션 API 자체에 닿을 수 없는 경우, issue #41/#42): 커밋/산출물/worktree 루트의 `.orca-orphaned-result-<task_id>.json`(⑦의 exhausted 폴백 산출물) 확인 + `task-update --status completed` 수동 복구, 기록. orphan 파일은 복구 반영 후 삭제한다.
- **완료 확인된 subtask 터미널은 즉시 닫는다** — wave 전체를 기다리지 않고, 그 subtask의 `worker_done` 수신(taskId+dispatchId 일치) 또는 위 유실 복구가 끝나는 즉시:

  ```bash
  read_json="$(orca terminal read --terminal <impl_handle> --json)"
  # recv 이벤트 — logging.md §2 "첫 read" 레시피대로 $read_json에서 tail/nextCursor를 뽑아
  # term-<impl_handle>.jsonl에 append(이 터미널은 §5에서 sent만 기록했고 이후 한 번도 read하지
  # 않았으므로, 이 read가 곧 유일한 recv).
  orca terminal close --terminal <impl_handle> --tab --json
  rm -f "$HOME/.local/state/orca-workflows/logs/spec-<task_id>.txt"   # 사이드카 회수는 여기서
  # 한다 — §5 dispatch 블록에서 즉시 지우면, 같은 task_id를 재스폰하는 스폰 실패 재시도나
  # worker_done 유실 수동 복구가 두 번째로 이 블록을 태울 때 spec_text를 못 읽어 sent.content가
  # 빈 문자열이 된다. 터미널이 실제로 닫히는 시점까지 사이드카를 살려 두면 재시도도 원문을 그대로
  # 기록할 수 있다.
  ```

  `--tab`을 반드시 붙인다 — 실측 결과 `--tab` close는 기저 프로세스를 실제로 종료시키고 메모리를 회수하지만(`diagnostics memory`에서 세션이 사라짐), `--tab` 없는 close는 pane만 닫고 프로세스가 남을 수 있다. close 전에 `term-<impl_handle>.jsonl`에 마지막 `recv`를 남기는 이유는 close하면 스크롤백이 사라져서, §6 task-레벨 게이트가 나중에 실패했을 때 "이 subtask가 뭘 했는지" 재확인할 방법이 없어지기 때문이다. worker_done/유실 복구 둘 다 확인 전에는(단순히 활동이 멈췄다는 이유만으로는) 닫지 않는다 — 아직 파일 쓰기·커밋이 끝나지 않은 프로세스를 죽일 위험이 있다. 이 close는 §3에서 매 wave 새 터미널을 스폰하는 구조라 재사용 대상이 없다는 전제 위에서만 안전하다 — 이 스킬 밖(범용 `orchestration`, `orca-workflow-task` 자체 relay 터미널)에는 적용하지 않는다.

**Wave telemetry(종료)** — 이 wave의 모든 subtask가 완료(worker_done 또는 수동 복구)된 직후 1회, §3 `wave_start`와 같은 `issue`+`wave_index`로 join되도록:

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
# event="wave_end", issue=<issue-num>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
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

**재시도 후 통과("flake"로 재분류)를 §7 반환값 없이 조용히 넘기지 않는다.** 1회차가 실패하고 이후
시도가 통과해 게이트를 넘겼다면, §7 반환값에 다음을 반드시 포함한다: 실패했던 attempt의 spec
파일명·에러 첫 줄(위 attempt 로그에서 추출), 그리고 레포에 알려진 flake 목록(예:
`.claude/memory/project_known_flaky_e2e.md`, 존재하는 repo에 한함)이 있으면 그 목록과 대조한 결과.
이 기록이 없으면 `orca-evaluate`·`orca-workflow-task`가 "이 diff와 무관한 flake였다"는 재실행측 판단을 사후에
검증할 방법이 없다 — 재실행-green과 "게이트 통과"를 구분하지 못하게 된다.

## 7. 완료

Task 레벨 게이트(§6)를 통과하면 → task 전체 diff를 정리해 `orca-workflow-task`에 반환한다(diff 경로 + resolved providers/models + wave 구성 기록 + (§6에서 재시도 후 통과한 경우) flake 증거: 실패 attempt의 spec 파일명·에러 첫 줄 + 알려진 flake 목록 대조 결과). **`orca-evaluate`는 이 스킬이 직접 호출하지 않는다** — `orca-workflow-task`가 호출한다. (§6에서 `GATE_FAIL`을 반환한 경우엔 diff를 넘기지 않는다 — 그 자체가 반환값이다.)

**Evaluate-FAIL 재시도로 재호출된 경우**(spec에 attempt 번호가 있음): contract 협상(§1)을 다시 하지 않는다 — 확정 AC는 그대로다. `CONTRACT_DIR`의 `eval-report-a<attempt>.json`에서 `findings`를 직접 읽고(`orca-workflow-task`는 본문을 중계하지 않는다 — `~/.agents/orca-workflows/contract-schema.md`), 그 수정에 필요한 만큼만 §2~§5를 다시 태운 뒤 §6 task-레벨 게이트를 전체 재통과시키고 위 §7 반환을 반복한다. 수정 결과에 대한 서술형 해명을 evaluator에게 보내지 않는다 — 재평가의 입력은 diff의 사실 변화뿐이다(같은 문서의 "재시도 입력 격리").

## 폴백

- orca 런타임 불가: `superpowers:subagent-driven-development`로 폴백 — 모델은 provider 문서의 같은 subtask 유형 등급을 Agent tool `model` 인자로. 폴백 발동은 사용자에게 보고.
- 폴백에서도 §5의 할당 로그는 동일하게 남긴다 — `terminal` 필드만 subagent 식별자로 대체.
