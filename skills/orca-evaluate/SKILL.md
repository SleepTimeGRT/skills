---
name: orca-evaluate
description: Use when evaluating a completed task's diff before merge. This session runs on a REPL-capable provider other than agy (agy REPL is unsupported — see `~/.agents/orca-workflows/models/agy.md`); it spawns agy headless for the agent-e2e test gate (speed/cost/computer-use strength — e2e/pgTAP already passed in orca-task-runner, so this skill never re-touches them), spawns a separate strong-coding-agent terminal for the two judgment calls it can't make itself (contract approval — judging the generator's drafted acceptance criteria against the original issue — and diff code review informed by the agent-e2e result — skipped fail-fast when agent-e2e failure is confirmed), and synthesizes the results into one report against the negotiated Acceptance Criteria. Returns PASS, FAIL-with-feedback, or ESCALATE. Self-relative.
---

# Orca Evaluate

task(issue) 하나를 **1회** 평가한다(subtask마다 하지 않음). 코드를 쓰지 않는다 — `orca-task-runner`가 생성한 결과만 판단한다.

이 스킬이 하는 일은 세 가지다: **1) contract 협상, 2) test gate 실행(agent e2e), 3) code review.** 셋 다 별도 터미널로 스폰한다 — 이유는 §0.

## 0. 이 세션 자체의 launch — REPL 가능한 provider로, agy는 제외

