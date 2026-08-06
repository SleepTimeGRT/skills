# spawn-failures.md Evaluator Mid-Run Crash Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register the "evaluator crashed mid-session" failure as a known row in `orca-workflows/spawn-failures.md`'s known-signature table, and fix a table-rendering bug in the same file discovered while doing so.

**Architecture:** Single-file markdown edit. Two independent, anchor-based text edits to `orca-workflows/spawn-failures.md`: (1) remove a stray blank line that splits the known-signature table into two disconnected fragments, (2) append a new no-signature row (modeled on the existing `#60` row) plus a one-sentence addendum to the "Adding a new row" explanatory section. No code, no other files, no other repositories.

**Tech Stack:** Markdown. Verification is via `grep`/`awk` shell checks against the file — there is no test runner for this repo's prose files.

## Global Constraints

- Only `orca-workflows/spawn-failures.md` changes. No other file, no other repository (spec §범위 경계).
- The new row's `failure_signature` cell must read `*(no signature captured yet — see root cause)*` — do **not** use the issue's original literal-string proposal (`Agent exited with code -1 mid-session (dispatch status=failed, terminal status=exited)`); the brainstorming decision explicitly rejected that as unverifiable against this occurrence's logs (spec §결정 1, §검토 후 기각한 대안).
- The new row's `known_issue` cell must be `#61`.
- The blank line currently between the `#43` row and the `#60` row (line 70) must be removed so the table renders as one unbroken block (spec §결정 2).
- The "Adding a new row" no-signature exception paragraph must gain one sentence linking the new row to `#60`'s reasoning (spec §결정 1).
- No other row's text changes.

---

### Task 1: Fix the table-splitting blank line

**Files:**
- Modify: `orca-workflows/spawn-failures.md` (currently line 70 — a blank line between the `#43` row and the `#60` row)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a `spawn-failures.md` where every line of the known-signature table (from the header row through the `#60` row) is contiguous — i.e., `grep -n '^|' orca-workflows/spawn-failures.md` returns strictly consecutive line numbers with no gap in that range. Task 2 depends on this: it anchors its insertion on the `#60` row assuming no blank line follows it.

- [ ] **Step 1: Write the failing check**

This repo has no test runner for markdown files, so "test" here means a shell check that proves the bug is present. Run this from the repo root:

```bash
grep -n '^|' orca-workflows/spawn-failures.md | awk -F: '
NR==1 { prev=$1; next }
{ if ($1 != prev+1) print "gap between table line " prev " and " $1; prev=$1 }
'
```

- [ ] **Step 2: Run the check to verify it currently reports the gap**

Run the command from Step 1.
Expected output: `gap between table line 69 and 71` (the `#43` row is line 69, the `#60` row is line 71, and the blank line 70 between them breaks table contiguity).

- [ ] **Step 3: Remove the blank line**

Use the Edit tool on `orca-workflows/spawn-failures.md` with:

`old_string`:
```
Log an occurrence either way per the Procedure section above | #43 |

| *(literal substring not yet confirmed in this environment — see root cause)* | A spawned worker/evaluator terminal's MCP server
```

`new_string`:
```
Log an occurrence either way per the Procedure section above | #43 |
| *(literal substring not yet confirmed in this environment — see root cause)* | A spawned worker/evaluator terminal's MCP server
```

(This deletes exactly the one blank line between the two rows — everything else in both lines is unchanged.)

- [ ] **Step 4: Run the check again to verify it passes**

Run the same command from Step 1.
Expected output: nothing (no gap reported) — the known-signature table (header through the `#60` row) is now one contiguous block.

- [ ] **Step 5: Commit**

```bash
git add orca-workflows/spawn-failures.md
git commit -m "$(cat <<'EOF'
fix(orca-workflows): close spawn-failures.md table-splitting blank line

A stray blank line between the #43 and #60 rows broke the known-signature
table into two Markdown fragments, so the #60 row silently stopped being
part of the table the grep-first procedure searches.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add the evaluator mid-run crash row

**Files:**
- Modify: `orca-workflows/spawn-failures.md` (the `#60` row, immediately followed by the `## Adding a new row` heading — one line lower than in Task 1's description, since Task 1 removed a line above it)

**Interfaces:**
- Consumes: Task 1's fixed file state — this task's anchor edit targets the text immediately after the `#60` row's closing `| #60 |` and assumes no blank line was reintroduced there.
- Produces: the final `spawn-failures.md` state. No later task depends on this one.

- [ ] **Step 1: Write the failing check**

```bash
grep -c '^| \*(no signature captured yet' orca-workflows/spawn-failures.md
```

- [ ] **Step 2: Run the check to verify it currently fails (row absent)**

