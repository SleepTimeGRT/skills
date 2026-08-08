---
name: model-codex
description: Codex(OpenAI) worker model and effort selection for coordinators, implementers, and evaluators
---

# Codex (OpenAI)

Use GPT-5.6 workers with an explicit model and effort. Evaluators require fresh context, not a different
provider.

Launch:

```bash
codex --model <id> -c model_reasoning_effort=<effort>
```

Use `codex exec` for headless runs. `-s workspace-write` permits reads and writes inside the workspace;
it is not read-only. Approval policy is separate from the sandbox boundary. Use `-s read-only` when the
reviewer must not write.

## Mapping

| Model | Use | Orca effort |
|---|---|---|
| `gpt-5.6-sol` | High Risk implementation and final review | high; xhigh for security/final gates with asymmetric miss cost |
| `gpt-5.6-terra` | Routine implementation and bounded first-pass triage | medium |
| `gpt-5.6-luna` | Clear, repeatable, high-volume work; narrow-context routine subtasks | medium |

Routine review path: Terra may triage a bounded diff, but final or high-risk judgment escalates to Sol.
Luna's role is clear, repeatable, high-volume work.

## Effort support

Use the lowest reasoning effort that produces the required result, then increase it when the task needs
more planning, analysis, or checking. `max` is for the hardest single-agent problems. Ultra uses automatic
task delegation. Do not use `ultra` for Orca workers; Orca owns parallel decomposition explicitly.

## Launch precondition

`gpt-5.6-luna` has no recorded boot smoke in this repository — it has never been dispatched to a real
worker here (confirmed by grepping `assignments*.jsonl`, 2026-08-04: zero occurrences). Before its first
real worker launch at the `max` effort above, run one bounded `codex exec` smoke and record the result in
the reference. This precondition is unchanged by the low→max effort update; it was never satisfied at any
effort level.

Load [the Codex evidence reference](../references/models/codex.md) only when auditing, changing, or
re-validating this mapping.
