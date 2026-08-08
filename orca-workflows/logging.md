# Orca Workflows Logging

> verified_at: 2026-07-30

Shared logging procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow`, split out so the three
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

(`orca-workflow`'s three dispatch sites — §2a's task-runner/evaluator round-1 calls and the round-2+
relay — write this event via `orca-workflows/scripts/log_dispatch.sh` rather than hand-copying the
recipe below; issue #68. If you change this schema, update that script's jq call to match.)

**`assign`** (who got dispatched what):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
printf '{"ts":"%s","event":"assign","skill":"<skill>","role":"<role>","issue":"<issue-num>","task_id":"<task_id-or-omit>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<handle>","worktree":"<worktree 경로>"}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

Extra fields (`wave_index`, `subtask_type`, `advisor`, ...) are added per call site exactly as each
`SKILL.md` already does — only the target path changes.

`provider`의 허용값은 `~/.agents/orca-workflows/models/*.md`의 basename을 정본으로 못박는다 — 현재
`claude-code`|`codex`|`agy` 3개(각각 `models/claude-code.md`/`models/codex.md`/`models/agy.md`). `claude`는
**폐기된 별칭(deprecated alias)**이다 — `claude-code`와 같은 provider를 가리키는 값으로 실제 관측됐으나
(issue #69 증거 3), 새로 로그를 남길 때는 항상 `claude-code`로 정규화해 기록한다. 새 provider 문서가
`models/`에 추가되면 그 basename이 곧 새 허용값이다.

**`task-create`가 새 task를 만들지 않은 relay dispatch**: 이런 dispatch에는 진짜 `task_id`가 없는 경우가
있다. `task_id` 필드는 기존 `<task_id-or-omit>` 규칙대로 그대로 생략한다 — 빈 문자열(`""`)이나 issue
#62에서 실제로 관찰된 것 같은 즉석 placeholder 문자열을 넣지 않는다. 대신 extra field로 `"relay":true`를
추가해 "몰라서 생략"과 "relay라서 없음"을 로그에서 구분한다.
`orca-workflow` §2a의 라운드 2+ relay(issue #64로 해소)는 매 라운드 `task-create`로 새 task를 만들므로
현재 이 사이트엔 이 규칙이 적용되지 않는다 — 다만 진짜 task_id가 없는 다른 relay dispatch에는 이 규칙이
그대로 적용된다.

**`outcome`** (`orca-workflow` only — routing result for a task). 값은 두 축으로 나뉜다 — 둘 다 같은
`outcome` JSON 필드에 담기지만 의미가 다르므로 구분해서 읽는다:

- **verdict 축** — task 라우팅 판정: `PASS`|`FAIL`|`ESCALATE`|`GATE_FAIL`|`PREMERGE_FAIL`
- **진행-분기 축** — 판정이 아니라 정상적인 워크플로 상태 전이:
  `NO_DONE_TRANSITION`|`CONTRACT_FINALIZED_BY_GENERATOR`|`CONTRACT_APPROVED_ROUND1`|
  `MANUAL_RECOVERY_COMPLETED`|`PREMERGE_TIMEOUT`|`RETRO_DONE`|`RETRO_FAIL`

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_DONE_TRANSITION|CONTRACT_FINALIZED_BY_GENERATOR|CONTRACT_APPROVED_ROUND1|MANUAL_RECOVERY_COMPLETED|PREMERGE_TIMEOUT|RETRO_DONE|RETRO_FAIL>","retry":<n>}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

**목록에 없는 정상 분기를 만나면** 즉석 문자열을 발명하거나(issue #62에서 최초 관측된 패턴) outcome
이벤트 자체를 생략하지 말고, `sleeptimegrt-skills`에 스키마 구멍 이슈를 연다 — 이 규칙 자체가 새 값이
필요할 때마다 반복되는 드리프트(#62, #69)를 막는 대상이다.

`RETRO_DONE`/`RETRO_FAIL`은 task 라우팅이 아니라 epic retro 결과다 — `orca-workflow` §1d(epic close 직후의
retro 사이트)만 쓴다. `RETRO_DONE` 라인은 per-call-site 추가 필드 규칙에 따라 `filed`/`commented`/`discarded`
정수 카운트를 더해 남기고, `RETRO_FAIL` 라인은 카운트 필드를 생략한다.

`CONTRACT_FINALIZED_BY_GENERATOR`는 계약 협상(orca-task-runner ↔ orca-evaluate) 라운드 한도에 도달해
task-runner(generator) 쪽 결정이 그대로 확정된 경우다 — PASS/FAIL/ESCALATE 어느 것도 아닌 정상 분기이므로,
이 결과에 도달했을 때 outcome 이벤트 자체를 생략하지 말고 반드시 이 값으로 남긴다(observed in practice:
issue #62). 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(도달한 계약 협상 라운드 수)를 더해
남긴다 — `retry`는 §2 하단의 task-level FAIL 재-dispatch 횟수를 세는 별개 필드이므로, 라운드 수를 `retry`에
넣지 않는다.

`CONTRACT_APPROVED_ROUND1`는 contract 협상이 라운드 1에서 곧장 승인되어 재협상 없이 2b(Generate)로
넘어가는 정상 분기다 — PASS/FAIL/ESCALATE 어느 것도 아니므로 outcome 이벤트를 생략하지 말고 이 값으로
남긴다(issue #69 — 이전엔 이 분기가 즉석 문자열을 발명하거나(#498) 이벤트 자체를 생략했다(#499~#501)).
`skills/orca-workflow/SKILL.md` §2a가 이 분기(승인 시점, 2b로 넘어가기 전)에서 기록을 지시한다 — 위
`CONTRACT_FINALIZED_BY_GENERATOR`(라운드 한도 도달) 지시와 대칭. 이 라인은 per-call-site 추가 필드
규칙에 따라 `round=1`을 고정해 남긴다 — 라운드 한도 도달 케이스의 가변 `round`와 값 자체로 구분된다.

`MANUAL_RECOVERY_COMPLETED`는 `worker_done`이 Orca 런타임 문제(재시작·연결 끊김 등)로 유실돼
`self-recovery.md`의 자동 대기/재시도 루프로도 완료 확인이 안 될 때, 코디네이터가 산출물(커밋·아티팩트)을
직접 확인해 수동으로 완료 처리한 **직후** 남긴다 — 복구 절차 도중이 아니라 성공적으로 끝난 시점(issue
#69 증거 2). 이 값도 PASS/FAIL/ESCALATE가 아닌 정상(예외적이지만 처리됨) 분기이므로, 이 값을 기록하라는
전용 지시가 특정 `SKILL.md` 사이트에 따로 없더라도 위 "목록에 없는 정상 분기" 규칙에 따라 생략해선 안
된다 — 이 값 자체가 그 규칙이 커버하는 사례다. 이 라인은 per-call-site 추가 필드 규칙에 따라
`detail`(무엇이 유실됐고 어떻게 확인했는지 한두 문장)을 더해 남긴다 — 이 필드가 없으면 사후에 "정말
복구가 맞았는지" 재구성할 방법이 없다(#69 증거 2가 실제로 이 상세를 `detail`에 남긴 덕에 그 retro가
판독 가능했다).

**`wave_start`/`wave_end`** (`orca-task-runner` only): same jq schema as today, written to
`waves-$(date -u +%F).jsonl` instead of the fixed `waves.jsonl`.

**`self_recovery`** (`orca-task-runner`/`orca-workflow`, per `orca-workflows/self-recovery.md`'s
wait/recovery loop):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/waves-$(date -u +%F).jsonl"   # orca-task-runner
# or: target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"   # orca-workflow
printf '{"ts":"%s","event":"self_recovery","skill":"<skill>","issue":"<issue-num>","task_id":"<task_id>","dispatch_id":"<dispatch_id>","terminal":"<handle>","waited_ms":<n>,"terminal_status":"<alive|dead|stuck_draft>","action_taken":"<resumed_wait|retried_enter|worker_abandon_retry|escalated_spawn_failure>","new_dispatch_id":"<new dispatch_id-or-omit, only when action_taken=worker_abandon_retry>"}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

`orca-task-runner` writes to `waves-<date>.jsonl` (add `wave_index` as an extra field, joinable with
that wave's `wave_start`/`wave_end` records); `orca-workflow` writes to `assignments-<date>.jsonl` (no
`wave_index`). Purpose: `self-recovery.md`'s 3600000ms timeout is an unvalidated starting guess — this
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
find the most recent matching record.)

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

(`orca-workflow`'s three dispatch sites write `meta`+`sent` here via
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

  jq -cn --arg issue "<issue-num>" --arg skill "<skill>" --arg role "<role>" --arg terminal "<handle>" \
    --arg created_at "$(date -u +%FT%TZ)" \
    --argjson skill_version "$sv_json" --argjson orca_workflows_commit "$owc_json" \
    --argjson orca_app_version "$oav_json" \
    '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at,
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
