# orca-retro — 이슈 라벨 범용화 + 실행시점 버전 캡처 — Design

**Date**: 2026-08-07
**Status**: Approved (brainstorming phase) — pending implementation plan

## Context

사용자가 GitHub 이슈 backlog를 열어보며 "옛날 버전에서 실행해서 생긴 오류일 수 있다"는 가설을 제기했다.
실측 결과(이 문서 작성 세션에서 subagent로 열린 이슈 6개 전부를 현재 HEAD 기준으로 재확인) 그 가설은
틀렸다 — #72/#70/#69/#68/#42/#3 전부 `STILL_VALID`였고, 나중 커밋이 이미 고친 것은 하나도 없었다. 다만 이
과정에서 실제 결함 두 가지를 발견했다:

1. **이슈를 봐도 "이 버그가 어느 버전(커밋)에서 관측됐는지" 알 방법이 없다.** `orca-retro`(현재 유일하게
   `gh issue create`를 호출하는 스킬, `skills/orca-retro/SKILL.md:90`)의 이슈 body 템플릿에 버전/커밋 필드가
   없다. `AGENTS.md`가 이미 문서화한 대로 `skills/`는 `deploy-skills.sh`로 별도 배포되는 commit-pin이라
   레포 HEAD와 배포본이 어긋날 수 있는데(`~/.agents/skills/orca-retro/.installed-version.json`이 실측 시점에
   `fc18dde`로, 레포 HEAD `6dc50c2`보다 뒤처져 있었다 — 바로 그 사례), 이슈 본문 어디에도 이걸 알 근거가
   없었다.
2. **"스킬이 실행 중 발견한 이슈"와 "사람이 만든 이슈"를 구분하는 라벨은 이미 있다** — `retro` 라벨
   (`orca-retro가 파일한 스킬 결함`). 다만 description이 `orca-retro` 전용처럼 좁게 쓰여 있어, 앞으로 다른
   경로(ad-hoc 세션, 다른 스킬)로 이슈를 파일링할 때도 재사용 가능한 일반 컨벤션이라는 게 안 드러난다.

## 범위

**수정 대상**: `orca-workflows/logging.md`(§2 meta 스키마), `skills/orca-retro/SKILL.md`(§4 이슈 body
템플릿 + 라벨 설명 문구), GitHub `retro` 라벨의 description(`gh label edit`).

**건드리지 않는 것**:

- `skills/orca-workflow/SKILL.md`, `skills/orca-task-runner/SKILL.md`, `skills/orca-evaluate/SKILL.md`의
  실제 코드 — 세 파일 모두 meta 레시피를 직접 들고 있지 않고 `logging.md §2`를 참조만 한다(실측 확인,
  `grep -n meta`로 3개 파일 전부 "logging.md §2 term 로그: ... meta 기록 후" 형태의 참조 문구뿐).
  `logging.md` 한 곳만 고치면 세 스킬 모두에 새 필드가 적용된다.
