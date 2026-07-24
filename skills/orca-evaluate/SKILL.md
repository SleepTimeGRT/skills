---
name: orca-evaluate
description: Use when evaluating a completed task's diff before merge — this session itself runs on agy(Gemini) for its speed/cost/computer-use strength (running the agent-e2e test gate and synthesizing everything into one report; e2e/pgTAP already passed a task-level gate in orca-task-runner before this diff arrived, so this skill never touches them), while it spawns a separate strong-coding-agent terminal for the two judgment calls it can't make well itself — sprint contract approval and diff code review informed by the agent-e2e result — against the issue's Acceptance criteria. Returns PASS, FAIL-with-feedback, or ESCALATE. Self-relative.
---

# Orca Evaluate

task(issue) 하나를 **1회** 평가한다(subtask마다 하지 않음). 코드를 쓰지 않는다 — `orca-task-runner`가 생성한 결과만 판단한다.

이 스킬이 하는 일은 세 가지다: **1) contract 협상, 2) test gate 실행, 3) code review.** 이 세션 자체(기본 agy/Gemini)가 직접 담당하는 건 **2번뿐**이다 — 1번과 3번은 실제 판단이 필요한 지점이라 별도의 coding-agent 터미널을 스폰해서 그 판단만 맡기고, 이 세션은 relay + 세 결과를 하나의 리포트로 합성하는 역할을 한다. 아래 §0에서 이유를 설명한다.

## 0. 이 세션 자체의 launch

`orca-workflow`가 이 스킬을 orchestration으로 띄운다 — orca-workflow 자신이 직접 실행하는 게 아니라 별도 터미널을 만들어 넘긴다:

```bash
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "agy -p '<이 SKILL.md 지침 + diff 경로 + issue 원문 acceptance criteria>' --model <token> --print-timeout 15m" --json
orca orchestration task-create --spec "<diff 경로 + issue 번호 + PASS/FAIL/ESCALATE 요청>" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
```

**이 세션은 기본적으로 agy(Gemini)로 뜬다** — §2의 agent e2e 실행과 §4의 리포트 합성이 이 세션의 핵심 업무이고, Gemini의 속도·비용·컴퓨터 사용 강점이 정확히 여기에 맞기 때문이다(`~/.agents/orca-workflows/model-selection.md`의 Computer Use / Long-Context 축, `~/.agents/orca-workflows/models/agy.md` 참고). e2e·pgTAP은 이 세션에 들어오지 않는다 — `orca-task-runner`의 task-레벨 게이트(`skills/orca-task-runner/SKILL.md` §6)를 이미 통과한 뒤에만 이 스킬이 호출되기 때문에 전량 신뢰하고 재검증하지 않는다. `gemini-3.6-flash`는 아직 이 리포에서 스모크 테스트 전이므로, 검증 전엔 `gemini-3.5-flash-high`로 launch한다.

**단, §1(Contract 검토)과 §3(Diff 리뷰)의 실제 판단은 이 세션의 몫이 아니다.** 둘 다 "코드/구현이 기술적으로 타당한가"를 보는 일이고, Gemini는 `model-selection.md`의 High Risk tier(production review/final approval)에서 SWE-Bench Pro 기준 Opus/Sol 앵커보다 낮다고 리포 스스로 표시해둔 지점이다 — 그래서 이 세션(evaluator)은 두 판단 모두 **강한 coding 모델 세션을 스폰**해서 맡기고, 자신은 relay + 최종 리포트 합성만 한다.

## 1. Contract 검토 (coding agent 스폰)

`orca-task-runner`가 구현 전 제안서(범위 + 검증 방법)를 보내오면, 이 세션(evaluator)이 직접 판단하지 않고 **coding agent 터미널을 스폰**해서 issue의 원본 `## Acceptance criteria`에 대조 검토를 맡긴다 — 제안된 파일 범위·검증 방법이 실제 코드베이스에서 기술적으로 타당한지 보는 일이라 §3 code-reviewer와 같은 이유로 강한 reasoning 모델이 낫다.

