---
name: orca-evaluate
description: Use when evaluating a completed task's diff before merge — this session itself runs on a REPL-capable provider other than agy (agy REPL launches are unsupported here, see `~/.agents/orca-workflows/models/agy.md`), spawning agy headless for the agent-e2e test gate (its speed/cost/computer-use strength; e2e/pgTAP already passed a task-level gate in orca-task-runner before this diff arrived, so this skill never touches them) and synthesizing everything into one report, while also spawning a separate strong-coding-agent terminal for the two judgment calls it can't make well itself — sprint contract approval and diff code review informed by the agent-e2e result — against the issue's Acceptance criteria. Returns PASS, FAIL-with-feedback, or ESCALATE. Self-relative.
---

# Orca Evaluate

task(issue) 하나를 **1회** 평가한다(subtask마다 하지 않음). 코드를 쓰지 않는다 — `orca-task-runner`가 생성한 결과만 판단한다.

이 스킬이 하는 일은 세 가지다: **1) contract 협상, 2) test gate 실행(agent e2e), 3) code review.** 셋 다 이 세션 자체가 직접 실행하지 않는다 — 1번과 3번은 실제 기술 판단이 필요한 지점이라, 2번은 agy를 REPL로 쓰지 않기로 한 결정(아래 §0, `agy.md` 참고) 때문에 각각 별도 터미널로 스폰하고, 이 세션은 relay + 스폰 + 세 결과를 하나의 리포트로 합성하는 역할만 한다.

## 0. 이 세션 자체의 launch — REPL 가능한 provider로, agy는 제외

`orca-workflow`가 이 스킬을 orchestration으로 띄운다 — orca-workflow 자신이 직접 실행하는 게 아니라 별도 터미널을 만들어 넘긴다. 스폰이 실패하면(파싱 에러, no-output, timeout with zero output 등) 처음부터 재진단하지 않는다 — `~/.agents/orca-workflows/spawn-failures.md`의 grep-first 절차를 따른다. 이 확인은 여기 §0뿐 아니라 아래 §1·§2·§3의 `terminal create` 호출 전부에 적용된다.

**이 세션은 REPL로 띄운다** — one-shot(`agy -p ... --print-timeout`)은 이후 `dispatch --inject`가 이미
종료된 프로세스의 셸에 떨어져 도달하지 못한다(`~/.agents/orca-workflows/spawn-failures.md`, issue #37
참고). **단, 그 REPL을 agy로 띄우지 않는다** — agy REPL은 포커스가 없으면 부팅 자체가 멈추고, 두 세션이
동시에 focus를 다투면 나중에 focus를 다시 줘도 복구되지 않는 영구 데드락으로 이어질 수 있음이 실측됐다
(2026-07-30, `~/.agents/orca-workflows/models/agy.md` 참고 — agy는 이 repo 전체에서 headless 전용). 그래서
이 세션은 `~/.agents/orca-workflows/model-selection.md` 기준으로 REPL이 검증된 다른 provider로 resolve한다
(구체 모델명을 여기 복제하지 않는다 — 아래 §1·§3의 sub-agent 스폰과 같은 원칙). launch-then-inject 시퀀스는
그 provider 자신의 launch 문서를 따른다:

```bash
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는 절차를 따른다
# (agy처럼 자동 확정 가능한 provider도 있고 아닐 수도 있다 — 여기서 agy 전용 시퀀스를 가정하지 않는다).
orca orchestration task-create --spec "<이 SKILL.md 지침 + diff 경로 + issue 원문 acceptance criteria + PASS/FAIL/ESCALATE 요청>" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
```

