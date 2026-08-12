# Contract Negotiation Schema

Shared reference for `orca-workflow-task`(§1 relay, §4 FAIL relay), `orca-task-runner`(§1, §7),
`orca-evaluate`(§1, §4). Defines the on-disk artifacts the contract lifecycle exchanges — 협상
라운드(proposal/verdict/override)와 이행 평가(eval-report) 둘 다. The coordinator relays the
directory path and round/attempt numbers only; generator and evaluator read/write these files
directly.

## Directory

```bash
CONTRACT_DIR="$HOME/.local/state/orca-workflows/contracts/<project-slug>/issue-<issue>"
install -d -m 700 "$CONTRACT_DIR"
```

- `<project-slug>`: 대상 repo의 디렉토리명(예: `medicount`). 코디네이터(`orca-workflow-task`)가 계산해
  두 spec_text에 절대경로로 넣는다. run-id 사이드카 파일명에도 같은 값이 재사용된다(logging.md §3,
  issue #159).
- `<issue>`: 처리 중인 task issue 번호 — 큐 항목마다 별개 디렉토리다. 계산·생성 시점은 그 task의
  §1 시작 시(`orca-workflow-task` §0).
- 워크트리 밖(전역)인 이유: worktree는 merge 후 삭제되지만 retro(`orca-retro`)는 root issue close 후에
  이 기록을 읽는다. 실수 커밋 위험도 없다. per-project 폴더는 repo가 다른 같은 issue 번호끼리의
  충돌을 막는다.
- 파일은 라운드별 append-only — r1 파일을 r2에서 수정하지 않는다(라운드 간 규칙 — 크래시-재개의
  같은 라운드 재-태움은 예외, 아래 크래시-재개 절). 파일은 `chmod 600`.
- **launch posture 전제**: 이 경로는 워크스페이스 밖이므로, contract 파일을 쓰는 역할
  (task-runner/evaluator)을 codex로 띄울 때 `-s workspace-write` 샌드박스로는 쓸 수 없다 —
  워크스페이스 밖 쓰기가 가능한 posture여야 한다. 현행 codex posture
  (`--dangerously-bypass-approvals-and-sandbox`, `models/codex.md`)가 이를 충족한다.

## Files

| file | writer | when |
|---|---|---|
| `proposal-r<n>.json` | orca-task-runner (generator) | 라운드 n 제안 (r3+는 override 후속 라운드 — 아래 절) |
| `verdict-r<n>.json` | orca-evaluate (evaluator) | 라운드 n 판정 |
| `override.json` | orca-task-runner | 2라운드에도 rejected일 때 결정권 행사 기록 |
| `gate-flake-a<k>.json` | orca-task-runner (generator) | attempt k의 task 게이트가 재시도 후 통과(flake 재분류)했을 때만 |
| `eval-report-a<k>.json` | orca-evaluate (evaluator) | 구현 attempt k의 평가 판정 기록 |

## proposal-r&lt;n&gt;.json

```json
{
  "schema_version": 1,
  "issue": "<issue id — GitHub 번호든 Jira 키든 문자열>",
  "run_id": "<orchestration run id>",
  "task_id": "<이 라운드의 task id>",
  "round": 1,
  "draft_acceptance_criteria": [ {"id": "ac1", "text": "<판정 가능한 완료 기준>"} ],
  "scope": { "summary": "<무엇을 만들 것인가 — 사실 서술만>", "files": ["<path>"] },
  "verification_plan": [ {"covers": ["ac1"], "method": "<구체 파일/함수/테스트>", "fails_before_fix": "<이 항목이 fix 이전에 어떻게 실패하는지, 또는 왜 실패할 수 없는지>"} ],
  "destructive_operations": [ "<의도된 destructive op 설명>" ],
  "existing_tests_affected": [ {"location": "<file:line>", "reason": "<이 변경으로 red가 되는 이유>"} ]
}
```

- **모든 필드 필수.** `destructive_operations`/`existing_tests_affected`의 빈 배열 `[]`은
  "명시적으로 없음"이다 — 필드가 아예 없으면 스키마 위반이므로 "언급 안 함" 상태는 존재할 수
  없다(종전 prose 제안서의 "공란 vs 없음" 구분을 스키마 필수성이 대체한다). `verification_plan[].fails_before_fix`도 같은 규칙이다 — 비어 있거나 필드 자체가 없으면 스키마 위반이다. 변별 불가일 때도 침묵이 아니라 그 사실을 명시적으로 적는다 — 예: 이 항목이 fix 전후 구분이 불가능한 이유를 그대로 서술한다. **무동작(no-op) 통과 금지**: `fails_before_fix`를 채울 때, 이 검증 방법이 stub/no-op(빈 구현, 아무 것도 하지 않는 구현)에서도 통과하는지 스스로 점검한다. 통과한다면 그 검증 방법 자체가 스키마 위반이다 — 구조적 존재 확인(예: 특정 API 호출 문자열이 소스에 있는지)만으로는 무동작 구현을 배제하지 못하는 경우가 이에 해당한다. 여러 경로를 커버해도 전부 구조적 확인이면 여전히 무동작을 통과시킨다는 점에 유의한다(happy-path만 커버 금지 규칙과는 별개 축).
- **설득 서술 필드는 의도적으로 없다.** "왜 이 제안이 충분한가"류 정당화는 어떤 필드에도 넣지
  않는다(`scope.summary` 포함 — 사실 서술만). `verification_plan[].fails_before_fix`도 같은 경계를 따른다 — pre-fix 동작에 대한 사실 서술이지 "왜 이 항목이 검증으로 충분한가" 정당화가 아니다. 근거는 아래 "라운드 2 입력 격리".
- `verification_plan[].covers`는 `draft_acceptance_criteria`의 id만 참조한다. 어떤 plan 항목도
  커버하지 않는 ac id가 남으면 evaluator가 기계적으로 잡을 수 있다. `fails_before_fix`가 비어 있거나 없거나 "fix 이후에도 동일하다"고 스스로 적은 항목도 evaluator가 기계적으로 반려할 수 있다.
- `draft_acceptance_criteria`의 각 항목은 (a) **binary**(판정 가능 — "좋다/나쁘다" 같은 주관적
  기준 금지) (b) **independent**(정확히 한 가지만 검증 — 여러 조건을 접속사로 묶지 않음) (c) 배열에
  쓰는 순서가 곧 **중요도 순서**(ordered by importance)여야 한다. 새 필드를 추가하지 않는다 — 배열
  순서 자체가 우선순위다. evaluator는 이 3원칙 위반을 `ac_fidelity` 반려 사유로 삼을 수 있다(Spec-
  Driven Development 관행 — round1 반려율 88%의 근본 원인이 AC 자체 품질이라는 실측 근거,
  `docs/superpowers/specs/2026-08-12-contract-sprint-improvements-design.md`).

## verdict-r&lt;n&gt;.json

```json
{
  "schema_version": 1,
  "issue": "<issue id>",
  "run_id": "<orchestration run id>",
  "task_id": "<판정 라운드의 task id>",
  "round": 1,
  "status": "approved",
  "ac_fidelity_ok": true,
  "plan_covers_ac": true,
  "reasons": [ {"target": "ac_fidelity", "ac_id": "ac2", "reason": "<구체 근거>"} ]
}
```

- `ac_fidelity_ok`: AC 초안이 원본 issue의 요구를 충실히 반영하는가(누락·과소·과대).
- `plan_covers_ac`: verification_plan이 그 AC를 실제로 커버하는가.
- `reasons[].target`은 `"ac_fidelity"` 또는 `"plan_coverage"`; `ac_id`는 특정 항목을 가리킬 때만,
  아니면 `null`. 커버리지 누락(기존 축)과 `fails_before_fix` 결함(신규 축) 둘 다 verification_plan의 품질에 대한 것이므로 두 축 모두 `"plan_coverage"`로 지목한다 — 이 이슈로 `target` 값을 추가하지 않는다.
- **불변식**: `status`는 두 boolean이 모두 true일 때만 `"approved"`, 아니면 `"rejected"`.
  소비자(generator, coordinator의 기계적 검사)는 이 불변식으로 파일 정합성을 확인한다.
- `"rejected"`면 `reasons`는 비어 있을 수 없다.

## override.json

```json
{
  "schema_version": 1,
  "issue": "<issue id>",
  "run_id": "<orchestration run id>",
  "overridden_by": "generator",
  "final_round": 2,
  "unresolved_reasons": [ {"target": "plan_coverage", "ac_id": "ac3", "reason": "<verdict-r2에서 복사>"} ]
}
```

- 2라운드에도 rejected일 때만 존재한다. evaluator의 verdict 파일은 수정하지 않는다 — 판정은
  rejected로 남고, 진행 결정만 여기 기록된다. `unresolved_reasons`는 `verdict-r2.json`의
  `reasons` 중 generator가 해소하지 못한 항목을 그대로 복사한다.
- **override의 라우팅은 무조건 진행이 아니다** — 코디네이터(`orca-workflow-task` §1)가 기계적으로
  분기하되, **라우팅 입력은 이 파일이 아니라 evaluator 소유의 `verdict-r2.json`이다**:
  `verdict-r2.json`의 `reasons[].target`에 `ac_fidelity`가 하나라도 있으면 "무엇을 만들지" 자체에
  이견이 남은 것이므로 코드 생성 없이 human escalate(`CONTRACT_ESCALATE`), `plan_coverage`만 있으면
  검증 방법 이견일 뿐이므로 진행(그 항목은 `orca-evaluate` §3 리뷰어의 집중 검토 입력이 된다).
  숫자 임계치가 아니라 target 범주가 기준이다. `unresolved_reasons`를 라우팅 입력으로 쓰지 않는
  이유: 이 파일은 generator가 쓰고, 어떤 항목을 "해소했다"고 볼지도 generator가 정한다 — 2라운드
  한도 뒤에는 그 "해소"를 검증할 evaluator 라운드가 없으므로, generator의 자기 필터를 라우팅
  기준으로 삼으면 자기평가 편향이 게이트를 그대로 통과한다
  (`docs/references/anthropic-harness-design-long-running-apps.md`의 self-evaluation 편향 — 이
  스키마의 "적대적 판정 지침"이 존재하는 이유와 같다). `unresolved_reasons`는 generator가 무엇을
  우려로 인정했는지의 **기록**으로만 남는다.

## override 후속 라운드 (proposal-r3+, issue #130)

override는 협상의 종착점이지 계약의 종착점이 아니다 — override 발동 시 generator는
`override.json`을 쓴 **직후, 같은 스텝에서** `proposal-r3.json`을 새로 쓴다(쓰기 순서 고정:
override.json 먼저 — 크래시 시 재구성이 "override 없이 r3만 있는" 비정상 상태를 만들지 않게).

- `proposal-r3.json` = `verdict-r2.json`의 `reasons` 중 generator가 해소한 항목을 반영한 **최종
  확정 계약**이다. `round: 3`, 나머지 필드는 proposal 스키마 그대로. `proposal-r2.json`/
  `override.json`은 그대로 둔다(append-only).
- **`verdict-r3.json`은 존재하지 않는 것이 정상이다** — 이 라운드는 evaluator 재검토를 구하지
  않는다(협상 라운드 한도는 2). 검증은 `orca-evaluate` §3 diff 리뷰가 최종 AC 기준으로 한다.
- **override 이후 계약 자체의 결함이 발견되면**(eval FAIL findings가 코드가 아니라 proposal 필드를
  지적) 동결된 라운드 파일을 절대 제자리 수정하지 않는다 — 다음 라운드 번호(`proposal-r4.json`, …)로
  새 파일을 쓴다. 제자리 수정은 이미 그 파일을 인용해 둔 `verdict-r*`/`override.json`의 인용
  무결성을 깨고, 같은 diff를 서로 다른 두 계약으로 측정하게 만든다(#96에서 ESCALATE로 실측).
- 이미 제자리 수정으로 손상된 경우의 교정: 손상 파일을 복구하려 들지 말고(그 시도 자체가 또 다른
  제자리 수정이다) **현재 내용**을 그대로 `proposal-r<n+1>.json`으로 복제하고 `round` 필드만 올린다.
- **`proposal-r3.json`이 없다고 항상 위반은 아니다** — override.json이 이 절 자체의 도입(commit
  79b7c3b, 2026-08-12T09:44:57+09:00) 이전에 완료된 세션은 규칙이 생기기 전에 끝난 것이므로
  `CONTRACT_SCHEMA_STALE`로 별도 처리한다(issue #160). 도입 시각 상수(`R3_REQUIRED_SINCE`)와 비교
  로직은 `orca-workflows/scripts/contract_resume.sh`와 `orca-workflow-task` SKILL.md §1 양쪽에
  정의돼 있다 — 이 문서는 그 존재만 가리키고 상수 자체를 복제하지 않는다.

## gate-flake-a&lt;k&gt;.json

```json
{
  "schema_version": 1,
  "issue": "<issue id>",
  "attempt": 1,
  "gates": [
    {
      "gate": "e2e",
      "failed_attempts": [
        {"n": 1, "log": ".gate-e2e.attempt1.log", "spec": "<실패 spec 파일명>", "first_error": "<에러 첫 줄>"}
      ],
      "passed_attempt": 2
    }
  ],
  "known_flake_list": "<대조한 목록 경로, 없으면 null>",
  "known_flake_matched": ["<목록과 일치한 spec 파일명...>"]
}
```

- generator(`orca-task-runner` §6)가 쓴다 — **task 게이트의 어떤 시도가 실패하고 이후 시도가
  통과했을 때만**. 파일 부재 = flake 재분류가 없었다는 뜻이므로, 첫 시도에 전부 통과한 attempt에는
  만들지 않는다. `<k>`는 `eval-report-a<k>.json`과 같은 구현 attempt 번호.
- 소비자는 `orca-evaluate` §3의 code-reviewer다(리뷰어 입력 ⑧) — "재실행 green"이 정말 이 diff와
  무관한 flake였는지는 generator 자신이 아니라 리뷰어가 판정한다. 코디네이터
  (`orca-workflow-task`)는 이 파일을 읽지 않고 존재 여부도 중계하지 않는다 — evaluator가
  결정론적 경로로 직접 확인한다.
- `gate`는 `"e2e"` 또는 `"pgtap"`. `first_error`는 attempt 로그에서 추출한 에러 첫 줄 —
  로그 전문을 넣지 않는다(로그 파일 자체는 worktree에 남아 있고 `log` 필드가 가리킨다).

## eval-report-a&lt;k&gt;.json

구현이 끝난 뒤 `orca-evaluate` §4가 합성한 판정의 기계적 기록이다. `<k>`는 evaluate **attempt**
번호(1부터 — attempt 1이 최초 평가, FAIL 재-dispatch 후의 재평가가 attempt 2, 3). 협상 라운드
`r<n>`과는 별개 카운터다.

```json
{
  "schema_version": 1,
  "issue": "<issue id>",
  "run_id": "<orchestration run id>",
  "attempt": 1,
  "verdict": "FAIL",
  "code_review_ran": true,
  "findings": [ {"severity": "critical", "finding": "<결함 서술>", "evidence": "<file:line 또는 e2e 관찰>", "fix_direction": "<수정 방향>"} ]
}
```

- `verdict`: `"PASS"` | `"FAIL"` | `"ESCALATE"` — `orca-workflow-task`에 반환하는 값과 반드시 일치한다.
- `findings[].severity`: `"critical"` | `"important"` | `"minor"`.
- `code_review_ran`: 이 attempt에서 §3 code review가 실제 실행됐는가. agent e2e 실패 확정으로
  fail-fast 생략된 attempt는 `false`.
- **불변식**: `"FAIL"`이면 `findings`는 비어 있을 수 없고, `"PASS"`면 `critical`/`important`
  finding이 없어야 하며 `code_review_ran`은 `true`여야 한다(리뷰 생략 후 PASS는 위반이다).
- **이 파일이 FAIL feedback의 정본이다.** 경로가 `CONTRACT_DIR`와 attempt 번호로 결정론적이므로
  코디네이터는 attempt 번호와 확정 라운드 번호만 중계하고 본문을 요약·중계하지 않는다 — 재-dispatch된 generator가
  직접 읽는다(협상 라운드 2+의 verdict 전달과 같은 원칙).

## 크래시-재개 (crash-resume)

이 디렉토리의 파일명 번호(`r<n>`, `a<k>`)가 round/attempt 진행 상태의 **정본**이다 — 코디네이터
세션의 대화 컨텍스트가 아니다(issue #156). 코디네이터 세션이 죽고 같은 issue로 재호출되면,
`orca-workflows/scripts/contract_resume.sh`의 `contract_resume_state <CONTRACT_DIR>`가 파일 스캔만으로
재개 지점을 재구성한다(소비자: `orca-workflow-task` §0의 재개 분기; 동작은
`tests/test_contract_resume.py`가 고정한다).

- 모호 상태(파일은 있는데 JSON 무효, 또는 `status`/`verdict` 값이 스키마 밖 — 쓰다 죽은 것)는 없는
  것으로 취급해 그 파일의 생산 스텝을 fail-closed로 다시 태운다. **예외**: 유효한 `override.json`이
  있을 때 verdict 없는 `proposal-r3.json`(이상)은 모호가 아니라 정상이다 — override 후속 라운드는
  verdict를 갖지 않는다(위 절). 반대로 override가 있는데 `proposal-r3.json`이 없으면 override 스텝이
  쓰다 죽은 것이므로 그 스텝을 다시 태운다. 이때 같은 번호 파일을 덮어쓰는
  것은 append-only 위반이 아니다 — append-only는 라운드 간(r1을 r2에서 수정 금지) 규칙이다.
- override 라우팅 게이트(위 override 절)는 재개 경로에서도 동일하게 적용된다 —
  `contract_resume.sh`가 `orca-workflow-task` §1의 인라인 분기를 미러링한다. 한쪽을 바꾸면 함께
  바꾼다.
- `gate-flake-a<k>.json`은 재개 라우팅에 영향을 주지 않는다(평가 입력용 정보 파일).

## 재시도 입력 격리 (evaluate attempt 2+)

attempt 2+의 리뷰 입력에 추가되는 것은 **자신의 직전 `eval-report-a<k-1>.json`의 findings**뿐이다
(지적 항목이 실제 수정됐는지 확인용 — 협상 라운드 2가 자신의 `verdict-r1.json`을 입력으로 받는
것과 동일). generator의 수정 요약·서술형 해명은 입력에 넣지 않는다 — 판정을 바꾸는 근거는 diff의
사실 변화뿐이다("라운드 2 입력 격리"와 같은 근거, arXiv:2509.16533).

## 확정 AC의 정본

이후 모든 단계(`orca-task-runner` §2 subtask 분해, `orca-evaluate` §3 diff review)가 참조하는 확정
acceptance criteria는 **최종 라운드(가장 큰 n) proposal의 `draft_acceptance_criteria`**다(승인이든
override든 — override 경로에서는 `proposal-r3.json` 이상, 위 override 후속 라운드 절).
issue 본문의 사전 AC 섹션은 전제가 아니다 — 있으면 issue 원문의 일부로서 초안의 입력이 될 뿐이다.

## 적대적 판정 지침

evaluator가 스폰하는 contract-review 세션의 spec에 다음을 그대로 포함한다(OpenAI Codex
adversarial-review 프롬프트 차용 + grounding 제약):

- "이 검토의 목표는 제안의 확신을 깨는 것이다 — 검증해주는 것이 아니다."
- "선의, 부분적 커버, '후속에서 보완 예정'에 점수를 주지 않는다."
- "happy-path만 커버하는 검증 계획은 그 자체로 결함으로 보고한다."
- "결함을 지어내지 않는다 — 모든 reason은 원본 issue 또는 proposal의 구체 필드를 가리켜야 한다."
- "무동작(no-op) 구현을 상상해 이 `verification_plan` 항목이 통과하는지 자문한다 — 통과하면 그
  자체로 결함이다."

## 라운드 2 입력 격리 (sycophancy 방어)

evaluator의 라운드 2 입력은 정확히 셋: **원본 issue 전문, `proposal-r2.json`, 자신의
`verdict-r1.json`.** generator의 서술형 반박·해명은 입력에 존재하지 않는다 — proposal 스키마에
그런 필드가 없어서 구조적으로 배제된다. 판정 지침에 다음을 명시한다:

> "직전 판정을 뒤집을 때는 proposal의 사실 변화(필드 수준 차이)에 근거해야 한다. 단순 재제출·표현
> 변경은 뒤집을 근거가 아니다."

근거: 자율 코딩 에이전트를 상대로 한 LLM 판정자는 반복 반박 압박에 판정의 88%까지 뒤집었고, 행위자
서술 제거 + 명시적 지침으로 ~94%가 복구됐다(arXiv:2509.16533). 같은 이유로 Anthropic Auto Mode의
판정 classifier는 행위자의 reasoning 텍스트를 입력에서 제거한다.
