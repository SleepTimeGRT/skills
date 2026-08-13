# Orca Workflows Logging

> verified_at: 2026-07-30

Shared logging procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow-task`/`orca-workflow-epic`/`orca-workflow`, split out so the
`SKILL.md` files point here instead of each carrying its own copy of the same jq/printf (same precedent as
`spawn-failures.md`). Every path below lives under `~/.local/state/orca-workflows/logs/` — git-untracked
(the `orca-logs-not-git-tracked` convention: this directory is *not* under the `~/.agents/orca-workflows`
symlink target, unlike this file itself).

orca's own task/message state can be lost on a runtime reset (coordinator crash, orchestration restart,
etc.) — these log files are the only durable record of what was assigned, dispatched, and sent/received,
independent of whatever orca's live state currently shows.

## §1. Date-partitioned `assignments`/`waves` logs

`assignments.jsonl` and `waves.jsonl` are not single ever-growing files. Every write and every read-back
targets a UTC-date-suffixed filename, computed inline at the point of use — do not cache the date in a
shell variable across separate command blocks, since a skill's steps can execute far apart in wall-clock
time (long-running tasks can cross a UTC midnight between one log write and the next):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
# assignments-2026-07-30.jsonl, waves-2026-07-30.jsonl, etc.
target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"   # or waves-$(date -u +%F).jsonl
```

Append exactly the same jq/printf record shape used today, to `"$target"`, then `chmod 600 "$target"`.

### Event recipes (unchanged schemas, only the path changed)

