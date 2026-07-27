# agy Model Evidence

> verified_at: 2026-07-26

Load this file only to audit, change, or re-validate `../../models/agy.md`.

## Runtime behavior

The 2026-07-25 smoke found:

- `gemini-3.6-flash-high` booted and returned exit 0;
- headless tool calls without `--dangerously-skip-permissions` could be auto-denied while the process
  still exited successfully with no useful output;
- workspace-trust registration did not change that behavior for files inside the launch directory;
- paths outside the launch directory were not evaluated.

This is why the permission flag remains in the operational launch command. It is used only for workers
already isolated by the surrounding workflow.

## Model-generation decision

`gemini-3.6-flash` replaced the previous flash generation after it appeared in `agy models` on 2026-07-21.
The recorded public list price was $1.50 input and $7.50 output per 1M tokens, with $0.15 cached input.

Published and third-party reports collected during the decision recorded:

- OSWorld-Verified: 83.0%;
- Browser Use Benchmark: 68%;
- GDM-MRCR v2 at 128K: 91.8%;
- SWE-Bench Pro: 58.7%.

These results were not broken down by agy `low`, `medium`, and `high` effort. They support evaluating the
model generation for computer/browser execution, but they do not prove that medium is optimal. The
medium assignment comes from the narrower execution/reporting role and remains subject to representative
agent-e2e pilots.

Sources recorded during the 2026-07-21 to 2026-07-25 research included Google release material, Browser
Use, Artificial Analysis, OpenRouter, CodingFleet, and BuildFastWithAI. Because several are secondary
sources and URLs were not captured in the original decision, re-validation must replace this paragraph
with direct links before these numbers are used for a new routing change.

## Routing limits

The recorded 58.7% SWE-Bench Pro result was below the published Codex Terra and Sol results, so agy was not
promoted to Routine or High Risk code judgment. Cross-provider benchmark differences still limit that
comparison; it is a guardrail, not a precise quality ranking.

The Computer Use route favors agy because the Browser Use result is closer to Playwright agent e2e than a
general desktop benchmark. Long context alone is not a routing reason: context capacity and retrieval
scores are different properties, and no representative Orca long-log comparison is recorded.

## BrowserMCP and quota gaps

The intended agent-e2e setup is agy plus an accessibility-tree Playwright MCP. The repository still needs
a recorded connection smoke before treating that path as verified.

Public sources did not establish that the new model generation kept the previous quota and rate limits.
Track 429 and quota-skip frequency during pilots. `orca-evaluate` and `orca-task-runner` own runtime
fallback behavior.

## Re-validation

Re-check this file when `agy models`, launch flags, Google model availability, quota behavior, BrowserMCP
integration, or representative agent-e2e results change.
