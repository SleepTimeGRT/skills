# orca-evaluate: 게이트-안전 신호 코드화 설계

이슈: 직접 이슈 없음(세션 내 조사에서 발견). 관련: [#152](https://github.com/SleepTimeGRT/skills/issues/152), [#153](https://github.com/SleepTimeGRT/skills/issues/153), [#154](https://github.com/SleepTimeGRT/skills/issues/154)

## 문제

`skills/orca-evaluate/scripts/select_reviewer.py`는 diff의 파일 수·라인 수(`git diff --shortstat`)와
`--high-risk-signal` 불리언 하나로만 리뷰어의 모델·effort tier를 정한다. 이 불리언의 유일한 소스는
`orca-evaluate/SKILL.md` §3이 계산하는 `migration_files_present`다. diff의 실제 위험도(무엇을 건드리는가)는
tier 선택에 전혀 반영되지 않는다.

`docs/references/anthropic-building-skills-for-claude.pdf`("The Complete Guide to Building Skills for
Claude", 이하 PDF) 기준으로 이 레포 11개 스킬을 감사한 결과, 이 문제의 실제 근거는 PDF Ch5
"Instructions not followed" 절(p26)이 명시하는 패턴과 정확히 일치한다:

> "For critical validations, consider bundling a script that performs the checks programmatically rather
> than relying on language instructions. Code is deterministic; language interpretation isn't."

`orca-evaluate/SKILL.md` §3 ⑤는 스폰된 리뷰어에게 "이 diff가 orca 파이프라인 자신의 머지/게이트 안전성에
영향을 주는지 리뷰의 첫 단계로 판단하라"고 **prose로** 지시한다 — 이 판단은 "정적 파일 경로 목록과 절대
대조하지 않는다"고 스스로 명시할 만큼 전적으로 리뷰어의 즉흥 판단에 맡겨져 있다. 하지만 이 판단 중 상당
부분("이 diff가 `.githooks/`, `orca-workflows/*.md`, CI 설정 등을 건드리는가")은 `migration_files_present`와
똑같은 방식으로 diff가 스폰되기 **전에** 기계적으로 판별 가능하다. 지금은 이 신호가 tier 선택에 반영되지
않고, 이미 낮은 tier로 뽑힌 리뷰어가 그 사실을 스스로 기억해서 더 엄격해지길 바라는 prose 지시 하나에만
의존한다.

## 배경 조사 (기각된 방향 포함)

이 spec 이전에 별도로 검토했다가 기각한 접근들은 아래 "검토했으나 기각한 대안"에 정리한다. 요약:

- **Golden-dataset 기반 functional test 인프라**(과거 PR/이슈에서 정답 라벨을 마이닝해 select_reviewer.py와
  실제 스폰된 리뷰어의 판단을 검증) — 이 레포에서 실제로 라벨링 가능한 과거 사례가 2~3건뿐임을
  `gh issue list` 조사로 확인. 지금 투자하기엔 근거가 너무 얇다. 별도 논의로 분리.
- **294개 기존 테스트(207개 실행 기반 + 87개 텍스트-단언) 정리** — 87개 중 issue 근거가 exec 테스트와
  겹치는 건 2/13, 같은 issue를 공유하는 파일 군(issue #140, 7개 파일)도 확인해보니 서로 다른 파일을 각각
  지키는 것이라 내부 중복도 아니었다. "손쉬운 삭제 대상"을 찾는 시도가 두 방향 다 실증적으로 실패했다 —
  이 spec은 기존 테스트를 건드리지 않는다.

## 범위

**수정 대상**: `skills/orca-evaluate/SKILL.md` §3(diff 리뷰 절)뿐. `skills/orca-evaluate/scripts/select_reviewer.py`는
**인터페이스 변경 없음**(기존 `--high-risk-signal` 플래그를 그대로 재사용).

**하나의 스펙으로 묶는 이유**: 게이트-안전 경로 목록 계산과 그 결과를 `select_reviewer.py` 호출에 배선하는
것은 분리해서 머지할 이유가 없는 단일 변경이다.

**범위 밖**:

- **Golden-dataset 마이닝 인프라** — 위 배경 조사 참고. 근거 부족, 별도 논의 필요 시 재개.
- **294개 기존 테스트(87개 텍스트 + 207개 실행) 삭제·교체** — 근거 부족 확인됨(위 배경 조사). 정책만 명시:
  새 functional test가 특정 사이트의 핵심 판단 로직을 실제로 대체하게 되면 그 사이트의 텍스트 단언을
  **개별적으로** 재검토한다 — 일괄 삭제하지 않는다. 텍스트 단언이 잡는 실패("prose가 조용히 깨짐")와
  golden-set/functional test가 잡는 실패("판단 자체가 틀림")는 다른 실패 모드라 하나가 다른 하나를
  완전히 대체한다고 가정하지 않는다.
- **다른 orca-* 스킬로 일반화** — 지금은 `orca-evaluate`/`select_reviewer.py` 하나. 이 설계가 검증되면
  같은 패턴(경로 기반 사전 신호 + 기존 스크립트 재사용)을 다른 스킬에 적용할지는 별도 판단.
- **§3 ⑤ prose 지시 제거** — 경로 목록만으로 안 잡히는 회색지대(예: 경로는 평범한데 실질적으로 게이트
  로직을 우회하는 diff)의 backstop으로 남긴다. PDF도 "판단을 없애라"가 아니라 "코드화 가능한 critical
  validation은 코드화하라"는 것이지, 리뷰어의 심층 판단 자체를 없애라는 게 아니다.
- **합쳐지기 전 개별 신호 값(`migration_files_present`/`gate_safety_files_present`)을 로그에 남기는 것** —
  자기 리뷰 중 확인: `orca-workflows/scripts/log_dispatch.sh`엔 임의 extra field를 받는 플래그가 없고
  (`--skill/--role/--issue/--task-id/--terminal/--worktree/--provider/--model/--effort/--spec-text`만
  허용, 나머지는 `unknown argument` 에러), `migration_files_present`도 지금 로그에 안 남고 있다 — 애초에
  이 spec이 "기존 관례를 확장한다"고 썼던 전제 자체가 틀렸다(검증 안 하고 썼던 것, 이 자리에서 정정).
  개별 신호를 로그에 남기려면 `log_dispatch.sh`(5개 스킬이 공유)의 인터페이스 자체를 넓혀야 해서 이
  spec의 범위를 벗어난다. 필요해지면(사후 분석 수요가 실제로 생기면) 별도 이슈로.
- **이번 PDF 감사에서 함께 발견된 다른 항목**(`lifecycle-gate-policy` description 1024자 초과,
  `orca-evaluate`/`orca-retro`/`orca-task-runner` negative trigger 부재, SKILL.md 크기 상한 근접) — 각각
  이슈 [#152](https://github.com/SleepTimeGRT/skills/issues/152),
  [#153](https://github.com/SleepTimeGRT/skills/issues/153),
  [#154](https://github.com/SleepTimeGRT/skills/issues/154)로 분리. 레포 전체를 PDF 기준으로 개선한다는
  더 큰 목표의 나머지 조각들이며, 이 spec 하나로 다 처리하지 않는다.

## 검토했으나 기각한 대안

1. **`select_reviewer.py`에 새 플래그(`--gate-safety-signal`)를 별도로 추가** — 스크립트 내부에서
   `migration_files_present`와 `gate_safety_files_present`를 별도 파라미터로 받게 하는 안. 기각: 스크립트
   자신은 "이게 왜 high-risk인지" 몰라도 tier 선택엔 지장 없다(둘 다 결과적으로 같은 상위 tier로 승격).
   테스트 표면과 인터페이스를 넓히지 않고 호출부(`orca-evaluate/SKILL.md`)에서 OR로 합쳐 넘기는 쪽이
   기존 `--high-risk-signal` 계약과 `test_select_reviewer.py`의 기존 27개 테스트를 안 건드린다.
2. **경로 매칭을 정규식/설정 파일로 별도 관리** — `migration_files_present`가 인라인 배열로 계산되는
   기존 패턴과 다른 메커니즘을 도입하는 것. 기각: 지금 레포에 이런 패턴이 하나뿐(migration)인 상태에서
   두 번째 사례가 생기자마자 설정 파일로 추상화하는 건 이르다(YAGNI) — 인라인 배열로 시작하고, 세 번째
   신호가 필요해지는 시점에 공통 헬퍼로 뽑는 걸 재고한다.
3. **§3 ⑤ prose 지시를 이번에 함께 축소·재작성** — 새 신호가 커버하는 영역만큼 프롬프트를 줄이는 안.
   기각: 이번 spec의 검증 대상(tier 승격이 실제로 일어나는지)과 별개 관심사이고, prose 변경은 그 자체로
   "critical validation이 여전히 prose로 남아있는 정도"를 재평가해야 하는 별도 작업이다. 이번엔 §3 ⑤를
   그대로 두고 새 신호만 앞단에 추가한다.

## 설계

### 1. 게이트-안전 경로 계산 (`orca-evaluate/SKILL.md` §3)

`migration_files_present` 계산 블록(§3, diff 리뷰 절 초입) 바로 옆에 같은 모양으로 추가한다:

```bash
gate_safety_files=( <diff에 포함된 경로 중 아래 패턴에 매칭되는 것들...> )
#   .githooks/*, lifecycle-gate.toml, orca-workflows/**/*.md, orca-workflows/scripts/*,
#   skills/*/scripts/*, skills/*/SKILL.md, .github/workflows/*, premerge*.sh, token-gate.sh
gate_safety_files_present=false
[ ${#gate_safety_files[@]} -gt 0 ] && gate_safety_files_present=true
```

`migration_files`와 동일한 quoting 규칙(개별 quoted 배열 원소, unquoted 문자열 확장 금지 — zsh/bash
word-splitting 차이) 그대로 적용한다.

`skills/*/SKILL.md` 패턴은 이 파이프라인 자신(`orca-*` 스킬군)이 스스로를 수정하는 diff까지 포함한다 —
이번 세션 내내 다룬 boot-quiesce/dispatch-verify 류 변경이 정확히 이 범주다.

### 2. `select_reviewer.py` 호출부 변경

기존 호출(§3, `reviewer_json=` 직전)의 `--high-risk-signal` 조건절만 확장한다:

```bash
reviewer_json="$(python3 <skill-dir>/scripts/select_reviewer.py --shortstat "$diff_shortstat" \
  $( [ "$codex_available" = true ] && echo --codex-available || echo --no-codex-available ) \
  $( { [ "$migration_files_present" = true ] || [ "$gate_safety_files_present" = true ]; } && echo --high-risk-signal ))"
```

`select_reviewer.py` 본체는 수정하지 않는다 — 기존 `--high-risk-signal`이 이미 "diff에 하나 이상의 고위험
신호가 있다"는 뜻으로 정의돼 있고, 어느 신호가 그걸 세웠는지는 스크립트가 알 필요 없는 정보다.

### 3. 검증 — PDF의 가벼운 레시피 그대로

기존 `test_select_reviewer.py`의 두 테스트(`test_select_reviewer_small_migration_diff_is_no_longer_lowest_tier_when_codex_available`/
`..._when_codex_unavailable`)와 정확히 같은 모양의 새 테스트를 `skills/orca-evaluate/SKILL.md` §3의
bash 로직에 대해 추가한다 — 단, 이번엔 검증 대상이 `select_reviewer.py`(이미 커버됨, 변경 없음)가 아니라
**§3의 OR 조건 계산 자체**다. `test_dispatch_boot_quiesce_wiring.py`가 이미 쓰는 패턴(SKILL.md의 bash 블록을
문자열로 추출해 스텁 `orca`/`git` 함수로 subprocess 실행) 그대로 재사용한다:

- Given: `migration_files_present=false`, `gate_safety_files_present=true`인 상태를 스텁으로 구성
- When: §3의 해당 bash 블록 실행
- Then: `select_reviewer.py`가 `--high-risk-signal`을 받고 실행됐는지(호출 인자로 확인)

이건 PDF Ch2 "Define success criteria"가 실제로 제시하는 수준(with/without 비교, 가벼운 반복 검증)과
정확히 맞아떨어진다 — golden-dataset 없이도 "신호가 있을 때 없을 때와 다르게 동작하는가"를 결정론적으로
확인할 수 있다.

## 에러 처리

경로 패턴은 완벽하지 않다(false positive/negative 둘 다 가능) — 이건 받아들이는 트레이드오프다:

- **False positive**(게이트-무관한 이유로 매칭 경로를 건드림, 예: `skills/*/SKILL.md`의 오타 수정): 불필요하게
  높은 tier로 리뷰 — 비용 소폭 증가일 뿐 정확성 문제가 아니다.
- **False negative**(실질적으로 게이트에 영향을 주지만 매칭 패턴 밖의 경로): §3 ⑤ prose 지시가 여전히
  backstop이다 — 이번 변경으로 그 지시를 없애지 않는 이유가 여기 있다.

두 경우 다 조용한 실패가 아니다 — 전자는 낭비, 후자는 기존과 동일한(더 나빠지지 않는) 상태로 되돌아간다.

## 마이그레이션/롤아웃

`orca-set.version`이 묶는 7개 orca-* 스킬 세트에 `orca-evaluate`가 포함되므로, 구현 완료 후
`scripts/deploy-skills.sh`로 세트 전체를 배포해야 실제 반영된다(AGENTS.md "Skill deployment" 절차 그대로).