(`orca-workflow-task`'s three dispatch sites — §1's task-runner/evaluator round-1 calls and the round-2+
relay — and `orca-workflow-epic`'s task-coordinator site — write this event via `orca-workflows/scripts/log_dispatch.sh` rather than hand-copying the
recipe below; issue #68. If you change this schema, update that script's jq call to match.)

**`repo` 필드(issue #158, 모든 이벤트 공통 필수)**: 이 로그 디렉토리는 여러 저장소가 공유하고
`issue` 번호는 저장소 간에 충돌한다(실측: selah-android retro가 issue="23"으로 sleeptimegrt-skills/
toss-* 레코드를 섞어 읽음). 그래서 `assign`/`outcome`/`self_recovery`/`wave_start`/`wave_end`와 §2의
`meta`는 전부 `repo` 필드를 필수로 싣고, `orca-retro` §1은 `(repo, issue)` 복합 키로 필터한다. 값은
파이프라인 invocation이 입력으로 받은 **대상 repo 식별자 문자열 그대로**(GitHub: `owner/name`, 그 외
트래커는 adapter 문서의 저장소 식별자)를 spec 체인으로 내려받아 쓴다 — writer가 `git remote` 파싱
등으로 재계산하지 않는다(문자열 동일성이 복합 키 필터의 전제). `repo` 필드가 없는 레코드는 이 필드
도입 이전 버전이 남긴 것이며, 복합 키에 매칭되지 않아 retro의 issue-필터 렌즈에서 자연 제외된다.
기계-검증 정본은 `log_dispatch.sh` 세 헬퍼의 `--repo` 필수 검증이다.

**`assign`** (who got dispatched what):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
printf '{"ts":"%s","event":"assign","skill":"<skill>","role":"<role>","issue":"<issue-num>","repo":"<대상 repo>","task_id":"<task_id-or-omit>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<handle>","worktree":"<worktree 경로>"}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

Extra fields (`wave_index`, `subtask_type`, `advisor`, ...) are added per call site exactly as each
`SKILL.md` already does — only the target path changes. `attempt`(정수)는 `orca-workflow-task` §2의
구현 모드 dispatch 전용 extra field다(`log_dispatch`의 `--attempt` 플래그, issue #128) — 그 assign을
CONTRACT_DIR의 `eval-report-a<attempt>.json`과 join 가능하게 만들어, "attempt k가 정말
orca-task-runner에 dispatch됐는가"를 로그만으로 판정할 수 있게 한다. §1의 제안서 모드 dispatch는
구현 attempt가 아니므로 넘기지 않는다.

`provider`의 허용값은 `~/.agents/orca-workflows/models/*.md`의 basename을 정본으로 못박는다 — 현재
`claude-code`|`codex`|`agy` 3개(각각 `models/claude-code.md`/`models/codex.md`/`models/agy.md`). `claude`는
**폐기된 별칭(deprecated alias)**이다 — `claude-code`와 같은 provider를 가리키는 값으로 실제 관측됐으나
(issue #69 증거 3), 새로 로그를 남길 때는 항상 `claude-code`로 정규화해 기록한다. 새 provider 문서가
`models/`에 추가되면 그 basename이 곧 새 허용값이다.

**`task-create`가 새 task를 만들지 않은 relay dispatch**: 이런 dispatch에는 진짜 `task_id`가 없는 경우가
있다. `task_id` 필드는 기존 `<task_id-or-omit>` 규칙대로 그대로 생략한다 — 빈 문자열(`""`)이나 issue
#62에서 실제로 관찰된 것 같은 즉석 placeholder 문자열을 넣지 않는다. 대신 extra field로 `"relay":true`를
추가해 "몰라서 생략"과 "relay라서 없음"을 로그에서 구분한다.
`orca-workflow-task` §1의 라운드 2+ relay(issue #64로 해소)는 매 라운드 `task-create`로 새 task를 만들므로
현재 이 사이트엔 이 규칙이 적용되지 않는다 — 다만 진짜 task_id가 없는 다른 relay dispatch에는 이 규칙이
그대로 적용된다.

**`outcome`** (coordinator 스킬 전용 — task 라우팅 결과는 `orca-workflow-task`, parked 라우팅 결과
(`escalation_parked`)는 `orca-workflow-epic`, `RETRO_*`는 `orca-workflow`). 값은 두 축으로 나뉜다 — 둘 다 같은
`outcome` JSON 필드에 담기지만 의미가 다르므로 구분해서 읽는다:

- **verdict 축** — task 라우팅 판정: `PASS`|`FAIL`|`ESCALATE`|`GATE_FAIL`|`CONTRACT_ESCALATE`|`CI_GATE_FAIL`
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED`|`CONTRACT_SCHEMA_STALE`|
  `MANUAL_RECOVERY_COMPLETED`|`CI_GATE_TIMEOUT`|`MERGE_CONFLICT`|`RETRO_DONE`|`RETRO_FAIL`|
  `escalation_parked`|`skipped`|`unblocked_requeue`|`NO_ACCEPTANCE_CRITERIA`|`UNMAPPED_BRANCH`

**기계-검증 정본은 `orca-workflows/scripts/log_dispatch.sh`의 `log_outcome()`(enum 변수
`LOG_OUTCOME_ENUM`)이다** — 위 목록은 사람이 읽는 미러이고, 둘이 어긋나면 스크립트가 정본이다. 모든
outcome write는 이 헬퍼를 통해야 하며, `"event":"outcome"`을 raw printf/jq로 직접 조립하는 것은
금지다(#105/#116/#138 — 손으로 베낀 printf가 enum 즉석 발명 5회와 고정 필드 누락의 공통 원인이었고,
`assign` 이벤트가 issue #68에서 같은 방식으로 이미 해결된 전례를 그대로 확장한 것). 목록에 없는 값을
넘기면 헬퍼가 그 자리에서 `outcome=UNMAPPED_BRANCH`+`raw_outcome`+`schema_gap_issue`로 강제 대체하고
stderr 경고만 남긴다(파이프라인은 실패시키지 않는다).

```bash
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
log_outcome --skill <skill> --issue <issue-num> --repo <대상 repo> --outcome <위 두 축의 값 중 하나> --retry <n>
# per-call-site 추가 필드(해당할 때만): --round <n> / --filed <n> --commented <n> --discarded <n> /
#   --detail <text> / --blocked-by <issue-num>. 값이 빈 문자열이면 필드 자체가 생략된다 — 빈 문자열
#   조건부 필드 금지(#127)를 헬퍼가 강제한다.
# UNMAPPED_BRANCH를 직접 남길 때: --outcome UNMAPPED_BRANCH --raw-outcome <관측 문자열> \
#   --schema-gap-issue <추적 이슈 slug>
```

`skill`은 기록 주체다 — task 라우팅 outcome은 `orca-workflow-task`, parked 라우팅 결과(`escalation_parked`)는
`orca-workflow-epic`, `RETRO_*`는 `orca-workflow`.

**목록에 없는 정상 분기를 만나면** 즉석 문자열을 발명하지 말고(issue #62에서 최초 관측된 패턴),
`sleeptimegrt-skills`에 스키마 구멍 이슈를 열고, 같은 write에서 outcome 이벤트를
`outcome=UNMAPPED_BRANCH`, `raw_outcome=<실제 관측 문자열>`, `schema_gap_issue=<추적 이슈 slug>`로
남긴다(outcome 이벤트 자체를 생략하지 않는다) — 이 규칙 자체가 새 값이 필요할 때마다 반복되는
드리프트(#62, #69, #86, #105, #138)를 막는 대상이며, `log_outcome()`이 실행 시점에 자동으로 강제한다
(이슈를 아직 못 열었으면 `schema_gap_issue`는 `unfiled`로 남는다 — 헬퍼 기본값. 사후에 이슈를 열어
추적을 붙인다).

`RETRO_DONE`/`RETRO_FAIL`은 task 라우팅이 아니라 retro 결과다 — `orca-workflow` §2(invocation 종료 시의
retro 사이트)만 쓴다. `RETRO_DONE` 라인은 per-call-site 추가 필드 규칙에 따라 `filed`/`commented`/`discarded`
정수 카운트를 더해 남기고, `RETRO_FAIL` 라인은 카운트 필드를 생략한다.

`CONTRACT_FINALIZED_BY_GENERATOR`는 계약 협상(orca-task-runner ↔ orca-evaluate) 라운드 한도에 도달해
task-runner(generator) 쪽 결정이 그대로 확정된 경우다(라운드 한도 도달이 곧 이 값은 아니다 —
`ac_fidelity` 이견이 남았으면 아래 `CONTRACT_ESCALATE`로 간다) — PASS/FAIL/ESCALATE 어느 것도 아닌 정상 분기이므로,
이 결과에 도달했을 때 outcome 이벤트 자체를 생략하지 말고 반드시 이 값으로 남긴다(observed in practice:
issue #62). 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(도달한 계약 협상 라운드 수)를 더해
남긴다 — `retry`는 `orca-workflow-task` §4의 task-level FAIL 재-dispatch 횟수를 세는 별개 필드이므로, 라운드 수를 `retry`에
넣지 않는다.

`CONTRACT_ESCALATE`는 contract 협상이 라운드 한도에 도달했고 `override.json`의 `unresolved_reasons`에
`ac_fidelity` target이 남아, 코드 생성(§2 Generate) 없이 곧장 §5로 보낸 경우다(`orca-workflow-task` §1의
기계적 분기 — `contract-schema.md`의 override 라우팅 규칙 참고). 같은 라운드-한도 지점의 다른 갈래인
`CONTRACT_FINALIZED_BY_GENERATOR`(`plan_coverage`만 남은 경우, 진행)와 상호 배타다. 이 라인은
per-call-site 추가 필드 규칙에 따라 `round`(도달한 라운드 수)를 더해 남긴다.

`CONTRACT_APPROVED`는 contract 협상이 (몇 라운드에서 승인되든) 승인되어 재협상 없이 §2(Generate)로
넘어가는 정상 분기다 — PASS/FAIL/ESCALATE 어느 것도 아니므로 outcome 이벤트를 생략하지 말고 이 값으로
남긴다(issue #69, #86 — 이전엔 이 분기가 즉석 문자열을 발명하거나(#498) 이벤트 자체를 생략했다(#499~#501),
또는 `round`를 1로 못박은 라운드-번호-붙박이 값을 즉석 발명했다(#513 세션, #86)). `skills/orca-workflow-task/SKILL.md`
§1이 이 분기(승인 시점, §2로 넘어가기 전)에서 기록을 지시한다 — 위 `CONTRACT_FINALIZED_BY_GENERATOR`
(라운드 한도 도달) 지시와 대칭. 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(승인된 라운드 수,
가변)를 더해 남긴다 — `CONTRACT_FINALIZED_BY_GENERATOR`/`CONTRACT_ESCALATE`와 같은 필드 구성이며, 값
이름(`CONTRACT_APPROVED`) 자체로 구분된다.

`CONTRACT_SCHEMA_STALE`는 `override.json`은 있는데 `proposal-r3.json`이 없고, `override.json`의
mtime이 그 요구사항 도입 시점(commit 79b7c3b, 2026-08-12T09:44:57+09:00)보다 이전인 경우다(issue
#160) — `orca-workflow-task` §1의 기계적 분기든 `contract_resume.sh`의 크래시-재개 미러든 같은
값이다. `CONTRACT_ESCALATE`(기록 계약 위반)와 상호 배타다: 위반이 아니라 그 요구사항 자체가 그
세션이 끝난 뒤에 생겼다는 뜻이므로, 사람에게 "generator가 규칙을 어겼다"고 잘못 전달하지 않기 위해
별도 값으로 분리한다. 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(도달한 라운드 수, 이
게이트 한정 항상 2)와 `detail`(override.json mtime과 게이트 도입 시각을 사람이 읽을 수 있는
형태로)을 더해 남긴다.

`MANUAL_RECOVERY_COMPLETED`는 `worker_done`이 Orca 런타임 문제(재시작·연결 끊김 등)로 유실돼
`self-recovery.md`의 자동 대기/재시도 루프로도 완료 확인이 안 될 때, 코디네이터가 산출물(커밋·아티팩트)을
직접 확인해 수동으로 완료 처리한 **직후** 남긴다 — 복구 절차 도중이 아니라 성공적으로 끝난 시점(issue
#69 증거 2). 이 값도 PASS/FAIL/ESCALATE가 아닌 정상(예외적이지만 처리됨) 분기이므로, 이 값을 기록하라는
전용 지시가 특정 `SKILL.md` 사이트에 따로 없더라도 위 "목록에 없는 정상 분기" 규칙에 따라 생략해선 안
된다 — 이 값 자체가 그 규칙이 커버하는 사례다. 이 라인은 per-call-site 추가 필드 규칙에 따라
`detail`(무엇이 유실됐고 어떻게 확인했는지 한두 문장)을 더해 남긴다 — 이 필드가 없으면 사후에 "정말
복구가 맞았는지" 재구성할 방법이 없다(#69 증거 2가 실제로 이 상세를 `detail`에 남긴 덕에 그 retro가
판독 가능했다).

`skipped`는 `orca-workflow-epic`이 afk-escalation으로 park된 선행 task의 dependent를 건너뛸 때(또는
hitl 전체-중단 선택으로 남은 큐를 건너뛸 때) dependent issue별로 남기는 정상 진행-분기다 — issue #138에서
즉석 발명으로 최초 관측된 뒤 정식 등재. 이 값에는 조건부 필드 `blocked_by`(막은 선행 issue 번호)가
**필수**이며, `blocked_by`는 `outcome=skipped` 또는 `outcome=unblocked_requeue`일 때만 쓴다(다른
outcome에 실리면 헬퍼가 경고 후 버린다).

`unblocked_requeue`는 `skipped`의 짝이다 — park됐던 선행 issue가 나중에 PASS/merge로 풀려,
그것 때문에 `skipped`로 건너뛰었던 dependent를 `orca-workflow-epic`이 큐에 다시 올릴 때 남기는
정상 진행-분기다(issue #165, studio-hevv/selah-android issue #23에서 즉석 문자열 `raw_outcome:
"unblocked_requeue"`로 최초 관측된 뒤 정식 등재). `blocked_by`에는 그때 자신을 막았던 바로 그
선행 issue 번호를 그대로 남긴다 — `skipped` 레코드와 값이 같아야 두 이벤트가 같은 (repo, issue,
blocked_by) 조합으로 짝지어 읽힌다.

`NO_ACCEPTANCE_CRITERIA`는 issue 본문이 Acceptance Criteria를 초안할 만큼 구체적이지 않아 진행 불가로
판정된 정상 분기다(issue-drain/AC 초안 단계) — issue #105에서 즉석 발명으로 최초 관측된 뒤, 그 이슈의
수정 방향대로 정식 등재.

**`wave_start`/`wave_end`** (`orca-task-runner` only): same jq schema as today plus the required
`repo` field (issue #158, 위 공통 규칙), written to `waves-$(date -u +%F).jsonl` instead of the
fixed `waves.jsonl`.

**`self_recovery`** (`orca-task-runner`/`orca-workflow-task`/`orca-workflow-epic`, per `orca-workflows/self-recovery.md`'s
wait/recovery loop):

```bash
source ~/.agents/orca-workflows/scripts/log_dispatch.sh
log_self_recovery --skill <skill> --issue <issue-num> --repo <대상 repo> --task-id <task_id> --dispatch-id <dispatch_id> \
  --terminal <handle> --waited-ms <n> \
  --terminal-status <alive|dead|stuck_draft|n/a> \
  --action-taken <resumed_wait|retried_enter|worker_abandon_retry|task_recreate_retry|escalated_spawn_failure|none_decision_gate_self_timed_out_worker_proceeded|UNMAPPED_BRANCH>
# 조건부 필드(해당할 때만): --new-dispatch-id <id> (action_taken=worker_abandon_retry|task_recreate_retry
#   전용), --raw-action <관측 문자열>/--schema-gap-issue <slug> (action_taken=UNMAPPED_BRANCH 전용),
#   --wave-index <n> (orca-task-runner 전용). 값이 빈 문자열이면 필드 자체가 생략된다(#127).
```

`--terminal-status n/a`(issue #183)는 worker-liveness 프로브를 아예 돌리지 않은 escalation 전용이다 —
`self-recovery.md`의 retry-budget-소진, transport-stall-budget-소진 분기가 여기 해당한다.
alive/dead/stuck_draft 셋 다 "워커를 관측했더니 이랬다"는 뜻이라, 프로브를 안 돌린 상황에 셋 중
아무거나 강제로 붙이면 실제로 하지 않은 관측을 한 것처럼 기록하는 셈이 된다. 이 4번째 값을 추가하기
전에는(issue #183, 2026-08-13까지) 헬퍼가 exit 64로 거부해 retry-budget-소진 분기의 self_recovery
이벤트가 조용히 하나도 안 남았다. transport-stall-budget-소진 분기는 별도 원인이 하나 더 있었다 —
공유 `log_self_recovery` 호출부가 `elif` 분기 안에만 스코프되어 있어 이 분기에서는 호출 자체가 아예
일어나지 않았다(issue #186, 2026-08-14 수정). 두 원인이 모두 고쳐진 지금은 두 분기 다 이벤트가
정상적으로 기록된다.

**`action_taken`의 기계-검증 정본도 같은 스크립트의 `log_self_recovery()`(enum 변수
`LOG_SELF_RECOVERY_ACTION_ENUM`)다** — `"event":"self_recovery"` raw printf 금지. enum 밖 값(오타 포함 —
issue #127의 `resume_wait`처럼)은 헬퍼가 `action_taken=UNMAPPED_BRANCH`+`raw_action`+`schema_gap_issue`로
강제 대체한다.

대상 파일은 헬퍼가 `--skill` 값으로 고른다: `orca-task-runner` → `waves-<date>.jsonl` (`--wave-index`를
extra field로 실어 그 wave의 `wave_start`/`wave_end` 레코드와 join); `orca-workflow-task`/`orca-workflow-epic` →
`assignments-<date>.jsonl` (`wave_index` 없음). Purpose: `self-recovery.md`'s 3600000ms timeout is an unvalidated starting guess — this
log is what lets a future session re-derive a real distribution instead of guessing again, and lets
`orca-retro`'s "repeated FAIL attributable to skill prose" lens notice if a particular signature
recurs.

### Reading across dates

Any read-back that might need history from before this run — most importantly `orca-task-runner`'s §0
orphan-wave check, and its §5 `wave_end` lookup of the matching `wave_start` (a wave can straddle a UTC
midnight) — must glob every dated file, not just today's:

```bash
find "$HOME/.local/state/orca-workflows/logs" -name 'waves-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null | jq -s '...'
```

(`cat waves-*.jsonl` breaks under zsh when no dated file exists yet — the glob's `nomatch` fires during
expansion, before `2>/dev/null` can suppress it. `find | sort | xargs cat` is portable across bash/zsh and
the `sort` keeps dated files in chronological order, which matters wherever the caller does `tail -1` to
find the most recent matching record. Caveat found 2026-08-14 (issue #188): plain `xargs` word-splits on
whitespace, so this exact form still breaks if any path component under `$HOME` contains a space — use the
NUL-delimited form (`find ... -print0 | sort -z | xargs -0 cat`) wherever that's possible. This page and the
call sites that copied it (`skills/orca-retro/SKILL.md`, `skills/orca-workflow-task/SKILL.md`'s Generate
audit gate) still use the plain form as of this note — #188 tracks migrating them.)

**`assignments*.jsonl` has one extra wrinkle `waves*.jsonl` doesn't**: a pre-date-partition
`assignments.jsonl` (no date suffix) exists from before this scheme, holds only records older than every
dated file, and is kept around on purpose — old records live only there. Plain `find -name 'assignments*.jsonl'
| sort` puts it **last**, not first: ASCII `.` (0x2e) sorts after `-` (0x2d), so `assignments.jsonl` sorts
after `assignments-2026-08-02.jsonl`. A `tail -1` over that output picks the newest line from the *oldest*
file whenever the query's real most-recent match happens to be undated-vs-dated adjacent — a timestamp
inversion, not just a cosmetic ordering issue (observed in practice: issue #55). Read the legacy file first,
explicitly, then the sorted dated files — do not rely on `sort` to place it correctly:

```bash
{ [ -f "$HOME/.local/state/orca-workflows/logs/assignments.jsonl" ] && \
    cat "$HOME/.local/state/orca-workflows/logs/assignments.jsonl"; \
  find "$HOME/.local/state/orca-workflows/logs" -name 'assignments-*.jsonl' 2>/dev/null | sort | xargs cat 2>/dev/null; \
} 2>/dev/null | jq -s '...'
```

`waves*.jsonl` has no undated legacy file (it was introduced already date-partitioned), so the plain
glob+sort above remains correct for it unchanged.

Retention: unbounded. No automatic deletion of old dated files.

## §2. `term-<handle>.jsonl` — per-terminal prompt/response transcript

One file per Orca terminal handle, created the first time that terminal is dispatched to via
`orca orchestration dispatch --task <id> --to <handle> --inject`, appended to until the terminal closes.
Line 1 is always the `meta` record; every line after that is one `sent` or `recv` event. This file fully
replaces `orca-task-runner`'s old close-time `term-<handle>.json` single-snapshot file — do not write both.

(`orca-workflow-task`'s three dispatch sites and `orca-workflow-epic`'s task-coordinator site write `meta`+`sent` here via
`orca-workflows/scripts/log_dispatch.sh` — the same recipe as the `meta`/`sent` sections below,
folded into one function call alongside the §1 `assign` write; issue #68. `recv` is never written by
that helper — see the recv carve-out below.)

**Ownership**: the skill that spawns a terminal owns and is the sole writer of that terminal's
`term-<handle>.jsonl` — a skill running *inside* a spawned terminal never writes its own handle's file.

```bash
term_log="$HOME/.local/state/orca-workflows/logs/term-<handle>.jsonl"
install -d -m 700 ~/.local/state/orca-workflows/logs
```

### `meta` — write once, first line in the file, right before or right after the first `dispatch --inject` to this handle

**Idempotent by construction** — a dispatch retry against the same handle (spawn-failure retry, manual
`worker_done`-loss recovery) can re-enter the same code block and re-run this write. Guard on line 1 already
existing before appending, so retries never produce a second `meta` line (observed in practice without this
guard: issue #59):

```bash
if [ ! -s "$term_log" ] || ! head -1 "$term_log" | jq -e '.type == "meta"' >/dev/null 2>&1; then
  version_file="$HOME/.agents/skills/<skill>/.installed-version.json"
  sv_json="null"
  [ -f "$version_file" ] && sv_json="$(jq -c '{version, commit}' "$version_file" 2>/dev/null || true)"
  [ -z "$sv_json" ] && sv_json="null"

  owc_raw="$(git -C "$HOME/.agents/orca-workflows" rev-parse HEAD 2>/dev/null || true)"
  owc_json="null"
  [ -n "$owc_raw" ] && owc_json="$(printf '%s' "$owc_raw" | jq -R .)"

  oav_raw="$(orca status --json 2>/dev/null | jq -r '.result.runtime.appVersion // empty' 2>/dev/null || true)"
  oav_json="null"
  [ -n "$oav_raw" ] && oav_json="$(printf '%s' "$oav_raw" | jq -R .)"

  jq -cn --arg issue "<issue-num>" --arg repo "<대상 repo>" --arg skill "<skill>" --arg role "<role>" \
    --arg terminal "<handle>" \
    --arg created_at "$(date -u +%FT%TZ)" \
    --argjson skill_version "$sv_json" --argjson orca_workflows_commit "$owc_json" \
    --argjson orca_app_version "$oav_json" \
    '{type:"meta", issue:$issue, repo:$repo, skill:$skill, role:$role, terminal:$terminal,
      created_at:$created_at,
      skill_version:$skill_version, orca_workflows_commit:$orca_workflows_commit,
      orca_app_version:$orca_app_version}' \
    >> "$term_log"
  chmod 600 "$term_log"
fi
```

`skill_version`은 그 순간 실제 **배포(commit-pin)**된 버전(`~/.agents/skills/<skill>/.installed-version.json`),
`orca_workflows_commit`은 orca-workflows가 symlink-tracks-main이라 항상 "그 순간의" 레포 HEAD, `orca_app_version`은
Orca 앱 자체 버전(#42류 앱-기인 버그 추적용)이다. 셋 다 best-effort — 조회 실패는 `null`로만 남기고 meta
기록 자체를 막지 않는다.

### `sent` — write right after `dispatch --inject`, reusing the exact text already passed to that task's `task-create --spec` (do not re-fetch it via `task-list`)

```bash
# $spec_text must be the same string used for `orca orchestration task-create --spec "$spec_text"`
jq -cn --arg ts "$(date -u +%FT%TZ)" --arg content "$spec_text" \
  '{ts:$ts, direction:"sent", content:$content}' >> "$term_log"
```

(No `cursor_before` field on `sent` — cursor bookkeeping only applies to `recv`, since that's what
`orca terminal read --cursor` consumes.)

### `recv` — write only at a point this skill *already* reads that terminal's output today

Do not add a new `orca terminal read` call purely to produce a `recv` log line at a site that has no
existing read. If a `dispatch --inject` site never reads the terminal back (result arrives via a different
channel — e.g. a relayed judgment, or a report file read directly), it logs `sent` only. Each `SKILL.md`
call site states explicitly which case it is.

**Carve-out:** the post-`dispatch --inject` liveness probe in `dispatch-verify.md` (a bounded, opaque tail
equality comparison, never inspected for content) does not count as "already reads that terminal's output"
for this rule — a site whose only read of a terminal is that probe still logs `sent` only, not `recv`.

For a terminal's **first** read (no prior cursor for this handle), omit `--cursor` entirely — this matches
what `orca-task-runner` §5's close block does (`read_json="$(orca terminal read --terminal <handle> --json)"`,
right before `orca terminal close`) and avoids relying on unverified behavior for `--cursor 0`:

```bash
read_json="$(orca terminal read --terminal <handle> --json)"
content="$(printf '%s' "$read_json" | jq -r '.result.terminal.tail | join("\n")')"
next_cursor="$(printf '%s' "$read_json" | jq -r '.result.terminal.nextCursor')"
jq -cn --arg ts "$(date -u +%FT%TZ)" --arg content "$content" --argjson cursor_after "$next_cursor" \
  '{ts:$ts, direction:"recv", content:$content, cursor_before:null, cursor_after:$cursor_after, dropped:false}' \
  >> "$term_log"
```

For a **subsequent** read on a terminal that already has a `cursor_after` from an earlier `recv` in the
same file (multi-round terminals — retries, decision-gate replies), pass that value as `--cursor` to get
only the new output, and detect drops by comparing it against the response's `oldestCursor`:

```bash
prev_cursor="<cursor_after from this terminal's last recv line>"
read_json="$(orca terminal read --terminal <handle> --cursor "$prev_cursor" --json)"
content="$(printf '%s' "$read_json" | jq -r '.result.terminal.tail | join("\n")')"
next_cursor="$(printf '%s' "$read_json" | jq -r '.result.terminal.nextCursor')"
oldest_cursor="$(printf '%s' "$read_json" | jq -r '.result.terminal.oldestCursor')"
dropped=false
[ "$prev_cursor" -lt "$oldest_cursor" ] 2>/dev/null && dropped=true
jq -cn --arg ts "$(date -u +%FT%TZ)" --arg content "$content" --argjson cursor_before "$prev_cursor" \
  --argjson cursor_after "$next_cursor" --argjson dropped "$dropped" \
  '{ts:$ts, direction:"recv", content:$content, cursor_before:$cursor_before, cursor_after:$cursor_after, dropped:$dropped}' \
  >> "$term_log"
```

`--cursor`'s incremental-read behavior (only new output since the given cursor) and the `.result.terminal.*`
JSON shape (`tail`, `nextCursor`, `oldestCursor`) are confirmed via `orca terminal read --help` and a real
captured response in this environment — not assumed.

### Edge cases

- A `sent` with no following `recv` (terminal died, timed out, or this site is `sent`-only by design) is
  left as-is — it is itself useful diagnostic signal (last content sent, and when), not an error to paper
  over.
- `dropped:true` is recorded and logging continues normally — no retry or reconstruction of the missing
  span.

## §3. Run-id sidecars (`run-<project-slug>-<issue>-<skill>.txt`)

Like the logs in §1 and the transcripts in §2, these sidecar files live under
`~/.local/state/orca-workflows/logs/` and are git-untracked.

Naming: `run-<project-slug>-<issue-num-or-root-num>-<skill-dir-name>.txt`, where `<project-slug>` is
contract-schema.md's `<project-slug>` (대상 repo의 디렉토리명 — issue #159: issue 번호는 저장소 간에
충돌하므로, slug 없이는 다른 저장소의 같은 번호 issue를 병렬로 돌릴 때 한쪽이 다른 쪽의 RUN_ID를
덮어써 이후 relay가 남의 Run으로 `worker-start`를 낸다), and `<skill-dir-name>` is the directory name
of the skill writing the sidecar, exactly as it appears under `skills/` — one of `orca-workflow-task`,
`orca-task-runner`, or `orca-workflow-epic`. 과거 컨벤션(`run-<issue>-<skill>.txt`)의 잔존 파일은
마이그레이션하지 않는다 — 사이드카는 실행-스코프 임시값이라 새 실행이 새 이름으로 새로 쓴다.

Each skill writes and reads only its own sidecar; it does not read a sidecar written by another skill.

Same `install -d -m 700`/`chmod 600` convention as §1.
