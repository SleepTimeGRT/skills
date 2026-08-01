# Orca Retro — Epic-End Skill-Defect Feedback Loop Design

**Date:** 2026-08-01

**Scope:** New skill `skills/orca-retro/SKILL.md`, one integration step in
`skills/orca-workflow/SKILL.md` §1c (epic close), and a one-line extension of the documented
`outcome` enum in `orca-workflows/logging.md` (add `RETRO_DONE|RETRO_FAIL`) — filing new outcome
values without documenting them would reproduce exactly the enum drift this design targets. No
changes to `orca-task-runner` or `orca-evaluate`.

## 1. Purpose

The orca-* skill family is a layer-2 system: it builds the environment in which development happens.
What is missing is layer 3 — a loop that improves layer 2 itself. Logs are already collected
(`~/.local/state/orca-workflows/logs/`), but nothing consumes them, and measurement confirms the gap
is real: over 8 days the `outcome` field accumulated ~40 distinct free-text values against a
documented 7-value enum (`CONTRACT_APPROVE` vs `CONTRACT_APPROVED_ROUND1_WITH_CONDITIONS`,
`DIFF_RETURNED` vs `diff-returned`, `retry="n/a(human-approved continuation past cap)"`), and
`event` names drift too (`assign`/`assign-complete`, `recover`/`recovery`). The writers are LLM
agents; without a consumer that pushes back, drift is unbounded.

`spawn-failures.md` is the existing proof that a defect-fix loop works at this repo's sample sizes:
failure signature recorded → known-issue matched → skill prose fixed, effective at N=2–3
occurrences. This design generalizes that pattern. Statistical uses of the logs (per-role model
performance comparison) are explicitly out of scope — 496 assignment lines is months short of
supporting them.

**Decisions taken during brainstorming (2026-08-01):**

1. Layer-3 first target: the skill-defect-fix loop (not model-assignment optimization, not
   retry-policy tuning, not schema enforcement first).
2. Trigger: epic-end retro, spawned by `orca-workflow`.
3. Input: existing logs as-is — no new collection events before the retro has run a few times.
4. Output: auto-filed GitHub issues on `sleeptimegrt-skills`, deduplicated against open issues.

## 2. Architecture

### 2.1 Integration point (`orca-workflow` §1c)

After the all-children-closed check **and after `close_issue(epic-num, ...)` succeeds**,
`orca-workflow` spawns one retro terminal and dispatches it the `orca-retro` skill with the epic
number and target repo. It waits for the summary reply, appends an `outcome` event
(`RETRO_DONE` with issues-filed/comments-added counts, or `RETRO_FAIL`) per `logging.md` §1, logs
the terminal round-trip per `logging.md` §2 (this site *does* read the reply, so it records both
`sent` and `recv`), closes the terminal, and finishes.

Ordering note — this is a deliberate adjustment from the approved draft, which said "right before
epic close": if retro ran before `close_issue` and the coordinator crashed mid-retro, the epic would
be left open with all children done — a regression in epic-completion reliability. Running retro
after the close removes that failure mode; the retro loses nothing by running against an
already-closed epic.

### 2.2 Best-effort contract

Retro must never block or fail an epic. Spawn failure (handled per `spawn-failures.md`), dispatch
failure (per `dispatch-verify.md`), analysis failure, or `gh` failure all result in a `RETRO_FAIL`
outcome event and normal termination of the workflow. No retry of the retro itself beyond what
`orca_call_with_retry.sh` already provides at the transport level.

### 2.3 Provider selection

The retro terminal is a judgment task (defect classification against skill prose, evidence
weighing). Provider/model resolve per `model-selection.md` at launch time, same tier as other
judgment roles; the constraint set matches the evaluator site in `orca-workflow` §2 (REPL required,
agy excluded as session provider).

## 3. `orca-retro` skill procedure

Input: epic issue number, target repo, and the skills repo path (`sleeptimegrt-skills`).

### 3.1 Collect

From `~/.local/state/orca-workflows/logs/`, gather records whose `issue` field matches the epic or
any of its child task numbers (child list obtained via the issue tracker, same resolution as
`orca-workflow` §0):

- `assignments*.jsonl` — `assign` and `outcome` events (dated files globbed per `logging.md` §1
  read-across-dates rule)
- `spawn-failures.jsonl`
- `term-*.jsonl` transcripts whose `meta` line matches those issues

