# Contract Negotiation Schema

Shared reference for `orca-workflow`(§2a relay), `orca-task-runner`(§1), `orca-evaluate`(§1).
Defines the on-disk artifacts the contract round exchanges. The coordinator relays the directory
path and round number only; generator and evaluator read/write these files directly.

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
  워크스페이스 밖 쓰기가 가능한 posture여야 한다.

## Files

| file | writer | when |
|---|---|---|
| `proposal-r<n>.json` | orca-task-runner (generator) | 라운드 n 제안 |
| `verdict-r<n>.json` | orca-evaluate (evaluator) | 라운드 n 판정 |
| `override.json` | orca-task-runner | 2라운드에도 rejected일 때 결정권 행사 기록 |

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
