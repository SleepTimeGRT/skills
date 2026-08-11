# orca-workflow-task/orca-task-runner: FAIL 재시도 dispatch에 확정 계약 파일 포인터 추가 — Design

**Date**: 2026-08-11
**Status**: Approved (brainstorming phase) — pending implementation plan
**Related**: GitHub issue #141 (SleepTimeGRT/skills)

## Context

이슈 #141은 FAIL 재시도로 재-dispatch될 때, 재시도 세션(generator)에 확정 계약
(`proposal-r<확정라운드>.json`)이 다시 전달되지 않는다고 보고한다. 두 스킬 모두
"generator가 `eval-report-a<attempt>.json`을 직접 읽는다"만 규정하고, 확정
acceptance criteria 전체를 다시 읽으라는 지시는 어디에도 없다:

- `orca-workflow-task/SKILL.md` §2 "Generate"(현재 L252): dispatch를 실제로
  구성하는 지점.
- `orca-task-runner/SKILL.md` §7 "완료" 안의 "Evaluate-FAIL 재시도로 재호출된
  경우" 문단(현재 L252): 그 dispatch를 받아 소비하는 지점.

실측(studio-hevv/selah-android#10 attempt3)에서 dispatch spec 원문이 findings를
번호 매겨 prose로 요약해 전달했고, 이 과정에서 finding 하나(`A2-F4`)의
`fix_direction`(두 가지 수정 선택지)이 통째로 손실됐다. `proposal-r3.json`
언급은 원문에 단 한 번도 없었다. 결과: 재시도 세션이 minor finding을 고치다가
확정 계약(`ac12`/`ac15`/`ac18`이 못박은 공개 API 시그니처)을 삭제해 evaluate가
`A3-F2`(계약 위반 회귀)로 재포착했다.

**근본 원인 진단**: `orca-workflow-task` §1(협상 라운드 relay)에는 `spec_text="<...>"`
형태의 강제 템플릿이 라운드마다 있는데(L121, L185, L229), §2 "Generate"에는
이런 템플릿이 전혀 없고 순수 prose 지시("spec에 직전 attempt 번호를 넣는다")뿐이다.
"feedback 본문을 중계하지 않는다"는 원칙은 문서에 있지만 이를 강제하는 템플릿이
없어, 실제 실행 시 에이전트가 자유 재구성하다 prose 요약으로 드리프트했다.
`contract-schema.md`의 "확정 AC의 정본" 절은 이미 "최종 라운드 proposal의
`draft_acceptance_criteria`가 확정 AC"라고 규정하지만, 이 원칙이 FAIL 재시도
dispatch 문구에 실제로 반영돼 있지 않다.

## 결정

### 1. `orca-workflow-task/SKILL.md` §2 "Generate" — dispatch 템플릿 신설

현재 문장(§2, 현재 L252):

> §4의 FAIL 재시도로 돌아온 호출이면 spec에 직전 attempt 번호를 넣는다 —
> generator가 `CONTRACT_DIR`의 `eval-report-a<attempt>.json`을 직접
> 읽는다(이 스킬은 feedback 본문을 중계하지 않는다).

다음으로 교체(§1의 기존 `spec_text=` 라인들과 같은 스타일로 템플릿화):

> §4의 FAIL 재시도로 돌아온 호출이면 spec을 아래 템플릿대로 구성한다 —
> findings를 prose로 요약하지 않고 파일 경로만 넘긴다:
>
> ```
> spec_text="<... + 직전 attempt 번호 + \"CONTRACT_DIR의 eval-report-a<attempt>.json과
> proposal-r<확정라운드>.json을 이 순서로 전부 읽어라 — findings를 요약해 넘기지
> 않는다\" + orphan-폴백 계약(§0) 전문>"
> ```
>
> `<확정라운드>`는 §1에서 라운드 루프를 직접 돈 이 세션이 이미 로그로 남긴 값
> (`CONTRACT_APPROVED`/`CONTRACT_FINALIZED_BY_GENERATOR` 이벤트의 `round`)을
> 그대로 리터럴 치환한다 — 추가 파일 읽기·디렉토리 listing 없음. generator가
> 두 파일을 직접 읽는다(이 스킬은 feedback 본문도 확정 AC 본문도 중계하지 않는다).

### 2. `orca-task-runner/SKILL.md` §7 — 수신 측 문단에 두 번째 파일 추가

현재 문장(§7, 현재 L252) 중:

> `CONTRACT_DIR`의 `eval-report-a<attempt>.json`에서 `findings`를 직접
> 읽고(`orca-workflow-task`는 본문을 중계하지 않는다 —
> `~/.agents/orca-workflows/contract-schema.md`)

다음으로 교체:

> `CONTRACT_DIR`의 `eval-report-a<attempt>.json`과 `proposal-r<확정라운드>.json`을
> 이 순서로 직접 읽고(`orca-workflow-task`는 findings 본문도 확정 AC 본문도
> 중계하지 않는다 — `~/.agents/orca-workflows/contract-schema.md`의 "확정 AC의
> 정본")

문단의 나머지(그 수정에 필요한 만큼만 §2~§5를 다시 태운 뒤 §6 재통과 → §7 반환
반복, evaluator에게 서술형 해명을 보내지 않는다)는 그대로 둔다 — ①②로 정보
전달 경로만 고치는 것이지 §7의 반환/재시도 구조 자체는 바꾸지 않는다.

## 검토 후 기각한 대안

- **③ "diff를 확정 AC 전체와 재대조하는 명시적 단계"를 `orca-task-runner` §7에
  추가(이슈 원문의 세 번째 해소 방향)**: `orca-task-runner` SKILL.md 자신이
  이미 "생성만 한다 — 평가는 이 스킬의 책임이 아니다"라고 명시한다. ③은 이
  generator/evaluator 역할 분리 원칙과 충돌하는 평가성 단계이고, §6의 기존
  게이트(typecheck/lint/e2e)와 달리 스크립트로 강제되지 않는 prompt 수준
  지시라 실제 준수 여부를 검증할 방법이 없다. 이 재대조는 이미
  `orca-evaluate` §3의 diff review가 맡고 있고(`contract-schema.md` "확정
  AC의 정본"), 실측 사례에서도 결국 evaluate가 `A3-F2`로 이 위반을 잡아냈다
  — 라운드 하나를 더 쓴 것뿐이다. ①②로 generator가 확정 AC를 애초에 보고
  작업하게 만들면 이 재발 자체가 줄 것으로 판단, 강제력 없는 중복 단계를
  추가하지 않는다.
- **generator가 `CONTRACT_DIR`를 직접 listing해 최신 `proposal-r*.json`을
  스스로 찾게 하는 방식**: 코디네이터(`orca-workflow-task`)가 §1 라운드
  루프를 직접 돌며 승인/override된 라운드 번호를 이미 알고 있으므로, 이
  값을 spec에 리터럴로 박아넣는 쪽이 더 결정론적이고 추가 메커니즘(파일
  glob·정렬·최신값 판별 로직을 generator 쪽에 새로 규정하는 것)이 필요
  없다. 코디네이터가 "파일 본문은 읽지 않되 라운드 번호는 중계한다"는 기존
  원칙(§1)과도 일치한다.

## 테스트 계획

skill 문서 수정이라 실행 가능한 테스트는 없다 — 검증은 문서 self-review로
대체한다:
- 두 파일의 수정된 문단을 나란히 놓고 A가 보내는 두 파일 포인터와 B가 읽는다고
  말하는 두 파일이 이름·순서까지 정확히 일치하는지 확인.
- `contract-schema.md`의 파일명 컨벤션(`proposal-r<n>.json`,
  `eval-report-a<k>.json`)과 새 문구의 표기가 정확히 일치하는지 확인.
- 기존 §1의 `spec_text=` 템플릿들과 문체·placeholder 표기 스타일이 일관되는지
  확인.
- "이 스킬은 본문을 중계하지 않는다"는 기존 원칙 문구와 새로 추가된 "findings를
  요약해 넘기지 않는다" 문구가 모순 없이 같은 방향을 가리키는지 확인.

## 범위 경계

- `skills/orca-workflow-task/SKILL.md`, `skills/orca-task-runner/SKILL.md`
  두 파일만 수정. `contract-schema.md`(이미 "확정 AC의 정본" 원칙을 갖고
  있음)와 `orca-evaluate`는 건드리지 않는다.
- 이 두 파일은 `skills/orca-set.version`으로 묶인 6종 세트 멤버이므로, 커밋
  후 `scripts/deploy-skills.sh`로 세트 전체를 재배포해야 실제 배포에 반영된다
  — 구현 단계에서 처리(설계 범위 밖).
- ③(diff-vs-AC 재대조 단계)은 이번 작업에 포함하지 않는다(위 "검토 후 기각한
  대안" 참고) — 필요해지면 별도 이슈로 분리.
