# Codex Model Evidence

> verified_at: 2026-08-04

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
balance, and Luna as the cost-sensitive high-volume tier. Published prices per 1M tokens, before and after
OpenAI's 2026-07-30 price cut (Luna -80%, Terra -20%, Sol unchanged but gained an API Fast mode):

| Model | Input (was → now) | Output (was → now) |
|---|---:|---:|
| Sol | $5.00 (unchanged) | $30.00 (unchanged) |
| Terra | $2.50 → $2.00 | $15.00 → $12.00 |
| Luna | $1.00 → $0.20 | $6.00 → $1.20 |

Luna carries a long-context surcharge not reflected in the table above: requests over 272K tokens are
billed at 2x the input rate and 1.5x the output rate — a second reason (beyond the MRCR cliff below) to
keep Luna's scope narrow-context.

Sources:

- <https://openai.com/index/gpt-5-6/>
- <https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6/>
- <https://x.com/OpenAI/status/2082878156483219672> (official price-cut announcement, 2026-07-30)

## Published benchmark context

The OpenAI launch report includes:

| Evaluation | Sol | Terra | Luna |
|---|---:|---:|---:|
| Artificial Analysis Coding Agent Index v1.1 | 80.0 | 77.4 | 74.6 |
| SWE-Bench Pro | 64.6% | 63.4% | 62.7% |
| MRCR v2, 8-needle, 256K-512K | 91.5% | 89.6% | 41.3% |
| MRCR v2, 8-needle, 512K-1M | 73.8% | 72.5% | 41.3% |

The launch text explicitly identifies Sol's Coding Agent Index 80 result with max reasoning. **Resolved
2026-08-04** (was previously unconfirmed in this file): secondary reporting independently confirms Terra's
77.4 and Luna's 74.6 are also each that model's max-effort score, not its operational default (Terra
medium, Luna's former low) — so none of the three scores in this row describe the assignments this
mapping actually runs at. The MRCR row is unconfirmed at a specific effort per model, but given Sol/Terra/
Luna's Coding Agent Index scores all originate from the same max-effort harness, the MRCR figures likely do
too — meaning Luna's 41.3% is plausibly its max-effort ceiling on long-context recall, not a floor that
higher effort would improve. This is why Luna's expanded scope (below) stays narrow-context even at max.

Sources: <https://openai.com/index/gpt-5-6/>, <https://artificialanalysis.ai/agents/coding-agents/> (Coding
Agent Index v1.1 chart, effort plotted per point on the cost axis — corroborates the max-effort attribution
visually: Luna's score climbs steeply from its low/medium points to the 74.6 max point, while Terra/Sol's
curves are comparatively flat across effort levels already at lower settings)

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
- **Luna moved from `low` to `max` (2026-08-04)**, reversing the prior policy. Rationale: Luna's own
  Coding Agent Index curve is far steeper across effort levels than Terra's or Sol's (see chart source
  above) — `low` was leaving most of the model's demonstrated capability (74.6 at max, competitive with
  Terra's 77.4) unused, and the 2026-07-30 price cut (Luna -80%) means `max` still costs less than
  `gpt-5.6-terra` at `high`. This is a benchmark-driven change, explicitly not the "workflow policy, not a
  benchmark conclusion" stance the previous version of this file took — that stance is superseded, not
  merely restated. The long-context caveat is unaffected: MRCR likely doesn't improve with effort (see
  above), so scope stays narrow-context regardless.
- Max is opt-in rather than a tier default **except for Luna**, where it is now the default per the above.

Representative Orca evaluations should compare the selected setting with one adjacent lower setting before
changing a default — **not applied for the Luna change above**: no operational low/medium/high run of
`gpt-5.6-luna` exists in this repository to compare against (zero dispatches recorded, see Smoke history),
so the comparison used instead was the independent published benchmark curve, not an internal adjacent-step
trial. The boot-smoke precondition below still gates the first real dispatch.

## Smoke history

- 2026-07-21: `gpt-5.6-terra` medium booted and returned exit 0.
- 2026-07-21: `gpt-5.6-sol` high and xhigh booted and returned exit 0.
- `gpt-5.6-luna`: no recorded boot smoke at any effort (confirmed 2026-08-04 by grepping
  `assignments*.jsonl` for `gpt-5.6-luna`: zero matches). This remains an operational precondition — smoke
  at `max`, the effort this mapping now uses, not the former `low`.

Smoke success establishes availability and launch syntax only. It does not validate task quality.
