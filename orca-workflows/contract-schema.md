# Contract Negotiation Schema

Shared reference for `orca-workflow`(§2a relay, §2d FAIL relay), `orca-task-runner`(§1, §7),
`orca-evaluate`(§1, §4). Defines the on-disk artifacts the contract lifecycle exchanges — 협상
라운드(proposal/verdict/override)와 이행 평가(eval-report) 둘 다. The coordinator relays the
directory path and round/attempt numbers only; generator and evaluator read/write these files
directly.

## Directory

```bash
CONTRACT_DIR="$HOME/.local/state/orca-workflows/contracts/<project-slug>/issue-<issue>"
install -d -m 700 "$CONTRACT_DIR"
```

- `<project-slug>`: 대상 repo의 디렉토리명(예: `medicount`). 코디네이터(`orca-workflow` §0)가 1회
  계산해 두 spec_text에 절대경로로 넣는다.
- 워크트리 밖(전역)인 이유: worktree는 merge 후 삭제되지만 retro(`orca-retro`)는 epic close 후에
  이 기록을 읽는다. 실수 커밋 위험도 없다. per-project 폴더는 repo가 다른 같은 issue 번호끼리의
  충돌을 막는다.
- 파일은 라운드별 append-only — r1 파일을 r2에서 수정하지 않는다. 파일은 `chmod 600`.
- **launch posture 전제**: 이 경로는 워크스페이스 밖이므로, contract 파일을 쓰는 역할
  (task-runner/evaluator)을 codex로 띄울 때 `-s workspace-write` 샌드박스로는 쓸 수 없다 —
  워크스페이스 밖 쓰기가 가능한 posture여야 한다. 현행 codex posture
  (`--dangerously-bypass-approvals-and-sandbox`, `models/codex.md`)가 이를 충족한다.

## Files