**이 세션 자체는 agy가 아니다.** agy는 §2(agent e2e)에서만, 그것도 headless sub-spawn으로만 쓴다 — Gemini의
속도·비용·컴퓨터 사용 강점이 정확히 agent e2e 실행에 맞기 때문이다(`~/.agents/orca-workflows/model-selection.md`의
Computer Use / Long-Context 축, `~/.agents/orca-workflows/models/agy.md` 참고). e2e·pgTAP은 이 세션(또는 §2
sub-spawn)에 새로 들어오지 않는다 — `orca-task-runner`의 task-레벨 게이트(`skills/orca-task-runner/SKILL.md`
§6)를 이미 통과한 뒤에만 이 스킬이 호출되기 때문에 전량 신뢰하고 재검증하지 않는다.

**단, §1(Contract 검토)과 §3(Diff 리뷰)의 실제 판단은 이 세션의 몫이 아니다.** 둘 다 "코드/구현이 기술적으로 타당한가"를 보는 technical judgment이고, `model-selection.md`의 Computer Use/Long-Context 축 Exclusion 조항이 명시하듯 이 축(agent e2e·리포트 합성)을 쓰는 세션이라도 technical judgment call은 이 축에 올리지 않는다 — Default Mapping도 Gemini를 Routine/High Risk 코드 판단에 배정하지 않는다. 그래서 이 세션(evaluator)은 두 판단 모두 fresh-context coding-agent 세션에 맡기고, 자신은 relay + 최종 리포트 합성만 한다 — §1(계약 검토)은 고정된 강한 reasoning 모델을 쓰고, §3(diff 리뷰)은 diff 통계로 동적 선택된 모델을 쓴다(§3 참고).

## 1. Contract 검토 (coding agent 스폰)

`orca-task-runner`가 구현 전 제안서(범위 + 검증 방법)를 보내오면, 이 세션(evaluator)이 직접 판단하지 않고 **coding agent 터미널을 스폰**해서 issue의 원본 acceptance-criteria 섹션(`orca-workflow`가 dispatch spec으로 넘겨준 섹션명)에 대조 검토를 맡긴다 — 제안된 파일 범위·검증 방법이 실제 코드베이스에서 기술적으로 타당한지 보는, 구현 착수 전의 1회성 판단이라 diff 규모 같은 위험도를 낮출 신호가 아직 존재하지 않는 시점이다. 그래서 여기는 고정된 강한 reasoning 모델(`model-selection.md` High Risk tier)을 쓴다 — §3처럼 사후에 diff 통계로 동적으로 낮추지 않는다.

```bash
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration task-create --spec "<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시>" --json
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 할당 로그 — 스폰하는 쪽이 남긴다. dispatch와 같은 블록에서 즉시 실행(누락 방지);
# orca 상태는 reset으로 소실될 수 있어 할당의 영속 기록은 이 파일이 유일하다. §2·§3 스폰도 동일.
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"contract-review","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<contract-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl
```

판단 기준은 "제안이 그럴듯한가"가 아니라 "acceptance criteria를 실제로 커버하는가"다. 이 evaluator 세션은 그 판정 결과(승인/반려+사유)를 받아 `orca-task-runner`로 relay한다(파일 내용을 새로 읽거나 재해석하지 않고 판정 결과만 전달). 최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.

acceptance-criteria 섹션 존재 확인은 `orca-workflow`가 `orca-task-runner`를 dispatch하기 전에 이미
gate로 처리한다(`skills/orca-workflow/SKILL.md` §2, outcome `NO_ACCEPTANCE_CRITERIA`) — 이 스킬이
호출됐다는 것 자체가 그 섹션이 존재함을 의미하므로 여기서 다시 확인하지 않는다.

두 번의 coding agent 스폰(여기 §1과 아래 §3)은 시간상 멀리 떨어져 있다(§1은 구현 시작 전, §3은 전체 subtask wave가 끝난 뒤) — 하나의 터미널을 그 사이 계속 띄워두지 않고, 그때그때 fresh-context로 새로 스폰한다.

## 2. Test Gate: Agent e2e (evaluator가 headless agy로 스폰)

