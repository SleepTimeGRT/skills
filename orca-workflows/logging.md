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

**`task-create`가 새 task를 만들지 않은 relay dispatch**: 이런 dispatch에는 진짜 `task_id`가 없는 경우가
있다. `task_id` 필드는 기존 `<task_id-or-omit>` 규칙대로 그대로 생략한다 — 빈 문자열(`""`)이나 issue
#62에서 실제로 관찰된 것 같은 즉석 placeholder 문자열을 넣지 않는다. 대신 extra field로 `"relay":true`를
추가해 "몰라서 생략"과 "relay라서 없음"을 로그에서 구분한다.
`orca-workflow` §2a의 라운드 2+ relay(issue #64로 해소)는 매 라운드 `task-create`로 새 task를 만들므로
현재 이 사이트엔 이 규칙이 적용되지 않는다 — 다만 진짜 task_id가 없는 다른 relay dispatch에는 이 규칙이
그대로 적용된다.

**`outcome`** (`orca-workflow` only — routing result for a task):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
target="$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION|CONTRACT_FINALIZED_BY_GENERATOR|RETRO_DONE|RETRO_FAIL>","retry":<n>}\n' \
  "$(date -u +%FT%TZ)" >> "$target"
chmod 600 "$target"
```

`RETRO_DONE`/`RETRO_FAIL`은 task 라우팅이 아니라 epic retro 결과다 — `orca-workflow` §1d(epic close 직후의
retro 사이트)만 쓴다. `RETRO_DONE` 라인은 per-call-site 추가 필드 규칙에 따라 `filed`/`commented`/`discarded`
정수 카운트를 더해 남기고, `RETRO_FAIL` 라인은 카운트 필드를 생략한다.

`CONTRACT_FINALIZED_BY_GENERATOR`는 계약 협상(orca-task-runner ↔ orca-evaluate) 라운드 한도에 도달해
task-runner(generator) 쪽 결정이 그대로 확정된 경우다 — PASS/FAIL/ESCALATE 어느 것도 아닌 정상 분기이므로,
이 결과에 도달했을 때 outcome 이벤트 자체를 생략하지 말고 반드시 이 값으로 남긴다(observed in practice:
issue #62). 이 라인은 per-call-site 추가 필드 규칙에 따라 `round`(도달한 계약 협상 라운드 수)를 더해
남긴다 — `retry`는 §2 하단의 task-level FAIL 재-dispatch 횟수를 세는 별개 필드이므로, 라운드 수를 `retry`에
넣지 않는다.

**`wave_start`/`wave_end`** (`orca-task-runner` only): same jq schema as today, written to
`waves-$(date -u +%F).jsonl` instead of the fixed `waves.jsonl`.

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
  jq -cn --arg issue "<issue-num>" --arg skill "<skill>" --arg role "<role>" --arg terminal "<handle>" \
    --arg created_at "$(date -u +%FT%TZ)" \
    '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at}' \
    >> "$term_log"
  chmod 600 "$term_log"
fi
```

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