| file | writer | when |
|---|---|---|
| `proposal-r<n>.json` | orca-task-runner (generator) | 라운드 n 제안 |
| `verdict-r<n>.json` | orca-evaluate (evaluator) | 라운드 n 판정 |
| `override.json` | orca-task-runner | 2라운드에도 rejected일 때 결정권 행사 기록 |
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
  "verification_plan": [ {"covers": ["ac1"], "method": "<구체 파일/함수/테스트>"} ],
  "destructive_operations": [ "<의도된 destructive op 설명>" ],
  "existing_tests_affected": [ {"location": "<file:line>", "reason": "<이 변경으로 red가 되는 이유>"} ]
}
```

- **모든 필드 필수.** `destructive_operations`/`existing_tests_affected`의 빈 배열 `[]`은
  "명시적으로 없음"이다 — 필드가 아예 없으면 스키마 위반이므로 "언급 안 함" 상태는 존재할 수
  없다(종전 prose 제안서의 "공란 vs 없음" 구분을 스키마 필수성이 대체한다).
- **설득 서술 필드는 의도적으로 없다.** "왜 이 제안이 충분한가"류 정당화는 어떤 필드에도 넣지
  않는다(`scope.summary` 포함 — 사실 서술만). 근거는 아래 "라운드 2 입력 격리".
- `verification_plan[].covers`는 `draft_acceptance_criteria`의 id만 참조한다. 어떤 plan 항목도
  커버하지 않는 ac id가 남으면 evaluator가 기계적으로 잡을 수 있다.

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
  아니면 `null`.
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
- **override의 라우팅은 무조건 진행이 아니다** — 코디네이터(`orca-workflow` §2a)가 이 파일의
  `unresolved_reasons[].target`만 기계적으로 확인해 분기한다: `ac_fidelity`가 하나라도 남아 있으면
  "무엇을 만들지" 자체에 이견이 남은 것이므로 코드 생성 없이 human escalate(`CONTRACT_ESCALATE`),
  `plan_coverage`만 남았으면 검증 방법 이견일 뿐이므로 진행(그 항목은 `orca-evaluate` §3 리뷰어의
  집중 검토 입력이 된다). 숫자 임계치가 아니라 target 범주가 기준이다.

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

- `verdict`: `"PASS"` | `"FAIL"` | `"ESCALATE"` — `orca-workflow`에 반환하는 값과 반드시 일치한다.
- `findings[].severity`: `"critical"` | `"important"` | `"minor"`.
- `code_review_ran`: 이 attempt에서 §3 code review가 실제 실행됐는가. agent e2e 실패 확정으로
  fail-fast 생략된 attempt는 `false`.
- **불변식**: `"FAIL"`이면 `findings`는 비어 있을 수 없고, `"PASS"`면 `critical`/`important`
  finding이 없어야 하며 `code_review_ran`은 `true`여야 한다(리뷰 생략 후 PASS는 위반이다).
- **이 파일이 FAIL feedback의 정본이다.** 경로가 `CONTRACT_DIR`와 attempt 번호로 결정론적이므로
  코디네이터는 attempt 번호만 중계하고 본문을 요약·중계하지 않는다 — 재-dispatch된 generator가
  직접 읽는다(협상 라운드 2+의 verdict 전달과 같은 원칙).

## 재시도 입력 격리 (evaluate attempt 2+)

attempt 2+의 리뷰 입력에 추가되는 것은 **자신의 직전 `eval-report-a<k-1>.json`의 findings**뿐이다
(지적 항목이 실제 수정됐는지 확인용 — 협상 라운드 2가 자신의 `verdict-r1.json`을 입력으로 받는
것과 동일). generator의 수정 요약·서술형 해명은 입력에 넣지 않는다 — 판정을 바꾸는 근거는 diff의
사실 변화뿐이다("라운드 2 입력 격리"와 같은 근거, arXiv:2509.16533).

## 확정 AC의 정본

이후 모든 단계(`orca-task-runner` §2 subtask 분해, `orca-evaluate` §3 diff review)가 참조하는 확정
acceptance criteria는 **최종 라운드 proposal의 `draft_acceptance_criteria`**다(승인이든 override든).
issue 본문의 사전 AC 섹션은 전제가 아니다 — 있으면 issue 원문의 일부로서 초안의 입력이 될 뿐이다.

## 적대적 판정 지침

evaluator가 스폰하는 contract-review 세션의 spec에 다음을 그대로 포함한다(OpenAI Codex
adversarial-review 프롬프트 차용 + grounding 제약):

- "이 검토의 목표는 제안의 확신을 깨는 것이다 — 검증해주는 것이 아니다."
- "선의, 부분적 커버, '후속에서 보완 예정'에 점수를 주지 않는다."
- "happy-path만 커버하는 검증 계획은 그 자체로 결함으로 보고한다."
- "결함을 지어내지 않는다 — 모든 reason은 원본 issue 또는 proposal의 구체 필드를 가리켜야 한다."

## 라운드 2 입력 격리 (sycophancy 방어)

evaluator의 라운드 2 입력은 정확히 셋: **원본 issue 전문, `proposal-r2.json`, 자신의
`verdict-r1.json`.** generator의 서술형 반박·해명은 입력에 존재하지 않는다 — proposal 스키마에
그런 필드가 없어서 구조적으로 배제된다. 판정 지침에 다음을 명시한다:

> "직전 판정을 뒤집을 때는 proposal의 사실 변화(필드 수준 차이)에 근거해야 한다. 단순 재제출·표현
> 변경은 뒤집을 근거가 아니다."

근거: 자율 코딩 에이전트를 상대로 한 LLM 판정자는 반복 반박 압박에 판정의 88%까지 뒤집었고, 행위자
서술 제거 + 명시적 지침으로 ~94%가 복구됐다(arXiv:2509.16533). 같은 이유로 Anthropic Auto Mode의
판정 classifier는 행위자의 reasoning 텍스트를 입력에서 제거한다.
