# Claude Code Model Evidence

> verified_at: 2026-07-26

Load this file only to audit, change, or re-validate `../../models/claude-code.md`.

## Release and role decision

The current mapping uses:

- Opus 5 for coordinator and High Risk judgment;
- Sonnet 5 high for Routine implementation;
- Haiku 4.5 for Simple mechanical work;
- no Fable 5.

The 2026-07-26 decision retired Fable 5 after Anthropic's Opus 5 release material reported comparable or
better results on the cited OSWorld 2.0 and CursorBench 3.2 results at a lower published price. This is a
routing decision, not a claim that Opus dominates Fable on every workflow.

Sources:

- <https://www.anthropic.com/news/claude-opus-5>
- <https://platform.claude.com/docs/en/about-claude/models/overview>

## Effort semantics

Claude Code exposes `low`, `medium`, `high`, `xhigh`, and `max` for the selected current models, subject to
model support. Haiku 4.5 does not support the effort parameter and must omit it.

Anthropic's effort guidance says Opus 5 defaults to high and recommends a fresh effort sweep rather than
carrying a previous model's setting forward. Its typical-use guidance associates high with difficult
coding and xhigh with longer agentic/coding work. Max is for frontier problems where extra reasoning cost
is acceptable.

The Orca Opus xhigh assignment is a precision-oriented policy choice. External CodeRabbit results found
that Opus 5 xhigh improved actionable precision but reduced known-issue coverage and increased the broader
noise tail. Therefore xhigh is not described as uniformly better. Orca still lacks a representative
high-versus-xhigh evaluation for its contract and diff-review gates.

Sources:

- <https://platform.claude.com/docs/en/build-with-claude/effort>
- <https://www.coderabbit.ai/blog/opus-5-model-review>

## Automatic model fallback

Claude Code documentation reviewed on 2026-07-26 described category-based automatic fallback:

- Opus 5 plus a cybersecurity classification reruns on Opus 4.8 and emits a notice.
- Opus 5 plus a biology classification has no fallback and may refuse.
- Fable 5 plus a biology classification can move the session to Opus 5, where a later flagged request may
  still refuse.
- Classification can be triggered by the initial workspace context.
- JSON output reports actual usage in `modelUsage`.

The category-specific behavior requires Claude Code 2.1.219 or newer, which is also the recorded minimum
for selecting Opus 5 in the model picker.

Source: <https://code.claude.com/docs/en/model-config>

## Advisor tool

Claude Code advisor selects a model but exposes no advisor effort setting through `/advisor`, `--advisor`,
or `advisorModel`. Usage reports the advisor model and tokens, not a verifiable advisor effort. Therefore
the operational document does not call the advisor an "xhigh backend."

Other constraints recorded on 2026-07-26:

- `--advisor <model>` is documented even though it is absent from `claude --help`.
- The advisor must be at least as capable as the main model under Claude's pairing rules.
- Claude Code advisor availability depends on the provider surface.
- It is intended for multi-step work where planning quality matters, not every short request.

Sources:

- <https://code.claude.com/docs/en/advisor>
- <https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool>

## Re-validation

Re-check this file on a new Claude release, Claude Code model-catalog change, advisor change, fallback
change, or when an Orca high/xhigh pilot produces workflow-specific evidence.