Run the command from Step 1.
Expected output: `0`

- [ ] **Step 3: Insert the new row after the `#60` row**

Use the Edit tool on `orca-workflows/spawn-failures.md` with:

`old_string`:
```
capture the modal's literal on-screen text via `terminal read` and upgrade this row to a proper `failure_signature` substring — this row stays no-signature until then | #60 |

## Adding a new row
```

`new_string`:
```
capture the modal's literal on-screen text via `terminal read` and upgrade this row to a proper `failure_signature` substring — this row stays no-signature until then | #60 |
| *(no signature captured yet — see root cause)* | An evaluator terminal (REPL, no scheduled `terminal read` per `orca-workflow` SKILL.md §2a's by-design read-nothing-until-`worker_done` model) went unresponsive mid-session and was inferred crashed via structured status ("dispatch status=failed" / "terminal status=exited") rather than any `terminal read` output — this term log has zero `recv` events by design, so no literal on-screen substring exists to grep. Root cause of the crash itself is unconfirmed; even the exact command/JSON that produced the "failed"/"exited" status pair wasn't captured this occurrence | fresh evaluator terminal re-spawn + re-dispatch — this consumes no task-level retry budget (`assignments.jsonl`'s `retry` counter is untouched by a spawn-failure respawn; verified against issue #470's log, where the crash-respawn kept `round:2` without bumping `retry`) since it isn't a FAIL verdict. Next occurrence: before respawning, run `orca terminal show --terminal <handle> --json` and `orca orchestration worker-show --dispatch <dispatch_id> --json`, capture the raw JSON verbatim, and attempt one `orca terminal read` even if expected empty — upgrade this row to a literal substring once actually observed | #61 |

## Adding a new row
```

- [ ] **Step 4: Run the check again to verify it passes**

Run the same command from Step 1.
Expected output: `1`

- [ ] **Step 5: Write the failing check for the explanatory-section addendum**

```bash
grep -c "Issue #61's row groups with #60's reasoning" orca-workflows/spawn-failures.md
```

- [ ] **Step 6: Run the check to verify it currently fails**

Run the command from Step 5.
Expected output: `0`

- [ ] **Step 7: Add the addendum sentence to the "Adding a new row" section**

Use the Edit tool on `orca-workflows/spawn-failures.md` with:

`old_string`:
```
modal is actually observed, unlike #43's row which has no substring to capture even in principle. Use a
signature-less row like this only when a failure genuinely has neither a literal substring nor a reliable
retrospective log check; default to the literal-substring form whenever one exists.
```

`new_string`:
```
modal is actually observed, unlike #43's row which has no substring to capture even in principle. Issue
#61's row groups with #60's reasoning — a structured status pair (`dispatch status=failed`/`terminal
status=exited`) was observed, so a substring likely exists, but neither it nor the command/JSON that
produced it was captured this occurrence. Use a signature-less row like this only when a failure genuinely
has neither a literal substring nor a reliable retrospective log check; default to the literal-substring
form whenever one exists.
```

- [ ] **Step 8: Run the check again to verify it passes**

Run the same command from Step 5.
Expected output: `1`

- [ ] **Step 9: Full-table regression check**

Confirm the insertion didn't reopen the Task 1 gap and that the new row is the last row before the heading:

```bash
grep -n '^|' orca-workflows/spawn-failures.md | awk -F: '
NR==1 { prev=$1; next }
{ if ($1 != prev+1) print "gap between table line " prev " and " $1; prev=$1 }
'
```

Expected output: nothing.

- [ ] **Step 10: Commit**

```bash
git add orca-workflows/spawn-failures.md
git commit -m "$(cat <<'EOF'
fix(orca-workflows): register evaluator mid-run crash as known spawn failure

Adds a no-signature row (grouped with #60's reasoning — a structured status
pair was observed but not the literal command/JSON that produced it) so the
next "Agent exited with code -1 mid-session" evaluator crash is recognized
as known instead of re-diagnosed from scratch.

Fixes #61

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** §결정 1 (new no-signature row, exact wording) → Task 2 Steps 1-4. §결정 1's addendum to "Adding a new row" → Task 2 Steps 5-8. §결정 2 (blank-line fix) → Task 1. §범위 경계 (single file, single repo) → Global Constraints + both tasks only touch `orca-workflows/spawn-failures.md`.
- **Placeholder scan:** no TBD/TODO; every step has literal `old_string`/`new_string` content or a runnable shell command with expected output.
- **Type consistency:** N/A (no code, no function signatures) — the one cross-task dependency (Task 2's anchor assumes Task 1's blank-line removal already happened) is stated explicitly in Task 2's Interfaces block.