앱을 직접 조작하는 e2e. Playwright MCP(accessibility-tree 기반이라 스크린샷·좌표 클릭보다 UI 변경에 덜 깨진다)를 붙인 agy(Gemini) 세션을 별도 터미널로 스폰한다 — **headless(`-p`, one-shot)로**, REPL이 아니다. agy는 이 스킬 전체에서 REPL로 띄우지 않는다(`~/.agents/orca-workflows/models/agy.md` 참고 — 2026-07-30 실측: REPL은 포커스가 없으면 부팅이 멈추고, 두 세션이 동시에 focus를 다투면 영구 데드락으로 이어질 수 있다). 시나리오·경로·요청 형식을 전부 launch 시점의 `-p` 인자 하나에 담아 한 번에 실행하고, 이후 별도 orchestration 왕복 없이 완료를 회수한다. (e2e·pgTAP은 더 이상 여기서 돌지 않는다 — `orca-task-runner`의 task-레벨 게이트로 이관되어 이 스킬에 들어오는 diff는 이미 그 둘을 통과한 상태다. evaluator는 그 사실을 전량 신뢰하고 재검증하지 않는다.)

```bash
report_path="<worktree 루트>/.evaluate-agent-e2e-report.md"
orca terminal create --worktree active --title eval-agent-e2e \
  --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오 + 앱 URL/worktree 경로 + 실패 시 무엇을 관찰했는지 요약해서 $report_path에 저장하고 완료 시 한 줄 요약도 출력하라는 지침>' --model <token> --print-timeout 15m --dangerously-skip-permissions" --json
orca terminal wait --terminal <agent-e2e-handle> --for tui-idle --timeout-ms 900000 --json
# 완료 확인은 orchestration이 아니라 터미널 출력/report 파일로 한다 — headless는 dispatch --inject
# 대상이 아니고(agy.md 참고), 이 터미널의 셸 자체는 agy 프로세스가 끝나도 죽지 않으므로
# `--for exit`은 쓰지 않는다(agy.md 실측 참고).
orca terminal read --terminal <agent-e2e-handle> --json
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"agent-e2e","issue":"<issue-num>","provider":"agy","model":"<model>","effort":"","terminal":"<agent-e2e-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고, task_id/dispatch_id 없음(orchestration 태스크가 아니므로)
```

이 세션(evaluator)은 agy의 자기 요약을 **그대로 믿지 않는다** — 이미 이 세션 자체가 롱컨텍스트 REPL 세션이므로, `$report_path`와 원본 트레이스를 직접(별도 터미널 스폰 없이) 읽어서 "성공했다"는 보고가 실제로 맞는지, 조용히 막히거나 우회한 흔적은 없는지 확인한다.

## 3. Diff 리뷰 (coding agent 스폰, agent e2e 결과 반영)

```bash
git diff "$(git merge-base origin/main HEAD)"...HEAD > <worktree 루트>/.evaluate-diff.patch
```

diff에 schema/migration 파일이 포함돼 있으면, code-reviewer를 스폰하기 전에 destructive-op 린터를 돌린다. 이때 계산한 "migration 파일 포함 여부"는 여기서 버리지 않는다 — 아래 리뷰어 tier 선택에도 그대로 전달해, churn(변경 파일 수·라인 수)이 작아도 migration/destructive 신호가 있으면 최저 tier로 떨어지지 않게 한다(§3 자신이 이미 계산해 둔 신호를 tier 선택 시점에 버리는 것이 결함이었다 — 새 정적 경로 매칭을 추가하는 것이 아니다, AC1과 무관):

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
    :   # flag 발견 — rc=1은 린터가 정상적으로 destructive-op을 찾았다는 신호이지 실패가 아니다.
        # 여기서 중단하면 §4의 유일한 하드 ESCALATE 규칙(린터가 flag했는데 code-reviewer가 미커버로
        # 판정)이 영원히 도달 불가가 된다. .migration-lint.json은 유효 JSON이므로 그대로 신뢰하고
        # 리뷰어 ④ 항목으로 전달한다.
  else
    echo "migration-lint 크래시(rc=$lint_rc) — .migration-lint.json 신뢰 불가" >&2
    exit 1
  fi
