# Log-schema enum gaps: name known branches, reserve UNMAPPED_BRANCH for unknown ones

`orca-workflows` 로그 스키마의 닫힌 enum(`logging.md` §1 `outcome`, `self-recovery.md` `action_taken`)은
정상 분기가 enum에 없을 때마다 기록 주체가 즉석 문자열을 발명하는 드리프트를 반복해 왔다(#62, #69,
#86에서 한 세션에 3건). 우리는 혼합 방식을 택한다: **의미가 이미 규명된 분기는 전용 값으로 즉시
등재**하고(관측된 실사용 문자열을 그대로 채택), **아직 규명되지 않은 미래의 분기**를 위해 예약값
`UNMAPPED_BRANCH` + 실제 관측 문자열 필드(`raw_outcome`/`raw_action`) + 추적 이슈 필드
(`schema_gap_issue`)의 3종 안전판을 두 문서 모두에 둔다.

## Considered Options

- **점 패치만** (알려진 갭에 전용 값 추가, 안전판 없음) — 네 번째 미지의 갭에서 즉석 발명이 그대로
  반복된다. 기각.
- **안전판만** (`UNMAPPED_BRANCH`로 전부 수용, 전용 값 추가 없음) — 의미를 이미 아는 분기까지 미매핑으로
  남겨 관측성이 떨어지고, `orca-retro` 렌즈 1(스키마 위반 탐지)이 알려진 분기를 계속 갭으로 오탐한다.
  기각.
- **혼합(채택)** — 알려진 분기는 이름을 갖고, 미지의 분기는 발명 대신 `UNMAPPED_BRANCH`로 기록하면서
  `schema_gap_issue`로 추적된다. grep 한 번으로 미해결 스키마 구멍 목록이 로그에서 바로 나온다.

## Consequences

- `CONTRACT_APPROVED_ROUND1`은 `CONTRACT_APPROVED` + 가변 `round` 필드로 대체된다(기존
  `CONTRACT_FINALIZED_BY_GENERATOR`/`CONTRACT_ESCALATE`의 "값 이름 + `round` 필드" 패턴과 통일).
  과거 로그 라인은 append-only 원칙대로 재작성하지 않는다 — 판독 시 두 표기가 공존한다.
- `UNMAPPED_BRANCH` 라인의 존재는 곧 열려 있어야 할 스키마 구멍 이슈의 존재다 — retro 렌즈 1은 이 값을
  위반이 아니라 "추적 중인 알려진 구멍"으로 읽는다.
