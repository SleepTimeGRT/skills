# Orca Workflows Log Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Date-partition `assignments.jsonl`/`waves.jsonl` and add a per-terminal `term-<handle>.jsonl` prompt/response transcript, so orca-\* debugging doesn't depend on one ever-growing file or a close-time-only snapshot.

**Architecture:** A new git-tracked reference doc, `orca-workflows/logging.md`, defines every log recipe (date-partitioned path pattern, `assign`/`outcome`/`wave_start`/`wave_end` events, `term-<handle>.jsonl` meta/sent/recv events) in one place, following the same pointer-doc precedent as `orca-workflows/spawn-failures.md`. The three `SKILL.md` files that currently inline this logic (`orca-task-runner`, `orca-evaluate`, `orca-workflow`) are edited to point at that doc instead of repeating the jq/printf blocks, and to add `sent`/`recv` logging at their `dispatch --inject` sites.

**Tech Stack:** Markdown (`SKILL.md`, reference docs), `bash`/`jq`, the `orca` CLI (verified installed at `/usr/local/bin/orca` in this environment).

## Global Constraints

- Log directory stays `~/.local/state/orca-workflows/logs/` — git-untracked (see `orca-logs-not-git-tracked` convention). Do not move any log file under `~/.agents/orca-workflows/` or anywhere inside this repo.
- Every write keeps `install -d -m 700 ~/.local/state/orca-workflows/logs` and `chmod 600` on the written file, matching current behavior exactly.
- `orca-workflows/` is not deployed via `scripts/deploy-skills.sh` — edits there go live on merge to `main` (symlink-tracks-main convention). `skills/*/SKILL.md` changes similarly need no separate deploy step beyond the normal git workflow for this task.
- Do not add retry/backfill/reconstruction logic for dropped or missing log lines — per the approved spec, missing `recv` after a `sent`, or a `dropped:true` cursor gap, is left as diagnostic signal, not auto-corrected.
- Do not add a `terminal read` call at any `dispatch --inject` site that doesn't already read that terminal's output today — `recv` logging only extends existing read points, never introduces a new one (see Task 3/4 notes on why `orca-evaluate` §1/§3 and all of `orca-workflow`'s sites are `sent`-only). This is a correction to the approved spec's blanket "3/2 sites get sent+recv" framing, found by reading every call site's actual bash (spec was written from a grep-level pass); flagged for the user in the final summary.
- Field names for `orca terminal read --json` output (`.result.terminal.tail`, `.nextCursor`, `.oldestCursor`) are taken from a real captured response in this environment (`~/.local/state/orca-workflows/logs/term-term_04f08341-*.json`), not guessed.

---

## File Structure

- Create: `orca-workflows/logging.md` — shared logging reference (git-tracked)
- Modify: `skills/orca-task-runner/SKILL.md` — date-partition assign/wave logs, orphan-check glob, add term-log sent+recv at the one `dispatch --inject` site, replace close-time snapshot
- Modify: `skills/orca-evaluate/SKILL.md` — date-partition 3 assign-log sites, add term-log sent-only at 2 `dispatch --inject` sites (contract-review, code-review)
- Modify: `skills/orca-workflow/SKILL.md` — date-partition 4 assign/outcome-log sites, add term-log sent-only at 2 `dispatch --inject` sites (task-runner, evaluate)

---

### Task 1: Create `orca-workflows/logging.md`

**Files:**
- Create: `orca-workflows/logging.md`

**Interfaces:**
- Produces: the canonical path pattern (`assignments-<UTC-date>.jsonl`, `waves-<UTC-date>.jsonl`, `term-<handle>.jsonl`) and event schemas (`assign`, `outcome`, `wave_start`, `wave_end`, `meta`, `sent`, `recv`) that Tasks 2-4 point to instead of duplicating.

- [ ] **Step 1: Write `orca-workflows/logging.md`**

```markdown
# Orca Workflows Logging

> verified_at: 2026-07-30

Shared logging procedure for `orca-task-runner`/`orca-evaluate`/`orca-workflow`, split out so the three
`SKILL.md` files point here instead of each carrying its own copy of the same jq/printf (same precedent as
`spawn-failures.md`). Every path below lives under `~/.local/state/orca-workflows/logs/` — git-untracked
(the `orca-logs-not-git-tracked` convention: this directory is *not* under the `~/.agents/orca-workflows`
symlink target; only this file, `spawn-failures.md`, `model-selection.md`, and `models/*.md` are).

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
printf '{"ts":"%s","event":"assign","skill":"<skill>","role":"<role>","issue":"<issue-num>","task_id":"<task_id-or-omit>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<handle>","worktree":"<worktree 경로>"}\n' \
  "$(date -u +%FT%TZ)" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
```

Extra fields (`wave_index`, `subtask_type`, `advisor`, ...) are added per call site exactly as each
`SKILL.md` already does — only the target path changes.

**`outcome`** (`orca-workflow` only — routing result for a task):

```bash
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION>","retry":<n>}\n' \
  "$(date -u +%FT%TZ)" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
```

**`wave_start`/`wave_end`** (`orca-task-runner` only): same jq schema as today, written to
`waves-$(date -u +%F).jsonl` instead of the fixed `waves.jsonl`.

### Reading across dates

Any read-back that might need history from before this run — most importantly `orca-task-runner`'s §0
orphan-wave check, and its §5 `wave_end` lookup of the matching `wave_start` (a wave can straddle a UTC
midnight) — must glob every dated file, not just today's:

```bash
cat "$HOME"/.local/state/orca-workflows/logs/waves-*.jsonl 2>/dev/null | jq -s '...'
```

Retention: unbounded. No automatic deletion of old dated files.

## §2. `term-<handle>.jsonl` — per-terminal prompt/response transcript

One file per Orca terminal handle, created the first time that terminal is dispatched to via
`orca orchestration dispatch --task <id> --to <handle> --inject`, appended to until the terminal closes.
Line 1 is always the `meta` record; every line after that is one `sent` or `recv` event. This file fully
replaces `orca-task-runner`'s old close-time `term-<handle>.json` single-snapshot file — do not write both.

```bash
term_log="$HOME/.local/state/orca-workflows/logs/term-<handle>.jsonl"
install -d -m 700 ~/.local/state/orca-workflows/logs
```

### `meta` — write once, first line in the file, right before or right after the first `dispatch --inject` to this handle

```bash
jq -cn --arg issue "<issue-num>" --arg skill "<skill>" --arg role "<role>" --arg terminal "<handle>" \
  --arg created_at "$(date -u +%FT%TZ)" \
  '{type:"meta", issue:$issue, skill:$skill, role:$role, terminal:$terminal, created_at:$created_at}' \
  >> "$term_log"
chmod 600 "$term_log"
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

For a terminal's **first** read (no prior cursor for this handle), omit `--cursor` entirely — this matches
what `orca-task-runner` already does today (`orca terminal read --terminal <handle> --json`) and avoids
relying on unverified behavior for `--cursor 0`:

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
```

- [ ] **Step 2: Verify the file was written correctly**

Run: `grep -c '^```bash' orca-workflows/logging.md` — expect at least 6 (one per bash block above). Run:
`grep -n 'TBD\|TODO' orca-workflows/logging.md` — expect no output.

- [ ] **Step 3: Commit**

```bash
git add orca-workflows/logging.md
git commit -m "$(cat <<'EOF'
docs(orca-workflows): add shared logging.md reference

Date-partitioned assignments/waves paths and the new
term-<handle>.jsonl prompt/response transcript recipe, factored
out so orca-task-runner/orca-evaluate/orca-workflow point here
instead of each inlining the same jq/printf blocks.
EOF
)"
```

---

### Task 2: Update `skills/orca-task-runner/SKILL.md`

**Files:**
- Modify: `skills/orca-task-runner/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/logging.md` §1 (date-partitioned path pattern, `assign`/`wave_start`/`wave_end`
  recipes, cross-date glob read), §2 (`meta`/`sent`/`recv` recipes)
- Produces: `term-<impl_handle>.jsonl` per subtask terminal, containing exactly one `sent` (the dispatch
  spec) + one `recv` (the pre-close read) round — this is the file Task 5's validation sweep checks for.

This is the only one of the three skills whose single `dispatch --inject` site gets full `sent`+`recv`
logging, because it already reads the terminal's output once, right before close (`SKILL.md:129` today) —
that existing read becomes the `recv` event instead of a standalone `.json` snapshot.

- [ ] **Step 1: Fix the §0 orphan-check to glob across dated `waves-*.jsonl` files**

Old (`skills/orca-task-runner/SKILL.md:25-32`):

```bash
  jq -s --arg issue "<issue-num>" '
    [.[] | select(.issue == $issue)] as $rows
    | ($rows | map(select(.event == "wave_start") | .wave_index)) as $starts
    | ($rows | map(select(.event == "wave_end") | .wave_index)) as $ends
    | $starts - $ends
  ' ~/.local/state/orca-workflows/logs/waves.jsonl 2>/dev/null
```

New:

```bash
  cat ~/.local/state/orca-workflows/logs/waves-*.jsonl 2>/dev/null | jq -s --arg issue "<issue-num>" '
    [.[] | select(.issue == $issue)] as $rows
    | ($rows | map(select(.event == "wave_start") | .wave_index)) as $starts
    | ($rows | map(select(.event == "wave_end") | .wave_index)) as $ends
    | $starts - $ends
  '
```

(This is a crash-recovery read spanning a possibly-earlier session, so it must not be scoped to "today" —
see `orca-workflows/logging.md` §1 "Reading across dates".)

- [ ] **Step 2: Shrink the §3 wave_start telemetry block to a pointer**

Old (`skills/orca-task-runner/SKILL.md:82-95`):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs
jq -cn \
  --arg ts "$(date -u +%FT%TZ)" \
  --argjson ts_epoch "$(date -u +%s)" \
  --arg event "wave_start" \
  --arg issue "<issue-num>" \
  --argjson wave_index <n> \
  --argjson wave_size <이 wave 터미널 수> \
  --argjson nproc "$(sysctl -n hw.ncpu 2>/dev/null || nproc)" \
  '{ts: $ts, ts_epoch: $ts_epoch, event: $event, skill: "orca-task-runner", issue: $issue, wave_index: $wave_index, wave_size: $wave_size, nproc: $nproc}' \
  >> ~/.local/state/orca-workflows/logs/waves.jsonl
chmod 600 ~/.local/state/orca-workflows/logs/waves.jsonl
```

New:

```bash
# wave_start 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로 waves-<오늘 UTC 날짜>.jsonl에 기록.
# event="wave_start", issue=<issue-num>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
# nproc=$(sysctl -n hw.ncpu 2>/dev/null || nproc), ts_epoch=$(date -u +%s) — 필드는 기존과 동일, 경로만 변경.
```

Leave the following explanatory sentence (currently line 97, "`nproc`(가용 코어 수)을 같이 남기는 이유...")
exactly as-is — it explains task-runner-specific reasoning, not generic logging mechanics, so it does not
move to `logging.md`.

- [ ] **Step 3: Add `sent`+assign logging pointer to the §5 wave loop dispatch**

Old (`skills/orca-task-runner/SKILL.md:111-119`):

```bash
orca orchestration task-list --ready --brief --json
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 할당 로그 — dispatch와 같은 블록에서 즉시 실행(누락 방지). orca 상태는 reset으로 소실될 수 있어
# "어떤 subtask가 어떤 provider/model/effort로 갔는지"의 영속 기록은 이 파일이 유일하다.
# wave_index는 §3 wave_start 로그와 join해 "이 provider 조합이 이 wave 크기에서 경합을 냈는지"를 나중에 볼 수 있게 한다.
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-task-runner","role":"subtask-impl","issue":"<issue-num>","task_id":"<task_id>","wave_index":<n>,"subtask_type":"<전사|통합|아키텍처>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<impl_handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
orca orchestration task-list --ready --brief --json
spec_text="<이 task_id로 §2에서 task-create --spec에 쓴 텍스트와 동일한 subtask 본문>"
orca orchestration dispatch --task <task_id> --to <impl_handle> --inject --json   # wave 크기만큼 병렬 — 상한 임시 해제, §3 참고
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  §1 assign 이벤트: role="subtask-impl", issue=<issue-num>, task_id=<task_id>, wave_index=<n>,
#    subtask_type=<전사|통합|아키텍처>, provider/model/effort=resolved 값, terminal=<impl_handle>,
#    worktree=<worktree 경로>. wave_index는 §3 wave_start 로그와 join한다.
#  §2 term 로그: skill="orca-task-runner", role="subtask-impl", terminal=<impl_handle>,
#    meta 기록 후 sent.content=$spec_text. recv는 아래 close 직전에 기록한다(§5 마지막 블록).
```

- [ ] **Step 4: Replace the close-time `.json` snapshot with a `recv` event append**

Old (`skills/orca-task-runner/SKILL.md:128-132`):

```bash
  orca terminal read --terminal <impl_handle> --json > ~/.local/state/orca-workflows/logs/term-<impl_handle>.json
  chmod 600 ~/.local/state/orca-workflows/logs/term-<impl_handle>.json
  orca terminal close --terminal <impl_handle> --tab --json
```

New:

```bash
  # recv 이벤트 — ~/.agents/orca-workflows/logging.md §2 "첫 read" 레시피(이 터미널은 §5에서 sent만
  # 기록했고 이후 한 번도 read하지 않았으므로, 여기서의 read가 곧 유일한 recv). term-<impl_handle>.jsonl에
  # append하고, 예전처럼 별도 .json 스냅샷 파일은 만들지 않는다.
  orca terminal close --terminal <impl_handle> --tab --json
```

- [ ] **Step 5: Update the explanatory paragraph right after the close block**

Old (`skills/orca-task-runner/SKILL.md:134`, first two sentences only — rest of the paragraph is unrelated
to logging and stays untouched):

> `--tab`을 반드시 붙인다 — ... close 전에 `terminal read` 스냅샷을 남기는 이유는 close하면 스크롤백이
> 사라져서, §6 task-레벨 게이트가 나중에 실패했을 때 "이 subtask가 뭘 했는지" 재확인할 방법이 없어지기
> 때문이다. ...

New (only the "스냅샷을 남기는 이유" clause changes wording, same meaning):

> `--tab`을 반드시 붙인다 — ... close 전에 `term-<impl_handle>.jsonl`에 마지막 `recv`를 남기는 이유는
> close하면 스크롤백이 사라져서, §6 task-레벨 게이트가 나중에 실패했을 때 "이 subtask가 뭘 했는지"
> 재확인할 방법이 없어지기 때문이다. ...

- [ ] **Step 6: Shrink the §5 wave_end telemetry block, fix its read-back to glob dates**

Old (`skills/orca-task-runner/SKILL.md:138-157`):

```bash
start_epoch="$(jq -r --arg issue "<issue-num>" --argjson wi <n> \
  'select(.event == "wave_start" and .issue == $issue and .wave_index == $wi) | .ts_epoch' \
  ~/.local/state/orca-workflows/logs/waves.jsonl | tail -1)"
if [ -n "$start_epoch" ]; then
  elapsed_ms=$(( ("$(date -u +%s)" - start_epoch) * 1000 ))
else
  elapsed_ms=null   # 매칭되는 wave_start가 없음 — §0 orphan 확인을 건너뛴 경우거나 데이터 유실
fi
jq -cn \
  --arg ts "$(date -u +%FT%TZ)" \
  --arg event "wave_end" \
  --arg issue "<issue-num>" \
  --argjson wave_index <n> \
  --argjson wave_size <이 wave 터미널 수> \
  --argjson retry_count <이 wave에서 발생한 스폰 실패·timeout 재시도 총 횟수, 알 수 없으면 null> \
  --argjson elapsed_ms "$elapsed_ms" \
  --arg outcome "completed" \
  '{ts: $ts, event: $event, skill: "orca-task-runner", issue: $issue, wave_index: $wave_index, wave_size: $wave_size, retry_count: $retry_count, elapsed_ms: $elapsed_ms, outcome: $outcome}' \
  >> ~/.local/state/orca-workflows/logs/waves.jsonl
```

New:

```bash
start_epoch="$(cat ~/.local/state/orca-workflows/logs/waves-*.jsonl 2>/dev/null | jq -r --arg issue "<issue-num>" --argjson wi <n> \
  'select(.event == "wave_start" and .issue == $issue and .wave_index == $wi) | .ts_epoch' \
  | tail -1)"
if [ -n "$start_epoch" ]; then
  elapsed_ms=$(( ("$(date -u +%s)" - start_epoch) * 1000 ))
else
  elapsed_ms=null   # 매칭되는 wave_start가 없음 — §0 orphan 확인을 건너뛴 경우거나 데이터 유실
fi
# wave_end 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로 waves-<오늘 UTC 날짜>.jsonl에 기록.
# event="wave_end", issue=<issue-num>, wave_index=<n>, wave_size=<이 wave 터미널 수>,
# retry_count=<이 wave에서 발생한 스폰 실패·timeout 재시도 총 횟수, 알 수 없으면 null>,
# elapsed_ms=$elapsed_ms, outcome="completed" — 필드는 기존과 동일, 경로만 변경.
```

(§0's orphan-recovery variant of this write, `outcome:"crash_recovered"`, gets the same path treatment —
no separate step needed, it reuses this same pointer.)

- [ ] **Step 7: Verify no bare (undated) log paths remain, and every dispatch site has a logging pointer**

Run: `grep -n 'logs/assignments\.jsonl\|logs/waves\.jsonl\|logs/term-.*\.json"' skills/orca-task-runner/SKILL.md`
— expect no matches (all now either date-suffixed, `.jsonl` for term files, or replaced by pointer
comments referencing `logging.md`).

Run: `grep -n 'dispatch --task.*--inject' skills/orca-task-runner/SKILL.md` — confirm the one match
(§5 wave loop) is immediately followed within the same fenced block by a `logging.md` pointer comment.

- [ ] **Step 8: Commit**

```bash
git add skills/orca-task-runner/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(orca-task-runner): date-partition logs, add term transcript

Point assignments/waves writes and reads at orca-workflows/logging.md
instead of inlining the jq/printf blocks, switch to dated filenames,
and replace the close-time term-<handle>.json snapshot with a full
sent+recv term-<handle>.jsonl transcript.
EOF
)"
```

---

### Task 3: Update `skills/orca-evaluate/SKILL.md`

**Files:**
- Modify: `skills/orca-evaluate/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/logging.md` §1 (`assign` recipe, date-partitioned path), §2 (`meta`/`sent`
  recipes only — no `recv`)
- Produces: `term-<contract-handle>.jsonl` and `term-<review-handle>.jsonl`, each containing exactly one
  `meta` + one `sent` line (no `recv` — see rationale below)

Both of this skill's own `dispatch --inject` sites (§1 contract-review, §3 code-review) get `sent` logging
only. Neither site has an existing `terminal read` call in the current `SKILL.md` — the judgment/report
comes back through a different channel (relayed verdict, or a report file this session reads directly), so
adding a `terminal read` here would be a new behavior, not a logging change. §2's agent-e2e site keeps its
existing `terminal read` call untouched (it is out of this plan's scope — it's a headless one-shot launch,
not a `dispatch --inject`, and the approved spec's integration-point list did not include it); only its
`assignments.jsonl` path gets date-partitioned.

- [ ] **Step 1: Add `sent` logging pointer to the §1 contract-review dispatch, date-partition its assign log**

Old (`skills/orca-evaluate/SKILL.md:36-48`):

```bash
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration task-create --spec "<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시>" --json
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 할당 로그 — 스폰하는 쪽이 남긴다. dispatch와 같은 블록에서 즉시 실행(누락 방지);
# orca 상태는 reset으로 소실될 수 있어 할당의 영속 기록은 이 파일이 유일하다. §2·§3 스폰도 동일.
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"contract-review","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<contract-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
# 다회 왕복(핑퐁)이 필요한 역할 — one-shot(`agy -p`/`codex exec`) 금지, 반드시 인터랙티브(REPL)
# 세션으로 띄운다(provider 이름에 종속되지 않는 공통 원칙)
orca terminal create --worktree active --title eval-contract \
  --command "<강한 reasoning provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <contract-handle> --for tui-idle --timeout-ms 60000 --json
spec_text="<제안서 경로 + acceptance criteria 원문 + 승인/반려 판정 요청 + 반려 시 어느 criteria가 안 커버되는지 명시>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <contract-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. §2·§3 스폰도 동일한 형태.
#  §1 assign 이벤트: role="contract-review", issue=<issue-num>, task_id=<task_id>,
#    provider/model/effort=resolved 값, terminal=<contract-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-evaluate", role="contract-review", terminal=<contract-handle>,
#    meta 기록 후 sent.content=$spec_text. 이 사이트는 dispatch 이후 이 터미널을 다시 read하지
#    않으므로 recv는 기록하지 않는다(판정 결과는 relay로 받는다 — 위 §1 본문 참고).
```

- [ ] **Step 2: Date-partition the §2 agent-e2e assign log (no term-log changes — out of scope, see task notes)**

Old (`skills/orca-evaluate/SKILL.md:71-72`):

```bash
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"agent-e2e","issue":"<issue-num>","provider":"agy","model":"<model>","effort":"","terminal":"<agent-e2e-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고, task_id/dispatch_id 없음(orchestration 태스크가 아니므로)
```

New:

```bash
# 할당 로그 — ~/.agents/orca-workflows/logging.md §1 절차대로. role="agent-e2e", issue=<issue-num>,
# provider="agy", model=<model>, effort="", terminal=<agent-e2e-handle>, worktree=<worktree 경로>,
# task_id/dispatch_id 없음(orchestration 태스크가 아니므로).
```

- [ ] **Step 3: Add `sent` logging pointer to the §3 code-review dispatch, date-partition its assign log**

Old (`skills/orca-evaluate/SKILL.md:129-138`):

```bash
orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
orca orchestration task-create --spec "<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>" --json
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-evaluate","role":"code-review","issue":"<issue-num>","task_id":"<task_id>","provider":"%s","model":"%s","effort":"%s","advisor":"%s","terminal":"<review-handle>","worktree":"<worktree 경로>"}\n' \
  "$(date -u +%FT%TZ)" "$reviewer_provider" "$reviewer_model" "$reviewer_effort" "${reviewer_advisor:-}" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl   # 할당 로그 — §1 참고
```

New:

```bash
orca terminal create --worktree active --title eval-review \
  --command "$launch_cmd" --json
orca terminal wait --terminal <review-handle> --for tui-idle --timeout-ms 60000 --json
# 스폰이 실패했고 reviewer_provider가 codex였다면(spawn-failures.md 절차로 확인) 여기서 재진단하지
# 않고 --no-codex-available로 select_reviewer.py를 다시 불러 Claude 분기로 재시도한다.
spec_text="<diff 절대경로 + acceptance criteria 원문 + §2 agent e2e 결과 요약 + (해당 시) migration-lint 결과와 §1 destructive-op 선언 + skeptical 리뷰 지침 + report 경로 + 코드 수정 금지>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <review-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  §1 assign 이벤트: role="code-review", issue=<issue-num>, task_id=<task_id>, provider=$reviewer_provider,
#    model=$reviewer_model, effort=$reviewer_effort, advisor=${reviewer_advisor:-}, terminal=<review-handle>,
#    worktree=<worktree 경로>
#  §2 term 로그: skill="orca-evaluate", role="code-review", terminal=<review-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다(§1 contract-review와 같은 이유 — report는 이
#    세션이 별도로 직접 읽는다, §3 본문 마지막 문단 참고).
```

- [ ] **Step 4: Verify no bare (undated) log paths remain, and both owned dispatch sites have a logging pointer**

Run: `grep -n 'logs/assignments\.jsonl' skills/orca-evaluate/SKILL.md` — expect no matches.

Run: `grep -n 'dispatch --task.*--inject' skills/orca-evaluate/SKILL.md` — expect 3 matches (§0's
evaluate-session dispatch — owned/logged by `orca-workflow`, see Task 4, so no pointer comment needed
here — plus §1 contract-review and §3 code-review, which must each be followed by a `logging.md` pointer
comment within the same fenced block).

- [ ] **Step 5: Commit**

```bash
git add skills/orca-evaluate/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(orca-evaluate): date-partition logs, add term transcript

Point assignments.jsonl writes at orca-workflows/logging.md and
switch to dated filenames; add sent-only term-<handle>.jsonl
logging at the contract-review and code-review dispatch sites
(no recv — neither site reads the terminal back today).
EOF
)"
```

---

### Task 4: Update `skills/orca-workflow/SKILL.md`

**Files:**
- Modify: `skills/orca-workflow/SKILL.md`

**Interfaces:**
- Consumes: `orca-workflows/logging.md` §1 (`assign`/`outcome` recipes, date-partitioned path), §2
  (`meta`/`sent` recipes only — no `recv`)
- Produces: `term-<run-handle>.jsonl` and `term-<evaluate-handle>.jsonl`, each containing one `meta` + one
  `sent` line

Both of this skill's `dispatch --inject` sites (task-runner call, evaluate call) get `sent` logging only.
This skill's own stated operating principle is "diff나 report 본문을 직접 읽지 않는다" (§ intro) — it has no
`terminal read` call anywhere in the current `SKILL.md`, receiving results via task-state polling and
relayed judgments instead. Adding a `recv` capture here would mean introducing a new terminal-read call
that contradicts that principle for no logging benefit — the actual round-trip content already lands in
`orca-task-runner`'s and `orca-evaluate`'s own `term-*.jsonl` files (Tasks 2-3). This narrows the approved
spec's "orca-workflow: 2 sites, sent+recv" to "2 sites, sent-only" — flagged for the user in the final
summary.

- [ ] **Step 1: Add `sent` logging pointer to the task-runner dispatch, date-partition its assign log**

Old (`skills/orca-workflow/SKILL.md:60-68`):

```bash
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
orca orchestration task-create --spec "<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드>" --json
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 할당 로그 — 스폰하는 쪽이 남긴다. dispatch와 같은 블록에서 즉시 실행(누락 방지);
# orca 상태는 reset으로 소실될 수 있어 할당의 영속 기록은 이 파일이 유일하다.
install -d -m 700 ~/.local/state/orca-workflows/logs && printf '{"ts":"%s","event":"assign","skill":"orca-workflow","role":"task-runner","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<run-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl && chmod 600 ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
# task-runner 호출 (provider는 model-selection.md 기준 선택 — 코드 생성이라 Routine/High-Risk tier)
orca terminal create --worktree active --title task-run-<n> \
  --command "<provider의 launch 문법 — provider 문서에서 resolve>" --json
spec_text="<issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 제안서/구현 모드>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <run-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로. dispatch와 같은 블록에서 즉시 실행(누락 방지).
#  §1 assign 이벤트: role="task-runner", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<run-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-workflow", role="task-runner", terminal=<run-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 이 스킬은 diff/report 본문을 직접 읽지 않는다
#    (도입부 원칙); task-runner 자신의 왕복 내용은 task-runner의 term-<run-handle>.jsonl에 이미 남는다.
```

- [ ] **Step 2: Add `sent` logging pointer to the evaluate dispatch, date-partition its assign log**

Old (`skills/orca-workflow/SKILL.md:70-83`):

```bash
# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (agy REPL은 포커스 경합 시 영구 hang — `~/.agents/orca-workflows/models/agy.md`,
# `skills/orca-evaluate/SKILL.md` §0 참고). agy는 evaluate 내부 §2(agent e2e)의 headless
# sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
orca orchestration task-create --spec "<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드>" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
printf '{"ts":"%s","event":"assign","skill":"orca-workflow","role":"evaluator","issue":"<issue-num>","task_id":"<task_id>","provider":"<provider>","model":"<model>","effort":"<effort>","terminal":"<evaluate-handle>","worktree":"<worktree 경로>"}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
# evaluate 호출 — REPL 필수(one-shot은 이후 dispatch --inject를 못 받음), agy는 제외한다
# (agy REPL은 포커스 경합 시 영구 hang — `~/.agents/orca-workflows/models/agy.md`,
# `skills/orca-evaluate/SKILL.md` §0 참고). agy는 evaluate 내부 §2(agent e2e)의 headless
# sub-spawn일 뿐, 이 세션의 provider가 아니다. 구체 provider는 model-selection.md 기준 매
# launch 시 resolve.
orca terminal create --worktree active --title task-evaluate-<n> \
  --command "<REPL이 가능한, agy 제외 provider의 launch 문법 — provider 문서에서 resolve>" --json
orca terminal wait --terminal <evaluate-handle> --for tui-idle --timeout-ms 60000 --json
# 해당 provider가 최초 launch 시 신뢰/승인류 재프롬프트를 요구하면 그 provider 문서가 정의하는
# 절차를 따른다(agy 전용 시퀀스를 여기서 가정하지 않는다).
spec_text="<orca-evaluate SKILL.md 지침 + diff/제안서 경로 + issue 원문 + issue 번호 + §0에서 해석한 acceptance-criteria 섹션명 + 요청 모드>"
orca orchestration task-create --spec "$spec_text" --json
orca orchestration dispatch --task <task_id> --to <evaluate-handle> --inject --json
# 로그 — ~/.agents/orca-workflows/logging.md 절차대로.
#  §1 assign 이벤트: role="evaluator", issue=<issue-num>, task_id=<task_id>, provider/model/effort=resolved 값,
#    terminal=<evaluate-handle>, worktree=<worktree 경로>
#  §2 term 로그: skill="orca-workflow", role="evaluator", terminal=<evaluate-handle>, meta 기록 후
#    sent.content=$spec_text. recv는 기록하지 않는다 — 위 task-runner 사이트와 같은 이유.
```

- [ ] **Step 3: Date-partition the PREMERGE_FAIL outcome log**

Old (`skills/orca-workflow/SKILL.md:120-121`):

```bash
      printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"PREMERGE_FAIL","retry":0,"premerge_exit":%s}\n' \
        "$(date -u +%FT%TZ)" "$premerge_exit" >> ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
      printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"PREMERGE_FAIL","retry":0,"premerge_exit":%s}\n' \
        "$(date -u +%FT%TZ)" "$premerge_exit" >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
```

- [ ] **Step 4: Date-partition the generic outcome log**

Old (`skills/orca-workflow/SKILL.md:143-146`):

```bash
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION>","retry":<재시도 횟수>}\n' "$(date -u +%FT%TZ)" \
  >> ~/.local/state/orca-workflows/logs/assignments.jsonl
```

New:

```bash
printf '{"ts":"%s","event":"outcome","skill":"orca-workflow","issue":"<issue-num>","outcome":"<PASS|FAIL|ESCALATE|GATE_FAIL|PREMERGE_FAIL|NO_ACCEPTANCE_CRITERIA|NO_DONE_TRANSITION>","retry":<재시도 횟수>}\n' "$(date -u +%FT%TZ)" \
  >> "$HOME/.local/state/orca-workflows/logs/assignments-$(date -u +%F).jsonl"
```

- [ ] **Step 5: Verify no bare (undated) log paths remain, and both dispatch sites have a logging pointer**

Run: `grep -n 'logs/assignments\.jsonl' skills/orca-workflow/SKILL.md` — expect no matches.

Run: `grep -n 'dispatch --task.*--inject' skills/orca-workflow/SKILL.md` — expect 2 matches, each followed
within its fenced block by a `logging.md` pointer comment.

- [ ] **Step 6: Commit**

```bash
git add skills/orca-workflow/SKILL.md
git commit -m "$(cat <<'EOF'
refactor(orca-workflow): date-partition logs, add term transcript

Point assignments.jsonl writes at orca-workflows/logging.md and
switch to dated filenames; add sent-only term-<handle>.jsonl
logging at the task-runner and evaluate dispatch sites (no recv
— this skill never reads terminal output directly).
EOF
)"
```

---

### Task 5: Cross-file validation sweep

**Files:**
- No new modifications — read-only verification across Tasks 1-4's output.

**Interfaces:**
- Consumes: the final state of all four files from Tasks 1-4.

- [ ] **Step 1: Confirm no skill still references a bare, undated log filename**

Run:

```bash
grep -rn 'logs/assignments\.jsonl\|logs/waves\.jsonl' skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md skills/orca-workflow/SKILL.md orca-workflows/logging.md
```

Expected: no matches anywhere (all four files use either a `$(date -u +%F)`-suffixed path, a glob
`*.jsonl` read, or a pointer comment referencing `logging.md`).

- [ ] **Step 2: Confirm every `dispatch --inject` call site has a logging pointer in the same fenced block**

Run:

```bash
for f in skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md skills/orca-workflow/SKILL.md; do
  echo "== $f =="
  awk '/dispatch --task.*--inject/{print NR": "$0}' "$f"
done
```

Manually confirm each printed line's surrounding fenced code block also contains a `logging.md` pointer
comment (or, for `orca-evaluate`'s §0 block, confirm it is the one intentionally-unowned duplicate of
`orca-workflow`'s evaluate-dispatch site — see Task 3 Step 4).

- [ ] **Step 3: Confirm the old `.json` snapshot mechanism is fully gone and had no other reader**

Run: `grep -rn 'term-<impl_handle>\.json"\|term-.*\.json ' skills/orca-task-runner/SKILL.md` — expect no
matches (only `.jsonl` should remain).

Also run a repo-wide sweep for any other consumer of the old snapshot filename before treating its removal
as safe: `grep -rln 'term-.*\.json[^l]' --include='*.md' --include='*.sh' --include='*.py' .` (from the repo
root) — as of plan-writing time this already returned zero hits outside `skills/orca-task-runner/SKILL.md`
itself and this plan/spec's own prose, i.e. nothing else in the repo reads that file; re-run after Task 2 to
confirm that stays true.

- [ ] **Step 4: `bash -n` syntax-check every extracted bash block across the four files**

```bash
for f in orca-workflows/logging.md skills/orca-task-runner/SKILL.md skills/orca-evaluate/SKILL.md skills/orca-workflow/SKILL.md; do
  echo "== $f =="
  awk '/^```bash/{flag=1; block=""; next} /^```/{if(flag){print block > "/tmp/_blk.sh"; close("/tmp/_blk.sh"); system("bash -n /tmp/_blk.sh || echo FAILED: " NR)}; flag=0} flag{block = block $0 "\n"}' "$f"
done
```

This will report `FAILED` for any block that isn't standalone-parseable — expect failures only on blocks
that intentionally rely on `<placeholder>` tokens as bash syntax errors would be masked by them; visually
confirm any reported failure is a `<placeholder>`-only issue, not a real syntax mistake (unbalanced quotes,
mismatched `if`/`fi`, etc.).

- [ ] **Step 5: Confirm `orca-workflows/logging.md`'s `.result.terminal.*` field usage matches a real captured response**

Run:

```bash
python3 -c "
import json
with open('$HOME/.local/state/orca-workflows/logs/term-term_04f08341-556d-4b53-9e66-bb8703944577.json') as f:
    d = json.load(f)
t = d['result']['terminal']
assert 'tail' in t and 'nextCursor' in t and 'oldestCursor' in t
print('OK', list(t.keys()))
"
```

(If this specific file no longer exists on the machine running validation, use any other `term-*.json`
file under the same directory — the field names are a property of the `orca` CLI version, not this one
file.)

- [ ] **Step 6: Report validation results to the user**

Summarize pass/fail for Steps 1-5. If any step fails, fix the underlying file (return to the relevant Task
2-4 step) before considering this plan complete — do not commit a "fix" as part of this validation task;
re-open the task whose file needed the correction.
