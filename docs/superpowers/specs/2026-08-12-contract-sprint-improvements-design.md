# Contract Sprint 개선 — Design

## 배경

`orca-task-runner`(generator)와 `orca-evaluate`(evaluator)가 `orca-workflows/contract-schema.md`
스키마로 주고받는 계약 협상("contract sprint": proposal-r*/verdict-r*/override.json)의 실측 로그를
5개 저장소·49개 issue 표본으로 조사한 결과, 4개의 근거 있는 결함 패턴이 확인됐다. 이 설계는 그 4개를
해소한다.

원출처 확인: `docs/references/anthropic-harness-design-long-running-apps.md`가 이 generator/evaluator
계약 협상 패턴의 원본이다("Before each sprint, the generator and evaluator negotiated a sprint
contract... The two iterated until they agreed"). 우리 구현은 이 원본에서 라운드 상한(2)+override를
추가해 이탈했고, 그 이탈 지점이 아래 패턴 3의 근거다.

## 문제 정의 (근거)

1. **무동작(vacuous-pass) 검증**: `verification_plan` 항목이 구조적 존재 확인만 해 무동작 구현도
   통과시키는 사례가 3개 이상 저장소·언어에서 반복됐다 — `selah_android/issue-12`(ac6: 스와이프
   제스처를 `SwipeToDismissBox(` 존재만 확인, undo 왕복 실패가 계약 통과 후 code-review 3라운드째
   실기기 재현), `toss-samhaengsi/issue-630`(ac2: 빈 CSS가 마커 4개 검사 전부 통과).
   `contract-schema.md`의 "happy-path만 커버 금지" 규칙은 이 패턴을 명시적으로 막지 않는다 — 여러
   경로를 커버해도 전부 구조적 확인이면 여전히 무동작을 통과시킨다.
2. **AC 초안 품질**: round1 반려율 88%(43/49), 그중 93%가 ac_fidelity·plan_coverage 동시 실패.
   Spec-Driven Development 커뮤니티 관행(binary/independent/ordered-by-importance)을
   `draft_acceptance_criteria` 스키마가 요구하지 않는다.
3. **라운드 상한의 구조적 비용**: `contract-schema.md`의 override 정책(plan_coverage-only 잔여 시
   무조건 진행)은 스키마 명문 규칙이지 즉흥이 아니지만, 실비용이 실측된다 — `issue-12`(override 시
   unresolved_count=0으로 "완전 해소" 처리했지만 verdict-r1이 경고한 결함이 code-review 3라운드
   뒤 재현), `selah_android/issue-3`(실제 버그성 지적 5건 override로 밀어붙임). `issue-11`은 세션
   3회에 걸쳐 같은 결함 클래스가 한 링크씩 위로 이동하며 반복 반려됨(비수렴/goalpost migration).
4. **evaluator 오판 감지 렌즈 부재**: `orca-retro`는 5개 렌즈로 invocation당 최대 3건 결함 이슈를
   파일링하지만, "evaluator가 승인/override한 것이 다운스트림에서 실제 결함으로 확인됨"을 별도
   집계하지 않는다.

## 비목표

- **generator/evaluator 협상을 superpowers:brainstorming식 대화형 QA로 교체하지 않는다** —
  `contract-schema.md`의 "라운드 2 입력 격리(sycophancy 방어)" 절이 막는 바로 그 패턴(반복 대화
  압박에 LLM 판정자가 최대 88%까지 뒤집힘, arXiv:2509.16533)을 재도입하게 되므로 기각됐다(이전
  대화에서 결정).
- **무제한 라운드 반복 도입 안 함** — anthropic 원본은 무제한이지만 비용 트레이드오프(원본 사례도
  4~6시간/$124~200)가 크므로, 조건부 1라운드 연장까지만 한다.
- **round cap 로직을 매개변수화(일반화)하지 않는다** — 기존 라운드1→2 fail-closed 게이트를 그대로
  두고 라운드2→3용 병렬 블록만 추가한다(아래 Component 3).

## 설계

### Component 1 — `fails_before_fix` 무동작-통과 금지 (스키마 필드 변경 없음)

`contract-schema.md`의 `proposal-r<n>.json` 절, `fails_before_fix` 필드 설명 뒤에 추가:

> 이 항목이 stub/no-op(빈 구현, 아무 것도 하지 않는 구현)에서도 통과하는지 스스로 점검한다.
> 통과한다면 그 검증 방법 자체가 스키마 위반이다 — 구조적 존재 확인(예: 특정 API 호출 문자열이
> 소스에 있는지)만으로는 무동작 구현을 배제하지 못하는 경우가 이에 해당한다.

같은 문서 "적대적 판정 지침"에 5번째 불릿 추가:

> "무동작(no-op) 구현을 상상해 이 verification_plan 항목이 통과하는지 자문한다 — 통과하면 그
> 자체로 결함이다."

`orca-evaluate/SKILL.md` §1 dispatch spec 문자열("verification_plan[]의 각 항목이
fails_before_fix를 비우지 않았고 fix 전후를 실제로 구분함을 확인하라는 지시")에 "무동작 구현
배제 여부도 확인하라"를 추가.

### Component 2 — `draft_acceptance_criteria`에 SDD 3원칙 (스키마 필드 변경 없음)

`contract-schema.md`의 `draft_acceptance_criteria` 설명에 추가:

> 각 AC는 (a) binary(판정 가능, "좋다/나쁘다" 같은 주관적 기준 금지) (b) independent(한 항목은
> 정확히 한 가지만 검증 — 여러 조건을 접속사로 묶지 않음) (c) 배열에 쓰는 순서가 곧 중요도
> 순서(ordered by importance)여야 한다. 새 필드를 추가하지 않는다 — 배열 순서 자체가 우선순위다.

evaluator의 ac_fidelity 판정 기준(§1 dispatch spec)에 이 3원칙 위반을 반려 사유로 추가.

### Component 3 — round cap 조건부 연장 (plan_coverage-only)

**새 규칙**: `verdict-r2.json`이 `rejected`이고 `reasons[].target`이 전부 `"plan_coverage"`(즉
`"ac_fidelity"`가 하나도 없음)면, override 대신 `proposal-r3.json`(정식 협상 라운드, verdict 있음)을
한 번 더 허용한다.

- `verdict-r3.json` → `approved`: 확정 AC = `proposal-r3`(정본 규칙 "최종 라운드(가장 큰 n)"는
  이미 라운드 번호에 열려 있어 변경 불필요), 정상 종료.
- `verdict-r3.json` → `rejected`이고 `reasons[].target`에 `"ac_fidelity"`가 하나라도 있음:
  지금과 동일하게 `CONTRACT_ESCALATE`(단 `round=3`으로 기록 — 지금은 `round=2`).
- `verdict-r3.json` → `rejected`이고 여전히 `plan_coverage`-only: 지금의 override 절차를 그대로
  한 라운드 밀어서 수행 — `override.json`(`final_round=3`) 작성 직후 같은 스텝에서
  `proposal-r4.json`(신규 최종 확정 계약, verdict 없음)을 작성한다.

**구현 원칙**: 기존 라운드1→2 fail-closed 게이트(코드·테스트 모두 이미 검증됨)는 손대지 않는다.
`orca-workflow-task/SKILL.md` §1과 `contract_resume.sh` 둘 다에 라운드2→3용 **병렬 블록**을
구조적으로 복제해 추가한다(참조 대상만 `verdict-r2.json`→`verdict-r3.json`, `round=3`→`round=4`로
치환) — 매개변수화(라운드 번호를 변수로 일반화)는 하지 않는다. 코드 중복은 생기지만 기존 동작을
회귀시킬 위험이 그만큼 줄어든다.

**버전 게이트 (신규, `issue #160`의 `R3_REQUIRED_SINCE`와 동일 패턴)**: 이 기능 도입 이전에는
`proposal-r3.json`이 항상 "verdict 없는 최종 계약"(override-at-round-2의 산출물)이었다. 이후에는
`proposal-r3.json`이 "verdict-r3을 기다리는 정식 협상 라운드"라는 **반대 의미**가 된다.
`contract_resume.sh`에 `ROUND3_NEGOTIATION_SINCE` 상수(이 기능을 도입하는 커밋의 타임스탬프)를
추가해, `override.json`의 mtime이 그 이전이면 지금처럼 "round=2 종결"로, 이후면 새 "round=3 협상"
경로로 분기한다(`R3_REQUIRED_SINCE`가 쓰는 `touch -t` mtime 비교 기법을 그대로 재사용).

**영향 파일**:
- `orca-workflows/contract-schema.md` — override 절, "override 후속 라운드" 절에 조건부 연장
  규칙과 `ROUND3_NEGOTIATION_SINCE` 설명 추가.
- `skills/orca-task-runner/SKILL.md` §1 — "최대 2 라운드" 옆에 조건부 3라운드 규칙 추가.
- `skills/orca-evaluate/SKILL.md` §1 — "최대 2라운드까지 왕복" 문구 동일 갱신.
- `skills/orca-workflow-task/SKILL.md` §1 — 라운드 한도 도달 시점 기계적 분기에 라운드2→3 확장
  블록 추가(verdict-r2가 plan_coverage-only면 override 대신 round-3 릴레이로 라우팅).
- `orca-workflows/scripts/contract_resume.sh` — `ROUND3_NEGOTIATION_SINCE` 상수 + round=3용 병렬
  분기 블록.
- `tests/test_contract_resume.py` — 신규 케이스(아래 테스트 절).

### Component 4 — `orca-retro` 6번째 렌즈: contract-verdict 오판 대조

`skills/orca-retro/SKILL.md`에 6번째 defect 렌즈 추가:

> 이 invocation이 다룬 issue들 중 `verdict-r*.json`이 `approved` 또는 `plan_coverage`-only
> `override`로 종결된 것을 골라, 같은 issue의 최종 `eval-report-a*.json`의 FAIL findings 또는
> human escalation 기록과 대조한다. 다운스트림에서 같은 결함(같은 `ac_id` 또는 같은 지적 내용)이
> 실제로 재현되면, evidence-backed defect issue로 파일링한다(기존 "invocation당 최대 3건" 한도,
> 기존 중복 방지 — open issue에 recurrence 코멘트 — 규칙 그대로 적용).

영향 파일: `skills/orca-retro/SKILL.md`만.

## 데이터 흐름 (Component 3 전/후)

```
[전]                              [후]
r1 proposal → r1 verdict          r1 proposal → r1 verdict
  rejected(ac_fidelity)             rejected(ac_fidelity) → ESCALATE(round=1, 동일)
  rejected(plan_coverage-only)      rejected(plan_coverage-only)
    ↓                                 ↓
r2 proposal → r2 verdict          r2 proposal → r2 verdict
  approved → 종료                    approved → 종료(동일)
  rejected(ac_fidelity)              rejected(ac_fidelity) → ESCALATE(round=2, 동일)
  rejected(plan_coverage-only)       rejected(plan_coverage-only)
    ↓ override                         ↓ (신규) 연장
  override.json(final_round=2)      r3 proposal → r3 verdict
  + proposal-r3(최종, verdict 없음)     approved → 종료(확정 AC=r3)
                                       rejected(ac_fidelity) → ESCALATE(round=3)
                                       rejected(plan_coverage-only)
                                         ↓ override
                                       override.json(final_round=3)
                                       + proposal-r4(최종, verdict 없음)
```

## 에러 처리

- `contract_resume.sh`의 라운드2→3 신규 블록도 기존과 같은 fail-closed 원칙을 따른다: 라운드
  한도(신규 기준 3) 도달인데 `override.json`이 없으면 `CONTRACT_ESCALATE`(기록 계약 위반),
  override는 있는데 최종 proposal이 없으면 "쓰다 죽음"으로 재태움 — 기존 라운드1→2 블록의 동일
  분기를 그대로 복제한다.
- `ROUND3_NEGOTIATION_SINCE` 이전 세션의 `override.json`(round=2 종결)은 새 로직의 영향을 받지
  않는다 — 기존 경로 그대로 처리된다.

## 테스트 계획

- Component 1·2·4는 prose/지침 변경 — 이 레포는 prose-pinning 테스트를 의도적으로 두지 않는다
  (`AGENTS.md`: "SKILL.md 문면을 고정하면 의도적 문서 수정마다 거짓 실패가 난다"). 효과는 다음
  실 issue 사이클에서 Component 4의 신규 렌즈로 관찰한다.
- Component 3은 `tests/test_contract_resume.py`에 케이스 추가 후 `python3 -m pytest tests/ -q`로
  검증:
  1. 라운드2 `verdict-r2` rejected, `plan_coverage`-only → `contract_resume_state`가 라운드3
     협상으로 라우팅(override 아님).
  2. 라운드3 `verdict-r3` rejected, 여전히 `plan_coverage`-only → override(`final_round=3`) +
     `proposal-r4` 상태로 라우팅.
  3. 라운드3 `verdict-r3` rejected, `ac_fidelity` 포함 → `CONTRACT_ESCALATE`(round=3).
  4. `override.json` mtime이 `ROUND3_NEGOTIATION_SINCE` 이전 → 기존 round=2 종결 경로 유지(회귀
     확인).
  5. `override.json` mtime이 `ROUND3_NEGOTIATION_SINCE` 이후, `proposal-r3` verdict 없음 →
     "쓰다 죽음"으로 재태움(기존 `R3_REQUIRED_SINCE` 대칭 케이스).

## 배포

`orca-evaluate`/`orca-retro`/`orca-task-runner`/`orca-workflow-task`는 `skills/orca-set.version`
(현재 `v1.1.18`)으로 묶인 세트 — 넷 중 하나라도 건드리면 세트 전체를 같은 새 버전으로
`scripts/deploy-skills.sh`를 통해 배포해야 한다(더러운 멤버가 하나라도 있으면 세트 전체 배포가
거부됨). `contract-schema.md`/`contract_resume.sh`/`tests/`는 `orca-workflows/` 심볼릭 링크
경로라 별도 배포 스텝 없이 main 병합 즉시 반영된다(`AGENTS.md` issue #22 결정).