```bash
orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration task-create --spec "<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시>" --json
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 할당 로그 — 스폰하는 쪽이 남긴다. dispatch와 같은 블록에서 즉시 실행(누락 방지);
# orca 상태는 reset으로 소실될 수 있어 할당의 영속 기록은 이 파일이 유일하다. §2·§3 스폰도 동일.
install -d -m 700 ~/.agents/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"contract-review","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<contract-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.agents/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.agents/orca-workflows/logs/assignments.jsonl
```

판단 기준은 "제안이 그럴듯한가"가 아니라 "acceptance criteria를 실제로 커버하는가"다. 이 evaluator 세션은 그 판정 결과(승인/반려+사유)를 받아 `orca-task-runner`로 relay한다(파일 내용을 새로 읽거나 재해석하지 않고 판정 결과만 전달). 최대 2라운드까지 왕복하고, 그 안에 합의 안 되면 generator가 결정권을 가진다 — 이견은 기록만 하고 진행을 막지 않는다.

`## Acceptance criteria`가 issue body에 없으면 평가를 진행하지 않고 `orca-workflow`에 보고한다. (issue 생성 시 이 섹션을 보장하는 절차는 아직 없다 — 별도 후속 이슈. 임시로는 `/triage` 리다이렉트 대상으로 취급한다.)

두 번의 coding agent 스폰(여기 §1과 아래 §3)은 시간상 멀리 떨어져 있다(§1은 구현 시작 전, §3은 전체 subtask wave가 끝난 뒤) — 하나의 터미널을 그 사이 계속 띄워두지 않고, 그때그때 fresh-context로 새로 스폰한다.

## 2. Test Gate: Agent e2e (evaluator 자신이 실행)

앱을 직접 조작하는 e2e. Playwright MCP(accessibility-tree 기반이라 스크린샷·좌표 클릭보다 UI 변경에 덜 깨진다)를 붙인 agy(Gemini) 세션을 별도 터미널로 스폰한다 — 이 세션 자체가 이미 에이전트이므로, worker_done에 자기가 무엇을 했고 무엇이 실패했는지 자연어 요약을 실어 보낸다. (e2e·pgTAP은 더 이상 여기서 돌지 않는다 — `orca-task-runner`의 task-레벨 게이트로 이관되어 이 스킬에 들어오는 diff는 이미 그 둘을 통과한 상태다. evaluator는 그 사실을 전량 신뢰하고 재검증하지 않는다.)

```bash
orca terminal create --worktree active --title eval-agent-e2e \
  --command "agy -p '<Playwright MCP 지침 + 테스트 시나리오>' --model <token> --print-timeout 15m" --json
orca orchestration task-create --spec "<앱 URL/worktree 경로 + 테스트 시나리오 + 실패 시 무엇을 관찰했는지 요약해서 worker_done에 실어달라는 지침>" --json
orca orchestration dispatch --task <task_id> --to <agent-e2e-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"agent-e2e","issue":"<issue-num>","task_id":"<task_id>","provider":"agy","model":"<model>","effort":"","terminal":"<agent-e2e-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.agents/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고
```

이 세션(evaluator)은 그 자기 요약을 **그대로 믿지 않는다** — 이미 이 세션 자체가 롱컨텍스트 Gemini이므로, 원본 트레이스를 직접(별도 터미널 스폰 없이) 읽어서 "성공했다"는 보고가 실제로 맞는지, 조용히 막히거나 우회한 흔적은 없는지 확인한다.

## 3. Diff 리뷰 (coding agent 스폰, agent e2e 결과 반영)

```bash
git diff "$(git merge-base origin/main HEAD)"...HEAD > <worktree 루트>/.evaluate-diff.patch
```

diff에 schema/migration 파일이 포함돼 있으면, code-reviewer를 스폰하기 전에 destructive-op 린터를 돌린다:

```bash
python3 scripts/migration-lint.py <diff에 포함된 migration 파일 경로...> > <worktree 루트>/.migration-lint.json
```

(repo에 `scripts/migration-lint.py`가 없으면 이 단계를 건너뛴다 — opt-in 게이트이므로 미구성 repo에서는 아무 일도 하지 않는다.)