- `assignments*.jsonl`/`waves*.jsonl`의 `assign`/`outcome`/`wave_start`/`wave_end` 이벤트 — 버전 필드는
  §2 `meta`(터미널당 1회, 이미 "write once, first line" 보장이 있는 자리, issue #59 교훈)에만 추가한다.
  같은 정보를 매 assign/outcome 레코드에도 중복시키는 건 이번 범위 밖(YAGNI) — 필요해지면 나중 이슈로.
- `issue-trackers/{selection,github,jira}.md` — 이 어댑터들은 orca-workflow가 *대상 repo*의 이슈를 다룰 때
  쓰는 백엔드 인터페이스고, `orca-retro`는 항상 `gh issue create`로 sleeptimegrt-skills 레포에 직접 파일링한다
  (스킬 결함은 항상 이 레포 소관이므로 백엔드 선택이 필요 없음). 건드릴 이유가 없다.
- 이슈 #1(open issue backlog 재판정)의 실행 결과 자체 — 이미 이 세션에서 읽기 전용으로 끝났고 닫을 이슈가
  없었다. 별도 산출물(새 트래킹 이슈 등)을 만들지 않는다 — 기존 6개 open 이슈가 곧 큐다.

## 아키텍처

### A. `logging.md` §2 meta 레코드에 필드 3개 추가

현재 meta는 터미널 스폰 시 1회, 다음 필드로 기록된다: `type, issue, skill, role, terminal, created_at`.
여기에 3개를 추가한다 — 전부 best-effort, 실패해도 `null`로 채우고 meta 기록 자체(및 그걸 게이팅하는 어떤
흐름도)를 막지 않는다. 기존 로깅의 "환경 문제가 워크플로를 막지 않는다"는 원칙(§2 자체가 이미 idempotent
guard로 재시도를 흡수하는 것과 동일한 사상)을 그대로 따른다.

| 필드 | 소스 | 의미 |
|---|---|---|
| `skill_version` | `~/.agents/skills/<skill>/.installed-version.json`의 `{version, commit}` | 그 순간 실제 **배포(commit-pin)**된 스킬 버전. 레포 HEAD와 다를 수 있음(그게 이 필드의 존재 이유). |
| `orca_workflows_commit` | `git -C ~/.agents/orca-workflows rev-parse HEAD` | orca-workflows는 symlink-tracks-main이라 항상 "그 순간의" 레포 HEAD — `skill_version.commit`과 별도 축(AGENTS.md #22 결정: 두 배포 경로가 원래 독립적으로 표류함). |
| `orca_app_version` | `orca status --json`의 `.result.runtime.appVersion` | 실측 확인된 실제 경로(`1.4.175` 관측). Orca 앱 자체 버전에 기인하는 버그(#42류)를 추적하기 위함. `orca` 커맨드 부재/실패 시 `null`. |

`.installed-version.json`이 없는 경우(스킬이 아직 배포된 적 없음, 또는 orca-workflows처럼 애초에 그 파일이
없는 대상)는 `skill_version: null`.

### B. `orca-retro` §4 이슈 body에 "환경/버전" 섹션 추가

이슈를 새로 만들거나(§4 `gh issue create`) 재발 코멘트를 달 때, 다음 우선순위로 버전 정보를 채운다:

1. 이번 결함의 증거로 인용한 term 로그(`term-<handle>.jsonl`)가 있으면 그 파일의 meta 라인(1행)에서
   `skill_version`/`orca_workflows_commit`/`orca_app_version`을 그대로 뽑아 쓴다 — **실제 버그가 관측된
   시점의 버전**이라 가장 정확하다.
2. term 로그가 없는 후보(assignments/spawn-failures만으로 나온 렌즈1·렌즈4 후보)는 대상 스킬의 **현재**
   `~/.agents/skills/<skill>/.installed-version.json`을 폴백으로 쓰되, 이슈 본문에 "실행 당시 버전이 아니라
   분석 시점 기준 — 그 사이 재배포됐을 수 있음"이라고 명시한다. 이 폴백을 조용히 정확한 값처럼 적지 않는다.

### C. `retro` 라벨 범용화

- `gh label edit retro --description "스킬 실행 중 발견된 결함/이슈"` — 라벨명은 유지, description만
  넓힌다(레이블 자체를 새로 만들지 않음 — 이미 정확히 이 용도로 쓰이고 있었고, 이름을 바꾸면 기존 20여 개
  이슈의 검색/필터 관례가 깨진다).
- `skills/orca-retro/SKILL.md`에 "이 라벨은 orca-retro 전용이 아니라 스킬 실행 중 발견한 이슈 전반의 일반
  컨벤션 — 다만 현재 `gh issue create`를 호출하는 스킬은 orca-retro뿐"이라고 명시한다. 다른 스킬에 대한
  코드 변경은 하지 않는다(범위 밖, 사용자 확인 완료 — "orca-retro만" 선택).

## 검토했으나 기각한 대안

1. **버전을 이슈 파일링 시점에만 조회**(로그에 안 남기고, `gh issue create` 직전 `~/.agents/skills/.../
   .installed-version.json`을 그때 읽기) — 더 간단하지만, 버그가 실제로 관측된 epic 실행과 orca-retro
   분석 사이에 재배포가 끼면 "그때 버전"이 아니라 "지금 버전"을 잘못 붙이게 된다. 사용자가 정확도를
   우선한다고 확인(실행 시점 기록 선택) — 기각.
2. **버전 전용 새 이벤트 타입 추가**(meta를 안 건드리고 별도 로그) — meta가 이미 "터미널당 1회, 헤더성
   정보" 자리로 정확히 들어맞고, orca-retro가 어차피 term 로그를 읽는 김에 같은 파일에서 뽑을 수 있어 별도
   조인이 필요 없다. 새 이벤트 타입은 `logging.md`에 실질적 이점 없이 스키마만 늘린다 — 기각.
3. **`retro` 라벨을 새 이름으로 교체**(예: `skill-filed`) — 기존 이슈 20여 개가 이미 `retro`로 필터되고
   있어 이름을 바꾸면 과거 이슈 검색이 깨진다. description만 넓히는 쪽이 하위 호환적 — 채택.

## 테스트

- `tests/test_orca_skills.py`류 구조 테스트에, `logging.md` §2 meta jq 레시피 문자열에 새 필드 키
  (`skill_version`, `orca_workflows_commit`, `orca_app_version`)가 포함되는지 assert 추가.
- `orca-retro/SKILL.md`의 §4 body 템플릿에 "환경/버전" 섹션 문구가 존재하는지, 그리고 term-로그-있음/없음
  두 경로(위 B의 우선순위 1/2) 문구가 모두 존재하는지 assert 추가.
- 실제 `orca status --json` 호출은 CI/테스트 환경에 Orca 앱이 없을 수 있으므로 테스트에서 mock하지 않고
  스킬 문서(prose)의 "실패 시 null" 지침 존재만 구조적으로 확인한다 — 런타임 동작 자체는 이 레포의 다른
  best-effort 로깅 규칙과 동일하게 실서비스에서 자연 검증된다.
