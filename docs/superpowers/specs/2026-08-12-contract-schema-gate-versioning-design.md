# contract-schema 게이트 소급 적용 방지: CONTRACT_SCHEMA_STALE 설계

이슈: [#160](https://github.com/SleepTimeGRT/skills/issues/160). 관련: [#130](https://github.com/SleepTimeGRT/skills/issues/130)(이번 게이트를 도입한 원인 이슈), [#96](https://github.com/SleepTimeGRT/skills/issues/96)(#130의 원인 사고), [#161](https://github.com/SleepTimeGRT/skills/issues/161)(이 설계 중 발견한 별개 공백, 범위 밖으로 분리).

## 문제

`79b7c3b`(Closes #130, 2026-08-12T09:44:57+09:00 머지)가 `orca-workflow-task` §1에
`override.json`은 있는데 `proposal-r3.json`이 없으면 무조건 `outcome=CONTRACT_ESCALATE`(기록 계약
위반)로 판정하는 fail-closed 분기를 신설했다. 이 게이트는 **소급 적용**된다 — 이 커밋 이전에 override를
정상 완료(당시 규칙엔 `proposal-r3.json` 요구사항 자체가 없었다)한 세션이 이후 재확인되면, 실제로는
아무 규칙도 어기지 않았는데 "위반"으로 오분류된다.

실측 사례(studio-hevv/selah-android issue #20, 원본 이슈 본문 참고): 05:10 override 완료 → 구현까지
정상 진행(커밋 7개, 게이트 통과) → 09:44 게이트 도입 → 10:55 재확인 시 `CONTRACT_ESCALATE`로 오분류 →
`escalation_parked`. issue #20은 여전히 OPEN, PR 없음, `orca-evaluate` 미호출 상태로 방치됐다.

이 설계 착수 시점에 로컬 `~/.local/state/orca-workflows/contracts/`를 스캔한 결과, 같은 조건(override
있음, proposal-r3 없음, override.json mtime이 게이트 도입 이전)을 만족하는 디렉토리가 **20개**
확인됐다(medicount 1건, selah_android 9건, sleeptimegrt-skills 6건, toss-samhaengsi 4건) — 이번
보고 사례 1건이 아니라 게이트 도입 시점 이전 4.5시간 안에 override를 완료한 모든 세션이 잠재적
영향권이었다. 다만 이 스캔은 override→r3 부재 여부만 볼 뿐 해당 issue가 현재 open/closed인지는 보지
않으므로, "20건이 전부 지금 stuck 상태"라는 뜻은 아니다 — 이후 재확인 없이 이미 다른 경로로 끝난
것도 섞여 있을 수 있다.

## 근본 원인

`contract-schema.md`의 게이트(스키마) 변경이 무버전(unversioned)이다 — "이 요구사항이 언제부터
유효한가"를 기계가 판별할 수 있는 형태로 기록해두지 않아서, 파일 상태만 보는 fail-closed 로직이
"규칙을 어김"과 "그 규칙이 그때 없었음"을 구조적으로 구분하지 못한다.

## 범위

**수정 대상**: `orca-workflows/contract-schema.md`, `orca-workflows/scripts/contract_resume.sh`,
`skills/orca-workflow-task/SKILL.md`(§1, §5), `orca-workflows/logging.md`,
`orca-workflows/scripts/log_dispatch.sh`(`LOG_OUTCOME_ENUM`), `skills/orca-retro/SKILL.md`(lens 3),
`tests/test_contract_resume.py`, `skills/orca-set.version`(버전업).

**범위 밖**:

- **`contract_resume.sh`가 "구현은 끝났는데 evaluate만 안 불렸다"를 자동 감지해 evaluate로 바로
  점프하는 기능.** 별도 이슈 [#161](https://github.com/SleepTimeGRT/skills/issues/161)로 분리했다 —
  이 공백은 `CONTRACT_SCHEMA_STALE`에 국한되지 않고 임의의 "구현 dispatch 후 evaluate 직전 크래시"
  시나리오에서도 재현되는, 이번 사고와 독립적인 기존 구조적 공백이다. 여기서 손대면 "CONTRACT_DIR
  파일만 보고 판별 가능한 범위"라는 `contract_resume.sh`의 현재 설계 전제(워크트리 상태를 보지
  않는다)를 깨야 해서 검증 부담이 크게 늘어난다.
- **자동 마이그레이션(사후 `proposal-r3.json` 합성 후 자동 계속 진행).** 이슈 본문의 제안 (b)에
  해당하나 채택하지 않는다 — `proposal-r3.json`은 구현 **이전에** 확정돼야 evaluator의 맹검 검증
  (`contract-schema.md`의 적대적 판정·self-evaluation 편향 방지 설계 근거)이 성립한다. 이미 끝난
  구현을 보면서 사후에 r3를 합성하면 diff를 보고 AC를 짜맞추는 것과 같아져, 이 스키마가 막으려던
  문제를 그대로 재현한다. 따라서 복구는 항상 사람이 개시한다.
- **다른 fail-closed 게이트에 대한 일반 스키마-버전 레지스트리.** 지금까지 이런 종류의 사고가
  관측된 것은 이번 1건뿐이라, 재사용 가능한 레지스트리 파일을 미리 만들 근거가 얇다(YAGNI). 같은
  패턴(게이트 옆에 도입 시각 상수 + `_cr_predates_r3_gate` 스타일 헬퍼)이 세 번째로 필요해지면 그때
  공통 추상화를 고려한다.
- **기존 20개 디렉토리의 개별 상태 재확인·수동 복구.** 이건 이 스킬 레포의 설계/구현 범위가 아니라
  각 대상 repo에서의 운영 작업이다. 배포 후 재스캔해 사람이 개별 판단한다.

## 새 outcome: `CONTRACT_SCHEMA_STALE`

`override.json`은 있고 `proposal-r3.json`이 없는 상태를 만나면, `override.json`의 mtime을 이
요구사항의 도입 시각(상수, 아래)과 비교해 3번째 해석을 추가한다:

| override.json mtime | 상태 | outcome |
|---|---|---|
| 게이트 도입 이후 | worker_done 수신됨(§1) → 진짜 위반 | `CONTRACT_ESCALATE`(기존 그대로) |
| 게이트 도입 이후 | worker_done 없음(§0 재개) → 쓰다 죽음 | override 스텝 재-태움(기존 그대로) |
| **게이트 도입 이전** | **위반도 크래시도 아님 — 구버전 세션** | **`CONTRACT_SCHEMA_STALE`(신설)** |

`logging.md`의 두 축 중 **진행-분기 축**에 놓는다(`MERGE_CONFLICT`/`CI_GATE_TIMEOUT`과 같은 성격 —
작업물의 품질·AC에 대한 판정이 아니라 예외적이지만 처리된 워크플로 상태이기 때문. 처음엔 "§5로
간다"는 이유로 verdict 축(`CONTRACT_ESCALATE`와 동급)에 놓으려 했으나, 이 축의 실제 기준은 "작업물에
대한 판정이냐"이지 "어디로 라우팅되냐"가 아니다). 형제값(`CONTRACT_ESCALATE`/
`CONTRACT_FINALIZED_BY_GENERATOR`)과 같은 필드 구성: `round`(도달 라운드 수, 이 게이트 한정 항상 2) +
`detail`(두 시각 문자열, 아래 §5 문구 참고).

## 감지 메커니즘

게이트 도입 시각은 **이 게이트 옆에 하드코딩**한다(공용 JSON 레지스트리 신설은 범위 밖 — 위 참고).
비교 메커니즘은 `contract_resume.sh`가 이미 쓰는 `recent_write` 가드와 동일한 패턴
(`touch -t` 기준 파일 + `find -newer`)을 재사용한다 — `stat -f`/`date -d` 기반 epoch 파싱은
GNU `stat -f`(파일시스템 정보 플래그, mtime 아님)와 충돌해 숫자 비교에 쓰레기 값이 들어갈 위험이
있어 배제했다.

```bash
# contract-schema.md "override 후속 라운드" 절 도입 시점(commit 79b7c3b, issue #130) — 이 값을
# 바꾸는 건 그 요구사항 자체가 또 바뀔 때뿐이다(현재 재도입 계획 없음, issue #160).
# touch -t 포맷 [[CC]YY]MMDDhhmm[.SS] — 이 파이프라인이 도는 머신의 로컬 TZ(KST) 기준.
R3_REQUIRED_SINCE='202608120944.57'

_cr_predates_r3_gate() {   # $1 = probed file. echoes 1(stale)|0(on/after gate) to stdout.
  local ref
  ref="$(mktemp "${TMPDIR:-/tmp}/contract-resume-r3gate.XXXXXX")" || return $?
  touch -t "$R3_REQUIRED_SINCE" "$ref" 2>/dev/null
  if [ -n "$(find "$(dirname "$1")" -maxdepth 1 -name "$(basename "$1")" -newer "$ref" 2>/dev/null)" ]; then
    printf '0'
  else
    printf '1'
  fi
  rm -f "$ref"
}
```

경계: mtime이 상수와 정확히 같은 초면 `find -newer`는 "newer 아님"으로 보므로 stale로 분류된다 — 실제
사건이 도입 시각과 정확히 같은 초에 발생할 확률은 무시 가능하므로 별도 처리하지 않는다.

`contract_resume.sh`(§0 재개 경로)와 `orca-workflow-task` §1(실시간 경로)은 **미러링**한다 — 공유
함수로 추출하지 않고 상수+로직을 양쪽에 복제하고 상호 참조 주석을 단다. 이는 새 관례가 아니라 이미
이 두 지점이 `ac_fidelity` jq 체크 등 다른 분기에서 쓰고 있는 기존 관례(§1은 프로즈로 에이전트가
직접 타이핑해 실행하는 텍스트라, `contract_resume.sh`를 매번 소싱해 함수를 호출하게 만드는 게 오히려
이 파일의 실행 모델과 어긋난다)를 그대로 따른 것이다.

## 분기별 변경

**`contract_resume.sh`** — `elif [ "$maxp" -lt 3 ]`(override 있음, r3 없음) 분기 진입 시
`_cr_predates_r3_gate "$dir/override.json"`을 먼저 확인:
- `1`(stale) → `contract="escalated"; resume="section-5"; outcome='"CONTRACT_SCHEMA_STALE"'`,
  `round=2`, `detail`에 override mtime과 게이트 도입 시각을 사람이 읽을 수 있는 형태로 기록.
- `0`(그 외) → 기존 그대로("죽다 재-태움", `resume="section-1-override"`).

**`orca-workflow-task` §1** — `elif [ ! -f proposal-r3.json ]` 분기도 같은 판정을 앞에 두어
`CONTRACT_SCHEMA_STALE`과 기존 `CONTRACT_ESCALATE`(기록 계약 위반)를 분리한다.

## §5 사람 보고 문구

`CONTRACT_ESCALATE`/`CI_GATE_FAIL` 등과 같은 자리에 다음을 추가한다. **"자동 재개"를 암시하는
문구를 쓰지 않는다** — 아래 §범위 밖에서 설명한 대로 `contract_resume.sh`는 구현 완료 여부를 모르므로,
사람이 r3를 쓴 뒤 자동 재개를 그대로 트리거하면 완료된 구현을 다시 만들려 들 위험이 있다(#161):

> **`CONTRACT_SCHEMA_STALE`**: override 완료(mtime `<t1>`)가 이 게이트 도입 시각(`<t2>`, commit
> 79b7c3b) 이전 — 위반이 아니라 구버전 세션. 사람의 선택지: (a) `verdict-r2.json`의 미해소
> `reasons`를 반영해 `proposal-r3.json`을 수동 작성한다 — 이때 worktree에 구현이 이미 있어도
> **§2를 기계적으로 재실행해 이미 끝난 구현을 덮어쓰지 않도록 주의한다**: §2 "Dispatch 실행부"는
> "코디네이터가 직접 코드를 작성·수정해 §3로 가는 경로는 존재하지 않는다"(issue #128)고 명시하므로,
> 기존 diff를 그대로 §3 evaluate로 넘기는 정식 경로가 이 스킬에 현재 없다 — 이 공백은 issue #161로
> 추적하며, 사람이 상황을 보고 직접 진행 방식을 정한다. 구현이 없으면 정상적으로 §2부터 재개한다.
> (b) 완료된 작업을 폐기하고 재협상을 지시한다.

**정정(구현 단계에서 발견)**: 이 문단은 애초 "§2를 재실행하지 말고 §1의 evaluate-dispatch 블록만
재사용"을 제안했으나, 이는 실재하지 않는 경로였다 — §2 "Dispatch 실행부"(issue #128)와 §3 "Generate
감사 게이트"(issue #128, 매 evaluate dispatch 전 `role="task-runner"` assign 기록을 기계적으로 확인)가
함께 "이미 있는 diff를 evaluate에 바로 넘기는" 우회를 명시적으로 차단한다. 구현 중 이 모순이 발견돼
위 문단을 정정했다.

## enum 등록

`log_dispatch.sh:79`의 `LOG_OUTCOME_ENUM`(기계-검증 정본)과 `logging.md`(사람용 미러) 둘 다 갱신한다
— enum에만 없으면 `log_outcome()`이 조용히 `outcome=UNMAPPED_BRANCH`로 강제 대체하므로, 스크립트
쪽을 빠뜨리면 새 outcome이 로그에 절대 나타나지 않는다.

## orca-retro 반영

lens 3("예방 가능했던 ESCALATE·인간 개입")이 `CONTRACT_SCHEMA_STALE` 발생을 매번 "스킬 문구로 막을
수 있었던 결함"으로 오탐하지 않도록, ADR 0001의 `UNMAPPED_BRANCH`/`CONTRACT_APPROVED_ROUND1` carve-out과
같은 자리에 다음을 추가한다: `outcome`이 `CONTRACT_SCHEMA_STALE`인 레코드는 이미 추적된 마이그레이션
범주이므로 후보에서 제외한다.

## 테스트

`tests/test_contract_resume.py`에 두 케이스 추가:
- override mtime이 `R3_REQUIRED_SINCE` 이전 → `outcome="CONTRACT_SCHEMA_STALE"`,
  `resume="section-5"`, `round=2`.
- override mtime이 이후(기존 `test_override_without_r3_reruns_override_step`과 동일 시나리오, 회귀
  없음 확인) → 기존 `resume="section-1-override"`, `round=3` 그대로.

`os.utime`(기존 `_age()` 헬퍼 확장)으로 결정론적으로 backdate — 시스템 시계에 의존하지 않는다.

## 배포 메모

`orca-workflow-task`/`orca-retro`는 `orca-set`(현재 v1.1.17) 멤버라 `skills/orca-set.version`
버전업 + `scripts/deploy-skills.sh` 실행이 필요하다. `orca-workflows/`(`contract-schema.md`,
`contract_resume.sh`, `logging.md`)는 main 머지 즉시 심볼릭 링크로 반영되지만, `skills/`(SKILL.md
prose)는 별도 배포 스텝을 거쳐야 실제로 적용된다 — 두 반영 시점이 어긋난다는 점을 롤아웃 시 유의한다.
