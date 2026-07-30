---
name: model-claude-code
description: Claude Code worker model and effort selection for coordinators, implementers, and reviewers
---

# Claude Code (Anthropic)

Launch:

```bash
claude --model <id> --effort <low|medium|high|xhigh|max>
```

SDD implementation workers use `--dangerously-skip-permissions` (equivalent to `--permission-mode bypassPermissions`)
only inside an isolated worktree.
`claude-opus-5` requires Claude Code 2.1.219 or newer.

## Mapping

| Model | Use | Effort |
|---|---|---|
| `claude-opus-5` | Coordinator, High Risk work, separate-session precision review | xhigh |
| `claude-sonnet-5` | Routine implementation and integration | high |
| `claude-haiku-4-5-20251001` | Transcription and mechanical work | omit; unsupported |

Do not use `claude-fable-5`. Architecture decisions move to Opus 5 High Risk; design-heavy Routine
implementation stays on Sonnet 5.

## Automatic model fallback

Claude Code safety classification can change the actual model:

- Opus 5 plus a cybersecurity flag reruns on `claude-opus-4-8`.
- Opus 5 plus a biology flag has no fallback and may refuse.
- The first request, including workspace context, can trigger classification.

After every High Risk Opus 5 run, inspect JSON `modelUsage` or the interactive transcript. Report the
actual model. A biology refusal returns human `ESCALATE`, not `PASS` or `FAIL`.

## Advisor tool

Use `/advisor`, `--advisor`, or `advisorModel` for an Opus review inside a Sonnet 5 session when available.
The advisor model can be selected, but its effort cannot be set or verified. The xhigh mapping applies only
when Opus 5 is launched as a separate session.

Load [the Claude evidence reference](../references/models/claude-code.md) only when auditing, changing, or
re-validating this mapping.
