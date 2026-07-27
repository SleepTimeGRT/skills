# Codex Model Evidence

> verified_at: 2026-07-27

Load this file only to audit, change, or re-validate `../../models/codex.md`.

## Current catalog and effort semantics

Local verification used Codex CLI 0.145.0:

```bash
codex debug models
```

The refreshed catalog exposed:

| Model | Default | Supported in Codex catalog |
|---|---|---|
| `gpt-5.6-sol` | medium | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-terra` | medium | low, medium, high, xhigh, max, ultra |
| `gpt-5.6-luna` | medium | low, medium, high, xhigh, max |

The OpenAI API model guide documents `none`, `low`, `medium`, `high`, `xhigh`, and `max` for GPT-5.6.
That API list must not be copied into CLI launch guidance without checking the current CLI catalog.
`minimal` appeared in an older general configuration example but is not exposed by the current GPT-5.6
Codex catalog.

`max` gives one model more time for the hardest problems. `ultra` additionally delegates to subagents.
Orca excludes ultra because Orca already controls worker decomposition, concurrency, and synthesis.

Sources:

- <https://developers.openai.com/api/docs/models>
- <https://developers.openai.com/api/docs/guides/latest-model>
- <https://developers.openai.com/codex/codex-manual.md>

## Model roles and pricing

OpenAI positions Sol as the flagship for complex professional work, Terra as the intelligence/cost
balance, and Luna as the cost-sensitive high-volume tier. Published prices per 1M tokens are:

| Model | Input | Output |
|---|---:|---:|
| Sol | $5.00 | $30.00 |
| Terra | $2.50 | $15.00 |
| Luna | $1.00 | $6.00 |

Source: <https://openai.com/index/gpt-5-6/>

## Published benchmark context

The OpenAI launch report includes:

| Evaluation | Sol | Terra | Luna |
|---|---:|---:|---:|
| Artificial Analysis Coding Agent Index v1.1 | 80.0 | 77.4 | 74.6 |
| SWE-Bench Pro | 64.6% | 63.4% | 62.7% |
| MRCR v2, 8-needle, 256K-512K | 91.5% | 89.6% | 41.3% |
| MRCR v2, 8-needle, 512K-1M | 73.8% | 72.5% | 41.3% |

The launch text explicitly identifies Sol's Coding Agent Index 80 result with max reasoning. Do not
present these scores as measurements of the operational Terra-medium or Luna-low assignments unless the
published harness confirms the same effort.

Source: <https://openai.com/index/gpt-5-6/>

## Review evidence

CodeRabbit reported the following when adding individual model lanes to its production ensemble:

- Sol: 69.7% actionable pass, +7.4 percentage points versus baseline, 31.6% actionable precision.
- Terra: 52.5% actionable pass, -8.6 percentage points versus baseline, 35.7% actionable precision.

The -8.6 value is not general "accuracy." It is the actionable-pass delta in that specific ensemble,
prompt, dataset, and filtering pipeline. The same report recommends Terra for cheaper triage and
first-pass review before escalation, not a universal ban on review.

Source: <https://www.coderabbit.ai/blog/gpt-5-6-sol-and-terra-benchmark>

## Effort decision

- Sol high is the High Risk baseline because official guidance describes high as appropriate for complex
  logic, assumptions, and edge cases.
- Sol xhigh is reserved for security and final gates with asymmetric miss cost. OpenAI's Codex Security
  quickstart explicitly recommends Sol xhigh for best scan quality.
- Terra medium matches its current default and Routine balance role.
- Luna low is a workflow policy for narrow Simple tasks, not a conclusion drawn from max-effort benchmark
  scores.
- Max is opt-in rather than a tier default.

Representative Orca evaluations should compare the selected setting with one adjacent lower setting before
changing a default.

## Smoke history

- 2026-07-21: `gpt-5.6-terra` medium booted and returned exit 0.
- 2026-07-21: `gpt-5.6-sol` high and xhigh booted and returned exit 0.
- `gpt-5.6-luna`: no recorded boot smoke. This remains an operational precondition.

Smoke success establishes availability and launch syntax only. It does not validate task quality.