fi
```

(repo에 `scripts/migration-lint.py`가 없으면 린터 실행만 건너뛴다 — opt-in 게이트이므로 미구성 repo에서는 아무 일도 하지 않는다. `migration_files_present`는 린터 실행 여부와 무관하게 **diff에 migration 파일이 있었다는 사실 자체**를 기록한다 — `scripts/migration-lint.py`가 없는 repo라도 migration 파일을 건드리는 diff는 여전히 리뷰어 tier 선택에서 high-risk로 취급돼야 하기 때문이다. **rc=1은 실패가 아니다** — 이 repo가 배포하는 린터 자신의 docstring이 "Exit code 0 = clean, 1 = one or more flags found"라고 명시하고, flag는 "스스로 차단하지 않고 intent check(사람 리뷰 또는 orca-evaluate contract 대조)로 라우팅되어야 한다"고 못박는다. 그래서 rc=1이면서 `.migration-lint.json`이 유효 JSON이면(린터는 flag를 print한 *뒤에* rc=1로 종료하므로 flag 케이스의 JSON은 항상 완전하다) 그 파일을 신뢰하고 계속 진행한다. rc만으로는 "flag됨"과 "크래시"를 구분할 수 없다 — uncaught exception도 Python 기본 동작상 rc=1로 끝나기 때문이다(`FileNotFoundError` 등, 실측: traceback + stdout 0바이트). 그래서 rc=1일 때 JSON 유효성까지 함께 확인하고, rc>1(예: argparse 인자 오류)이거나 rc=1인데 JSON이 무효/비어 있으면 그때만 진짜 크래시로 보고 `.migration-lint.json`을 신뢰하지 않은 채 중단한다.)

fresh-context code-reviewer terminal을 하나 스폰한다(**이 evaluator 세션과는 별개 세션** — 코드 정오 판단을 자기 세션에 맡기지 않는다는 뜻이지, `orca-task-runner`(generator)와 달라야 한다는 뜻은 아니다: `models/codex.md`가 이미 "Evaluators require fresh context, not a different provider"로 명시하듯, 요구되는 것은 fresh-context(별도 세션)뿐이고 리뷰어가 generator와 다른 모델/provider여야 한다는 하드 요구사항은 없다 — 우연히 같은 모델이 선택돼도 무방하고 provider가 다르면 다양성 이점은 있지만 필수 조건은 아니다). 모델·effort는 diff 통계(변경 파일 수·라인 수)를 `<skill-dir>/scripts/select_reviewer.py`에 넘겨 동적으로 고른다 — 후보 풀은 Codex의 `gpt-5.6-terra`/`gpt-5.6-sol`과 Claude의 `claude-sonnet-5`(+ `--advisor opus`)/`claude-opus-5`이고, `claude-fable-5`는 제외한다(2026-07 벤치마크상 opus-5 대비 유의미한 우위 없음 — `model-selection.md`의 기존 금지 그대로 유지). 이 diff 통계만으로는 churn이 작은 destructive migration diff가 최저 tier로 떨어질 수 있으므로, 위에서 이미 계산해 둔 `migration_files_present`를 `--high-risk-signal`로 함께 넘겨 그런 diff가 churn과 무관하게 high-risk tier로 강제되게 한다 — 이것도 새 경로 매칭이 아니라 §3이 이미 다른 목적(destructive-op 린터 실행 여부)으로 계산해 둔 값을 그대로 재사용하는 것이다. Codex 가용성은 **이번 세션에서 사용자가 알려준 정보를 1차 근거**로 판단한다(`command -v codex`는 바이너리 존재만 증명하는 보조 신호일 뿐 토큰·쿼터 가용성을 증명하지 못한다) — 이 문서 어디에도 "Codex는 이 환경에서 쓸 수 없다"는 식의 고정 서술을 두지 않는다. Codex 세션 스폰이 실패하면(`~/.agents/orca-workflows/spawn-failures.md` 절차로 스폰 실패임을 먼저 확인) 처음부터 재진단하지 않고 `select_reviewer.py --no-codex-available`로 재호출해 Claude 분기로 다시 스폰한다 — `select_reviewer` 자신은 순수 함수라 스폰 실패를 감지할 수 없으므로 이 재시도는 호출자(이 스폰 지점)의 몫이다. 구체 모델명을 여기 복제하지 않는다(`orca-task-runner` §0과 같은 원칙; 복제가 모델 교체 때마다 stale의 원인이 된다). 리뷰어는 반드시 이 항목들을 갖는다: ①skeptical 지침("동의 표명 불필요, 결함·spec-divergence만 보고, 근거 있는 우려를 안이하게 넘기지 말 것") ②issue의 acceptance criteria 원문 ③**§2 agent e2e 결과 요약** — diff만으로는 안 보이는 런타임 동작(무엇이 실제로 실패했는지)을 code review가 근거로 쓸 수 있게 한다 ④**(schema/migration 변경이 있으면) `.migration-lint.json` 결과 + §1에서 받은 "의도된 destructive 오퍼레이션" 선언** — 린터가 flag한 항목 중 선언에 커버되지 않는 게 있으면 report에 명시하라는 지시와 함께 ⑤**게이트-안전성 판단 지시** — 이 diff가 orca 파이프라인 자신의 머지/게이트 안전성에 영향을 주는지(예시일 뿐 비망라적: 워크플로 스킬 문서, 게이트·훅 스크립트, CI·hook 설정, 이 파이프라인이 의존하는 셸 배선 자체를 수정하는 diff인지 등) 리뷰의 첫 단계로 판단하라고 지시한다. 영향이 있다고 판단되면 그 부분을 diff의 다른 코드보다 더 엄격하게(더 회의적으로, 더 많은 재현·실패 시나리오로) 검토하라고 요구한다. 이 판단은 정적 파일 경로 목록과 절대 대조하지 않는다 — 리뷰어 자신의 판단이다. 게이트-안전성 영향이 있다고 판단했는데 주어진 정보로 완전히 clear하지 못하면 Critical/Important finding 또는 명시적 escalation 사유로 report에 반드시 남기라고 지시한다(diff 규모가 작아 이 리뷰가 낮은 tier로 동적 선택됐더라도, 그 사실만으로 게이트-안전성 우려를 낮잡아 보지 말 것).

```bash
diff_shortstat="$(git diff --shortstat "$(git merge-base origin/main HEAD)"...HEAD)"
# codex_available: 1차 근거는 이번 세션에서 사용자가 알려준 정보. 그 정보가 없을 때만
# `command -v codex`로 바이너리 존재를 보조 확인한다(토큰/쿼터까지는 증명하지 못한다).
codex_available=true   # 세션에서 알려진 가용성으로 덮어쓸 것
# migration_files_present: 위에서 이미 계산해 둔 것을 그대로 넘긴다 — churn이 작아도 migration
# 파일이 있으면 최저 tier로 떨어지지 않는다(round1 Finding 2 수정).
reviewer_json="$(python3 <skill-dir>/scripts/select_reviewer.py --shortstat "$diff_shortstat" \
  $( [ "$codex_available" = true ] && echo --codex-available || echo --no-codex-available ) \
  $( [ "$migration_files_present" = true ] && echo --high-risk-signal ))"
