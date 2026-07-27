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

Use `codex exec` for headless runs. `-s workspace-write -a never` permits reads and writes inside the
workspace without approval prompts; it is not read-only. Use `-s read-only -a never` when the reviewer
must not write.

## Mapping

| Model | Use | Orca effort |
|---|---|---|
| `gpt-5.6-sol` | High Risk implementation and final review | high; xhigh for security/final gates with asymmetric miss cost |
| `gpt-5.6-terra` | Routine implementation and bounded first-pass triage | medium |
| `gpt-5.6-luna` | Short, clear, repeatable Simple work | low |

Routine review path: Terra may triage a bounded diff, but final or high-risk judgment escalates to Sol.
Do not use Luna for large diffs, long logs, or final code review.

## Effort support

The current Codex catalog exposes:

- Sol and Terra: `low`, `medium`, `high`, `xhigh`, `max`, `ultra`
- Luna: `low`, `medium`, `high`, `xhigh`, `max`

`max` is opt-in for the hardest single-agent problems. Do not use `ultra` for Orca workers: it adds
automatic delegation on top of Orca's explicit orchestration. Use only the model-specific values listed
above.

## Launch precondition

`gpt-5.6-luna` has no recorded boot smoke in this repository. Before its first real worker launch, run one
bounded `codex exec` smoke and record the result in the reference.

Load [the Codex evidence reference](../references/models/codex.md) only when auditing, changing, or
re-validating this mapping.
