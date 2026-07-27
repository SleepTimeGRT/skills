# Model Selection Evidence

> verified_at: 2026-07-27

Load this file only to audit, change, or re-validate `../model-selection.md`. Worker selection itself should
use the operational document.

## Ownership

- `../model-selection.md` owns the active tier-to-model/effort mapping.
- `models/*.md` references own provider facts, sources, smoke history, and unresolved validation.
- Workflow skills own orchestration, fallbacks, and evaluator freshness.

Evidence belongs in one reference only. Operational documents should link here instead of repeating it.

## Comparison rules

1. Provider effort labels are local controls, not a shared scale. Claude `xhigh` and Codex `xhigh` are not
   calibrated merely because they have the same name.
2. A benchmark supports a routing decision only when its task, harness, context size, effort, tools, and
   scoring are sufficiently close to the target workflow.
3. Context capacity is not retrieval quality. A 1M-token window cannot be compared numerically with an
   MRCR score.
4. Model-generation benchmark scores do not establish reviewer quality. Review needs precision, recall,
   severity, and filtering-cost measurements.
5. Use the lowest effort that passes representative workflow evaluations. Higher effort can change the
   failure mode rather than improve every metric monotonically.

## Current decisions

### High Risk

- Claude Opus 5 xhigh is the precision-oriented lane. Current external evidence suggests xhigh can improve
  actionable precision while reducing issue coverage; the mapping intentionally chooses that failure mode.
- Codex Sol starts at high. Raise it to xhigh for security and final gates where missed findings are
  materially more expensive than extra latency, usage, or false positives.
- These are independent provider decisions, not cross-provider effort calibration.

Confidence: medium. The provider direction is supported, but the exact Orca gate prompts do not yet have a
recorded high-versus-xhigh evaluation.

### Routine

- Claude Sonnet 5 high is the preferred primary generator.
- Codex Terra medium is the balanced implementation lane.
- Terra can perform bounded first-pass review triage, but its external ensemble result does not justify
  final high-risk judgment; escalate that judgment to Sol.

Confidence: medium-high for generation, medium for review routing.

### Simple

- Claude Haiku 4.5 omits effort because the provider does not expose it for that model.
- Codex Luna low and Gemini flash-low are restricted to clear, repeatable work.
- Luna remains gated on a recorded boot smoke.

Confidence: medium.

### Computer use and skeptical artifact checks

Gemini flash-medium is the primary execution lane; Sonnet 5 medium is the quota/provider fallback. This
axis does not own technical judgment and is not selected solely because inputs are long.

Confidence: medium-low until the repository records representative BrowserMCP and agent-e2e pilots.

## Re-verification triggers

Re-check the affected provider reference when any of these changes:

- provider model release, retirement, alias, or availability;
- CLI model catalog, supported effort, default effort, or launch flag;
- pricing, context, tool support, quota, or safety fallback;
- benchmark harness or published result used by a routing decision;
- Orca task shape, review prompt, or gate acceptance criteria;
- a smoke test contradicts the recorded runtime behavior.

A new release from one provider does not automatically invalidate facts for every provider, but it does
trigger re-evaluation of cross-provider preference.

## Decision log

### 2026-07-27 — separate operations from evidence

- Created this reference layer so routine agent selection does not load benchmark and research history.
- Changed Codex High Risk from unconditional Sol xhigh to high with conditional xhigh.
- Retained Terra medium and Luna low.
- Removed cross-provider effort-name calibration.
- Excluded Codex ultra from Orca workers because both layers would own delegation.
- Removed the long-context-capacity versus MRCR-score comparison.
- Reclassified Terra's CodeRabbit result as an actionable-pass delta in one ensemble harness, not general
  accuracy.

Provider evidence:

- [Codex](models/codex.md)
- [Claude Code](models/claude-code.md)
- [agy](models/agy.md)
