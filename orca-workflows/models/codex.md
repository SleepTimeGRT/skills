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

**Linked worktree exception:** the writable boundary `-s workspace-write` grants is the worktree's own
filesystem path, nothing more. In a linked worktree (`~/worktrees/...` — `orca-task-runner`'s standard
per-task layout), `.git` is not a directory but a file that points at the parent repository's
`.git/worktrees/<name>/`. That target path lives outside the worktree's own filesystem tree, so it is
outside the sandbox boundary. A codex worker launched this way edits source files normally, but any
`git add`/`git commit` it runs fails — the write lands on a path the sandbox denies. Do not have codex
workers commit in this configuration; see `skills/orca-task-runner/SKILL.md` §2 (subtask spec, provider=codex
branch) and §5 (commit-helper terminal) for the contract this exception drives.

## Mapping

| Model | Use | Orca effort |
|---|---|---|
| `gpt-5.6-sol` | High Risk implementation and final review | high; xhigh for security/final gates with asymmetric miss cost |
| `gpt-5.6-terra` | Routine implementation and bounded first-pass triage | medium |
| `gpt-5.6-luna` | Simple work, plus narrow-context Routine subtasks (single file or small bounded diff) | max |

Routine review path: Terra may triage a bounded diff, but final or high-risk judgment escalates to Sol.
Do not use Luna for large diffs, long logs, final code review, or anything requiring reasoning across
multiple files or a large codebase — its long-context recall collapses regardless of effort level (see
reference, MRCR). Luna's role is bounded-context volume work, not depth.

## Effort support

The current Codex catalog exposes:

- Sol and Terra: `low`, `medium`, `high`, `xhigh`, `max`, `ultra`
- Luna: `low`, `medium`, `high`, `xhigh`, `max`

`max` is opt-in for the hardest single-agent problems. Do not use `ultra` for Orca workers: it adds
automatic delegation on top of Orca's explicit orchestration. Use only the model-specific values listed
above.

## Launch precondition

`gpt-5.6-luna` has no recorded boot smoke in this repository — it has never been dispatched to a real
worker here (confirmed by grepping `assignments*.jsonl`, 2026-08-04: zero occurrences). Before its first
real worker launch at the `max` effort above, run one bounded `codex exec` smoke and record the result in
the reference. This precondition is unchanged by the low→max effort update; it was never satisfied at any
effort level.

Load [the Codex evidence reference](../references/models/codex.md) only when auditing, changing, or
re-validating this mapping.
