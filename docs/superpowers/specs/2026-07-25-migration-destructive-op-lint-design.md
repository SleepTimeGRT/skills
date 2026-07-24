# DB Migration Destructive-Op Lint + orca-evaluate ESCALATE 연동 — Design

**Date**: 2026-07-25
**Status**: Approved — pending implementation
**Source issue**: [SleepTimeGRT/sleeptimegrt-skills#9](https://github.com/SleepTimeGRT/sleeptimegrt-skills/issues/9) (MediCount/MediCount#343에서 재평가 후 이관)

## Context

`lifecycle-gate-policy`의 canonical 정책은 현재 "schema/migrations를 건드리는 변경은 무조건 human-gate"라고 못 박아 두고 있다(`assets/agents-policy.md` self-merge 에스컬레이션 규칙). 이 원안을 AI 리뷰 기반 self-merge로 완전히 개정하자는 제안이 medicount#343에서 나왔으나, 재평가 결과 그 4종 세트(Squawk 도입 + pgTAP 지침 강화 + 롤백 자동화 + 정책 개정)는 과설계로 판단되었다. `premerge.sh`는 이미 모든 코드 변경(스키마 포함)에 리뷰를 강제하고, `parity.sh`가 이미 매 PR마다 `db reset` + schema/types diff + pgTAP을 돌린다. 실제로 부족한 것은 review가 놓칠 수 있는 걸 **결정론적으로** 잡아주는 destructive-op 탐지뿐이다.

이 정책 문구는 `lifecycle-gate-policy` 마커가 박힌 cross-repo canonical 블록에 있고, medicount 외에도 `sidework-dashboard`, `pokeplant` 등 다른 supabase 프로젝트가 공유한다. **린터 게이트 없이 정책 문구만 삭제하면, 린터가 없는 다른 repo들도 동시에 self-merge가 허용되어 gate가 약화된다** — 그래서 정책 개정과 린터 게이트는 같이, 그리고 canonical 레벨(이 repo)에서 다뤄야 한다.

"destructive하지만 의도된 변경"을 판단하는 sprint-contract 메커니즘은 이미 `skills/orca-evaluate/SKILL.md`(§1 contract 판정 + §3 code review → PASS/FAIL/ESCALATE)에 구현되어 있다. 이 설계는 그 기존 메커니즘에 4번째 ESCALATE 조건을 얹는 것이지, 새 판정 인프라를 만드는 게 아니다.

## 사전 확인된 제약 (구현 전 코드 확인으로 확정)

- **`orca-workflow`의 PASS 경로는 `gh pr merge`를 직접 호출하고 `scripts/premerge.sh`를 거치지 않는다**(`skills/orca-workflow/SKILL.md` §2d). 즉 이 설계가 다루는 두 경로 — ①사람/에이전트가 `premerge.sh`로 직접 셀프머지 ②`orca-workflow`가 `orca-evaluate` 판정으로 셀프머지 — 는 완전히 분리된 독립 코드패스이며 서로 간섭하지 않는다. 같은 destructive-op를 "한쪽은 하드블록, 한쪽은 계약 대조"로 다르게 처리해도 충돌이 생기지 않는다.
- `orca-task-runner`의 §1 "제안서"는 자유 형식 텍스트(구현 범위 + 검증 방법)이며, 아직 구조화된 스키마가 없다. §1은 구현 **전** 단계라 diff가 존재하지 않는다 — 린터를 여기서 돌릴 수 없다. 린터가 돌 수 있는 시점은 diff가 확보되는 §3뿐이다.
- `premerge.conf.sh`의 기존 관례상 경로 매칭 변수는 전부 정규식이다(`REVIEW_EXEMPT_REGEX`, `PROTECTED_EXTRA_REGEX`). 새 변수명도 이 관례를 따른다.
- 이 repo의 canonical 스크립트(`premerge.sh`, `token-gate.sh`, `audit.py`)는 전부 외부 바이너리 의존 없는 순수 bash/Python stdlib다. 이 설계는 그 원칙을 유지한다(아래 "정적분석기 대신 deny-list인 이유" 참고).
- 테스트 컨벤션: `tests/test_lifecycle_gate_policy.py`는 정적 fixture 파일이 아니라 `GitFixture`(tempdir에 `git init` + `self.write(relative, content)`로 동적 파일 생성) 패턴을 쓴다. 신규 테스트도 이 패턴을 따른다.

## Non-goals

- Squawk/Atlas 같은 외부 정적분석기 도입 — 아래 별도 절에서 다룬다.
- pgTAP 작성 지침 강화, 롤백/역호환성 자동화 — medicount#343 원안 항목이었으나 이번 재설계에서 제외.
- pre-push(`verify:static`) 마찰 — 실재하는 별도 문제이나 이 이슈와 무관, 추후 별도 이슈.
- medicount/sidework-dashboard/pokeplant에 실제로 게이트를 적용하는 작업 — 이 설계는 canonical 자산(이 repo)만 만든다. 각 repo 적용은 `lifecycle-gate-policy`의 기존 "Apply to a repository" 절차를 따라 **사용자의 명시적 요청 시** 별도 커밋으로 진행한다(레포별 독립 커밋 원칙).

## 정적분석기(Squawk 등) 대신 deny-list 정규식 스크립트인 이유

검토했지만 유지하기로 확정한 트레이드오프:

- Squawk의 핵심 가치(락 경합/무중단 배포 분석)는 이 규모의 1인 개발 프로젝트에 과한 기능이다.
- 이 repo의 모든 canonical 게이트 스크립트는 지금까지 외부 바이너리 의존이 0개였다(순수 bash/Python stdlib). Squawk 도입은 pinned binary 설치·checksum 관리라는 새로운 유지보수 축을 여는 첫 사례가 된다.
- Deny-list는 recall 우선(정밀도보다 "일단 flag") 설계이고, 이 게이트의 역할은 "위험을 완벽히 판별"이 아니라 "의도 판정(sprint contract) 앞으로 노출"이므로 정밀도 부족의 실질 비용이 낮다(아래 "알려진 한계" 참고).
- False negative가 실제로 문제가 되면 그때 Squawk 등으로 교체/보강한다 — 지금은 가설적 위험에 미리 의존성을 들이지 않는다.

## A. 신규 canonical 스크립트 — `scripts/migration-lint.py`

위치: `skills/lifecycle-gate-policy/assets/scripts/migration-lint.py` (canonical 원본), 배포 시 repo의 `scripts/migration-lint.py`로 복사. Python stdlib-only, `audit.py`와 동일한 스타일.

**인터페이스:**

```bash
python3 scripts/migration-lint.py <file> [<file> ...]
```

각 인자 파일의 전체 내용(파일 단위 — 라인 단위 아님, 여러 줄에 걸친 SQL 문장을 잡기 위해)을 아래 deny-list로 스캔한다(대소문자 무시).

**탐지 규칙:**

| 규칙 | 패턴 | 비고 |
|---|---|---|
| `drop-table` | `DROP TABLE` | |
| `drop-column` | `DROP COLUMN` | |
| `alter-column-type` | `ALTER COLUMN ... (SET DATA )?TYPE` | narrowing/widening 구분 안 함 — 전부 flag (coarse) |
| `truncate` | `TRUNCATE` | |
| `delete-without-where` | 세미콜론(`;`) 기준으로 문장을 나눈 뒤, `DELETE FROM`으로 시작하는 문장에 `WHERE` 키워드가 없으면 flag | 문장 분리는 best-effort(따옴표 안의 `;`는 고려 안 함 — 알려진 한계) |
| `rename` | `RENAME (TABLE|COLUMN)`, `ALTER TABLE ... RENAME` | |

**출력:** stdout에 JSON 한 덩어리.

```json
{
  "clean": false,
  "flags": [
    {"file": "supabase/migrations/0099_x.sql", "line": 3, "rule": "drop-table", "snippet": "DROP TABLE users;"}
  ]
}
```

**exit code:** 0 = `clean: true` (flag 없음), 1 = flag 1개 이상.

**알려진 한계 (의도적으로 받아들이는 coarseness):**

- narrowing/widening `ALTER COLUMN TYPE` 구분 안 함 — 전부 flag.
- 문자열 리터럴/주석 안에 deny-list 키워드가 있으면 오탐 가능.
- non-SQL 마이그레이션 포맷(Prisma/Django 마이그레이션 등)은 범위 밖 — 이 규칙은 raw SQL 텍스트 전용.
- down-migration 파일은 별도 취급 없음(up과 동일하게 스캔됨).

이 한계들은 전부 **false negative가 아니라 false positive 쪽으로 치우친 것**이라 허용된다 — flag는 차단이 아니라 "의도 판정 절차로 넘긴다"는 뜻뿐이므로, 지나치게 flag해도 실질 비용은 계약 대조 1회(orca 경로) 또는 사람이 머지(일반 경로)로 낮다.

## B. `premerge.sh` 통합 — 일반 경로(하드블록)

새 스테이지를 기존 "2. gate integrity" 뒤, "3. review requirement" 앞에 삽입한다(기존 3/4번 스테이지 번호를 4/5로 민다).

```
# ---- 3. migration safety (opt-in) --------------------------------------------
MIGRATION_LINT_ENABLED="${MIGRATION_LINT_ENABLED:-false}"
MIGRATION_LINT_REGEX="${MIGRATION_LINT_REGEX:-}"
if [ "$MIGRATION_LINT_ENABLED" = "true" ]; then
  if [ -z "$MIGRATION_LINT_REGEX" ]; then
    printf '[premerge] FAIL — MIGRATION_LINT_ENABLED=true but MIGRATION_LINT_REGEX unset\n' >&2
    exit 2
  fi
  MIGRATION_FILES=$(printf '%s\n' "$CHANGED" | grep -E "$MIGRATION_LINT_REGEX" || true)
  if [ -n "$MIGRATION_FILES" ]; then
    LINT_OUT=$(python3 scripts/migration-lint.py $MIGRATION_FILES) || {
      printf '[premerge] MIGRATION_ESCALATE — destructive-op lint flagged:\n' >&2
      printf '%s\n' "$LINT_OUT" >&2
      printf '[premerge] self-merge is not allowed — a human must review and merge this PR\n' >&2
      exit 5
    }
  fi
fi
```

- `MIGRATION_LINT_ENABLED=false`(기본값) — 스테이지 전체 no-op.
- 활성화됐지만 매치되는 변경 파일이 없으면 — no-op(다음 스테이지로).
- 활성화 + 매치 + flag 있음 — **무조건 exit 5, 우회 옵션 없음**(이 경로엔 의도 판정 메커니즘이 없으므로 — dual-path 결정 참고).
- 새 exit code 5는 스크립트 헤더 주석의 exit-code 표에 추가한다.

## C. `audit.py` — canonical 해시 대상 추가

`CANONICAL` dict에 추가:

```python
"scripts/migration-lint.py": ASSETS / "scripts" / "migration-lint.py",
```

`premerge.sh`의 `PROTECTED_REGEX`에도 추가(에이전트가 자기 게이트를 몰래 약화 못 하게):

```
PROTECTED_REGEX='^\.githooks/|^scripts/(premerge\.sh|premerge\.conf\.sh|token-gate\.sh|migration-lint\.py)$|^biome\.json$|^\.gitleaks\.toml$'
```

`premerge.conf.sh`는 이미 `PROTECTED_REGEX`에 포함돼 있으므로, opt-in 스위치(`MIGRATION_LINT_ENABLED`/`MIGRATION_LINT_REGEX`) 자체도 이미 사람 검토 없이 못 끈다 — 추가 조치 불필요.

`premerge.conf.sh` 템플릿에 새 옵션 설명 주석 추가(다른 옵션과 동일한 스타일):

```
# Destructive-op lint (opt-in). Enable and set a regex matching this repo's
# migration file paths (e.g. '^supabase/migrations/.*\.sql$').
#MIGRATION_LINT_ENABLED="true"
#MIGRATION_LINT_REGEX='^supabase/migrations/.*\.sql$'
```

## D. `orca-task-runner` §1 제안서 포맷 — 필드 추가

기존 제안서 필수 항목(구현 범위, 검증 방법)에 다음을 추가:

> ③(schema/migration 파일을 건드리는 경우) **의도된 destructive 오퍼레이션 목록.** 없으면 명시적으로 "없음"이라고 쓴다(공란과 구분하기 위함 — 공란은 "언급 안 함"이지 "없음"이 아니다).

## E. `orca-evaluate` §3/§4 연동

**§3 (diff 리뷰, coding agent 스폰):** code-reviewer 스폰 전에, diff에 포함된 migration 파일에 `migration-lint.py`를 돌린다. 그 JSON 결과 + §1에서 받은 "의도된 destructive 오퍼레이션" 선언 텍스트를 code-reviewer의 task spec에 함께 넣고, 다음을 명시적으로 지시한다:

> "린터가 flag한 항목 중 제안서의 선언에 커버되지 않는 게 있으면 report에 명시하라."

이 비교는 기계적 매칭이 아니라 code-reviewer(강한 reasoning 모델)의 판단이다 — "DROP TABLE old_sessions"라는 flag가 "세션 테이블 정리"라는 선언과 같은 것을 가리키는지는 의미적 판단이 필요하기 때문.

**§4 (리포트 합성):** 기존 3개 ESCALATE 조건에 4번째를 추가:

> - acceptance criteria 자체가 애매해서 판정 불가
> - 구현이 issue 스코프 밖의 것을 건드림
> - agent e2e가 인프라 문제로 판단 불가
> - **destructive-op 린터가 flag했는데 code-reviewer report가 그 항목이 제안서 선언에 커버되지 않는다고 명시함**

네 조건 중 하나라도 해당하면 재시도 없이 즉시 ESCALATE → `orca-workflow` §3 Inspecting(사람 체크포인트)으로 간다. 계약에 명시돼 있거나 애초에 non-destructive면 그대로 PASS 경로 — **모든 스키마 PR이 아니라 의도 확인이 안 되는 경우만** 사람에게 간다.

## F. `agents-policy.md` — 셀프머지 에스컬레이션 문구 개정

기존:

> ...or the change touches schema/migrations/deploy configuration.

변경 후:

> ...or the change touches schema/migrations (unless this repo has a migration-safety gate configured — `MIGRATION_LINT_ENABLED=true` in `scripts/premerge.conf.sh` — in which case `premerge.sh` itself blocks automatically when the linter flags something, so no separate escalation check is needed) or deploy configuration.

**미구성 repo는 기존과 동일하게 무조건 human-gate 유지** — 이 문구 변경이 다른 repo의 게이트를 조용히 약화시키지 않는다(옵트인이므로).

## G. `lifecycle-gate-policy/SKILL.md` 문서 갱신

- "Layer | When | What" 요약 표에 premerge.sh 설명에 짧게 migration-safety 옵트인 언급 추가.
- "Apply to a repository" 절차에 옵트인 단계(선택) 추가: "repo가 SQL 마이그레이션을 쓰면 `MIGRATION_LINT_ENABLED`/`MIGRATION_LINT_REGEX`를 `premerge.conf.sh`에 채우는 것을 검토하되, 실제 적용은 이 skill 문서 변경과 별개로 각 repo에서 사용자의 명시적 요청 시에만 진행한다."

## 테스트

- **`migration-lint.py` 유닛 테스트** (신규, `tests/test_lifecycle_gate_policy.py`에 추가): `GitFixture` 없이 직접 스크립트를 서브프로세스로 호출 — 규칙별로 최소 1개 destructive 케이스(예: `DROP TABLE`, `WHERE` 없는 `DELETE`) + 1개 clean 케이스(예: `CREATE TABLE`, `WHERE` 있는 `DELETE`)를 동적으로 tempdir에 써서 exit code(0/1)와 JSON `flags` 내용을 검증. 멀티라인 `DELETE ... WHERE` 케이스도 포함(라인 단위 스캔이 아님을 검증).
- **`premerge.sh` 통합 테스트** (기존 `GitFixture` 패턴 확장): `MIGRATION_LINT_ENABLED=true` + `MIGRATION_LINT_REGEX` 설정 상태에서 destructive 마이그레이션 파일 커밋 → exit 5 + stderr에 flag 상세 출력 확인. Clean 마이그레이션 커밋 → 다음 스테이지(review requirement)로 진행 확인. `MIGRATION_LINT_ENABLED` 미설정(기본값) 상태에서는 destructive 파일이 있어도 이 스테이지가 no-op임을 확인(기존 동작 무회귀).
- **`audit.py` 회귀**: `CANONICAL` dict에 새 엔트리가 추가된 뒤에도 기존 audit 테스트가 그대로 통과하는지 확인(파일 존재 시 PASS, 부재 시 MISSING).
- **`orca-task-runner`/`orca-evaluate` 문서 레벨 테스트** (`tests/test_orca_skills.py`, grep 기반, 기존 컨벤션): §1 제안서 포맷에 "의도된 destructive 오퍼레이션" 문구 존재, `orca-evaluate` §4에 4번째 ESCALATE 조건 문구 존재 확인. LLM의 실제 의미 판단 자체는 테스트 대상이 아니다(기존 컨벤션과 동일).

## 영향받는 파일

- `skills/lifecycle-gate-policy/assets/scripts/migration-lint.py` (신규)
- `skills/lifecycle-gate-policy/assets/scripts/premerge.sh` (신규 스테이지, PROTECTED_REGEX 갱신, exit code 문서화)
- `skills/lifecycle-gate-policy/assets/scripts/premerge.conf.sh` (신규 옵션 주석)
- `skills/lifecycle-gate-policy/assets/agents-policy.md` (에스컬레이션 문구 개정)
- `skills/lifecycle-gate-policy/scripts/audit.py` (`CANONICAL` dict 추가)
- `skills/lifecycle-gate-policy/SKILL.md` (요약 표 + Apply 절차 갱신)
- `skills/orca-task-runner/SKILL.md` (§1 제안서 필드 추가)
- `skills/orca-evaluate/SKILL.md` (§3 린터 실행+대조 지시, §4 4번째 ESCALATE 조건)
- `tests/test_lifecycle_gate_policy.py` (신규 테스트)
- `tests/test_orca_skills.py` (신규 grep 테스트)

이 repo 밖(medicount 등 실제 opt-in 대상)에는 이 설계로 아무 파일도 변경하지 않는다 — 별도 요청 시 별도 커밋.
