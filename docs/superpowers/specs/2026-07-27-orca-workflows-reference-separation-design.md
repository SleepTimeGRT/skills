# Orca Workflows Reference Separation Design

**Date:** 2026-07-27

**Scope:** `orca-workflows/` model-selection guidance and the correctness fixes found during its review

## 1. Purpose

The model-selection documents currently mix two jobs:

1. instructions an agent needs every time it selects and launches a worker;
2. benchmark results, source notes, caveats, and the reasoning behind those instructions.

Loading both jobs on every selection wastes context, while deleting the evidence makes later reviews repeat
the same research without a durable record. Separate the operational guidance from its evidence using
progressive disclosure.

## 2. Document Structure

Keep the existing operational entry points:

- `orca-workflows/model-selection.md`
- `orca-workflows/models/codex.md`
- `orca-workflows/models/claude-code.md`
- `orca-workflows/models/agy.md`

Add evidence references:

- `orca-workflows/references/model-selection.md`
- `orca-workflows/references/models/codex.md`
- `orca-workflows/references/models/claude-code.md`
- `orca-workflows/references/models/agy.md`

`references/model-selection.md` owns cross-provider policy, comparison limits, tier decisions, and the
decision log. Each provider reference owns source-backed model facts, benchmark conditions, effort
semantics, pricing, runtime caveats, and unresolved validation work for that provider.

Operational documents link directly to the one relevant reference and tell agents to load it only when
auditing, changing, or re-validating the mapping. Evidence is not duplicated between operational and
reference documents.

## 3. Operational Content Boundary

Operational documents retain only:

- task classification and provider preference;
- the current tier-to-model/effort mapping;
- concise escalation rules;
- exact launch syntax and safety-critical launch preconditions;
- runtime checks required for a trustworthy result;
- a short reference-loading rule.

Move the following to references:

- benchmark scores and harness caveats;
- pricing and release-history discussion;
- comparisons with models from other providers;
- explanations of why a mapping was chosen;
- rejected alternatives and provisional assumptions;
- `verified_at` evidence and re-verification triggers;
- smoke-test history, while retaining an operational warning when a model is not yet safe to launch.

## 4. Model and Effort Corrections

The Codex operational guidance will use current CLI model-catalog semantics:

- Sol and Terra support `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`;
- Luna supports `low`, `medium`, `high`, `xhigh`, and `max`;
- `minimal` is not documented for the GPT-5.6 Codex model entries;
- API-only reasoning names are not presented as CLI values;
- `ultra` is explicitly excluded from Orca worker launch because it adds automatic delegation on top of
  Orca's explicit orchestration.

The default mapping becomes:

- High Risk Codex: Sol `high`; raise to `xhigh` for security work and final gates where missed findings are
  materially more expensive than latency or usage;
- Routine Codex: Terra `medium`;
- Simple Codex: Luna `low`, after the existing boot smoke precondition.

`max` remains an explicit opt-in for the hardest single-agent problems, not a tier default. Effort labels
are never calibrated across providers by name; each provider mapping requires provider-specific evidence.

Claude High Risk keeps its current precision-oriented `xhigh` policy where the workflow specifically wants
that failure mode, but the operational document labels this a policy choice rather than a universally
better effort. The reference records the `high` versus `xhigh` trade-off and the missing workflow-specific
evaluation.

## 5. Correctness Fixes in the Same Change

Apply the previously identified documentation fixes:

- describe pinned model/effort as an Orca invariant, not an immutable runtime fact;
- make re-verification triggers cover every provider and CLI catalog change;
- remove the context-window-capacity versus MRCR-score comparison;
- distinguish Terra's CodeRabbit actionable-pass delta from general accuracy and allow bounded triage use;
- clarify the Routine Codex review path;
- describe `workspace-write` and `never` approval semantics accurately;
- use native GitHub issue types and sub-issues first, with legacy labels/body parsing only as a fallback;
- do not treat `Refs` as a dependency edge;
- require selection changes when adding a Linear adapter;
- replace the Claude-specific Atlassian MCP namespace with capability-level adapter language;
- generate spawn-failure JSONL with correct JSON escaping;
- make closing-keyword matching require an exact issue identifier.

## 6. Validation

Validation is documentation-focused and read-only:

1. check every operational document has a valid direct reference link;
2. search operational model documents for benchmark, pricing, and long-form research text that should have
   moved;
3. search for stale claims and values: `minimal`, `high = cost floor`, cross-provider `xhigh` calibration,
   “no native GitHub hierarchy,” `Refs` as dependency, and Claude-specific Atlassian namespaces;
4. compare all tier/model/effort rows across `model-selection.md` and provider documents;
5. render or otherwise inspect Markdown links and tables;
6. run repository-provided documentation or skill validation commands if present.

No skill deployment is part of this change. `orca-workflows/` follows the main-checkout symlink path and
does not use `scripts/deploy-skills.sh`.
