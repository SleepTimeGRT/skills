# Orca Workflows Log Restructure Design

**Date:** 2026-07-30

**Scope:** `~/.local/state/orca-workflows/logs/` layout produced by `orca-task-runner`, `orca-evaluate`,
`orca-workflow`, plus a new shared `orca-workflows/logging.md` reference document

## 1. Purpose

Two gaps in the current orca-\* logging:

1. `assignments.jsonl`/`waves.jsonl` are single, non-rotating, append-only files. `assignments.jsonl` has
   already grown to 438 lines / 130KB over roughly 3-4 days of use, with no date boundary to scope a read to
   "what happened today" or "what happened for this issue on this day."
2. There is no durable record of what prompt content actually moved between the orchestrating session and a
   spawned terminal. `orca-task-runner` captures a single terminal-read snapshot immediately before closing
   a subtask terminal (`term-<handle>.json`), but nothing records the injected prompt itself, and nothing
   captures this for `orca-evaluate`'s or `orca-workflow`'s own spawned terminals. When something goes wrong
   downstream, there is no way to reconstruct which prompt produced which response.

This design adds date-partitioned assignment/wave logs and a per-terminal round-trip transcript, and factors
the shared logging procedure into one reference document so three `SKILL.md` files do not each carry their
own copy of the same bash logic.

## 2. `assignments.jsonl` / `waves.jsonl` Date Partitioning

Path changes from a single fixed file to one file per UTC date:

- `~/.local/state/orca-workflows/logs/assignments-<UTC-date>.jsonl`
- `~/.local/state/orca-workflows/logs/waves-<UTC-date>.jsonl`

Each append computes `date="$(date -u +%F)"` immediately before writing and interpolates it into the
filename. The jq schema, `install -d -m 700`, and `chmod 600` on every write stay exactly as they are today
— only the path changes. No cross-file join key is needed since `wave_index`/`issue`/`task_id` already
appear inside each record.

Retention: unbounded, no automatic deletion. Multi-day queries use `cat assignments-*.jsonl | jq ...` or
`grep`/`jq` filtering by `issue`.

## 3. New Shared Reference: `orca-workflows/logging.md`

Added alongside `orca-workflows/spawn-failures.md`, following the same two-layer precedent already
established there (a git-tracked procedure document that three `SKILL.md` files point to instead of each
repeating the same bash):

- **§1 — Date-partitioned paths.** The exact snippet for computing today's `assignments`/`waves` path
  (Section 2 above), so all three skills compute the date the same way.
- **§2 — `term-<handle>.jsonl` round-trip log.** The format, the `meta`/`sent`/`recv` event schema, and the
  `orca terminal read --cursor` incremental-read pattern (Section 4 below).

Each `SKILL.md`'s existing inline logging blocks are replaced with a short pointer comment in the same style
already used for `spawn-failures.md` references (e.g. `~/.agents/orca-workflows/spawn-failures.md`) — the
procedure is documented once, not copied three times.

## 4. `term-<handle>.jsonl` Format

Path: `~/.local/state/orca-workflows/logs/term-<handle>.jsonl`. Created the first time a terminal is
dispatched to; append-only until the terminal closes; `chmod 600` on creation, matching the other logs in
this directory.

Line 1 is a meta record; every following line is a round-trip event:

```jsonl
{"type":"meta","issue":"<issue-num>","skill":"<orca-task-runner|orca-evaluate|orca-workflow>","role":"<subtask-impl|evaluate|contract-review|...>","terminal":"<handle>","created_at":"<ISO8601>"}
{"ts":"<ISO8601>","direction":"sent","content":"<text passed to task-create --spec for this dispatch>","cursor_before":<n>}
{"ts":"<ISO8601>","direction":"recv","content":"<orca terminal read --cursor <cursor_before> output>","cursor_after":<n>}
```

- `related_terminals` is not tracked — the `issue` field alone is the join key. Every `term-*.jsonl` file
  for the same issue can be found by `grep -l '"issue":"<n>"' term-*.jsonl` without a skill needing to look
  up and record sibling terminal handles at spawn time.
- **`sent`** is written right after (or immediately before) `orca orchestration dispatch --task <id> --to
  <handle> --inject`, using the same spec text the orchestrating session already composed for
  `task-create --spec`. It is not re-fetched from `orca orchestration task-list`.
- **`recv`** is written after `orca terminal wait --for tui-idle` returns, using
  `orca terminal read --terminal <handle> --cursor <cursor_before> --json`, where `cursor_before` is the
  previous round's `cursor_after` (or omitted/`0` for the first round). `--cursor` returns only output
  produced since the last read (confirmed via `orca terminal read --help`), so each `recv` line holds only
  the new output for that round rather than the full scrollback — file size grows with actual new output,
  not quadratically with round count.
- One `sent`+`recv` pair is one round. A terminal that receives multiple injects (retries, decision-gate
  replies) accumulates multiple rounds in the same file.

## 5. Integration Points

Every existing `dispatch --inject` call site gains sent/recv logging around it:

- `orca-task-runner` §5 (wave loop): `dispatch --task <task_id> --to <impl_handle> --inject`
- `orca-evaluate`: §1 evaluate-session dispatch, §1 contract-review dispatch, §3 code-review dispatch (three
  sites)
- `orca-workflow` §2: task-runner dispatch, evaluate dispatch (two sites)

`orca-task-runner`'s existing close-time snapshot (`orca terminal read --terminal <impl_handle> --json >
~/.local/state/orca-workflows/logs/term-<impl_handle>.json`, `skills/orca-task-runner/SKILL.md:129`) is
removed. `term-<handle>.jsonl` already holds the full round-trip history up through the terminal's last
`recv` before close, making the separate single-snapshot file redundant.

## 6. Edge Cases

- If a terminal dies or times out after a `sent` with no corresponding `recv`, the file is left with a
  dangling `sent` line. This is treated as useful diagnostic signal in itself (last content sent, and when)
  rather than an error to correct — no cleanup or backfill logic.
- If `orca terminal read --cursor` reports a stale cursor or dropped lines (via `oldestCursor` in its
  output), the `recv` event gets a `"dropped":true` field and logging continues normally. No retry or
  reconstruction logic — this stays a diagnostic breadcrumb, not a guarantee of completeness.

## 7. Validation

Read-only / dry-run checks, no production log mutation during validation:

1. Confirm the date-partitioned path snippet in `logging.md` produces the same jq schema output as the
   current single-file `assignments.jsonl`/`waves.jsonl` blocks, just with a dated filename.
2. Confirm every `dispatch --inject` call site identified in Section 5 gets a paired sent/recv logging
   snippet, and that no call site is missed by re-grepping the three `SKILL.md` files for `--inject` after
   the edit.
3. Confirm the removed close-time snapshot logic (`skills/orca-task-runner/SKILL.md:129`) has no other
   reader depending on the `.json` (non-`.jsonl`) filename before deleting it.
4. Manually exercise the `term-<handle>.jsonl` format against a real `orca terminal read --cursor` response
   shape to confirm the field names used here (`nextCursor`, `oldestCursor`) match the live CLI output before
   wiring the jq extraction.
5. Confirm `orca-workflows/logging.md` is referenced by pointer (not duplicated) from all three `SKILL.md`
   files, matching the existing `spawn-failures.md` pattern.

No skill deployment is part of this change under the existing `orca-workflows/` symlink-tracks-main
convention — edits go live on merge to `main` with no separate `scripts/deploy-skills.sh` step.