fresh-context code-reviewer terminal을 하나 스폰한다(이 evaluator 세션·generator와 별도 세션 — **강한 reasoning 모델 고정**, `model-selection.md` High Risk tier 참고: Claude Opus 4.8 xhigh / Codex Sol xhigh 등. "provider 자유, 가장 싼 provider"가 아니다 — 코드 정오 판단은 이 세션의 Gemini가 약하다고 표시된 지점이라 일부러 다른 모델을 쓰는 것). 리뷰어는 반드시 이 항목들을 갖는다: ①skeptical 지침("동의 표명 불필요, 결함·spec-divergence만 보고, 근거 있는 우려를 안이하게 넘기지 말 것") ②issue의 acceptance criteria 원문 ③**§2 agent e2e 결과 요약** — diff만으로는 안 보이는 런타임 동작(무엇이 실제로 실패했는지)을 code review가 근거로 쓸 수 있게 한다 ④**(schema/migration 변경이 있으면) `.migration-lint.json` 결과 + §1에서 받은 "의도된 destructive 오퍼레이션" 선언** — 린터가 flag한 항목 중 선언에 커버되지 않는 게 있으면 report에 명시하라는 지시와 함께.

```bash
orca terminal create --worktree active --title eval-review \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration task-create --spec "<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>" --json
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"code-review","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<review-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.agents/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고
```

report는 severity(Critical/Important/Minor) + 도달 조건 + 최악 결과 + fail-closed 여부를 포함해야 한다. 이 report는 작아서(요약된 finding 목록) 이 evaluator 세션이 직접 읽는다.

**agent e2e(§2)와 code review(§3)는 순차 실행이다** — code review가 agent e2e 결과를 입력으로 받아야 하므로 병렬로 못 돌린다. wall-clock이 늘어나는 트레이드오프를 감수한 것이다.

## 4. 리포트 합성 (evaluator 역할)

§1(contract 판정 기록) + §2(agent e2e 자기 요약 + 재확인 결과) + §3(code-reviewer report, agent e2e 결과가 이미 반영됨) 세 가지를 이 세션이 하나의 리포트로 합성한다 — 이건 판단이 아니라 이미 나온 판단들을 압축하는 일이라(어려운 판단은 §1·§3에서 강한 reasoning 모델이 이미 끝냄) Gemini가 해도 된다. PASS/FAIL/ESCALATE 매핑도 아래 고정 규칙을 그대로 적용하는 것이라 이 세션이 직접 낸다:

- **PASS** — code-reviewer report에 Critical/Important finding 없음, contract 판정 승인 상태 유지, agent e2e 통과(자기 요약과 재확인 결과가 일치).
- **FAIL** — 구체적 finding(severity+근거) + 수정 방향을 `orca-workflow`에 반환한다. (재시도는 `orca-workflow`가 관리한다 — 이 스킬은 재-dispatch하지 않는다. `orca-workflow`가 이 리포트를 받아 재시도 카운터를 세고, 필요하면 `orca-task-runner`에 재-dispatch — evaluator가 task-runner를 직접 부르지 않는다.)
- **ESCALATE** — 다음 중 하나면 재시도 없이 즉시: acceptance criteria 자체가 애매해서 판정이 불가능, 구현이 issue 스코프 밖의 것을 건드림, agent e2e가 인프라 문제(계정·secret·환경)로 판단 불가, **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서의 destructive-op 선언에 커버되지 않는다고 명시함**.

## 폴백

- orca 런타임 불가: coding agent(§1 contract 판정, §3 code review 둘 다)를 orca 없이 **Bash로 직접**(headless, 강한 reasoning 모델 그대로) 실행해 판정·report 회수. 할당 로그(§1)는 동일하게 남긴다 — `terminal` 필드만 대체 식별자로. agent e2e(§2)는 로컬에서 Playwright MCP를 붙인 세션으로 직접 실행하고 요약 경로만 기록. 이 evaluator 세션 자체(agy)가 뜨지 않으면 다른 provider로 대체하되, §1·§3의 coding agent는 반드시 이 세션과 다른 provider/모델을 유지한다(같은 세션이 스스로를 판단하지 않도록). 폴백 발동은 사용자에게 보고.