Empty result set → reply `RETRO_DONE` with zero findings and stop (no-op epics are normal for work
done outside the harness).

### 3.2 Extract defect candidates — four lenses

1. **Instruction violations** — log records that break the schemas the skills themselves document:
   `outcome` values outside the documented enum, `event` name variants, free-text where a number is
   specified. The schema drift measured in §1 is deliberately the first-class target: the loop's
   first filings should be against whichever skill sites produced the drift. This lens alone scans
   the *full* contents of the dated log files spanning the epic's first `assign` to its close (not
   only the issue-filtered records) — a record whose own `issue` field drifted would otherwise
   escape the very lens that hunts drift.
2. **Repeated FAILs attributable to skill prose** — the same FAIL reason recurring across tasks or
   retries where the term transcript shows the worker misreading or missing a skill instruction.
3. **Escalations/human interventions the skill could have prevented** — `ESCALATE` and
   `*_HUMAN_DECISION` outcomes whose transcripts show a gap a skill amendment would close.
4. **New spawn-failure signatures** — `spawn-failures.jsonl` entries with no `known_issue` match.

### 3.3 Evidence bar and cap

A candidate without at least one quoted log line (file path + verbatim excerpt) is discarded, not
filed. At most **3 issues per epic**; further candidates go into an appendix section of the
highest-priority filed issue. Priority order: recurrence count first, then blast radius (how many
skills/sites the defect touches).

### 3.4 Deduplicate

Before filing, list open issues on the skills repo (`gh issue list --state open`) and compare
against candidates; also compare spawn-failure candidates against `known_issue` numbers already
assigned in `spawn-failures.md`. A match → add a recurrence comment on the existing issue (evidence
lines + epic number) instead of filing. Recurrence comments are the loop's priority signal.

### 3.5 File

New issues carry: label `retro`, the target skill file(s), quoted evidence, the epic number, the
log paths consulted, and a proposed fix direction (one paragraph, not a diff — the fix itself goes
through the normal `/orca-workflow` pipeline later).

### 3.6 Reply

Single summary message back to the coordinator: filed issue numbers, commented issue numbers,
discarded-candidate count. No report file — the issues are the durable output.

## 4. How the loop closes

Retro-filed issue → user triages → `/orca-workflow` picks it up as an ordinary task → skill fix
merges to main → live immediately for `orca-workflows/` reference files via the `~/.agents`
symlink, after `scripts/deploy-skills.sh` for `skills/` copies → the next epic's retro naturally
re-observes: recurrence comment on the issue means the fix missed; silence means it held. No
separate effect-measurement mechanism.

## 5. Out of scope (deliberate)

- **Model/role performance statistics** — sample size months short; revisit when volume supports it.
- **New deviation-capture events** — run the retro 2–3 times on existing logs first, then add only
  the fields whose absence actually hurt the analysis.
- **Mechanical outcome-enum enforcement** — the retro files the drift as defect issues; whether the
  fix is prose hardening or a validation helper script is decided in those issues, not here.
- **Retro for single-task (non-epic) issues** — epic-end only in v1.
- **Retro effectiveness dashboards/metrics** — recurrence comments are the signal.

## 6. Known risks (accepted)

- The retro analyst is itself an LLM and can drift or hallucinate defects. Mitigations: the evidence
  bar (§3.3), the 3-issue cap, and the fact that output is triage-able issues, not direct skill
  edits. The retro skill is itself subject to the same loop.
- Large `term-*.jsonl` transcripts may strain the retro session's context. Accepted for v1;
  measure before adding summarization or sampling.
- Log records with drifted `issue`/`event` fields may escape the §3.1 filter — the loop can miss
  evidence of exactly the drift it hunts. Accepted: lens 1 runs on the *full* day-file contents for
  the epic's date range, not only on issue-filtered records, so enum drift is still visible.

## 7. Validation

Per AGENTS.md validation rules, test against a fixture log directory before first real use:

- Epic with defects across all four lenses → issues filed with evidence, cap respected
- Empty/no logs for the epic → `RETRO_DONE`, zero findings, no `gh` calls
- Candidate matching an existing open issue → recurrence comment, no duplicate issue
- More than 3 candidates → appendix behavior
- `gh` failure mid-filing → `RETRO_FAIL` reported, no partial-state cleanup required beyond what was
  already filed