reviewer_provider="$(printf '%s' "$reviewer_json" | jq -r .provider)"
reviewer_model="$(printf '%s' "$reviewer_json" | jq -r .model)"
reviewer_effort="$(printf '%s' "$reviewer_json" | jq -r .effort)"
reviewer_advisor="$(printf '%s' "$reviewer_json" | jq -r '.advisor // empty')"

case "$reviewer_provider" in
  codex)  launch_cmd="<Codex launch 문법 — models/codex.md에서 model=$reviewer_model effort=$reviewer_effort로 resolve>" ;;
  claude) launch_cmd="<Claude Code launch 문법 — models/claude-code.md에서 model=$reviewer_model effort=$reviewer_effort${reviewer_advisor:+, advisor=$reviewer_advisor}로 resolve>" ;;
  *)      echo "select_reviewer.py did not return a known provider (jq/script failure?): $reviewer_json" >&2; exit 1 ;;
esac

# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
orca orchestration task-create --spec "<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>" --json
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"code-review","issue":"<issue-num>","task_id":"<task_id>","provider":"%s","model":"%s","effort":"%s","advisor":"%s","terminal":"<review-handle>","worktree":"<worktree 경로>"}\n' \
  "$(date -u +%FT%TZ)" "$reviewer_provider" "$reviewer_model" "$reviewer_effort" "${reviewer_advisor:-}" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고