`orca-workflow-task`가 이 스킬을 orchestration으로 띄운다 — 별도 터미널을 만들어 넘기는 것이지 자기 세션에서 도는 게 아니다. 스폰 실패 시(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않고 `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다 — 아래 §1·§2·§3의 `terminal create` 호출에도 동일하게 적용된다. 자동 업데이트로 Orca 앱이 세션 도중 재시작해 orchestration 호출이 일시적으로 끊기면(known signature: 같은 문서, issue #42), 아래 §0·§1·§2·§3의 `orca orchestration`/`orca terminal create` 호출은 전부 `source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh` 후 `orca_call_with_retry <skill> <role> -- <원명령>`으로 감싼다.

**MCP 서버 인증 전제**(세션 시작 시 1회 확인) — 아래 §0·§1·§2·§3에서 스폰하는 터미널이 쓰는 MCP 서버
(예: Context7)는 스폰 전에 이미 인증이 끝나 있거나, 그 프로필에서 비활성화돼 있어야 한다. 로그인
프롬프트가 스폰된 세션을 막으면 주입된 spec이 처리되지 않고 사람이 직접 ESC로 해제해야 한다 —
dispatch spec마다 그때그때 예방 문구를 덧붙이는 방식은 막지 못하는 것이 실측됐다(issue #60). 막히면
재진단 없이 `~/.agents/orca-workflows/spawn-failures.md`의 해당 row로.

**이 세션은 REPL로 띄우되, agy는 제외한다.** One-shot(`agy -p ... --print-timeout`)은 이후 `dispatch --inject`가 이미 종료된 프로세스의 셸에 떨어져 도달하지 못하므로(issue #37, `spawn-failures.md` 참고) REPL이 필요하다 — 하지만 agy로 그 REPL을 띄우면 안 된다: 포커스 없이 부팅이 멈추거나 동시 focus 경합 시 영구 데드락으로 이어질 수 있다(`~/.agents/orca-workflows/models/agy.md` — agy는 이 repo 전체에서 headless 전용). 그래서 `model-selection.md` 기준으로 REPL이 검증된, agy 아닌 provider로 resolve한다(구체 모델명은 여기 복제하지 않는다 — 아래 §1·§3의 sub-agent 스폰과 같은 원칙). launch-then-inject 시퀀스는 그 provider 자신의 launch 문서를 따른다:

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는 절차를 따른다
# (agy처럼 자동 확정 가능한 provider도 있고 아닐 수도 있다 — 여기서 agy 전용 시퀀스를 가정하지 않는다).
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration task-create --spec "<이 SKILL.md 지침 + CONTRACT_DIR·라운드 번호(계약 검토 모드) 또는 CONTRACT_DIR·diff 경로·attempt 번호(diff 평가 모드) + issue 원문 + PASS/FAIL/ESCALATE 요청>" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-workflow-task" "evaluator" -- \
  orca orchestration dispatch --task <task_id> --to <evaluate-handle> --retry-request "$(uuidgen)" --inject --json
```

**이 세션 자체는 agy가 아니다.** agy는 §2(agent e2e)에서만, headless sub-spawn으로만 쓴다 — Gemini의 속도·비용·컴퓨터 사용 강점이 거기 맞기 때문이다(`model-selection.md`의 Computer Use / Long-Context 축, `models/agy.md` 참고). e2e·pgTAP 자체는 새로 안 들어온다 — `orca-task-runner`의 task-레벨 게이트(`skills/orca-task-runner/SKILL.md` §6)를 이미 통과한 뒤에만 이 스킬이 호출되므로 전량 신뢰한다.

**§1(Contract 검토)·§3(Diff 리뷰)의 실제 판단도 이 세션의 몫이 아니다.** 둘 다 "코드/구현이 기술적으로 타당한가"를 보는 technical judgment이고, `model-selection.md`의 Computer Use/Long-Context 축 Exclusion 조항이 이 축의 세션에 technical judgment를 맡기지 말라고 명시한다 — Default Mapping도 Gemini를 Routine/High Risk 코드 판단에 배정하지 않는다. 그래서 두 판단 모두 fresh-context coding-agent 세션에 맡기고, 이 세션은 relay + 최종 리포트 합성만 한다(각 세션의 모델 선택 기준은 §1·§3에).

## 1. Contract 검토 (coding agent 스폰)

`orca-task-runner`가 구현 전 제안서(`proposal-r<n>.json` — AC 초안 + 범위 + 검증 방법, 스키마는 `~/.agents/orca-workflows/contract-schema.md`)를 보내오면, 이 세션(evaluator)이 직접 판단하지 않고 **coding agent 터미널을 스폰**해서 **원본 issue 전문**에 대조 검토를 맡긴다 — 판정은 두 축이다: ①AC 초안이 issue의 요구를 충실히 반영하는가(누락·과소·과대) ②`verification_plan`이 그 AC를 실제로 커버하는가. 제안된 파일 범위·검증 방법이 실제 코드베이스에서 기술적으로 타당한지 보는, 구현 착수 전의 1회성 판단이라 diff 규모 같은 위험도를 낮출 신호가 아직 존재하지 않는 시점이다. 그래서 여기는 고정된 강한 reasoning 모델(`model-selection.md` High Risk tier)을 쓴다 — §3처럼 사후에 diff 통계로 동적으로 낮추지 않는다.

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve하되, 인라인 permission-bypass 플래그 필수: claude → --dangerously-skip-permissions, codex → --dangerously-bypass-approvals-and-sandbox>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<proposal-r<n>.json 경로 + 원본 issue 전문 + contract-schema.md의 '적대적 판정 지침' 그대로 + verdict-r<n>.json을 스키마·불변식대로 CONTRACT_DIR에 쓰라는 지시(반려 시 reasons에 target·대상 ac_id 명시) + (라운드 2면) 같은 문서의 '라운드 2 입력 격리' 규칙 그대로 + 판정 결과를 보낼 orchestration 호출은 orca_call_with_retry로 감싸고 연결 실패를 즉시 사람에게 알리지 말라는 지시>"
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-evaluate" "contract-review" -- \
  orca orchestration dispatch --task <task_id> --to <contract-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58). §3 스폰도
# 동일하게 적용한다.
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §3 스폰도 동일한 형태(§2 agent-e2e는
# assign만 — term 로그 대상 아님).
#  logging.md §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-evaluate", role="contract-review", terminal=<contract-handle>,
#    meta 기록 후 sent.content=$spec_text. 이 터미널에 대한 유일한 read는 위 dispatch-verify.md의
#    liveness probe(불투명 payload-echo 확인 — issue #58)뿐이며, 이는 의도적으로 recv로 기록하지 않는다(판정 결과는
#    relay로 받는다 — 위 §1 본문 참고).
```

이 evaluator 세션은 그 판정 결과(승인/반려+사유)를 받아 `orca-task-runner`로 relay한다(파일 내용을 새로 읽거나 재해석하지 않고 판정 결과만 전달) — 각 라운드는 별도 dispatch로 도착한다: 판정 결과를 relay하고 나면 이번 턴을 끝낸다(주입된 preamble의 worker_done 지시대로), 같은 턴 안에서 다음 제안을 기다리거나 폴링하지 않는다. 최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.

두 번의 coding agent 스폰(여기 §1과 아래 §3)은 시간상 멀리 떨어져 있다(§1은 구현 시작 전, §3은 전체 subtask wave가 끝난 뒤) — 하나의 터미널을 그 사이 계속 띄워두지 않고, 그때그때 fresh-context로 새로 스폰한다.

## 2. Test Gate: Agent e2e (evaluator가 headless agy로 스폰)

앱을 직접 조작하는 e2e. Playwright MCP(accessibility-tree 기반 — 스크린샷·좌표 클릭보다 UI 변경에 덜 깨진다)를 붙인 agy(Gemini) 세션을 **headless(`-p`, one-shot)로** 스폰한다, REPL 아님(agy는 이 스킬 전체에서 REPL 금지 — 이유는 §0). 시나리오·경로·요청 형식을 launch 시점의 `-p` 인자 하나에 다 담아 한 번에 실행하고, 이후 orchestration 왕복 없이 완료를 회수한다. (e2e·pgTAP은 여기서 안 돈다 — §0 참고.)

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
report_path="<worktree 루트>/.evaluate-agent-e2e-report.md"
orca_call_with_retry "orca-evaluate" "agent-e2e" -- \
  orca terminal create --worktree active --title eval-agent-e2e \
  --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오 + 앱 URL/worktree 경로 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
orca terminal wait --terminal <agent-e2e-handle> --for tui-idle --timeout-ms 900000 --json
# 완료 확인은 orchestration이 아니라 터미널 출력/report 파일로 한다 — headless는 dispatch --inject
# 대상이 아니고(agy.md 참고), 이 터미널의 셸 자체는 agy 프로세스가 끝나도 죽지 않으므로
# `--for exit`은 쓰지 않는다(agy.md 실측 참고).
orca terminal read --terminal <agent-e2e-handle> --json
# 할당 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로. role="agent-e2e", issue=<issue-num>,
# provider="agy", model=<model>, effort="", terminal=<agent-e2e-handle>, worktree=<worktree 경로>,
# task_id/dispatch_id 없음(orchestration 태스크가 아니므로).
```

이 세션(evaluator)은 agy의 자기 요약을 **그대로 믿지 않는다** — 이미 이 세션 자체가 롱컨텍스트 REPL 세션이므로, `$report_path`와 원본 트레이스를 직접(별도 터미널 스폰 없이) 읽어서 "성공했다"는 보고가 실제로 맞는지, 조용히 막히거나 우회한 흔적은 없는지 확인한다.

**실패 확정 시 fail-fast — §3 생략**: 위 재확인 결과 실패가 실제이고(자기 요약·report·트레이스가 일치) 인프라 원인이 아니라 AC-관련 동작 실패로 확인되면, §3 code-reviewer를 스폰하지 않고 곧장 §4로 간다 — §4의 PASS 조건이 어차피 agent e2e 통과를 요구하므로 리뷰를 돌려도 verdict는 FAIL로 같고, 강한 reasoning 모델 스폰 비용만 든다(이미 실패가 확정된 코드를 비싼 단계에 태우지 않는다는 `GATE_FAIL`과 같은 원칙). 이때 FAIL findings는 e2e 관찰(어떤 시나리오가 어떤 AC에서 실패했는지)로 작성하고, eval-report의 `code_review_ran`을 `false`로 남긴다 — 생략은 이번 attempt에 한하며, 다음 attempt는 §3을 다시 태운다. 인프라 원인(계정·secret·환경)이면 §4의 ESCALATE 규칙 그대로다. 부분 통과 등 판단이 애매하면 생략하지 않는다 — §3을 그대로 진행한다.

## 3. Diff 리뷰 (coding agent 스폰, agent e2e 결과 반영)

(§2가 실패 확정 fail-fast로 끝난 attempt면 이 절은 실행되지 않는다 — §2 참고.)

```bash
git diff "$(git merge-base origin/main HEAD)"...HEAD > <worktree 루트>/.evaluate-diff.patch
```

diff에 schema/migration 파일이 포함돼 있으면, code-reviewer를 스폰하기 전에 destructive-op 린터를 돌린다. 이때 계산한 "migration 파일 포함 여부"는 여기서 버리지 않는다 — 아래 리뷰어 tier 선택에도 그대로 전달해, churn(변경 파일 수·라인 수)이 작아도 migration/destructive 신호가 있으면 최저 tier로 떨어지지 않게 한다:

```bash
migration_files=( <diff에 포함된 migration 파일 경로...> )   # 각 경로를 개별 quoted 원소로 (배열 — bash/zsh 공통, unquoted 문자열 확장 금지: zsh는 word-split하지 않아 파일 2개 이상이면 인자 1개로 뭉개지고, bash/sh는 반대로 공백 있는 경로가 쪼개진다)
migration_files_present=false
[ ${#migration_files[@]} -gt 0 ] && migration_files_present=true
if [ "$migration_files_present" = true ] && [ -f scripts/migration-lint.py ]; then
  python3 scripts/migration-lint.py "${migration_files[@]}" > <worktree 루트>/.migration-lint.json
  lint_rc=$?
  if [ "$lint_rc" -eq 0 ]; then
    :   # clean — flag 없음, 그대로 진행
  elif [ "$lint_rc" -eq 1 ] && jq -e . <worktree 루트>/.migration-lint.json > /dev/null 2>&1; then
    :   # flag 발견(실패 아님, 유효 JSON) — 리뷰어 ④ 항목으로 전달. 근거는 아래 문단.
  else
    echo "migration-lint 크래시(rc=$lint_rc) — .migration-lint.json 신뢰 불가" >&2
    exit 1
  fi
fi
```

(`scripts/migration-lint.py`가 없는 repo는 린터 실행만 건너뛴다 — opt-in 게이트라 아무 일도 안 한다. `migration_files_present`는 린터 실행 여부와 무관하게 diff에 migration 파일이 있었다는 사실 자체를 기록해 리뷰어 tier 선택에 넘긴다. **rc=1은 실패가 아니라 flag 발견이다**(린터 docstring: "0=clean, 1=flag found") — 여기서 중단하면 §4의 유일한 하드 ESCALATE 경로(린터가 flag했는데 code-reviewer가 미커버로 판정)가 영원히 도달 불가가 된다. 문제는 uncaught exception도 rc=1로 끝난다는 것(`FileNotFoundError` 등, 실측: traceback + stdout 0바이트) — 그래서 rc=1일 때 `.migration-lint.json`의 JSON 유효성까지 같이 확인해야 "진짜 flag"와 "크래시"를 구분할 수 있다. rc>1이거나 rc=1인데 JSON이 무효/비어 있으면 그때만 크래시로 보고 신뢰하지 않은 채 중단한다.)

fresh-context code-reviewer terminal을 하나 스폰한다(이 evaluator 세션과는 별개 세션 — `orca-task-runner`(generator)와 달라야 한다는 뜻은 아니다). 모델·effort는 diff 통계(변경 파일 수·라인 수)를 `<skill-dir>/scripts/select_reviewer.py`에 넘겨 동적으로 고른다 — 후보 풀·제외 사유·high-risk-signal 오버라이드·Codex 가용성 판단·스폰 실패 시 재시도 로직은 `references/reviewer-selection.md` 참고(구체 모델명을 SKILL.md 본문에 복제하지 않는다 — `orca-task-runner` §0과 같은 원칙). 리뷰어는 반드시 이 항목들을 갖는다: ①skeptical 지침("동의 표명 불필요, 결함·spec-divergence만 보고, 근거 있는 우려를 안이하게 넘기지 말 것") ②확정 acceptance criteria(최종 라운드 proposal의 `draft_acceptance_criteria` — `contract-schema.md`의 "확정 AC의 정본") + issue 번호 ③**§2 agent e2e 결과 요약** — diff만으로는 안 보이는 런타임 동작(무엇이 실제로 실패했는지)을 code review가 근거로 쓸 수 있게 한다 ④**(schema/migration 변경이 있으면) `.migration-lint.json` 결과 + 최종 proposal의 `destructive_operations` 선언** — 린터가 flag한 항목 중 선언에 커버되지 않는 게 있으면 report에 명시하라는 지시와 함께 ⑤**게이트-안전성 판단 지시** — 이 diff가 orca 파이프라인 자신의 머지/게이트 안전성에 영향을 주는지(예시일 뿐 비망라적: 워크플로 스킬 문서, 게이트·훅 스크립트, CI·hook 설정, 이 파이프라인이 의존하는 셸 배선 자체를 수정하는 diff인지 등) 리뷰의 첫 단계로 판단하라고 지시한다. 영향이 있다고 판단되면 그 부분을 diff의 다른 코드보다 더 엄격하게(더 회의적으로, 더 많은 재현·실패 시나리오로) 검토하라고 요구한다. 이 판단은 정적 파일 경로 목록과 절대 대조하지 않는다 — 리뷰어 자신의 판단이다. 게이트-안전성 영향이 있다고 판단했는데 주어진 정보로 완전히 clear하지 못하면 Critical/Important finding 또는 명시적 escalation 사유로 report에 반드시 남기라고 지시한다(diff 규모가 작아 이 리뷰가 낮은 tier로 동적 선택됐더라도, 그 사실만으로 게이트-안전성 우려를 낮잡아 보지 말 것) ⑥**(contract가 override로 종결된 경우) `override.json`의 `unresolved_reasons`** — evaluator가 반려했지만 generator가 결정권으로 진행한 우려 지점이다. 각 항목이 diff·agent e2e 결과에서 실제 결함으로 실체화됐는지 명시적으로 판정해 report에 남기라는 지시와 함께 넘긴다(`ac_fidelity` 미해소는 여기 오지 않는다 — `orca-workflow-task` §1이 `CONTRACT_ESCALATE`로 먼저 자르므로, 여기 도달한 override는 `plan_coverage`-only다) ⑦**(attempt 2+면) 자신의 직전 `eval-report-a<k-1>.json`의 findings** — 각 finding이 실제 수정됐는지 확인하라는 지시와 함께. generator의 수정 요약·서술형 해명은 입력에 넣지 않는다 — 판정을 바꾸는 근거는 diff의 사실 변화뿐이다(`contract-schema.md`의 "재시도 입력 격리").

```bash
source ~/.agents/orca-workflows/scripts/orca_call_with_retry.sh
diff_shortstat="$(git diff --shortstat "$(git merge-base origin/main HEAD)"...HEAD)"
# codex_available: `~/.agents/orca-workflows/model-selection.md`의 "Quota check before pinning"
# 절차(orca account list --json 기준)로 codex를 먼저 판정한다 — hard-exclude면 false, 아니면 true.
# 이번 세션에서 더 최신 정보를 알고 있으면(예: 방금 quota 소진을 직접 확인) 그 값으로 덮어쓴다.
# 정보가 전혀 없을 때만 `command -v codex`로 바이너리 존재를 보조 확인한다(토큰/쿼터까지는 증명 못함).
codex_available=false   # quota check로 hard-exclude 아님을 확인하면 true로 바꿀 것
# migration_files_present: 위에서 이미 계산해 둔 것을 그대로 넘긴다 — churn이 작아도 migration
# 파일이 있으면 최저 tier로 떨어지지 않는다.
reviewer_json="$(python3 <skill-dir>/scripts/select_reviewer.py --shortstat "$diff_shortstat" \
  $( [ "$codex_available" = true ] && echo --codex-available || echo --no-codex-available ) \
  $( [ "$migration_files_present" = true ] && echo --high-risk-signal ))"
reviewer_provider="$(printf '%s' "$reviewer_json" | jq -r .provider)"
reviewer_model="$(printf '%s' "$reviewer_json" | jq -r .model)"
reviewer_effort="$(printf '%s' "$reviewer_json" | jq -r .effort)"
reviewer_advisor="$(printf '%s' "$reviewer_json" | jq -r '.advisor // empty')"

case "$reviewer_provider" in
  codex)  launch_cmd="<Codex launch 문법 — models/codex.md에서 model=$reviewer_model effort=$reviewer_effort로 resolve, --dangerously-bypass-approvals-and-sandbox 인라인 포함>" ;;
  claude-code) launch_cmd="<Claude Code launch 문법 — models/claude-code.md에서 model=$reviewer_model effort=$reviewer_effort${reviewer_advisor:+, advisor=$reviewer_advisor}로 resolve, --dangerously-skip-permissions 인라인 포함>" ;;
  *)      echo "select_reviewer.py did not return a known provider (jq/script failure?): $reviewer_json" >&2; exit 1 ;;
esac

# REPL 필수, one-shot 금지 — 이유는 §1의 동일 주석 참고
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
spec_text="<diff 절대경로 + 확정 acceptance criteria(위 ②의 정본) + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 최종 proposal의 destructive_operations 선언 + (override 종결 시) override.json의 unresolved_reasons(위 ⑥) + (attempt 2+) 직전 eval-report findings(위 ⑦) + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지 + 판정 결과를 보낼 orchestration 호출은 orca_call_with_retry로 감싸고 연결 실패를 즉시 사람에게 알리지 말라는 지시>"
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca orchestration task-create --spec "$spec_text" --retry-request "$(uuidgen)" --json
orca_call_with_retry "orca-evaluate" "code-review" -- \
  orca orchestration dispatch --task <task_id> --to <review-handle> --retry-request "$(uuidgen)" --inject --json
# 미전송 확인 — ~/.agents/orca-workflows/dispatch-verify.md 절차대로(issue #43·#58).
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  logging.md §1 assign 이벤트: role="code-review", issue=<issue-num>, task_id=<task_id>, provider=$reviewer_provider,
#    model=$reviewer_model, effort=$reviewer_effort, advisor=${reviewer_advisor:-}, terminal=<review-handle>,
#    worktree=<worktree 경로>
#  logging.md §2 term 로그: skill="orca-evaluate", role="code-review", terminal=<review-handle>, meta 기록 후
#    sent.content=$spec_text. 이 터미널에 대한 유일한 read는 위 dispatch-verify.md의 liveness probe
#    (불투명 payload-echo 확인 — issue #58)뿐이며, 이는 의도적으로 recv로 기록하지 않는다(§1 contract-review와 같은
#    이유 — report는 이 세션이 별도로 직접 읽는다, §3 본문 마지막 문단 참고).
```

report는 severity(Critical/Important/Minor) + 도달 조건 + 최악 결과 + fail-closed 여부를 포함해야 한다. 이 report는 작아서(요약된 finding 목록) 이 evaluator 세션이 직접 읽는다.

**agent e2e(§2)와 code review(§3)는 순차 실행이다** — code review가 agent e2e 결과를 입력으로 받아야 하므로 병렬로 못 돌린다. wall-clock이 늘어나는 트레이드오프를 감수한 것이다.

## 4. 리포트 합성 (evaluator 역할)

§1(contract 판정 기록) + §2(agent e2e 자기 요약 + 재확인 결과) + §3(code-reviewer report, agent e2e 결과가 이미 반영됨) 세 가지를 이 세션이 하나의 리포트로 합성한다(§2 fail-fast로 §3이 생략된 attempt면 §1+§2 두 가지다) — 이건 판단이 아니라 이미 나온 판단들을 압축하는 일이라(어려운 판단은 §1·§3에서 강한 reasoning 모델이 이미 끝냄) 이 세션(REPL-capable provider, agy 아님)이 그대로 해도 된다. PASS/FAIL/ESCALATE 매핑도 아래 고정 규칙을 그대로 적용하는 것이라 이 세션이 직접 낸다:

- **PASS** — code-reviewer report에 Critical/Important finding 없음, agent e2e 통과(자기 요약과 재확인 결과가 일치), contract 종결이 approved거나 `plan_coverage`-only override(override의 unresolved 항목이 §3 리뷰(입력 ⑥)에서 실제 결함으로 실체화되면 그게 곧 finding이라 첫 조건에서 걸린다 — override 자체는 PASS를 막지 않는다. `ac_fidelity` 미해소 override는 이 스킬에 도달하지 않는다: `orca-workflow-task` §1이 `CONTRACT_ESCALATE`로 먼저 자른다).
- **FAIL** — 구체적 finding(severity+근거+수정 방향)은 아래 `eval-report-a<attempt>.json`에 남기고, `orca-workflow-task`에는 FAIL verdict만 반환한다. (재시도는 `orca-workflow-task`가 관리한다 — 이 스킬은 재-dispatch하지 않는다. `orca-workflow-task`가 재시도 카운터를 세고, 필요하면 attempt 번호와 함께 `orca-task-runner`에 재-dispatch — evaluator가 task-runner를 직접 부르지 않고, feedback 본문도 `orca-workflow-task`를 거치지 않는다.)
- **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.

판정과 함께 `CONTRACT_DIR`에 `eval-report-a<attempt>.json`을 남긴다(attempt 번호는 spec으로 받은 값, 스키마·불변식은 `contract-schema.md` — `verdict` 필드는 반환값과 반드시 일치). FAIL 시 이 파일의 `findings`가 재-dispatch된 generator의 유일한 feedback 입력이다.

## 폴백

- orca 런타임 불가: coding agent(§1 contract 판정, §3 code review 둘 다)를 orca 없이 **Bash로 직접**(headless) 실행해 판정·report 회수 — §1은 고정된 강한 reasoning 모델 그대로, §3은 `select_reviewer.py`가 고른 모델·effort 그대로 유지한다(폴백이라는 이유로 §3의 동적 선택을 강한 고정으로 되돌리지 않는다). 할당 로그(§1)는 동일하게 남긴다 — `terminal` 필드만 대체 식별자로. agent e2e(§2)는 로컬에서 Playwright MCP를 붙인 headless agy 세션으로 직접 실행하고 report 경로만 기록. 이 evaluator 세션 자체(REPL, agy 아님)가 뜨지 않으면 `model-selection.md`의 다른 REPL 가능 provider로 대체하되, §1·§3의 coding agent는 반드시 이 세션과 다른 provider/모델을 유지한다(같은 세션이 스스로를 판단하지 않도록). 폴백 발동은 사용자에게 보고.
