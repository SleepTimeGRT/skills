# Model Selection

Select and pin the worker model and effort before launch.

This file owns the tier-to-model mapping. Provider documents own launch syntax and required runtime checks.
Load [the selection reference](references/model-selection.md) only when auditing, changing, or re-validating
the mapping.

Workflow orchestration is owned by `orca-workflow`, `orca-workflow-task`, `orca-workflow-epic`, `orca-task-runner`, `orca-evaluate`, and `orca-retro`.

## 1. Classify the task

Choose the highest applicable tier.

| Tier | Typical work |
|---|---|
| **High Risk** | Architecture decisions, auth/RLS, migration, crypto, server logic, production review, final approval |
| **Routine** | Feature development, refactor, debugging, testing, bounded code review |
| **Simple** | Formatting, rename, boilerplate, transcription, classification |

If uncertain, choose the higher tier.

## 2. Pin model and effort

Before pinning a provider, run the "Quota check before pinning" step below — it can exclude or deprioritize
a candidate before you commit to it.

Orca workers must launch with an explicit model and effort and must not change either mid-task without
reclassifying the task. This is an Orca workflow invariant, not a claim that every provider runtime makes
the setting immutable.

When reusing a worker, verify that its pinned model and effort still match the task.

Claude Code exception:

- Check the minimum CLI version before launching `claude-opus-5`; see `models/claude-code.md`.
- After every High Risk Opus 5 run, inspect `modelUsage` or the transcript for automatic fallback.
- If it ran on `claude-opus-4-8`, report the actual model. If a biology flag refused the run, return human
  `ESCALATE` instead of `PASS` or `FAIL`.

## Default mapping

| Tier | Provider | Model | Effort | Use |
|---|---|---|---|---|
| High Risk | Claude | `claude-opus-5` | xhigh | Precision-oriented architecture, security, migration, production review, and final approval |
| High Risk | Codex | `gpt-5.6-sol` | high; xhigh for security/final gates | Recall-oriented review and demanding implementation; raise effort when missed findings cost more than latency or usage |
| Routine | Claude | `claude-sonnet-5` | high | Primary generator, including design-heavy implementation; architecture decisions move to High Risk |
| Routine | Claude | `claude-opus-5` | xhigh, separate session only | Reviewer, not primary generator; advisor-tool effort cannot be selected or verified |
| Routine | Codex | `gpt-5.6-terra` | medium | Primary generator and bounded first-pass triage; escalate final or high-risk review to Sol |
| Simple | Claude | `claude-haiku-4-5-20251001` | omit | Transcription, boilerplate, and mechanical edits |
| Simple | Codex | `gpt-5.6-luna` | max | Short, clear, repeatable work, plus narrow-context Routine subtasks (single file/small bounded diff) — never long-context or large-codebase work, regardless of effort; boot-smoke precondition applies (never dispatched in this repo yet) |
| Simple | Gemini (agy) | `gemini-3.6-flash-low` | low | Short mechanical work |

Do not use `claude-fable-5`. Do not transfer an effort choice between models or providers merely because
the level has the same name. Provider-specific evidence and unresolved validation are recorded in the
references.

## Computer-use / skeptical artifact cross-check

This is a separate execution axis; it does not replace the risk tier.

Use it when a worker:

- drives a browser or desktop directly, including agent e2e;
- re-reads multiple raw logs or artifacts to correlate failures their summaries may miss.

Do not use a model where a deterministic parser can consume TAP, JUnit, JSON, or another structured
format. Technical judgment still goes to the appropriate risk-tier worker.

| Priority | Model | Effort | Use |
|---|---|---|---|
| 1 | `gemini-3.6-flash-medium` | medium | Browser/computer execution and raw-artifact cross-check |
| 2 | `claude-sonnet-5` | medium | Fallback when agy is unavailable or quota-limited |

Do not choose this axis for long context alone. Capacity and retrieval quality are separate properties and
must be evaluated on representative inputs.

Consumers: `orca-evaluate` agent-e2e/raw-trace work and report synthesis. Its contract approval and diff
review remain separate High Risk sessions.

## Provider preference

Routine:

1. Claude Sonnet 5
2. Codex Terra

Simple:

1. Claude Haiku 4.5
2. Codex Luna, after boot smoke
3. Gemini flash-low

Escalate immediately for architecture, security, migration, production incidents, and final review.

## Quota check before pinning

Before pinning a provider from the default mapping or the preference order above, confirm it has room via
`usage-check.md`'s `orca account list --json` procedure, for whichever window(s) its `rateLimits` object
actually carries (session/weekly/buckets — see `usage-check.md` for the per-provider shape; a missing
window is not the same as 0% used, don't treat absence as available room). Two different states, two
different responses — don't collapse them into one exclusion bucket:

**Hard-exclude** (never pin, regardless of what else is available): `status != "ok"`, or a present window's
`usedPercent >= 100`, or `rateLimitResetCredits.availableCount == 0`. At this point the provider either
can't run at all, or keeps accepting dispatches while billing past its included quota — the exact outcome
to avoid, not something to accept as a last resort.

**Prefer-avoid** (pick another candidate first, but still usable): a present window's `usedPercent` in
`[90, 100)`. This is margin against several parallel workers pushing the same window over 100% between
checks, not a sign the provider is already costing extra — don't stop a wave just because the remaining
candidate is only prefer-avoid.

Resolution: try candidates in order (preference list, then any other tier-appropriate provider), skipping
hard-excluded ones outright and only falling back to a prefer-avoid one if no clean candidate remains. If
every candidate for the tier is hard-excluded, stop and report the earliest `resetsAt` among them instead of
pinning — don't silently drop to a lower tier just to find something available.

## Provider documents

- Claude Code: `models/claude-code.md`
- Codex: `models/codex.md`
- agy: `models/agy.md`

Evidence references:

- Cross-provider decisions: `references/model-selection.md`
- Claude: `references/models/claude-code.md`
- Codex: `references/models/codex.md`
- agy: `references/models/agy.md`