```

report는 severity(Critical/Important/Minor) + 도달 조건 + 최악 결과 + fail-closed 여부를 포함해야 한다. 이 report는 작아서(요약된 finding 목록) 이 evaluator 세션이 직접 읽는다.

**agent e2e(§2)와 code review(§3)는 순차 실행이다** — code review가 agent e2e 결과를 입력으로 받아야 하므로 병렬로 못 돌린다. wall-clock이 늘어나는 트레이드오프를 감수한 것이다.

## 4. 리포트 합성 (evaluator 역할)

§1(contract 판정 기록) + §2(agent e2e 자기 요약 + 재확인 결과) + §3(code-reviewer report, agent e2e 결과가 이미 반영됨) 세 가지를 이 세션이 하나의 리포트로 합성한다 — 이건 판단이 아니라 이미 나온 판단들을 압축하는 일이라(어려운 판단은 §1·§3에서 강한 reasoning 모델이 이미 끝냄) 이 세션(REPL-capable provider, agy 아님)이 그대로 해도 된다. PASS/FAIL/ESCALATE 매핑도 아래 고정 규칙을 그대로 적용하는 것이라 이 세션이 직접 낸다:

- **PASS** — code-reviewer report에 Critical/Important finding 없음, contract 판정 승인 상태 유지, agent e2e 통과(자기 요약과 재확인 결과가 일치).
- **FAIL** — 구체적 finding(severity+근거) + 수정 방향을 `orca-workflow`에 반환한다. (재시도는 `orca-workflow`가 관리한다 — 이 스킬은 재-dispatch하지 않는다. `orca-workflow`가 이 리포트를 받아 재시도 카운터를 세고, 필요하면 `orca-task-runner`에 재-dispatch — evaluator가 task-runner를 직접 부르지 않는다.)
- **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.

## 폴백

- orca 런타임 불가: coding agent(§1 contract 판정, §3 code review 둘 다)를 orca 없이 **Bash로 직접**(headless) 실행해 판정·report 회수 — §1은 고정된 강한 reasoning 모델 그대로, §3은 `select_reviewer.py`가 고른 모델·effort 그대로 유지한다(폴백이라는 이유로 §3의 동적 선택을 강한 고정으로 되돌리지 않는다). 할당 로그(§1)는 동일하게 남긴다 — `terminal` 필드만 대체 식별자로. agent e2e(§2)는 로컬에서 Playwright MCP를 붙인 headless agy 세션으로 직접 실행하고 report 경로만 기록. 이 evaluator 세션 자체(REPL, agy 아님)가 뜨지 않으면 `model-selection.md`의 다른 REPL 가능 provider로 대체하되, §1·§3의 coding agent는 반드시 이 세션과 다른 provider/모델을 유지한다(같은 세션이 스스로를 판단하지 않도록). 폴백 발동은 사용자에게 보고.
